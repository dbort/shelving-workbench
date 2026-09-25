"""``split_region`` / ``merge_at``: refusals, and split-then-merge round trips."""

import copy

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
    if isinstance(region, Bay):
        return region.id
    if isinstance(region, Division):
        for item in region.items:
            if not isinstance(item, Board):
                found = _find_bay_id(item)
                if found is not None:
                    return found
    raise AssertionError(f"no Bay found in {region!r}")


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
