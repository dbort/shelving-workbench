"""Axis solver: least motion, targets, conflicts, redundancy and freedom."""

import itertools
import random
from collections.abc import Mapping, Sequence

import pytest

from freecad.Shelving.core.axis_solver import (
    Conflict,
    ConstraintId,
    LowerBound,
    PositionId,
    Relation,
    Solved,
    Target,
    solve,
)

X0, X1, X2, X3 = (PositionId(f"x{i}") for i in range(4))


def _cid(name: str) -> ConstraintId:
    return ConstraintId(name)


def _diff(cid: str, low: PositionId, high: PositionId, value_mm: float) -> Relation:
    """``high - low == value_mm``."""
    return Relation(_cid(cid), {high: 1.0, low: -1.0}, value_mm)


def _fix(cid: str, position: PositionId, value_mm: float) -> Relation:
    return Relation(_cid(cid), {position: 1.0}, value_mm)


def _bound(cid: str, low: PositionId, high: PositionId, min_mm: float) -> LowerBound:
    return LowerBound(_cid(cid), low, high, min_mm)


def _solved(result: Solved | Conflict) -> Solved:
    assert isinstance(result, Solved), result
    return result


def _conflict(result: Solved | Conflict) -> Conflict:
    assert isinstance(result, Conflict), result
    return result


def _ids(*names: str) -> frozenset[ConstraintId]:
    return frozenset(_cid(n) for n in names)


CURRENT_MM: Mapping[PositionId, float] = {X0: 0.0, X1: 10.0, X2: 25.0, X3: 40.0}


def test_consistent_relations_without_targets_move_nothing() -> None:
    result = _solved(
        solve(
            CURRENT_MM,
            [_diff("a", X0, X1, 10.0), _fix("o", X0, 0.0), _diff("b", X2, X3, 15.0)],
            [_bound("lo", X1, X2, 5.0)],
        )
    )
    for p, value_mm in CURRENT_MM.items():
        assert abs(result.positions_mm[p] - value_mm) <= 1e-9
    assert result.redundant == {}
    assert result.active_bounds == frozenset()


def test_contradictory_relations_conflict_naming_both() -> None:
    result = _conflict(
        solve(
            CURRENT_MM, [_diff("ten", X0, X1, 10.0), _diff("twelve", X0, X1, 12.0)], []
        )
    )
    assert result.conflicting == _ids("ten", "twelve")


def test_implied_relation_solves_and_is_reported_redundant() -> None:
    relations = [
        _diff("a", X0, X1, 12.0),
        _diff("b", X1, X2, 15.0),
        _diff("sum", X0, X2, 27.0),
    ]
    result = _solved(solve(CURRENT_MM, relations, []))
    assert result.redundant == {_cid("sum"): _ids("a", "b")}
    assert result.positions_mm[X1] - result.positions_mm[X0] == pytest.approx(
        12.0, abs=1e-9
    )
    assert result.positions_mm[X2] - result.positions_mm[X1] == pytest.approx(
        15.0, abs=1e-9
    )


def test_a_repeated_relation_is_redundant_with_its_twin() -> None:
    result = _solved(
        solve(CURRENT_MM, [_fix("lock", X1, 10.0), _fix("again", X1, 10.0)], [])
    )
    assert result.redundant == {_cid("again"): _ids("lock")}


def test_bounds_the_relations_cannot_meet_conflict_naming_them() -> None:
    result = _conflict(
        solve(
            CURRENT_MM,
            [_fix("left", X0, 0.0), _fix("right", X2, 10.0)],
            [_bound("gap1", X0, X1, 6.0), _bound("gap2", X1, X2, 6.0)],
        )
    )
    assert result.conflicting == _ids("left", "right", "gap1", "gap2")


def test_bounds_alone_can_conflict() -> None:
    result = _conflict(
        solve(
            CURRENT_MM,
            [],
            [
                _bound("up", X0, X1, 5.0),
                _bound("down", X1, X0, 5.0),
                _bound("free", X2, X3, 1.0),
            ],
        )
    )
    assert result.conflicting == _ids("up", "down")


def test_freedom_names_the_relations_that_fix_a_difference() -> None:
    result = _solved(
        solve(
            CURRENT_MM,
            [_diff("a", X0, X1, 10.0), _diff("b", X1, X2, 15.0)],
            [_bound("free", X2, X3, 5.0)],
        )
    )
    fixed = result.freedom({X2: 1.0, X0: -1.0})
    assert fixed.determined
    assert fixed.fixed_by == _ids("a", "b")
    free = result.freedom({X3: 1.0, X2: -1.0})
    assert not free.determined
    assert free.fixed_by == frozenset()
    assert not result.freedom({X0: 1.0}).determined


def test_freedom_counts_an_active_bound() -> None:
    result = _solved(
        solve(
            CURRENT_MM,
            [_fix("floor", X0, 0.0)],
            [_bound("min", X0, X1, 10.0)],
            [Target(X1, 2.0)],
        )
    )
    assert result.active_bounds == _ids("min")
    held = result.freedom({X1: 1.0})
    assert held.determined
    assert held.fixed_by == _ids("floor", "min")


def test_freedom_rejects_an_unknown_position() -> None:
    result = _solved(solve(CURRENT_MM, [], []))
    with pytest.raises(ValueError, match="nowhere"):
        result.freedom({PositionId("nowhere"): 1.0})


def test_target_without_an_active_bound_lands() -> None:
    result = _solved(
        solve(
            CURRENT_MM,
            [_diff("a", X0, X1, 10.0), _diff("b", X1, X2, 15.0)],
            [_bound("gap", X0, X2, 5.0)],
            [Target(X1, 2500.0)],
        )
    )
    assert abs(result.positions_mm[X1] - 2500.0) <= 0.001
    assert result.positions_mm[X0] == pytest.approx(2490.0, abs=0.001)
    assert result.active_bounds == frozenset()


def test_target_beyond_the_bounds_stops_where_they_hold_it() -> None:
    result = _solved(
        solve(
            CURRENT_MM,
            [_fix("floor", X0, 0.0), _fix("roof", X3, 40.0)],
            [
                _bound("a", X0, X1, 5.0),
                _bound("b", X1, X2, 5.0),
                _bound("c", X2, X3, 5.0),
            ],
            [Target(X1, 1000.0)],
        )
    )
    assert result.positions_mm[X1] == pytest.approx(30.0, abs=1e-6)
    assert result.positions_mm[X2] == pytest.approx(35.0, abs=1e-6)
    assert result.active_bounds == _ids("b", "c")


def test_relation_over_three_positions_solves() -> None:
    result = _solved(
        solve(
            CURRENT_MM,
            [
                Relation(_cid("even"), {X0: 1.0, X2: 1.0, X1: -2.0}, 0.0),
                _fix("floor", X0, 0.0),
                _fix("roof", X2, 30.0),
            ],
            [],
        )
    )
    assert result.positions_mm[X1] == pytest.approx(15.0, abs=1e-9)


def test_forty_chained_positions_with_one_target() -> None:
    positions = [PositionId(f"p{i}") for i in range(40)]
    current_mm = {p: 30.0 * i for i, p in enumerate(positions)}
    relations: list[Relation] = [_fix("floor", positions[0], 0.0)]
    bounds: list[LowerBound] = []
    for i, (low, high) in enumerate(itertools.pairwise(positions)):
        if i % 2 == 0:
            relations.append(_diff(f"thick{i}", low, high, 30.0))
        else:
            bounds.append(_bound(f"gap{i}", low, high, 5.0))
    relations.append(_fix("roof", positions[-1], 30.0 * 39))
    result = _solved(
        solve(current_mm, relations, bounds, [Target(positions[19], 420.0)])
    )
    x = result.positions_mm
    assert abs(x[positions[19]] - 420.0) <= 0.001
    for r in relations:
        assert sum(c * x[p] for p, c in r.coefficients.items()) == pytest.approx(
            r.constant_mm, abs=1e-6
        )
    for b in bounds:
        assert x[b.high] - x[b.low] >= b.min_mm - 1e-6
    # Pulling the board p18-p19 down 150 mm closes each 30 mm gap below it
    # to 5 mm, so it pushes the five boards beneath, the nearest farthest.
    # The board above stays where it is.
    assert {_cid(f"gap{i}") for i in (9, 11, 13, 15, 17)} <= result.active_bounds
    # The target's finite weight lets the pushed boards hold it back by
    # about 1e-6 mm.
    assert x[positions[16]] == pytest.approx(480.0 - 125.0, abs=1e-4)
    assert x[positions[8]] == pytest.approx(240.0 - 25.0, abs=1e-4)
    assert x[positions[6]] == pytest.approx(180.0, abs=1e-6)
    assert x[positions[20]] == pytest.approx(600.0, abs=1e-6)


def test_a_target_drags_a_locked_chain_far_and_still_lands() -> None:
    positions = [PositionId(f"p{i}") for i in range(40)]
    current_mm = {p: 18.0 * i for i, p in enumerate(positions)}
    relations = [
        _diff(f"t{i}", low, high, 18.0)
        for i, (low, high) in enumerate(itertools.pairwise(positions))
    ]
    result = _solved(solve(current_mm, relations, [], [Target(positions[0], 3000.0)]))
    assert abs(result.positions_mm[positions[0]] - 3000.0) <= 0.001


def test_positions_outside_every_constraint_stay_put() -> None:
    result = _solved(solve(CURRENT_MM, [_fix("move", X0, 7.0)], []))
    assert result.positions_mm[X0] == pytest.approx(7.0, abs=1e-12)
    assert result.positions_mm[X3] == 40.0


@pytest.mark.parametrize(
    ("relations", "bounds", "targets", "message"),
    [
        ([_fix("r", PositionId("ghost"), 0.0)], [], [], "ghost"),
        ([], [_bound("b", X0, PositionId("ghost"), 1.0)], [], "ghost"),
        ([], [], [Target(PositionId("ghost"), 1.0)], "ghost"),
        ([_fix("same", X0, 0.0)], [_bound("same", X0, X1, 1.0)], [], "twice"),
        ([], [], [Target(X0, 1.0, weight=0.0)], "weight"),
    ],
)
def test_malformed_input_raises(
    relations: Sequence[Relation],
    bounds: Sequence[LowerBound],
    targets: Sequence[Target],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        solve(CURRENT_MM, relations, bounds, targets)


def _objective(
    x: Mapping[PositionId, float],
    current_mm: Mapping[PositionId, float],
    targets: Sequence[Target],
) -> float:
    motion = sum((x[p] - current_mm[p]) ** 2 for p in current_mm)
    return motion + sum(t.weight * (x[t.position] - t.target_mm) ** 2 for t in targets)


def _feasible(
    x: Mapping[PositionId, float],
    relations: Sequence[Relation],
    bounds: Sequence[LowerBound],
) -> bool:
    ok_relations = all(
        abs(sum(c * x[p] for p, c in r.coefficients.items()) - r.constant_mm) <= 1e-6
        for r in relations
    )
    return ok_relations and all(x[b.high] - x[b.low] >= b.min_mm - 1e-6 for b in bounds)


@pytest.mark.parametrize("seed", range(60))
def test_matches_enumerating_every_active_set(seed: int) -> None:
    """The optimum is the best feasible equality-constrained solution over
    all subsets of bounds held as equalities, so enumeration checks the
    active-set logic against the equality path alone.
    """
    rng = random.Random(seed)
    positions = [X0, X1, X2, X3]
    current_mm = {p: rng.uniform(-50.0, 50.0) for p in positions}
    relations: list[Relation] = []
    for k in range(rng.randint(0, 2)):
        low, high = rng.sample(positions, 2)
        relations.append(_diff(f"r{k}", low, high, rng.uniform(-20.0, 20.0)))
    bounds: list[LowerBound] = []
    for k in range(rng.randint(1, 4)):
        low, high = rng.sample(positions, 2)
        bounds.append(_bound(f"b{k}", low, high, rng.uniform(-10.0, 30.0)))
    targets = [
        Target(
            rng.choice(positions),
            rng.uniform(-80.0, 80.0),
            weight=rng.uniform(0.5, 5.0),
        )
    ]
    result = solve(current_mm, relations, bounds, targets)

    best: float | None = None
    for size in range(len(bounds) + 1):
        for held in itertools.combinations(bounds, size):
            as_relations = [_diff(b.id + "=", b.low, b.high, b.min_mm) for b in held]
            candidate = solve(current_mm, relations + as_relations, [], targets)
            if isinstance(candidate, Solved) and _feasible(
                candidate.positions_mm, relations, bounds
            ):
                value = _objective(candidate.positions_mm, current_mm, targets)
                best = value if best is None else min(best, value)

    if best is None:
        conflict = _conflict(result)
        named_relations = [r for r in relations if r.id in conflict.conflicting]
        named_bounds = [b for b in bounds if b.id in conflict.conflicting]
        assert isinstance(solve(current_mm, named_relations, named_bounds), Conflict)
    else:
        solved = _solved(result)
        assert _feasible(solved.positions_mm, relations, bounds)
        assert _objective(solved.positions_mm, current_mm, targets) == pytest.approx(
            best, rel=1e-9, abs=1e-9
        )
