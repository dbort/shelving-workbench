"""Solver: laying out stored geometry, the per-axis engine system an edit
solves with, and failure reasons."""

import dataclasses
from collections.abc import Mapping, Sequence

import pytest

from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    FixedPoint,
    FixedSide,
    Item,
    Unit,
    Void,
)
from freecad.Shelving.core.solver import (
    EPS_MM,
    LayoutSolveError,
    SolveErrorReason,
    describe_solve_error,
    duplicated_locks,
    fixing_locks,
    size_fixed_by,
    solve,
    solve_axis,
)


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


def _column(
    sizes_mm: Sequence[float],
    locked: Sequence[str] = (),
    side: FixedSide = "min",
) -> Unit:
    """A column of 18 mm boards: ``bottom``, bays ``A``, ``B``, ... at
    ``sizes_mm`` between shelves ``s1``, ``s2``, ..., then ``top``."""
    items: list[Item] = [Board(thickness_mm=18.0, id="bottom")]
    for index, size_mm in enumerate(sizes_mm):
        name = "ABCDEF"[index]
        lock = Basis.CLEAR if name in locked else None
        items.append(Bay(size_mm=size_mm, lock=lock, id=name))
        last = index == len(sizes_mm) - 1
        items.append(Board(thickness_mm=18.0, id="top" if last else f"s{index + 1}"))
    height_mm = 18.0 * (len(sizes_mm) + 1) + sum(sizes_mm)
    return Unit(
        size_mm=Vec3(500.0, 300.0, height_mm),
        root=Division(axis=Axis.Z, items=items, id="root"),
        fixed_point=FixedPoint(z=side),
    )


def _sizes(unit: Unit) -> Mapping[str, float]:
    assert isinstance(unit.root, Division)
    return {
        item.id: item.size_mm for item in unit.root.items if not isinstance(item, Board)
    }


# --- solve(): laying out the stored geometry. ---


def test_closed_box_places_its_four_shell_boards_and_interior() -> None:
    root = Division(
        axis=Axis.Z,
        items=[
            Board(thickness_mm=18.0, role="bottom", id="bottom"),
            Division(
                axis=Axis.X,
                items=[
                    Board(thickness_mm=18.0, role="left_side", id="left"),
                    Bay(size_mm=864.0, id="interior"),
                    Board(thickness_mm=18.0, role="right_side", id="right"),
                ],
                size_mm=1764.0,
                id="middle",
            ),
            Board(thickness_mm=18.0, role="top", id="top"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(900.0, 300.0, 1800.0), root=root)
    spaces = solve(unit)
    _assert_space(spaces["bottom"], origin=(0, 0, 0), size=(900, 300, 18))
    _assert_space(spaces["top"], origin=(0, 0, 1782), size=(900, 300, 18))
    _assert_space(spaces["middle"], origin=(0, 0, 18), size=(900, 300, 1764))
    _assert_space(spaces["left"], origin=(0, 0, 18), size=(18, 300, 1764))
    _assert_space(spaces["right"], origin=(882, 0, 18), size=(18, 300, 1764))
    _assert_space(spaces["interior"], origin=(18, 0, 18), size=(864, 300, 1764))


def test_root_is_placed_at_the_units_position() -> None:
    root = Division(
        axis=Axis.X,
        items=[
            Board(thickness_mm=18.0, id="left"),
            Bay(size_mm=564.0, id="interior"),
            Board(thickness_mm=18.0, id="right"),
        ],
        id="root",
    )
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        root=root,
        position_mm=Vec3(100.0, -300.0, 50.0),
    )
    spaces = solve(unit)
    _assert_space(spaces["root"], origin=(100, -300, 50), size=(600, 300, 900))
    _assert_space(spaces["left"], origin=(100, -300, 50), size=(18, 300, 900))
    _assert_space(spaces["interior"], origin=(118, -300, 50), size=(564, 300, 900))
    _assert_space(spaces["right"], origin=(682, -300, 50), size=(18, 300, 900))


def test_a_board_extent_overrides_its_thickness_along_its_run() -> None:
    root = Division(
        axis=Axis.X,
        items=[
            Board(thickness_mm=18.0, extent_mm=40.0, id="post"),
            Bay(size_mm=560.0, id="bay"),
        ],
        id="root",
    )
    spaces = solve(Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=root))
    _assert_space(spaces["post"], origin=(0, 0, 0), size=(40, 300, 900))
    _assert_space(spaces["bay"], origin=(40, 0, 0), size=(560, 300, 900))


def test_void_receives_a_space_like_any_region() -> None:
    root = Division(
        axis=Axis.Z,
        items=[Bay(size_mm=400.0, id="bay"), Void(size_mm=100.0, id="void")],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 500.0), root=root)
    spaces = solve(unit)
    _assert_space(spaces["void"], origin=(0, 0, 400), size=(600, 300, 100))


def test_division_along_axis_y_is_laid_out_the_same_way() -> None:
    root = Division(
        axis=Axis.Y,
        items=[
            Board(thickness_mm=18.0, id="front"),
            Bay(size_mm=264.0, id="bay"),
            Board(thickness_mm=18.0, id="back"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 900.0), root=root)
    spaces = solve(unit)
    _assert_space(spaces["front"], origin=(0, 0, 0), size=(600, 18, 900))
    _assert_space(spaces["bay"], origin=(0, 18, 0), size=(600, 264, 900))
    _assert_space(spaces["back"], origin=(0, 282, 0), size=(600, 18, 900))


@pytest.mark.parametrize("bay_mm", [300.0, 400.0])
def test_sizes_that_do_not_fill_their_run_are_a_misfit(bay_mm: float) -> None:
    root = Division(
        axis=Axis.X,
        items=[Bay(size_mm=bay_mm), Board(thickness_mm=18.0), Bay(size_mm=200.0)],
        id="split",
    )
    unit = Unit(size_mm=Vec3(600.0, 300.0, 1000.0), root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit)
    assert excinfo.value.reason == "misfit"
    assert excinfo.value.node_id == "split"


def test_a_region_with_no_size_is_a_misfit_naming_it() -> None:
    root = Division(
        axis=Axis.Z,
        items=[Bay(size_mm=500.0, id="top"), Bay(id="bot")],
        id="split",
    )
    unit = Unit(size_mm=Vec3(200.0, 300.0, 500.0), root=root)
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit)
    assert excinfo.value.reason == "misfit"
    assert excinfo.value.node_id == "bot"


# --- Pinned boards: the layout verifies rather than derives. ---


def _pinned_shelf_unit(width_mm: float, pinned_size_mm: Vec3) -> Unit:
    board = Board(thickness_mm=18.0, id="fixed_shelf", pinned_size_mm=pinned_size_mm)
    root = Division(
        axis=Axis.Z,
        items=[Bay(size_mm=400.0), board, Bay(size_mm=482.0)],
        id="root",
    )
    return Unit(size_mm=Vec3(width_mm, 300.0, 900.0), root=root)


def test_pinned_board_matching_layout_solves() -> None:
    unit = _pinned_shelf_unit(200.0, Vec3(200.0, 300.0, 18.0))
    spaces = solve(unit)
    _assert_space(spaces["fixed_shelf"], origin=(0, 0, 400), size=(200, 300, 18))


def test_pinned_board_mismatch_raises_naming_the_board() -> None:
    """Widening the unit in the direction the pinned board spans changes its
    laid-out extent; the layout refuses rather than stretching the board."""
    unit = _pinned_shelf_unit(250.0, Vec3(200.0, 300.0, 18.0))
    with pytest.raises(LayoutSolveError) as excinfo:
        solve(unit)
    assert excinfo.value.reason == "pinned_mismatch"
    assert excinfo.value.node_id == "fixed_shelf"


def test_pinned_board_agreeing_within_eps_mm_does_not_raise() -> None:
    unit = _pinned_shelf_unit(200.0, Vec3(200.0 + EPS_MM / 2, 300.0, 18.0))
    spaces = solve(unit)
    _assert_space(spaces["fixed_shelf"], origin=(0, 0, 400), size=(200, 300, 18))


# --- solve_axis(): least motion through the engine. ---


def test_solve_axis_with_no_change_moves_nothing() -> None:
    unit = _column([300.0, 300.0, 300.0])
    solved = solve_axis(unit, solve(unit), Axis.Z, 5.0)
    assert _sizes(solved) == {"A": 300.0, "B": 300.0, "C": 300.0}
    assert solved.size_mm == unit.size_mm
    assert solved.position_mm == unit.position_mm


def test_solve_axis_grows_the_opening_beside_the_moving_face() -> None:
    unit = _column([300.0, 300.0])
    solved = solve_axis(unit, solve(unit), Axis.Z, 5.0, size_mm=754.0)
    assert _sizes(solved) == pytest.approx({"A": 300.0, "B": 400.0})
    assert solved.size_mm.z_mm == 754.0


def test_solve_axis_at_a_max_fixed_point_moves_the_low_face() -> None:
    unit = _column([300.0, 300.0], side="max")
    solved = solve_axis(unit, solve(unit), Axis.Z, 5.0, size_mm=754.0)
    assert _sizes(solved) == pytest.approx({"A": 400.0, "B": 300.0})
    assert solved.position_mm.z_mm == pytest.approx(-100.0)
    assert solve(solved)["s1"].origin.z_mm == pytest.approx(318.0)


def test_solve_axis_does_not_push_open_an_opening_under_the_minimum() -> None:
    unit = _column([3.0, 300.0])
    solved = solve_axis(unit, solve(unit), Axis.Z, 5.0, size_mm=unit.size_mm.z_mm + 100)
    assert _sizes(solved) == pytest.approx({"A": 3.0, "B": 400.0})


def test_solve_axis_pushes_through_a_nested_run() -> None:
    """A column nested in a row nested in the root column takes its height
    from the slot it sits in, so a drag in the root pushes its shelves once
    the nested bay above reaches the minimum."""
    inner = Division(
        axis=Axis.Z,
        items=[
            Bay(size_mm=100.0, id="low"),
            Board(thickness_mm=18.0, id="inner_shelf"),
            Bay(size_mm=182.0, id="high"),
        ],
        size_mm=500.0,
        id="inner",
    )
    row = Division(
        axis=Axis.X,
        items=[
            inner,
            Board(thickness_mm=18.0, id="divider"),
            Bay(size_mm=300.0, id="side"),
        ],
        size_mm=300.0,
        id="row",
    )
    root = Division(
        axis=Axis.Z,
        items=[
            Board(thickness_mm=18.0, id="bottom"),
            Bay(size_mm=300.0, id="A"),
            Board(thickness_mm=18.0, id="s1"),
            row,
            Board(thickness_mm=18.0, id="top"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(818.0, 300.0, 654.0), root=root)
    solved = solve_axis(unit, solve(unit), Axis.Z, 5.0, target=("s1", 418.0))
    spaces = solve(solved)
    assert spaces["s1"].origin.z_mm == pytest.approx(418.0, abs=1e-3)
    assert spaces["inner"].extent_mm(2) == pytest.approx(200.0, abs=1e-3)
    assert spaces["low"].extent_mm(2) == pytest.approx(5.0, abs=1e-6)
    assert spaces["inner_shelf"].origin.z_mm == pytest.approx(441.0, abs=1e-3)


def test_solve_axis_moves_a_seam_between_two_regions() -> None:
    root = Division(
        axis=Axis.Z,
        items=[
            Board(thickness_mm=18.0, id="bottom"),
            Void(size_mm=100.0, lock=Basis.CLEAR, id="plinth"),
            Bay(size_mm=300.0, id="bay"),
            Board(thickness_mm=18.0, id="top"),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(500.0, 300.0, 436.0), root=root)
    solved = solve_axis(unit, solve(unit), Axis.Z, 5.0, size_mm=536.0)
    assert _sizes(solved) == pytest.approx({"plinth": 100.0, "bay": 400.0})


def test_solve_axis_conflict_names_the_locks_and_openings_at_the_minimum() -> None:
    unit = _column([300.0, 300.0, 300.0], locked=["A"])
    with pytest.raises(LayoutSolveError) as excinfo:
        solve_axis(unit, solve(unit), Axis.Z, 5.0, size_mm=360.0)
    err = excinfo.value
    assert err.reason == "conflict"
    assert set(err.region_ids) <= {"A", "B", "C"}
    assert "A" in err.region_ids
    assert err.node_id == err.region_ids[0]
    assert err.detail["minimum_mm"] == 5.0


def test_solve_axis_locks_that_fix_the_size_drop_a_consistent_one() -> None:
    unit = _column([300.0, 300.0], locked=["A", "B"])
    solved = solve_axis(unit, solve(unit), Axis.Z, 5.0, size_mm=unit.size_mm.z_mm)
    assert _sizes(solved) == {"A": 300.0, "B": 300.0}


def test_solve_axis_locks_that_fix_the_size_refuse_another_one() -> None:
    unit = _column([300.0, 300.0], locked=["A", "B"])
    with pytest.raises(LayoutSolveError) as excinfo:
        solve_axis(unit, solve(unit), Axis.Z, 5.0, size_mm=700.0)
    assert excinfo.value.reason == "conflict"
    assert excinfo.value.region_ids == ("A", "B")
    assert excinfo.value.node_id == "A"
    assert excinfo.value.detail == {"fixed_size_mm": pytest.approx(654.0)}


def test_solve_axis_lets_a_size_the_locks_fix_follow_them() -> None:
    before = _column([300.0, 300.0], locked=["A", "B"], side="center")
    assert isinstance(before.root, Division)
    after = dataclasses.replace(
        before,
        root=dataclasses.replace(
            before.root,
            items=[
                Bay(size_mm=340.0, lock=Basis.CLEAR, id=item.id)
                if item.id == "A"
                else item
                for item in before.root.items
            ],
        ),
    )
    solved = solve_axis(after, solve(before), Axis.Z, 5.0)
    assert _sizes(solved) == {"A": 340.0, "B": 300.0}
    assert solved.size_mm.z_mm == pytest.approx(694.0)
    assert solved.position_mm.z_mm == pytest.approx(-20.0)


# --- size_fixed_by() and duplicated_locks(): reference sizes and redundancy. ---


def test_size_fixed_by_is_none_until_the_locks_fix_the_size() -> None:
    unlocked: list[str] = []
    for locked in (unlocked, ["A"], ["B"]):
        unit = _column([300.0, 300.0], locked=locked)
        assert size_fixed_by(unit, solve(unit), Axis.Z) is None
    unit = _column([300.0, 300.0], locked=["A", "B"])
    assert size_fixed_by(unit, solve(unit), Axis.Z) == ("A", "B")
    assert size_fixed_by(unit, solve(unit), Axis.X) is None


def test_duplicated_locks_names_what_a_redundant_lock_repeats() -> None:
    """Two rows stacked under one shelf: once the lower row's two locks fix
    the width, locking both of the upper row's openings repeats them."""
    root = Division(
        axis=Axis.Z,
        items=[
            Division(
                axis=Axis.X,
                items=[
                    Bay(size_mm=200.0, lock=Basis.CLEAR, id="L1"),
                    Board(thickness_mm=18.0, id="dl"),
                    Bay(size_mm=282.0, lock=Basis.CLEAR, id="L2"),
                ],
                size_mm=200.0,
                id="lower",
            ),
            Board(thickness_mm=18.0, id="shelf"),
            Division(
                axis=Axis.X,
                items=[
                    Bay(size_mm=300.0, lock=Basis.CLEAR, id="U1"),
                    Board(thickness_mm=18.0, id="du"),
                    Bay(size_mm=182.0, lock=Basis.CLEAR, id="U2"),
                ],
                size_mm=200.0,
                id="upper",
            ),
        ],
        id="root",
    )
    unit = Unit(size_mm=Vec3(500.0, 300.0, 418.0), root=root)
    spaces = solve(unit)
    assert duplicated_locks(unit, spaces, "U2", Axis.X) == ("L1", "L2", "U1")
    assert duplicated_locks(unit, spaces, "L1", Axis.X) == ("L2", "U1", "U2")
    assert duplicated_locks(unit, spaces, "shelf", Axis.X) is None
    assert duplicated_locks(unit, spaces, "lower", Axis.Z) is None


def test_solve_axis_leaves_the_other_axes_alone() -> None:
    unit = _column([300.0, 300.0])
    solved = solve_axis(unit, solve(unit), Axis.X, 5.0, size_mm=900.0)
    assert solved.size_mm == Vec3(900.0, 300.0, unit.size_mm.z_mm)
    assert _sizes(solved) == {"A": 300.0, "B": 300.0}


# --- fixing_locks(): what holds a board, for held_by. ---


def test_fixing_locks_is_none_for_a_free_board() -> None:
    unit = _column([300.0, 300.0])
    assert fixing_locks(unit, solve(unit), "s1", Axis.Z) is None


def test_fixing_locks_is_empty_for_a_carcass_board() -> None:
    unit = _column([300.0, 300.0])
    assert fixing_locks(unit, solve(unit), "bottom", Axis.Z) == frozenset()
    assert fixing_locks(unit, solve(unit), "top", Axis.Z) == frozenset()


def test_fixing_locks_names_the_lock_and_honors_without() -> None:
    unit = _column([300.0, 300.0], locked=["A"])
    spaces = solve(unit)
    assert fixing_locks(unit, spaces, "s1", Axis.Z) == frozenset({"A"})
    assert fixing_locks(unit, spaces, "s1", Axis.Z, without=["A"]) is None


# --- describe_solve_error(). ---


@pytest.mark.parametrize(
    ("reason", "detail", "expected"),
    [
        ("misfit", {"span_mm": 600.0, "sizes_total_mm": 518.0}, "do not add up"),
        ("pinned_mismatch", {"derived_x_mm": 1.0}, "cannot reshape"),
        ("conflict", {"minimum_mm": 5.0}, "at their 5.0 mm minimum"),
        ("conflict", {"fixed_size_mm": 654.0}, "at 654.0 mm"),
        ("conflict", {}, "cannot all keep their sizes"),
    ],
)
def test_describe_solve_error_reads_as_a_sentence_without_the_node_id(
    reason: SolveErrorReason, detail: dict[str, float], expected: str
) -> None:
    node_id = "8d0c6f4e-1b2a-4c3d-9e8f-0a1b2c3d4e5f"
    message = describe_solve_error(LayoutSolveError(node_id, reason, detail))
    assert expected in message
    assert node_id not in message
    assert message.endswith(".")
