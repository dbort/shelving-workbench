"""Region-tree expansion: a solved ``Unit`` to a flat list of ``BoardSpec`` records.

A board's geometry is its parent division's solved
:class:`~shelving_core.geometry.Space` for that item id, cross-section axes
inset by the board's own ``Insets``. A ``Void`` contributes no board: it has
no id in the boards it would otherwise occupy, only in the solved space map.

All lengths are float millimetres in the unit's local frame: origin at the
front-bottom-left corner, ``+X`` right (width), ``+Y`` back (depth), ``+Z`` up
(height). A :attr:`BoardSpec.placement` is the board's minimum corner in that
frame, the point a caller would extrude the box from before translating.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .geometry import Space
from .geometry import Vec3 as Vec3  # re-exported for existing importers
from .layout import Axis, Board, Division, Insets, Region, Unit
from .materials import Catalog, MaterialId
from .solver import solve


@dataclass(frozen=True)
class BoardSpec:
    """One physical board: its node id, role, extent, minimum corner, material.

    ``size`` and ``placement`` are :class:`Vec3` in the unit's local frame.
    """

    node_id: str
    role: str
    size: Vec3
    placement: Vec3
    material: MaterialId


def total_volume_mm3(specs: Sequence[BoardSpec]) -> float:
    """Summed bounding-box volume over ``specs``, cubic millimetres."""
    return sum(s.size.x_mm * s.size.y_mm * s.size.z_mm for s in specs)


def expand(unit: Unit, catalog: Catalog) -> list[BoardSpec]:
    """One :class:`BoardSpec` per ``Board`` in the tree, in pre-order.

    A material id absent from ``catalog`` raises ``KeyError``; an
    unsatisfiable layout raises
    :class:`~shelving_core.solver.LayoutSolveError`.
    """
    spaces = solve(unit, catalog)
    specs: list[BoardSpec] = []
    _collect(unit.root, unit, spaces, specs)
    return specs


def _collect(
    region: Region,
    unit: Unit,
    spaces: Mapping[str, Space],
    out: list[BoardSpec],
) -> None:
    if not isinstance(region, Division):
        return
    for item in region.items:
        if isinstance(item, Board):
            board_space = _apply_insets(region.axis, spaces[item.id], item.insets)
            out.append(
                BoardSpec(
                    node_id=item.id,
                    role=item.role,
                    size=board_space.size,
                    placement=board_space.origin,
                    material=item.material or unit.default_material,
                )
            )
        else:
            _collect(item, unit, spaces, out)


def _apply_insets(axis: Axis, space: Space, insets: Insets) -> Space:
    """``space`` with ``insets`` applied to its two cross-section axes.

    The pair on ``axis`` itself is ignored: a board fills its division's axis
    with the solved extent (its own thickness), never an inset.
    """
    origin = space.origin
    size = space.size
    match axis:
        case Axis.X:
            origin = Vec3(
                origin.x_mm,
                origin.y_mm + insets.y_min_mm,
                origin.z_mm + insets.z_min_mm,
            )
            size = Vec3(
                size.x_mm,
                size.y_mm - insets.y_min_mm - insets.y_max_mm,
                size.z_mm - insets.z_min_mm - insets.z_max_mm,
            )
        case Axis.Y:
            origin = Vec3(
                origin.x_mm + insets.x_min_mm,
                origin.y_mm,
                origin.z_mm + insets.z_min_mm,
            )
            size = Vec3(
                size.x_mm - insets.x_min_mm - insets.x_max_mm,
                size.y_mm,
                size.z_mm - insets.z_min_mm - insets.z_max_mm,
            )
        case Axis.Z:
            origin = Vec3(
                origin.x_mm + insets.x_min_mm,
                origin.y_mm + insets.y_min_mm,
                origin.z_mm,
            )
            size = Vec3(
                size.x_mm - insets.x_min_mm - insets.x_max_mm,
                size.y_mm - insets.y_min_mm - insets.y_max_mm,
                size.z_mm,
            )
    return Space(origin=origin, size=size)
