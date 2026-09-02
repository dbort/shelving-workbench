"""Carcass expansion: a solved split-tree to a flat list of ``PlankSpec`` records.

Shell planks follow the default carcass lap rule: the top and bottom run
continuous the full width and depth, the two sides are captured between them.
Divider geometry is the solver's :class:`~shelving_core.solver.Rect` extruded
through the full depth, never recomputed here.

All lengths are float millimetres in the carcass local frame: origin at the
front-bottom-left corner, ``+X`` right (width), ``+Y`` back (depth), ``+Z`` up
(height). A :attr:`PlankSpec.placement` is the plank's minimum corner in that
frame, the point a caller would extrude the box from before translating.
"""

import enum
from collections.abc import Sequence
from dataclasses import dataclass

from shelving_core.layout import Bay, Carcass, Orientation, Split
from shelving_core.materials import Catalog, MaterialId
from shelving_core.solver import SolvedLayout, solve


@dataclass(frozen=True)
class Vec3:
    """A point or an extent in the carcass local frame, millimetres."""

    x_mm: float
    y_mm: float
    z_mm: float


class PlankRole(enum.StrEnum):
    """What a plank is within the carcass; the FreeCAD layer derives its ``Label``."""

    LEFT_SIDE = "left_side"
    RIGHT_SIDE = "right_side"
    TOP = "top"
    BOTTOM = "bottom"
    SHELF = "shelf"
    DIVIDER = "divider"


@dataclass(frozen=True)
class PlankSpec:
    """One physical plank: its node id, role, extent, minimum corner, material.

    ``node_id`` is the owning tree node's id for a divider, and the literal
    ``f"{carcass.id}:{role.value}"`` for a shell plank, which has no tree node
    of its own. ``size`` and ``placement`` are in the carcass local frame.
    """

    node_id: str
    role: PlankRole
    size: Vec3
    placement: Vec3
    material: MaterialId


def total_volume_mm3(specs: Sequence[PlankSpec]) -> float:
    """Summed bounding-box volume over ``specs``, cubic millimetres."""
    return sum(s.size.x_mm * s.size.y_mm * s.size.z_mm for s in specs)


def expand(carcass: Carcass, catalog: Catalog) -> list[PlankSpec]:
    """Every physical plank of ``carcass`` once the spacing solver has placed it.

    Calls :func:`~shelving_core.solver.solve` internally, then emits the shell
    in the order ``BOTTOM``, ``TOP``, ``LEFT_SIDE``, ``RIGHT_SIDE`` followed by
    one plank per ``Divider`` in pre-order (each child, then the divider that
    follows it, recursing into ``Split`` children). A material id absent from
    ``catalog`` raises ``KeyError`` and an unsatisfiable layout raises
    :class:`~shelving_core.solver.LayoutSolveError`; both propagate unchanged.
    ``Divider.lap`` is not read.
    """
    layout = solve(carcass, catalog)
    thickness_mm = catalog[carcass.default_material].thickness_mm
    width_mm = carcass.width_mm
    height_mm = carcass.height_mm
    depth_mm = carcass.depth_mm

    def shell(role: PlankRole, size: Vec3, placement: Vec3) -> PlankSpec:
        return PlankSpec(
            node_id=f"{carcass.id}:{role.value}",
            role=role,
            size=size,
            placement=placement,
            material=carcass.default_material,
        )

    specs: list[PlankSpec] = [
        shell(
            PlankRole.BOTTOM,
            Vec3(width_mm, depth_mm, thickness_mm),
            Vec3(0.0, 0.0, 0.0),
        ),
        shell(
            PlankRole.TOP,
            Vec3(width_mm, depth_mm, thickness_mm),
            Vec3(0.0, 0.0, height_mm - thickness_mm),
        ),
        shell(
            PlankRole.LEFT_SIDE,
            Vec3(thickness_mm, depth_mm, height_mm - 2.0 * thickness_mm),
            Vec3(0.0, 0.0, thickness_mm),
        ),
        shell(
            PlankRole.RIGHT_SIDE,
            Vec3(thickness_mm, depth_mm, height_mm - 2.0 * thickness_mm),
            Vec3(width_mm - thickness_mm, 0.0, thickness_mm),
        ),
    ]
    _append_divider_specs(
        carcass.root, layout, catalog, carcass.default_material, depth_mm, specs
    )
    return specs


def _append_divider_specs(
    bay: Bay,
    layout: SolvedLayout,
    catalog: Catalog,
    default_material: MaterialId,
    depth_mm: float,
    out: list[PlankSpec],
) -> None:
    """Pre-order walk appending one :class:`PlankSpec` per ``Divider`` to ``out``.

    A ``HORIZONTAL`` split's dividers are ``SHELF``; a ``VERTICAL`` split's are
    ``DIVIDER``. Each divider's size and placement come straight from its solved
    ``Rect``, extruded through ``depth_mm``. The material is the divider's own
    when set, else ``default_material``, resolved through ``catalog`` so an
    unknown id raises ``KeyError``.
    """
    if not isinstance(bay, Split):
        return
    horizontal = bay.orientation is Orientation.HORIZONTAL
    role = PlankRole.SHELF if horizontal else PlankRole.DIVIDER
    for index, child in enumerate(bay.children):
        _append_divider_specs(child, layout, catalog, default_material, depth_mm, out)
        if index >= len(bay.dividers):
            continue
        divider = bay.dividers[index]
        requested = (
            divider.material if divider.material is not None else default_material
        )
        material = catalog[requested].id
        rect = layout[divider.id]
        out.append(
            PlankSpec(
                node_id=divider.id,
                role=role,
                size=Vec3(rect.width_mm, depth_mm, rect.height_mm),
                placement=Vec3(rect.x_mm, 0.0, rect.z_mm),
                material=material,
            )
        )
