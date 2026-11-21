"""Layout of a region tree's stored geometry, and the engine calls an edit
solves its result with.

``solve`` places one :class:`~freecad.Shelving.core.geometry.Space` per
region and board id from the sizes the tree stores and checks that they fit:
it never moves anything. An edit that moves boards builds the constraint
system for one axis with :func:`solve_axis`, which hands it to
:func:`freecad.Shelving.core.axis_solver.solve` and writes the solved sizes
back into the tree, so every unit an edit returns already holds the geometry
``solve`` lays out.

The system's positions are each board's low face on runs along the axis and
the unit's two outer faces, plus one seam where two regions meet with no
board between them. A board's high face is its low face plus its extent, so
a run of boards face to face shares one position. The engine gives every
position the same motion weight, so a seam's motion counts as much as a
board's; the outer faces' motion never decides anything, since the fixed
point and the size, or the faces held for a drag, place them. Relations hold
the boards in their runs, the unit's fixed point, each active lock, each
other active constraint, and the unit's size, in that order: the engine
reports the later member of a dependent group as redundant. A lock holds its
opening's clear size at the size the tree stores. When the locks and
constraints already determine the size, it is a reference, as a Sketcher
reference dimension is: the size relation is left out and the size follows
them. A deactivated constraint plays no part.

All lengths are float millimeters. :data:`EPS_MM` is the tolerance for the
"does it fit" and "is it positive" comparisons only.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from freecad.Shelving.core import axis_solver
from freecad.Shelving.core.axis_solver import ConstraintId as EngineId
from freecad.Shelving.core.axis_solver import (
    LowerBound,
    PositionId,
    Relation,
    Target,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Board,
    Constraint,
    ConstraintId,
    Division,
    EvenSpacing,
    FixedSide,
    Item,
    Lock,
    Region,
    Unit,
    constraint_regions,
    spacing_group,
)

EPS_MM: float = 1e-6

# A solved size within this of the size stored before the edit keeps the
# stored value, so the rounding a solve leaves on an untouched region never
# reaches the document.
_SETTLE_MM: float = 1e-7

SolveErrorReason = Literal["misfit", "pinned_mismatch", "conflict"]


class LayoutSolveError(Exception):
    """A layout that cannot be satisfied.

    ``node_id`` is the offending ``Division`` id for a ``"misfit"`` whose
    sizes do not add up to its span, and the item's id for one with a size
    that is not positive; the pinned board's id for ``"pinned_mismatch"``;
    and for ``"conflict"`` the first of ``region_ids``, else the region of
    the first lock named, else the root's id. ``region_ids``,
    ``constraint_ids`` and ``lock_ids`` are set only for ``"conflict"``: the
    regions whose minimum widths the engine named, in tree order, the
    constraints it named, locks included, in the unit's order, and which of
    those are locks. ``detail`` carries the numbers that explain the
    failure.
    """

    def __init__(
        self,
        node_id: str,
        reason: SolveErrorReason,
        detail: Mapping[str, float],
        region_ids: Sequence[str] = (),
        constraint_ids: Sequence[ConstraintId] = (),
        lock_ids: Sequence[ConstraintId] = (),
    ) -> None:
        super().__init__(
            f"layout solve failed at {node_id!r}: {reason} ({dict(detail)})"
        )
        self.node_id = node_id
        self.reason = reason
        self.detail = detail
        self.region_ids: tuple[str, ...] = tuple(region_ids)
        self.constraint_ids: tuple[ConstraintId, ...] = tuple(constraint_ids)
        self.lock_ids: tuple[ConstraintId, ...] = tuple(lock_ids)


def _replace_component_mm(v: Vec3, axis_index: int, value_mm: float) -> Vec3:
    components = [v.x_mm, v.y_mm, v.z_mm]
    components[axis_index] = value_mm
    return Vec3(*components)


def board_extent_mm(board: Board) -> float:
    """``board``'s size along its run: its ``extent_mm`` when set, else its
    thickness."""
    return board.thickness_mm if board.extent_mm is None else board.extent_mm


def _item_size_mm(item: Item) -> float:
    return board_extent_mm(item) if isinstance(item, Board) else item.size_mm


def _check_pinned(board: Board, size: Vec3) -> None:
    """Raise a ``"pinned_mismatch"`` :class:`LayoutSolveError` when the
    extent ``size`` laid out for ``board`` differs from its
    ``pinned_size_mm`` by more than :data:`EPS_MM` on any axis."""
    pinned = board.pinned_size_mm
    if pinned is None:
        return
    if (
        abs(size.x_mm - pinned.x_mm) > EPS_MM
        or abs(size.y_mm - pinned.y_mm) > EPS_MM
        or abs(size.z_mm - pinned.z_mm) > EPS_MM
    ):
        raise LayoutSolveError(
            board.id,
            "pinned_mismatch",
            {
                "derived_x_mm": size.x_mm,
                "derived_y_mm": size.y_mm,
                "derived_z_mm": size.z_mm,
                "pinned_x_mm": pinned.x_mm,
                "pinned_y_mm": pinned.y_mm,
                "pinned_z_mm": pinned.z_mm,
            },
        )


def _lay_out(region: Region, space: Space, out: dict[str, Space]) -> None:
    out[region.id] = space
    if not isinstance(region, Division):
        return
    axis_index = region.axis.component_index
    start_mm = space.origin_mm(axis_index)
    cursor_mm = start_mm
    for item in region.items:
        size_mm = _item_size_mm(item)
        if size_mm <= EPS_MM:
            raise LayoutSolveError(item.id, "misfit", {"size_mm": size_mm})
        child_space = Space(
            origin=_replace_component_mm(space.origin, axis_index, cursor_mm),
            size=_replace_component_mm(space.size, axis_index, size_mm),
        )
        cursor_mm += size_mm
        if isinstance(item, Board):
            _check_pinned(item, child_space.size)
            out[item.id] = child_space
        else:
            _lay_out(item, child_space, out)
    span_mm = space.extent_mm(axis_index)
    if abs(cursor_mm - start_mm - span_mm) > EPS_MM:
        raise LayoutSolveError(
            region.id,
            "misfit",
            {"span_mm": span_mm, "sizes_total_mm": cursor_mm - start_mm},
        )


def solve(unit: Unit) -> dict[str, Space]:
    """One :class:`~freecad.Shelving.core.geometry.Space` per region and board
    id, laid out from the stored sizes.

    The root is placed at ``unit.position_mm`` with extent ``unit.size_mm``,
    so every space is in the frame the unit's boards are written in. Raises
    a ``"misfit"`` :class:`LayoutSolveError` when a run's sizes do not add up
    to its span or one is not positive, and a ``"pinned_mismatch"`` one when
    a pinned board would change size.
    """
    out: dict[str, Space] = {}
    _lay_out(unit.root, Space(origin=unit.position_mm, size=unit.size_mm), out)
    return out


@dataclasses.dataclass(frozen=True)
class _Edge:
    """A face along the system's axis: a position plus a fixed offset."""

    position: PositionId
    offset_mm: float


_OUTER_MIN = PositionId("outer:min")
_OUTER_MAX = PositionId("outer:max")
_FIXED_ID = EngineId("outer:fixed")
_SIZE_ID = EngineId("outer:size")
_HELD_MAX_ID = EngineId("outer:held")
_SIZE_EXPRESSION: Mapping[PositionId, float] = {_OUTER_MAX: 1.0, _OUTER_MIN: -1.0}


def _span(low: _Edge, high: _Edge) -> tuple[Mapping[PositionId, float], float]:
    """``high - low`` as relation coefficients and the offset to subtract
    from the constant."""
    if low.position == high.position:
        return {}, high.offset_mm - low.offset_mm
    return {high.position: 1.0, low.position: -1.0}, high.offset_mm - low.offset_mm


@dataclasses.dataclass
class _System:
    """One axis's positions and structural relations, built from a unit."""

    axis: Axis
    current_mm: dict[PositionId, float]
    board_low: dict[str, _Edge]
    # Every region whose parent runs along the axis, in tree order.
    regions: list[Region]
    region_edges: dict[str, tuple[_Edge, _Edge]]
    # The high face of the board just after each region followed by one: the
    # far end of a Basis.WITH_NEXT size.
    next_board_high: dict[str, _Edge]
    structural: list[Relation]
    # Each active constraint whose regions all lie on runs along the axis,
    # with its relations, in the unit's order.
    constraint_relations: list[tuple[ConstraintId, list[Relation]]]
    # The region each lock in constraint_relations holds.
    lock_regions: dict[ConstraintId, str]

    def value_mm(self, edge: _Edge, positions_mm: Mapping[PositionId, float]) -> float:
        return positions_mm[edge.position] + edge.offset_mm

    def min_id(self, region_id: str) -> EngineId:
        return EngineId(f"{region_id}:min")

    def rule_relations(self, without: Collection[ConstraintId] = ()) -> list[Relation]:
        """Every constraint's relations but those of ``without``: the locks'
        first, then the others', each in the unit's order."""
        locks = [m for m in self.constraint_relations if m[0] in self.lock_regions]
        others = [m for m in self.constraint_relations if m[0] not in self.lock_regions]
        return [
            relation
            for constraint_id, relations in (*locks, *others)
            if constraint_id not in without
            for relation in relations
        ]

    def relations_of(self, constraint_ids: Collection[ConstraintId]) -> list[Relation]:
        """The relations of the constraints ``constraint_ids`` names, in the
        unit's order."""
        return [
            relation
            for constraint_id, relations in self.constraint_relations
            if constraint_id in constraint_ids
            for relation in relations
        ]

    def region_ids(self, engine_ids: Collection[EngineId]) -> list[str]:
        """The regions whose minimum width ``engine_ids`` names, in tree
        order."""
        return [
            region.id for region in self.regions if self.min_id(region.id) in engine_ids
        ]

    def constraint_ids(self, engine_ids: Collection[EngineId]) -> list[ConstraintId]:
        """The constraints any of whose relations ``engine_ids`` names, in
        the unit's order."""
        return [
            constraint_id
            for constraint_id, relations in self.constraint_relations
            if any(relation.id in engine_ids for relation in relations)
        ]

    def measured(
        self, region_id: str, basis: Basis
    ) -> tuple[Mapping[PositionId, float], float]:
        """The region's size in ``basis`` as :func:`_span` gives a span."""
        low, high = self.region_edges[region_id]
        if basis is Basis.WITH_NEXT and region_id in self.next_board_high:
            high = self.next_board_high[region_id]
        return _span(low, high)


def _equal_relation(
    relation_id: EngineId,
    first: tuple[Mapping[PositionId, float], float],
    second: tuple[Mapping[PositionId, float], float],
) -> Relation:
    """``first == second`` for two spans as :func:`_span` gives them."""
    coefficients: dict[PositionId, float] = dict(first[0])
    for position, value in second[0].items():
        coefficients[position] = coefficients.get(position, 0.0) - value
    return Relation(relation_id, coefficients, second[1] - first[1])


def _add_constraints(unit: Unit, system: _System) -> None:
    sizes_mm = {region.id: region.size_mm for region in system.regions}
    for constraint in unit.constraints:
        if not constraint.active:
            continue
        if isinstance(constraint, Lock):
            region_id = constraint.region_id
            if region_id not in system.region_edges:
                continue
            coefficients, offset_mm = _span(*system.region_edges[region_id])
            system.constraint_relations.append(
                (
                    constraint.id,
                    [
                        Relation(
                            EngineId(f"{constraint.id}:lock"),
                            coefficients,
                            sizes_mm[region_id] - offset_mm,
                        )
                    ],
                )
            )
            system.lock_regions[constraint.id] = region_id
            continue
        region_ids = constraint_regions(unit, constraint)
        if len(region_ids) < 2 or any(
            region_id not in system.region_edges for region_id in region_ids
        ):
            continue
        spans = [
            system.measured(region_id, constraint.basis) for region_id in region_ids
        ]
        system.constraint_relations.append(
            (
                constraint.id,
                [
                    _equal_relation(
                        EngineId(f"{constraint.id}:{index}"),
                        spans[index],
                        spans[index + 1],
                    )
                    for index in range(len(spans) - 1)
                ],
            )
        )


def _build(unit: Unit, spaces: Mapping[str, Space], axis: Axis) -> _System:
    """The system for ``axis`` with ``unit``'s boards, locks, active
    constraints and stored sizes, at the current positions ``spaces`` lays
    out."""
    axis_index = axis.component_index
    root_space = spaces[unit.root.id]
    system = _System(
        axis=axis,
        current_mm={
            _OUTER_MIN: root_space.origin_mm(axis_index),
            _OUTER_MAX: root_space.origin_mm(axis_index)
            + root_space.extent_mm(axis_index),
        },
        board_low={},
        regions=[],
        region_edges={},
        next_board_high={},
        structural=[],
        constraint_relations=[],
        lock_regions={},
    )

    def walk(region: Region, low: _Edge, high: _Edge) -> None:
        if not isinstance(region, Division):
            return
        if region.axis is not axis:
            for item in region.items:
                if not isinstance(item, Board):
                    walk(item, low, high)
            return
        cursor = low
        last = len(region.items) - 1
        for index, item in enumerate(region.items):
            if isinstance(item, Board):
                system.board_low[item.id] = cursor
                cursor = _Edge(
                    cursor.position, cursor.offset_mm + board_extent_mm(item)
                )
                if index == last:
                    coefficients, offset_mm = _span(cursor, high)
                    system.structural.append(
                        Relation(EngineId(f"{item.id}:fit"), coefficients, -offset_mm)
                    )
                continue
            if index == last:
                item_high = high
            else:
                after = region.items[index + 1]
                if isinstance(after, Board):
                    position = PositionId(after.id)
                    system.current_mm[position] = spaces[after.id].origin_mm(axis_index)
                    system.next_board_high[item.id] = _Edge(
                        position, board_extent_mm(after)
                    )
                else:
                    position = PositionId(f"{item.id}:end")
                    space = spaces[item.id]
                    system.current_mm[position] = space.origin_mm(
                        axis_index
                    ) + space.extent_mm(axis_index)
                item_high = _Edge(position, 0.0)
            system.regions.append(item)
            system.region_edges[item.id] = (cursor, item_high)
            walk(item, cursor, item_high)
            cursor = item_high

    walk(unit.root, _Edge(_OUTER_MIN, 0.0), _Edge(_OUTER_MAX, 0.0))
    _add_constraints(unit, system)
    return system


def _fixed_relation(unit: Unit, system: _System) -> Relation:
    """The unit's fixed point along the system's axis, where it is now."""
    low_mm = system.current_mm[_OUTER_MIN]
    high_mm = system.current_mm[_OUTER_MAX]
    match unit.fixed_point.side(system.axis):
        case "min":
            return Relation(_FIXED_ID, {_OUTER_MIN: 1.0}, low_mm)
        case "center":
            return Relation(
                _FIXED_ID, {_OUTER_MIN: 0.5, _OUTER_MAX: 0.5}, (low_mm + high_mm) / 2
            )
        case "max":
            return Relation(_FIXED_ID, {_OUTER_MAX: 1.0}, high_mm)


# How far along an axis, as a fraction of the unit's size there, each fixed
# side lies from the unit's minimum corner.
FIXED_FRACTION: Mapping[FixedSide, float] = {"min": 0.0, "center": 0.5, "max": 1.0}


def _settled(new_mm: float, old_mm: float) -> float:
    return old_mm if abs(new_mm - old_mm) <= _SETTLE_MM else new_mm


def _with_sizes(region: Region, sizes_mm: Mapping[str, float]) -> Region:
    """``region`` with each region ``sizes_mm`` names at that size, copying
    only the paths down to them."""
    new_region = region
    if region.id in sizes_mm:
        size_mm = _settled(sizes_mm[region.id], region.size_mm)
        if size_mm != region.size_mm:
            new_region = dataclasses.replace(region, size_mm=size_mm)
    if not isinstance(new_region, Division):
        return new_region
    new_items: list[Item] = []
    changed = False
    for item in new_region.items:
        new_item = item if isinstance(item, Board) else _with_sizes(item, sizes_mm)
        changed = changed or new_item is not item
        new_items.append(new_item)
    if changed:
        return dataclasses.replace(new_region, items=new_items)
    return new_region


def solve_axis(
    unit: Unit,
    spaces: Mapping[str, Space],
    axis: Axis,
    minimum_mm: float,
    *,
    size_mm: float | None = None,
    target: tuple[str, float] | None = None,
) -> Unit:
    """``unit`` with its sizes along ``axis`` solved by moving the boards as
    little as possible from where ``spaces`` places them.

    ``unit`` carries the constraints after an edit: its boards' extents, its
    locks at their stored sizes, its active constraints, and its fixed
    point; ``spaces`` is the layout before it, the reference the motion is
    measured from, and must hold every node of ``unit``. The fixed point
    stays where ``spaces`` has it, and the unit's size along ``axis``
    becomes ``size_mm``, or stays as it is when that is ``None``. When the
    locks and constraints determine that size, as :func:`size_fixed_by`
    reports, it takes the size they give instead, and a ``size_mm`` that
    differs from it is a conflict. With ``target``, the board it names is
    pulled so its low face reaches the given unit-frame coordinate wherever
    the constraints allow. Every region in a run along ``axis`` keeps at
    least ``minimum_mm``, or its current size when that is smaller. Only
    sizes along ``axis`` and the unit's size and position on it change.

    Raises a ``"conflict"`` :class:`LayoutSolveError` when no layout meets
    the constraints, naming the regions whose minimum widths and the
    constraints, locks included, the engine found in conflict. One for a
    ``size_mm`` the locks rule out names the locks and constraints that
    determine the size, and its ``detail`` carries that size as
    ``"fixed_size_mm"``.
    """
    system = _build(unit, spaces, axis)
    axis_index = axis.component_index
    current_size_mm = system.current_mm[_OUTER_MAX] - system.current_mm[_OUTER_MIN]
    relations = [
        *system.structural,
        _fixed_relation(unit, system),
        *system.rule_relations(),
    ]
    reference = _reference(unit, system)
    if reference is None:
        wanted_size_mm = current_size_mm if size_mm is None else size_mm
        relations.append(Relation(_SIZE_ID, _SIZE_EXPRESSION, wanted_size_mm))
    else:
        constraint_ids, wanted_size_mm = reference
        if size_mm is not None and abs(size_mm - wanted_size_mm) > EPS_MM:
            raise _conflict(
                unit, system, {"fixed_size_mm": wanted_size_mm}, (), constraint_ids
            )
    bounds: list[LowerBound] = []
    for region in system.regions:
        low, high = system.region_edges[region.id]
        if low.position == high.position:
            continue
        now_mm = system.value_mm(high, system.current_mm) - system.value_mm(
            low, system.current_mm
        )
        bounds.append(
            LowerBound(
                system.min_id(region.id),
                low.position,
                high.position,
                min(minimum_mm, now_mm) - high.offset_mm + low.offset_mm,
            )
        )
    targets: list[Target] = []
    if target is not None:
        board_id, low_face_mm = target
        edge = system.board_low[board_id]
        targets.append(Target(edge.position, low_face_mm - edge.offset_mm))
    result = axis_solver.solve(system.current_mm, relations, bounds, targets)
    if isinstance(result, axis_solver.Conflict):
        raise _conflict(
            unit,
            system,
            {"minimum_mm": minimum_mm},
            system.region_ids(result.conflicting),
            system.constraint_ids(result.conflicting),
        )
    positions_mm = result.positions_mm
    sizes_mm = {
        region_id: system.value_mm(high, positions_mm)
        - system.value_mm(low, positions_mm)
        for region_id, (low, high) in system.region_edges.items()
    }
    new_size_mm = _settled(
        positions_mm[_OUTER_MAX] - positions_mm[_OUTER_MIN], wanted_size_mm
    )
    # From the fixed point rather than the solved face, so the fixed point
    # stays exactly where it was.
    old_low_mm = system.current_mm[_OUTER_MIN]
    old_size_mm = system.current_mm[_OUTER_MAX] - old_low_mm
    fraction = FIXED_FRACTION[unit.fixed_point.side(axis)]
    new_low_mm = old_low_mm + fraction * (old_size_mm - new_size_mm)
    return dataclasses.replace(
        unit,
        root=_with_sizes(unit.root, sizes_mm),
        size_mm=_replace_component_mm(unit.size_mm, axis_index, new_size_mm),
        position_mm=_replace_component_mm(unit.position_mm, axis_index, new_low_mm),
    )


def _conflict(
    unit: Unit,
    system: _System,
    detail: Mapping[str, float],
    region_ids: Sequence[str],
    constraint_ids: Sequence[ConstraintId],
) -> LayoutSolveError:
    """The ``"conflict"`` :class:`LayoutSolveError` naming ``region_ids``
    and ``constraint_ids``."""
    lock_ids = [c for c in constraint_ids if c in system.lock_regions]
    if region_ids:
        node_id = region_ids[0]
    elif lock_ids:
        node_id = system.lock_regions[lock_ids[0]]
    else:
        node_id = unit.root.id
    return LayoutSolveError(
        node_id, "conflict", detail, region_ids, constraint_ids, lock_ids
    )


def _reference(
    unit: Unit, system: _System
) -> tuple[tuple[ConstraintId, ...], float] | None:
    """The constraints, locks included, in the unit's order, that determine
    ``unit``'s size along the system's axis, and the size they give it;
    ``None`` when that size is free. The minimum widths play no part."""
    relations = [
        *system.structural,
        _fixed_relation(unit, system),
        *system.rule_relations(),
    ]
    result = axis_solver.solve(system.current_mm, relations, [])
    if isinstance(result, axis_solver.Conflict):
        # Locks that contradict each other leave no size to report; the
        # solve that follows names them.
        return None
    freedom = result.freedom(_SIZE_EXPRESSION)
    if not freedom.determined:
        return None
    positions_mm = result.positions_mm
    return (
        tuple(system.constraint_ids(freedom.fixed_by)),
        positions_mm[_OUTER_MAX] - positions_mm[_OUTER_MIN],
    )


def size_fixed_by(
    unit: Unit, spaces: Mapping[str, Space], axis: Axis
) -> tuple[ConstraintId, ...] | None:
    """The constraints, locks included, in the unit's order, that determine
    ``unit``'s size along ``axis``, making that size a reference; ``None``
    when the size is free.

    ``spaces`` is ``unit`` laid out. The boards' extents count alongside the
    locks and active constraints, and the openings' minimum widths do not.
    An empty tuple means the boards alone determine the size. When several
    sets determine it, the result is one of them.
    """
    reference = _reference(unit, _build(unit, spaces, axis))
    if reference is None:
        return None
    return reference[0]


def _duplicates(
    system: _System, relations: Sequence[Relation], own: Sequence[Relation]
) -> tuple[ConstraintId, ...] | None:
    """The constraints that imply any of ``own``, listed last after
    ``relations``; ``None`` when none of ``own`` is implied."""
    result = axis_solver.solve(system.current_mm, [*relations, *own], [])
    duplicates: set[EngineId] = set()
    for relation in own:
        duplicates |= result.redundant.get(relation.id, frozenset())
    if not duplicates:
        return None
    own_ids = {relation.id for relation in own}
    return tuple(system.constraint_ids(duplicates - own_ids))


def duplicated_constraint(
    unit: Unit, spaces: Mapping[str, Space], constraint_id: ConstraintId, axis: Axis
) -> tuple[ConstraintId, ...] | None:
    """The other constraints, locks included, in the unit's order, that
    with the boards already imply some relation of the constraint
    ``constraint_id``; ``None`` when none of it is redundant, or when it
    names no active constraint whose regions lie on runs along ``axis``.

    ``spaces`` is ``unit`` laid out, and the unit's size counts as free, so
    a lock that only makes the size a reference is not redundant. When
    several sets imply it, the result is one of them.
    """
    system = _build(unit, spaces, axis)
    own = system.relations_of((constraint_id,))
    if not own:
        return None
    relations = [
        *system.structural,
        _fixed_relation(unit, system),
        *system.rule_relations(without=(constraint_id,)),
    ]
    return _duplicates(system, relations, own)


def _at_current(system: _System, relation: Relation) -> Relation:
    """``relation`` with its constant replaced by its value at the system's
    current positions. Rank does not depend on the constants, and a layout
    an active constraint misses within the joint clearance would otherwise
    read as a conflict."""
    constant_mm = sum(
        coefficient * system.current_mm[position]
        for position, coefficient in relation.coefficients.items()
    )
    return dataclasses.replace(relation, constant_mm=constant_mm)


def redundant_rules(unit: Unit, spaces: Mapping[str, Space]) -> frozenset[ConstraintId]:
    """The active constraints of ``unit``, locks included, each of which,
    removed alone, leaves its axis's freedom unchanged: every member of an
    overlapping group, so a person can pick which to remove.

    ``spaces`` is ``unit`` laid out, and the unit's size counts as free, so
    a lock that only makes the size a reference is not redundant. A
    deactivated constraint is never in the set.
    """
    found: set[ConstraintId] = set()
    for axis in Axis:
        system = _build(unit, spaces, axis)
        base = [
            _at_current(system, relation)
            for relation in (*system.structural, _fixed_relation(unit, system))
        ]
        members = system.constraint_relations
        current = [
            (member_id, [_at_current(system, r) for r in relations])
            for member_id, relations in members
        ]
        for index, (member_id, own) in enumerate(current):
            others = [r for i, (_, rs) in enumerate(current) if i != index for r in rs]
            result = axis_solver.solve(system.current_mm, [*base, *others, *own], [])
            if all(relation.id in result.redundant for relation in own):
                found.add(member_id)
    return frozenset(found)


def fixing_locks(
    unit: Unit,
    spaces: Mapping[str, Space],
    board_id: str,
    axis: Axis,
    without: Collection[ConstraintId] = (),
) -> frozenset[ConstraintId] | None:
    """The active constraints, locks included, that fix the board
    ``board_id``'s low face along ``axis``, the axis of its run, with the
    unit's outer faces held and every region free to take any size; ``None``
    when that leaves the face free.

    ``spaces`` is ``unit`` laid out. A constraint ``without`` names is left
    out, as though it were deactivated. An empty set means the boards and
    outer faces alone fix the face, as for a carcass board, and is also the
    answer when the layout misses its own locks by more than the engine's
    tolerance, so a caller treats the board as immovable rather than
    failing. When several sets fix it, the result is one of them, preferring
    locks to other constraints.
    Never raises for a board of ``unit`` on a run along ``axis``.
    """
    system = _build(unit, spaces, axis)
    relations = [
        *system.structural,
        Relation(_FIXED_ID, {_OUTER_MIN: 1.0}, system.current_mm[_OUTER_MIN]),
        Relation(_HELD_MAX_ID, {_OUTER_MAX: 1.0}, system.current_mm[_OUTER_MAX]),
        *system.rule_relations(without),
    ]
    result = axis_solver.solve(system.current_mm, relations, [])
    if isinstance(result, axis_solver.Conflict):
        # The current layout meets every lock, so only rounding beyond the
        # engine's tolerance gets here.
        return frozenset()
    freedom = result.freedom({system.board_low[board_id].position: 1.0})
    if not freedom.determined:
        return None
    return frozenset(system.constraint_ids(freedom.fixed_by))


def _parent_of(region: Region, node_id: str) -> tuple[Division, int] | None:
    if not isinstance(region, Division):
        return None
    for index, item in enumerate(region.items):
        if item.id == node_id:
            return region, index
        if not isinstance(item, Board):
            found = _parent_of(item, node_id)
            if found is not None:
                return found
    return None


def constraint_axis(unit: Unit, constraint: Constraint) -> Axis | None:
    """The axis of the run holding ``constraint``'s first region: the axis
    a solve for it builds; ``None`` when it holds no region of ``unit``."""
    region_ids = constraint_regions(unit, constraint)
    if not region_ids:
        return None
    found = _parent_of(unit.root, region_ids[0])
    return None if found is None else found[0].axis


def measured_mm(
    unit: Unit, spaces: Mapping[str, Space], region_id: str, basis: Basis
) -> float | None:
    """The size of the region ``region_id`` along its run in ``basis``, read
    from ``spaces``, with the extent of the board just after it added for
    ``Basis.WITH_NEXT``; ``None`` when ``unit`` holds no such region in a
    run."""
    found = _parent_of(unit.root, region_id)
    if found is None or region_id not in spaces:
        return None
    run, index = found
    size_mm = spaces[region_id].extent_mm(run.axis.component_index)
    if basis is Basis.WITH_NEXT and index + 1 < len(run.items):
        after = run.items[index + 1]
        if isinstance(after, Board):
            size_mm += board_extent_mm(after)
    return size_mm


def constraint_spread_mm(
    unit: Unit, spaces: Mapping[str, Space], constraint: Constraint
) -> float | None:
    """How far ``constraint``'s regions are from meeting it: the largest of
    their sizes in its basis less the smallest, read from ``spaces``; 0 for
    a group of fewer than two, and ``None`` when a region it names is not
    in ``unit``."""
    if isinstance(constraint, EvenSpacing) and spacing_group(unit, constraint) is None:
        return None
    sizes_mm: list[float] = []
    for region_id in constraint_regions(unit, constraint):
        size_mm = measured_mm(unit, spaces, region_id, constraint.basis)
        if size_mm is None:
            return None
        sizes_mm.append(size_mm)
    if len(sizes_mm) < 2:
        return 0.0
    return max(sizes_mm) - min(sizes_mm)


def describe_solve_error(err: LayoutSolveError) -> str:
    """``err`` as one or two sentences for a person editing the layout.

    Names no node id, since region ids are opaque UUIDs; the editor shows
    which region the failure is about by other means. Lengths are rounded
    to 0.1 mm.
    """
    detail = err.detail
    # The constraints the error names other than locks; the wording speaks
    # of constraints only when there is one.
    others = set(err.constraint_ids) - set(err.lock_ids)
    match err.reason:
        case "misfit":
            return (
                "The stored sizes of a row or column do not add up to the space "
                "it fills."
            )
        case "pinned_mismatch":
            return (
                "A board this workbench cannot reshape would have to change size "
                "to fit."
            )
        case "conflict" if "fixed_size_mm" in detail and others:
            return (
                "Locked openings and constraints fix this size of the unit at "
                f"{detail['fixed_size_mm']:.1f} mm: unlock or remove one of "
                "them to change it."
            )
        case "conflict" if "fixed_size_mm" in detail:
            return (
                "Locked openings fix this size of the unit at "
                f"{detail['fixed_size_mm']:.1f} mm: unlock one of them to change it."
            )
        case "conflict" if "minimum_mm" in detail and others:
            return (
                "There is no room for that: the constraints, the locked "
                "openings, and openings already at their "
                f"{detail['minimum_mm']:.1f} mm minimum hold the boards where "
                "they are."
            )
        case "conflict" if "minimum_mm" in detail:
            return (
                "There is no room for that: the locked openings, and openings "
                f"already at their {detail['minimum_mm']:.1f} mm minimum, hold "
                "the boards where they are."
            )
        case "conflict" if others:
            return "The locked openings and constraints cannot all hold."
        case "conflict":
            return "The locked openings cannot all keep their sizes."
