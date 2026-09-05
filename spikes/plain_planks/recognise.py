"""Plain-planks spike: recognise a cut tree from axis-aligned boxes.

Throwaway code that proves the recognition rule described in
``docs/parametric-model-evaluation.md`` against the core's ``expand`` as the
oracle. Nothing in the workbench imports it.

Coordinates follow the core: X right (width), Y back (depth), Z up (height),
millimetres. A box is a plank when it is thin along X or Z; a box thin along
Y (a back or front panel) projects over the whole elevation and is set aside.

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

DEFAULT_SNAP_MM = 0.05
DEFAULT_CLEARANCE_MM = 3.0


class ThinAxis(enum.StrEnum):
    X = "x"
    Y = "y"
    Z = "z"


@dataclass(frozen=True)
class Box:
    """One axis-aligned solid: minimum corner and extent, millimetres."""

    name: str
    corner_mm: tuple[float, float, float]
    size_mm: tuple[float, float, float]


@dataclass(frozen=True)
class Plank:
    """A box with its edges snapped to the grid and its thin axis classified."""

    name: str
    x0_mm: float
    x1_mm: float
    y0_mm: float
    y1_mm: float
    z0_mm: float
    z1_mm: float
    thin: ThinAxis

    @property
    def thickness_mm(self) -> float:
        match self.thin:
            case ThinAxis.X:
                return self.x1_mm - self.x0_mm
            case ThinAxis.Y:
                return self.y1_mm - self.y0_mm
            case ThinAxis.Z:
                return self.z1_mm - self.z0_mm


class RecogniseError(ValueError):
    """A refusal: ``objects`` names the boxes the diagnosis points at."""

    def __init__(self, message: str, objects: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.objects = tuple(objects)


@dataclass(frozen=True)
class Rect:
    x0_mm: float
    x1_mm: float
    z0_mm: float
    z1_mm: float

    @property
    def width_mm(self) -> float:
        return self.x1_mm - self.x0_mm

    @property
    def height_mm(self) -> float:
        return self.z1_mm - self.z0_mm


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
    appears. ``orientation`` follows the core: ``HORIZONTAL`` cuts are Z-thin
    planks stacked along Z.
    """

    orientation: Orientation
    rect: Rect
    cuts: tuple[Cut, ...]
    strips: tuple["Node | None", ...]


Node = Open | Outside | CutSplit


@dataclass(frozen=True)
class Recognised:
    bbox: Rect
    y0_mm: float
    depth_mm: float
    root: Node
    panels: tuple[Plank, ...]


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


def recognise(
    boxes: Sequence[Box],
    snap_mm: float = DEFAULT_SNAP_MM,
    clearance_mm: float = DEFAULT_CLEARANCE_MM,
) -> Recognised:
    """The cut tree of ``boxes``, or ``RecogniseError`` naming the offenders.

    Edges closer than ``snap_mm`` are one grid line. A plank end may stop up
    to ``clearance_mm`` short of the region edge it spans to; the gap is
    recorded on the ``Cut``.
    """
    if not boxes:
        raise RecogniseError("no boxes to recognise")
    planks = [_classify(box) for box in boxes]
    panels = tuple(p for p in planks if p.thin is ThinAxis.Y)
    members = [p for p in planks if p.thin is not ThinAxis.Y]
    if not members:
        raise RecogniseError(
            "every box is thin along Y; nothing forms an elevation",
            (p.name for p in planks),
        )
    grid = _Grid(members, snap_mm)
    bbox = Rect(grid.xs[0], grid.xs[-1], grid.zs[0], grid.zs[-1])
    y0_mm = min(p.y0_mm for p in members)
    y1_mm = max(p.y1_mm for p in members)
    root = _region(grid, 0, len(grid.xs) - 1, 0, len(grid.zs) - 1, clearance_mm)
    if not _has_open(root):
        raise RecogniseError(
            "no enclosed bay: the outside reaches every void, so the shell has "
            "a gap wider than the clearance tolerance"
        )
    return Recognised(
        bbox=bbox, y0_mm=y0_mm, depth_mm=y1_mm - y0_mm, root=root, panels=panels
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


def thicknesses(rec: Recognised) -> set[float]:
    """Every distinct plank thickness in the cut tree, for building a catalog."""
    found: set[float] = set()

    def walk(node: Node | None) -> None:
        if isinstance(node, CutSplit):
            for cut in node.cuts:
                found.add(cut.plank.thickness_mm)
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


def _classify(box: Box) -> Plank:
    sx, sy, sz = box.size_mm
    if min(sx, sy, sz) <= 0:
        raise RecogniseError(f"{box.name}: every extent must be positive", (box.name,))
    smallest = min(sx, sy, sz)
    thin_axes = [
        axis
        for axis, extent in ((ThinAxis.X, sx), (ThinAxis.Y, sy), (ThinAxis.Z, sz))
        if extent == smallest
    ]
    if len(thin_axes) != 1:
        raise RecogniseError(
            f"{box.name}: no single thin axis (extents {sx:g} x {sy:g} x {sz:g})",
            (box.name,),
        )
    cx, cy, cz = box.corner_mm
    return Plank(
        name=box.name,
        x0_mm=cx,
        x1_mm=cx + sx,
        y0_mm=cy,
        y1_mm=cy + sy,
        z0_mm=cz,
        z1_mm=cz + sz,
        thin=thin_axes[0],
    )


_EMPTY = -1


class _Grid:
    """Cell grid over the elevation. ``cover[j][i]`` is the plank index at
    column ``i`` (X) and row ``j`` (Z), or ``_EMPTY``; ``outside[j][i]`` marks
    uncovered cells reachable from the border."""

    def __init__(self, planks: Sequence[Plank], snap_mm: float) -> None:
        self.xs = _snap_lines([v for p in planks for v in (p.x0_mm, p.x1_mm)], snap_mm)
        self.zs = _snap_lines([v for p in planks for v in (p.z0_mm, p.z1_mm)], snap_mm)
        self.planks: list[Plank] = []
        self.cols: list[tuple[int, int]] = []
        self.rows: list[tuple[int, int]] = []
        nx = len(self.xs) - 1
        nz = len(self.zs) - 1
        self.cover = [[_EMPTY] * nx for _ in range(nz)]
        for index, plank in enumerate(planks):
            i0 = _index_of(self.xs, plank.x0_mm, snap_mm)
            i1 = _index_of(self.xs, plank.x1_mm, snap_mm)
            j0 = _index_of(self.zs, plank.z0_mm, snap_mm)
            j1 = _index_of(self.zs, plank.z1_mm, snap_mm)
            if i0 == i1 or j0 == j1:
                raise RecogniseError(
                    f"{plank.name}: an extent is below the snap tolerance",
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
            self.planks.append(
                Plank(
                    name=plank.name,
                    x0_mm=self.xs[i0],
                    x1_mm=self.xs[i1],
                    y0_mm=plank.y0_mm,
                    y1_mm=plank.y1_mm,
                    z0_mm=self.zs[j0],
                    z1_mm=self.zs[j1],
                    thin=plank.thin,
                )
            )
            self.cols.append((i0, i1))
            self.rows.append((j0, j1))
        self.outside = self._flood_outside(nx, nz)

    def _flood_outside(self, nx: int, nz: int) -> list[list[bool]]:
        outside = [[False] * nx for _ in range(nz)]
        queue: deque[tuple[int, int]] = deque()
        for j in range(nz):
            for i in range(nx):
                on_border = i == 0 or j == 0 or i == nx - 1 or j == nz - 1
                if on_border and self.cover[j][i] == _EMPTY:
                    outside[j][i] = True
                    queue.append((i, j))
        while queue:
            i, j = queue.popleft()
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ni, nj = i + di, j + dj
                if 0 <= ni < nx and 0 <= nj < nz:
                    if not outside[nj][ni] and self.cover[nj][ni] == _EMPTY:
                        outside[nj][ni] = True
                        queue.append((ni, nj))
        return outside

    def rect(self, i0: int, i1: int, j0: int, j1: int) -> Rect:
        return Rect(self.xs[i0], self.xs[i1], self.zs[j0], self.zs[j1])


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
        if grid.planks[index].thin is ThinAxis.Z
        and (cut := _horizontal_cut(grid, index, i0, i1, clearance_mm)) is not None
    ]
    v_cuts = [
        cut
        for index in inside
        if grid.planks[index].thin is ThinAxis.X
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
        h_cuts.sort(key=lambda c: c.plank.z0_mm)
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
    v_cuts.sort(key=lambda c: c.plank.x0_mm)
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
    lo = _gap(grid, range(pi0 - 1, i0 - 1, -1), range(pj0, pj1), grid.xs, True)
    hi = _gap(grid, range(pi1, i1), range(pj0, pj1), grid.xs, True)
    if lo is None or hi is None or lo > clearance_mm or hi > clearance_mm:
        return None
    return Cut(grid.planks[index], lo, hi)


def _vertical_cut(
    grid: _Grid, index: int, j0: int, j1: int, clearance_mm: float
) -> Cut | None:
    pi0, pi1 = grid.cols[index]
    pj0, pj1 = grid.rows[index]
    lo = _gap(grid, range(pj0 - 1, j0 - 1, -1), range(pi0, pi1), grid.zs, False)
    hi = _gap(grid, range(pj1, j1), range(pi0, pi1), grid.zs, False)
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
    """Sorted distinct grid lines, merging values closer than ``snap_mm``."""
    lines: list[float] = []
    for value in sorted(values):
        if lines and value - lines[-1] <= snap_mm:
            continue
        lines.append(value)
    return lines


def _index_of(lines: Sequence[float], value: float, snap_mm: float) -> int:
    for index, line in enumerate(lines):
        if abs(line - value) <= snap_mm:
            return index
    raise AssertionError(f"{value} is not on the grid")


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
