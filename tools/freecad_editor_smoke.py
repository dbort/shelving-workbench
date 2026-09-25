"""Headless functional check for the elevation editor's session: selection
permissions, split, merge, both refusal reasons a session edit returns
rather than raises, cancel, commit-then-undo, and that a committed layout
survives a fresh session's rescan (bug-006); plus the selection-to-unit
mapping that decides when Edit Unit is enabled.

Drives :class:`freecad.Shelving.editor.session.Session` directly rather than
:class:`freecad.Shelving.editor.panel.EditUnitPanel`: ``FreeCADGui.Control``,
which the panel needs to show itself, does not exist under ``freecadcmd``
(``docs/freecadcmd-notes.md``), so the panel's own wiring is a
``docs/manual-qa.md`` case instead. Unlike ``tools/freecad_scan_smoke.py``,
this is a plain script, not a self-invoking ``pytest`` module: ``freecadcmd``
exits 0 on an uncaught exception, so it prints ``shelving editor OK`` as its
last line only when every assertion held, and ``tools/run-tests.sh`` greps
the captured output for that line.
"""

import os
import sys
from typing import Protocol, cast

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import FreeCAD  # noqa: E402

from freecad.Shelving.container import (  # noqa: E402
    read_container,
    unit_for_selection,
    write_container,
)
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
    :meth:`~freecad.Shelving.editor.session.Session.split` resolved a
    direction to."""
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


def _find_bay_ids_in_order(region: Region) -> list[str]:
    """Every ``Bay`` id in ``region``'s subtree, depth first: the same order
    an elevation's items run in, so the first is "the left opening" and the
    last "the right" for a run split along the horizontal axis."""
    out: list[str] = []
    _collect_bay_ids(region, out)
    return out


def _collect_bay_ids(region: Region, out: list[str]) -> None:
    if isinstance(region, Bay):
        out.append(region.id)
        return
    if isinstance(region, Division):
        for item in region.items:
            if not isinstance(item, Board):
                _collect_bay_ids(item, out)


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


def _board_objects(container: FreeCAD.DocumentObject) -> list[FreeCAD.DocumentObject]:
    return [
        obj
        for obj in cast("FreeCAD.DocumentObjectGroup", container).Group
        if obj.isDerivedFrom("Part::Box")
    ]


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


def _board_snapshot_by_name(
    container: FreeCAD.DocumentObject,
) -> dict[str, tuple[float, float, float, float, float, float]]:
    """:func:`_board_snapshot`, keyed by board name, so a caller can check
    that a chosen subset of boards kept their geometry across an edit that
    also adds boards the subset never named."""
    return {entry[0]: entry[1:] for entry in _board_snapshot(container)}


def _assert_session_matches_document(session: Session) -> None:
    """Every board id ``session.unit`` names has a document object of that
    name whose placement and size agree with ``session.spaces``, within
    ``1e-6`` mm: what "an editor-built layout reads back unchanged"
    (bug-006) means for a session immediately after it re-scans the
    container, before any further edit or write happens."""
    doc = session.container.Document
    tol_mm = 1e-6
    document_board_names = {obj.Name for obj in _board_objects(session.container)}
    assert _board_ids(session.unit.root) == document_board_names, (
        _board_ids(session.unit.root),
        document_board_names,
    )
    for board_id in _board_ids(session.unit.root):
        space = session.spaces[board_id]
        obj = cast("_BoxFeature", doc.getObject(board_id))
        assert obj is not None, board_id
        base = obj.Placement.Base
        # obj.Length/Width/Height are FreeCAD Quantity values at runtime
        # despite the Protocol's plain-float annotation; float() strips the
        # unit before arithmetic, which otherwise raises "Unit mismatch"
        # against space.size's plain millimetre floats.
        assert abs(float(base.x) - space.origin.x_mm) <= tol_mm, (board_id, "origin.x")
        assert abs(float(base.y) - space.origin.y_mm) <= tol_mm, (board_id, "origin.y")
        assert abs(float(base.z) - space.origin.z_mm) <= tol_mm, (board_id, "origin.z")
        assert abs(float(obj.Length) - space.size.x_mm) <= tol_mm, (board_id, "size.x")
        assert abs(float(obj.Width) - space.size.y_mm) <= tol_mm, (board_id, "size.y")
        assert abs(float(obj.Height) - space.size.z_mm) <= tol_mm, (board_id, "size.z")


def _check_an_editor_layout_survives_a_rescan() -> None:
    """bug-006 end to end: build the layout through one ``Session``, commit,
    and confirm a *fresh* ``Session`` (a real rescan, not the same in-memory
    tree) reads every board back at its just-written placement and size;
    then a further edit elsewhere must not move any board on the left."""
    doc = FreeCAD.newDocument("editor_smoke_bug_006")
    try:
        container = create_unit(doc)
        doc.recompute()

        session = Session(container)
        session.open()
        # Add a divider: the bay's parent (the inner Axis.X division)
        # already runs along Axis.X, so this splices rather than nests.
        bay_id = _find_bay_id(session.unit.root)
        session.select(bay_id)
        assert session.split("horizontal") is None
        doc.recompute()

        # Add a shelf on the left: that bay's parent is the Axis.X
        # division, a different axis, so this nests instead.
        left_bay_id = _find_bay_ids_in_order(session.unit.root)[0]
        session.select(left_bay_id)
        assert session.split("vertical") is None
        doc.recompute()

        # Add a shelf top-left: that bay's parent is now the Axis.Z
        # division split_left just nested, the same axis as this split, so
        # it splices into that division's own run rather than nesting
        # again - the exact structure bug-006's rescan could not recover.
        # solve places a run's items from the axis minimum up, so of the two
        # bays that division split_left just made, index [1] (not [0]) is
        # the upper, top-left one.
        topleft_bay_id = _find_bay_ids_in_order(session.unit.root)[1]
        session.select(topleft_bay_id)
        assert session.split("vertical") is None
        doc.recompute()

        session.commit()
        doc.recompute()
        boards_before = _board_snapshot_by_name(container)

        fresh = Session(container)
        _assert_session_matches_document(fresh)

        fresh.open()
        right_bay_id = _find_bay_ids_in_order(fresh.unit.root)[-1]
        fresh.select(right_bay_id)
        assert fresh.split("horizontal") is None
        doc.recompute()
        fresh.commit()
        doc.recompute()

        boards_after = _board_snapshot_by_name(container)
        for name, snapshot_before in boards_before.items():
            assert boards_after[name] == snapshot_before, name
    finally:
        FreeCAD.closeDocument(doc.Name)


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
    not X. Guards against a hardcoded elevation axis, which picks the wrong
    pair of model axes when ``depth_axis`` is not Y and splits the bay
    parallel to the elevation plane (invisible in the drawing) instead of
    across it."""
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
    """A refused edit leaves the document at the last state that solved,
    not necessarily the session's opening state. Split once (an accepted
    edit) before attempting the structurally impossible merge, then assert
    the document still matches the state right after that split, not the
    state from before it."""
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
    """A unit whose depth axis is X, not Y. Add Divider and Add Shelf
    must resolve their model axis from
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


def _check_selection_maps_to_its_unit() -> None:
    """Boards inside one unit, alone or together with the unit's container
    or a nested group, name that unit; objects from two units, or from
    outside any unit, name nothing."""
    doc = FreeCAD.newDocument("editor_smoke_selection")
    try:
        first = create_unit(doc)
        second = create_unit(doc)
        loose = cast("FreeCAD.DocumentObject", doc.addObject("Part::Box", "Loose"))
        doc.recompute()
        first_boards = _board_objects(first)
        second_boards = _board_objects(second)

        assert unit_for_selection([first]) is first
        assert unit_for_selection(first_boards[:1]) is first
        assert unit_for_selection(first_boards) is first
        assert unit_for_selection([first, first_boards[0]]) is first

        # A group nested inside the unit is climbed through, and selecting
        # it alone maps to the unit, not to the group itself.
        nested = cast(
            "FreeCAD.DocumentObjectGroup",
            doc.addObject("App::DocumentObjectGroup", "Nested"),
        )
        cast("FreeCAD.DocumentObjectGroup", first).addObject(nested)
        extra = cast("FreeCAD.DocumentObject", doc.addObject("Part::Box", "Extra"))
        nested.addObject(extra)
        assert unit_for_selection([extra]) is first
        assert unit_for_selection([nested]) is first

        assert unit_for_selection([]) is None
        assert unit_for_selection([loose]) is None
        assert unit_for_selection([first_boards[0], second_boards[0]]) is None
        assert unit_for_selection([first_boards[0], loose]) is None

        # A container with no ShelvingUnitId yet is still editable on its own.
        bare = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Bare"))
        assert unit_for_selection([bare]) is bare
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
    _check_selection_maps_to_its_unit()
    _check_cancel_restores_the_opening_state()
    _check_commit_then_one_undo_reverses_the_session()
    _check_an_editor_layout_survives_a_rescan()
    print("shelving editor OK")
    sys.stdout.flush()


main()
