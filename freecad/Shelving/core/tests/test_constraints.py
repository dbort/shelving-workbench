"""Locks, Equal and even spacing on openings: creating them, how the solve
honors them, what edits drop them, and what they report, on sh-046's column
of 18 mm boards."""

import dataclasses
from collections.abc import Collection

import pytest

from freecad.Shelving.core.edit import (
    EditError,
    Held,
    add_equal,
    add_equal_along,
    add_even_spacing,
    carry_constraints,
    constraint_status,
    held_by,
    lock,
    merge_at,
    move_board,
    remove_boards,
    remove_constraints,
    remove_deactivated,
    set_constraint_active,
    set_constraint_basis,
    set_size,
    split_region,
    unlock,
)
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Constraint,
    ConstraintId,
    Division,
    Equal,
    EvenSpacing,
    FixedPoint,
    Item,
    Lock,
    Region,
    RunEnd,
    Unit,
    Void,
    constraint_regions,
    is_locked,
    region_lock,
    spacing_group,
)
from freecad.Shelving.core.solver import (
    LayoutSolveError,
    constraint_spread_mm,
    duplicated_constraint,
    redundant_rules,
    size_fixed_by,
    solve,
)


def _column(sizes_mm: Collection[float] = (300.0, 300.0, 300.0)) -> Unit:
    """A column of 18 mm boards with fixed point ``min``: bottom, A, shelf
    ``s1``, B, shelf ``s2``, C, top; 972 mm tall at the default sizes."""
    items: list[Item] = [Board(thickness_mm=18.0, id="bottom")]
    for index, size_mm in enumerate(sizes_mm):
        items.append(Bay(size_mm=size_mm, id="ABCD"[index]))
        last = index == len(sizes_mm) - 1
        items.append(Board(thickness_mm=18.0, id="top" if last else f"s{index + 1}"))
    return Unit(
        size_mm=Vec3(600.0, 300.0, 18.0 * (len(sizes_mm) + 1) + sum(sizes_mm)),
        root=Division(axis=Axis.Z, items=items, id="column"),
        depth_axis=Axis.Y,
        fixed_point=FixedPoint(z="min"),
    )


def _heights_mm(unit: Unit) -> list[float]:
    """Every opening's height in the column's run, bottom to top."""
    spaces = solve(unit)
    root = unit.root
    assert isinstance(root, Division)
    return [
        spaces[item.id].size.z_mm for item in root.items if not isinstance(item, Board)
    ]


def _bay_mm(unit: Unit) -> dict[str, float]:
    spaces = solve(unit)
    return {name: spaces[name].size.z_mm for name in "ABC" if name in spaces}


def _new_board(before: Unit, after: Unit) -> str:
    def ids(region: Region) -> set[str]:
        if not isinstance(region, Division):
            return set()
        found: set[str] = set()
        for item in region.items:
            found |= {item.id} if isinstance(item, Board) else ids(item)
        return found

    (added,) = ids(after.root) - ids(before.root)
    return added


def _a200_b400() -> Unit:
    """The column after typing 200 into A and unlocking it."""
    typed = set_size(_column(), "A", 200.0, Basis.CLEAR)
    return unlock(typed, "A")


def _lock_id(unit: Unit, region_id: str) -> ConstraintId:
    """The id of the Lock on ``region_id``, active or not."""
    found = region_lock(unit, region_id)
    assert found is not None
    return found.id


def _others(unit: Unit) -> tuple[Constraint, ...]:
    """``unit``'s constraints other than its Locks, in its order."""
    return tuple(c for c in unit.constraints if not isinstance(c, Lock))


# --- Lock ----------------------------------------------------------------


def test_locking_appends_one_active_lock_and_moves_nothing() -> None:
    unit = add_equal(_column(), ["B", "C"])
    locked = lock(unit, "A")
    *kept, added = locked.constraints
    assert tuple(kept) == unit.constraints
    assert isinstance(added, Lock)
    assert (added.region_id, added.basis, added.active) == ("A", Basis.CLEAR, True)
    assert solve(locked) == solve(unit)
    assert lock(locked, "A") is locked


def test_an_active_lock_holds_and_a_deactivated_one_does_not() -> None:
    unit = lock(_column(), "A")
    assert _bay_mm(set_size(unit, "B", 400.0, Basis.CLEAR)) == pytest.approx(
        {"A": 300.0, "B": 400.0, "C": 200.0}
    )
    off = set_constraint_active(unit, _lock_id(unit, "A"), False)
    assert solve(off) == solve(unit)
    assert not is_locked(off, "A")
    assert _bay_mm(set_size(off, "B", 400.0, Basis.CLEAR)) == pytest.approx(
        {"A": 250.0, "B": 400.0, "C": 250.0}
    )


def test_turning_a_lock_back_on_moves_nothing() -> None:
    unit = lock(_column((280.0, 300.0, 320.0)), "A")
    off = set_constraint_active(unit, _lock_id(unit, "A"), False)
    moved = move_board(off, "s1", 18.0 + 250.0)
    on = set_constraint_active(moved, _lock_id(unit, "A"), True)
    assert solve(on) == solve(moved)
    assert _bay_mm(on)["A"] == pytest.approx(250.0)
    assert is_locked(on, "A")


def test_typing_into_a_region_turns_its_deactivated_lock_on() -> None:
    unit = lock(_column(), "A")
    off = set_constraint_active(unit, _lock_id(unit, "A"), False)
    typed = set_size(off, "A", 250.0, Basis.CLEAR)
    (only,) = typed.constraints
    assert isinstance(only, Lock)
    assert (only.id, only.region_id, only.active) == (_lock_id(unit, "A"), "A", True)
    assert _bay_mm(typed)["A"] == pytest.approx(250.0)


def test_locking_a_deactivated_lock_turns_it_on_keeping_its_basis() -> None:
    unit = set_size(_column(), "A", 318.0, Basis.WITH_NEXT)
    off = set_constraint_active(unit, _lock_id(unit, "A"), False)
    on = lock(off, "A")
    assert [
        (c.region_id, c.basis, c.active) for c in on.constraints if isinstance(c, Lock)
    ] == [("A", Basis.WITH_NEXT, True)]
    assert unlock(off, "A") is off


def test_equal_against_two_locks_names_both_locks_and_the_equal() -> None:
    unit = lock(set_size(_column(), "C", 200.0, Basis.CLEAR), "A")
    with pytest.raises(LayoutSolveError) as err:
        add_equal(unit, ["A", "C"])
    assert err.value.reason == "conflict"
    *locks, equal = err.value.constraint_ids
    assert set(locks) == {_lock_id(unit, "A"), _lock_id(unit, "C")}
    assert set(err.value.lock_ids) == set(locks)
    assert equal not in {c.id for c in unit.constraints}


def test_a_locks_basis_changes_without_moving_anything() -> None:
    unit = lock(_thick_s2_column(), "B")
    spaced = set_constraint_basis(unit, _lock_id(unit, "B"), Basis.WITH_NEXT)
    assert [c.basis for c in spaced.constraints] == [Basis.WITH_NEXT]
    assert solve(spaced) == solve(unit)


# --- Equal ---------------------------------------------------------------


def test_an_equal_shares_a_typed_size_between_its_openings() -> None:
    equal = add_equal(_column(), ["A", "B"])
    assert _bay_mm(set_size(equal, "C", 400.0, Basis.CLEAR)) == pytest.approx(
        {"A": 250.0, "B": 250.0, "C": 400.0}
    )


def test_without_an_equal_a_typed_size_moves_only_the_nearest_board() -> None:
    assert _bay_mm(set_size(_column(), "C", 400.0, Basis.CLEAR)) == pytest.approx(
        {"A": 300.0, "B": 200.0, "C": 400.0}
    )


def test_equal_on_three_openings_chains_two_constraints_in_selection_order() -> None:
    unit = add_equal(_column(), ["A", "B", "C"])
    assert [c.region_ids for c in _others(unit) if isinstance(c, Equal)] == [
        ("A", "B"),
        ("B", "C"),
    ]
    assert len(unit.constraints) == 2


def test_equal_keeps_the_first_openings_size() -> None:
    # A keeps 200 mm, so s2 comes down 200 mm and C takes the difference.
    unit = add_equal(_a200_b400(), ["A", "B"])
    assert _bay_mm(unit) == pytest.approx({"A": 200.0, "B": 200.0, "C": 500.0})


def test_equal_changes_the_first_opening_when_locks_rule_out_keeping_it() -> None:
    # A's Lock fixes it at 200 mm, so B cannot keep 400 mm; the boards then
    # move as little as possible.
    unit = add_equal(lock(_a200_b400(), "A"), ["B", "A"])
    assert _bay_mm(unit) == pytest.approx({"A": 200.0, "B": 200.0, "C": 500.0})
    assert [type(c) for c in unit.constraints] == [Lock, Equal]


def test_equal_keeps_the_units_size_when_locks_fill_the_rest_of_the_run() -> None:
    # Holding A with C locked would shrink the column to 772 mm; the hold is
    # refused instead and the boards move as little as possible.
    before = lock(_a200_b400(), "C")
    unit = add_equal(before, ["A", "B"])
    assert unit.size_mm == before.size_mm
    assert _bay_mm(unit) == pytest.approx({"A": 300.0, "B": 300.0, "C": 300.0})


def test_equal_needs_two_openings() -> None:
    selections: list[list[str]] = [["A"], ["A", "A"], []]
    for selection in selections:
        with pytest.raises(EditError):
            add_equal(_column(), selection)
    with pytest.raises(EditError):
        add_equal(_column(), ["A", "s1"])
    with pytest.raises(EditError):
        add_equal(_column(), ["A", "column"])


def test_equal_across_a_width_and_a_height_is_refused() -> None:
    split = split_region(_column(), "A", Axis.X)
    root = split.root
    assert isinstance(root, Division)
    wrap = root.items[1]
    assert isinstance(wrap, Division) and wrap.axis is Axis.X
    left = wrap.items[0]
    with pytest.raises(EditError):
        add_equal(split, ["B", left.id])


def test_a_lock_an_equal_already_implies_is_redundant() -> None:
    unit = lock(add_equal(_column(), ["A", "B"]), "A")
    locked = lock(unit, "B")
    (equal,) = _others(locked)
    b_lock = _lock_id(locked, "B")
    duplicates = duplicated_constraint(locked, solve(locked), b_lock, Axis.Z)
    assert duplicates is not None
    assert {_lock_id(locked, "A"), equal.id} <= set(duplicates)


def test_an_equal_two_locks_already_imply_is_redundant() -> None:
    unit = lock(lock(_column(), "A"), "B")
    equal_unit = add_equal(unit, ["A", "B"])
    (equal,) = _others(equal_unit)
    duplicates = duplicated_constraint(equal_unit, solve(equal_unit), equal.id, Axis.Z)
    assert duplicates == (_lock_id(unit, "A"), _lock_id(unit, "B"))
    assert duplicated_constraint(unit, solve(unit), equal.id, Axis.Z) is None


def test_deleting_a_board_beside_an_equal_opening_drops_it() -> None:
    for pair in (("A", "C"), ("B", "C")):
        unit = add_equal(_column(), list(pair))
        assert merge_at(unit, "s1").constraints == ()
        assert remove_boards(unit, ["s1"]).constraints == ()


def test_deleting_a_board_away_from_an_equal_keeps_it() -> None:
    unit = add_equal(_column(), ["A", "B"])
    split = split_region(unit, "C", Axis.Z)
    kept = merge_at(split, _new_board(unit, split))
    assert [c.region_ids for c in kept.constraints if isinstance(c, Equal)] == [
        ("A", "B")
    ]


def test_splitting_an_equal_opening_along_its_run_drops_the_equal() -> None:
    unit = add_equal(_column(), ["A", "B"])
    assert split_region(unit, "A", Axis.Z).constraints == ()


def test_splitting_an_equal_opening_across_its_run_keeps_the_equal() -> None:
    unit = add_equal(_column(), ["A", "B"])
    split = split_region(unit, "A", Axis.X)
    (equal,) = split.constraints
    assert isinstance(equal, Equal)
    root = split.root
    assert isinstance(root, Division)
    assert equal.region_ids == (root.items[1].id, "B")
    assert _bay_mm(set_size(split, "C", 400.0, Basis.CLEAR))["B"] == pytest.approx(
        250.0
    )


def test_merging_back_a_split_across_an_equal_opening_keeps_it() -> None:
    unit = add_equal(_column(), ["A", "B"])
    split = split_region(unit, "A", Axis.X)
    merged = merge_at(split, _new_board(unit, split))
    (equal,) = merged.constraints
    assert isinstance(equal, Equal)
    assert equal.region_ids[1] == "B"
    assert equal.region_ids[0] in solve(merged)


# --- Even spacing ---------------------------------------------------------


def test_even_spacing_on_the_end_openings_spaces_the_run_and_follows_splits() -> None:
    unit = _a200_b400()
    assert _bay_mm(unit) == pytest.approx({"A": 200.0, "B": 400.0, "C": 300.0})
    even = add_even_spacing(unit, ["A", "C"])
    (spacing,) = even.constraints
    assert isinstance(spacing, EvenSpacing)
    assert (spacing.start, spacing.end) == ("bottom", "top")
    assert _heights_mm(even) == pytest.approx([300.0, 300.0, 300.0])
    split = split_region(even, "C", Axis.Z)
    assert _heights_mm(split) == pytest.approx([220.5] * 4)
    merged = merge_at(split, _new_board(even, split))
    assert _heights_mm(merged) == pytest.approx([300.0] * 3)
    assert [c.id for c in merged.constraints] == [spacing.id]


def test_even_spacing_on_two_boards_spaces_the_openings_between() -> None:
    even = add_even_spacing(_a200_b400(), ["top", "s1"])
    (spacing,) = even.constraints
    assert isinstance(spacing, EvenSpacing)
    assert (spacing.start, spacing.end) == ("s1", "top")
    # The ends s1 and top stay put, so only s2 moves, down 50 mm.
    assert _bay_mm(even) == pytest.approx({"A": 200.0, "B": 350.0, "C": 350.0})


def test_even_spacing_with_one_opening_between_is_refused() -> None:
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["s1", "s2"])
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["B"])


def test_even_spacing_refuses_a_mixed_selection_or_three_boards() -> None:
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["A", "s2"])
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["s1", "s2", "top"])


def test_even_spacing_on_a_sub_bay_and_a_bay_spaces_their_column() -> None:
    # A's left half stands for the side-by-side region that replaced A.
    split = split_region(_column(), "A", Axis.X)
    root = split.root
    assert isinstance(root, Division)
    wrap = root.items[1]
    assert isinstance(wrap, Division)
    even = add_even_spacing(split, [wrap.items[0].id, "B"])
    (spacing,) = even.constraints
    assert isinstance(spacing, EvenSpacing)
    assert (spacing.run_id, spacing.start, spacing.end) == ("column", "bottom", "s2")
    assert spacing_group(even, spacing) == (wrap.id, "B")


def test_even_spacing_on_a_nested_column_ends_at_the_run_ends() -> None:
    """A column whose run holds no carcass boards: its top and bottom bays
    give the run's own ends."""
    split = split_region(_column(), "B", Axis.X)
    root = split.root
    assert isinstance(root, Division)
    wrap = root.items[3]
    assert isinstance(wrap, Division)
    left = wrap.items[0]
    stacked = split_region(split, left.id, Axis.Z)
    stacked = split_region(
        stacked, _bottom_of(stacked, wrap.id), Axis.Z
    )  # three bays in the nested column
    column = _nested_column(stacked, wrap.id)
    bays = [item.id for item in column.items if not isinstance(item, Board)]
    even = add_even_spacing(stacked, [bays[0], bays[-1]])
    (spacing,) = even.constraints
    assert isinstance(spacing, EvenSpacing)
    assert (spacing.start, spacing.end) == (RunEnd.START, RunEnd.END)
    assert spacing_group(even, spacing) == tuple(bays)


def _nested_column(unit: Unit, wrap_id: str) -> Division:
    root = unit.root
    assert isinstance(root, Division)
    wrap = next(item for item in root.items if item.id == wrap_id)
    assert isinstance(wrap, Division)
    column = wrap.items[0]
    assert isinstance(column, Division) and column.axis is Axis.Z
    return column


def _bottom_of(unit: Unit, wrap_id: str) -> str:
    return _nested_column(unit, wrap_id).items[0].id


def test_deleting_an_even_spacing_end_board_drops_it() -> None:
    unit = add_even_spacing(_column(), ["s1", "top"])
    assert merge_at(unit, "s1").constraints == ()


def test_deleting_a_board_inside_an_even_spacing_keeps_it() -> None:
    unit = add_even_spacing(_column(), ["bottom", "top"])
    merged = merge_at(unit, "s1")
    (spacing,) = merged.constraints
    assert isinstance(spacing, EvenSpacing)
    assert spacing_group(merged, spacing) == ("A", "C")
    assert _heights_mm(merged) == pytest.approx([459.0, 459.0])


def test_an_even_spacing_holds_its_inner_boards_and_offers_no_unlock() -> None:
    unit = add_even_spacing(_column(), ["A", "C"])
    (spacing,) = unit.constraints
    assert held_by(unit, "s1") == Held(constraints=(spacing.id,))
    with pytest.raises(EditError):
        move_board(unit, "s1", 400.0)


def test_an_equal_on_two_of_three_openings_leaves_the_shelves_free() -> None:
    unit = add_equal(_column(), ["A", "B"])
    assert held_by(unit, "s1") == Held()
    moved = move_board(unit, "s2", 700.0)
    heights = _bay_mm(moved)
    assert heights["A"] == pytest.approx(heights["B"])


def test_a_lock_and_an_even_spacing_together_name_both() -> None:
    unit = lock(add_even_spacing(_column(), ["A", "C"]), "A")
    (spacing,) = _others(unit)
    held = held_by(unit, "s1")
    assert held is not None
    assert held.constraints == (spacing.id,)


def test_an_even_spacing_and_a_lock_fix_the_column_height() -> None:
    unit = lock(add_even_spacing(_column(), ["A", "C"]), "B")
    (spacing,) = _others(unit)
    assert size_fixed_by(unit, solve(unit), Axis.Z) == (spacing.id, _lock_id(unit, "B"))


def test_a_deactivated_constraint_plays_no_part() -> None:
    unit = add_equal(_column(), ["A", "B"])
    (equal,) = unit.constraints
    off = dataclasses.replace(
        unit, constraints=(dataclasses.replace(equal, active=False),)
    )
    assert _bay_mm(set_size(off, "C", 400.0, Basis.CLEAR)) == pytest.approx(
        {"A": 300.0, "B": 200.0, "C": 400.0}
    )


# --- Equal along an axis, Even along the picks' axis ------------------------


def _three_columns() -> Unit:
    """A unit 972 mm wide and 654 mm tall of 18 mm boards, fixed point
    ``min``, split by dividers ``d1`` and ``d2`` into columns L 300, M 200
    and R 400, each split by one shelf: A1 300, A2 300; B1 200, B2 400;
    C1 250, C2 350, bottom to top."""

    def column(
        name: str, width_mm: float, bays: tuple[str, str], sizes_mm: tuple[float, float]
    ) -> Division:
        return Division(
            axis=Axis.Z,
            id=name,
            items=[
                Board(thickness_mm=18.0, id=f"{name}-bottom"),
                Bay(size_mm=sizes_mm[0], id=bays[0]),
                Board(thickness_mm=18.0, id=f"{name}-shelf"),
                Bay(size_mm=sizes_mm[1], id=bays[1]),
                Board(thickness_mm=18.0, id=f"{name}-top"),
            ],
            size_mm=width_mm,
        )

    return Unit(
        size_mm=Vec3(972.0, 300.0, 654.0),
        root=Division(
            axis=Axis.X,
            id="root",
            items=[
                Board(thickness_mm=18.0, id="left"),
                column("L", 300.0, ("A1", "A2"), (300.0, 300.0)),
                Board(thickness_mm=18.0, id="d1"),
                column("M", 200.0, ("B1", "B2"), (200.0, 400.0)),
                Board(thickness_mm=18.0, id="d2"),
                column("R", 400.0, ("C1", "C2"), (250.0, 350.0)),
                Board(thickness_mm=18.0, id="right"),
            ],
        ),
        depth_axis=Axis.Y,
        fixed_point=FixedPoint(x="min", z="min"),
    )


def _widths_mm(unit: Unit) -> dict[str, float]:
    spaces = solve(unit)
    return {name: spaces[name].size.x_mm for name in "LMR"}


def _bay_heights_mm(unit: Unit) -> dict[str, float]:
    spaces = solve(unit)
    return {
        name: spaces[name].size.z_mm for name in ("A1", "A2", "B1", "B2", "C1", "C2")
    }


def test_equal_width_on_two_bays_makes_their_columns_equal() -> None:
    before = _three_columns()
    unit = add_equal_along(before, ["A1", "B1"], Axis.X)
    (equal,) = unit.constraints
    assert isinstance(equal, Equal) and equal.region_ids == ("L", "M")
    widths_mm = _widths_mm(unit)
    assert abs(widths_mm["L"] - widths_mm["M"]) < 0.001
    assert _bay_heights_mm(unit) == pytest.approx(_bay_heights_mm(before), abs=0.001)


def test_equal_width_keeps_the_first_columns_width_and_moves_free_columns() -> None:
    # M, picked first, keeps 200 mm; R narrows to it and L, which nothing
    # holds, takes up the difference.
    unit = add_equal_along(_three_columns(), ["B1", "C1"], Axis.X)
    assert _widths_mm(unit) == pytest.approx({"L": 500.0, "M": 200.0, "R": 200.0})


def test_even_width_between_two_boards_keeps_its_ends() -> None:
    # The ends d1 and right stay put, so L keeps 300 mm and only d2 moves.
    unit = add_even_spacing(_three_columns(), ["d1", "right"])
    assert _widths_mm(unit) == pytest.approx({"L": 300.0, "M": 300.0, "R": 300.0})
    unit = add_even_spacing(_three_columns(), ["B1", "C1"])
    assert _widths_mm(unit) == pytest.approx({"L": 300.0, "M": 300.0, "R": 300.0})


def test_equal_width_keeps_the_units_width_when_locks_fill_the_rest() -> None:
    before = lock(_three_columns(), "R")
    unit = add_equal_along(before, ["A1", "B1"], Axis.X)
    assert unit.size_mm == before.size_mm
    assert _widths_mm(unit) == pytest.approx({"L": 250.0, "M": 250.0, "R": 400.0})


def test_even_width_keeps_the_units_width_when_locks_fill_the_rest() -> None:
    # R's Lock rules out holding L, so L gives up the room and the unit
    # keeps 972 mm.
    before = lock(_three_columns(), "R")
    unit = add_even_spacing(before, ["B1", "C1"])
    assert unit.size_mm == before.size_mm
    assert _widths_mm(unit) == pytest.approx({"L": 100.0, "M": 400.0, "R": 400.0})


def _nested() -> Unit:
    """:func:`_three_columns` with M's top bay B2 split side by side into P
    100 and Q 200 by board ``pq``, and the columns L 300, M 318, R 282."""
    before = _three_columns()
    root = before.root
    assert isinstance(root, Division)
    left, middle, right = root.items[1], root.items[3], root.items[5]
    assert isinstance(left, Division)
    assert isinstance(middle, Division)
    assert isinstance(right, Division)
    split = Division(
        axis=Axis.X,
        id="B2",
        items=[
            Bay(size_mm=100.0, id="P"),
            Board(thickness_mm=18.0, id="pq"),
            Bay(size_mm=200.0, id="Q"),
        ],
        size_mm=400.0,
    )
    middle_items = list(middle.items)
    middle_items[3] = split
    root_items = list(root.items)
    root_items[1] = dataclasses.replace(left, size_mm=300.0)
    root_items[3] = dataclasses.replace(middle, items=middle_items, size_mm=318.0)
    root_items[5] = dataclasses.replace(right, size_mm=282.0)
    return dataclasses.replace(before, root=dataclasses.replace(root, items=root_items))


def test_even_width_in_a_nested_run_keeps_its_ends() -> None:
    # Spacing P and Q must leave d1 and d2, which bound B2, where they stand.
    unit = add_even_spacing(_nested(), ["P", "Q"])
    (even,) = unit.constraints
    assert isinstance(even, EvenSpacing) and even.run_id == "B2"
    spaces = solve(unit)
    assert (spaces["P"].size.x_mm, spaces["Q"].size.x_mm) == pytest.approx(
        (150.0, 150.0)
    )
    assert _widths_mm(unit) == pytest.approx({"L": 300.0, "M": 318.0, "R": 282.0})


def test_even_spacing_on_a_sub_bay_and_another_columns_bay_spaces_the_columns() -> None:
    unit = add_even_spacing(_nested(), ["P", "C1"])
    (even,) = unit.constraints
    assert isinstance(even, EvenSpacing)
    assert (even.run_id, even.start, even.end) == ("root", "d1", "right")
    assert spacing_group(unit, even) == ("M", "R")
    widths_mm = _widths_mm(unit)
    assert widths_mm["L"] == pytest.approx(300.0)
    assert widths_mm["M"] == pytest.approx(widths_mm["R"], abs=0.001)


def test_equal_height_on_two_bays_makes_them_equal() -> None:
    unit = add_equal_along(_three_columns(), ["A1", "B1"], Axis.Z)
    (equal,) = unit.constraints
    assert isinstance(equal, Equal) and equal.region_ids == ("A1", "B1")


def test_equal_width_on_three_columns_chains_two_equals() -> None:
    unit = add_equal_along(_three_columns(), ["A1", "B1", "C1"], Axis.X)
    assert [c.region_ids for c in unit.constraints if isinstance(c, Equal)] == [
        ("L", "M"),
        ("M", "R"),
    ]
    assert len(unit.constraints) == 2


def test_equal_width_on_bays_of_one_column_is_refused() -> None:
    with pytest.raises(EditError, match="two or more columns"):
        add_equal_along(_three_columns(), ["A1", "A2"], Axis.X)


def test_equal_along_refuses_boards_and_the_unit() -> None:
    with pytest.raises(EditError, match="not boards"):
        add_equal_along(_three_columns(), ["A1", "d1"], Axis.X)
    with pytest.raises(EditError):
        add_equal_along(_three_columns(), ["A1", "root"], Axis.X)
    with pytest.raises(EditError):
        add_equal_along(_three_columns(), [], Axis.X)


def test_even_spacing_on_bays_of_two_columns_spaces_the_root_run() -> None:
    unit = add_even_spacing(_three_columns(), ["A1", "C1"])
    (even,) = unit.constraints
    assert isinstance(even, EvenSpacing)
    assert (even.run_id, even.start, even.end) == ("root", "left", "right")
    widths_mm = _widths_mm(unit)
    assert max(widths_mm.values()) - min(widths_mm.values()) < 0.001


def test_even_spacing_on_two_bays_of_one_column_spaces_its_heights() -> None:
    unit = add_even_spacing(_three_columns(), ["A1", "A2"])
    (even,) = unit.constraints
    assert isinstance(even, EvenSpacing) and even.run_id == "L"


def test_even_spacing_counts_a_column_once_for_its_bays() -> None:
    unit = add_even_spacing(_three_columns(), ["A1", "A2", "C1"])
    (even,) = unit.constraints
    assert isinstance(even, EvenSpacing)
    assert (even.run_id, even.start, even.end) == ("root", "left", "right")
    assert spacing_group(unit, even) == ("L", "M", "R")


def test_even_spacing_on_two_boards_takes_their_run() -> None:
    unit = add_even_spacing(_three_columns(), ["left", "d2"])
    (even,) = unit.constraints
    assert isinstance(even, EvenSpacing)
    assert (even.run_id, even.start, even.end) == ("root", "left", "d2")


@pytest.mark.parametrize(
    "picks",
    [
        pytest.param(["L-shelf", "M-shelf"], id="boards-of-two-runs"),
        pytest.param(["A1"], id="one-bay"),
        pytest.param(["A1", "A1"], id="one-bay-twice"),
        pytest.param(["A1", "d1"], id="mixed"),
        pytest.param(["L", "A1"], id="column-and-its-bay"),
        pytest.param(["A1", "root"], id="whole-unit"),
        pytest.param([], id="nothing"),
    ],
)
def test_even_spacing_refuses_a_selection_with_no_run_to_space(
    picks: list[str],
) -> None:
    with pytest.raises(EditError, match="Select"):
        add_even_spacing(_three_columns(), picks)


def test_even_spacing_on_a_column_with_no_divider_spaces_its_heights() -> None:
    unit = add_even_spacing(_column(), ["A", "C"])
    (even,) = unit.constraints
    assert isinstance(even, EvenSpacing) and even.run_id == "column"


def test_even_spacing_through_the_depth_is_refused() -> None:
    split = split_region(_column(), "B", Axis.Y)
    root = split.root
    assert isinstance(root, Division)
    depth = root.items[3]
    assert isinstance(depth, Division) and depth.axis is Axis.Y
    front, back = (item.id for item in depth.items if not isinstance(item, Board))
    with pytest.raises(EditError, match="side by side"):
        add_even_spacing(split, [front, back])


def test_equal_width_on_a_unit_with_no_divider_is_refused() -> None:
    with pytest.raises(EditError, match="unit's width"):
        add_equal_along(_column(), ["A", "B"], Axis.X)


# --- removing and carrying ------------------------------------------------


def test_removing_constraints_moves_nothing() -> None:
    unit = add_even_spacing(add_equal(_a200_b400(), ["A", "B"]), ["A", "C"])
    ids = [c.id for c in unit.constraints]
    removed = remove_constraints(unit, ids)
    assert removed.constraints == ()
    assert solve(removed) == solve(unit)
    with pytest.raises(EditError):
        remove_constraints(unit, [ConstraintId("nothing")])


def test_constraint_regions_resolve_from_the_tree() -> None:
    unit = add_even_spacing(add_equal(_column(), ["A", "C"]), ["bottom", "top"])
    equal, spacing = unit.constraints
    assert constraint_regions(unit, equal) == ("A", "C")
    assert constraint_regions(unit, spacing) == ("A", "B", "C")


def test_constraint_spread_reads_the_boards() -> None:
    unit = _a200_b400()
    equal = Equal(region_ids=("A", "B"))
    spacing = EvenSpacing(run_id="column", start="bottom", end="top")
    assert constraint_spread_mm(unit, solve(unit), equal) == pytest.approx(200.0)
    assert constraint_spread_mm(unit, solve(unit), spacing) == pytest.approx(200.0)
    gone = EvenSpacing(run_id="column", start="s9", end="top")
    assert constraint_spread_mm(unit, solve(unit), gone) is None


def test_carry_keeps_constraints_through_an_edit_that_changes_no_structure() -> None:
    unit = add_even_spacing(add_equal(_column(), ["A", "B"]), ["A", "C"])
    assert carry_constraints(unit, unit).constraints == unit.constraints


# --- the constraint list's queries and edits ------------------------------


def _with_equal(unit: Unit, first: str, second: str, active: bool = True) -> Unit:
    """``unit`` with an Equal on ``first`` and ``second`` appended as it is,
    solving nothing."""
    equal = Equal(region_ids=(first, second), active=active)
    return dataclasses.replace(unit, constraints=(*unit.constraints, equal))


def test_two_locks_and_an_equal_on_them_are_all_redundant() -> None:
    unit = add_equal(lock(lock(_column(), "A"), "B"), ["A", "B"])
    (equal,) = _others(unit)
    assert redundant_rules(unit, solve(unit)) == {
        _lock_id(unit, "A"),
        _lock_id(unit, "B"),
        equal.id,
    }
    freed = unlock(unit, "B")
    assert redundant_rules(freed, solve(freed)) == frozenset()


def test_locks_that_only_fix_the_height_are_not_redundant() -> None:
    unit = lock(lock(_column(), "A"), "B")
    assert redundant_rules(unit, solve(unit)) == frozenset()


def test_a_deactivated_constraint_is_never_redundant() -> None:
    unit = _with_equal(lock(lock(_column(), "A"), "B"), "A", "B", active=False)
    assert redundant_rules(unit, solve(unit)) == frozenset()


def test_deactivating_an_equal_moves_nothing_and_frees_its_openings() -> None:
    unit = add_equal(_column(), ["A", "B"])
    (equal,) = unit.constraints
    off = set_constraint_active(unit, equal.id, False)
    assert [c.active for c in off.constraints] == [False]
    assert solve(off) == solve(unit)
    assert set_constraint_active(off, equal.id, False) is off
    assert _bay_mm(set_size(off, "A", 400.0, Basis.CLEAR)) == pytest.approx(
        {"A": 400.0, "B": 200.0, "C": 300.0}
    )


def test_reactivating_an_equal_moves_the_boards_least() -> None:
    unit = _with_equal(_column((280.0, 300.0, 320.0)), "A", "B", active=False)
    (equal,) = unit.constraints
    on = set_constraint_active(unit, equal.id, True)
    assert [c.active for c in on.constraints] == [True]
    assert _bay_mm(on) == pytest.approx({"A": 288.0, "B": 288.0, "C": 324.0})


def test_reactivating_against_two_locks_is_a_conflict() -> None:
    locked = lock(set_size(_column(), "C", 200.0, Basis.CLEAR), "A")
    unit = _with_equal(locked, "A", "C", active=False)
    (equal,) = _others(unit)
    with pytest.raises(LayoutSolveError) as caught:
        set_constraint_active(unit, equal.id, True)
    assert caught.value.reason == "conflict"
    assert caught.value.constraint_ids == (
        _lock_id(unit, "C"),
        _lock_id(unit, "A"),
        equal.id,
    )
    assert [c.active for c in _others(unit)] == [False]


def test_activating_an_unknown_constraint_is_refused() -> None:
    with pytest.raises(EditError):
        set_constraint_active(_column(), ConstraintId("nothing"), True)


def test_removing_the_deactivated_keeps_the_active_and_every_lock() -> None:
    unit = add_even_spacing(add_equal(lock(_column(), "A"), ["A", "B"]), ["A", "C"])
    unit = lock(unit, "C")
    a_lock, equal, spacing, c_lock = unit.constraints
    unit = set_constraint_active(unit, equal.id, False)
    unit = set_constraint_active(unit, c_lock.id, False)
    cleared = remove_deactivated(unit)
    assert cleared.constraints == (a_lock, spacing)
    assert solve(cleared) == solve(unit)


def _thick_s2_column() -> Unit:
    """The column with ``s2`` 36 mm thick: 990 mm tall."""
    unit = _column()
    root = unit.root
    assert isinstance(root, Division)
    items = [
        dataclasses.replace(item, thickness_mm=36.0)
        if isinstance(item, Board) and item.id == "s2"
        else item
        for item in root.items
    ]
    return dataclasses.replace(
        unit,
        root=dataclasses.replace(root, items=items),
        size_mm=Vec3(600.0, 300.0, 990.0),
    )


def test_an_equal_in_the_spacing_basis_counts_each_next_board() -> None:
    unit = add_equal(_thick_s2_column(), ["A", "B"])
    (equal,) = unit.constraints
    spaced = set_constraint_basis(unit, equal.id, Basis.WITH_NEXT)
    assert [c.basis for c in spaced.constraints] == [Basis.WITH_NEXT]
    heights = _bay_mm(spaced)
    assert abs(heights["A"] + 18.0 - (heights["B"] + 36.0)) <= 1e-6


def test_the_spacing_basis_needs_a_board_after_every_opening() -> None:
    unit = _column()
    root = unit.root
    assert isinstance(root, Division)
    # C's run ends in a bay, so nothing follows it.
    open_top = dataclasses.replace(
        unit,
        root=dataclasses.replace(root, items=root.items[:-1]),
        size_mm=Vec3(600.0, 300.0, 954.0),
    )
    unit = add_equal(open_top, ["A", "C"])
    (equal,) = unit.constraints
    with pytest.raises(EditError) as caught:
        set_constraint_basis(unit, equal.id, Basis.WITH_NEXT)
    assert caught.value.node_id == "C"


def test_a_deactivated_constraint_changes_basis_without_moving() -> None:
    unit = _with_equal(_column((280.0, 300.0, 320.0)), "A", "B", active=False)
    (equal,) = unit.constraints
    spaced = set_constraint_basis(unit, equal.id, Basis.WITH_NEXT)
    assert [c.basis for c in spaced.constraints] == [Basis.WITH_NEXT]
    assert solve(spaced) == solve(unit)


# --- fully constrained boards and degrees of freedom ----------------------

_CARCASS = {"bottom", "top"}


def _fully_constrained_by_held_by(unit: Unit) -> set[str]:
    """The boards the drag arrow treats as fully constrained."""
    boards = {"bottom", "s1", "s2", "top"}
    return {
        board_id
        for board_id in boards
        if (held := held_by(unit, board_id)) is None or not held.free
    }


def _status(unit: Unit) -> tuple[int, set[str]]:
    status = constraint_status(unit)
    assert status.fully_constrained == _fully_constrained_by_held_by(unit)
    return status.degrees_of_freedom, set(status.fully_constrained)


def test_an_unconstrained_column_keeps_a_freedom_per_shelf() -> None:
    assert _status(_column()) == (2, _CARCASS)


def test_a_lock_fixes_the_shelf_it_reaches() -> None:
    assert _status(lock(_column(), "A")) == (1, _CARCASS | {"s1"})


def test_two_locks_fully_constrain_the_column() -> None:
    assert _status(lock(lock(_column(), "A"), "B")) == (
        0,
        _CARCASS | {"s1", "s2"},
    )


def test_two_equals_fully_constrain_the_column_with_no_lock() -> None:
    unit = add_equal(add_equal(_column(), ["A", "B"]), ["B", "C"])
    assert _status(unit) == (0, _CARCASS | {"s1", "s2"})


def test_a_deactivated_lock_constrains_nothing() -> None:
    locked = lock(_column(), "A")
    off = set_constraint_active(locked, _lock_id(locked, "A"), False)
    assert _status(off) == (2, _CARCASS)


def test_degrees_of_freedom_sum_over_both_elevation_axes() -> None:
    status = constraint_status(_three_columns())
    # The dividers d1 and d2 across, and one shelf in each column up.
    assert status.degrees_of_freedom == 5
    assert status.fully_constrained == {
        "left",
        "right",
        *(f"{column}-{board}" for column in "LMR" for board in ("bottom", "top")),
    }


def test_a_seam_between_openings_adds_no_freedom() -> None:
    """A plinth void and a bay meet with no board between them: the seam
    can move, but it moves no board, so nothing is left to report."""
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 436.0),
        root=Division(
            axis=Axis.Z,
            id="column",
            items=[
                Board(thickness_mm=18.0, id="bottom"),
                Void(size_mm=100.0, id="plinth"),
                Bay(size_mm=300.0, id="A"),
                Board(thickness_mm=18.0, id="top"),
            ],
        ),
        depth_axis=Axis.Y,
        fixed_point=FixedPoint(z="min"),
    )
    status = constraint_status(unit)
    assert status.degrees_of_freedom == 0
    assert status.fully_constrained == {"bottom", "top"}
