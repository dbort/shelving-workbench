"""The source board a new board copies its stock from, and carcass classification."""

from pathlib import Path

import pytest

from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Axis, Bay, Board, Division, Fill, Fixed, Unit
from freecad.Shelving.core.scan import boxes_from_json, scan
from freecad.Shelving.core.solver import solve
from freecad.Shelving.core.stock import is_carcass, source_board

REAL_MAGICSTART_F1 = (
    Path(__file__).parent / "fixtures" / "real_magicstart_f1.boxes.json"
)


def _board(board_id: str, thickness_mm: float = 18.0) -> Board:
    return Board(thickness_mm=thickness_mm, role=board_id, id=board_id)


def _source_id(unit: Unit, region_id: str, axis: Axis) -> str | None:
    source = source_board(unit, solve(unit), region_id, axis)
    return None if source is None else source.id


def test_magic_start_floor_top_and_sides_are_carcass_and_the_shelf_is_not() -> None:
    """The floor sits 100 mm up over a plinth gap, so only the tree rule, a
    ``Void`` and nothing else below it, makes it carcass."""
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    unit = scan(boxes).unit
    for board_id in ("Left", "Right", "Floor", "Top"):
        assert is_carcass(unit, board_id), board_id
    assert not is_carcass(unit, "Shelf")


def test_is_carcass_refuses_an_unknown_board() -> None:
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(axis=Axis.Z, items=[_board("bottom"), Bay(), _board("top")]),
    )
    with pytest.raises(KeyError):
        is_carcass(unit, "no-such-id")


def test_an_interior_board_in_the_same_run_wins_over_a_nearer_carcass_board() -> None:
    """The 25 mm shelf's centre is 12.5 mm past the target bay's top edge,
    the bottom's only 9 mm below its bottom edge, so the carcass bottom is
    nearer, and still loses."""
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 1000.0),
        root=Division(
            axis=Axis.Z,
            items=[
                _board("bottom"),
                Bay(rule=Fixed(200.0), id="target"),
                _board("shelf", 25.0),
                Bay(rule=Fill()),
                _board("top"),
            ],
        ),
    )
    assert _source_id(unit, "target", Axis.Z) == "shelf"


def _two_column_unit(right_column: Bay | Division) -> Unit:
    left_column = Division(
        axis=Axis.Z,
        items=[
            Bay(rule=Fixed(300.0)),
            _board("shelf_low", 15.0),
            Bay(rule=Fixed(150.0)),
            _board("shelf_high", 16.0),
            Bay(rule=Fill()),
        ],
    )
    return Unit(
        size_mm=Vec3(1000.0, 300.0, 1000.0),
        root=Division(
            axis=Axis.Z,
            items=[
                _board("bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        _board("left"),
                        left_column,
                        _board("divider"),
                        right_column,
                        _board("right"),
                    ],
                ),
                _board("top"),
            ],
        ),
    )


def test_with_no_interior_board_in_the_run_the_nearest_interior_board_wins() -> None:
    """The target bay's centre is 500 mm up; ``shelf_high``'s is 491 mm up,
    nearer than ``shelf_low``'s, and the carcass bottom and top rank below
    any interior board."""
    unit = _two_column_unit(Bay(id="target"))
    assert _source_id(unit, "target", Axis.Z) == "shelf_high"


def test_with_no_interior_board_at_all_the_nearest_carcass_board_wins() -> None:
    """The interior divider is not parallel to a new shelf, so it never
    counts; the 20 mm bottom's centre is 1 mm nearer than the 22 mm top's."""
    unit = Unit(
        size_mm=Vec3(1000.0, 300.0, 1000.0),
        root=Division(
            axis=Axis.Z,
            items=[
                _board("bottom", 20.0),
                Division(
                    axis=Axis.X,
                    items=[
                        _board("left"),
                        Bay(id="target"),
                        _board("divider"),
                        Bay(),
                        _board("right"),
                    ],
                ),
                _board("top", 22.0),
            ],
        ),
    )
    assert not is_carcass(unit, "divider")
    assert _source_id(unit, "target", Axis.Z) == "bottom"


def test_with_no_parallel_board_the_nearest_board_of_any_kind_wins() -> None:
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=Division(
            axis=Axis.X,
            items=[_board("left"), Bay(id="target"), _board("right", 20.0)],
        ),
    )
    assert _source_id(unit, "target", Axis.Z) == "left"


def test_a_unit_with_no_board_has_no_source() -> None:
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=Bay(id="target"))
    assert _source_id(unit, "target", Axis.Z) is None
