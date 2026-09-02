"""Spacing solver: a ``Carcass`` split-tree plus outer dimensions to 2D rects.

``solve`` insets the carcass by its default material's panel thickness, then
walks the tree placing one :class:`Rect` per ``Leaf``, ``Split``, and
``Divider`` id. Slack along a split's axis is distributed by
:func:`distribute`, a pure function that knows nothing about rectangles or the
tree. A layout that cannot be satisfied
raises :class:`LayoutSolveError` with a machine-readable ``reason`` and the id of
the offending node.

All lengths are float millimetres. There is no rounding or quantisation;
:data:`EPS_MM` is the tolerance for the "does it fit" and "is it positive"
comparisons only.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from shelving_core.layout import (
    Bay,
    Carcass,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
    SplitRule,
    Weighted,
)
from shelving_core.materials import Catalog

EPS_MM: float = 1e-6

SolveErrorReason = Literal["overflow", "no_slack_absorber", "nonpositive_opening"]


class LayoutSolveError(Exception):
    """A layout that cannot be satisfied.

    ``node_id`` is the offending ``Split`` id for ``"overflow"`` and
    ``"no_slack_absorber"`` (or the root bay id when the carcass inset itself
    collapses), and the child bay id for ``"nonpositive_opening"``. ``detail``
    carries the numbers that explain the failure.
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


@dataclass(frozen=True)
class Rect:
    """An axis-aligned rectangle in the front elevation (X right, Z up)."""

    x_mm: float
    z_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class SolvedLayout:
    """Read-only map from node id to its solved :class:`Rect`."""

    rect_by_id: Mapping[str, Rect]

    def __getitem__(self, node_id: str) -> Rect:
        return self.rect_by_id[node_id]


def _driven_weight(rule: Weighted | Fill) -> float:
    """Weight a driven rule contributes to slack sharing; ``Fill`` counts as 1."""
    return rule.weight if isinstance(rule, Weighted) else 1.0


def distribute(
    axis_span_mm: float,
    rules: Sequence[SplitRule],
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
    split whose sizes exceed the span reports ``"overflow"``, not
    ``"no_slack_absorber"``. It does not check for nonpositive openings;
    ``_place`` does that against the child bay id.
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
    # so this precedes the no_slack_absorber check: an all-Fixed split that
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


def _interior_rect(carcass: Carcass, default_thickness_mm: float) -> Rect:
    """Carcass exterior inset by ``default_thickness_mm`` on all four sides."""
    thickness_mm = default_thickness_mm
    width_mm = carcass.width_mm - 2 * thickness_mm
    height_mm = carcass.height_mm - 2 * thickness_mm
    if width_mm <= EPS_MM or height_mm <= EPS_MM:
        raise LayoutSolveError(
            carcass.root.id,
            "overflow",
            {
                "width_mm": width_mm,
                "height_mm": height_mm,
                "thickness_mm": thickness_mm,
            },
        )
    return Rect(
        x_mm=thickness_mm,
        z_mm=thickness_mm,
        width_mm=width_mm,
        height_mm=height_mm,
    )


def _effective_thicknesses_mm(
    split: Split, catalog: Catalog, default_thickness_mm: float
) -> list[float]:
    """Resolved thickness per divider: its material's, or the carcass default.

    A ``Divider`` whose ``material`` is set but absent from ``catalog`` raises
    ``KeyError`` from :meth:`Catalog.__getitem__`.
    """
    return [
        default_thickness_mm
        if divider.material is None
        else catalog[divider.material].thickness_mm
        for divider in split.dividers
    ]


def _place(
    bay: Bay,
    rect: Rect,
    out: dict[str, Rect],
    catalog: Catalog,
    default_thickness_mm: float,
) -> None:
    """Record one :class:`Rect` per node id in the subtree rooted at ``bay``.

    A ``HORIZONTAL`` split shares its ``rect``'s ``height_mm`` along Z; a
    ``VERTICAL`` split shares its ``width_mm`` along X. Children are laid from
    the low edge in list order, each filling the parent's cross axis; every
    divider fills the gap between two consecutive children. ``out`` is mutated
    in place. ``catalog`` and ``default_thickness_mm`` resolve each
    ``Divider``'s thickness (its own material, or the carcass default). A
    resolved opening ``<= EPS_MM`` raises :class:`LayoutSolveError` against that
    child bay's id.
    """
    match bay:
        case Leaf():
            out[bay.id] = rect
        case Split():
            out[bay.id] = rect
            thicknesses_mm = _effective_thicknesses_mm(
                bay, catalog, default_thickness_mm
            )
            horizontal = bay.orientation is Orientation.HORIZONTAL
            axis_span_mm = rect.height_mm if horizontal else rect.width_mm
            sizes_mm = distribute(
                axis_span_mm, bay.rules, thicknesses_mm, node_id=bay.id
            )
            for size_mm, child in zip(sizes_mm, bay.children, strict=True):
                if size_mm <= EPS_MM:
                    raise LayoutSolveError(
                        child.id,
                        "nonpositive_opening",
                        {"size_mm": size_mm},
                    )
            cursor_mm = rect.z_mm if horizontal else rect.x_mm
            for index, child in enumerate(bay.children):
                size_mm = sizes_mm[index]
                if horizontal:
                    child_rect = Rect(
                        x_mm=rect.x_mm,
                        z_mm=cursor_mm,
                        width_mm=rect.width_mm,
                        height_mm=size_mm,
                    )
                else:
                    child_rect = Rect(
                        x_mm=cursor_mm,
                        z_mm=rect.z_mm,
                        width_mm=size_mm,
                        height_mm=rect.height_mm,
                    )
                _place(child, child_rect, out, catalog, default_thickness_mm)
                cursor_mm += size_mm
                if index < len(thicknesses_mm):
                    thickness_mm = thicknesses_mm[index]
                    if horizontal:
                        divider_rect = Rect(
                            x_mm=rect.x_mm,
                            z_mm=cursor_mm,
                            width_mm=rect.width_mm,
                            height_mm=thickness_mm,
                        )
                    else:
                        divider_rect = Rect(
                            x_mm=cursor_mm,
                            z_mm=rect.z_mm,
                            width_mm=thickness_mm,
                            height_mm=rect.height_mm,
                        )
                    out[bay.dividers[index].id] = divider_rect
                    cursor_mm += thickness_mm


def solve(carcass: Carcass, catalog: Catalog) -> SolvedLayout:
    """Place every ``Leaf``, ``Split``, and ``Divider`` id in one :class:`Rect`.

    A ``default_material`` or ``Divider.material`` id absent from ``catalog``
    raises ``KeyError`` from :meth:`Catalog.__getitem__`, not
    :class:`LayoutSolveError`.
    """
    default_thickness_mm = catalog[carcass.default_material].thickness_mm
    interior_rect = _interior_rect(carcass, default_thickness_mm)
    out: dict[str, Rect] = {}
    _place(carcass.root, interior_rect, out, catalog, default_thickness_mm)
    return SolvedLayout(rect_by_id=out)
