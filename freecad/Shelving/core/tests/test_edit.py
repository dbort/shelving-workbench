"""``split_region`` / ``merge_at``: refusals, and split-then-merge round trips."""

import copy
import dataclasses

import pytest

from freecad.Shelving.core.edit import EditError, merge_at, split_region
from freecad.Shelving.core.geometry import Vec3
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
from freecad.Shelving.core.materials import MaterialId

PLY = MaterialId("ply18")


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
    split = split_region(unit, bay_id, Axis.Z, material=None)
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


# --- split_region refusals ---------------------------------------------------


def test_split_region_refuses_a_void() -> None:
    void = Void()
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), default_material=PLY, root=void)
    with pytest.raises(EditError, match=void.id) as exc_info:
        split_region(unit, void.id, Axis.X)
    assert exc_info.value.node_id == void.id


def test_split_region_refuses_a_division() -> None:
    unit = _closed_box_unit()
    assert isinstance(unit.root, Division)
    with pytest.raises(EditError, match=unit.root.id) as exc_info:
        split_region(unit, unit.root.id, Axis.X)
    assert exc_info.value.node_id == unit.root.id


def test_split_region_refuses_an_unknown_id() -> None:
    unit = _closed_box_unit()
    with pytest.raises(EditError, match="no-such-id") as exc_info:
        split_region(unit, "no-such-id", Axis.X)
    assert exc_info.value.node_id == "no-such-id"


# --- merge_at refusals -------------------------------------------------------


def test_merge_at_refuses_an_unknown_id() -> None:
    unit = _closed_box_unit()
    with pytest.raises(EditError, match="no-such-id") as exc_info:
        merge_at(unit, "no-such-id")
    assert exc_info.value.node_id == "no-such-id"


def test_merge_at_refuses_a_board_with_no_neighbour_on_one_side() -> None:
    edge_board = Board(role="edge")
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(axis=Axis.X, items=[edge_board, Bay()]),
    )
    with pytest.raises(EditError, match=edge_board.id) as exc_info:
        merge_at(unit, edge_board.id)
    assert exc_info.value.node_id == edge_board.id


def test_merge_at_refuses_a_board_flanked_by_another_board() -> None:
    middle_board = Board(role="middle")
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        default_material=PLY,
        root=Division(axis=Axis.X, items=[Board(role="left"), middle_board, Bay()]),
    )
    with pytest.raises(EditError, match=middle_board.id) as exc_info:
        merge_at(unit, middle_board.id)
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
    """The replacement is a ``Division`` on the requested axis, carrying the
    split ``Bay``'s own rule; its items are ``Bay(Fill)``, ``Board``,
    ``Bay(Fill)``; the parent's untouched siblings are the same
    objects split_region reused, not copies of them."""
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

    split = split_region(unit, bay_id, Axis.Z, material=PLY)

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
    unit = _closed_box_unit()
    bay_id = _find_bay_id(unit.root)
    split = split_region(unit, bay_id, Axis.X)
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
    ``Division`` to slot the replacement into."""
    bay = Bay(rule=Fixed(500.0))
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), default_material=PLY, root=bay)

    split = split_region(unit, bay.id, Axis.X, material=PLY)

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
