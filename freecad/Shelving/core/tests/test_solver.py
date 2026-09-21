"""Spacing solver: distribution rules, region-tree geometry, and failure reasons."""

import pytest

from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Unit,
    Void,
    Weighted,
)
from freecad.Shelving.core.materials import Catalog, MaterialEntry, MaterialId
from freecad.Shelving.core.solver import EPS_MM, LayoutSolveError, distribute, solve

T10 = MaterialId("t10")
T18 = MaterialId("t18")
T20 = MaterialId("t20")


def _catalog(**thicknesses_mm: float) -> Catalog:
    """A catalog whose entry ids are the keyword names, thicknesses the values."""
    return Catalog(
        entries={
            MaterialId(key): MaterialEntry(
                id=MaterialId(key),
                name=key,
                thickness_mm=value,
                material_type="test",
            )
            for key, value in thicknesses_mm.items()
        }
    )


CATALOG = _catalog(t10=10.0, t18=18.0, t20=20.0)


def _assert_space(
    space: Space,
    *,
    origin: tuple[float, float, float],
    size: tuple[float, float, float],
) -> None:
    assert space.origin.x_mm == pytest.approx(origin[0], abs=1e-6)
    assert space.origin.y_mm == pytest.approx(origin[1], abs=1e-6)
    assert space.origin.z_mm == pytest.approx(origin[2], abs=1e-6)
    assert space.size.x_mm == pytest.approx(size[0], abs=1e-6)
    assert space.size.y_mm == pytest.approx(size[1], abs=1e-6)
    assert space.size.z_mm == pytest.approx(size[2], abs=1e-6)


# --- distribute(): the pure slack-sharing function, no region tree involved ---


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


def test_distribute_all_fixed_exact_is_ok() -> None:
    assert distribute(
        100.0, [Fixed(30.0), Fixed(50.0)], [20.0], node_id="x"
    ) == pytest.approx([30.0, 50.0], abs=1e-6)


def test_distribute_all_fixed_overflow_reports_overflow() -> None:
    with pytest.raises(LayoutSolveError) as excinfo:
        distribute(100.0, [Fixed(80.0), Fixed(60.0)], [0.0], node_id="x")
    assert excinfo.value.reason == "overflow"
    assert excinfo.value.node_id == "x"


def test_distribute_all_fixed_underfill_reports_no_slack_absorber() -> None:
    with pytest.raises(LayoutSolveError) as excinfo:
        distribute(100.0, [Fixed(20.0), Fixed(30.0)], [0.0], node_id="x")
    assert excinfo.value.reason == "no_slack_absorber"
    assert excinfo.value.node_id == "x"


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


# --- solve() over the region tree. ---


def test_closed_box_places_its_four_shell_boards_and_interior() -> None:
    root = Division(
        axis=Axis.Z,
        items=[
            Board(role="bottom", id="bottom"),
            Division(
                axis=Axis.X,
                items=[
                    Board(role="left_side", id="left"),
                    Bay(id="interior"),
                    Board(role="right_side", id="right"),
                ],
                id="middle",
            ),
            Board(role="top", id="top"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(900.0, 300.0, 1800.0), default_material=T18, root=root)
    spaces = solve(unit, CATALOG)
    _assert_space(spaces["bottom"], origin=(0, 0, 0), size=(900, 300, 18))
    _assert_space(spaces["top"], origin=(0, 0, 1782), size=(900, 300, 18))
    _assert_space(spaces["middle"], origin=(0, 0, 18), size=(900, 300, 1764))
    _assert_space(spaces["left"], origin=(0, 0, 18), size=(18, 300, 1764))
    _assert_space(spaces["right"], origin=(882, 0, 18), size=(18, 300, 1764))
    _assert_space(spaces["interior"], origin=(18, 0, 18), size=(864, 300, 1764))


def test_division_mixing_fixed_fill_and_boards() -> None:
    root = Division(
        axis=Axis.X,
        items=[
            Board(id="left_board"),
            Bay(rule=Fixed(200.0), id="fixed_bay"),
            Bay(rule=Fill(), id="fill_bay"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), default_material=T18, root=root)
    spaces = solve(unit, CATALOG)
    _assert_space(spaces["left_board"], origin=(0, 0, 0), size=(18, 300, 900))
    _assert_space(spaces["fixed_bay"], origin=(18, 0, 0), size=(200, 300, 900))
    _assert_space(spaces["fill_bay"], origin=(218, 0, 0), size=(382, 300, 900))


def test_void_receives_a_space_like_any_region() -> None:
    root = Division(
        axis=Axis.Z,
        items=[Bay(id="bay"), Void(rule=Fixed(100.0), id="void")],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 500.0), default_material=T18, root=root)
    spaces = solve(unit, CATALOG)
    _assert_space(spaces["void"], origin=(0, 0, 400), size=(600, 300, 100))


def test_division_along_axis_y_is_solved_the_same_way() -> None:
    """The solver is axis-agnostic: swapping the division's axis to Y produces
    the same distribution, just along a different component."""
    root = Division(
        axis=Axis.Y,
        items=[Board(id="front"), Bay(rule=Fill(), id="bay"), Board(id="back")],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), default_material=T18, root=root)
    spaces = solve(unit, CATALOG)
    _assert_space(spaces["front"], origin=(0, 0, 0), size=(600, 18, 900))
    _assert_space(spaces["bay"], origin=(0, 18, 0), size=(600, 264, 900))
    _assert_space(spaces["back"], origin=(0, 282, 0), size=(600, 18, 900))


def test_solve_overflow_reason_and_node_id() -> None:
    root = Division(
        axis=Axis.X,
        items=[Bay(rule=Fixed(5000.0)), Bay(rule=Fill())],
        id="split",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 1000.0), default_material=T18, root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit, CATALOG)
    assert excinfo.value.reason == "overflow"
    assert excinfo.value.node_id == "split"


def test_solve_no_slack_absorber_reason_and_node_id() -> None:
    root = Division(
        axis=Axis.X,
        items=[Bay(rule=Fixed(100.0)), Bay(rule=Fixed(200.0))],
        id="split",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 1000.0), default_material=T18, root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit, CATALOG)
    assert excinfo.value.reason == "no_slack_absorber"
    assert excinfo.value.node_id == "split"


def test_solve_nonpositive_opening_reason_and_node_id() -> None:
    root = Division(
        axis=Axis.Z,
        items=[Bay(rule=Fixed(500.0), id="top"), Bay(rule=Fill(), id="bot")],
        id="split",
    )
    unit = Unit(size_mm=Vec3(200.0, 300.0, 500.0), default_material=T18, root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit, CATALOG)
    assert excinfo.value.reason == "nonpositive_opening"
    assert excinfo.value.node_id == "bot"


def test_solve_unresolvable_basis_when_region_is_last_item() -> None:
    root = Division(
        axis=Axis.Z,
        items=[
            Board(id="bottom"),
            Bay(rule=Fixed(500.0, basis=Basis.WITH_NEXT), id="last"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 1000.0), default_material=T18, root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit, CATALOG)
    assert excinfo.value.reason == "unresolvable_basis"
    assert excinfo.value.node_id == "last"


def test_solve_unresolvable_basis_when_next_item_is_not_a_board() -> None:
    root = Division(
        axis=Axis.Z,
        items=[
            Bay(rule=Fixed(500.0, basis=Basis.WITH_NEXT), id="with_next"),
            Bay(rule=Fill()),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 1000.0), default_material=T18, root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit, CATALOG)
    assert excinfo.value.reason == "unresolvable_basis"
    assert excinfo.value.node_id == "with_next"


def test_solve_with_next_thinner_than_next_board_raises_layout_solve_error() -> None:
    """A ``WITH_NEXT`` spacing quoted narrower than the following board's
    thickness resolves to a non-positive size; that must surface as
    ``LayoutSolveError``, not a bare ``ValueError`` from ``Fixed``'s own
    validation."""
    root = Division(
        axis=Axis.Z,
        items=[
            Bay(rule=Fixed(5.0, basis=Basis.WITH_NEXT), id="too_thin"),
            Board(material=T18, id="next_board"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 1000.0), default_material=T18, root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit, CATALOG)
    assert excinfo.value.reason == "nonpositive_opening"
    assert excinfo.value.node_id == "too_thin"


def test_basis_with_next_holds_board_position_across_catalog_thickness_change() -> None:
    """A shelf spacing quoted top face to top face (``WITH_NEXT``, a bay's
    fixed size covering the bay plus the shelf immediately above it) keeps the
    upper shelf's position fixed when the catalog's board thickness changes;
    the same layout measured ``CLEAR`` instead moves it."""

    def build(basis: Basis) -> Unit:
        root = Division(
            axis=Axis.Z,
            items=[
                Board(id="lower_shelf"),
                Bay(rule=Fixed(400.0, basis=basis), id="bay"),
                Board(id="upper_shelf"),
                Bay(rule=Fill(), id="top_bay"),
            ],
            id="root",
        )
        return Unit(size_mm=Vec3(600.0, 300.0, 1200.0), default_material=T18, root=root)

    thin_catalog = _catalog(t18=10.0)

    with_next_thick = solve(build(Basis.WITH_NEXT), CATALOG)
    with_next_thin = solve(build(Basis.WITH_NEXT), thin_catalog)
    assert with_next_thick["upper_shelf"].origin.z_mm == pytest.approx(400.0)
    assert with_next_thin["upper_shelf"].origin.z_mm == pytest.approx(400.0)

    clear_thick = solve(build(Basis.CLEAR), CATALOG)
    clear_thin = solve(build(Basis.CLEAR), thin_catalog)
    assert clear_thick["upper_shelf"].origin.z_mm == pytest.approx(418.0)
    assert clear_thin["upper_shelf"].origin.z_mm == pytest.approx(410.0)


# --- Pinned boards: the solver verifies rather than derives. ---


def _pinned_shelf_unit(width_mm: float, pinned_size_mm: Vec3) -> Unit:
    """A shelf pinned at ``pinned_size_mm``, between a fixed lower bay and a
    fill bay that absorbs the rest of the height."""
    board = Board(id="fixed_shelf", pinned_size_mm=pinned_size_mm)
    root = Division(
        axis=Axis.Z,
        items=[Bay(rule=Fixed(400.0)), board, Bay(rule=Fill())],
        id="root",
    )
    return Unit(size_mm=Vec3(width_mm, 300.0, 900.0), default_material=T18, root=root)


def test_pinned_board_matching_layout_solves() -> None:
    unit = _pinned_shelf_unit(200.0, Vec3(200.0, 300.0, 18.0))
    spaces = solve(unit, CATALOG)
    _assert_space(spaces["fixed_shelf"], origin=(0, 0, 400), size=(200, 300, 18))


def test_pinned_board_mismatch_raises_naming_the_board() -> None:
    """Widening the unit in the direction the pinned board spans changes the
    derived extent; the solver refuses rather than stretching the board."""
    unit = _pinned_shelf_unit(250.0, Vec3(200.0, 300.0, 18.0))
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit, CATALOG)
    assert excinfo.value.reason == "pinned_mismatch"
    assert excinfo.value.node_id == "fixed_shelf"


def test_pinned_board_agreeing_within_eps_mm_does_not_raise() -> None:
    unit = _pinned_shelf_unit(200.0, Vec3(200.0 + EPS_MM / 2, 300.0, 18.0))
    spaces = solve(unit, CATALOG)
    _assert_space(spaces["fixed_shelf"], origin=(0, 0, 400), size=(200, 300, 18))
