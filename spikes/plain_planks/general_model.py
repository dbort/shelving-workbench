"""Plain-planks spike: the split tree without a carcass.

A `Carcass` names four shell planks that `expand` emits by rule: a top and a
bottom running the full width, two sides captured between them. That rule is
what refuses a stepped outline, and it is a special case of something the tree
already expresses. Here a split is an ordered list of *items* along its axis,
each either a `Plank` or a `Sub` region, and the shell is nothing but the
outermost planks of the outermost splits.

What that buys, all of it out of reach of the shell rule:

- a stepped or otherwise rectilinear outline, because a `Void` item is just
  another region with a size;
- two planks face to face, which a framed wall's double top plate needs;
- a plank that runs through where the shell rule says it is captured, because
  lap order is the order the splits nest;
- one solver path for shell and interior alike.

`solve` and `expand` here reuse `shelving_core.solver.distribute` unchanged: a
plank contributes `Fixed(thickness)` and a region contributes its own rule, so
the arithmetic never needed to know which was which.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field

from shelving_core.expand import PlankRole, PlankSpec, Vec3
from shelving_core.layout import Fill, Fixed, Orientation, SplitRule, new_id
from shelving_core.materials import Catalog, MaterialId
from shelving_core.solver import EPS_MM, LayoutSolveError, Rect, distribute

# A role is a free-form string here: the general tree has no closed set of
# shell positions, and a stepped outline has several tops. The mapping exists
# only so a spec can carry the core's enum where a name happens to match.
_ROLE_BY_NAME = {role.value: role for role in PlankRole}
_DEFAULT_ROLE = PlankRole.DIVIDER


class Face(enum.StrEnum):
    """Which end of the depth axis a unit is viewed from."""

    MIN = "min"
    MAX = "max"


@dataclass
class Plank:
    """One physical panel, sized along its split's axis by its thickness.

    ``front_inset_mm`` sets the panel back from the unit's front face; the rear
    stays flush, which is how a unit sits against a wall. ``depth_mm``
    overrides the unit depth outright when a panel is neither.
    """

    material: MaterialId | None = None
    front_inset_mm: float = 0.0
    depth_mm: float | None = None
    role: str = ""
    id: str = field(default_factory=new_id)


@dataclass
class Sub:
    """A child region with the rule that sizes it along its split's axis."""

    region: Region
    rule: SplitRule = field(default_factory=Fill)


Item = Plank | Sub


@dataclass
class Bay:
    """An enclosed compartment: open, and part of the unit."""

    id: str = field(default_factory=new_id)


@dataclass
class Void:
    """Space inside the bounding rectangle that is not part of the unit.

    What makes an outline stepped. It holds no planks and is not a compartment.
    """

    id: str = field(default_factory=new_id)


@dataclass
class Divide:
    """A region cut into an ordered run of planks and sub-regions along an axis.

    ``Orientation.HORIZONTAL`` cuts with horizontal planks, so the items stack
    up the elevation. Items are in order along that axis and need not
    alternate: two adjacent planks are two panels face to face.
    """

    orientation: Orientation
    items: list[Item]
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("Divide.items must not be empty")


Region = Bay | Void | Divide


@dataclass
class Unit:
    """A shelving unit: outer size, a default material, and a root region.

    There is no shell field and no shell rule. Every panel is a ``Plank`` item
    somewhere in the tree, so a closed box, a stepped outline, and a framed wall
    differ only in the shape of that tree.
    """

    width_mm: float
    height_mm: float
    depth_mm: float
    default_material: MaterialId
    root: Region
    # Which end of the depth axis faces the viewer. Stored, never inferred:
    # geometry usually cannot say (see the evaluation doc).
    face: Face | None = None
    id: str = field(default_factory=new_id)


def solve(unit: Unit, catalog: Catalog) -> dict[str, Rect]:
    """One :class:`Rect` per region and plank id, in the unit's local frame.

    Raises :class:`LayoutSolveError` exactly as the carcass solver does; the
    shell participates in the same distribution as everything else, so a shell
    that does not fit is an ordinary overflow.
    """
    rects: dict[str, Rect] = {}
    _place(
        unit.root,
        Rect(0.0, 0.0, unit.width_mm, unit.height_mm),
        unit,
        catalog,
        rects,
    )
    return rects


def _thickness_mm(plank: Plank, unit: Unit, catalog: Catalog) -> float:
    return catalog[plank.material or unit.default_material].thickness_mm


def _place(
    region: Region,
    rect: Rect,
    unit: Unit,
    catalog: Catalog,
    out: dict[str, Rect],
) -> None:
    out[region.id] = rect
    if not isinstance(region, Divide):
        return
    along_mm = (
        rect.height_mm
        if region.orientation is Orientation.HORIZONTAL
        else rect.width_mm
    )
    # A plank's size along the axis is its thickness, which is exactly a Fixed
    # rule, so planks and regions go through one distribution.
    rules: list[SplitRule] = [
        Fixed(size_mm=_thickness_mm(item, unit, catalog))
        if isinstance(item, Plank)
        else item.rule
        for item in region.items
    ]
    sizes_mm = distribute(along_mm, rules, [], node_id=region.id)
    cursor_mm = rect.z_mm if region.orientation is Orientation.HORIZONTAL else rect.x_mm
    for item, size_mm in zip(region.items, sizes_mm, strict=True):
        if size_mm <= EPS_MM:
            raise LayoutSolveError(
                item.id if isinstance(item, Plank) else item.region.id,
                "nonpositive_opening",
                {"size_mm": size_mm},
            )
        if region.orientation is Orientation.HORIZONTAL:
            child = Rect(rect.x_mm, cursor_mm, rect.width_mm, size_mm)
        else:
            child = Rect(cursor_mm, rect.z_mm, size_mm, rect.height_mm)
        cursor_mm += size_mm
        if isinstance(item, Plank):
            out[item.id] = child
        else:
            _place(item.region, child, unit, catalog, out)


def expand(unit: Unit, catalog: Catalog) -> list[PlankSpec]:
    """One :class:`PlankSpec` per ``Plank`` in the tree, in tree order.

    Depth runs along +Y from the unit's front face at Y=0, so a plank's
    ``front_inset_mm`` moves it back and leaves its rear flush.
    """
    rects = solve(unit, catalog)
    specs: list[PlankSpec] = []
    _collect(unit.root, unit, catalog, rects, specs)
    return specs


def _collect(
    region: Region,
    unit: Unit,
    catalog: Catalog,
    rects: Mapping[str, Rect],
    out: list[PlankSpec],
) -> None:
    if not isinstance(region, Divide):
        return
    for item in region.items:
        if isinstance(item, Sub):
            _collect(item.region, unit, catalog, rects, out)
            continue
        rect = rects[item.id]
        depth_mm = (
            item.depth_mm
            if item.depth_mm is not None
            else unit.depth_mm - item.front_inset_mm
        )
        out.append(
            PlankSpec(
                node_id=item.id,
                # PlankRole is a closed enum in the core; the general model
                # carries a free-form role instead, so the spec's role field is
                # reused only where it maps.
                role=_ROLE_BY_NAME.get(item.role, _DEFAULT_ROLE),
                size=Vec3(rect.width_mm, depth_mm, rect.height_mm),
                placement=Vec3(rect.x_mm, item.front_inset_mm, rect.z_mm),
                material=item.material or unit.default_material,
            )
        )


def bays(unit: Unit) -> list[Bay]:
    """Every open compartment, in tree order. ``Void`` regions are not bays."""
    found: list[Bay] = []

    def walk(region: Region) -> None:
        if isinstance(region, Bay):
            found.append(region)
        elif isinstance(region, Divide):
            for item in region.items:
                if isinstance(item, Sub):
                    walk(item.region)

    walk(unit.root)
    return found


def closed_box(
    width_mm: float,
    height_mm: float,
    depth_mm: float,
    material: MaterialId,
    interior: Region | None = None,
    interior_rule: SplitRule | None = None,
) -> Unit:
    """A unit whose shell is the carcass default: a bottom and a top running the
    full width, the two sides captured between them.

    The shape `Carcass` hard-codes, written out as ordinary items. Everything a
    carcass could express is this call; everything it could not is a different
    tree.
    """
    inner: Region = interior if interior is not None else Bay()
    return Unit(
        width_mm=width_mm,
        height_mm=height_mm,
        depth_mm=depth_mm,
        default_material=material,
        root=Divide(
            orientation=Orientation.HORIZONTAL,
            items=[
                Plank(role="bottom"),
                Sub(
                    region=Divide(
                        orientation=Orientation.VERTICAL,
                        items=[
                            Plank(role="left_side"),
                            Sub(
                                region=inner,
                                rule=interior_rule or Fill(),
                            ),
                            Plank(role="right_side"),
                        ],
                    )
                ),
                Plank(role="top"),
            ],
        ),
    )
