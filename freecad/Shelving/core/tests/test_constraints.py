"""Equal and even spacing between openings: creating them, how the solve
honors them, what edits drop them, and what they report, on sh-046's column
of 18 mm boards."""

import dataclasses
from collections.abc import Collection

import pytest

from freecad.Shelving.core.edit import (
    EditError,
    Held,
    add_equal,
    add_even_spacing,
    carry_constraints,
    held_by,
    lock,
    merge_at,
    move_board,
    remove_boards,
    remove_constraints,
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
    ConstraintId,
    Division,
    Equal,
    EvenSpacing,
    FixedPoint,
    Item,
    Region,
    RunEnd,
    Unit,
    constraint_regions,
    spacing_group,
)
from freecad.Shelving.core.solver import (
    LayoutSolveError,
    constraint_spread_mm,
    duplicated_constraint,
    duplicated_locks,
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
    assert [c.region_ids for c in unit.constraints if isinstance(c, Equal)] == [
        ("A", "B"),
        ("B", "C"),
    ]
    assert len(unit.constraints) == 2


def test_equal_makes_unequal_openings_equal_moving_the_boards_least() -> None:
    # s1 and s2 share the move as least squares share it: s1 up 80 mm, s2
    # down 40 mm.
    unit = add_equal(_a200_b400(), ["A", "B"])
    assert _bay_mm(unit) == pytest.approx({"A": 280.0, "B": 280.0, "C": 340.0})


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


def test_equal_against_two_locks_of_different_sizes_is_a_conflict() -> None:
    unit = lock(set_size(_column(), "C", 200.0, Basis.CLEAR), "A")
    with pytest.raises(LayoutSolveError) as err:
        add_equal(unit, ["A", "C"])
    assert err.value.reason == "conflict"
    assert {"A", "C"} <= set(err.value.region_ids)
    assert len(err.value.constraint_ids) == 1


def test_a_lock_an_equal_already_implies_is_redundant() -> None:
    unit = lock(add_equal(_column(), ["A", "B"]), "A")
    locked = lock(unit, "B")
    (equal,) = locked.constraints
    duplicates = duplicated_locks(locked, solve(locked), "B", Axis.Z)
    assert duplicates is not None
    assert {"A", equal.id} <= set(duplicates)


def test_an_equal_two_locks_already_imply_is_redundant() -> None:
    unit = lock(lock(_column(), "A"), "B")
    equal_unit = add_equal(unit, ["A", "B"])
    (equal,) = equal_unit.constraints
    duplicates = duplicated_constraint(equal_unit, solve(equal_unit), equal.id, Axis.Z)
    assert duplicates == ("A", "B")
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
    # s1 up 20 mm and s2 down 40 mm: the least motion that evens B and C.
    assert _bay_mm(even) == pytest.approx({"A": 220.0, "B": 340.0, "C": 340.0})


def test_even_spacing_with_one_opening_between_is_refused() -> None:
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["s1", "s2"])
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["B"])


def test_even_spacing_refuses_a_mixed_or_scattered_selection() -> None:
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["A", "s2"])
    with pytest.raises(EditError):
        add_even_spacing(_column(), ["s1", "s2", "top"])
    split = split_region(_column(), "A", Axis.X)
    root = split.root
    assert isinstance(root, Division)
    wrap = root.items[1]
    assert isinstance(wrap, Division)
    with pytest.raises(EditError):
        add_even_spacing(split, [wrap.items[0].id, "B"])


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
    (spacing,) = unit.constraints
    held = held_by(unit, "s1")
    assert held is not None
    assert held.constraints == (spacing.id,)


def test_an_even_spacing_and_a_lock_fix_the_column_height() -> None:
    unit = lock(add_even_spacing(_column(), ["A", "C"]), "B")
    (spacing,) = unit.constraints
    assert size_fixed_by(unit, solve(unit), Axis.Z) == ("B", spacing.id)


def test_a_deactivated_constraint_plays_no_part() -> None:
    unit = add_equal(_column(), ["A", "B"])
    (equal,) = unit.constraints
    off = dataclasses.replace(
        unit, constraints=(dataclasses.replace(equal, active=False),)
    )
    assert _bay_mm(set_size(off, "C", 400.0, Basis.CLEAR)) == pytest.approx(
        {"A": 300.0, "B": 200.0, "C": 400.0}
    )


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
