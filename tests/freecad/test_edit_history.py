"""An editing session's undo steps, driven at the App level: each edit one
named step, Undo and Redo read back into the session, the floor, the fold
near FreeCAD's history limit, steps the session did not make, and OK and
Cancel. ``tests/freecad_view/test_undo_in_the_editor.py`` runs Undo and
Redo through ``Std_Undo`` and ``Std_Redo`` with the 3D view up."""

from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import pytest

from freecad.Shelving import properties
from freecad.Shelving.container import read_container
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import Basis, Bay, Board, Division, Region
from freecad.Shelving.editor.history import (
    FLOOR_MESSAGE,
    NOT_FOLDED_MESSAGE,
    SESSION_STEP,
)
from freecad.Shelving.editor.session import EditFailure, Session
from freecad.Shelving.unit_ops import create_unit
from tests.freecad_materials import library_material

_Boards = tuple[tuple[str, float, float, float, float, float, float], ...]
_Spaces = dict[str, Space]


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


class _Labeled(Protocol):
    Label: str


def _boards(container: FreeCAD.DocumentObject) -> _Boards:
    """Every board's name, size and position."""
    boxes, _skipped, _record = read_container(container)
    doc = container.Document
    found: list[tuple[str, float, float, float, float, float, float]] = []
    for name in sorted(box.name for box in boxes):
        obj = cast("_BoxFeature", doc.getObject(name))
        base = obj.Placement.Base
        found.append((name, obj.Length, obj.Width, obj.Height, base.x, base.y, base.z))
    return tuple(found)


def _bay_ids(region: Region) -> list[str]:
    if isinstance(region, Bay):
        return [region.id]
    if not isinstance(region, Division):
        return []
    return [
        bay_id
        for item in region.items
        if not isinstance(item, Board)
        for bay_id in _bay_ids(item)
    ]


def _board_ids(region: Region) -> set[str]:
    if not isinstance(region, Division):
        return set()
    found: set[str] = set()
    for item in region.items:
        found |= {item.id} if isinstance(item, Board) else _board_ids(item)
    return found


class _Messages:
    """What a session tells its panel after an Undo or Redo."""

    def __init__(self, session: Session) -> None:
        self.seen: list[str] = []
        session.on_change = self._record

    def _record(self, failure: EditFailure | None) -> None:
        if failure is not None:
            self.seen.append(failure.message)


@pytest.fixture
def doc() -> Iterator[FreeCAD.Document]:
    """A document holding a fresh unit, made in one step of its own."""
    document = FreeCAD.newDocument("edit_history")
    document.UndoMode = 1
    document.openTransaction("Create Shelving Unit")
    create_unit(document)
    document.commitTransaction()
    document.recompute()
    yield document
    FreeCAD.closeDocument(document.Name)


def _container(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    container = doc.getObject("ShelvingUnit")
    assert container is not None
    return container


def _opened(doc: FreeCAD.Document) -> Session:
    session = Session(_container(doc))
    session.open()
    return session


def _add_shelf(session: Session) -> str:
    """Split the session's first bay with a shelf and return its id."""
    before = _board_ids(session.unit.root)
    session.select(_bay_ids(session.unit.root)[0])
    assert session.split("vertical") is None
    (shelf,) = _board_ids(session.unit.root) - before
    return shelf


def _undo(session: Session) -> None:
    session.container.Document.undo()
    session.settle()


def _redo(session: Session) -> None:
    session.container.Document.redo()
    session.settle()


def _same_state(session: Session, spaces: _Spaces, boards: _Boards) -> bool:
    return dict(session.spaces) == spaces and _boards(session.container) == boards


def _record(session: Session) -> tuple[_Spaces, _Boards]:
    return dict(session.spaces), _boards(session.container)


def test_each_edit_is_one_step_named_for_it(doc: FreeCAD.Document) -> None:
    container = _container(doc)
    panel = cast("_BoxFeature", doc.addObject("Part::Box", "HandAdded"))
    panel.Length, panel.Width, panel.Height = 400.0, 5.0, 400.0
    cast("FreeCAD.DocumentObjectGroup", container).addObject(
        cast("FreeCAD.DocumentObject", panel)
    )
    doc.recompute()
    before = list(doc.UndoNames)
    session = _opened(doc)
    try:
        shelf = _add_shelf(session)
        lower, upper = _bay_ids(session.unit.root)
        session.select(lower)
        assert session.set_size(250.0) is None
        names = list(doc.UndoNames)
        assert isinstance(session.set_size(5000.0), EditFailure)
        assert doc.UndoNames == names
        assert session.set_basis(Basis.WITH_NEXT) is None
        assert session.set_locks([lower], locked=False) is None
        assert session.resize("height", 950.0) is None
        grab_mm = session.spaces[shelf].origin
        assert session.begin_drag(shelf, grab_mm) is None
        for up_mm in (5.0, 10.0, 15.0):
            pointer_mm = Vec3(grab_mm.x_mm, grab_mm.y_mm, grab_mm.z_mm + up_mm)
            assert session.drag_to(pointer_mm) is None
        session.end_drag()
        session.select(upper)
        assert session.split("horizontal") is None
        assert session.delete_untagged(["HandAdded"]) is None
        assert doc.UndoNames == [
            "Delete Objects",
            "Add Divider",
            "Move Board",
            "Resize Unit",
            "Unlock Openings",
            "Change What a Size Measures",
            "Set Size",
            "Add Shelf",
            SESSION_STEP,
            *before,
        ]
    finally:
        session.cancel()


def test_a_drag_that_moves_nothing_leaves_no_step(doc: FreeCAD.Document) -> None:
    session = _opened(doc)
    try:
        shelf = _add_shelf(session)
        names = list(doc.UndoNames)
        assert session.begin_drag(shelf, session.spaces[shelf].origin) is None
        session.end_drag()
        assert doc.UndoNames == names
    finally:
        session.cancel()


def test_undo_and_redo_step_one_edit_at_a_time(doc: FreeCAD.Document) -> None:
    session = _opened(doc)
    messages = _Messages(session)
    try:
        states = [_record(session)]
        _add_shelf(session)
        states.append(_record(session))
        lower = _bay_ids(session.unit.root)[0]
        session.select(lower)
        assert session.set_size(250.0) is None
        states.append(_record(session))
        assert session.set_size(300.0) is None
        states.append(_record(session))
        for number, (spaces, boards) in enumerate(reversed(states[:-1])):
            _undo(session)
            assert _same_state(session, spaces, boards)
            if number == 0:
                # A selected node that still exists stays selected.
                assert session.selected_id == lower
        assert messages.seen == []
        assert session.selected_id is None
        for spaces, boards in states[1:]:
            _redo(session)
            assert _same_state(session, spaces, boards)
    finally:
        session.cancel()


def test_undo_past_the_first_edit_stops_at_the_start(doc: FreeCAD.Document) -> None:
    opening = _boards(_container(doc))
    session = _opened(doc)
    messages = _Messages(session)
    try:
        _add_shelf(session)
        first = _record(session)
        _undo(session)
        assert _boards(session.container) == opening
        assert messages.seen == []
        _undo(session)
        assert _boards(session.container) == opening
        assert messages.seen == [FLOOR_MESSAGE]
        assert session.probe is not None
        _redo(session)
        assert _same_state(session, *first)
    finally:
        session.cancel()


def test_ok_leaves_one_step_that_undoes_the_session(doc: FreeCAD.Document) -> None:
    container = _container(doc)
    before_names = list(doc.UndoNames)
    before_boards = _boards(container)
    session = _opened(doc)
    _add_shelf(session)
    session.select(_bay_ids(session.unit.root)[0])
    assert session.set_size(250.0) is None
    final = _boards(container)
    assert session.commit() is None
    assert doc.UndoNames == [SESSION_STEP, *before_names]
    assert doc.RedoNames == []
    assert _boards(container) == final
    assert doc.getObject("ShelvingDimensionProbe") is None
    doc.undo()
    assert _boards(container) == before_boards


def test_ok_with_no_edits_adds_no_step(doc: FreeCAD.Document) -> None:
    before_names = list(doc.UndoNames)
    session = _opened(doc)
    assert session.commit() is None
    assert doc.UndoNames == before_names
    assert doc.RedoNames == []
    assert doc.getObject("ShelvingDimensionProbe") is None


def test_cancel_puts_everything_back(doc: FreeCAD.Document) -> None:
    container = _container(doc)
    before_names = list(doc.UndoNames)
    before_boards = _boards(container)
    before_count = len(doc.Objects)
    session = _opened(doc)
    _add_shelf(session)
    _add_shelf(session)
    _undo(session)
    assert session.cancel() is None
    assert _boards(container) == before_boards
    assert len(doc.Objects) == before_count
    assert doc.UndoNames == before_names
    assert doc.RedoNames == []


def test_an_added_shelf_keeps_its_stock_through_undo_redo_and_ok(
    doc: FreeCAD.Document,
) -> None:
    bottom = doc.getObject("bottom")
    assert bottom is not None
    cast("properties._MaterialObject", bottom).ShapeMaterial = library_material("Wood")
    doc.recompute()
    session = _opened(doc)
    shelf = _add_shelf(session)

    def shelf_material() -> str | None:
        obj = doc.getObject(shelf)
        assert obj is not None
        return properties.read_material_name(obj)

    assert shelf_material() == "Wood"
    session.select(_bay_ids(session.unit.root)[0])
    assert session.set_size(250.0) is None
    _undo(session)
    _redo(session)
    assert shelf_material() == "Wood"
    assert session.commit() is None
    assert shelf_material() == "Wood"


def _foreign_change(doc: FreeCAD.Document, label: str) -> None:
    other = doc.getObject("Elsewhere")
    assert other is not None
    doc.openTransaction("Relabel")
    cast("_Labeled", other).Label = label
    doc.commitTransaction()


@pytest.mark.parametrize("keep", [True, False])
def test_a_step_the_session_did_not_make_is_never_undone(
    doc: FreeCAD.Document, keep: bool
) -> None:
    container = _container(doc)
    doc.addObject("Part::Box", "Elsewhere")
    doc.recompute()
    before_boards = _boards(container)
    session = _opened(doc)
    _add_shelf(session)
    _foreign_change(doc, "changed during the session")
    session.settle()
    _add_shelf(session)
    final = _boards(container)
    message = session.commit() if keep else session.cancel()
    assert message == NOT_FOLDED_MESSAGE
    assert _boards(container) == (final if keep else before_boards)
    other = cast("_Labeled", doc.getObject("Elsewhere"))
    assert other.Label == "changed during the session"
    assert doc.getObject("ShelvingDimensionProbe") is None


def test_near_the_history_limit_only_the_oldest_steps_fold(
    doc: FreeCAD.Document,
) -> None:
    """With FreeCAD's history at its default 20 steps and ten unrelated ones
    already in it, a session of 30 edits keeps its newest steps one edit at
    a time, folds the oldest into its floor, and still cancels to where it
    started."""
    container = _container(doc)
    doc.addObject("Part::Box", "Elsewhere")
    for number in range(10):
        _foreign_change(doc, f"before the session {number}")
    before_names = list(doc.UndoNames)
    before_boards = _boards(container)
    session = _opened(doc)
    messages = _Messages(session)
    _add_shelf(session)
    lower = _bay_ids(session.unit.root)[0]
    session.select(lower)
    states = [_record(session)]
    for number in range(29):
        assert session.set_size(200.0 + number) is None
        states.append(_record(session))
    assert doc.UndoNames[0] == "Set Size"
    held = 0
    while not messages.seen:
        expected = states[-2 - held]
        _undo(session)
        if messages.seen:
            break
        assert _same_state(session, *expected), held
        held += 1
    assert messages.seen == [FLOOR_MESSAGE]
    assert held >= 9
    floor = _record(session)
    _undo(session)
    assert _same_state(session, *floor)
    assert session.cancel() is None
    assert _boards(container) == before_boards
    remaining = list(doc.UndoNames)
    assert remaining == before_names[: len(remaining)]


def test_ok_near_the_history_limit_leaves_one_step(doc: FreeCAD.Document) -> None:
    container = _container(doc)
    session = _opened(doc)
    _add_shelf(session)
    session.select(_bay_ids(session.unit.root)[0])
    for number in range(30):
        assert session.set_size(200.0 + number) is None
    final = _boards(container)
    assert session.commit() is None
    assert doc.UndoNames[0] == SESSION_STEP
    assert SESSION_STEP not in doc.UndoNames[1:]
    assert _boards(container) == final


def test_an_undo_during_a_drag_ends_the_drag(doc: FreeCAD.Document) -> None:
    """FreeCAD commits the drag's open step before undoing it."""
    session = _opened(doc)
    try:
        shelf = _add_shelf(session)
        before = _record(session)
        grab_mm = session.spaces[shelf].origin
        assert session.begin_drag(shelf, grab_mm) is None
        pointer_mm = Vec3(grab_mm.x_mm, grab_mm.y_mm, grab_mm.z_mm + 20.0)
        assert session.drag_to(pointer_mm) is None
        _undo(session)
        assert not session.dragging
        assert _same_state(session, *before)
        assert isinstance(session.drag_to(pointer_mm), EditFailure)
        session.end_drag()
        _redo(session)
        assert session.spaces[shelf].origin.z_mm == pytest.approx(grab_mm.z_mm + 20.0)
    finally:
        session.cancel()
