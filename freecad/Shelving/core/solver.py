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
board's; the outer faces' never decides anything, since the fixed point and
the size, or the faces held for a drag, place them. Relations hold the boards
in their runs, the unit's fixed point, each lock, and the unit's size, in
that order: the engine reports the later member of a dependent group as
redundant, so the size drops out when locks already determine it and
conflicts when they contradict it.

All lengths are float millimeters. :data:`EPS_MM` is the tolerance for the
"does it fit" and "is it positive" comparisons only.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from freecad.Shelving.core import axis_solver
from freecad.Shelving.core.axis_solver import (
    ConstraintId,
    LowerBound,
    PositionId,
    Relation,
    Target,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Board,
    Division,
    FixedSide,
    Item,
    Region,
    Unit,
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
    and for ``"conflict"`` the first of ``region_ids``, or the root's id when
    that is empty. ``region_ids`` is set only for ``"conflict"``: the regions
    whose locks or minimum widths the engine named, in tree order. ``detail``
    carries the numbers that explain the failure.
    """

    def __init__(
        self,
        node_id: str,
        reason: SolveErrorReason,
        detail: Mapping[str, float],
        region_ids: Sequence[str] = (),
    ) -> None:
        super().__init__(
            f"layout solve failed at {node_id!r}: {reason} ({dict(detail)})"
        )
        self.node_id = node_id
        self.reason = reason
        self.detail = detail
        self.region_ids: tuple[str, ...] = tuple(region_ids)


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
_FIXED_ID = ConstraintId("outer:fixed")
_SIZE_ID = ConstraintId("outer:size")
_HELD_MAX_ID = ConstraintId("outer:held")


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
    structural: list[Relation]

    def value_mm(self, edge: _Edge, positions_mm: Mapping[PositionId, float]) -> float:
        return positions_mm[edge.position] + edge.offset_mm

    def lock_id(self, region_id: str) -> ConstraintId:
        return ConstraintId(f"{region_id}:lock")

    def min_id(self, region_id: str) -> ConstraintId:
        return ConstraintId(f"{region_id}:min")

    def lock_relations(self, without: Collection[str] = ()) -> list[Relation]:
        relations: list[Relation] = []
        for region in self.regions:
            if region.lock is None or region.id in without:
                continue
            coefficients, offset_mm = _span(*self.region_edges[region.id])
            relations.append(
                Relation(
                    self.lock_id(region.id), coefficients, region.size_mm - offset_mm
                )
            )
        return relations

    def region_ids(self, constraint_ids: Collection[ConstraintId]) -> list[str]:
        """The regions whose lock or minimum width ``constraint_ids`` names,
        in tree order."""
        return [
            region.id
            for region in self.regions
            if self.lock_id(region.id) in constraint_ids
            or self.min_id(region.id) in constraint_ids
        ]


def _build(unit: Unit, spaces: Mapping[str, Space], axis: Axis) -> _System:
    """The system for ``axis`` with ``unit``'s boards, locks and stored
    sizes, at the current positions ``spaces`` lays out."""
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
        structural=[],
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
                        Relation(
                            ConstraintId(f"{item.id}:fit"), coefficients, -offset_mm
                        )
                    )
                continue
            if index == last:
                item_high = high
            else:
                after = region.items[index + 1]
                if isinstance(after, Board):
                    position = PositionId(after.id)
                    system.current_mm[position] = spaces[after.id].origin_mm(axis_index)
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
    locks at their stored sizes, and its fixed point; ``spaces`` is the
    layout before it, the reference the motion is measured from, and must
    hold every node of ``unit``. The fixed point stays where ``spaces`` has
    it, and the unit's size along ``axis`` becomes ``size_mm``, or stays as
    it is when that is ``None``, unless the locks already determine it. With
    ``target``, the board it names is pulled so its low face reaches the
    given unit-frame coordinate wherever the constraints allow. Every region
    in a run along ``axis`` keeps at least ``minimum_mm``, or its current
    size when that is smaller. Only sizes along ``axis`` and the unit's size
    and position on it change.

    Raises a ``"conflict"`` :class:`LayoutSolveError` when no layout meets
    the constraints, naming the regions whose locks or minimum widths the
    engine found in conflict.
    """
    system = _build(unit, spaces, axis)
    axis_index = axis.component_index
    current_size_mm = system.current_mm[_OUTER_MAX] - system.current_mm[_OUTER_MIN]
    wanted_size_mm = current_size_mm if size_mm is None else size_mm
    relations = [
        *system.structural,
        _fixed_relation(unit, system),
        *system.lock_relations(),
        Relation(_SIZE_ID, {_OUTER_MAX: 1.0, _OUTER_MIN: -1.0}, wanted_size_mm),
    ]
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
        region_ids = system.region_ids(result.conflicting)
        raise LayoutSolveError(
            region_ids[0] if region_ids else unit.root.id,
            "conflict",
            {"minimum_mm": minimum_mm},
            region_ids,
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


def fixing_locks(
    unit: Unit,
    spaces: Mapping[str, Space],
    board_id: str,
    axis: Axis,
    without: Collection[str] = (),
) -> frozenset[str] | None:
    """The locked regions that fix the board ``board_id``'s low face along
    ``axis``, the axis of its run, with the unit's outer faces held and
    every region free to take any size; ``None`` when that leaves the face
    free.

    ``spaces`` is ``unit`` laid out. A lock on a region ``without`` names is
    left out, as though that region were unlocked. An empty set means the
    boards and outer faces alone fix the face, as for a carcass board, and
    is also the answer when the layout misses its own locks by more than the
    engine's tolerance, so a caller treats the board as immovable rather
    than failing. When several sets of locks fix it, the result is one of
    them. Never raises for a board of ``unit`` on a run along ``axis``.
    """
    system = _build(unit, spaces, axis)
    relations = [
        *system.structural,
        Relation(_FIXED_ID, {_OUTER_MIN: 1.0}, system.current_mm[_OUTER_MIN]),
        Relation(_HELD_MAX_ID, {_OUTER_MAX: 1.0}, system.current_mm[_OUTER_MAX]),
        *system.lock_relations(without),
    ]
    result = axis_solver.solve(system.current_mm, relations, [])
    if isinstance(result, axis_solver.Conflict):
        # The current layout meets every lock, so only rounding beyond the
        # engine's tolerance gets here.
        return frozenset()
    freedom = result.freedom({system.board_low[board_id].position: 1.0})
    if not freedom.determined:
        return None
    return frozenset(system.region_ids(freedom.fixed_by))


def describe_solve_error(err: LayoutSolveError) -> str:
    """``err`` as one or two sentences for a person editing the layout.

    Names no node id, since region ids are opaque UUIDs; the editor shows
    which region the failure is about by other means. Lengths are rounded
    to 0.1 mm.
    """
    detail = err.detail
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
        case "conflict" if "minimum_mm" in detail:
            return (
                "There is no room for that: the locked openings, and openings "
                f"already at their {detail['minimum_mm']:.1f} mm minimum, hold "
                "the boards where they are."
            )
        case "conflict":
            return "The locked openings cannot all keep their sizes."
