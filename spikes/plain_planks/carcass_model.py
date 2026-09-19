"""Frozen pre-M4 carcass model: the split tree sh-013 replaced in ``shelving_core``.

``spikes/plain_planks/general_model.py``, ``scan.py``, and their tests compare
themselves against this exact model, and ``docs/roadmap.md`` (M4, M5) commits
to keeping the whole ``spikes/plain_planks/`` package running as the fallback
until M6 deletes the directory outright. sh-013 deleted the carcass split
tree, its solver, and its expansion from ``shelving_core`` itself, so this
module is a copy of what those modules held immediately before that deletion
(``git show main:shelving_core/layout.py`` etc., at the commit sh-013
branched from), minus the JSON interop layer nothing here calls and the
reserved, never-read ``Divider.lap`` / ``LapOrder``.
Nothing outside ``spikes/plain_planks/`` imports it, and it gains no new
features: a real port to the region model is M5's job, not this file's.

``Fixed``, ``Weighted``, ``Fill``, and ``new_id`` are unchanged by sh-013, so
callers still get those from ``shelving_core.layout``; ``EPS_MM``,
``LayoutSolveError``, and ``distribute`` are unchanged too and still come from
``shelving_core.solver``. Only the carcass-specific types, ``solve``, and
``expand`` live here.
"""

import enum
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from shelving_core.geometry import Vec3
from shelving_core.layout import Fill, Fixed, Weighted, new_id
from shelving_core.materials import Catalog, MaterialId
from shelving_core.solver import EPS_MM, LayoutSolveError, distribute


class Orientation(enum.StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


SplitRule = Fixed | Weighted | Fill


@dataclass
class Leaf:
    """An open compartment. Carries only its persistent id."""

    id: str = field(default_factory=new_id)


@dataclass
class Divider:
    """The panel between two consecutive split children."""

    # ``None`` inherits ``Carcass.default_material``; the solver resolves the
    # id to a thickness, this model keeps the ``None`` verbatim.
    material: MaterialId | None = None
    id: str = field(default_factory=new_id)


@dataclass
class Split:
    """A bay divided into two or more child bays along one axis.

    ``rules`` is parallel to ``children`` (one rule per child); ``dividers``
    has one fewer entry, one per gap between consecutive children.
    """

    orientation: Orientation
    children: list["Bay"]
    rules: list[SplitRule]
    dividers: list[Divider]
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if len(self.children) < 2:
            raise ValueError(
                f"Split.children must have at least 2 entries, got {len(self.children)}"
            )
        if len(self.rules) != len(self.children):
            raise ValueError(
                f"Split.rules count ({len(self.rules)}) must equal children count "
                f"({len(self.children)})"
            )
        if len(self.dividers) != len(self.children) - 1:
            raise ValueError(
                f"Split.dividers count ({len(self.dividers)}) must equal children "
                f"count minus one ({len(self.children) - 1})"
            )


Bay = Leaf | Split


@dataclass
class Carcass:
    """The shelving box: outer dimensions, a default material, and a root bay."""

    width_mm: float
    height_mm: float
    depth_mm: float
    # Catalog id; its thickness applies to the shell panels and to any
    # ``Divider`` that sets no ``material`` of its own.
    default_material: MaterialId
    root: Bay
    # This unit's persistent identity, assigned once and preserved across edits.
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.width_mm <= 0:
            raise ValueError(f"Carcass.width_mm must be > 0, got {self.width_mm}")
        if self.height_mm <= 0:
            raise ValueError(f"Carcass.height_mm must be > 0, got {self.height_mm}")
        if self.depth_mm <= 0:
            raise ValueError(f"Carcass.depth_mm must be > 0, got {self.depth_mm}")
        if not self.default_material:
            raise ValueError("Carcass.default_material must be non-empty")


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
    """Record one :class:`Rect` per node id in the subtree rooted at ``bay``."""
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
    """Every physical plank of ``carcass``, in list order: the shell as
    ``BOTTOM``, ``TOP``, ``LEFT_SIDE``, ``RIGHT_SIDE``, then one plank per
    ``Divider`` from a depth-first walk of the split tree.

    A material id absent from ``catalog`` raises ``KeyError``; an unsatisfiable
    layout raises :class:`LayoutSolveError`.
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
    """Pre-order walk appending one :class:`PlankSpec` per ``Divider`` to ``out``."""
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
