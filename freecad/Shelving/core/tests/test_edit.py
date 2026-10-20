"""The core edits: refusals, round trips, and (bug-006) that every other
board and region in an edited run keeps its solved geometry."""

import copy
import dataclasses
from collections.abc import Collection, Mapping

import pytest

from freecad.Shelving.core.edit import (
    MIN_DRAG_GAP_MM,
    EditError,
    Measurement,
    fixed_point_mm,
    held_by,
    lock,
    measure,
    merge_at,
    move_board,
    region_before,
    remove_boards,
    run_axis,
    set_basis,
    set_size,
    set_thickness,
    set_unit_size,
    split_region,
    unlock,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    FixedPoint,
    FixedSide,
    Item,
    Region,
    SizeRule,
    Unit,
    Void,
    Weighted,
)
from freecad.Shelving.core.scan import DEFAULT_CLEARANCE_MM, DEFAULT_SNAP_MM
from freecad.Shelving.core.solver import LayoutSolveError, solve


def _closed_box_unit() -> Unit:
    """A single open ``Bay`` nested inside boards on every side: the shape
    ``freecad.Shelving.unit_ops._default_unit`` seeds a fresh document with."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=18.0, role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(thickness_mm=18.0, role="left_side"),
                        Bay(),
                        Board(thickness_mm=18.0, role="right_side"),
                    ],
                ),
                Board(thickness_mm=18.0, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _nested_division_unit() -> Unit:
    """A ``Division`` that itself sits beside another region in a wider run,
    so a merge at its board must operate within that outer run rather than
    at the tree root."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1800.0),
        root=Division(
            axis=Axis.X,
            items=[
                Board(thickness_mm=18.0, role="left_side"),
                Division(
                    axis=Axis.Z,
                    items=[
                        Bay(rule=Fixed(400.0)),
                        Board(thickness_mm=18.0, role="mid_shelf"),
                        Bay(),
                    ],
                ),
                Board(thickness_mm=18.0, role="right_side"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _stepped_unit() -> Unit:
    """A stepped outline: a ``Void`` alongside a ``Bay`` in the same run."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1200.0),
        root=Division(
            axis=Axis.X,
            items=[
                Bay(rule=Weighted(2.0)),
                Board(thickness_mm=18.0, role="divider"),
                Void(),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _run_unit(rule_a: SizeRule, rule_b: SizeRule, width_mm: float = 900.0) -> Unit:
    """A flat ``Axis.X`` run: three boards and two bays, ``rule_a`` and
    ``rule_b``, so splitting or merging the first bay has a second sibling
    in the same run whose geometry must not move."""
    return Unit(
        size_mm=Vec3(width_mm, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[
                Board(thickness_mm=18.0, role="left"),
                Bay(rule=rule_a),
                Board(thickness_mm=18.0, role="mid"),
                Bay(rule=rule_b),
                Board(thickness_mm=18.0, role="right"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _multi_weighted_run_unit() -> Unit:
    """A flat ``Axis.X`` run with four bays: ``Weighted(1.0)``,
    ``Weighted(2.5)``, ``Fill()``, ``Weighted(4.0)``. Editing ``bay2``
    leaves three OTHER driven siblings of different weights in the
    same run, exercising ``_other_driven_anchor`` past the trivial
    single-other-sibling case every other fixture in this module gives it."""
    return Unit(
        size_mm=Vec3(2400.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[
                Board(thickness_mm=18.0, role="b0"),
                Bay(rule=Weighted(1.0), id="bay1"),
                Board(thickness_mm=18.0, role="b1"),
                Bay(rule=Weighted(2.5), id="bay2"),
                Board(thickness_mm=18.0, role="b2"),
                Bay(rule=Fill(), id="bay3"),
                Board(thickness_mm=18.0, role="b3"),
                Bay(rule=Weighted(4.0), id="bay4"),
                Board(thickness_mm=18.0, role="b4"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _fixed_and_weighted_merge_unit() -> Unit:
    """A flat ``Axis.X`` run whose ``merge_board`` sits between a ``Fixed``
    bay and a ``Weighted`` one, with two more ``Weighted`` bays of
    different weights further down the same run: the non-trivial
    ``Weighted`` branch of ``_merged_rule`` (the two merging neighbors are
    not both ``Fixed``), anchored against an ``_other_driven_anchor`` that
    has more than one candidate to choose from."""
    return Unit(
        size_mm=Vec3(2400.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[
                Board(thickness_mm=18.0, role="b0"),
                Bay(rule=Fixed(300.0), id="fixed_bay"),
                Board(thickness_mm=18.0, role="merge_board", id="merge_board"),
                Bay(rule=Weighted(2.0), id="weighted_bay"),
                Board(thickness_mm=18.0, role="b1"),
                Bay(rule=Weighted(3.5), id="bay_c"),
                Board(thickness_mm=18.0, role="b2"),
                Bay(rule=Weighted(1.5), id="bay_d"),
                Board(thickness_mm=18.0, role="b3"),
            ],
        ),
        depth_axis=Axis.Y,
    )


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


def _find_bay_ids_in_order(region: Region) -> list[str]:
    """Every ``Bay`` id in ``region``'s subtree, depth first: within one
    ``Division``, item order is solved-position order (``solve`` places a
    run's items from the axis minimum up), so the bays a single split just
    produced come back lower-position first."""
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


def _find_region(region: Region, node_id: str) -> Region | None:
    """The ``Region`` in ``region``'s subtree (``region`` included) whose id
    is ``node_id``, or ``None`` when nothing matches."""
    if region.id == node_id:
        return region
    if not isinstance(region, Division):
        return None
    for item in region.items:
        if not isinstance(item, Board):
            found = _find_region(item, node_id)
            if found is not None:
                return found
    return None


def _find_parent(region: Region, node_id: str) -> Division | None:
    """The ``Division`` in ``region``'s subtree directly holding the item
    (``Region`` or ``Board``) named ``node_id``, or ``None`` when nothing
    matches."""
    if not isinstance(region, Division):
        return None
    if any(item.id == node_id for item in region.items):
        return region
    for item in region.items:
        if not isinstance(item, Board):
            found = _find_parent(item, node_id)
            if found is not None:
                return found
    return None


def _rule_shape(rule: SizeRule) -> tuple[object, ...]:
    match rule:
        case Fixed(size_mm=size_mm, basis=basis):
            return ("fixed", size_mm, basis)
        case Weighted(weight=weight):
            return ("weighted", weight)
        case Fill():
            return ("fill",)


def _item_shape(item: Item) -> object:
    if isinstance(item, Board):
        return ("board", item.role, item.thickness_mm, _rule_shape(item.rule or Fill()))
    return _region_shape(item)


def _region_shape(region: Region) -> object:
    if isinstance(region, Bay):
        return ("bay", _rule_shape(region.rule))
    if isinstance(region, Void):
        return ("void", _rule_shape(region.rule))
    return (
        "division",
        region.axis,
        _rule_shape(region.rule),
        tuple(_item_shape(item) for item in region.items),
    )


def _find_board(region: Region, board_id: str) -> Board:
    assert isinstance(region, Division)
    for item in region.items:
        if isinstance(item, Board):
            if item.id == board_id:
                return item
        elif isinstance(item, Division):
            try:
                return _find_board(item, board_id)
            except LookupError:
                pass
    raise LookupError(board_id)


def _split_then_merge_round_trips(unit: Unit) -> None:
    bay_id = _find_bay_id(unit.root)
    split = split_region(unit, bay_id, Axis.Z)
    board_id = _new_board_id(unit, split)
    merged = merge_at(split, board_id)
    assert _region_shape(merged.root) == _region_shape(unit.root)


def _new_board_id(before: Unit, after: Unit) -> str:
    """The id of the one ``Board`` present in ``after`` and absent from
    ``before``: the board :func:`split_region` just created."""
    before_ids = _all_board_ids(before.root)
    after_ids = _all_board_ids(after.root)
    new_ids = after_ids - before_ids
    assert len(new_ids) == 1, new_ids
    return next(iter(new_ids))


def _all_board_ids(region: Region) -> set[str]:
    if isinstance(region, Division):
        ids: set[str] = set()
        for item in region.items:
            if isinstance(item, Board):
                ids.add(item.id)
            else:
                ids |= _all_board_ids(item)
        return ids
    return set()


def _has_same_axis_nesting(region: Region) -> bool:
    """Whether ``region``'s subtree nests a ``Division`` directly inside
    another ``Division`` sharing its axis: the shape rescanning cannot tell
    apart from a flat run of the same boards (bug-006), which
    ``split_region`` must never produce."""
    if not isinstance(region, Division):
        return False
    for item in region.items:
        if isinstance(item, Division):
            if item.axis == region.axis:
                return True
            if _has_same_axis_nesting(item):
                return True
    return False


def _spaces_equal(a: Space, b: Space, *, tol_mm: float = 1e-6) -> bool:
    return (
        abs(a.origin.x_mm - b.origin.x_mm) <= tol_mm
        and abs(a.origin.y_mm - b.origin.y_mm) <= tol_mm
        and abs(a.origin.z_mm - b.origin.z_mm) <= tol_mm
        and abs(a.size.x_mm - b.size.x_mm) <= tol_mm
        and abs(a.size.y_mm - b.size.y_mm) <= tol_mm
        and abs(a.size.z_mm - b.size.z_mm) <= tol_mm
    )


def _assert_surviving_boards_unchanged(
    spaces_before: Mapping[str, Space], unit_after: Unit
) -> None:
    """Every board id present both in ``spaces_before`` and in
    ``unit_after`` solves to the same ``Space``, within ``1e-6`` mm, as it
    did before the edit that produced ``unit_after``. A region id is never
    checked this way: split and merge both mint fresh region ids for
    whatever they touch, so only a board can "survive"."""
    spaces_after = solve(unit_after)
    for board_id in _all_board_ids(unit_after.root):
        if board_id not in spaces_before:
            continue
        assert _spaces_equal(spaces_before[board_id], spaces_after[board_id]), (
            board_id,
            spaces_before[board_id],
            spaces_after[board_id],
        )


# --- split_region refusals ---------------------------------------------------


def test_split_region_refuses_a_void() -> None:
    void = Void()
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=void)
    with pytest.raises(EditError) as exc_info:
        split_region(unit, void.id, Axis.X)
    assert exc_info.value.node_id == void.id
    assert void.id not in str(exc_info.value)


def test_split_region_refuses_a_division() -> None:
    unit = _closed_box_unit()
    assert isinstance(unit.root, Division)
    with pytest.raises(EditError) as exc_info:
        split_region(unit, unit.root.id, Axis.X)
    assert exc_info.value.node_id == unit.root.id
    assert unit.root.id not in str(exc_info.value)


def test_split_region_refuses_an_unknown_id() -> None:
    unit = _closed_box_unit()
    with pytest.raises(EditError) as exc_info:
        split_region(unit, "no-such-id", Axis.X)
    assert exc_info.value.node_id == "no-such-id"
    assert "no-such-id" not in str(exc_info.value)


def test_split_region_refuses_a_bay_too_small_for_the_divider() -> None:
    """A splice-case split (the bay's parent already runs along the split
    axis) whose opening cannot fit the new board and still leave two
    positive-sized halves is refused by the bay's own id, not left to a
    downstream ``Fixed``/``Weighted`` construction to crash on, in a message
    that does not show that id."""
    bay = Bay(rule=Fixed(10.0))
    unit = Unit(
        size_mm=Vec3(46.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[
                Board(thickness_mm=18.0, role="left"),
                bay,
                Board(thickness_mm=18.0, role="right"),
            ],
        ),
    )
    with pytest.raises(EditError) as exc_info:
        split_region(unit, bay.id, Axis.X)
    assert exc_info.value.node_id == bay.id
    assert bay.id not in str(exc_info.value)


# --- merge_at refusals -------------------------------------------------------


def test_merge_at_refuses_an_unknown_id() -> None:
    unit = _closed_box_unit()
    with pytest.raises(EditError) as exc_info:
        merge_at(unit, "no-such-id")
    assert exc_info.value.node_id == "no-such-id"
    assert "no-such-id" not in str(exc_info.value)


def test_merge_at_refuses_a_board_with_no_neighbor_on_one_side() -> None:
    edge_board = Board(thickness_mm=18.0, role="edge")
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(axis=Axis.X, items=[edge_board, Bay()]),
    )
    with pytest.raises(EditError) as exc_info:
        merge_at(unit, edge_board.id)
    assert exc_info.value.node_id == edge_board.id
    assert edge_board.id not in str(exc_info.value)


def test_merge_at_refuses_a_board_flanked_by_another_board() -> None:
    middle_board = Board(thickness_mm=18.0, role="middle")
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[Board(thickness_mm=18.0, role="left"), middle_board, Bay()],
        ),
    )
    with pytest.raises(EditError) as exc_info:
        merge_at(unit, middle_board.id)
    assert exc_info.value.node_id == middle_board.id
    assert middle_board.id not in str(exc_info.value)


# --- split then merge round-trips the tree shape -----------------------------


def test_split_then_merge_round_trips_a_closed_box() -> None:
    _split_then_merge_round_trips(_closed_box_unit())


def test_split_then_merge_round_trips_a_nested_division() -> None:
    _split_then_merge_round_trips(_nested_division_unit())


def test_split_then_merge_round_trips_a_stepped_unit() -> None:
    _split_then_merge_round_trips(_stepped_unit())


# --- neither edit mutates its argument ---------------------------------------


def test_split_region_leaves_the_argument_unit_unchanged() -> None:
    unit = _closed_box_unit()
    before = copy.deepcopy(unit)
    bay_id = _find_bay_id(unit.root)
    split_region(unit, bay_id, Axis.X)
    assert _region_shape(unit.root) == _region_shape(before.root)


def test_merge_at_leaves_the_argument_unit_unchanged() -> None:
    unit = _closed_box_unit()
    bay_id = _find_bay_id(unit.root)
    split = split_region(unit, bay_id, Axis.X)
    before = copy.deepcopy(split)
    board_id = _new_board_id(unit, split)
    merge_at(split, board_id)
    assert _region_shape(split.root) == _region_shape(before.root)


# --- split_region's own result, not only what merge_at can invert -----------


def test_split_region_produces_a_division_of_bay_board_bay() -> None:
    """A cross-axis split (the bay's parent runs on a different axis) nests
    a new ``Division`` on the requested axis, carrying the split ``Bay``'s
    own rule; its items are ``Bay(Fill)``, ``Board``, ``Bay(Fill)``: a fresh
    run has no other region to preserve, so both halves are always
    ``Fill`` regardless of the split bay's own rule. The parent's untouched
    siblings are the same objects split_region reused, not copies of them."""
    unit = _closed_box_unit()
    bay_id = _find_bay_id(unit.root)
    original_bay = _find_region(unit.root, bay_id)
    assert isinstance(original_bay, Bay)
    original_bay = dataclasses.replace(original_bay, rule=Weighted(3.0))
    unit = dataclasses.replace(
        unit, root=_replace_node(unit.root, bay_id, original_bay)
    )
    parent = _find_parent(unit.root, bay_id)
    assert isinstance(parent, Division)
    index = next(i for i, item in enumerate(parent.items) if item.id == bay_id)
    siblings_before = [item for i, item in enumerate(parent.items) if i != index]

    split = split_region(unit, bay_id, Axis.Z)

    new_parent = _find_region(split.root, parent.id)
    assert isinstance(new_parent, Division)
    division = new_parent.items[index]
    assert isinstance(division, Division)
    assert division.axis == Axis.Z
    assert division.rule == original_bay.rule

    assert len(division.items) == 3
    left, board, right = division.items
    assert isinstance(left, Bay) and left.rule == Fill()
    assert isinstance(right, Bay) and right.rule == Fill()
    assert isinstance(board, Board)
    assert board.thickness_mm == 18.0

    siblings_after = [item for i, item in enumerate(new_parent.items) if i != index]
    assert siblings_after == siblings_before
    for before_item, after_item in zip(siblings_before, siblings_after, strict=True):
        assert before_item is after_item


def test_split_region_takes_thickness_and_stock_from_a_parallel_board() -> None:
    """The bay sits between the sides, so a new ``Axis.Z`` board's only
    parallel boards are the bottom and the top, both carcass and equally
    near; the first in tree order wins."""
    unit = _closed_box_unit()
    assert isinstance(unit.root, Division)
    bottom, _middle, top = unit.root.items
    assert isinstance(bottom, Board) and isinstance(top, Board)
    unit.root.items[0] = dataclasses.replace(bottom, thickness_mm=25.0)
    unit.root.items[2] = dataclasses.replace(top, thickness_mm=25.0)
    bay_id = _find_bay_id(unit.root)
    split = split_region(unit, bay_id, Axis.Z)
    board = _find_board(split.root, _new_board_id(unit, split))
    assert board.thickness_mm == 25.0
    assert board.stock_from == bottom.id
    assert board.role == ""


def test_split_region_refuses_a_unit_with_no_board() -> None:
    bay = Bay(rule=Fixed(500.0))
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=bay)
    with pytest.raises(EditError) as exc_info:
        split_region(unit, bay.id, Axis.X)
    assert exc_info.value.node_id == bay.id


def _replace_node(region: Region, node_id: str, replacement: Region) -> Region:
    """``region`` with the node named ``node_id`` replaced by ``replacement``,
    used only to seed a non-default rule onto the bay a test is about to
    split, the same shape :mod:`freecad.Shelving.core.edit`'s own recursion
    uses."""
    if region.id == node_id:
        return replacement
    if not isinstance(region, Division):
        return region
    new_items: list[Item] = []
    for item in region.items:
        if isinstance(item, Board):
            new_items.append(item)
        else:
            new_items.append(_replace_node(item, node_id, replacement))
    return dataclasses.replace(region, items=new_items)


# --- bug-006: a same-axis split/merge never moves the rest of its run -------


def _check_split_and_merge_preserve_the_other_bay(
    rule_a: SizeRule, rule_b: SizeRule, width_mm: float = 900.0
) -> None:
    unit = _run_unit(rule_a, rule_b, width_mm)
    assert isinstance(unit.root, Division)
    spaces_before = solve(unit)
    bay_a = unit.root.items[1]
    assert isinstance(bay_a, Bay)
    bay_b = unit.root.items[3]
    assert isinstance(bay_b, Bay)

    split = split_region(unit, bay_a.id, Axis.X)
    assert not _has_same_axis_nesting(split.root)
    _assert_surviving_boards_unchanged(spaces_before, split)
    spaces_after_split = solve(split)
    assert _spaces_equal(spaces_after_split[bay_b.id], spaces_before[bay_b.id])

    board_id = _new_board_id(unit, split)
    merged = merge_at(split, board_id)
    assert isinstance(merged.root, Division)
    # Tree shape round-trips by item kind (Board, Bay, Board, Bay, Board);
    # the merged bay's *rule* need not come back as the literal Fill() or
    # Weighted() it started as (a Weighted anchor elsewhere in the run can
    # solve it to a numerically equivalent but differently-typed rule), only
    # its solved geometry, checked below, must round-trip exactly.
    assert [type(item).__name__ for item in merged.root.items] == [
        type(item).__name__ for item in unit.root.items
    ]
    _assert_surviving_boards_unchanged(spaces_after_split, merged)
    spaces_after_merge = solve(merged)
    assert _spaces_equal(spaces_after_merge[bay_b.id], spaces_before[bay_b.id])
    merged_bay_a = merged.root.items[1]
    assert isinstance(merged_bay_a, Bay)
    assert _spaces_equal(spaces_after_merge[merged_bay_a.id], spaces_before[bay_a.id])


def test_split_and_merge_preserve_the_other_bay_in_a_fill_run() -> None:
    _check_split_and_merge_preserve_the_other_bay(Fill(), Fill())


def test_split_and_merge_preserve_the_other_bay_in_a_weighted_run() -> None:
    _check_split_and_merge_preserve_the_other_bay(Weighted(1.5), Weighted(2.5))


def test_split_and_merge_preserve_the_other_bay_in_a_fixed_run() -> None:
    # left + mid + right boards (18mm each) plus both Fixed bays, with no
    # slack left over: an all-Fixed run must sum exactly to the span.
    _check_split_and_merge_preserve_the_other_bay(
        Fixed(300.0), Fixed(250.0), width_mm=3 * 18.0 + 300.0 + 250.0
    )


def test_split_and_merge_preserve_the_other_bay_in_a_mixed_run() -> None:
    """``rule_b`` is ``Fixed``, not driven, so splitting or merging
    ``rule_a`` finds no other driven sibling to solve a weight against and
    falls back to ``Fill`` for the driven side, per
    :func:`~freecad.Shelving.core.edit._other_driven_anchor`."""
    _check_split_and_merge_preserve_the_other_bay(Weighted(1.0), Fixed(250.0))


def test_split_preserves_a_weighted_sibling_across_an_intervening_fixed_bay() -> None:
    """The anchor search skips a ``Fixed`` sibling in between and keeps
    going to find the run's one driven item."""
    unit = Unit(
        size_mm=Vec3(1200.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[
                Board(thickness_mm=18.0, role="left"),
                Bay(rule=Weighted(1.0), id="bay_a"),
                Board(thickness_mm=18.0, role="mid1"),
                Bay(rule=Fixed(200.0)),
                Board(thickness_mm=18.0, role="mid2"),
                Bay(rule=Fill(), id="bay_c"),
                Board(thickness_mm=18.0, role="right"),
            ],
        ),
        depth_axis=Axis.Y,
    )
    spaces_before = solve(unit)

    split = split_region(unit, "bay_a", Axis.X)
    assert not _has_same_axis_nesting(split.root)
    _assert_surviving_boards_unchanged(spaces_before, split)
    spaces_after = solve(split)
    assert _spaces_equal(spaces_after["bay_c"], spaces_before["bay_c"])


def test_split_region_bug_006_sequence_preserves_every_prior_boards_geometry() -> None:
    """The exact bug-006 repro run directly against ``split_region``, no
    rescan involved: add a divider (splice, the bay's parent already runs
    on that axis), a shelf on the left (nest, a different axis), then a
    shelf top-left (splice again, the just-nested division now shares its
    axis). Every board added by an earlier step keeps its solved space
    through every later one, and the final tree nests no same-axis
    ``Division`` inside another."""
    unit = _closed_box_unit()
    spaces = solve(unit)

    bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, bay_id, Axis.X)
    _assert_surviving_boards_unchanged(spaces, unit)
    assert not _has_same_axis_nesting(unit.root)
    spaces = solve(unit)

    left_bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, left_bay_id, Axis.Z)
    _assert_surviving_boards_unchanged(spaces, unit)
    assert not _has_same_axis_nesting(unit.root)
    spaces = solve(unit)

    # The shelf-left split just nested a fresh Axis.Z Division holding the
    # lower and upper halves of the old left bay, in that solved-position
    # order; index [1] is the upper (top-left) one, not [0] (bottom-left).
    ordered_bay_ids = _find_bay_ids_in_order(unit.root)
    lower_left_bay_id, topleft_bay_id = ordered_bay_ids[0], ordered_bay_ids[1]
    assert spaces[topleft_bay_id].origin.z_mm > spaces[lower_left_bay_id].origin.z_mm
    unit = split_region(unit, topleft_bay_id, Axis.Z)
    _assert_surviving_boards_unchanged(spaces, unit)
    assert not _has_same_axis_nesting(unit.root)


# --- three or more other driven siblings -------------------------------------


def test_split_preserves_three_other_weighted_siblings_of_different_weights() -> None:
    """Splitting ``bay2`` in a four-bay run leaves ``bay1`` (``Weighted(1.0)``),
    ``bay3`` (``Fill()``) and ``bay4`` (``Weighted(4.0)``) all at their
    pre-split ``Space``, not only the single other driven sibling every other
    split fixture in this module gives ``_other_driven_anchor``."""
    unit = _multi_weighted_run_unit()
    spaces_before = solve(unit)

    split = split_region(unit, "bay2", Axis.X)
    assert not _has_same_axis_nesting(split.root)
    _assert_surviving_boards_unchanged(spaces_before, split)
    spaces_after = solve(split)
    for bay_id in ("bay1", "bay3", "bay4"):
        assert _spaces_equal(spaces_after[bay_id], spaces_before[bay_id]), bay_id


def test_merge_preserves_three_other_weighted_siblings_of_different_weights() -> None:
    """The matching merge back, in the same four-bay run: splitting ``bay2``
    then merging at the board the split just added restores ``bay2``'s own
    geometry, and still leaves ``bay1``, ``bay3`` and ``bay4`` untouched."""
    unit = _multi_weighted_run_unit()
    spaces_before = solve(unit)

    split = split_region(unit, "bay2", Axis.X)
    board_id = _new_board_id(unit, split)
    spaces_after_split = solve(split)

    merged = merge_at(split, board_id)
    assert not _has_same_axis_nesting(merged.root)
    _assert_surviving_boards_unchanged(spaces_after_split, merged)
    spaces_after_merge = solve(merged)
    for bay_id in ("bay1", "bay3", "bay4"):
        assert _spaces_equal(spaces_after_merge[bay_id], spaces_before[bay_id]), bay_id
    merged_root = merged.root
    assert isinstance(merged_root, Division)
    merged_bay2 = merged_root.items[3]
    assert isinstance(merged_bay2, Bay)
    assert _spaces_equal(spaces_after_merge[merged_bay2.id], spaces_before["bay2"])


def test_merge_a_fixed_bay_with_a_weighted_one_leaves_other_weighted_siblings() -> None:
    """Merging away ``merge_board`` combines a ``Fixed`` bay with a
    ``Weighted`` one, the non-``Fixed``/``Fixed`` branch of
    ``_merged_rule``, while ``bay_c`` and ``bay_d``, two more ``Weighted``
    bays of different weights elsewhere in the run, keep their pre-merge
    ``Space`` exactly."""
    unit = _fixed_and_weighted_merge_unit()
    spaces_before = solve(unit)

    merged = merge_at(unit, "merge_board")
    assert not _has_same_axis_nesting(merged.root)
    _assert_surviving_boards_unchanged(spaces_before, merged)
    spaces_after = solve(merged)
    for bay_id in ("bay_c", "bay_d"):
        assert _spaces_equal(spaces_after[bay_id], spaces_before[bay_id]), bay_id

    merged_root = merged.root
    assert isinstance(merged_root, Division)
    merged_bay = merged_root.items[1]
    assert isinstance(merged_bay, Bay)
    assert isinstance(merged_bay.rule, Weighted)
    fixed_extent_mm = spaces_before["fixed_bay"].extent_mm(0)
    weighted_extent_mm = spaces_before["weighted_bay"].extent_mm(0)
    board_extent_mm = spaces_before["merge_board"].extent_mm(0)
    expected_extent_mm = fixed_extent_mm + board_extent_mm + weighted_extent_mm
    assert abs(spaces_after[merged_bay.id].extent_mm(0) - expected_extent_mm) <= 1e-6


# --- split's own item shape at the splice site --------------------------------


def test_split_region_spliced_items_are_bay_board_bay_in_place() -> None:
    """In the splice case (the bay's parent already runs on the split
    axis), the parent's ``items`` gain exactly
    ``Bay, Board, Bay`` at the split bay's old slot, no more, no fewer."""
    unit = _run_unit(Weighted(1.5), Weighted(2.5))
    assert isinstance(unit.root, Division)
    bay_a = unit.root.items[1]
    assert isinstance(bay_a, Bay)
    index = 1

    split = split_region(unit, bay_a.id, Axis.X)
    assert isinstance(split.root, Division)
    spliced = split.root.items[index : index + 3]
    kinds = [type(item).__name__ for item in spliced]
    assert kinds == ["Bay", "Board", "Bay"], kinds
    # Nothing else in the run moved: nothing before or after the spliced
    # slot changed identity or count.
    assert len(split.root.items) == len(unit.root.items) + 2
    assert split.root.items[:index] == unit.root.items[:index]
    assert split.root.items[index + 3 :] == unit.root.items[index + 1 :]


# --- a merge's collapse never nests a same-axis Division either -------------


def _bare_column_unit() -> Unit:
    """A ``Division`` (axis ``Z``) whose middle item is an ``Axis.X``
    ``Division`` holding a single bare ``Bay``: no side boards flank it, so
    a splice-then-nest-then-collapse sequence on that bay can reduce the
    ``Axis.X`` division to one item and promote it straight into the
    ``Axis.Z`` run above, the same axis as the promoted item once the
    intervening split nests a ``Division`` sharing it. A second ``Weighted``
    bay elsewhere in the ``Axis.Z`` run gives the promoted items' own
    ``_other_driven_anchor`` something real to solve against."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 1800.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=18.0, role="bottom"),
                Division(axis=Axis.X, items=[Bay(rule=Weighted(1.0))]),
                Board(thickness_mm=18.0, role="mid"),
                Bay(rule=Weighted(2.0)),
                Board(thickness_mm=18.0, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def test_merge_collapse_never_nests_a_same_axis_division_either() -> None:
    """The divider, shelf left, delete divider sequence: add a divider
    (splice, the bare column's own axis), a shelf on its left half (nest,
    a different axis), then delete the divider. The delete collapses the
    ``Axis.X`` division to its one surviving item, the ``Axis.Z`` division
    ``shelf left`` just nested, which shares the grandparent (``Axis.Z``)
    run's own axis; that promoted division's items must splice into the
    grandparent's run rather than nest inside it, and every surviving
    board (the unit's ``bottom``, ``mid`` and ``top``) must keep its
    solved ``Space`` throughout."""
    unit = _bare_column_unit()
    spaces_before_divider = solve(unit)

    boards_before_divider = _all_board_ids(unit.root)
    bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, bay_id, Axis.X)
    assert not _has_same_axis_nesting(unit.root)
    divider_id = next(iter(_all_board_ids(unit.root) - boards_before_divider))
    _assert_surviving_boards_unchanged(spaces_before_divider, unit)
    spaces_after_divider = solve(unit)

    left_bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, left_bay_id, Axis.Z)
    assert not _has_same_axis_nesting(unit.root)
    _assert_surviving_boards_unchanged(spaces_after_divider, unit)

    merged = merge_at(unit, divider_id)
    assert not _has_same_axis_nesting(merged.root)
    _assert_surviving_boards_unchanged(spaces_before_divider, merged)

    merged_root = merged.root
    assert isinstance(merged_root, Division)
    assert merged_root.axis == Axis.Z
    # The promoted division's items spliced straight into the Axis.Z run in
    # place of the collapsed Axis.X division: no nested Division survives.
    assert all(not isinstance(item, Division) for item in merged_root.items)


# --- a collapse with no other driven sibling keeps existing ratios ----------


def _two_unequal_fixed_openings_unit() -> Unit:
    """Two unequal openings, both ``Fixed``, as two typed sizes leave them:
    no bay in this run is driven, so every edit below exercises
    ``_splice_collapsed_child``'s ``anchor is None`` branch, the one every
    other merge-collapse fixture in this module leaves untested."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 350.0 + 400.0 + 3 * 18.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=18.0, role="bottom"),
                Bay(rule=Fixed(350.0), id="lower"),
                Board(thickness_mm=18.0, role="shelf"),
                Bay(rule=Fixed(400.0), id="upper"),
                Board(thickness_mm=18.0, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def test_merge_collapse_with_no_other_driven_sibling_moves_no_board() -> None:
    """A divider in the lower opening (nest, a
    different axis than the Z-axis column), a shelf left of the divider
    (nest again, a different axis than the divider's X-axis division), then
    another shelf in the upper-left bay that split just made (splice: its
    parent now shares the shelf's own Z axis), then delete the divider. The
    delete collapses the divider's ``Axis.X`` division down to the "shelf
    left" division alone, which shares the column's own ``Axis.Z`` axis and
    must splice into it rather than nest. With both openings ``Fixed``,
    nothing else in the column is driven, so the splice has no other driven
    sibling to solve a fresh weight against and must keep the two shelf
    boards' own ratio instead of equalizing them to a shared ``Fill()``
    share, which would move both (the bug this test reproduces)."""
    unit = _two_unequal_fixed_openings_unit()
    spaces_before_divider = solve(unit)
    boards_before_divider = _all_board_ids(unit.root)

    unit = split_region(unit, "lower", Axis.X)
    assert not _has_same_axis_nesting(unit.root)
    _assert_surviving_boards_unchanged(spaces_before_divider, unit)
    divider_id = next(iter(_all_board_ids(unit.root) - boards_before_divider))

    root = unit.root
    assert isinstance(root, Division)
    x_division = root.items[1]
    assert isinstance(x_division, Division) and x_division.axis == Axis.X
    left_bay = x_division.items[0]
    assert isinstance(left_bay, Bay)

    spaces_after_divider = solve(unit)
    unit = split_region(unit, left_bay.id, Axis.Z)
    assert not _has_same_axis_nesting(unit.root)
    _assert_surviving_boards_unchanged(spaces_after_divider, unit)

    root = unit.root
    assert isinstance(root, Division)
    x_division = root.items[1]
    assert isinstance(x_division, Division)
    p_division = x_division.items[0]
    assert isinstance(p_division, Division) and p_division.axis == Axis.Z
    lower_left_bay, shelf_board, upper_left_bay = p_division.items
    assert isinstance(lower_left_bay, Bay)
    assert isinstance(shelf_board, Board)
    assert isinstance(upper_left_bay, Bay)

    spaces_after_shelf_left = solve(unit)
    assert (
        spaces_after_shelf_left[upper_left_bay.id].origin.z_mm
        > spaces_after_shelf_left[lower_left_bay.id].origin.z_mm
    )
    unit = split_region(unit, upper_left_bay.id, Axis.Z)
    assert not _has_same_axis_nesting(unit.root)
    _assert_surviving_boards_unchanged(spaces_after_shelf_left, unit)
    other_board_ids = {divider_id, shelf_board.id} | boards_before_divider
    board_id_2 = next(iter(_all_board_ids(unit.root) - other_board_ids))

    # merge_at unifies the divider's left and right openings into one region
    # that spans the divider's full pre-merge width, exactly as the divider's
    # removal should: that width change (size.x_mm) reaches every board
    # inside the promoted "shelf left" division, including shelf_board and
    # board_id_2, and is not what this test checks. What must not move is the
    # column's Axis.Z share those two boards divide up between them: their
    # z origin and z extent, which _splice_collapsed_child's anchor-is-None
    # branch (the fix under test) must reproduce exactly.
    spaces_before_delete = solve(unit)
    merged = merge_at(unit, divider_id)
    assert not _has_same_axis_nesting(merged.root)
    _assert_surviving_boards_unchanged(spaces_before_divider, merged)
    spaces_after_merge = solve(merged)
    for board_id in (shelf_board.id, board_id_2):
        before_space = spaces_before_delete[board_id]
        after_space = spaces_after_merge[board_id]
        assert abs(before_space.origin.z_mm - after_space.origin.z_mm) <= 1e-6, board_id
        assert abs(before_space.size.z_mm - after_space.size.z_mm) <= 1e-6, board_id


# --- set_size / set_basis / move_board ---------------------------------------


def _column_unit(lower_rule: SizeRule, thickness_mm: float = 18.0) -> Unit:
    """One vertical run of ``thickness_mm`` boards: bottom, a lower bay ruled
    by ``lower_rule``, a shelf, a ``Fill`` upper bay, a ``Weighted`` top bay,
    and a top. Every node carries a fixed id so a test can name it."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=thickness_mm, id="bottom"),
                Bay(id="lower", rule=lower_rule),
                Board(thickness_mm=thickness_mm, id="shelf"),
                Bay(id="upper"),
                Board(thickness_mm=thickness_mm, id="shelf2"),
                Void(id="topmost", rule=Weighted(2.0)),
                Board(thickness_mm=thickness_mm, id="top"),
            ],
            id="column",
        ),
        depth_axis=Axis.Y,
    )


def _rules_by_id(region: Region) -> dict[str, SizeRule]:
    out = {region.id: region.rule}
    if isinstance(region, Division):
        for item in region.items:
            if not isinstance(item, Board):
                out.update(_rules_by_id(item))
    return out


def _assert_same_layout(before: Unit, after: Unit) -> None:
    spaces_before = solve(before)
    spaces_after = solve(after)
    assert spaces_before.keys() == spaces_after.keys()
    for node_id, space in spaces_before.items():
        assert _spaces_equal(space, spaces_after[node_id]), (node_id, space)


def test_set_unit_size_changes_only_the_outer_size() -> None:
    unit = _column_unit(Fill())
    resized = set_unit_size(unit, Vec3(600.0, 300.0, 1000.0))
    assert resized.size_mm == Vec3(600.0, 300.0, 1000.0)
    assert resized.root is unit.root
    assert unit.size_mm == Vec3(600.0, 300.0, 900.0)
    assert solve(resized)["top"].origin.z_mm == pytest.approx(1000.0 - 18.0)


@pytest.mark.parametrize(
    "size_mm",
    [
        Vec3(0.0, 300.0, 900.0),
        Vec3(600.0, -1.0, 900.0),
        Vec3(600.0, 300.0, 0.0),
    ],
)
def test_set_unit_size_refuses_a_nonpositive_axis(size_mm: Vec3) -> None:
    unit = _column_unit(Fill())
    with pytest.raises(EditError) as err:
        set_unit_size(unit, size_mm)
    assert err.value.node_id == unit.id


_FIXED_SIDES: tuple[FixedSide, ...] = ("min", "center", "max")


def _solved_extent_mm(unit: Unit, axis: Axis) -> tuple[float, float]:
    """The low and high faces of every board ``unit`` solves to, along
    ``axis``."""
    spaces = solve(unit)
    index = axis.component_index
    boards = [spaces[board_id] for board_id in ("bottom", "shelf", "shelf2", "top")]
    low_mm = min(space.origin_mm(index) for space in boards)
    high_mm = max(space.max_corner().component_mm(index) for space in boards)
    return low_mm, high_mm


@pytest.mark.parametrize("side", _FIXED_SIDES)
@pytest.mark.parametrize("axis", list(Axis))
def test_set_unit_size_keeps_the_fixed_side_where_it_was(
    axis: Axis, side: FixedSide
) -> None:
    """Growing and shrinking a unit offset from its frame's origin along
    ``axis`` leaves the low face, the midpoint or the high face there where
    it was, and leaves the other two axes' faces alone."""
    unit = dataclasses.replace(
        _column_unit(Fill()),
        position_mm=Vec3(100.0, -300.0, 50.0),
        fixed_point=FixedPoint().with_side(axis, side),
    )
    before = {other: _solved_extent_mm(unit, other) for other in Axis}
    low_mm, high_mm = before[axis]
    fixed_before_mm = {"min": low_mm, "center": (low_mm + high_mm) / 2, "max": high_mm}
    index = axis.component_index
    for change_mm in (150.0, -100.0):
        components = [unit.size_mm.x_mm, unit.size_mm.y_mm, unit.size_mm.z_mm]
        components[index] += change_mm
        resized = set_unit_size(unit, Vec3(*components))
        new_low_mm, new_high_mm = _solved_extent_mm(resized, axis)
        assert new_high_mm - new_low_mm == pytest.approx(components[index])
        fixed_after_mm = {
            "min": new_low_mm,
            "center": (new_low_mm + new_high_mm) / 2,
            "max": new_high_mm,
        }
        assert abs(fixed_after_mm[side] - fixed_before_mm[side]) <= 1e-6
        assert fixed_point_mm(resized) == fixed_point_mm(unit)
        for other in set(Axis) - {axis}:
            assert _solved_extent_mm(resized, other) == pytest.approx(
                before[other], abs=1e-6
            )


def test_a_unit_fixes_its_minimum_corner_unless_told_otherwise() -> None:
    unit = _column_unit(Fill())
    assert unit.fixed_point == FixedPoint("min", "min", "min")
    assert fixed_point_mm(unit) == unit.position_mm


def test_fixed_point_mm_measures_each_side_on_the_units_box() -> None:
    unit = dataclasses.replace(
        _column_unit(Fill()),
        position_mm=Vec3(100.0, -300.0, 50.0),
        fixed_point=FixedPoint("max", "center", "min"),
    )
    assert fixed_point_mm(unit) == Vec3(700.0, -150.0, 50.0)


def test_set_size_fixes_the_region_and_leaves_every_sibling_rule() -> None:
    unit = _column_unit(Fill())
    edited = set_size(unit, "upper", 250.0, Basis.WITH_NEXT)
    rules_before = _rules_by_id(unit.root)
    rules_after = _rules_by_id(edited.root)
    assert rules_after.pop("upper") == Fixed(250.0, Basis.WITH_NEXT)
    rules_before.pop("upper")
    assert rules_after == rules_before
    spaces = solve(edited)
    # 250mm top face to top face: the upper bay plus the 18mm shelf2 above it.
    assert spaces["upper"].size.z_mm + spaces["shelf2"].size.z_mm == pytest.approx(
        250.0
    )


def test_set_size_leaves_the_argument_unit_unchanged() -> None:
    unit = _column_unit(Fill())
    snapshot = copy.deepcopy(unit)
    set_size(unit, "lower", 300.0, Basis.CLEAR)
    assert unit == snapshot


@pytest.mark.parametrize("size_mm", [0.0, -12.7])
def test_set_size_refuses_a_nonpositive_size(size_mm: float) -> None:
    with pytest.raises(EditError) as err:
        set_size(_column_unit(Fill()), "lower", size_mm, Basis.CLEAR)
    assert err.value.node_id == "lower"


@pytest.mark.parametrize("node_id", ["no-such-id", "shelf", "column"])
def test_set_size_refuses_an_unknown_id_a_board_and_the_root(node_id: str) -> None:
    with pytest.raises(EditError) as err:
        set_size(_column_unit(Fill()), node_id, 300.0, Basis.CLEAR)
    assert err.value.node_id == node_id


def _region_before_region_unit() -> Unit:
    """A bay followed directly by a void, with no board between them."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[Bay(id="bay"), Void(id="void"), Board(thickness_mm=18.0, id="side")],
        ),
        depth_axis=Axis.Y,
    )


def test_set_size_and_set_basis_refuse_a_spacing_with_no_board_after_it() -> None:
    unit = _region_before_region_unit()
    with pytest.raises(EditError) as err:
        set_size(unit, "bay", 300.0, Basis.WITH_NEXT)
    assert err.value.node_id == "bay"
    with pytest.raises(EditError) as err:
        set_basis(unit, "bay", Basis.WITH_NEXT)
    assert err.value.node_id == "bay"


@pytest.mark.parametrize(
    ("lower_rule", "basis"),
    [
        (Fixed(282.0), Basis.WITH_NEXT),
        (Fixed(300.0, Basis.WITH_NEXT), Basis.CLEAR),
        (Fixed(300.0, Basis.WITH_NEXT), Basis.WITH_NEXT),
        (Fill(), Basis.WITH_NEXT),
        (Weighted(0.5), Basis.CLEAR),
    ],
)
def test_set_basis_leaves_the_solved_layout_identical(
    lower_rule: SizeRule, basis: Basis
) -> None:
    unit = _column_unit(lower_rule)
    edited = set_basis(unit, "lower", basis)
    _assert_same_layout(unit, edited)
    new_rule = _rules_by_id(edited.root)["lower"]
    assert isinstance(new_rule, Fixed)
    assert new_rule.basis is basis


def test_set_basis_restates_the_number_in_the_new_basis() -> None:
    unit = _column_unit(Fixed(282.0))
    spacing = set_basis(unit, "lower", Basis.WITH_NEXT)
    assert _rules_by_id(spacing.root)["lower"] == Fixed(300.0, Basis.WITH_NEXT)
    clear = set_basis(spacing, "lower", Basis.CLEAR)
    assert _rules_by_id(clear.root)["lower"] == Fixed(282.0, Basis.CLEAR)


def test_set_basis_uses_the_thickness_of_a_board_with_its_own_rule() -> None:
    """The solver resolves ``WITH_NEXT`` by the next board's ``thickness_mm``,
    not its ruled extent, so the restated number must too or the layout would
    move."""
    unit = _column_unit(Fixed(282.0))
    assert isinstance(unit.root, Division)
    unit.root.items[2] = Board(thickness_mm=18.0, id="shelf", rule=Fixed(30.0))
    edited = set_basis(unit, "lower", Basis.WITH_NEXT)
    _assert_same_layout(unit, edited)


def test_a_spacing_holds_boards_and_a_clear_size_moves_them_across_thicknesses() -> (
    None
):
    """The reason basis exists: thicker stock keeps a shelf's position under a
    spacing, and pushes it up under a clear opening."""
    spacing = Fixed(300.0, Basis.WITH_NEXT)
    clear = Fixed(282.0, Basis.CLEAR)
    for rule in (spacing, clear):
        assert solve(_column_unit(rule))["shelf"].origin.z_mm == pytest.approx(300.0)
    thick_spacing = solve(_column_unit(spacing, thickness_mm=25.0))
    thick_clear = solve(_column_unit(clear, thickness_mm=25.0))
    assert thick_spacing["shelf"].origin.z_mm == pytest.approx(300.0)
    assert thick_clear["shelf"].origin.z_mm == pytest.approx(307.0)


@pytest.mark.parametrize("board_id", ["bottom", "no-such-id", "lower"])
def test_move_board_refuses_a_carcass_board_and_a_non_board(board_id: str) -> None:
    with pytest.raises(EditError) as err:
        move_board(_column_unit(Fill()), board_id, 350.0)
    assert err.value.node_id == board_id


def test_move_board_stops_a_drag_past_the_region_below_at_the_minimum_gap() -> None:
    moved = move_board(_column_unit(Fill()), "shelf", -100.0)
    spaces = solve(moved)
    assert spaces["lower"].size.z_mm == pytest.approx(MIN_DRAG_GAP_MM)
    assert spaces["shelf"].origin.z_mm == pytest.approx(18.0 + MIN_DRAG_GAP_MM)


def test_move_board_stops_a_drag_past_the_region_above_at_the_minimum_gap() -> None:
    moved = move_board(_three_bays(), "shelf1", 900.0)
    assert _heights_mm(moved) == pytest.approx([395.0, MIN_DRAG_GAP_MM, 200.0])


def test_move_board_never_grows_a_region_already_under_the_minimum_gap() -> None:
    narrow = unlock(set_size(_column_unit(Fill()), "lower", 2.0, Basis.CLEAR), "lower")
    assert solve(narrow)["lower"].size.z_mm == pytest.approx(2.0)
    for low_face_mm in (-100.0, 18.0):
        moved = move_board(narrow, "shelf", low_face_mm)
        assert solve(moved)["lower"].size.z_mm == pytest.approx(2.0)
    raised = move_board(narrow, "shelf", 100.0)
    assert solve(raised)["lower"].size.z_mm == pytest.approx(82.0)


def test_the_minimum_drag_gap_survives_a_rescan() -> None:
    assert MIN_DRAG_GAP_MM > DEFAULT_CLEARANCE_MM + DEFAULT_SNAP_MM


def test_measure_reports_both_numbers_and_the_basis_a_size_would_use() -> None:
    fill = _column_unit(Fill())
    measured = measure(fill, "lower", solve(fill))
    assert measured.basis is Basis.CLEAR
    assert measured.fixed is False
    assert measured.spacing_mm == pytest.approx(measured.clear_mm + 18.0)
    spacing = _column_unit(Fixed(300.0, Basis.WITH_NEXT))
    assert measure(spacing, "lower", solve(spacing)) == Measurement(
        basis=Basis.WITH_NEXT, fixed=True, clear_mm=282.0, spacing_mm=300.0
    )
    assert measure(spacing, "lower", solve(spacing)).size_mm == pytest.approx(300.0)


def test_measure_has_no_spacing_without_a_board_after_the_region() -> None:
    unit = _region_before_region_unit()
    measured = measure(unit, "bay", solve(unit))
    assert measured.spacing_mm is None
    assert measured.size_mm == measured.clear_mm


@pytest.mark.parametrize("node_id", ["shelf", "column", "no-such-id"])
def test_measure_refuses_what_set_size_refuses(node_id: str) -> None:
    unit = _column_unit(Fill())
    with pytest.raises(EditError):
        measure(unit, node_id, solve(unit))


def test_region_before_and_run_axis() -> None:
    unit = _column_unit(Fill())
    assert region_before(unit, "shelf") == "lower"
    assert run_axis(unit, "shelf") is Axis.Z
    with pytest.raises(EditError):
        region_before(unit, "bottom")
    with pytest.raises(EditError):
        run_axis(unit, "column")


# --- locked and unlocked regions, and the drag -------------------------------

_LAST_UNLOCKED = (
    "One opening in each row stays unlocked, to take up changes to the unit's size."
)


def _three_bays(locked: Collection[str] = ()) -> Unit:
    """A column of three 200 mm bays, ``bay1`` lowest, between 20 mm boards:
    680 mm tall. Each bay named in ``locked`` is ``Fixed`` at 200 mm."""
    items: list[Item] = [Board(thickness_mm=20.0, id="bottom")]
    for number in (1, 2, 3):
        bay_id = f"bay{number}"
        rule: SizeRule = Fixed(200.0) if bay_id in locked else Fill()
        board_id = f"shelf{number}" if number < 3 else "top"
        items += [Bay(id=bay_id, rule=rule), Board(thickness_mm=20.0, id=board_id)]
    return Unit(
        size_mm=Vec3(600.0, 300.0, 680.0),
        root=Division(axis=Axis.Z, items=items, id="column"),
        depth_axis=Axis.Y,
    )


def _heights_mm(unit: Unit) -> list[float]:
    spaces = solve(unit)
    return [spaces[f"bay{number}"].size.z_mm for number in (1, 2, 3)]


def _units_to_lock() -> list[tuple[Unit, str]]:
    return [
        (_column_unit(Fill()), "lower"),
        (_column_unit(Weighted(0.5)), "lower"),
        (_column_unit(Fixed(300.0, Basis.WITH_NEXT)), "upper"),
        (_column_unit(Fill()), "topmost"),
        (_three_bays(), "bay2"),
        (_three_bays({"bay1"}), "bay3"),
    ]


@pytest.mark.parametrize(("unit", "region_id"), _units_to_lock())
def test_locking_and_unlocking_move_nothing(unit: Unit, region_id: str) -> None:
    locked = lock(unit, region_id)
    clear_mm = solve(unit)[region_id].size.z_mm
    assert _rules_by_id(locked.root)[region_id] == Fixed(clear_mm, Basis.CLEAR)
    _assert_same_layout(unit, locked)
    unlocked = unlock(locked, region_id)
    assert not isinstance(_rules_by_id(unlocked.root)[region_id], Fixed)
    _assert_same_layout(unit, unlocked)


def test_unlocking_holds_the_size_against_the_other_unlocked_regions() -> None:
    unit = _three_bays({"bay1"})
    unit = set_unit_size(unit, Vec3(600.0, 300.0, 780.0))
    # bay1 holds 200 mm; bay2 and bay3 share the rest, 250 mm each.
    unlocked = unlock(unit, "bay1")
    assert _rules_by_id(unlocked.root)["bay1"] == Weighted(0.8)
    _assert_same_layout(unit, unlocked)


def test_unlocking_the_only_unlocked_region_of_its_run_gives_fill() -> None:
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 680.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=20.0, id="bottom"),
                Bay(id="bay1", rule=Fixed(300.0)),
                Board(thickness_mm=20.0, id="shelf1"),
                Bay(id="bay2", rule=Fixed(320.0)),
                Board(thickness_mm=20.0, id="top"),
            ],
        ),
    )
    assert _rules_by_id(unlock(unit, "bay1").root)["bay1"] == Fill()


def test_locking_a_locked_or_unlocking_an_unlocked_region_changes_nothing() -> None:
    unit = _three_bays({"bay1"})
    assert lock(unit, "bay1") is unit
    assert unlock(unit, "bay2") is unit


@pytest.mark.parametrize("node_id", ["shelf1", "column", "no-such-id"])
def test_lock_and_unlock_refuse_what_set_size_refuses(node_id: str) -> None:
    unit = _three_bays()
    for edit in (lock, unlock):
        with pytest.raises(EditError) as err:
            edit(unit, node_id)
        assert err.value.node_id == node_id


def test_the_last_unlocked_region_of_a_run_cannot_be_locked() -> None:
    unit = _three_bays({"bay1", "bay2"})
    with pytest.raises(EditError, match=_LAST_UNLOCKED) as err:
        lock(unit, "bay3")
    assert err.value.node_id == "bay3"
    with pytest.raises(EditError, match=_LAST_UNLOCKED) as err:
        set_size(unit, "bay3", 150.0, Basis.CLEAR)
    assert err.value.node_id == "bay3"
    with pytest.raises(EditError, match=_LAST_UNLOCKED) as err:
        set_basis(unit, "bay3", Basis.WITH_NEXT)
    assert err.value.node_id == "bay3"


def test_a_run_with_no_unlocked_region_keeps_what_it_was_allowed() -> None:
    """An older record can leave every region of a run locked."""
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 680.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=20.0, id="bottom"),
                Bay(id="bay1", rule=Fixed(300.0)),
                Board(thickness_mm=20.0, id="shelf1"),
                Bay(id="bay2", rule=Fixed(320.0)),
                Board(thickness_mm=20.0, id="top"),
            ],
        ),
    )
    assert lock(unit, "bay1") is unit
    resized = set_size(unit, "bay1", 290.0, Basis.CLEAR)
    assert _rules_by_id(resized.root)["bay1"] == Fixed(290.0)
    spacing = set_basis(unit, "bay1", Basis.WITH_NEXT)
    assert _rules_by_id(spacing.root)["bay1"] == Fixed(320.0, Basis.WITH_NEXT)


def test_a_drag_resizes_the_openings_beside_it_and_leaves_them_unlocked() -> None:
    moved = move_board(_three_bays(), "shelf1", 270.0)
    assert _heights_mm(moved) == pytest.approx([250.0, 150.0, 200.0])
    rules = _rules_by_id(moved.root)
    assert not any(isinstance(rules[f"bay{n}"], Fixed) for n in (1, 2, 3))
    taller = set_unit_size(moved, Vec3(600.0, 300.0, 770.0))
    assert _heights_mm(taller) == pytest.approx([287.5, 172.5, 230.0])


def test_a_locked_opening_carries_the_board_beyond_it() -> None:
    unit = _three_bays({"bay2"})
    before = solve(unit)
    moved = move_board(unit, "shelf1", 250.0)
    after = solve(moved)
    assert _heights_mm(moved) == pytest.approx([230.0, 200.0, 170.0])
    assert after["shelf2"].origin.z_mm == pytest.approx(
        before["shelf2"].origin.z_mm + 30.0
    )
    assert _rules_by_id(moved.root)["bay2"] == Fixed(200.0)


def test_a_board_with_only_locks_to_the_end_of_its_run_is_held() -> None:
    unit = _three_bays({"bay1", "bay2"})
    assert held_by(unit, "shelf1") == ("bay1",)
    assert held_by(unit, "shelf2") == ("bay2",)
    for board_id, holder in (("shelf1", "bay1"), ("shelf2", "bay2")):
        with pytest.raises(EditError) as err:
            move_board(unit, board_id, 300.0)
        assert err.value.node_id == holder


def test_a_board_held_on_both_sides_names_both_holders() -> None:
    unit = _three_bays({"bay1", "bay3"})
    # bay2 is free between them: shelf1 has it above, shelf2 below.
    assert held_by(unit, "shelf1") == ("bay1",)
    assert held_by(unit, "shelf2") == ("bay3",)
    assert held_by(_three_bays({"bay1"}), "shelf2") == ()


def test_a_carcass_board_has_nothing_to_unlock() -> None:
    for unit in (_three_bays(), _three_bays({"bay1", "bay2"})):
        assert held_by(unit, "bottom") is None
        assert held_by(unit, "top") is None
        with pytest.raises(EditError) as err:
            move_board(unit, "top", 600.0)
        assert err.value.node_id == "top"
    assert held_by(_three_bays(), "shelf1") == ()
    assert held_by(_three_bays(), "bay1") is None


def test_a_drag_never_changes_another_regions_size() -> None:
    unit = _column_unit(Fill())
    before = solve(unit)
    moved = move_board(unit, "shelf", 350.0)
    after = solve(moved)
    assert after["shelf"].origin.z_mm == pytest.approx(350.0)
    assert after["topmost"].size.z_mm == pytest.approx(before["topmost"].size.z_mm)
    assert after["shelf2"].origin.z_mm == pytest.approx(before["shelf2"].origin.z_mm)


def test_splitting_a_locked_bay_gives_locked_halves_and_merging_them_locks() -> None:
    unit = _three_bays({"bay1"})
    split = split_region(unit, "bay1", Axis.Z)
    assert isinstance(split.root, Division)
    halves = [item for item in split.root.items[:4] if not isinstance(item, Board)]
    assert [half.rule for half in halves] == [Fixed(90.0), Fixed(90.0)]
    new_board = split.root.items[2]
    assert _rules_by_id(merge_at(split, new_board.id).root)[halves[0].id] == Fixed(
        200.0
    )
    half_unlocked = unlock(split, halves[1].id)
    merged = merge_at(half_unlocked, new_board.id)
    assert not isinstance(_rules_by_id(merged.root)[halves[0].id], Fixed)


def _stock_unit() -> Unit:
    """A column with a locked spacing over its first shelf, a locked clear
    opening under its second, and a free opening at the top."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=18.0, id="bottom"),
                Bay(rule=Fixed(300.0, Basis.WITH_NEXT), id="spaced"),
                Board(thickness_mm=18.0, id="s1"),
                Bay(rule=Fixed(282.0, Basis.CLEAR), id="clear"),
                Board(thickness_mm=18.0, id="s2"),
                Bay(id="free"),
                Board(thickness_mm=18.0, id="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _top_face_mm(spaces: Mapping[str, Space], node_id: str) -> float:
    space = spaces[node_id]
    return space.origin.z_mm + space.size.z_mm


def test_set_thickness_keeps_the_unit_size_and_a_spacing_holds_its_shelf() -> None:
    """A spacing is quoted to the top of the shelf after it, so that top
    stays put; a clear opening keeps its own height, so the shelf over it
    comes down by the thickness it lost."""
    unit = _stock_unit()
    before = solve(unit)
    edited = set_thickness(unit, ["s1", "s2"], 12.0)
    after = solve(edited)
    assert edited.size_mm == unit.size_mm
    assert after[edited.root.id] == before[unit.root.id]
    assert _top_face_mm(after, "s1") == pytest.approx(_top_face_mm(before, "s1"))
    assert _top_face_mm(after, "s2") == pytest.approx(_top_face_mm(before, "s2") - 6.0)
    assert after["s1"].size.z_mm == pytest.approx(12.0)
    assert after["bottom"] == before["bottom"]
    assert after["top"] == before["top"]
    # The argument is left as it was.
    assert solve(unit) == before


def test_set_thickness_that_cannot_fit_fails_the_solve() -> None:
    edited = set_thickness(_stock_unit(), ["bottom", "s1", "s2", "top"], 200.0)
    with pytest.raises(LayoutSolveError):
        solve(edited)


@pytest.mark.parametrize(
    ("board_ids", "thickness_mm", "named"),
    [
        (["s1", "nowhere"], 12.0, "nowhere"),
        (["s1", "free"], 12.0, "free"),
        (["s1"], 0.0, "s1"),
        (["s1"], -3.0, "s1"),
    ],
)
def test_set_thickness_refuses(
    board_ids: list[str], thickness_mm: float, named: str
) -> None:
    with pytest.raises(EditError) as raised:
        set_thickness(_stock_unit(), board_ids, thickness_mm)
    assert raised.value.node_id == named


def _two_column_unit() -> Unit:
    """Two columns of two bays each, side by side between three boards."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[
                Board(thickness_mm=18.0, id="left"),
                Division(
                    axis=Axis.Z,
                    items=[Bay(id="a1"), Board(thickness_mm=18.0, id="sa"), Bay()],
                ),
                Board(thickness_mm=18.0, id="mid"),
                Division(
                    axis=Axis.Z,
                    items=[Bay(id="b1"), Board(thickness_mm=18.0, id="sb"), Bay()],
                ),
                Board(thickness_mm=18.0, id="right"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _all_board_ids(region: Region) -> set[str]:
    if not isinstance(region, Division):
        return set()
    ids: set[str] = set()
    for item in region.items:
        ids |= {item.id} if isinstance(item, Board) else _all_board_ids(item)
    return ids


def test_remove_boards_removes_two_inner_boards_of_one_run() -> None:
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=18.0, id="bottom"),
                Bay(id="low"),
                Board(thickness_mm=18.0, id="s1"),
                Bay(rule=Weighted(2.0)),
                Board(thickness_mm=18.0, id="s2"),
                Bay(),
                Board(thickness_mm=18.0, id="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )
    before = solve(unit)
    edited = remove_boards(unit, ["s1", "s2"])
    after = solve(edited)
    assert edited == merge_at(merge_at(unit, "s1"), "s2")
    assert _all_board_ids(edited.root) == {"bottom", "top"}
    assert after["bottom"] == before["bottom"]
    assert after["top"] == before["top"]
    assert after["low"].size.z_mm == pytest.approx(864.0)


def test_remove_boards_removes_one_board_in_each_of_two_runs() -> None:
    unit = _two_column_unit()
    before = solve(unit)
    edited = remove_boards(unit, ["sa", "sb"])
    after = solve(edited)
    assert _all_board_ids(edited.root) == {"left", "mid", "right"}
    for board_id in ("left", "mid", "right"):
        assert after[board_id] == before[board_id]
    assert after["a1"].size.z_mm == pytest.approx(900.0)
    assert after["b1"].size.z_mm == pytest.approx(900.0)


def test_remove_boards_refuses_the_whole_set_for_an_end_of_run_board() -> None:
    unit = _two_column_unit()
    snapshot = copy.deepcopy(unit)
    with pytest.raises(EditError) as raised:
        remove_boards(unit, ["sa", "left"])
    assert raised.value.node_id == "left"
    assert unit == snapshot


def test_remove_boards_skips_a_board_an_earlier_removal_discarded() -> None:
    """Removing ``mid`` discards the column after it whole, ``sb`` with it."""
    unit = _two_column_unit()
    edited = remove_boards(unit, ["mid", "sb"])
    assert edited == merge_at(unit, "mid")
    assert _all_board_ids(edited.root) == {"left", "sa", "right"}


def test_remove_boards_refuses_an_id_that_was_never_a_board() -> None:
    with pytest.raises(EditError) as raised:
        remove_boards(_two_column_unit(), ["sa", "nowhere"])
    assert raised.value.node_id == "nowhere"
