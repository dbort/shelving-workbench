"""``split_region`` / ``merge_at``: refusals, round trips, and (bug-006) that
every other board and region in an edited run keeps its solved geometry."""

import copy
import dataclasses
from collections.abc import Mapping

import pytest

from freecad.Shelving.core.edit import EditError, merge_at, split_region
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Item,
    Region,
    SizeRule,
    Unit,
    Void,
    Weighted,
)
from freecad.Shelving.core.materials import Catalog, MaterialEntry, MaterialId
from freecad.Shelving.core.solver import solve

PLY = MaterialId("ply18")

CATALOG = Catalog(entries={PLY: MaterialEntry(PLY, "ply 18", 18.0, "plywood")})


def _closed_box_unit() -> Unit:
    """A single open ``Bay`` nested inside boards on every side: the shape
    ``freecad.Shelving.unit_ops._default_unit`` seeds a fresh document with."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        default_material=PLY,
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


def _nested_division_unit() -> Unit:
    """A ``Division`` that itself sits beside another region in a wider run,
    so a merge at its board must operate within that outer run rather than
    at the tree root."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1800.0),
        default_material=PLY,
        root=Division(
            axis=Axis.X,
            items=[
                Board(role="left_side"),
                Division(
                    axis=Axis.Z,
                    items=[Bay(rule=Fixed(400.0)), Board(role="mid_shelf"), Bay()],
                ),
                Board(role="right_side"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _stepped_unit() -> Unit:
    """A stepped outline: a ``Void`` alongside a ``Bay`` in the same run."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1200.0),
        default_material=PLY,
        root=Division(
            axis=Axis.X,
            items=[Bay(rule=Weighted(2.0)), Board(role="divider"), Void()],
        ),
        depth_axis=Axis.Y,
    )


def _run_unit(rule_a: SizeRule, rule_b: SizeRule, width_mm: float = 900.0) -> Unit:
    """A flat ``Axis.X`` run: three boards and two bays, ``rule_a`` and
    ``rule_b``, so splitting or merging the first bay has a second sibling
    in the very same run whose geometry must not move."""
    return Unit(
        size_mm=Vec3(width_mm, 300.0, 900.0),
        default_material=PLY,
        root=Division(
            axis=Axis.X,
            items=[
                Board(role="left"),
                Bay(rule=rule_a),
                Board(role="mid"),
                Bay(rule=rule_b),
                Board(role="right"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _multi_weighted_run_unit() -> Unit:
    """A flat ``Axis.X`` run with four bays: ``Weighted(1.0)``,
    ``Weighted(2.5)``, ``Fill()``, ``Weighted(4.0)``. Editing ``bay2``
    leaves three OTHER driven siblings of different weights in the very
    same run, exercising ``_other_driven_anchor`` past the trivial
    single-other-sibling case every other fixture in this module gives it."""
    return Unit(
        size_mm=Vec3(2400.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(
            axis=Axis.X,
            items=[
                Board(role="b0"),
                Bay(rule=Weighted(1.0), id="bay1"),
                Board(role="b1"),
                Bay(rule=Weighted(2.5), id="bay2"),
                Board(role="b2"),
                Bay(rule=Fill(), id="bay3"),
                Board(role="b3"),
                Bay(rule=Weighted(4.0), id="bay4"),
                Board(role="b4"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _fixed_and_weighted_merge_unit() -> Unit:
    """A flat ``Axis.X`` run whose ``merge_board`` sits between a ``Fixed``
    bay and a ``Weighted`` one, with two more ``Weighted`` bays of
    different weights further down the same run: the non-trivial
    ``Weighted`` branch of ``_merged_rule`` (the two merging neighbours are
    not both ``Fixed``), anchored against an ``_other_driven_anchor`` that
    has more than one candidate to choose from."""
    return Unit(
        size_mm=Vec3(2400.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(
            axis=Axis.X,
            items=[
                Board(role="b0"),
                Bay(rule=Fixed(300.0), id="fixed_bay"),
                Board(role="merge_board", id="merge_board"),
                Bay(rule=Weighted(2.0), id="weighted_bay"),
                Board(role="b1"),
                Bay(rule=Weighted(3.5), id="bay_c"),
                Board(role="b2"),
                Bay(rule=Weighted(1.5), id="bay_d"),
                Board(role="b3"),
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
        return ("board", item.role, item.material, _rule_shape(item.rule or Fill()))
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


def _split_then_merge_round_trips(unit: Unit) -> None:
    bay_id = _find_bay_id(unit.root)
    split = split_region(unit, bay_id, Axis.Z, CATALOG, material=None)
    board_id = _new_board_id(unit, split)
    merged = merge_at(split, board_id, CATALOG)
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
    whatever they touch, so only a board can meaningfully "survive"."""
    spaces_after = solve(unit_after, CATALOG)
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
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), default_material=PLY, root=void)
    with pytest.raises(EditError, match=void.id) as exc_info:
        split_region(unit, void.id, Axis.X, CATALOG)
    assert exc_info.value.node_id == void.id


def test_split_region_refuses_a_division() -> None:
    unit = _closed_box_unit()
    assert isinstance(unit.root, Division)
    with pytest.raises(EditError, match=unit.root.id) as exc_info:
        split_region(unit, unit.root.id, Axis.X, CATALOG)
    assert exc_info.value.node_id == unit.root.id


def test_split_region_refuses_an_unknown_id() -> None:
    unit = _closed_box_unit()
    with pytest.raises(EditError, match="no-such-id") as exc_info:
        split_region(unit, "no-such-id", Axis.X, CATALOG)
    assert exc_info.value.node_id == "no-such-id"


def test_split_region_refuses_a_bay_too_small_for_the_divider() -> None:
    """A splice-case split (the bay's parent already runs along the split
    axis) whose opening cannot fit the new board and still leave two
    positive-sized halves is refused by the bay's own id, not left to a
    downstream ``Fixed``/``Weighted`` construction to crash on."""
    bay = Bay(rule=Fixed(10.0))
    unit = Unit(
        size_mm=Vec3(46.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(
            axis=Axis.X,
            items=[Board(role="left"), bay, Board(role="right")],
        ),
    )
    with pytest.raises(EditError, match=bay.id) as exc_info:
        split_region(unit, bay.id, Axis.X, CATALOG)
    assert exc_info.value.node_id == bay.id


# --- merge_at refusals -------------------------------------------------------


def test_merge_at_refuses_an_unknown_id() -> None:
    unit = _closed_box_unit()
    with pytest.raises(EditError, match="no-such-id") as exc_info:
        merge_at(unit, "no-such-id", CATALOG)
    assert exc_info.value.node_id == "no-such-id"


def test_merge_at_refuses_a_board_with_no_neighbour_on_one_side() -> None:
    edge_board = Board(role="edge")
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(axis=Axis.X, items=[edge_board, Bay()]),
    )
    with pytest.raises(EditError, match=edge_board.id) as exc_info:
        merge_at(unit, edge_board.id, CATALOG)
    assert exc_info.value.node_id == edge_board.id


def test_merge_at_refuses_a_board_flanked_by_another_board() -> None:
    middle_board = Board(role="middle")
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(axis=Axis.X, items=[Board(role="left"), middle_board, Bay()]),
    )
    with pytest.raises(EditError, match=middle_board.id) as exc_info:
        merge_at(unit, middle_board.id, CATALOG)
    assert exc_info.value.node_id == middle_board.id


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
    split_region(unit, bay_id, Axis.X, CATALOG)
    assert _region_shape(unit.root) == _region_shape(before.root)


def test_merge_at_leaves_the_argument_unit_unchanged() -> None:
    unit = _closed_box_unit()
    bay_id = _find_bay_id(unit.root)
    split = split_region(unit, bay_id, Axis.X, CATALOG)
    before = copy.deepcopy(split)
    board_id = _new_board_id(unit, split)
    merge_at(split, board_id, CATALOG)
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

    split = split_region(unit, bay_id, Axis.Z, CATALOG, material=PLY)

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
    assert board.material == PLY

    siblings_after = [item for i, item in enumerate(new_parent.items) if i != index]
    assert siblings_after == siblings_before
    for before_item, after_item in zip(siblings_before, siblings_after, strict=True):
        assert before_item is after_item


def test_split_region_defaults_the_board_material_to_none() -> None:
    """``Axis.Z`` differs from ``_closed_box_unit``'s inner division
    (``Axis.X``), so this is the cross-axis nesting case: the new board
    sits inside a wrapping ``Division`` at the bay's old slot."""
    unit = _closed_box_unit()
    bay_id = _find_bay_id(unit.root)
    split = split_region(unit, bay_id, Axis.Z, CATALOG)
    # split_region gave the replacement Division a fresh id (bay_id no longer
    # names anything), so locate it by the parent slot instead.
    parent = _find_parent(unit.root, bay_id)
    assert isinstance(parent, Division)
    index = next(i for i, item in enumerate(parent.items) if item.id == bay_id)
    new_parent = _find_region(split.root, parent.id)
    assert isinstance(new_parent, Division)
    division = new_parent.items[index]
    assert isinstance(division, Division)
    _left, board, _right = division.items
    assert isinstance(board, Board)
    assert board.material is None


def test_split_region_at_the_tree_root() -> None:
    """``region_id`` can name the tree's own root, with no parent
    ``Division`` to slot the replacement into: always the cross-axis
    nesting case, so the bay's own ``Fixed`` rule has no bearing on the two
    new halves, which are ``Fill``."""
    bay = Bay(rule=Fixed(500.0))
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), default_material=PLY, root=bay)

    split = split_region(unit, bay.id, Axis.X, CATALOG, material=PLY)

    assert isinstance(split.root, Division)
    assert split.root.axis == Axis.X
    assert split.root.rule == bay.rule
    assert len(split.root.items) == 3
    left, board, right = split.root.items
    assert isinstance(left, Bay) and left.rule == Fill()
    assert isinstance(right, Bay) and right.rule == Fill()
    assert isinstance(board, Board)
    assert board.material == PLY


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
    spaces_before = solve(unit, CATALOG)
    bay_a = unit.root.items[1]
    assert isinstance(bay_a, Bay)
    bay_b = unit.root.items[3]
    assert isinstance(bay_b, Bay)

    split = split_region(unit, bay_a.id, Axis.X, CATALOG)
    assert not _has_same_axis_nesting(split.root)
    _assert_surviving_boards_unchanged(spaces_before, split)
    spaces_after_split = solve(split, CATALOG)
    assert _spaces_equal(spaces_after_split[bay_b.id], spaces_before[bay_b.id])

    board_id = _new_board_id(unit, split)
    merged = merge_at(split, board_id, CATALOG)
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
    spaces_after_merge = solve(merged, CATALOG)
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
    going to find the run's one genuinely driven item."""
    unit = Unit(
        size_mm=Vec3(1200.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(
            axis=Axis.X,
            items=[
                Board(role="left"),
                Bay(rule=Weighted(1.0), id="bay_a"),
                Board(role="mid1"),
                Bay(rule=Fixed(200.0)),
                Board(role="mid2"),
                Bay(rule=Fill(), id="bay_c"),
                Board(role="right"),
            ],
        ),
        depth_axis=Axis.Y,
    )
    spaces_before = solve(unit, CATALOG)

    split = split_region(unit, "bay_a", Axis.X, CATALOG)
    assert not _has_same_axis_nesting(split.root)
    _assert_surviving_boards_unchanged(spaces_before, split)
    spaces_after = solve(split, CATALOG)
    assert _spaces_equal(spaces_after["bay_c"], spaces_before["bay_c"])


def test_split_region_bug_006_sequence_preserves_every_prior_boards_geometry() -> None:
    """The exact bug-006 repro run directly against ``split_region``, no
    rescan involved: add a divider (splice, the bay's parent already runs
    on that axis), a shelf on the left (nest, a different axis), then a
    shelf top-left (splice again, the just-nested division now shares its
    axis) - every board added by an earlier step keeps its solved space
    through every later one, and the final tree nests no same-axis
    ``Division`` inside another."""
    unit = _closed_box_unit()
    spaces = solve(unit, CATALOG)

    bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, bay_id, Axis.X, CATALOG)
    _assert_surviving_boards_unchanged(spaces, unit)
    assert not _has_same_axis_nesting(unit.root)
    spaces = solve(unit, CATALOG)

    left_bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, left_bay_id, Axis.Z, CATALOG)
    _assert_surviving_boards_unchanged(spaces, unit)
    assert not _has_same_axis_nesting(unit.root)
    spaces = solve(unit, CATALOG)

    # The shelf-left split just nested a fresh Axis.Z Division holding the
    # lower and upper halves of the old left bay, in that solved-position
    # order; index [1] is the upper (top-left) one, not [0] (bottom-left).
    ordered_bay_ids = _find_bay_ids_in_order(unit.root)
    lower_left_bay_id, topleft_bay_id = ordered_bay_ids[0], ordered_bay_ids[1]
    assert spaces[topleft_bay_id].origin.z_mm > spaces[lower_left_bay_id].origin.z_mm
    unit = split_region(unit, topleft_bay_id, Axis.Z, CATALOG)
    _assert_surviving_boards_unchanged(spaces, unit)
    assert not _has_same_axis_nesting(unit.root)


# --- F2: three-or-more-other-driven-siblings coverage ------------------------


def test_split_preserves_three_other_weighted_siblings_of_different_weights() -> None:
    """Splitting ``bay2`` in a four-bay run leaves ``bay1`` (``Weighted(1.0)``),
    ``bay3`` (``Fill()``) and ``bay4`` (``Weighted(4.0)``) all at their
    pre-split ``Space``, not only the single other driven sibling every other
    split fixture in this module gives ``_other_driven_anchor``."""
    unit = _multi_weighted_run_unit()
    spaces_before = solve(unit, CATALOG)

    split = split_region(unit, "bay2", Axis.X, CATALOG)
    assert not _has_same_axis_nesting(split.root)
    _assert_surviving_boards_unchanged(spaces_before, split)
    spaces_after = solve(split, CATALOG)
    for bay_id in ("bay1", "bay3", "bay4"):
        assert _spaces_equal(spaces_after[bay_id], spaces_before[bay_id]), bay_id


def test_merge_preserves_three_other_weighted_siblings_of_different_weights() -> None:
    """The matching merge back, in the same four-bay run: splitting ``bay2``
    then merging at the board the split just added restores ``bay2``'s own
    geometry, and still leaves ``bay1``, ``bay3`` and ``bay4`` untouched."""
    unit = _multi_weighted_run_unit()
    spaces_before = solve(unit, CATALOG)

    split = split_region(unit, "bay2", Axis.X, CATALOG)
    board_id = _new_board_id(unit, split)
    spaces_after_split = solve(split, CATALOG)

    merged = merge_at(split, board_id, CATALOG)
    assert not _has_same_axis_nesting(merged.root)
    _assert_surviving_boards_unchanged(spaces_after_split, merged)
    spaces_after_merge = solve(merged, CATALOG)
    for bay_id in ("bay1", "bay3", "bay4"):
        assert _spaces_equal(spaces_after_merge[bay_id], spaces_before[bay_id]), bay_id
    merged_root = merged.root
    assert isinstance(merged_root, Division)
    merged_bay2 = merged_root.items[3]
    assert isinstance(merged_bay2, Bay)
    assert _spaces_equal(spaces_after_merge[merged_bay2.id], spaces_before["bay2"])


def test_merge_a_fixed_bay_with_a_weighted_one_leaves_other_weighted_siblings() -> None:
    """Merging away ``merge_board`` combines a ``Fixed`` bay with a
    ``Weighted`` one - the non-``Fixed``/``Fixed`` branch of
    ``_merged_rule`` - while ``bay_c`` and ``bay_d``, two more ``Weighted``
    bays of different weights elsewhere in the run, keep their pre-merge
    ``Space`` exactly."""
    unit = _fixed_and_weighted_merge_unit()
    spaces_before = solve(unit, CATALOG)

    merged = merge_at(unit, "merge_board", CATALOG)
    assert not _has_same_axis_nesting(merged.root)
    _assert_surviving_boards_unchanged(spaces_before, merged)
    spaces_after = solve(merged, CATALOG)
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


# --- N5: split's own item shape at the splice site ---------------------------


def test_split_region_spliced_items_are_bay_board_bay_in_place() -> None:
    """The literal Must Have wording for the splice case (the bay's parent
    already runs on the split axis): the parent's ``items`` gain exactly
    ``Bay, Board, Bay`` at the split bay's old slot, no more, no fewer."""
    unit = _run_unit(Weighted(1.5), Weighted(2.5))
    assert isinstance(unit.root, Division)
    bay_a = unit.root.items[1]
    assert isinstance(bay_a, Bay)
    index = 1

    split = split_region(unit, bay_a.id, Axis.X, CATALOG)
    assert isinstance(split.root, Division)
    spliced = split.root.items[index : index + 3]
    kinds = [type(item).__name__ for item in spliced]
    assert kinds == ["Bay", "Board", "Bay"], kinds
    # Nothing else in the run moved: nothing before or after the spliced
    # slot changed identity or count.
    assert len(split.root.items) == len(unit.root.items) + 2
    assert split.root.items[:index] == unit.root.items[:index]
    assert split.root.items[index + 3 :] == unit.root.items[index + 1 :]


# --- N4: a merge's collapse never nests a same-axis Division either --------


def _bare_column_unit() -> Unit:
    """A ``Division`` (axis ``Z``) whose middle item is an ``Axis.X``
    ``Division`` holding a single bare ``Bay``: no side boards flank it, so
    a splice-then-nest-then-collapse sequence on that bay can reduce the
    ``Axis.X`` division to one item and promote it straight into the
    ``Axis.Z`` run above - the same axis as the promoted item once the
    intervening split nests a ``Division`` sharing it. A second ``Weighted``
    bay elsewhere in the ``Axis.Z`` run gives the promoted items' own
    ``_other_driven_anchor`` something real to solve against."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 1800.0),
        default_material=PLY,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom"),
                Division(axis=Axis.X, items=[Bay(rule=Weighted(1.0))]),
                Board(role="mid"),
                Bay(rule=Weighted(2.0)),
                Board(role="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def test_merge_collapse_never_nests_a_same_axis_division_either() -> None:
    """The divider, shelf left, delete divider sequence: add a divider
    (splice, the bare column's own axis), a shelf on its left half (nest,
    a different axis), then delete the divider - the delete collapses the
    ``Axis.X`` division to its one surviving item, the ``Axis.Z`` division
    ``shelf left`` just nested, which shares the grandparent (``Axis.Z``)
    run's own axis; that promoted division's items must splice into the
    grandparent's run rather than nest inside it, and every surviving
    board - the unit's ``bottom``, ``mid`` and ``top`` - must keep its
    solved ``Space`` throughout."""
    unit = _bare_column_unit()
    spaces_before_divider = solve(unit, CATALOG)

    boards_before_divider = _all_board_ids(unit.root)
    bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, bay_id, Axis.X, CATALOG)
    assert not _has_same_axis_nesting(unit.root)
    divider_id = next(iter(_all_board_ids(unit.root) - boards_before_divider))
    _assert_surviving_boards_unchanged(spaces_before_divider, unit)
    spaces_after_divider = solve(unit, CATALOG)

    left_bay_id = _find_bay_id(unit.root)
    unit = split_region(unit, left_bay_id, Axis.Z, CATALOG)
    assert not _has_same_axis_nesting(unit.root)
    _assert_surviving_boards_unchanged(spaces_after_divider, unit)

    merged = merge_at(unit, divider_id, CATALOG)
    assert not _has_same_axis_nesting(merged.root)
    _assert_surviving_boards_unchanged(spaces_before_divider, merged)

    merged_root = merged.root
    assert isinstance(merged_root, Division)
    assert merged_root.axis == Axis.Z
    # The promoted division's items spliced straight into the Axis.Z run in
    # place of the collapsed Axis.X division: no nested Division survives.
    assert all(not isinstance(item, Division) for item in merged_root.items)
