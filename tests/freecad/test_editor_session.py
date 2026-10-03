"""The elevation editor's session against a real FreeCAD document.

Drives :class:`freecad.Shelving.editor.session.Session` directly rather than
:class:`freecad.Shelving.editor.panel.EditUnitPanel`, which needs the GUI;
``tests/freecad_gui/test_panel.py`` covers the panel's own wiring with the
GUI up.
"""

from typing import Protocol, cast

import FreeCAD

from freecad.Shelving import properties
from freecad.Shelving.catalog import ensure_catalog, read_catalog
from freecad.Shelving.container import (
    read_container,
    unit_for_selection,
    write_container,
)
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    Region,
    SizeRule,
    Unit,
)
from freecad.Shelving.core.scan import elevation_axes
from freecad.Shelving.default_catalog import (
    DEFAULT_CATALOG,
    DEFAULT_MATERIAL_ID,
)
from freecad.Shelving.editor.session import (
    PROBE_PROPERTY,
    EditFailure,
    Session,
    SplitDirection,
)
from freecad.Shelving.unit_ops import create_unit, reflow_all


class _Placeable(Protocol):
    Placement: FreeCAD.Placement


class _BoxFeature(_Placeable, Protocol):
    Length: float
    Width: float
    Height: float


_BoardSnapshot = tuple[tuple[str, float, float, float, float, float, float], ...]

# Index into one _board_snapshot_by_name entry (Length, Width, Height, x, y,
# z) for a given model axis's size component: X to Length, Y to Width, Z to
# Height, matching _write_geometry's mapping. Position always compares
# whole (indices 3:6), since nothing in this suite moves a surviving
# board's origin, only sometimes its extent along one axis.
_AXIS_SIZE_INDEX: dict[Axis, int] = {Axis.X: 0, Axis.Y: 1, Axis.Z: 2}


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


def _assert_unit_ids_match_document(session: Session) -> None:
    """Every id ``session.unit``'s tree names equals a live document
    object's ``Name``: the precondition the next ``write_container`` call
    relies on to match a board by name rather than delete and recreate it
    (bug-008). ``Session._apply`` maintains this after every accepted
    edit, adopting a freshly-created board's real ``Name`` via
    ``WriteResult.id_renames``. An object the session lists as left alone
    is not a board of the unit and is not counted."""
    left_alone = {entry.name for entry in session.left_alone}
    document_board_names = {
        obj.Name for obj in _board_objects(session.container)
    } - left_alone
    assert _board_ids(session.unit.root) == document_board_names, (
        _board_ids(session.unit.root),
        document_board_names,
    )


def _assert_session_matches_document(session: Session) -> None:
    """Every board id ``session.unit`` names has a document object of that
    name whose placement and size agree with ``session.spaces``, within
    ``1e-6`` mm: what "an editor-built layout reads back unchanged"
    (bug-006) means for a session immediately after it re-scans the
    container, before any further edit or write happens."""
    doc = session.container.Document
    tol_mm = 1e-6
    _assert_unit_ids_match_document(session)
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


def test_an_editor_layout_survives_a_rescan() -> None:
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
        # division the previous split nested, the same axis as this split,
        # so it splices into that division's own run rather than nesting
        # again: the structure bug-006's rescan could not recover.
        # solve places a run's items from the axis minimum up, so of the two
        # bays the previous split made, index [1] (not [0]) is the upper,
        # top-left one.
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


def test_deleting_a_divider_reaches_the_merge_collapse_splice() -> None:
    """The collapse-then-splice path ``_splice_collapsed_child`` implements
    is reachable from a real ``Session`` edit, not only a hand-built core
    fixture. On the default unit: add a shelf, a divider in the bay below
    the shelf, a shelf left of that divider, then delete the divider. The
    delete collapses the divider's ``Axis.X`` division down to the
    ``Axis.Z`` division the "shelf left" split nested, which shares the
    parent ``Axis.Z`` division the first shelf nested, and must splice
    rather than nest.

    Every surviving board, matched by ``Name``, keeps its placement (all
    three axes) and its size along the unit's vertical elevation axis: the
    axis the spliced-in run shares with its new, flatter home. The "shelf
    left of the divider" board widens along the horizontal axis, since the
    splice hands it the width the deleted divider and the bay on its other
    side occupied, so horizontal size is exempt from the comparison."""
    doc = FreeCAD.newDocument("editor_smoke_merge_collapse_reachable")
    try:
        container = create_unit(doc)
        doc.recompute()

        session = Session(container)
        session.open()
        try:
            bay_id = _find_bay_id(session.unit.root)
            session.select(bay_id)
            assert session.split("vertical") is None  # a shelf
            doc.recompute()

            lower_bay_id = _find_bay_ids_in_order(session.unit.root)[0]
            unit_before_divider = session.unit
            session.select(lower_bay_id)
            assert session.split("horizontal") is None  # a divider below it
            doc.recompute()
            divider_id = _find_new_board_id(unit_before_divider.root, session.unit.root)

            left_bay_id = _find_bay_ids_in_order(session.unit.root)[0]
            session.select(left_bay_id)
            assert session.split("vertical") is None  # a shelf left of it
            doc.recompute()

            snapshot_before_delete = _board_snapshot_by_name(container)
            board_count_before_delete = len(_board_names(container))
            depth_axis = session.unit.depth_axis
            assert depth_axis is not None, session.unit.id
            column_axis = elevation_axes(depth_axis)[1]  # vertical
            size_index = _AXIS_SIZE_INDEX[column_axis]

            session.select(divider_id)
            assert session.can_merge() is True
            result = session.merge()
            assert result is None, result
            doc.recompute()

            assert len(_board_names(container)) == board_count_before_delete - 1
            snapshot_after_delete = _board_snapshot_by_name(container)
            for name, before in snapshot_before_delete.items():
                after = snapshot_after_delete.get(name)
                if after is None:
                    continue  # the deleted divider itself
                assert after[3:6] == before[3:6], (name, "placement")
                assert after[size_index] == before[size_index], (name, "column size")
        finally:
            session.cancel()
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_split_created_board_keeps_its_name_across_edits() -> None:
    """bug-008: a board a split creates carries a fresh ``new_id()``, not a
    document object ``Name``, until ``write_container`` creates its object;
    ``Session._apply`` must adopt that real ``Name`` immediately so a
    second, unrelated split's ``write_container`` call matches the first
    board by name instead of deleting and recreating it under a new one.
    Checks both that the first board's id keeps naming the same live
    object after the second split, and that every id in ``session.unit``
    equals a document object ``Name`` after each edit."""
    doc = FreeCAD.newDocument("editor_smoke_bug_008")
    try:
        container = create_unit(doc)
        doc.recompute()

        session = Session(container)
        session.open()
        try:
            bay_id = _find_bay_id(session.unit.root)
            unit_before_first_split = session.unit
            session.select(bay_id)
            assert session.split("horizontal") is None
            doc.recompute()
            _assert_unit_ids_match_document(session)
            first_board_id = _find_new_board_id(
                unit_before_first_split.root, session.unit.root
            )
            first_board_obj = doc.getObject(first_board_id)
            assert first_board_obj is not None, first_board_id

            born_as_before = properties.read_board_born_as(first_board_obj)

            other_bay_id = _find_bay_ids_in_order(session.unit.root)[-1]
            session.select(other_bay_id)
            assert session.split("vertical") is None
            doc.recompute()
            _assert_unit_ids_match_document(session)

            # The name captured right after the first split must still name
            # a live object with the same provenance, not a
            # deleted-and-recreated one under a fresh name, and session.unit
            # must still carry that id rather than a stale one.
            still_there = doc.getObject(first_board_id)
            assert still_there is not None, first_board_id
            assert properties.read_board_born_as(still_there) == born_as_before
            assert first_board_id in _board_ids(session.unit.root)
        finally:
            session.cancel()
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


def test_selection_permissions_and_split() -> None:
    """Selecting a bay permits split and not merge; splitting writes one new
    board and two bays; selecting that board permits merge; merging removes
    it and restores the original board count and names. Also covers the
    "nothing selected" refusal both buttons can hit: no id was named to
    refuse, so ``EditFailure.node_id`` is ``None`` rather than an id string."""
    doc = FreeCAD.newDocument("editor_smoke")
    try:
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
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_structurally_refused_edit_changes_nothing() -> None:
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


def test_an_unsolvable_edit_changes_nothing() -> None:
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


def test_cancel_restores_the_opening_state() -> None:
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


def test_commit_then_one_undo_reverses_the_session() -> None:
    """Commit after the same edits leaves them in place and one undo reverses
    the lot. The probe object the session made for the dimension field is
    gone after the commit and does not come back with the undo."""
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

        assert session.probe is not None
        probe_name = session.probe.Name
        session.commit()
        doc.recompute()
        assert _board_names(container) == names_after_split
        assert doc.getObject(probe_name) is None

        doc.undo()  # type: ignore[no-untyped-call]
        doc.recompute()
        assert _board_names(container) == names_before
        assert doc.getObject(probe_name) is None
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_refused_edit_after_an_accepted_edit_changes_nothing() -> None:
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


def test_split_direction_follows_the_units_depth_axis() -> None:
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


def test_selection_maps_to_its_unit() -> None:
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


def _rule_of(region: Region, region_id: str) -> SizeRule:
    """The rule of the region named ``region_id`` in ``region``'s subtree."""
    if region.id == region_id:
        return region.rule
    if isinstance(region, Division):
        for item in region.items:
            if isinstance(item, Board):
                continue
            try:
                return _rule_of(item, region_id)
            except KeyError:
                pass
    raise KeyError(region_id)


def _z_mm(container: FreeCAD.DocumentObject, name: str) -> float:
    obj = cast("_Placeable", container.Document.getObject(name))
    return float(obj.Placement.Base.z)


def _catalog_entry(
    doc: FreeCAD.Document, material_id: str
) -> properties.CatalogEntryObject:
    group = ensure_catalog(doc)
    for obj in cast("FreeCAD.DocumentObjectGroup", group).Group:
        if properties.read_entry_material_id(obj) == material_id:
            return cast("properties.CatalogEntryObject", obj)
    raise AssertionError(f"no catalog entry {material_id!r}")


def _split_bay(session: Session, bay_id: str, direction: SplitDirection) -> str:
    """Split ``bay_id`` and return the new board's id."""
    unit_before = session.unit
    session.select(bay_id)
    result = session.split(direction)
    assert result is None, result
    session.container.Document.recompute()
    return _find_new_board_id(unit_before.root, session.unit.root)


def test_dimensions_drag_basis_stock_and_untagged() -> None:
    """The dimension operations end to end on one document, all inside one
    session: a set size fixes its region and the sibling redistributes;
    toggling the basis moves no board; a drag changes the number and keeps
    the basis; an unsolvable size changes nothing; an untagged box is
    listed as left alone, survives every write, and goes only when named;
    a thicker stock then holds a spacing-based shelf and moves a clear-based
    one; and cancel restores the opening document exactly."""
    doc = FreeCAD.newDocument("editor_smoke_dimensions")
    try:
        container = create_unit(doc)
        hand_added = cast("_BoxFeature", doc.addObject("Part::Box", "HandAdded"))
        hand_added.Length = 400.0
        hand_added.Width = 5.0
        hand_added.Height = 400.0
        cast("FreeCAD.DocumentObjectGroup", container).addObject(
            cast("FreeCAD.DocumentObject", hand_added)
        )
        doc.recompute()
        snapshot_open = _board_snapshot(container)
        hand_added_before = _board_snapshot_by_name(container)["HandAdded"]
        stock = _catalog_entry(doc, DEFAULT_MATERIAL_ID)
        stock_thickness_before_mm = float(stock.Thickness)

        session = Session(container)
        session.open()
        cancelled = False
        try:
            probe = session.probe
            assert probe is not None
            probe_name = probe.Name
            assert hasattr(probe, PROBE_PROPERTY)
            assert probe not in cast("FreeCAD.DocumentObjectGroup", container).Group
            assert [e.name for e in session.left_alone] == ["HandAdded"]
            assert "panel" in session.left_alone[0].reason

            divider_id = _split_bay(
                session, _find_bay_id(session.unit.root), "horizontal"
            )
            left_bay_id, right_bay_id = _find_bay_ids_in_order(session.unit.root)
            left_shelf_id = _split_bay(session, left_bay_id, "vertical")
            right_bay_id = _find_bay_ids_in_order(session.unit.root)[-1]
            right_shelf_id = _split_bay(session, right_bay_id, "vertical")
            left_lower_id, left_upper_id, right_lower_id, _right_upper_id = (
                _find_bay_ids_in_order(session.unit.root)
            )
            assert divider_id not in (left_shelf_id, right_shelf_id)
            assert [e.name for e in session.left_alone] == ["HandAdded"]

            # A set size fixes the region; its Fill sibling takes the rest.
            session.select(left_lower_id)
            assert session.set_size(282.0) is None
            doc.recompute()
            assert session.selected_id == left_lower_id
            assert _rule_of(session.unit.root, left_lower_id) == Fixed(282.0)
            lower_mm = session.spaces[left_lower_id].size.z_mm
            upper_mm = session.spaces[left_upper_id].size.z_mm
            assert abs(lower_mm - 282.0) < 1e-6, lower_mm
            # 900 tall, less the 18mm bottom, shelf and top.
            assert abs(upper_mm - (900.0 - 3 * 18.0 - 282.0)) < 1e-6, upper_mm
            _assert_session_matches_document(session)

            # Toggling the basis moves nothing, in either direction.
            boards_before_toggle = _board_snapshot(container)
            assert session.set_basis(Basis.WITH_NEXT) is None
            doc.recompute()
            assert _rule_of(session.unit.root, left_lower_id) == Fixed(
                300.0, Basis.WITH_NEXT
            )
            assert _board_snapshot(container) == boards_before_toggle
            assert session.set_basis(Basis.CLEAR) is None
            doc.recompute()
            assert _board_snapshot(container) == boards_before_toggle
            assert session.set_basis(Basis.WITH_NEXT) is None
            doc.recompute()
            assert _board_snapshot(container) == boards_before_toggle

            # A drag changes the number and never the basis.
            shelf_z_mm = _z_mm(container, left_shelf_id)
            grab_mm = Vec3(100.0, 0.0, shelf_z_mm + 5.0)
            assert session.begin_drag(left_shelf_id, grab_mm) is None
            assert session.drag_to(Vec3(100.0, 0.0, shelf_z_mm + 30.0)) is None
            assert session.drag_to(Vec3(100.0, 0.0, shelf_z_mm + 55.0)) is None
            session.end_drag()
            doc.recompute()
            assert session.selected_id == left_lower_id
            rule = _rule_of(session.unit.root, left_lower_id)
            assert isinstance(rule, Fixed), rule
            assert rule.basis is Basis.WITH_NEXT, rule
            assert abs(rule.size_mm - 350.0) < 1e-6, rule
            assert abs(_z_mm(container, left_shelf_id) - (shelf_z_mm + 50.0)) < 1e-6
            _assert_session_matches_document(session)

            # A drag with no region before the board, or no drag at all.
            assert isinstance(session.begin_drag("bottom", grab_mm), EditFailure)
            assert isinstance(session.drag_to(grab_mm), EditFailure)

            session.select(right_lower_id)
            assert session.set_size(282.0) is None
            doc.recompute()

            # An unsolvable size leaves the last state that solved.
            snapshot_solved = _board_snapshot(container)
            too_big = session.set_size(5000.0)
            assert isinstance(too_big, EditFailure), too_big
            doc.recompute()
            assert _board_snapshot(container) == snapshot_solved
            assert _rule_of(session.unit.root, right_lower_id) == Fixed(282.0)

            # The untagged box survived every write untouched.
            assert _board_snapshot_by_name(container)["HandAdded"] == (
                hand_added_before
            )
            assert [e.name for e in session.left_alone] == ["HandAdded"]
            refused = session.remove_untagged(["bottom"])
            assert isinstance(refused, EditFailure), refused
            assert doc.getObject("bottom") is not None
            assert session.remove_untagged(["HandAdded"]) is None
            assert doc.getObject("HandAdded") is None
            assert session.left_alone == ()

            # A thicker stock: the spacing holds its shelf, the clear size
            # lets its shelf ride up with the thicker bottom board.
            left_z_mm = _z_mm(container, left_shelf_id)
            right_z_mm = _z_mm(container, right_shelf_id)
            properties.write_entry_thickness_mm(stock, 25.0)
            result = reflow_all(doc, read_catalog(ensure_catalog(doc)))
            doc.recompute()
            assert container.Name in {n for n, _r in result.succeeded}, result
            assert abs(_z_mm(container, left_shelf_id) - left_z_mm) < 1e-6
            assert abs(_z_mm(container, right_shelf_id) - (right_z_mm + 7.0)) < 1e-6

            session.cancel()
            cancelled = True
            doc.recompute()
            assert _board_snapshot(container) == snapshot_open
            assert doc.getObject(probe_name) is None
            assert float(stock.Thickness) == stock_thickness_before_mm
        finally:
            if not cancelled:
                session.cancel()
    finally:
        FreeCAD.closeDocument(doc.Name)
