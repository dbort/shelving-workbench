"""Spacing solver: distribution rules, nested geometry, and failure reasons."""

import pytest

from shelving_core.layout import (
    Carcass,
    Divider,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
    Weighted,
)
from shelving_core.solver import (
    LayoutSolveError,
    Rect,
    SolvedLayout,
    distribute,
    solve,
)


def _assert_rect(
    actual: Rect, x_mm: float, z_mm: float, width_mm: float, height_mm: float
) -> None:
    assert actual.x_mm == pytest.approx(x_mm, abs=1e-6)
    assert actual.z_mm == pytest.approx(z_mm, abs=1e-6)
    assert actual.width_mm == pytest.approx(width_mm, abs=1e-6)
    assert actual.height_mm == pytest.approx(height_mm, abs=1e-6)


def _solve_single_split(
    *,
    height_mm: float,
    width_mm: float,
    rules: list[Fixed | Weighted | Fill],
) -> SolvedLayout:
    children: list[Leaf | Split] = [Leaf(id=f"c{i}") for i in range(len(rules))]
    dividers = [Divider(thickness_mm=None, id=f"d{i}") for i in range(len(rules) - 1)]
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=children,
        rules=rules,
        dividers=dividers,
        id="root",
    )
    carcass = Carcass(
        width_mm=width_mm,
        height_mm=height_mm,
        depth_mm=300.0,
        default_thickness_mm=0.0,
        root=root,
    )
    return solve(carcass)


def test_three_way_fill_split_gives_equal_openings() -> None:
    layout = _solve_single_split(
        height_mm=900.0, width_mm=600.0, rules=[Fill(), Fill(), Fill()]
    )
    _assert_rect(layout["c0"], 0.0, 0.0, 600.0, 300.0)
    _assert_rect(layout["c1"], 0.0, 300.0, 600.0, 300.0)
    _assert_rect(layout["c2"], 0.0, 600.0, 600.0, 300.0)


def test_fixed_plus_fill_split_fill_absorbs_slack() -> None:
    layout = _solve_single_split(
        height_mm=1800.0, width_mm=600.0, rules=[Fixed(500.0), Fill()]
    )
    _assert_rect(layout["c0"], 0.0, 0.0, 600.0, 500.0)
    _assert_rect(layout["c1"], 0.0, 500.0, 600.0, 1300.0)


def test_weighted_split_shares_slack_two_to_one() -> None:
    layout = _solve_single_split(
        height_mm=900.0, width_mm=600.0, rules=[Weighted(2.0), Weighted(1.0)]
    )
    _assert_rect(layout["c0"], 0.0, 0.0, 600.0, 600.0)
    _assert_rect(layout["c1"], 0.0, 600.0, 600.0, 300.0)


def test_distribute_fixed_and_fill() -> None:
    assert distribute(
        1000.0, [Fixed(400.0), Fill()], [18.0], node_id="x"
    ) == pytest.approx([400.0, 582.0], abs=1e-6)


def test_distribute_three_fills() -> None:
    assert distribute(
        300.0, [Fill(), Fill(), Fill()], [18.0, 18.0], node_id="x"
    ) == pytest.approx([88.0, 88.0, 88.0], abs=1e-6)


def test_distribute_weighted_ratio() -> None:
    assert distribute(
        900.0, [Weighted(2.0), Weighted(1.0)], [0.0], node_id="x"
    ) == pytest.approx([600.0, 300.0], abs=1e-6)


def test_distribute_overflow_raises() -> None:
    with pytest.raises(LayoutSolveError) as excinfo:
        distribute(100.0, [Fixed(200.0), Fill()], [0.0], node_id="x")
    assert excinfo.value.reason == "overflow"
    assert excinfo.value.node_id == "x"


def test_distribute_no_slack_absorber_raises() -> None:
    with pytest.raises(LayoutSolveError) as excinfo:
        distribute(100.0, [Fixed(30.0), Fixed(40.0)], [0.0], node_id="x")
    assert excinfo.value.reason == "no_slack_absorber"
    assert excinfo.value.node_id == "x"


def test_nested_horizontal_then_vertical_geometry() -> None:
    inner = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(id="b"), Leaf(id="c"), Leaf(id="d")],
        rules=[Fill(), Fill(), Fill()],
        dividers=[
            Divider(thickness_mm=None, id="d1"),
            Divider(thickness_mm=None, id="d2"),
        ],
        id="inner",
    )
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[Leaf(id="a"), inner],
        rules=[Fixed(400.0), Fill()],
        dividers=[Divider(thickness_mm=None, id="d0")],
        id="root",
    )
    layout = solve(
        Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_thickness_mm=18.0,
            root=root,
        )
    )
    _assert_rect(layout["root"], 18.0, 18.0, 864.0, 1764.0)
    _assert_rect(layout["a"], 18.0, 18.0, 864.0, 400.0)
    _assert_rect(layout["d0"], 18.0, 418.0, 864.0, 18.0)
    _assert_rect(layout["inner"], 18.0, 436.0, 864.0, 1346.0)
    _assert_rect(layout["b"], 18.0, 436.0, 276.0, 1346.0)
    _assert_rect(layout["d1"], 294.0, 436.0, 18.0, 1346.0)
    _assert_rect(layout["c"], 312.0, 436.0, 276.0, 1346.0)
    _assert_rect(layout["d2"], 588.0, 436.0, 18.0, 1346.0)
    _assert_rect(layout["d"], 606.0, 436.0, 276.0, 1346.0)


def test_carcass_inset_reduces_all_four_sides() -> None:
    layout = solve(
        Carcass(
            width_mm=100.0,
            height_mm=200.0,
            depth_mm=50.0,
            default_thickness_mm=10.0,
            root=Leaf(id="only"),
        )
    )
    _assert_rect(layout["only"], 10.0, 10.0, 80.0, 180.0)


def test_solve_overflow_reason_and_node_id() -> None:
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[Leaf(id="a"), Leaf(id="b")],
        rules=[Fixed(5000.0), Fill()],
        dividers=[Divider(thickness_mm=None, id="dv")],
        id="split",
    )
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(
            Carcass(
                width_mm=600.0,
                height_mm=1000.0,
                depth_mm=300.0,
                default_thickness_mm=0.0,
                root=root,
            )
        )
    assert excinfo.value.reason == "overflow"
    assert excinfo.value.node_id == "split"


def test_solve_no_slack_absorber_reason_and_node_id() -> None:
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[Leaf(id="a"), Leaf(id="b")],
        rules=[Fixed(100.0), Fixed(200.0)],
        dividers=[Divider(thickness_mm=None, id="dv")],
        id="split",
    )
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(
            Carcass(
                width_mm=600.0,
                height_mm=1000.0,
                depth_mm=300.0,
                default_thickness_mm=0.0,
                root=root,
            )
        )
    assert excinfo.value.reason == "no_slack_absorber"
    assert excinfo.value.node_id == "split"


def test_solve_nonpositive_opening_reason_and_node_id() -> None:
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[Leaf(id="top"), Leaf(id="bot")],
        rules=[Fixed(500.0), Fill()],
        dividers=[Divider(thickness_mm=0.0, id="dv")],
        id="split",
    )
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(
            Carcass(
                width_mm=200.0,
                height_mm=500.0,
                depth_mm=300.0,
                default_thickness_mm=0.0,
                root=root,
            )
        )
    assert excinfo.value.reason == "nonpositive_opening"
    assert excinfo.value.node_id == "bot"


def test_solve_carcass_inset_overflow_targets_root_bay_id() -> None:
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(
            Carcass(
                width_mm=30.0,
                height_mm=200.0,
                depth_mm=50.0,
                default_thickness_mm=20.0,
                root=Leaf(id="r"),
            )
        )
    assert excinfo.value.reason == "overflow"
    assert excinfo.value.node_id == "r"
