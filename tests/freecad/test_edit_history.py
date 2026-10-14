"""An editing session's undo steps, driven at the App level: each edit one
named step, Undo and Redo read back into the session, the floor, and Close.
``tests/freecad_view/test_undo_in_the_editor.py`` runs Undo and Redo
through ``Std_Undo`` and ``Std_Redo`` with the 3D view up."""

from collections.abc import Iterator, Mapping
from typing import Protocol, cast

import FreeCAD
import pytest

from freecad.Shelving import properties
from freecad.Shelving.container import read_container
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import Basis, Bay, Board, Division, Region
from freecad.Shelving.editor.session import PROBE_PROPERTY, EditFailure, Session
from freecad.Shelving.unit_ops import create_unit
from tests.freecad_materials import library_material

_Boards = tuple[tuple[str, float, float, float, float, float, float], ...]
# Every solved space, region ids aside: a rescan mints fresh ones.
_Spaces = list[tuple[float, ...]]


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


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


def _spaces(spaces: Mapping[str, Space]) -> _Spaces:
    # Rounded: a rescan solves from measured boards, a few ulps off.
    return sorted(
        tuple(
            round(value_mm, 6)
            for value_mm in (
                space.origin.x_mm,
                space.origin.y_mm,
                space.origin.z_mm,
                space.size.x_mm,
                space.size.y_mm,
                space.size.z_mm,
            )
        )
        for space in spaces.values()
    )


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


def _record(session: Session) -> tuple[_Spaces, _Boards]:
    return _spaces(session.spaces), _boards(session.container)


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
        assert isinstance(session.set_locks([lower, upper], locked=True), EditFailure)
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
        expected = [
            "Delete Objects",
            "Add Divider",
            "Move Board",
            "Resize Unit",
            "Unlock Openings",
            "Change What a Size Measures",
            "Set Size",
            "Add Shelf",
            *before,
        ]
        assert doc.UndoNames == expected
    finally:
        session.close()
    # Close leaves every step where it is and adds none.
    assert doc.UndoNames == expected


def test_a_drag_that_moves_nothing_leaves_no_step(doc: FreeCAD.Document) -> None:
    session = _opened(doc)
    try:
        shelf = _add_shelf(session)
        names = list(doc.UndoNames)
        assert session.begin_drag(shelf, session.spaces[shelf].origin) is None
        session.end_drag()
        assert doc.UndoNames == names
    finally:
        session.close()


def test_undo_and_redo_step_one_edit_at_a_time(doc: FreeCAD.Document) -> None:
    session = _opened(doc)
    try:
        states = [_record(session)]
        _add_shelf(session)
        states.append(_record(session))
        lower = _bay_ids(session.unit.root)[0]
        session.select(lower)
        for size_mm in (250.0, 300.0):
            assert session.set_size(size_mm) is None
            states.append(_record(session))
        for number, expected in enumerate(reversed(states[:-1])):
            _undo(session)
            assert _record(session) == expected
            if number < 2:
                # A rescan gives the bay a fresh id; it stays selected.
                selected = session.selected_id
                assert selected is not None
                assert session.spaces[selected].origin.z_mm == pytest.approx(18.0)
        assert session.selected_id is None
        for expected in states[1:]:
            _redo(session)
            assert _record(session) == expected
    finally:
        session.close()


def test_undo_past_the_first_edit_goes_on_into_the_document(
    doc: FreeCAD.Document,
) -> None:
    """As in Sketcher's edit mode: past the session's first edit lies the
    document's own history, here the step that created the unit, after
    which there is no unit to read."""
    opening = _boards(_container(doc))
    session = _opened(doc)
    try:
        _add_shelf(session)
        _undo(session)
        assert _boards(session.container) == opening
        assert not session.lost
        _undo(session)
        assert doc.getObject("ShelvingUnit") is None
        assert session.lost
        doc.redo()
        assert _boards(_container(doc)) == opening
    finally:
        session.close()


def test_close_keeps_the_steps_and_removes_the_probe(doc: FreeCAD.Document) -> None:
    container = _container(doc)
    before_names = list(doc.UndoNames)
    before_boards = _boards(container)
    session = _opened(doc)
    _add_shelf(session)
    _add_shelf(session)
    two_shelves = _boards(container)
    _undo(session)
    one_shelf = _boards(container)
    session.close()
    assert doc.getObject("ShelvingDimensionProbe") is None
    assert _boards(container) == one_shelf
    assert doc.UndoNames == ["Add Shelf", *before_names]
    assert doc.RedoNames == ["Add Shelf"]
    doc.redo()
    assert _boards(container) == two_shelves
    doc.undo()
    doc.undo()
    assert _boards(container) == before_boards


def _undone_step_elsewhere(doc: FreeCAD.Document) -> None:
    """Leave one step from before the session in the Redo list."""
    other = cast("_BoxFeature", doc.addObject("Part::Box", "Elsewhere"))
    doc.openTransaction("Move it")
    other.Length = 20.0
    doc.commitTransaction()
    doc.undo()


def test_a_session_without_edits_leaves_both_lists_as_it_found_them(
    doc: FreeCAD.Document,
) -> None:
    _undone_step_elsewhere(doc)
    before_undo, before_redo = list(doc.UndoNames), list(doc.RedoNames)
    assert before_redo == ["Move it"]
    session = _opened(doc)
    session.close()
    assert doc.UndoNames == before_undo
    assert doc.RedoNames == before_redo
    assert doc.getObject("ShelvingDimensionProbe") is None


def test_a_click_or_a_refused_edit_leaves_both_lists_as_it_found_them(
    doc: FreeCAD.Document,
) -> None:
    """A press on a board begins a drag that never moves, and a refused edit
    writes nothing: neither is an edit."""
    first = _opened(doc)
    shelf = _add_shelf(first)
    first.close()
    _undone_step_elsewhere(doc)
    before_undo, before_redo = list(doc.UndoNames), list(doc.RedoNames)
    session = _opened(doc)
    assert session.begin_drag(shelf, session.spaces[shelf].origin) is None
    session.end_drag()
    session.select(_bay_ids(session.unit.root)[0])
    assert isinstance(session.set_size(5000.0), EditFailure)
    session.close()
    assert doc.UndoNames == before_undo
    assert doc.RedoNames == before_redo


def test_a_probe_some_step_changed_goes_in_a_step_of_its_own(
    doc: FreeCAD.Document,
) -> None:
    """Removing it outside any step would leave that step naming a
    destroyed object."""
    session = _opened(doc)
    probe = session.probe
    assert probe is not None
    doc.openTransaction("Bind an expression")
    probe.setExpression(PROBE_PROPERTY, "20 mm")
    doc.commitTransaction()
    session.close()
    assert doc.getObject("ShelvingDimensionProbe") is None
    assert doc.UndoNames[0] == "Remove Shelving Dimension"


def test_an_added_shelf_keeps_its_stock_through_undo_redo_and_close(
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
    session.close()
    assert shelf_material() == "Wood"


def test_an_undo_before_a_drag_moves_ends_the_drag(doc: FreeCAD.Document) -> None:
    """The drag's step has nothing in it yet, so FreeCAD commits nothing and
    undoes the step below."""
    session = _opened(doc)
    try:
        shelf = _add_shelf(session)
        grab_mm = session.spaces[shelf].origin
        assert session.begin_drag(shelf, grab_mm) is None
        _undo(session)
        assert not session.dragging
        assert doc.RedoNames == ["Add Shelf"]
        assert shelf not in session.spaces
        failure = session.drag_to(grab_mm)
        assert failure is not None and failure.message == "no board is being dragged"
        session.end_drag()
        assert doc.RedoNames == ["Add Shelf"]
    finally:
        session.close()


def test_a_selected_board_stays_selected_through_undo(doc: FreeCAD.Document) -> None:
    session = _opened(doc)
    try:
        shelf = _add_shelf(session)
        session.select(shelf)
        assert session.resize("height", 950.0) is None
        _undo(session)
        assert session.selected_id == shelf
    finally:
        session.close()


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
        assert _record(session) == before
        assert isinstance(session.drag_to(pointer_mm), EditFailure)
        session.end_drag()
        _redo(session)
        assert session.spaces[shelf].origin.z_mm == pytest.approx(grab_mm.z_mm + 20.0)
    finally:
        session.close()
