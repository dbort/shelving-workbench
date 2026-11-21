"""Locks, Equal and even spacing through the editor's session against a
real FreeCAD document: what opening a unit does with its stored constraints
and what it reports, creating them, and deleting them as undo steps."""

import json
from collections.abc import Callable, Iterator
from typing import Protocol, cast

import FreeCAD
import pytest

from freecad.Shelving import properties, refusals
from freecad.Shelving.container import write_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Constraint,
    ConstraintId,
    Division,
    Equal,
    EvenSpacing,
    Lock,
    RunEnd,
    Unit,
    constraint_regions,
    region_lock,
)
from freecad.Shelving.editor.session import (
    EditFailure,
    EditWarning,
    Session,
)

_T_MM = 18.0
_BAY_MM = 288.0


class _Placeable(Protocol):
    Placement: FreeCAD.Placement


class _BoxFeature(_Placeable, Protocol):
    Length: float
    Width: float
    Height: float


class _Group(Protocol):
    def addObject(self, obj: FreeCAD.DocumentObject, /) -> None: ...


@pytest.fixture
def notified(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every warning sent to the Notification Area."""
    messages: list[str] = []

    def record(_notifier: str, message: str) -> None:
        messages.append(message)

    monkeypatch.setattr(refusals, "_print_user_warning", record)
    return messages


@pytest.fixture
def doc() -> Iterator[FreeCAD.Document]:
    document = FreeCAD.newDocument("constraint_session")
    yield document
    FreeCAD.closeDocument(document.Name)


class _Column:
    """A closed 936 mm carcass whose column holds bays A, B and C, 288 mm
    each, behind ``shelf_a`` and ``shelf_b``."""

    def __init__(self) -> None:
        self.a = Bay(size_mm=_BAY_MM)
        self.b = Bay(size_mm=_BAY_MM)
        self.c = Bay(size_mm=_BAY_MM)
        self.column = Division(
            axis=Axis.Z,
            items=[
                self.a,
                Board(thickness_mm=_T_MM, role="shelf_a"),
                self.b,
                Board(thickness_mm=_T_MM, role="shelf_b"),
                self.c,
            ],
            size_mm=564.0,
        )

    def unit(self, *constraints: Constraint) -> Unit:
        return Unit(
            size_mm=Vec3(600.0, 300.0, 936.0),
            root=Division(
                axis=Axis.Z,
                items=[
                    Board(thickness_mm=_T_MM, role="bottom"),
                    Division(
                        axis=Axis.X,
                        items=[
                            Board(thickness_mm=_T_MM, role="left_side"),
                            self.column,
                            Board(thickness_mm=_T_MM, role="right_side"),
                        ],
                        size_mm=900.0,
                    ),
                    Board(thickness_mm=_T_MM, role="top"),
                ],
            ),
            depth_axis=Axis.Y,
            front_at_min=None,
            constraints=constraints,
        )


def _written(doc: FreeCAD.Document, *constraints: Constraint) -> FreeCAD.DocumentObject:
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    write_container(container, _COLUMN.unit(*constraints))
    doc.recompute()
    return container


_COLUMN = _Column()


def _equal(first: Bay, second: Bay, *, active: bool = True) -> Equal:
    return Equal(region_ids=(first.id, second.id), active=active)


def _move_up(doc: FreeCAD.Document, name: str, up_mm: float) -> None:
    board = cast("_Placeable", doc.getObject(name))
    placement = board.Placement
    placement.Base.z += up_mm
    board.Placement = placement
    doc.recompute()


def _z_mm(doc: FreeCAD.Document, name: str) -> float:
    return cast("_Placeable", doc.getObject(name)).Placement.Base.z


def _heights_mm(doc: FreeCAD.Document) -> tuple[float, float, float]:
    """A, B and C from where the shelves stand."""
    shelf_a = _z_mm(doc, "shelf_a")
    shelf_b = _z_mm(doc, "shelf_b")
    top = _z_mm(doc, "top")
    return (shelf_a - _T_MM, shelf_b - shelf_a - _T_MM, top - shelf_b - _T_MM)


def _snapshot(doc: FreeCAD.Document) -> dict[str, tuple[float, float, float]]:
    found: dict[str, tuple[float, float, float]] = {}
    for obj in doc.Objects:
        if obj.TypeId == "Part::Box":
            base = cast("_Placeable", obj).Placement.Base
            found[obj.Name] = (base.x, base.y, base.z)
    return found


def _opened(container: FreeCAD.DocumentObject) -> Session:
    session = Session(container)
    session.open()
    return session


def _others(session: Session) -> tuple[Constraint, ...]:
    """The session's constraints other than its Locks, in its order."""
    return tuple(c for c in session.constraints if not isinstance(c, Lock))


def _lock_id(session: Session, region_id: str) -> ConstraintId:
    """The id of the Lock on the region named ``region_id``."""
    found = region_lock(session.unit, region_id)
    assert found is not None
    return found.id


def _stored(container: FreeCAD.DocumentObject) -> list[dict[str, object]]:
    text = properties.read_container_rules_json(container)
    assert text is not None
    constraints: list[dict[str, object]] = json.loads(text)["constraints"]
    return constraints


def test_an_equal_the_boards_miss_comes_in_deactivated_and_stays_so(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.b))
    _move_up(doc, "shelf_a", 20.0)
    session = _opened(container)
    try:
        (equal,) = session.constraints
        assert not equal.active
        assert session.open_report.deactivated == (equal.id,)
        assert len(notified) == 1
        assert "deactivated" in notified[0]
        a_mm, b_mm, _c_mm = _heights_mm(doc)
        assert a_mm - b_mm == pytest.approx(40.0)
        assert session.resize("width", 700.0) is None
        doc.recompute()
        a_mm, b_mm, _c_mm = _heights_mm(doc)
        assert a_mm - b_mm == pytest.approx(40.0)
        assert [entry["active"] for entry in _stored(container)] == [False]
    finally:
        session.close()


def test_an_equal_missed_within_the_clearance_is_met_by_the_next_edit(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.b))
    _move_up(doc, "shelf_a", 1.0)
    before = _snapshot(doc)
    session = _opened(container)
    try:
        (equal,) = session.constraints
        assert equal.active
        assert session.open_report.empty
        assert notified == []
        doc.recompute()
        assert _snapshot(doc) == before
        assert session.resize("width", 700.0) is None
        doc.recompute()
        a_mm, b_mm, _c_mm = _heights_mm(doc)
        assert a_mm == pytest.approx(b_mm)
    finally:
        session.close()


def test_a_stored_deactivated_equal_stays_deactivated_when_met(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.b, active=False))
    session = _opened(container)
    try:
        (equal,) = session.constraints
        assert not equal.active
        assert session.open_report.empty
        assert notified == []
    finally:
        session.close()


def test_an_equal_beside_a_board_deleted_by_hand_is_dropped(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(
        doc, _equal(_COLUMN.a, _COLUMN.c), _equal(_COLUMN.b, _COLUMN.c)
    )
    doc.removeObject("shelf_a")
    doc.recompute()
    session = _opened(container)
    try:
        assert session.constraints == ()
        assert session.open_report.dropped == 2
        assert len(notified) == 1
        assert "removed" in notified[0]
    finally:
        session.close()


def test_an_equal_on_an_opening_split_by_a_hand_added_shelf_is_dropped(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(
        doc, _equal(_COLUMN.a, _COLUMN.c), _equal(_COLUMN.b, _COLUMN.c)
    )
    shelf = cast("_BoxFeature", doc.addObject("Part::Box", "HandShelf"))
    shelf.Length, shelf.Width, shelf.Height = 564.0, 300.0, _T_MM
    shelf.Placement = FreeCAD.Placement(
        FreeCAD.Vector(_T_MM, 0.0, 150.0), FreeCAD.Rotation()
    )
    cast("_Group", container).addObject(cast("FreeCAD.DocumentObject", shelf))
    doc.recompute()
    session = _opened(container)
    try:
        (kept,) = session.constraints
        assert isinstance(kept, Equal)
        assert session.open_report.dropped == 1
        assert len(notified) == 1
    finally:
        session.close()


def test_an_even_spacing_is_dropped_with_its_end_board_and_kept_without_an_inner_one(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    column = _COLUMN.column.id
    container = _written(
        doc,
        EvenSpacing(run_id=column, start=RunEnd.START, end=RunEnd.END),
        EvenSpacing(run_id=column, start=RunEnd.START, end="shelf_b"),
    )
    doc.removeObject("shelf_b")
    doc.recompute()
    session = _opened(container)
    try:
        (kept,) = session.constraints
        assert isinstance(kept, EvenSpacing)
        assert (kept.start, kept.end) == (RunEnd.START, RunEnd.END)
        assert len(constraint_regions(session.unit, kept)) == 2
        assert session.open_report.dropped == 1
        assert len(notified) == 1
    finally:
        session.close()


def test_the_open_report_is_posted_once_and_not_after_undo_or_redo(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.b))
    _move_up(doc, "shelf_a", 20.0)
    session = _opened(container)
    try:
        assert len(notified) == 1
        assert session.resize("width", 700.0) is None
        doc.undo()
        session.settle()
        doc.redo()
        session.settle()
        assert not session.lost
        assert len(notified) == 1
    finally:
        session.close()


def test_a_unit_with_nothing_to_report_posts_nothing(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    session = _opened(_written(doc, _equal(_COLUMN.a, _COLUMN.b)))
    try:
        assert session.open_report.empty
        assert notified == []
    finally:
        session.close()


def test_delete_removes_selected_constraints_as_one_step_that_undo_restores(
    doc: FreeCAD.Document,
) -> None:
    column = _COLUMN.column.id
    container = _written(
        doc,
        _equal(_COLUMN.a, _COLUMN.b),
        _equal(_COLUMN.b, _COLUMN.c, active=False),
        EvenSpacing(run_id=column, start=RunEnd.START, end=RunEnd.END),
    )
    session = _opened(container)
    try:
        first, second, third = session.constraints
        before = _snapshot(doc)
        steps = doc.UndoCount
        session.select_constraints([first.id, second.id])
        assert session.selected_constraints == (first.id, second.id)
        assert session.delete_constraints() is None
        doc.recompute()
        assert [c.id for c in session.constraints] == [third.id]
        assert session.selected_constraints == ()
        assert doc.UndoCount == steps + 1
        assert _snapshot(doc) == before
        assert len(_stored(container)) == 1
        doc.undo()
        session.settle()
        assert [type(c) for c in session.constraints] == [Equal, Equal, EvenSpacing]
        assert [c.active for c in session.constraints] == [True, False, True]
        session.select_constraints([session.constraints[2].id])
        assert session.delete_constraints() is None
        assert len(session.constraints) == 2
    finally:
        session.close()


def test_delete_meets_another_constraint_left_within_the_clearance(
    doc: FreeCAD.Document,
) -> None:
    """Delete is an edit like any other: an active constraint the boards
    missed within the clearance at open is met in its step, so the Delete
    moves boards (bug-023)."""
    column = _COLUMN.column.id
    container = _written(
        doc,
        _equal(_COLUMN.a, _COLUMN.b),
        EvenSpacing(run_id=column, start="shelf_a", end=RunEnd.END),
    )
    _move_up(doc, "shelf_a", 1.0)
    session = _opened(container)
    try:
        equal, spacing = session.constraints
        assert equal.active and spacing.active
        session.select_constraints([spacing.id])
        assert session.delete_constraints() is None
        doc.recompute()
        a_mm, b_mm, _c_mm = _heights_mm(doc)
        assert a_mm == pytest.approx(b_mm)
        assert [c.id for c in session.constraints] == [equal.id]
    finally:
        session.close()


def test_delete_with_no_constraint_selected_is_refused(doc: FreeCAD.Document) -> None:
    session = _opened(_written(doc, _equal(_COLUMN.a, _COLUMN.b)))
    try:
        assert isinstance(session.delete_constraints(), EditFailure)
        assert len(session.constraints) == 1
    finally:
        session.close()


def _bays(session: Session) -> list[str]:
    """A, B and C as this session's scan named them, bottom to top."""
    root = session.unit.root
    assert isinstance(root, Division)
    middle = root.items[1]
    assert isinstance(middle, Division)
    column = middle.items[1]
    assert isinstance(column, Division)
    return [item.id for item in column.items if not isinstance(item, Board)]


def test_constrain_equal_chains_the_selected_openings_as_one_step(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc)
    session = _opened(container)
    try:
        a, b, c = _bays(session)
        steps = doc.UndoCount
        session.select_items([c, a, b])
        assert session.selected_items == (c, a, b)
        assert session.constrain_equal() is None
        assert doc.UndoCount == steps + 1
        assert [
            constraint.region_ids
            for constraint in session.constraints
            if isinstance(constraint, Equal)
        ] == [(c, a), (a, b)]
        assert session.selected_items == ()
        assert [entry["kind"] for entry in _stored(container)] == ["equal", "equal"]
    finally:
        session.close()


def test_constrain_even_spacing_spaces_the_column_and_refuses_one_opening(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc)
    session = _opened(container)
    try:
        a, b, c = _bays(session)
        session.select_items([b])
        refused = session.constrain_even_spacing()
        assert isinstance(refused, EditFailure)
        assert "Select" in refused.message
        assert session.constraints == ()
        session.select(a)
        assert session.set_size(200.0) is None
        assert session.set_lock(a, locked=False) is None
        session.select_items([a, c])
        assert session.constrain_even_spacing() is None
        doc.recompute()
        assert _heights_mm(doc) == pytest.approx((_BAY_MM, _BAY_MM, _BAY_MM))
    finally:
        session.close()


def test_a_conflicting_equal_is_refused_naming_its_locks_and_itself(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc)
    session = _opened(container)
    try:
        a, _b, c = _bays(session)
        session.select(c)
        assert session.set_size(200.0) is None
        assert session.set_lock(a, locked=True) is None
        snapshot = _snapshot(doc)
        locks = {_lock_id(session, a), _lock_id(session, c)}
        session.select_items([a, c])
        refused = session.constrain_equal()
        assert isinstance(refused, EditFailure)
        *named_locks, equal = refused.constraint_ids
        assert set(named_locks) == locks
        assert equal not in locks
        assert _others(session) == ()
        assert {*locks, equal} <= set(session.flagged)
        doc.recompute()
        assert _snapshot(doc) == snapshot
    finally:
        session.close()


def test_a_redundant_equal_is_kept_with_a_warning(doc: FreeCAD.Document) -> None:
    container = _written(doc)
    session = _opened(container)
    warnings: list[EditWarning] = []
    session.on_warning = warnings.append
    try:
        a, b, _c = _bays(session)
        assert session.set_lock(a, locked=True) is None
        assert session.set_lock(b, locked=True) is None
        session.select_items([a, b])
        assert session.constrain_equal() is None
        (equal,) = _others(session)
        (warning,) = warnings
        assert "redundant" in warning.message
        locks = (_lock_id(session, a), _lock_id(session, b))
        assert warning.region_ids == ()
        assert warning.constraint_ids == (*locks, equal.id)
        assert set(session.flagged) == {*locks, equal.id}
    finally:
        session.close()


def test_a_lock_an_equal_implies_is_kept_with_a_warning_naming_it(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc)
    session = _opened(container)
    warnings: list[EditWarning] = []
    session.on_warning = warnings.append
    try:
        a, b, _c = _bays(session)
        session.select_items([a, b])
        assert session.constrain_equal() is None
        (equal,) = session.constraints
        assert session.set_lock(a, locked=True) is None
        assert warnings == []
        assert session.set_lock(b, locked=True) is None
        (warning,) = warnings
        assert warning.region_ids == ()
        assert warning.constraint_ids == (equal.id, _lock_id(session, a))
    finally:
        session.close()


def test_selecting_constraints_and_items_exclude_each_other(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.b))
    session = _opened(container)
    try:
        (equal,) = session.constraints
        a, b, _c = _bays(session)
        session.select_items([a, b])
        session.select_constraints([equal.id])
        assert session.selected_items == ()
        assert session.selected_constraints == (equal.id,)
        session.select(a)
        assert session.selected_constraints == ()
        assert session.selected_items == (a,)
    finally:
        session.close()


# --- the constraint list's actions -----------------------------------------


def test_the_open_message_points_to_the_constraints_list(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.b))
    _move_up(doc, "shelf_a", 20.0)
    session = _opened(container)
    try:
        (message,) = notified
        assert "turned back on or deleted in the Constraints list" in message
    finally:
        session.close()


def test_rows_list_every_constraint_locks_included_as_made(
    doc: FreeCAD.Document,
) -> None:
    column = _COLUMN.column.id
    container = _written(
        doc,
        EvenSpacing(run_id=column, start=RunEnd.START, end=RunEnd.END, active=False),
        _equal(_COLUMN.a, _COLUMN.b),
    )
    session = _opened(container)
    try:
        a, b, c = _bays(session)
        assert session.set_lock(c, locked=True) is None
        assert session.set_lock(a, locked=True) is None
        rows = session.constraint_rows()
        spacing, equal, lock_c, lock_a = rows
        assert [row.constraint_id for row in rows] == [
            c.id for c in session.constraints
        ]
        assert (lock_c.constraint_id, lock_a.constraint_id) == (
            _lock_id(session, c),
            _lock_id(session, a),
        )
        assert (lock_a.kind, lock_a.active) == ("lock_height", True)
        assert lock_a.size_mm == pytest.approx(_BAY_MM)
        assert (spacing.kind, spacing.active, spacing.size_mm) == (
            "even_spacing",
            False,
            None,
        )
        assert (equal.kind, equal.active) == ("equal", True)
        assert equal.size_mm == pytest.approx(_BAY_MM)
        assert not any(row.redundant for row in rows)
        # C's lock alone fixes the column's height, so only A's, B's and
        # the Equal on them repeat each other.
        assert session.set_lock(b, locked=True) is None
        marked = [row.redundant for row in session.constraint_rows()]
        assert marked == [False, True, False, True, True]
        assert session.set_constraint_active(_lock_id(session, c), False) is None
        off = session.constraint_rows()[2]
        assert (off.kind, off.active, off.size_mm, off.redundant) == (
            "lock_height",
            False,
            None,
            False,
        )
    finally:
        session.close()


def test_each_constraint_action_is_one_named_step_that_undo_reverts(
    doc: FreeCAD.Document,
) -> None:
    container = _written(
        doc,
        _equal(_COLUMN.a, _COLUMN.b),
        _equal(_COLUMN.b, _COLUMN.c, active=False),
    )
    session = _opened(container)
    try:
        _first, second = session.constraints
        a, _b, _c = _bays(session)
        session.select(a)
        assert session.set_size(200.0) is None
        assert session.set_lock(a, locked=False) is None
        doc.recompute()

        def check(action: Callable[[], EditFailure | None], name: str) -> None:
            record = _stored(container)
            placements = _snapshot(doc)
            steps = doc.UndoCount
            assert action() is None
            doc.recompute()
            assert doc.UndoCount == steps + 1
            assert doc.UndoNames[0] == name
            doc.undo()
            session.settle()
            doc.recompute()
            assert _stored(container) == record
            assert _snapshot(doc) == pytest.approx(placements)
            doc.redo()
            session.settle()
            doc.recompute()

        check(
            lambda: session.set_constraint_active(second.id, True),
            "Activate Constraint",
        )
        assert [c.active for c in session.constraints] == [True, True]
        assert _heights_mm(doc) == pytest.approx((_BAY_MM, _BAY_MM, _BAY_MM))
        # Undo and Redo rescan, minting fresh constraint ids.
        second_id = session.constraints[1].id
        check(
            lambda: session.set_constraint_active(second_id, False),
            "Deactivate Constraint",
        )
        assert [c.active for c in session.constraints] == [True, False]
        check(lambda: session.delete_deactivated(), "Delete Deactivated Constraints")
        assert [c.active for c in session.constraints] == [True]
        (left,) = session.constraints
        session.select_constraints([left.id])
        check(lambda: session.set_basis(Basis.WITH_NEXT), "Change What a Size Measures")
        assert [entry["basis"] for entry in _stored(container)] == ["with_next"]
        (left,) = session.constraints
        check(lambda: session.delete_constraint(left.id), "Delete Constraint")
        assert session.constraints == ()
    finally:
        session.close()


def test_turning_on_or_off_what_already_is_adds_no_step(doc: FreeCAD.Document) -> None:
    session = _opened(_written(doc, _equal(_COLUMN.a, _COLUMN.b)))
    try:
        (equal,) = session.constraints
        steps = doc.UndoCount
        assert session.set_constraint_active(equal.id, True) is None
        assert doc.UndoCount == steps
        assert isinstance(session.delete_deactivated(), EditFailure)
        assert doc.UndoCount == steps
    finally:
        session.close()


def test_a_refused_reactivation_names_the_conflict_and_changes_nothing(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.c, active=False))
    session = _opened(container)
    try:
        a, _b, c = _bays(session)
        session.select(c)
        assert session.set_size(200.0) is None
        assert session.set_lock(a, locked=True) is None
        doc.recompute()
        (equal,) = _others(session)
        snapshot = _snapshot(doc)
        record = _stored(container)
        steps = doc.UndoCount
        refused = session.set_constraint_active(equal.id, True)
        assert isinstance(refused, EditFailure)
        named = (equal.id, _lock_id(session, c), _lock_id(session, a))
        assert refused.constraint_ids == named
        assert set(named) <= set(session.flagged)
        doc.recompute()
        assert doc.UndoCount == steps
        assert _snapshot(doc) == snapshot
        assert _stored(container) == record
        assert [c.active for c in _others(session)] == [False]
    finally:
        session.close()


def test_a_redundant_reactivation_is_kept_with_a_warning(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc, _equal(_COLUMN.a, _COLUMN.b, active=False))
    session = _opened(container)
    warnings: list[EditWarning] = []
    session.on_warning = warnings.append
    try:
        a, b, _c = _bays(session)
        assert session.set_lock(a, locked=True) is None
        assert session.set_lock(b, locked=True) is None
        (equal,) = _others(session)
        assert session.set_constraint_active(equal.id, True) is None
        assert [c.active for c in session.constraints] == [True, True, True]
        (warning,) = warnings
        assert "redundant" in warning.message
        assert warning.region_ids == ()
        assert warning.constraint_ids == (
            equal.id,
            _lock_id(session, a),
            _lock_id(session, b),
        )
    finally:
        session.close()


def test_a_lone_selected_constraint_reports_its_basis(doc: FreeCAD.Document) -> None:
    session = _opened(_written(doc, _equal(_COLUMN.a, _COLUMN.b)))
    try:
        (equal,) = session.constraints
        session.select_constraints([equal.id])
        measured = session.selected_measurement()
        assert measured is not None
        assert measured.basis is Basis.CLEAR
        assert measured.clear_mm == pytest.approx(_BAY_MM)
        assert measured.spacing_mm == pytest.approx(_BAY_MM + _T_MM)
    finally:
        session.close()


# --- locks as constraints ---------------------------------------------------


def test_a_stored_deactivated_lock_opens_deactivated_and_holds_nothing(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(doc, Lock(_COLUMN.a.id, active=False))
    session = _opened(container)
    try:
        (lock,) = session.constraints
        assert isinstance(lock, Lock) and not lock.active
        assert session.open_report.empty
        assert notified == []
        session.select(_bays(session)[1])
        assert session.set_size(_BAY_MM + 100.0) is None
        doc.recompute()
        assert _heights_mm(doc) == pytest.approx(
            (_BAY_MM - 50.0, _BAY_MM + 100.0, _BAY_MM - 50.0)
        )
        stored_lock, _typed = _stored(container)
        assert stored_lock["kind"] == "lock"
        assert stored_lock["active"] is False
    finally:
        session.close()


def test_a_stored_lock_on_a_gone_opening_is_reported_with_the_others(
    doc: FreeCAD.Document, notified: list[str]
) -> None:
    container = _written(
        doc, Lock(_COLUMN.a.id), _equal(_COLUMN.a, _COLUMN.c), Lock(_COLUMN.c.id)
    )
    doc.removeObject("shelf_a")
    doc.recompute()
    session = _opened(container)
    try:
        (kept,) = session.constraints
        assert isinstance(kept, Lock)
        assert session.open_report.dropped == 2
        assert len(notified) == 1
        assert "removed" in notified[0]
    finally:
        session.close()


def test_turning_a_lock_off_or_on_is_one_step_that_moves_no_board(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc, Lock(_COLUMN.a.id))
    session = _opened(container)
    try:
        doc.recompute()
        snapshot = _snapshot(doc)
        for active, name in (
            (False, "Deactivate Constraint"),
            (True, "Activate Constraint"),
        ):
            (lock,) = session.constraints
            steps = doc.UndoCount
            assert session.set_constraint_active(lock.id, active) is None
            doc.recompute()
            assert doc.UndoCount == steps + 1
            assert doc.UndoNames[0] == name
            assert _snapshot(doc) == snapshot
            assert [c.active for c in session.constraints] == [active]
            assert [entry["active"] for entry in _stored(container)] == [active]
            doc.undo()
            session.settle()
            assert [c.active for c in session.constraints] == [not active]
            doc.redo()
            session.settle()
            assert [c.active for c in session.constraints] == [active]
    finally:
        session.close()


def test_delete_deactivated_removes_deactivated_locks_with_the_rest(
    doc: FreeCAD.Document,
) -> None:
    container = _written(
        doc,
        Lock(_COLUMN.a.id, active=False),
        _equal(_COLUMN.a, _COLUMN.b, active=False),
        Lock(_COLUMN.c.id),
    )
    session = _opened(container)
    try:
        steps = doc.UndoCount
        assert session.delete_deactivated() is None
        (kept,) = session.constraints
        assert isinstance(kept, Lock) and kept.active
        assert doc.UndoCount == steps + 1
        assert doc.UndoNames[0] == "Delete Deactivated Constraints"
        doc.undo()
        session.settle()
        assert [c.active for c in session.constraints] == [False, False, True]
    finally:
        session.close()


def test_lock_height_locks_each_selected_opening_as_one_step_moving_nothing(
    doc: FreeCAD.Document,
) -> None:
    container = _written(doc, Lock(_COLUMN.b.id, active=False))
    session = _opened(container)
    try:
        doc.recompute()
        snapshot = _snapshot(doc)
        a, b, _c = _bays(session)
        session.select_items([a, b])
        steps = doc.UndoCount
        assert session.lock_axis("vertical") is None
        doc.recompute()
        assert doc.UndoCount == steps + 1
        assert doc.UndoNames[0] == "Lock Height"
        assert _snapshot(doc) == snapshot
        locks = [c for c in session.constraints if isinstance(c, Lock)]
        # B's deactivated Lock is turned on rather than joined by another.
        assert [(c.region_id, c.active) for c in locks] == [
            (b, True),
            (a, True),
        ]
        assert session.selected_items == (a, b)
        # Locking what is already locked adds no step.
        assert session.lock_axis("vertical") is None
        assert doc.UndoCount == steps + 1
        doc.undo()
        session.settle()
        assert [c.active for c in session.constraints] == [False]
    finally:
        session.close()


def test_lock_width_refuses_a_width_that_is_the_units_own(
    doc: FreeCAD.Document,
) -> None:
    session = _opened(_written(doc))
    try:
        session.select(_bays(session)[0])
        steps = doc.UndoCount
        failure = session.lock_axis("horizontal")
        assert isinstance(failure, EditFailure)
        assert "Width field" in failure.message
        assert session.constraints == ()
        assert doc.UndoCount == steps
    finally:
        session.close()


def test_lock_width_and_height_refuse_a_board_or_nothing_selected(
    doc: FreeCAD.Document,
) -> None:
    session = _opened(_written(doc))
    try:
        a = _bays(session)[0]
        selections: list[list[str]] = [[], ["shelf_a"], [a, "shelf_a"]]
        for selection in selections:
            session.select_items(selection)
            for direction in ("horizontal", "vertical"):
                failure = session.lock_axis(direction)
                assert isinstance(failure, EditFailure), (selection, direction)
                assert "Select one or more openings" in failure.message
        assert session.constraints == ()
    finally:
        session.close()
