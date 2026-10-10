"""Region-tree expansion: carcass equivalence, stepped outlines, and insets."""

import pytest

from freecad.Shelving.core.expand import BoardSpec, expand, total_volume_mm3
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Bay,
    Board,
    Division,
    Fixed,
    Insets,
    Item,
    Unit,
    Void,
)


def _assert_vec3(actual: Vec3, x_mm: float, y_mm: float, z_mm: float) -> None:
    assert actual.x_mm == pytest.approx(x_mm, abs=1e-6)
    assert actual.y_mm == pytest.approx(y_mm, abs=1e-6)
    assert actual.z_mm == pytest.approx(z_mm, abs=1e-6)


def _by_id(specs: list[BoardSpec], node_id: str) -> BoardSpec:
    matches = [spec for spec in specs if spec.node_id == node_id]
    assert len(matches) == 1, f"expected exactly one board with id {node_id!r}"
    return matches[0]


def _closed_box(width_mm: float, depth_mm: float, height_mm: float) -> Unit:
    """A bottom and a top running the full width, two sides captured between
    them: a carcass shell expressed as ordinary items, since regions carry no
    distinguished shell rule of their own."""
    return Unit(
        size_mm=Vec3(width_mm, depth_mm, height_mm),
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
    )


def test_closed_box_matches_the_carcass_models_geometry() -> None:
    """Expected values are hard-coded: there is no independent model to
    compute an expected result from and compare against at runtime."""
    unit = _closed_box(900.0, 300.0, 1800.0)
    specs = expand(unit)
    assert len(specs) == 4
    by_role = {spec.role: spec for spec in specs}
    _assert_vec3(by_role["bottom"].size, 900.0, 300.0, 18.0)
    _assert_vec3(by_role["bottom"].placement, 0.0, 0.0, 0.0)
    _assert_vec3(by_role["top"].size, 900.0, 300.0, 18.0)
    _assert_vec3(by_role["top"].placement, 0.0, 0.0, 1782.0)
    _assert_vec3(by_role["left_side"].size, 18.0, 300.0, 1764.0)
    _assert_vec3(by_role["left_side"].placement, 0.0, 0.0, 18.0)
    _assert_vec3(by_role["right_side"].size, 18.0, 300.0, 1764.0)
    _assert_vec3(by_role["right_side"].placement, 882.0, 0.0, 18.0)


def _column(void_mm: float, prefix: str) -> Division:
    """A stack of a bay, its own top, and (if positive) the void above it: the
    step is a ``Void`` taking the leftover height."""
    items: list[Item] = [
        Bay(id=f"{prefix}_bay"),
        Board(thickness_mm=18.0, role="top", id=f"{prefix}_top"),
    ]
    if void_mm > 0:
        items.append(Void(rule=Fixed(void_mm), id=f"{prefix}_void"))
    return Division(axis=Axis.Z, items=items, id=f"{prefix}_division")


def _stepped_unit() -> Unit:
    """Three columns of falling height on a continuous floor: the shape the
    carcass shell rule could not state."""
    return Unit(
        size_mm=Vec3(1200.0, 300.0, 1200.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=18.0, role="bottom", id="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(thickness_mm=18.0, role="left_side"),
                        _column(0.0, "col0"),
                        Board(thickness_mm=18.0, role="divider"),
                        _column(300.0, "col1"),
                        Board(thickness_mm=18.0, role="divider"),
                        _column(600.0, "col2"),
                        Board(thickness_mm=18.0, role="right_side"),
                    ],
                    id="middle",
                ),
            ],
            id="root",
        ),
    )


def test_stepped_outline_expands_with_falling_tops_and_no_void_boards() -> None:
    unit = _stepped_unit()
    specs = expand(unit)

    tops_mm = sorted(
        spec.placement.z_mm + spec.size.z_mm for spec in specs if spec.role == "top"
    )
    assert [round(z, 1) for z in tops_mm] == [600.0, 900.0, 1200.0]
    assert all(
        spec.size.x_mm < unit.size_mm.x_mm for spec in specs if spec.role == "top"
    )

    # A Void takes no id in the board list: 1 floor, 2 sides, 2 dividers, 3
    # tops, and nothing for either of the two Voids.
    assert len(specs) == 8

    floor = _by_id(specs, "bottom")
    assert floor.size.x_mm == pytest.approx(unit.size_mm.x_mm)


def test_two_adjacent_boards_touch() -> None:
    root = Division(
        axis=Axis.Z,
        items=[
            Bay(),
            Board(thickness_mm=18.0, role="lower", id="lower"),
            Board(thickness_mm=18.0, role="upper", id="upper"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 1000.0), root=root)
    specs = expand(unit)
    lower = _by_id(specs, "lower")
    upper = _by_id(specs, "upper")
    assert upper.placement.z_mm == pytest.approx(lower.placement.z_mm + lower.size.z_mm)


def test_board_insets_apply_to_cross_section_axes_only() -> None:
    insets = Insets(y_min_mm=10.0, y_max_mm=20.0, z_min_mm=5.0, z_max_mm=7.0)
    root = Division(
        axis=Axis.X,
        items=[Board(thickness_mm=18.0, insets=insets, id="inset_board"), Bay()],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=root)
    board = _by_id(expand(unit), "inset_board")

    # X is the division's own axis: the solved thickness, never inset.
    assert board.size.x_mm == pytest.approx(18.0)
    assert board.placement.x_mm == pytest.approx(0.0)

    # Y and Z are the cross-section axes: inset on both faces of each.
    assert board.placement.y_mm == pytest.approx(10.0)
    assert board.size.y_mm == pytest.approx(300.0 - 10.0 - 20.0)
    assert board.placement.z_mm == pytest.approx(5.0)
    assert board.size.z_mm == pytest.approx(900.0 - 5.0 - 7.0)


def test_total_volume_mm3_sums_the_closed_box() -> None:
    unit = _closed_box(900.0, 300.0, 1800.0)
    specs = expand(unit)
    expected_mm3 = 2 * (900.0 * 300.0 * 18.0) + 2 * (18.0 * 300.0 * 1764.0)
    assert total_volume_mm3(specs) == pytest.approx(expected_mm3, abs=1e-6)
