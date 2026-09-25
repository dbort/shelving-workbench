"""Headless functional check for the elevation editor's session: selection
permissions, split, merge, both refusal reasons a session edit returns
rather than raises, cancel, and commit-then-undo.

Drives :class:`freecad.Shelving.editor.session.Session` directly rather than
:class:`freecad.Shelving.editor.panel.EditUnitPanel`: ``FreeCADGui.Control``,
which the panel needs to show itself, does not exist under ``freecadcmd``
(``docs/freecadcmd-notes.md``, this repo's sh-020 Frontier Advice), so the
panel's own wiring is a ``docs/manual-qa.md`` case instead. Unlike
``tools/freecad_scan_smoke.py`` and ``tools/freecad_write_smoke.py``, this is
a plain script, not a self-invoking ``pytest`` module: this repo's sh-020
task file specifies printing ``shelving editor OK`` as this script's last
line, with ``tools/run-tests.sh`` grepping the captured output for it, rather
than relying on ``freecadcmd``'s own exit-code passthrough (which the other
two smokes use instead, each via ``sys.exit(pytest.main(...))``).

Every assertion below names the scenario it covers with an adjacent comment,
matching the sh-020 Execution Plan's own list one for one so a failure's
traceback line is enough to identify which bullet broke.
"""

import os
import sys
from typing import Protocol, cast

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import FreeCAD  # noqa: E402

from freecad.Shelving.container import read_container, write_container  # noqa: E402
from freecad.Shelving.core.geometry import Vec3  # noqa: E402
from freecad.Shelving.core.layout import (  # noqa: E402
    Axis,
    Bay,
    Board,
    Division,
    Region,
    Unit,
)
from freecad.Shelving.default_catalog import (  # noqa: E402
    DEFAULT_CATALOG,
    DEFAULT_MATERIAL_ID,
)
from freecad.Shelving.editor.session import EditFailure, Session  # noqa: E402
from freecad.Shelving.unit_ops import create_unit  # noqa: E402


class _Placeable(Protocol):
    Placement: FreeCAD.Placement


class _BoxFeature(_Placeable, Protocol):
    Length: float
    Width: float
    Height: float


_BoardSnapshot = tuple[tuple[str, float, float, float, float, float, float], ...]


def _find_bay_id(region: Region) -> str:
    """The id of the first ``Bay`` found in ``region``'s subtree, depth first."""
    found = _find_bay(region)
    if found is None:
        raise AssertionError(f"no Bay found in {region!r}")
    return found


def _find_bay(region: Region) -> str | None:
    """``_find_bay_id``'s recursive half: ``None`` rather than raising when
    ``region``'s own subtree holds no ``Bay``, so a sibling's subtree still
    gets searched instead of aborting the whole walk."""
    if isinstance(region, Bay):
        return region.id
    if isinstance(region, Division):
        for item in region.items:
            if not isinstance(item, Board):
                found = _find_bay(item)
                if found is not None:
                    return found
    return None


def _axis_of_new_board(before: Region, after: Region) -> Axis:
    """The ``Division.axis`` of the ``Division`` holding the one board
    present in ``after`` and absent from ``before``: the axis
    :meth:`~freecad.Shelving.editor.session.Session.split` actually resolved
    a direction to."""
    board_id = _find_new_board_id(before, after)
    axis = _axis_of_board(after, board_id)
    assert axis is not None, board_id
    return axis


def _axis_of_board(region: Region, board_id: str) -> Axis | None:
    if not isinstance(region, Division):
        return None
    for item in region.items:
        if isinstance(item, Board) and item.id == board_id:
            return region.axis
    for item in region.items:
        if not isinstance(item, Board):
            found = _axis_of_board(item, board_id)
            if found is not None:
                return found
    return None


def _find_new_board_id(before: Region, after: Region) -> str:
    """The id of the one ``Board`` present in ``after`` and absent from
    ``before``: the board a split just created."""
    new_ids = _board_ids(after) - _board_ids(before)
    assert len(new_ids) == 1, new_ids
    return next(iter(new_ids))


def _board_ids(region: Region) -> set[str]:
    if not isinstance(region, Division):
        return set()
    ids: set[str] = set()
    for item in region.items:
        if isinstance(item, Board):
            ids.add(item.id)
        else:
            ids |= _board_ids(item)
    return ids


def _bay_count(region: Region) -> int:
    if isinstance(region, Bay):
        return 1
    if isinstance(region, Division):
        return sum(
            _bay_count(item) for item in region.items if not isinstance(item, Board)
        )
    return 0


def _board_names(container: FreeCAD.DocumentObject) -> tuple[str, ...]:
    boxes, skipped, _record = read_container(container)
    assert not skipped, skipped
    return tuple(sorted(b.name for b in boxes))


def _board_snapshot(container: FreeCAD.DocumentObject) -> _BoardSnapshot:
    """One entry per board document object, its geometry and placement, so a
    refused edit's "changed nothing" claim can be checked exactly rather
    than only by name."""
    doc = container.Document
    entries: list[tuple[str, float, float, float, float, float, float]] = []
    for name in _board_names(container):
        obj = cast("_BoxFeature", doc.getObject(name))
        base = obj.Placement.Base
        entries.append(
            (name, obj.Length, obj.Width, obj.Height, base.x, base.y, base.z)
        )
    return tuple(entries)


def _tiny_unit() -> Unit:
    """A closed single-bay unit 40mm wide: its interior bay (40 - 2*18 = 4mm)
    is far too narrow to hold a divider board, so splitting it always fails
    to solve rather than write anything."""
    return Unit(
        size_mm=Vec3(40.0, 300.0, 900.0),
        default_material=DEFAULT_MATERIAL_ID,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[Board(role="left_side"), Bay(), Board(role="right_side")],
                ),
                Board(role="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _rotated_default_unit() -> Unit:
    """The same closed single-bay shape :func:`create_unit` seeds, but
    rotated a quarter turn: depth is X, not Y, and the run of shelves is Y,
    not X. Exercises the review's F1 bug: a hardcoded elevation axis picks
    the wrong pair of model axes when ``depth_axis`` is not Y, splitting the
    bay parallel to the elevation plane (invisible in the drawing) instead
    of across it."""
    return Unit(
        size_mm=Vec3(300.0, 600.0, 900.0),
        default_material=DEFAULT_MATERIAL_ID,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom"),
                Division(
                    axis=Axis.Y,
                    items=[Board(role="left_side"), Bay(), Board(role="right_side")],
                ),
                Board(role="top"),
            ],
        ),
        depth_axis=Axis.X,
    )


def _check_selection_permissions_and_split(doc: FreeCAD.Document) -> None:
    """Selecting a bay permits split and not merge; splitting writes one new
    board and two bays; selecting that board permits merge; merging removes
    it and restores the original board count and names. Also covers the
    "nothing selected" refusal both buttons can hit: no id was named to
    refuse, so ``EditFailure.node_id`` is ``None`` rather than an id string."""
    container = create_unit(doc)
    doc.recompute()
    names_before = _board_names(container)

    session = Session(container)
    session.open()
    try:
        assert session.selected_id is None
        no_selection_split = session.split("horizontal")
        assert isinstance(no_selection_split, EditFailure), no_selection_split
        assert no_selection_split.node_id is None, no_selection_split
        no_selection_merge = session.merge()
        assert isinstance(no_selection_merge, EditFailure), no_selection_merge
        assert no_selection_merge.node_id is None, no_selection_merge

        bay_id = _find_bay_id(session.unit.root)
        bay_count_before = _bay_count(session.unit.root)
        session.select(bay_id)
        assert session.can_split() is True
        assert session.can_merge() is False

        unit_before_split = session.unit
        result = session.split("horizontal")
        assert result is None, result
        doc.recompute()
        assert _bay_count(session.unit.root) == bay_count_before + 1
        names_after_split = _board_names(container)
        assert len(names_after_split) == len(names_before) + 1, names_after_split

        new_board_id = _find_new_board_id(unit_before_split.root, session.unit.root)
        session.select(new_board_id)
        assert session.can_split() is False
        assert session.can_merge() is True

        result = session.merge()
        assert result is None, result
        doc.recompute()
        assert _board_names(container) == names_before
    finally:
        session.cancel()


def _check_a_structurally_refused_edit_changes_nothing() -> None:
    """One refusal reason a session edit returns rather than raises: the core
    edit layer's own ``EditError``, here a merge on a board with no
    neighbour on one side (the edge of a run). Leaves board count, names,
    sizes and placements unchanged."""
    doc = FreeCAD.newDocument("editor_smoke_refused_structural")
    try:
        container = create_unit(doc)
        doc.recompute()

        session = Session(container)
        session.open()
        try:
            # "bottom" sits first in its Division's items, so it has no
            # neighbour before it: merge_at refuses it by construction.
            boxes, _skipped, _record = read_container(container)
            bottom_name = next(b.name for b in boxes if b.name == "bottom")
            session.select(bottom_name)
            snapshot_before = _board_snapshot(container)

            result = session.merge()
            assert isinstance(result, EditFailure), result
            assert result.node_id == bottom_name, result
            doc.recompute()
            assert _board_snapshot(container) == snapshot_before
        finally:
            session.cancel()
    finally:
        FreeCAD.closeDocument(doc.Name)


def _check_an_unsolvable_edit_changes_nothing() -> None:
    """The other refusal reason a session edit returns rather than raises:
    the re-solve's own ``LayoutSolveError``, here a split that would not
    physically fit. Leaves board count, names, sizes and placements
    unchanged."""
    doc = FreeCAD.newDocument("editor_smoke_refused_unsolvable")
    try:
        container = cast(
            "FreeCAD.DocumentObject", doc.addObject("App::Part", "TinyUnit")
        )
        write_container(container, _tiny_unit(), DEFAULT_CATALOG)
        doc.recompute()

        session = Session(container)
        session.open()
        try:
            bay_id = _find_bay_id(session.unit.root)
            session.select(bay_id)
            snapshot_before = _board_snapshot(container)

            result = session.split("horizontal")
            assert isinstance(result, EditFailure), result
            # A real node was pinned (the LayoutSolveError's own offending
            # id), distinguishing this from the "nothing selected" refusal,
            # which names none.
            assert result.node_id is not None, result
            doc.recompute()
            assert _board_snapshot(container) == snapshot_before
        finally:
            session.cancel()
    finally:
        FreeCAD.closeDocument(doc.Name)


def _check_cancel_restores_the_opening_state() -> None:
    """Cancel after several edits restores the document to its opening state
    exactly."""
    doc = FreeCAD.newDocument("editor_smoke_cancel")
    try:
        container = create_unit(doc)
        doc.recompute()
        snapshot_before = _board_snapshot(container)

        session = Session(container)
        session.open()
        bay_id = _find_bay_id(session.unit.root)
        session.select(bay_id)
        unit_before_split = session.unit
        assert session.split("horizontal") is None
        doc.recompute()

        new_board_id = _find_new_board_id(unit_before_split.root, session.unit.root)
        session.select(new_board_id)
        assert session.merge() is None
        doc.recompute()

        bay_id_again = _find_bay_id(session.unit.root)
        session.select(bay_id_again)
        assert session.split("vertical") is None
        doc.recompute()

        session.cancel()
        doc.recompute()
        assert _board_snapshot(container) == snapshot_before
    finally:
        FreeCAD.closeDocument(doc.Name)


def _check_commit_then_one_undo_reverses_the_session() -> None:
    """Commit after the same edits leaves them in place and one undo reverses
    the lot."""
    doc = FreeCAD.newDocument("editor_smoke_commit_undo")
    try:
        container = create_unit(doc)
        doc.recompute()
        names_before = _board_names(container)

        session = Session(container)
        session.open()
        bay_id = _find_bay_id(session.unit.root)
        session.select(bay_id)
        assert session.split("horizontal") is None
        doc.recompute()
        names_after_split = _board_names(container)
        assert names_after_split != names_before

        session.commit()
        doc.recompute()
        assert _board_names(container) == names_after_split

        doc.undo()  # type: ignore[no-untyped-call]
        doc.recompute()
        assert _board_names(container) == names_before
    finally:
        FreeCAD.closeDocument(doc.Name)


def _check_a_refused_edit_after_an_accepted_edit_changes_nothing() -> None:
    """The Must Have says a refused edit leaves the document "at the last
    state that did" solve, not necessarily the session's opening state:
    split once (an accepted edit) before attempting the structurally
    impossible merge, and assert the document still matches the state right
    after that split, not the state from before it."""
    doc = FreeCAD.newDocument("editor_smoke_refused_after_accepted")
    try:
        container = create_unit(doc)
        doc.recompute()

        session = Session(container)
        session.open()
        try:
            bay_id = _find_bay_id(session.unit.root)
            session.select(bay_id)
            assert session.split("horizontal") is None
            doc.recompute()
            snapshot_after_split = _board_snapshot(container)

            # "bottom" sits first in its Division's items regardless of the
            # split just made, so it still has no neighbour before it.
            boxes, _skipped, _record = read_container(container)
            bottom_name = next(b.name for b in boxes if b.name == "bottom")
            session.select(bottom_name)
            result = session.merge()
            assert isinstance(result, EditFailure), result
            assert result.node_id == bottom_name, result
            doc.recompute()
            assert _board_snapshot(container) == snapshot_after_split
        finally:
            session.cancel()
    finally:
        FreeCAD.closeDocument(doc.Name)


def _check_split_direction_follows_the_units_depth_axis() -> None:
    """sh-020 review F1: a unit whose depth axis is X, not Y. Split
    Horizontal and Split Vertical must resolve their model axis from
    ``elevation_axes(unit.depth_axis)`` rather than a hardcoded model axis,
    or the new board would lie in the elevation plane instead of dividing
    it. Asserts the new board's ``Division.axis`` is one of the elevation's
    own two axes (Y horizontal, Z vertical here), never the depth axis (X)."""
    doc = FreeCAD.newDocument("editor_smoke_depth_axis_not_y")
    try:
        container = cast(
            "FreeCAD.DocumentObject", doc.addObject("App::Part", "RotatedUnit")
        )
        write_container(container, _rotated_default_unit(), DEFAULT_CATALOG)
        doc.recompute()

        session = Session(container)
        session.open()
        try:
            assert session.unit.depth_axis == Axis.X

            bay_id = _find_bay_id(session.unit.root)
            session.select(bay_id)
            unit_before_horizontal = session.unit
            assert session.split("horizontal") is None
            doc.recompute()
            horizontal_axis = _axis_of_new_board(
                unit_before_horizontal.root, session.unit.root
            )
            assert horizontal_axis == Axis.Y, horizontal_axis

            bay_id = _find_bay_id(session.unit.root)
            session.select(bay_id)
            unit_before_vertical = session.unit
            assert session.split("vertical") is None
            doc.recompute()
            vertical_axis = _axis_of_new_board(
                unit_before_vertical.root, session.unit.root
            )
            assert vertical_axis == Axis.Z, vertical_axis
        finally:
            session.cancel()
    finally:
        FreeCAD.closeDocument(doc.Name)


def main() -> None:
    doc = FreeCAD.newDocument("editor_smoke")
    try:
        _check_selection_permissions_and_split(doc)
    finally:
        FreeCAD.closeDocument(doc.Name)
    _check_a_structurally_refused_edit_changes_nothing()
    _check_an_unsolvable_edit_changes_nothing()
    _check_a_refused_edit_after_an_accepted_edit_changes_nothing()
    _check_split_direction_follows_the_units_depth_axis()
    _check_cancel_restores_the_opening_state()
    _check_commit_then_one_undo_reverses_the_session()
    print("shelving editor OK")
    sys.stdout.flush()


main()
