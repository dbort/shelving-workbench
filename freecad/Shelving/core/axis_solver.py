"""Least-motion solver for positions along one axis under linear constraints.

The caller names every position and constraint; the engine knows nothing of
boards or regions. :func:`solve` moves the positions as little as possible
from their current values, in the Sketcher's manner: each position's squared
motion counts with weight 1, and each :class:`Target` pulls its position with
a weight heavy enough to land on it whenever the constraints allow.

The method is the Goldfarb-Idnani dual active-set method for a strictly
convex quadratic program. It starts from the unconstrained optimum and adds
violated constraints one at a time, so an infeasible system is detected at
the constraint that cannot be added, together with the active constraints
that rule it out. Elimination is exact on a dense QR factorization that is
updated, never recomputed, as constraints enter and leave the active set;
there is no iteration that converges toward a tolerance.

All lengths are float millimeters. Standard library only: the systems are
tens of positions, and the core suite stays free of dependencies.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import NewType

PositionId = NewType("PositionId", str)
ConstraintId = NewType("ConstraintId", str)

TARGET_WEIGHT: float = 1e9
"""Default :attr:`Target.weight`.

A target misses by at most the summed weight of the positions it drags along
times the distance, over its own weight: 40 positions moved 3000 mm miss by
about 1.2e-4 mm. The weight also stays small enough that the scaled
coordinates the solve works in keep about seven significant digits.
"""

# Relative size below which a residual or multiplier counts as zero. The
# coefficients callers write are small integers, so a real dependency leaves
# rounding noise near 1e-15 and a real independence leaves a residual near 1.
_ZERO = 1e-9


@dataclass(frozen=True)
class Relation:
    """Linear equality ``sum(coefficients[p] * position[p]) == constant_mm``."""

    id: ConstraintId
    # A position absent from the mapping has coefficient 0.
    coefficients: Mapping[PositionId, float]
    constant_mm: float


@dataclass(frozen=True)
class LowerBound:
    """Inequality ``position[high] - position[low] >= min_mm``."""

    id: ConstraintId
    low: PositionId
    high: PositionId
    min_mm: float


@dataclass(frozen=True)
class Target:
    """A pull of one position toward ``target_mm``.

    Several targets on one position combine as a weighted mean.
    """

    position: PositionId
    target_mm: float
    # Relative to the weight 1 every position's own motion carries.
    weight: float = TARGET_WEIGHT


@dataclass(frozen=True)
class Freedom:
    """Answer of :meth:`Solved.freedom` for one linear expression."""

    # True when the relations and active bounds leave the expression no
    # freedom: every solution near this one gives it the same value.
    determined: bool
    # The relations and active bounds the expression is a combination of;
    # empty when it is free, and empty for a constant expression.
    fixed_by: frozenset[ConstraintId]


class _QR:
    """Thin QR factorization ``[a_1 ... a_m] = Q R`` of columns of length ``n``.

    Columns are added by Gram-Schmidt, run twice so that orthogonality holds
    to rounding, and removed by Givens rotations.
    """

    def __init__(self, n: int) -> None:
        self.n = n
        # Q's orthonormal columns.
        self.q: list[list[float]] = []
        # R by rows; row i has len(self.q) entries, zero below the diagonal.
        self.r: list[list[float]] = []

    def project(
        self, a: Sequence[float]
    ) -> tuple[list[float], list[float], list[float]]:
        """Returns ``(coefficients, residual, q_coordinates)`` of ``a``.

        ``residual`` is ``a`` minus its projection onto the span of the
        columns, ``coefficients`` solves ``A coefficients = a - residual``,
        and ``q_coordinates`` is what :meth:`append` needs to add ``a``.
        """
        residual = list(a)
        coords = [0.0] * len(self.q)
        for _ in range(2):
            for i, qi in enumerate(self.q):
                c = math.fsum(x * y for x, y in zip(qi, residual, strict=True))
                coords[i] += c
                if c:
                    for k in range(self.n):
                        residual[k] -= c * qi[k]
        return self._back_substitute(coords), residual, coords

    def append(self, coords: Sequence[float], residual: Sequence[float]) -> None:
        """Adds the column :meth:`project` returned these two values for.

        The residual must be nonzero, so the column is independent.
        """
        rho = math.sqrt(math.fsum(x * x for x in residual))
        for row, c in zip(self.r, coords, strict=True):
            row.append(c)
        self.r.append([0.0] * len(self.q) + [rho])
        self.q.append([x / rho for x in residual])

    def remove(self, index: int) -> None:
        """Removes column ``index``; later columns shift down by one."""
        m = len(self.q)
        for row in self.r:
            del row[index]
        for k in range(index, m - 1):
            a = self.r[k][k]
            b = self.r[k + 1][k]
            h = math.hypot(a, b)
            c, s = a / h, b / h
            rk, rk1 = self.r[k], self.r[k + 1]
            for j in range(k, m - 1):
                rk[j], rk1[j] = c * rk[j] + s * rk1[j], -s * rk[j] + c * rk1[j]
            rk1[k] = 0.0
            qk, qk1 = self.q[k], self.q[k + 1]
            for i in range(self.n):
                qk[i], qk1[i] = c * qk[i] + s * qk1[i], -s * qk[i] + c * qk1[i]
        self.r.pop()
        self.q.pop()

    def least_norm(self, rhs: Sequence[float]) -> list[float]:
        """Returns the shortest ``v`` with ``A^T v == rhs``."""
        m = len(self.q)
        w = [0.0] * m
        for i in range(m):
            w[i] = (rhs[i] - math.fsum(self.r[j][i] * w[j] for j in range(i))) / self.r[
                i
            ][i]
        v = [0.0] * self.n
        for wi, qi in zip(w, self.q, strict=True):
            for k in range(self.n):
                v[k] += wi * qi[k]
        return v

    def _back_substitute(self, coords: Sequence[float]) -> list[float]:
        m = len(coords)
        x = [0.0] * m
        for i in range(m - 1, -1, -1):
            row = self.r[i]
            x[i] = (
                coords[i] - math.fsum(row[j] * x[j] for j in range(i + 1, m))
            ) / row[i]
        return x


@dataclass(frozen=True)
class _Basis:
    """Independent rows of the relations and active bounds, for freedom queries."""

    index: Mapping[PositionId, int]
    ids: tuple[ConstraintId, ...]
    qr: _QR


@dataclass(frozen=True)
class Solved:
    """A solution of :func:`solve`."""

    # Every position given to solve, solved.
    positions_mm: Mapping[PositionId, float]
    # The bounds that hold with equality at the solution, whether or not the
    # solution presses on them.
    active_bounds: frozenset[ConstraintId]
    # Each relation implied by relations listed before it, mapped to the
    # relations it is a combination of. A redundant relation is consistent,
    # and the solve treats it as absent.
    redundant: Mapping[ConstraintId, frozenset[ConstraintId]]
    _basis: _Basis = field(repr=False, compare=False)

    def freedom(self, expression: Mapping[PositionId, float]) -> Freedom:
        """Whether the relations and active bounds determine ``expression``.

        ``expression`` maps positions to coefficients, as
        :attr:`Relation.coefficients` does. When the expression is
        determined, ``fixed_by`` names one set of constraints it is a
        combination of: the non-redundant relations, then the active bounds
        in the order given to :func:`solve`, each bound kept only when it is
        independent of those before it. Among several bounds active at once
        that imply each other, the later ones are never named.

        Raises ``ValueError`` for a position :func:`solve` was not given.
        """
        basis = self._basis
        e = _dense(expression, basis.index, "expression")
        coefficients, residual, _ = basis.qr.project(e)
        scale = max((abs(x) for x in e), default=0.0)
        if max((abs(x) for x in residual), default=0.0) > _ZERO * scale:
            return Freedom(determined=False, fixed_by=frozenset())
        return Freedom(determined=True, fixed_by=_nonzero(basis.ids, coefficients))


@dataclass(frozen=True)
class Conflict:
    """The result of :func:`solve` when no positions meet every constraint."""

    # The set the method found: those constraints alone admit no solution,
    # but a proper subset of them may also admit no solution, so it is small
    # without being guaranteed minimal. It is the first conflict found; the
    # system may hold others.
    conflicting: frozenset[ConstraintId]
    # As Solved.redundant, over the relations examined before the conflict.
    redundant: Mapping[ConstraintId, frozenset[ConstraintId]]


@dataclass(frozen=True)
class _Row:
    """A constraint ``normal . x >= bound_mm``, or ``==`` when ``equality``."""

    id: ConstraintId
    normal: tuple[float, ...]
    bound_mm: float
    equality: bool


def solve(
    current_mm: Mapping[PositionId, float],
    relations: Sequence[Relation],
    bounds: Sequence[LowerBound],
    targets: Sequence[Target] = (),
) -> Solved | Conflict:
    """Moves the positions as little as possible to meet every constraint.

    Minimizes the sum over positions of the squared motion from
    ``current_mm``, plus each target's weight times its position's squared
    distance from it, subject to every relation and bound. The objective is
    strictly convex, so a feasible system has exactly one solution.

    Relations are examined in order, and one that the earlier ones imply is
    reported redundant rather than failing, when it is consistent with them.
    An inconsistent one is a conflict.

    Raises ``ValueError`` when a constraint or target names a position
    missing from ``current_mm``, when two constraints share an id, or when a
    target's weight is not positive.
    """
    index = {p: i for i, p in enumerate(current_mm)}
    n = len(index)
    seen: set[ConstraintId] = set()
    for cid in [r.id for r in relations] + [bound.id for bound in bounds]:
        if cid in seen:
            raise ValueError(f"constraint id {cid!r} is used twice")
        seen.add(cid)

    equalities = [
        _Row(r.id, tuple(_dense(r.coefficients, index, r.id)), r.constant_mm, True)
        for r in relations
    ]
    inequalities: list[_Row] = []
    for bound in bounds:
        normal = [0.0] * n
        for p, c in ((bound.high, 1.0), (bound.low, -1.0)):
            if p not in index:
                raise ValueError(f"{bound.id!r} names unknown position {p!r}")
            normal[index[p]] += c
        inequalities.append(_Row(bound.id, tuple(normal), bound.min_mm, False))

    # The objective is sum_i h_i (x_i - p_i)^2 plus a constant. Working in
    # y_i = sqrt(h_i) x_i turns it into a plain distance from y_p, so the
    # solve is a Euclidean projection onto the feasible polyhedron.
    pull = [1.0] * n
    pulled_mm = [float(v) for v in current_mm.values()]
    for t in targets:
        if t.position not in index:
            raise ValueError(f"target names unknown position {t.position!r}")
        if not t.weight > 0.0:
            raise ValueError(f"target on {t.position!r} has weight {t.weight}")
        i = index[t.position]
        pulled_mm[i] += t.weight * t.target_mm
        pull[i] += t.weight
    root = [math.sqrt(h) for h in pull]
    y_free_mm = [pulled_mm[i] / pull[i] * root[i] for i in range(n)]

    magnitudes_mm = [abs(v) for v in current_mm.values()]
    magnitudes_mm += [abs(t.target_mm) for t in targets]
    magnitudes_mm += [abs(r.bound_mm) for r in equalities + inequalities]
    tol_mm = _ZERO * max([1.0, *magnitudes_mm])

    def scaled(row: _Row, sign: float) -> list[float]:
        return [sign * row.normal[i] / root[i] for i in range(n)]

    def slack_mm(a: Sequence[float], b_mm: float, y_mm: Sequence[float]) -> float:
        return math.fsum(ai * yi for ai, yi in zip(a, y_mm, strict=True)) - b_mm

    def dependent(residual: Sequence[float], row: _Row) -> bool:
        # The residual in the caller's coordinates, so a heavy target's
        # small scaled entries cannot pass for a dependency.
        scale = max((abs(v) for v in row.normal), default=0.0)
        return (
            max((abs(residual[i] * root[i]) for i in range(n)), default=0.0)
            <= _ZERO * scale
        )

    y_mm = list(y_free_mm)
    qr = _QR(n)
    active: list[_Row] = []
    # Oriented right-hand sides of the active rows, parallel to `active`.
    rhs_mm: list[float] = []
    # Lagrange multipliers of the active rows, parallel to `active`.
    multipliers: list[float] = []
    redundant: dict[ConstraintId, frozenset[ConstraintId]] = {}

    for row in equalities:
        # Orient the equality as a violated inequality so the dual step
        # moves toward it.
        sign = (
            1.0
            if slack_mm(row.normal, row.bound_mm, _positions_mm(y_mm, root)) <= 0.0
            else -1.0
        )
        a = scaled(row, sign)
        b_mm = sign * row.bound_mm
        slack_now_mm = slack_mm(a, b_mm, y_mm)
        coefficients, residual, coords = qr.project(a)
        if dependent(residual, row):
            duplicates = _nonzero([r.id for r in active], coefficients)
            if slack_now_mm >= -tol_mm:
                redundant[row.id] = duplicates
                continue
            return Conflict(frozenset({row.id}) | duplicates, redundant)
        step = -slack_now_mm / math.fsum(v * v for v in residual)
        y_mm = [yi + step * zi for yi, zi in zip(y_mm, residual, strict=True)]
        multipliers = [
            u - step * c for u, c in zip(multipliers, coefficients, strict=True)
        ]
        qr.append(coords, residual)
        active.append(row)
        rhs_mm.append(b_mm)
        multipliers.append(step)

    # Each round adds one constraint and may drop several, and the dual
    # objective rises every round, so the method ends; the cap guards
    # against a cycle that rounding could set up.
    for _ in range(50 * (n + len(inequalities)) + 100):
        active_ids = {r.id for r in active}
        worst: _Row | None = None
        worst_slack_mm = -tol_mm
        x_mm = _positions_mm(y_mm, root)
        for row in inequalities:
            if row.id in active_ids:
                continue
            slack_now_mm = slack_mm(row.normal, row.bound_mm, x_mm)
            if slack_now_mm < worst_slack_mm:
                worst, worst_slack_mm = row, slack_now_mm
        if worst is None:
            break
        a = scaled(worst, 1.0)
        added = 0.0
        while True:
            coefficients, residual, coords = qr.project(a)
            r_scale = max((abs(c) for c in coefficients), default=0.0)
            drop: int | None = None
            partial = math.inf
            for k, row in enumerate(active):
                c = coefficients[k]
                if (
                    not row.equality
                    and c > _ZERO * r_scale
                    and multipliers[k] / c < partial
                ):
                    partial, drop = multipliers[k] / c, k
            is_dependent = dependent(residual, worst)
            if is_dependent and drop is None:
                culprits = _nonzero([r.id for r in active], coefficients)
                return Conflict(frozenset({worst.id}) | culprits, redundant)
            full = math.inf
            if not is_dependent:
                full = -slack_mm(a, worst.bound_mm, y_mm) / math.fsum(
                    v * v for v in residual
                )
                full = max(full, 0.0)
            step = min(partial, full)
            if not is_dependent:
                y_mm = [yi + step * zi for yi, zi in zip(y_mm, residual, strict=True)]
            multipliers = [
                u - step * c for u, c in zip(multipliers, coefficients, strict=True)
            ]
            added += step
            if full <= partial:
                qr.append(coords, residual)
                active.append(worst)
                rhs_mm.append(worst.bound_mm)
                multipliers.append(added)
                break
            assert drop is not None
            qr.remove(drop)
            del active[drop], rhs_mm[drop], multipliers[drop]
    else:
        raise RuntimeError("axis solve did not settle")

    # Recompute the solution from the final active set alone, so the
    # incremental steps leave no accumulated rounding in the answer.
    _, outside_mm, _ = qr.project(y_free_mm)
    inside_mm = qr.least_norm(rhs_mm)
    x_mm = _positions_mm(
        [o + v for o, v in zip(outside_mm, inside_mm, strict=True)], root
    )

    tight = [
        row
        for row in inequalities
        if slack_mm(row.normal, row.bound_mm, x_mm) <= tol_mm
    ]
    basis_qr = _QR(n)
    basis_ids: list[ConstraintId] = []
    for row in [r for r in active if r.equality] + tight:
        _, residual, coords = basis_qr.project(row.normal)
        scale = max((abs(v) for v in row.normal), default=0.0)
        if max((abs(v) for v in residual), default=0.0) > _ZERO * scale:
            basis_qr.append(coords, residual)
            basis_ids.append(row.id)

    return Solved(
        positions_mm={p: x_mm[i] for p, i in index.items()},
        active_bounds=frozenset(row.id for row in tight),
        redundant=redundant,
        _basis=_Basis(index, tuple(basis_ids), basis_qr),
    )


def _dense(
    coefficients: Mapping[PositionId, float],
    index: Mapping[PositionId, int],
    owner: str,
) -> list[float]:
    """Returns ``coefficients`` as a list in ``index`` order.

    Raises ``ValueError`` naming ``owner`` for a position not in ``index``.
    """
    dense = [0.0] * len(index)
    for p, c in coefficients.items():
        if p not in index:
            raise ValueError(f"{owner!r} names unknown position {p!r}")
        dense[index[p]] += c
    return dense


def _nonzero(
    ids: Sequence[ConstraintId], coefficients: Sequence[float]
) -> frozenset[ConstraintId]:
    """Returns the ids whose coefficient is not zero relative to the largest."""
    scale = max((abs(c) for c in coefficients), default=0.0)
    return frozenset(
        i for i, c in zip(ids, coefficients, strict=True) if abs(c) > _ZERO * scale
    )


def _positions_mm(y_mm: Sequence[float], root: Sequence[float]) -> list[float]:
    return [yi / ri for yi, ri in zip(y_mm, root, strict=True)]
