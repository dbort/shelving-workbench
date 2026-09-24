"""Spacing solver: a region tree plus a unit size to 3D spaces.

``solve`` walks the tree from the unit's outer
:class:`~freecad.Shelving.core.geometry.Space` placing one space per region
and board id. Slack along a division's axis is distributed by
:func:`distribute`, a pure function that knows nothing about
regions, boards, or axes: a board contributes ``Fixed(thickness_mm)``, or its
own ``rule`` when that is set, and a region contributes its own rule, so the
arithmetic never needs to know which is which. A layout that cannot be
satisfied raises :class:`LayoutSolveError` with a machine-readable ``reason``
and the id of the offending node.

All lengths are float millimetres. There is no rounding or quantisation;
:data:`EPS_MM` is the tolerance for the "does it fit" and "is it positive"
comparisons only.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from freecad.Shelving.core.geometry import AxisIndex, Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Board,
    Division,
    Fill,
    Fixed,
    Item,
    Region,
    SizeRule,
    Unit,
    Weighted,
)
from freecad.Shelving.core.materials import Catalog

EPS_MM: float = 1e-6

SolveErrorReason = Literal[
    "overflow",
    "no_slack_absorber",
    "nonpositive_opening",
    "unresolvable_basis",
    "pinned_mismatch",
]


class LayoutSolveError(Exception):
    """A layout that cannot be satisfied.

    ``node_id`` is the offending ``Division`` id for ``"overflow"`` and
    ``"no_slack_absorber"``, the region whose ``Basis.WITH_NEXT`` rule could
    not be resolved for ``"unresolvable_basis"``, the child item's id for
    ``"nonpositive_opening"``, and the pinned board's id for
    ``"pinned_mismatch"``. ``detail`` carries the numbers that explain the
    failure.
    """

    def __init__(
        self, node_id: str, reason: SolveErrorReason, detail: Mapping[str, float]
    ) -> None:
        super().__init__(
            f"layout solve failed at {node_id!r}: {reason} ({dict(detail)})"
        )
        self.node_id = node_id
        self.reason = reason
        self.detail = detail


def _driven_weight(rule: Weighted | Fill) -> float:
    """Weight a driven rule contributes to slack sharing; ``Fill`` counts as 1."""
    return rule.weight if isinstance(rule, Weighted) else 1.0


def distribute(
    axis_span_mm: float,
    rules: Sequence[SizeRule],
    divider_thicknesses_mm: Sequence[float],
    *,
    node_id: str,
) -> list[float]:
    """One opening size per rule, sharing slack by fixed / weighted / fill.

    ``Fixed`` openings take their stated size; ``Weighted`` and ``Fill`` split
    what remains of ``axis_span_mm`` after divider thicknesses and fixed sizes,
    in proportion to weight (``Fill`` is weight 1). Raises
    :class:`LayoutSolveError` with ``reason="overflow"`` when the dividers alone
    exceed the span or the fixed sizes leave negative slack, and
    ``reason="no_slack_absorber"`` when there is leftover positive slack but no
    driven rule to absorb it. Overflow is checked first, so an all-``Fixed``
    run whose sizes exceed the span reports ``"overflow"``, not
    ``"no_slack_absorber"``. It does not check for nonpositive openings; the
    caller does that against the offending item's id. Every ``Fixed`` rule
    here must already be resolved to ``Basis.CLEAR``; this function has no
    basis case of its own.
    """
    dividers_total_mm = sum(divider_thicknesses_mm)
    if dividers_total_mm > axis_span_mm + EPS_MM:
        raise LayoutSolveError(
            node_id,
            "overflow",
            {
                "axis_span_mm": axis_span_mm,
                "dividers_total_mm": dividers_total_mm,
            },
        )
    available_mm = axis_span_mm - dividers_total_mm
    fixed_sum_mm = sum(rule.size_mm for rule in rules if isinstance(rule, Fixed))
    slack_mm = available_mm - fixed_sum_mm
    driven = [rule for rule in rules if isinstance(rule, (Weighted, Fill))]
    # Negative slack is an overflow regardless of whether a driven rule exists,
    # so this precedes the no_slack_absorber check: an all-Fixed run that
    # overruns the span reports the more informative "overflow" reason.
    if slack_mm < -EPS_MM:
        raise LayoutSolveError(
            node_id,
            "overflow",
            {"slack_mm": slack_mm, "available_mm": available_mm},
        )
    # no_slack_absorber is the underfill case only: leftover positive slack and
    # no Weighted/Fill rule to take it up.
    if not driven and slack_mm > EPS_MM:
        raise LayoutSolveError(
            node_id,
            "no_slack_absorber",
            {"slack_mm": slack_mm, "available_mm": available_mm},
        )
    total_weight = sum(_driven_weight(rule) for rule in driven)
    sizes: list[float] = []
    for rule in rules:
        match rule:
            case Fixed(size_mm=size_mm):
                sizes.append(size_mm)
            case Weighted() | Fill():
                sizes.append(_driven_weight(rule) / total_weight * slack_mm)
    return sizes


def _axis_index(axis: Axis) -> AxisIndex:
    match axis:
        case Axis.X:
            return 0
        case Axis.Y:
            return 1
        case Axis.Z:
            return 2


def _component_mm(v: Vec3, axis_index: AxisIndex) -> float:
    return (v.x_mm, v.y_mm, v.z_mm)[axis_index]


def _replace_component_mm(v: Vec3, axis_index: AxisIndex, value_mm: float) -> Vec3:
    components = [v.x_mm, v.y_mm, v.z_mm]
    components[axis_index] = value_mm
    return Vec3(*components)


def _thickness_mm(board: Board, unit: Unit, catalog: Catalog) -> float:
    return catalog[board.material or unit.default_material].thickness_mm


def _resolve_with_next(
    rule: Fixed,
    index: int,
    items: Sequence[Item],
    unit: Unit,
    catalog: Catalog,
    region_id: str,
) -> Fixed:
    """Resolve a ``Basis.WITH_NEXT`` rule to an equivalent ``Basis.CLEAR`` one.

    Subtracts the resolved thickness of the item immediately after ``index``
    in ``items``. Raises :class:`LayoutSolveError` with reason
    ``"unresolvable_basis"`` when there is no next item or it is not a
    ``Board``, and with reason ``"nonpositive_opening"`` when the next item
    is at least as thick as the quoted spacing.
    """
    if index + 1 >= len(items) or not isinstance(items[index + 1], Board):
        raise LayoutSolveError(region_id, "unresolvable_basis", {})
    next_board = items[index + 1]
    assert isinstance(next_board, Board)
    next_thickness_mm = _thickness_mm(next_board, unit, catalog)
    resolved_size_mm = rule.size_mm - next_thickness_mm
    if resolved_size_mm <= 0:
        # Fixed.__post_init__ would reject this with a bare ValueError, which
        # breaks the LayoutSolveError contract solve's callers are told to
        # catch; raise the uniform error before constructing it.
        raise LayoutSolveError(
            region_id, "nonpositive_opening", {"size_mm": resolved_size_mm}
        )
    return Fixed(size_mm=resolved_size_mm)


def _rule_for_item(
    item: Item,
    index: int,
    items: Sequence[Item],
    unit: Unit,
    catalog: Catalog,
) -> SizeRule:
    """The rule ``distribute`` should use for ``item``.

    A board's size along the axis is its thickness, a ``Fixed`` rule, so
    boards and regions go through one distribution, unless the board's own
    ``rule`` is set, in which case that rule is used directly instead. A
    board's own rule is never routed through ``_resolve_with_next``: that
    resolution is for a region's ``Basis.WITH_NEXT`` quoting a spacing
    relative to the next item, a distinct concept a board's own size has no
    use for. A region's own ``Basis.WITH_NEXT`` rule is resolved to
    ``Basis.CLEAR`` first.
    """
    if isinstance(item, Board):
        if item.rule is not None:
            return item.rule
        return Fixed(size_mm=_thickness_mm(item, unit, catalog))
    rule = item.rule
    if isinstance(rule, Fixed) and rule.basis is Basis.WITH_NEXT:
        return _resolve_with_next(rule, index, items, unit, catalog, item.id)
    return rule


def _check_pinned(board: Board, size: Vec3) -> None:
    """Verify a pinned board's derived ``size`` against its ``pinned_size_mm``.

    The solver never lets a pinned size drive the layout; it derives the
    board's extent the same way as any other item, then checks it here.
    Raises :class:`LayoutSolveError` with reason ``"pinned_mismatch"`` when
    any axis differs by more than :data:`EPS_MM`.
    """
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


def _place(
    region: Region,
    space: Space,
    unit: Unit,
    catalog: Catalog,
    out: dict[str, Space],
) -> None:
    """Record one :class:`~freecad.Shelving.core.geometry.Space` per node id in the
    subtree rooted at ``region``.

    A ``Division`` shares ``space``'s extent along its own axis among its
    items and passes the other two axes through unchanged. Items are placed
    from the low edge in list order. ``out`` is mutated in place. A resolved
    opening ``<= EPS_MM`` raises :class:`LayoutSolveError` against that
    item's id.
    """
    out[region.id] = space
    if not isinstance(region, Division):
        return
    axis_index = _axis_index(region.axis)
    axis_span_mm = space.extent_mm(axis_index)
    rules: list[SizeRule] = [
        _rule_for_item(item, index, region.items, unit, catalog)
        for index, item in enumerate(region.items)
    ]
    sizes_mm = distribute(axis_span_mm, rules, [], node_id=region.id)
    cursor_mm = _component_mm(space.origin, axis_index)
    for item, size_mm in zip(region.items, sizes_mm, strict=True):
        if size_mm <= EPS_MM:
            raise LayoutSolveError(
                item.id,
                "nonpositive_opening",
                {"size_mm": size_mm},
            )
        child_space = Space(
            origin=_replace_component_mm(space.origin, axis_index, cursor_mm),
            size=_replace_component_mm(space.size, axis_index, size_mm),
        )
        cursor_mm += size_mm
        if isinstance(item, Board):
            _check_pinned(item, child_space.size)
            out[item.id] = child_space
        else:
            _place(item, child_space, unit, catalog, out)


def solve(unit: Unit, catalog: Catalog) -> dict[str, Space]:
    """One :class:`~freecad.Shelving.core.geometry.Space` per region and board id.

    The root is placed at the unit's local-frame origin with extent
    ``unit.size_mm``. A ``default_material`` or ``Board.material`` id absent
    from ``catalog`` raises ``KeyError`` from :meth:`Catalog.__getitem__`, not
    :class:`LayoutSolveError`.
    """
    out: dict[str, Space] = {}
    root_space = Space(origin=Vec3(0.0, 0.0, 0.0), size=unit.size_mm)
    _place(unit.root, root_space, unit, catalog, out)
    return out
