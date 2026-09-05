"""Plain-planks spike: recognise a cut tree from axis-aligned boxes.

Throwaway code that proves the recognition rule described in
``docs/parametric-model-evaluation.md`` against the core's ``expand`` as the
oracle. Nothing in the workbench imports it.

The elevation plane is detected, not assumed: real units are modelled on
whichever plane suited the room, so the depth axis is taken to be the one with
the smallest bounding-box extent and can be overridden. Within the plane the
vertical axis is Z unless Z is the depth. A plank thin along the depth axis (a
back or front panel) projects over the whole elevation and is set aside.

Recognition runs on a cell grid whose lines are every plank edge. A flood fill
from the grid's border through uncovered cells marks the outside. At each
region the planks whose line across the region meets only themselves, outside
cells, or a clearance gap are the full-span cuts; the strips between them are
recursed into. The plank cut at a region is the one that runs through at every
joint with the planks inside its strips, so lap order is the tree order.
"""

import enum
import json
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple

from shelving_core.expand import PlankSpec
from shelving_core.layout import (
    Bay,
    Carcass,
    Divider,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
    SplitRule,
)
from shelving_core.materials import MaterialId

# Real geometry disagrees at joints by tens of microns: a unit exported from
# FreeCAD had four supposedly-coincident edges spread over 0.09 mm. The snap has
# to absorb that and stay far below any real feature size.
DEFAULT_SNAP_MM = 0.5
DEFAULT_CLEARANCE_MM = 3.0

_AXIS_NAMES = ("X", "Y", "Z")


class Plane(NamedTuple):
    """Which axis is which, as indices into a box's corner and size triples,
    plus which end of the depth axis the unit is viewed from.

    ``front_at_min`` is ``None`` when geometry does not determine it. It never
    affects the recognised tree, only which end of a split is called left.
    """

    depth: int
    horizontal: int
    vertical: int
    front_at_min: bool | None = None

    def __str__(self) -> str:
        facing = (
            "front undetermined"
            if self.front_at_min is None
            else f"front at {'min' if self.front_at_min else 'max'} "
            f"{_AXIS_NAMES[self.depth]}"
        )
        return (
            f"{_AXIS_NAMES[self.horizontal]}{_AXIS_NAMES[self.vertical]} elevation, "
            f"depth along {_AXIS_NAMES[self.depth]}, {facing}"
        )

    @property
    def screen_right_sign(self) -> int | None:
        """``+1`` when increasing the horizontal axis moves to the viewer's
        right, ``-1`` when it moves left, ``None`` while the front is unknown.

        Left and right in a label or an elevation view are meaningless without
        this, and it cannot be recovered from the plane alone: the same YZ
        elevation reads mirrored from either side.
        """
        if self.front_at_min is None:
            return None
        # The viewing direction points into the unit, away from the viewer.
        forward = [0.0, 0.0, 0.0]
        forward[self.depth] = 1.0 if self.front_at_min else -1.0
        up = [0.0, 0.0, 0.0]
        up[self.vertical] = 1.0
        right = (
            forward[1] * up[2] - forward[2] * up[1],
            forward[2] * up[0] - forward[0] * up[2],
            forward[0] * up[1] - forward[1] * up[0],
        )
        return 1 if right[self.horizontal] > 0 else -1


class Member(enum.StrEnum):
    """What a plank is, by the axis it is thin along."""

    # Thin across the elevation: a side or a divider.
    UPRIGHT = "upright"
    # Thin up the elevation: a shelf, a top, or a bottom.
    SHELF = "shelf"
    # Thin through the depth: a back or a front, outside the bay partition.
    PANEL = "panel"


@dataclass(frozen=True)
class Box:
    """One axis-aligned solid: minimum corner and extent, millimetres."""

    name: str
    corner_mm: tuple[float, float, float]
    size_mm: tuple[float, float, float]


@dataclass(frozen=True)
class Plank:
    """A box in elevation coordinates: ``h`` across, ``v`` up, ``d`` through."""

    name: str
    h0_mm: float
    h1_mm: float
    v0_mm: float
    v1_mm: float
    d0_mm: float
    d1_mm: float
    member: Member

    @property
    def thickness_mm(self) -> float:
        match self.member:
            case Member.UPRIGHT:
                return self.h1_mm - self.h0_mm
            case Member.SHELF:
                return self.v1_mm - self.v0_mm
            case Member.PANEL:
                return self.d1_mm - self.d0_mm

    @property
    def depth_mm(self) -> float:
        return self.d1_mm - self.d0_mm


class RecogniseError(ValueError):
    """A refusal: ``objects`` names the boxes the diagnosis points at."""

    def __init__(self, message: str, objects: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.objects = tuple(objects)


@dataclass(frozen=True)
class Rect:
    """A region of the elevation: ``h`` across, ``v`` up."""

    h0_mm: float
    h1_mm: float
    v0_mm: float
    v1_mm: float

    @property
    def width_mm(self) -> float:
        return self.h1_mm - self.h0_mm

    @property
    def height_mm(self) -> float:
        return self.v1_mm - self.v0_mm


@dataclass(frozen=True)
class Open:
    """An enclosed void: an open bay."""

    rect: Rect


@dataclass(frozen=True)
class Outside:
    """A void reachable from the bounding rectangle's edge: not part of the unit."""

    rect: Rect


@dataclass(frozen=True)
class Cut:
    """A full-span plank at one region, with the enclosed gap at each end."""

    plank: Plank
    clearance_lo_mm: float
    clearance_hi_mm: float


@dataclass(frozen=True)
class CutSplit:
    """A region divided by parallel full-span cuts.

    ``strips`` has one entry per gap between consecutive cuts plus one before
    the first and one after the last; an entry is ``None`` when that gap has
    zero size, which is how a cut lying on the region's edge (a shell plank)
    appears. ``orientation`` follows the core: a ``HORIZONTAL`` split stacks
    its children up the elevation and cuts with shelves.
    """

    orientation: Orientation
    rect: Rect
    cuts: tuple[Cut, ...]
    strips: tuple["Node | None", ...]


Node = Open | Outside | CutSplit


@dataclass(frozen=True)
class Recognised:
    plane: Plane
    # What settled the facing, so a caller can weigh a convention against a
    # panel it can point at.
    facing_evidence: "FacingEvidence"
    bbox: Rect
    # Extent of the elevation members through the depth axis. Panels set aside
    # as backs or fronts may lie outside it.
    d0_mm: float
    depth_mm: float
    root: Node
    panels: tuple[Plank, ...]
    planks: tuple[Plank, ...]

    @property
    def depths_mm(self) -> set[float]:
        """Every distinct member depth; more than one means per-plank depth."""
        return {round(p.depth_mm, 4) for p in self.planks}


def boxes_from_json(text: str) -> list[Box]:
    """Parse the JSON written by ``export_boxes.py`` into ``Box`` records."""
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("top-level JSON value must be an object")
    raw_boxes = parsed.get("boxes")
    if not isinstance(raw_boxes, list):
        raise ValueError("'boxes' must be an array")
    boxes: list[Box] = []
    for entry in raw_boxes:
        if not isinstance(entry, dict):
            raise ValueError(f"box entry must be an object, got {entry!r}")
        boxes.append(
            Box(
                name=_req_str(entry, "name"),
                corner_mm=_req_vec(entry, "corner_mm"),
                size_mm=_req_vec(entry, "size_mm"),
            )
        )
    return boxes


def boxes_from_specs(specs: Sequence[PlankSpec]) -> list[Box]:
    """The ``Box`` form of ``expand``'s output, for the round-trip test."""
    return [
        Box(
            name=spec.node_id,
            corner_mm=(spec.placement.x_mm, spec.placement.y_mm, spec.placement.z_mm),
            size_mm=(spec.size.x_mm, spec.size.y_mm, spec.size.z_mm),
        )
        for spec in specs
    ]


class FacingEvidence(enum.StrEnum):
    """What settled which way a unit faces."""

    # The caller said so, or a stored property did.
    GIVEN = "given"
    # A depth-thin plank: proud of the members is a front, within them a back.
    PANEL = "panel"
    # The rear of a unit is almost always flush and the front may be inset for
    # looks, so the end the members sit flush with is the back.
    FLUSH_BACK = "flush_back"
    # Nothing distinguishes the two faces.
    NONE = "none"


class Facing(NamedTuple):
    front_at_min: bool | None
    evidence: FacingEvidence


def detect_axes(boxes: Sequence[Box]) -> Plane:
    """The elevation axes of ``boxes``: depth is the shallowest bounding-box
    axis, vertical is Z unless Z is the depth. Facing is left undetermined.

    A unit deeper than it is wide or tall would fool the depth choice;
    ``recognise`` takes an explicit ``plane`` for that case.
    """
    spans = [
        max(b.corner_mm[axis] + b.size_mm[axis] for b in boxes)
        - min(b.corner_mm[axis] for b in boxes)
        for axis in range(3)
    ]
    depth = min(range(3), key=lambda axis: spans[axis])
    vertical = 2 if depth != 2 else 1
    horizontal = next(axis for axis in range(3) if axis not in (depth, vertical))
    return Plane(depth=depth, horizontal=horizontal, vertical=vertical)


def detect_plane(boxes: Sequence[Box]) -> Plane:
    """:func:`detect_axes` with the facing filled in from :func:`infer_facing`."""
    axes = detect_axes(boxes)
    return axes._replace(front_at_min=infer_facing(boxes, axes).front_at_min)


def infer_facing(boxes: Sequence[Box], plane: Plane, tol_mm: float = 0.5) -> Facing:
    """Which end of the depth axis is the front, and what said so.

    Two signals, strongest first. A plank thin through the depth settles it:
    one lying within the members is a back, and one lying proud of them is a
    door when it is stock-thickness and an overlay back when it is thin, which
    point opposite ways. Failing that, the rear of a unit is almost
    always flush against the wall while the front may be inset for looks, so
    the end the members sit flush with is the back. A unit whose members are
    equally flush at both ends, which is any plain rectangular box, says
    nothing.

    Depth alignment alone was nearly read backwards here: a real unit's shallow
    planks are flush at the rear and inset three inches at the front, so the
    inset end is the front, not the back.
    """
    planks = [_classify(box, plane) for box in boxes]
    members = [p for p in planks if p.member is not Member.PANEL]
    if not members:
        return Facing(None, FacingEvidence.NONE)
    lo = min(p.d0_mm for p in members)
    hi = max(p.d1_mm for p in members)

    # A panel much thinner than the stock around it is backing material, not a
    # door. Without this a Woodworking cabinet's overlay back, which sits proud
    # behind the carcass, reads as a front and mirrors the whole elevation.
    thin_mm = _median(sorted(p.thickness_mm for p in members)) / 2.0
    votes = {
        _panel_vote(panel, lo, hi, panel.thickness_mm < thin_mm)
        for panel in planks
        if panel.member is Member.PANEL
    }
    if len(votes) == 1:
        return Facing(votes.pop(), FacingEvidence.PANEL)

    inset_at_min_mm = sum(p.d0_mm - lo for p in members)
    inset_at_max_mm = sum(hi - p.d1_mm for p in members)
    if abs(inset_at_min_mm - inset_at_max_mm) <= tol_mm:
        return Facing(None, FacingEvidence.NONE)
    # The flush end is the back, so the front is the end with more inset.
    return Facing(inset_at_min_mm > inset_at_max_mm, FacingEvidence.FLUSH_BACK)


def _panel_vote(panel: Plank, lo: float, hi: float, backing: bool) -> bool:
    """Whether this panel says the front is at the low end of the depth axis.

    A panel proud of the members is a door when it is stock-thickness and an
    overlay back when it is thin, and those point opposite ways.
    """
    if panel.d1_mm <= lo:
        return not backing
    if panel.d0_mm >= hi:
        return backing
    # Set within the members: a back, so the front is the far end.
    return (panel.d0_mm + panel.d1_mm) / 2.0 > (lo + hi) / 2.0


def _median(sorted_values: Sequence[float]) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def recognise(
    boxes: Sequence[Box],
    snap_mm: float = DEFAULT_SNAP_MM,
    clearance_mm: float = DEFAULT_CLEARANCE_MM,
    plane: Plane | None = None,
) -> Recognised:
    """The cut tree of ``boxes``, or ``RecogniseError`` naming the offenders.

    ``plane`` defaults to :func:`detect_plane`. Edges within ``snap_mm`` of each
    other are one grid line. A plank end may stop up to ``clearance_mm`` short
    of the region edge it spans to; the gap is recorded on the ``Cut``.
    """
    if not boxes:
        raise RecogniseError("no boxes to recognise")
    if plane is None:
        plane = detect_axes(boxes)
    if plane.front_at_min is None:
        facing = infer_facing(boxes, plane)
        plane = plane._replace(front_at_min=facing.front_at_min)
    else:
        facing = Facing(plane.front_at_min, FacingEvidence.GIVEN)
    planks = [_classify(box, plane) for box in boxes]
    panels = tuple(p for p in planks if p.member is Member.PANEL)
    members = [p for p in planks if p.member is not Member.PANEL]
    if not members:
        raise RecogniseError(
            f"every box is thin through the depth axis ({plane}); nothing forms "
            "an elevation",
            (p.name for p in planks),
        )
    grid = _Grid(members, snap_mm)
    bbox = Rect(grid.hs[0], grid.hs[-1], grid.vs[0], grid.vs[-1])
    d0_mm = min(p.d0_mm for p in members)
    d1_mm = max(p.d1_mm for p in members)
    root = _region(grid, 0, len(grid.hs) - 1, 0, len(grid.vs) - 1, clearance_mm)
    if not _has_open(root):
        raise RecogniseError(
            "no enclosed bay: the outside reaches every void, so the shell has "
            "a gap wider than the clearance tolerance"
        )
    return Recognised(
        plane=plane,
        facing_evidence=facing.evidence,
        bbox=bbox,
        d0_mm=d0_mm,
        depth_mm=d1_mm - d0_mm,
        root=root,
        panels=panels,
        planks=tuple(grid.planks),
    )


def to_carcass(
    rec: Recognised,
    material_for_thickness: Mapping[float, MaterialId],
    snap_mm: float = DEFAULT_SNAP_MM,
) -> Carcass:
    """Today's implicit-shell ``Carcass`` for a closed rectangular unit.

    Requires the root to be cut by exactly a bottom and a top with nothing
    beyond them, and the strip between to be cut by exactly a left and a right
    side; anything else (an outside leaf, a stepped outline) raises
    ``RecogniseError``. Sibling openings equal within ``snap_mm`` become
    ``Fill``; every other opening is ``Fixed`` at its size.
    """
    root = rec.root
    if not (
        isinstance(root, CutSplit)
        and root.orientation is Orientation.HORIZONTAL
        and len(root.cuts) == 2
        and root.strips[0] is None
        and root.strips[2] is None
    ):
        raise RecogniseError(
            "unit is not a closed rectangle: expected a bottom and a top on the "
            "bounding rectangle's edges"
        )
    middle = root.strips[1]
    if not (
        isinstance(middle, CutSplit)
        and middle.orientation is Orientation.VERTICAL
        and len(middle.cuts) >= 2
        and middle.strips[0] is None
        and middle.strips[-1] is None
    ):
        raise RecogniseError(
            "unit is not a closed rectangle: expected a left and a right side "
            "captured between the bottom and the top"
        )
    if len(root.cuts) != 2:
        raise RecogniseError(
            "a shelf runs through the sides; today's Carcass has no lap override",
            (c.plank.name for c in root.cuts[1:-1]),
        )
    shell_cuts = (*root.cuts, middle.cuts[0], middle.cuts[-1])
    shell_thicknesses = {round(c.plank.thickness_mm, 3) for c in shell_cuts}
    if len(shell_thicknesses) != 1:
        raise RecogniseError(
            f"shell planks have differing thicknesses {sorted(shell_thicknesses)}",
            (c.plank.name for c in shell_cuts),
        )
    default_material = _material_for(
        material_for_thickness, next(iter(shell_thicknesses)), snap_mm
    )
    # A full-height divider is a full-span cut at the same level as the sides,
    # so the interior cuts between the two sides are the root split's dividers.
    interior_cuts = middle.cuts[1:-1]
    interior_strips = middle.strips[1:-1]
    root_bay: Bay
    if interior_cuts:
        root_bay = _split(
            Orientation.VERTICAL,
            interior_cuts,
            interior_strips,
            default_material,
            material_for_thickness,
            snap_mm,
        )
    else:
        inner = interior_strips[0]
        if inner is None:
            raise RecogniseError("the sides leave no interior")
        root_bay = _bay(inner, default_material, material_for_thickness, snap_mm)
    return Carcass(
        width_mm=rec.bbox.width_mm,
        height_mm=rec.bbox.height_mm,
        depth_mm=rec.depth_mm,
        default_material=default_material,
        root=root_bay,
    )


def _has_open(node: Node | None) -> bool:
    if isinstance(node, Open):
        return True
    if isinstance(node, CutSplit):
        return any(_has_open(strip) for strip in node.strips)
    return False


def thicknesses(rec: Recognised, places: int = 4) -> set[float]:
    """Every distinct plank thickness in the cut tree, for building a catalog.

    Rounded to ``places`` decimals: a measured extent carries float noise well
    below any thickness difference that means a different stock.
    """
    found: set[float] = set()

    def walk(node: Node | None) -> None:
        if isinstance(node, CutSplit):
            for cut in node.cuts:
                found.add(round(cut.plank.thickness_mm, places))
            for strip in node.strips:
                walk(strip)

    walk(rec.root)
    return found


def _bay(
    node: Node,
    default_material: MaterialId,
    material_for_thickness: Mapping[float, MaterialId],
    snap_mm: float,
) -> Bay:
    match node:
        case Open():
            return Leaf()
        case Outside():
            raise RecogniseError(
                "an outside region lies within a closed carcass; the spike converts "
                "closed rectangles only"
            )
        case CutSplit():
            return _split(
                node.orientation,
                node.cuts,
                node.strips,
                default_material,
                material_for_thickness,
                snap_mm,
            )


def _split(
    orientation: Orientation,
    cuts: Sequence[Cut],
    strips: Sequence[Node | None],
    default_material: MaterialId,
    material_for_thickness: Mapping[float, MaterialId],
    snap_mm: float,
) -> Split:
    children: list[Bay] = []
    sizes_mm: list[float] = []
    for strip in strips:
        if strip is None:
            raise RecogniseError(
                "a divider sits on the edge of its bay",
                (c.plank.name for c in cuts),
            )
        children.append(_bay(strip, default_material, material_for_thickness, snap_mm))
        rect = strip.rect
        sizes_mm.append(
            rect.height_mm if orientation is Orientation.HORIZONTAL else rect.width_mm
        )
    dividers: list[Divider] = []
    for cut in cuts:
        material = _material_for(
            material_for_thickness, cut.plank.thickness_mm, snap_mm
        )
        dividers.append(
            Divider(material=None if material == default_material else material)
        )
    return Split(
        orientation=orientation,
        children=children,
        rules=_recover_rules(sizes_mm, snap_mm),
        dividers=dividers,
    )


def _material_for(
    material_for_thickness: Mapping[float, MaterialId],
    thickness_mm: float,
    snap_mm: float,
) -> MaterialId:
    for known_mm, material in material_for_thickness.items():
        if abs(known_mm - thickness_mm) <= snap_mm:
            return material
    raise RecogniseError(f"no material has thickness {thickness_mm:g} mm")


def _recover_rules(sizes_mm: Sequence[float], snap_mm: float) -> list[SplitRule]:
    """``Fill`` for every size that another sibling matches within ``snap_mm``,
    ``Fixed`` otherwise."""
    rules: list[SplitRule] = []
    for i, size_mm in enumerate(sizes_mm):
        has_twin = any(
            j != i and abs(other - size_mm) <= snap_mm
            for j, other in enumerate(sizes_mm)
        )
        rules.append(Fill() if has_twin else Fixed(size_mm=size_mm))
    return rules


def _classify(box: Box, plane: Plane) -> Plank:
    if min(box.size_mm) <= 0:
        raise RecogniseError(
            f"{box.name}: every extent must be positive, got "
            f"{box.size_mm[0]:g} x {box.size_mm[1]:g} x {box.size_mm[2]:g}",
            (box.name,),
        )
    smallest = min(box.size_mm)
    thin_axes = [a for a in range(3) if box.size_mm[a] == smallest]
    if len(thin_axes) != 1:
        raise RecogniseError(
            f"{box.name}: no single thin axis (extents "
            f"{box.size_mm[0]:g} x {box.size_mm[1]:g} x {box.size_mm[2]:g})",
            (box.name,),
        )
    thin = thin_axes[0]
    if thin == plane.horizontal:
        member = Member.UPRIGHT
    elif thin == plane.vertical:
        member = Member.SHELF
    else:
        member = Member.PANEL

    def span(axis: int) -> tuple[float, float]:
        return (box.corner_mm[axis], box.corner_mm[axis] + box.size_mm[axis])

    h0_mm, h1_mm = span(plane.horizontal)
    v0_mm, v1_mm = span(plane.vertical)
    d0_mm, d1_mm = span(plane.depth)
    return Plank(
        name=box.name,
        h0_mm=h0_mm,
        h1_mm=h1_mm,
        v0_mm=v0_mm,
        v1_mm=v1_mm,
        d0_mm=d0_mm,
        d1_mm=d1_mm,
        member=member,
    )


_EMPTY = -1


class _Grid:
    """Cell grid over the elevation. ``cover[j][i]`` is the plank index at
    column ``i`` (across) and row ``j`` (up), or ``_EMPTY``; ``outside[j][i]``
    marks uncovered cells reachable from the border."""

    def __init__(self, planks: Sequence[Plank], snap_mm: float) -> None:
        self.hs = _snap_lines([v for p in planks for v in (p.h0_mm, p.h1_mm)], snap_mm)
        self.vs = _snap_lines([v for p in planks for v in (p.v0_mm, p.v1_mm)], snap_mm)
        self.planks: list[Plank] = []
        self.cols: list[tuple[int, int]] = []
        self.rows: list[tuple[int, int]] = []
        nh = len(self.hs) - 1
        nv = len(self.vs) - 1
        self.cover = [[_EMPTY] * nh for _ in range(nv)]
        for index, plank in enumerate(planks):
            i0 = _index_of(self.hs, plank.h0_mm, snap_mm)
            i1 = _index_of(self.hs, plank.h1_mm, snap_mm)
            j0 = _index_of(self.vs, plank.v0_mm, snap_mm)
            j1 = _index_of(self.vs, plank.v1_mm, snap_mm)
            if i0 == i1 or j0 == j1:
                raise RecogniseError(
                    f"{plank.name}: an extent collapses at the {snap_mm:g} mm snap "
                    "tolerance",
                    (plank.name,),
                )
            for j in range(j0, j1):
                for i in range(i0, i1):
                    other = self.cover[j][i]
                    if other != _EMPTY:
                        raise RecogniseError(
                            f"{plank.name} overlaps {planks[other].name}",
                            (plank.name, planks[other].name),
                        )
                    self.cover[j][i] = index
            # Keep the plank's measured extents. Snapping moves an edge by up
            # to half the tolerance, which would corrupt the thickness that
            # identifies the plank's material; the grid owns the topology and
            # `cols` / `rows` carry it.
            self.planks.append(plank)
            self.cols.append((i0, i1))
            self.rows.append((j0, j1))
        self.outside = self._flood_outside(nh, nv)

    def _flood_outside(self, nh: int, nv: int) -> list[list[bool]]:
        outside = [[False] * nh for _ in range(nv)]
        queue: deque[tuple[int, int]] = deque()
        for j in range(nv):
            for i in range(nh):
                on_border = i == 0 or j == 0 or i == nh - 1 or j == nv - 1
                if on_border and self.cover[j][i] == _EMPTY:
                    outside[j][i] = True
                    queue.append((i, j))
        while queue:
            i, j = queue.popleft()
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < nh and 0 <= nj < nv:
                    if not outside[nj][ni] and self.cover[nj][ni] == _EMPTY:
                        outside[nj][ni] = True
                        queue.append((ni, nj))
        return outside

    def rect(self, i0: int, i1: int, j0: int, j1: int) -> Rect:
        return Rect(self.hs[i0], self.hs[i1], self.vs[j0], self.vs[j1])


def _region(
    grid: _Grid, i0: int, i1: int, j0: int, j1: int, clearance_mm: float
) -> Node:
    inside: list[int] = []
    for index, ((pi0, pi1), (pj0, pj1)) in enumerate(
        zip(grid.cols, grid.rows, strict=True)
    ):
        overlaps = pi0 < i1 and pi1 > i0 and pj0 < j1 and pj1 > j0
        if not overlaps:
            continue
        contained = pi0 >= i0 and pi1 <= i1 and pj0 >= j0 and pj1 <= j1
        if not contained:
            raise RecogniseError(
                f"{grid.planks[index].name} crosses the boundary of the bay it lies in",
                (grid.planks[index].name,),
            )
        inside.append(index)
    rect = grid.rect(i0, i1, j0, j1)
    if not inside:
        cells = [(i, j) for j in range(j0, j1) for i in range(i0, i1)]
        outside_count = sum(1 for i, j in cells if grid.outside[j][i])
        if outside_count == len(cells):
            return Outside(rect)
        if outside_count == 0:
            return Open(rect)
        raise RecogniseError(
            f"the empty region {rect} is partly enclosed and partly open to the "
            "outside; the outline is not a tree"
        )

    h_cuts = [
        cut
        for index in inside
        if grid.planks[index].member is Member.SHELF
        and (cut := _horizontal_cut(grid, index, i0, i1, clearance_mm)) is not None
    ]
    v_cuts = [
        cut
        for index in inside
        if grid.planks[index].member is Member.UPRIGHT
        and (cut := _vertical_cut(grid, index, j0, j1, clearance_mm)) is not None
    ]
    if h_cuts and v_cuts:
        raise RecogniseError(
            "both a horizontal and a vertical plank span the same region",
            (c.plank.name for c in (*h_cuts, *v_cuts)),
        )
    if not h_cuts and not v_cuts:
        raise RecogniseError(
            f"no plank runs the full span of the region {rect}; the layout is "
            "not a tree",
            (grid.planks[index].name for index in inside),
        )
    if h_cuts:
        h_cuts.sort(key=lambda c: c.plank.v0_mm)
        bounds = [j0]
        for cut in h_cuts:
            pj0, pj1 = grid.rows[grid.planks.index(cut.plank)]
            bounds.extend((pj0, pj1))
        bounds.append(j1)
        strips: list[Node | None] = []
        for lo, hi in zip(bounds[0::2], bounds[1::2], strict=True):
            strips.append(
                None if lo == hi else _region(grid, i0, i1, lo, hi, clearance_mm)
            )
        return CutSplit(Orientation.HORIZONTAL, rect, tuple(h_cuts), tuple(strips))
    v_cuts.sort(key=lambda c: c.plank.h0_mm)
    bounds = [i0]
    for cut in v_cuts:
        pi0, pi1 = grid.cols[grid.planks.index(cut.plank)]
        bounds.extend((pi0, pi1))
    bounds.append(i1)
    v_strips: list[Node | None] = []
    for lo, hi in zip(bounds[0::2], bounds[1::2], strict=True):
        v_strips.append(
            None if lo == hi else _region(grid, lo, hi, j0, j1, clearance_mm)
        )
    return CutSplit(Orientation.VERTICAL, rect, tuple(v_cuts), tuple(v_strips))


def _horizontal_cut(
    grid: _Grid, index: int, i0: int, i1: int, clearance_mm: float
) -> Cut | None:
    pi0, pi1 = grid.cols[index]
    pj0, pj1 = grid.rows[index]
    lo = _gap(grid, range(pi0 - 1, i0 - 1, -1), range(pj0, pj1), grid.hs, True)
    hi = _gap(grid, range(pi1, i1), range(pj0, pj1), grid.hs, True)
    if lo is None or hi is None or lo > clearance_mm or hi > clearance_mm:
        return None
    return Cut(grid.planks[index], lo, hi)


def _vertical_cut(
    grid: _Grid, index: int, j0: int, j1: int, clearance_mm: float
) -> Cut | None:
    pi0, pi1 = grid.cols[index]
    pj0, pj1 = grid.rows[index]
    lo = _gap(grid, range(pj0 - 1, j0 - 1, -1), range(pi0, pi1), grid.vs, False)
    hi = _gap(grid, range(pj1, j1), range(pi0, pi1), grid.vs, False)
    if lo is None or hi is None or lo > clearance_mm or hi > clearance_mm:
        return None
    return Cut(grid.planks[index], lo, hi)


def _gap(
    grid: _Grid,
    along: range,
    across: range,
    lines: Sequence[float],
    horizontal: bool,
) -> float | None:
    """Enclosed gap width walking ``along`` from a plank end toward the region
    edge, or ``None`` when another plank blocks the line. Outside cells cost
    nothing; enclosed uncovered cells add their width."""
    gap_mm = 0.0
    for a in along:
        enclosed = False
        for b in across:
            i, j = (a, b) if horizontal else (b, a)
            if grid.cover[j][i] != _EMPTY:
                return None
            if not grid.outside[j][i]:
                enclosed = True
        if enclosed:
            gap_mm += lines[a + 1] - lines[a]
    return gap_mm


def _snap_lines(values: Iterable[float], snap_mm: float) -> list[float]:
    """Sorted grid lines: each cluster of values within ``snap_mm`` of its own
    first member collapses to one line at the cluster's midpoint.

    Measuring from the cluster start rather than the previous value stops a run
    of small steps from chaining into one wide cluster, and stops four edges
    that should coincide from splitting because the outermost pair is a hair
    over the tolerance.
    """
    lines: list[float] = []
    cluster: list[float] = []
    for value in sorted(values):
        if cluster and value - cluster[0] > snap_mm:
            lines.append((cluster[0] + cluster[-1]) / 2.0)
            cluster = []
        cluster.append(value)
    if cluster:
        lines.append((cluster[0] + cluster[-1]) / 2.0)
    return lines


def _index_of(lines: Sequence[float], value: float, snap_mm: float) -> int:
    """Index of the grid line ``value`` snapped to; the nearest one, since a
    cluster midpoint can sit up to half the tolerance from any member."""
    best = min(range(len(lines)), key=lambda index: abs(lines[index] - value))
    if abs(lines[best] - value) > snap_mm:
        raise AssertionError(f"{value} is not on the grid")
    return best


def _req_str(obj: Mapping[str, object], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise ValueError(f"key {key!r} must be a string, got {value!r}")
    return value


def _req_vec(obj: Mapping[str, object], key: str) -> tuple[float, float, float]:
    value = obj.get(key)
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"key {key!r} must be a 3-element array, got {value!r}")
    out: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError(f"key {key!r} must hold numbers, got {item!r}")
        out.append(float(item))
    return (out[0], out[1], out[2])
