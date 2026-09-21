"""Scan axis-aligned boxes into a region-tree
:class:`~freecad.Shelving.core.layout.Unit`.

Real geometry, not stored intent: a FreeCAD export names solids and their
placements, and ``scan`` has to recover the same ``Unit`` shape
:mod:`freecad.Shelving.core.expand` would have produced from it, or refuse
and name what it could not read. There is no second tree type here: the
recursion builds ``Bay``, ``Void``, ``Division``, and ``Board`` directly,
because the region model can already express what a scan needs to say: an
enclosed compartment, a stepped outline's void, a run of boards and
sub-regions along one axis, and a board's own end clearances as ``Insets``.

The elevation plane is detected, not assumed: real units are modelled on
whichever plane suited the room, so the depth axis is taken to be the one
with the smallest bounding-box extent and can be overridden. A board thin
along the depth axis (a back or a front panel) projects over the whole
elevation rather than dividing it, and is set aside into
:attr:`ScanResult.panels` instead of placed: a back set within the carcass
and one sitting proud behind it need different trees, and scanning cannot
tell them apart from an axis-aligned box alone.

Scanning runs on a cell grid whose lines are every board edge. A flood fill
from the grid's border through uncovered cells marks the outside. At each
region the boards whose line across the region meets only themselves,
outside cells, or a clearance gap are the full-span cuts; the strips between
them are recursed into.
"""

from __future__ import annotations

import enum
import json
from collections import Counter, deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from freecad.Shelving.core.geometry import AxisIndex, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Insets,
    Item,
    Region,
    SizeRule,
    Unit,
    Void,
)
from freecad.Shelving.core.materials import Catalog, MaterialId

# Real geometry disagrees at joints by tens of microns: a unit exported from
# FreeCAD had four supposedly-coincident edges spread over 0.09 mm. The snap
# has to absorb that and stay far below any real feature size.
DEFAULT_SNAP_MM = 0.5
DEFAULT_CLEARANCE_MM = 3.0

_AXES: tuple[Axis, Axis, Axis] = (Axis.X, Axis.Y, Axis.Z)
_AXIS_INDICES: tuple[AxisIndex, AxisIndex, AxisIndex] = (0, 1, 2)


@dataclass(frozen=True)
class Box:
    """One axis-aligned solid to scan: a name, a minimum corner, an extent."""

    name: str
    corner_mm: Vec3
    size_mm: Vec3


@dataclass(frozen=True)
class Skipped:
    """A part the export could not read as a board.

    Carried through scanning rather than discarded. A dropped board does not
    make a unit fail, it makes it succeed with a hole: a real export lost a
    notched side panel and three enclosed bays were then reported as open to
    the outside, with nothing to signal it.
    """

    name: str
    label: str
    type: str
    reason: str


class ScanError(ValueError):
    """A refusal: ``objects`` names the boxes the diagnosis points at."""

    def __init__(self, message: str, objects: Iterable[str] = ()) -> None:
        super().__init__(message)
        self.objects: tuple[str, ...] = tuple(objects)


def boxes_from_json(text: str) -> list[Box]:
    """Parse the ``boxes`` half of the export format into ``Box`` records."""
    return _parse(text)[0]


def export_from_json(text: str) -> tuple[list[Box], list[Skipped]]:
    """Both halves of an export: the boxes, and the parts it could not read."""
    return _parse(text)


def _parse(text: str) -> tuple[list[Box], list[Skipped]]:
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("top-level JSON value must be an object")
    raw_boxes = parsed.get("boxes")
    if not isinstance(raw_boxes, list):
        raise ValueError("'boxes' must be an array")
    # A document Name identifies one object, so two entries sharing one are
    # the same board reached by two paths through the container tree.
    # Identical entries collapse; conflicting ones are a real error.
    by_name: dict[str, Box] = {}
    for entry in raw_boxes:
        if not isinstance(entry, dict):
            raise ValueError(f"box entry must be an object, got {entry!r}")
        box = Box(
            name=_req_str(entry, "name"),
            corner_mm=_req_vec(entry, "corner_mm"),
            size_mm=_req_vec(entry, "size_mm"),
        )
        seen = by_name.get(box.name)
        if seen is not None and seen != box:
            raise ValueError(
                f"two different boxes are both named {box.name!r}: "
                f"{seen.corner_mm}+{seen.size_mm} and "
                f"{box.corner_mm}+{box.size_mm}"
            )
        by_name[box.name] = box
    boxes = list(by_name.values())
    skipped: list[Skipped] = []
    for skip_entry in parsed.get("skipped") or []:
        if not isinstance(skip_entry, dict):
            continue
        skipped.append(
            Skipped(
                name=_req_str(skip_entry, "name"),
                label=str(skip_entry.get("label", "")),
                type=str(skip_entry.get("type", "")),
                reason=str(skip_entry.get("reason", "")),
            )
        )
    return boxes, skipped


def _req_str(obj: Mapping[str, object], key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise ValueError(f"key {key!r} must be a string, got {value!r}")
    return value


def _req_vec(obj: Mapping[str, object], key: str) -> Vec3:
    value = obj.get(key)
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"key {key!r} must be a 3-element array, got {value!r}")
    out: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int | float):
            raise ValueError(f"key {key!r} must hold numbers, got {item!r}")
        out.append(float(item))
    return Vec3(out[0], out[1], out[2])


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


def _span_mm(box: Box, axis_index: AxisIndex) -> tuple[float, float]:
    """``box``'s minimum and maximum extent along ``axis_index``."""
    lo_mm = _component_mm(box.corner_mm, axis_index)
    return lo_mm, lo_mm + _component_mm(box.size_mm, axis_index)


def _classify_thin_axis(box: Box) -> Axis:
    """The one axis ``box`` is thinnest along, or ``ScanError`` naming it.

    Every board has exactly one thin axis: two or three tied extents mean the
    box has no direction a reader would call "thickness", such as a square
    post, and the geometry cannot be read as a board.
    """
    sizes_mm = (box.size_mm.x_mm, box.size_mm.y_mm, box.size_mm.z_mm)
    if min(sizes_mm) <= 0:
        raise ScanError(
            f"{box.name}: every extent must be positive, got "
            f"{sizes_mm[0]:g} x {sizes_mm[1]:g} x {sizes_mm[2]:g}",
            (box.name,),
        )
    smallest_mm = min(sizes_mm)
    thin_axes = [index for index in range(3) if sizes_mm[index] == smallest_mm]
    if len(thin_axes) != 1:
        raise ScanError(
            f"{box.name}: no single thin axis (extents "
            f"{sizes_mm[0]:g} x {sizes_mm[1]:g} x {sizes_mm[2]:g})",
            (box.name,),
        )
    return _AXES[thin_axes[0]]


def detect_depth_axis(boxes: Sequence[Box]) -> Axis:
    """The elevation's depth axis: the bounding-box axis with the smallest span.

    A guess, not a measurement: a unit deeper than it is wide or tall would
    fool it. ``scan`` takes an explicit ``depth_axis`` for that case.
    """
    if not boxes:
        raise ScanError("no boxes to scan")

    def bounding_span_mm(axis_index: AxisIndex) -> float:
        spans_mm = [_span_mm(b, axis_index) for b in boxes]
        return max(hi_mm for _, hi_mm in spans_mm) - min(lo_mm for lo_mm, _ in spans_mm)

    depth_index = min(_AXIS_INDICES, key=bounding_span_mm)
    return _AXES[depth_index]


class FacingEvidence(enum.StrEnum):
    """What settled which way a unit faces."""

    # The caller said so, or a stored property did.
    GIVEN = "given"
    # A depth-thin board proud of the members: a door when stock-thickness, an
    # overlay back when much thinner, and those point opposite ways.
    PANEL = "panel"
    # The rear of a unit is almost always flush and the front may be inset
    # for looks, so the end the members sit flush with is the back.
    FLUSH_BACK = "flush_back"
    # Nothing distinguishes the two faces; the normal answer.
    NONE = "none"


def infer_facing(
    boxes: Sequence[Box], depth_axis: Axis, tol_mm: float = DEFAULT_SNAP_MM
) -> tuple[bool | None, FacingEvidence]:
    """Which end of ``depth_axis`` is the front, and what said so.

    ``True`` means the front is at the minimum end of ``depth_axis``,
    ``False`` the maximum, and ``None`` means undetermined, the normal
    answer for a plain rectangular box whose two faces are identical.

    Two signals, strongest first. A board thin through the depth settles it:
    one lying within the members is a back, and one lying proud of them is a
    door when it is stock-thickness and an overlay back when it is thin,
    which point opposite ways. Failing that, the rear of a unit is almost
    always flush against the wall while the front may be inset for looks, so
    the end the members sit flush with is the back.
    """
    depth_index = _axis_index(depth_axis)
    members: list[Box] = []
    panels: list[Box] = []
    thin_mm_by_name: dict[str, float] = {}
    for box in boxes:
        thin_axis = _classify_thin_axis(box)
        thin_mm_by_name[box.name] = _component_mm(box.size_mm, _axis_index(thin_axis))
        if thin_axis is depth_axis:
            panels.append(box)
        else:
            members.append(box)
    if not members:
        return None, FacingEvidence.NONE
    member_spans_mm = [_span_mm(b, depth_index) for b in members]
    lo_mm = min(member_lo_mm for member_lo_mm, _ in member_spans_mm)
    hi_mm = max(member_hi_mm for _, member_hi_mm in member_spans_mm)

    # A panel much thinner than the stock around it is backing material, not
    # a door. Without this a Woodworking cabinet's overlay back, which sits
    # proud behind the carcass, reads as a front and mirrors the whole
    # elevation.
    thin_stock_mm = _median(sorted(thin_mm_by_name[b.name] for b in members)) / 2.0
    votes = set[bool]()
    for box in panels:
        backing = thin_mm_by_name[box.name] < thin_stock_mm
        votes.add(_panel_vote(_span_mm(box, depth_index), lo_mm, hi_mm, backing))
    if len(votes) == 1:
        return votes.pop(), FacingEvidence.PANEL

    inset_at_min_mm = sum(member_lo_mm - lo_mm for member_lo_mm, _ in member_spans_mm)
    inset_at_max_mm = sum(hi_mm - member_hi_mm for _, member_hi_mm in member_spans_mm)
    if abs(inset_at_min_mm - inset_at_max_mm) <= tol_mm:
        return None, FacingEvidence.NONE
    # The flush end is the back, so the front is the end with more inset.
    return inset_at_min_mm > inset_at_max_mm, FacingEvidence.FLUSH_BACK


def _panel_vote(
    span_mm: tuple[float, float], lo_mm: float, hi_mm: float, backing: bool
) -> bool:
    """Whether this panel says the front is at the low end of ``depth_axis``.

    A panel proud of the members is a door when it is stock-thickness and an
    overlay back when it is thin, and those point opposite ways.
    """
    d0_mm, d1_mm = span_mm
    if d1_mm <= lo_mm:
        return not backing
    if d0_mm >= hi_mm:
        return backing
    # Set within the members: a back, so the front is the far end.
    return (d0_mm + d1_mm) / 2.0 > (lo_mm + hi_mm) / 2.0


def _median(sorted_values_mm: Sequence[float]) -> float:
    n = len(sorted_values_mm)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return sorted_values_mm[mid]
    return (sorted_values_mm[mid - 1] + sorted_values_mm[mid]) / 2.0


def _elevation_axes(depth_axis: Axis) -> tuple[Axis, Axis]:
    """The two axes the elevation is drawn on: horizontal across, vertical up.

    Vertical is Z unless Z is the depth axis, in which case Y stands in;
    horizontal is whichever axis is left. An arbitrary choice made only to
    keep a deterministic grid order; it has no effect on the scanned tree.
    """
    vertical = Axis.Z if depth_axis is not Axis.Z else Axis.Y
    horizontal = next(axis for axis in _AXES if axis not in (depth_axis, vertical))
    return horizontal, vertical


@dataclass(frozen=True)
class _Elevated:
    """A ``Box`` in elevation coordinates: ``h`` across, ``v`` up, ``d`` through."""

    name: str
    h0_mm: float
    h1_mm: float
    v0_mm: float
    v1_mm: float
    d0_mm: float
    d1_mm: float
    thin_axis: Axis
    thickness_mm: float


def _elevate(box: Box, horizontal: Axis, vertical: Axis, depth_axis: Axis) -> _Elevated:
    thin_axis = _classify_thin_axis(box)
    h0_mm, h1_mm = _span_mm(box, _axis_index(horizontal))
    v0_mm, v1_mm = _span_mm(box, _axis_index(vertical))
    d0_mm, d1_mm = _span_mm(box, _axis_index(depth_axis))
    thickness_mm = _component_mm(box.size_mm, _axis_index(thin_axis))
    return _Elevated(
        box.name, h0_mm, h1_mm, v0_mm, v1_mm, d0_mm, d1_mm, thin_axis, thickness_mm
    )


@dataclass(frozen=True)
class _ScanContext:
    """Everything the region recursion needs besides the grid itself."""

    horizontal: Axis
    vertical: Axis
    depth_axis: Axis
    depth_lo_mm: float
    depth_hi_mm: float
    clearance_mm: float
    snap_mm: float
    materials_by_name: Mapping[str, MaterialId]
    default_material: MaterialId


_EMPTY = -1


class _Grid:
    """Cell grid over the elevation. ``cover[j][i]`` is the member index at
    column ``i`` (across) and row ``j`` (up), or ``_EMPTY``; ``outside[j][i]``
    marks uncovered cells reachable from the border."""

    def __init__(self, members: Sequence[_Elevated], snap_mm: float) -> None:
        h_values_mm = [value_mm for p in members for value_mm in (p.h0_mm, p.h1_mm)]
        v_values_mm = [value_mm for p in members for value_mm in (p.v0_mm, p.v1_mm)]
        self.hs_mm = _snap_lines(h_values_mm, snap_mm)
        self.vs_mm = _snap_lines(v_values_mm, snap_mm)
        self.planks: list[_Elevated] = []
        self.cols: list[tuple[int, int]] = []
        self.rows: list[tuple[int, int]] = []
        nh = len(self.hs_mm) - 1
        nv = len(self.vs_mm) - 1
        self.cover: list[list[int]] = [[_EMPTY] * nh for _ in range(nv)]
        for index, plank in enumerate(members):
            i0 = _index_of(self.hs_mm, plank.h0_mm, snap_mm)
            i1 = _index_of(self.hs_mm, plank.h1_mm, snap_mm)
            j0 = _index_of(self.vs_mm, plank.v0_mm, snap_mm)
            j1 = _index_of(self.vs_mm, plank.v1_mm, snap_mm)
            if i0 == i1 or j0 == j1:
                raise ScanError(
                    f"{plank.name}: an extent collapses at the {snap_mm:g} mm snap "
                    "tolerance",
                    (plank.name,),
                )
            for j in range(j0, j1):
                for i in range(i0, i1):
                    other = self.cover[j][i]
                    if other != _EMPTY:
                        raise ScanError(
                            f"{plank.name} overlaps {self.planks[other].name}",
                            (plank.name, self.planks[other].name),
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


def _region(
    grid: _Grid, ctx: _ScanContext, i0: int, i1: int, j0: int, j1: int
) -> Region:
    """The region for one grid rectangle, cutting at every coordinate no
    member crosses.

    A guillotine cut is a line the geometry does not straddle, so the test is
    whether any member crosses it, not whether some one member spans the
    region. Cutting at a member's own two faces is then the special case
    where the resulting slab holds that member alone. Requiring a single
    spanning member instead refuses two abutting units, whose shared top is
    two boards that together span the width and neither of which spans
    alone.
    """
    inside = _contained(grid, i0, i1, j0, j1)
    if not inside:
        return _empty(grid, i0, i1, j0, j1)

    up = _clean_lines(
        grid, inside, j0, j1, ctx.vertical, across=False, clearance_mm=ctx.clearance_mm
    )
    across = _clean_lines(
        grid, inside, i0, i1, ctx.horizontal, across=True, clearance_mm=ctx.clearance_mm
    )
    # The finer partition wins, and a tie goes to stacking up the elevation,
    # which is how furniture is described. Either choice is a valid tree;
    # this only has to be deterministic.
    if up and len(up) >= len(across):
        axis, coords_mm, bounds = ctx.vertical, grid.vs_mm, [j0, *up, j1]
        raw = [
            _slab(grid, ctx, i0, i1, lo, hi, across=False)
            for lo, hi in zip(bounds[:-1], bounds[1:], strict=True)
        ]
    elif across:
        axis, coords_mm, bounds = ctx.horizontal, grid.hs_mm, [i0, *across, i1]
        raw = [
            _slab(grid, ctx, lo, hi, j0, j1, across=True)
            for lo, hi in zip(bounds[:-1], bounds[1:], strict=True)
        ]
    else:
        raise ScanError(
            f"no line crosses the region ({grid.hs_mm[i0]:g}, {grid.vs_mm[j0]:g})-"
            f"({grid.hs_mm[i1]:g}, {grid.vs_mm[j1]:g}) without cutting through a "
            "board; the layout is not a tree",
            (grid.planks[index].name for index in inside),
        )
    return Division(
        axis=axis, items=_finalize_items(raw, bounds, coords_mm, ctx.snap_mm)
    )


def _finalize_items(
    raw: Sequence[Item],
    bounds: Sequence[int],
    coords_mm: Sequence[float],
    snap_mm: float,
) -> list[Item]:
    """``raw`` with each non-``Board`` item's ``rule`` set by the
    equal-siblings heuristic, sized from its span in ``bounds``/``coords_mm``.

    A ``Board``'s size along its division's axis is its own thickness, never
    a rule, so it is excluded from the sibling comparison: two boards
    happening to be the same thickness as some region must not make that
    region ``Fill``.
    """
    region_positions = [i for i, item in enumerate(raw) if not isinstance(item, Board)]
    region_sizes_mm = [
        coords_mm[bounds[i + 1]] - coords_mm[bounds[i]] for i in region_positions
    ]
    rules = _recover_rules(region_sizes_mm, snap_mm)
    items = list(raw)
    for position, rule in zip(region_positions, rules, strict=True):
        region_item = items[position]
        assert isinstance(region_item, Bay | Void | Division)
        region_item.rule = rule
    return items


def _slab(
    grid: _Grid, ctx: _ScanContext, i0: int, i1: int, j0: int, j1: int, *, across: bool
) -> Item:
    """One slab between consecutive clean lines: a board, or a subtree.

    A slab holding one board that reaches across it is a ``Board`` item, with
    whatever is left beside it recorded as its cross-axis ``Insets``.
    """
    inside = _contained(grid, i0, i1, j0, j1)
    if len(inside) != 1:
        return _region(grid, ctx, i0, i1, j0, j1)
    index = inside[0]
    plank = grid.planks[index]
    pi0, pi1 = grid.cols[index]
    pj0, pj1 = grid.rows[index]
    if across:
        low_mm = _gap(
            grid,
            range(pj0 - 1, j0 - 1, -1),
            range(pi0, pi1),
            grid.vs_mm,
            horizontal=False,
        )
        high_mm = _gap(
            grid, range(pj1, j1), range(pi0, pi1), grid.vs_mm, horizontal=False
        )
        cross_axis = ctx.vertical
    else:
        low_mm = _gap(
            grid,
            range(pi0 - 1, i0 - 1, -1),
            range(pj0, pj1),
            grid.hs_mm,
            horizontal=True,
        )
        high_mm = _gap(
            grid, range(pi1, i1), range(pj0, pj1), grid.hs_mm, horizontal=True
        )
        cross_axis = ctx.horizontal
    if (
        low_mm is None
        or high_mm is None
        or low_mm > ctx.clearance_mm
        or high_mm > ctx.clearance_mm
    ):
        # It sits alone in the slab but does not reach across it, so the slab
        # divides again along the other axis and the board spans whatever is
        # left. Refusing here would reject a shelf that fills its own column
        # but not the full height of the region the column was cut from.
        return _region(grid, ctx, i0, i1, j0, j1)
    return _make_board(plank, cross_axis, low_mm, high_mm, ctx)


def _make_board(
    plank: _Elevated, cross_axis: Axis, low_mm: float, high_mm: float, ctx: _ScanContext
) -> Board:
    insets_kwargs: dict[str, float] = {}
    _set_axis_pair(insets_kwargs, cross_axis, low_mm, high_mm)
    _set_axis_pair(
        insets_kwargs,
        ctx.depth_axis,
        plank.d0_mm - ctx.depth_lo_mm,
        ctx.depth_hi_mm - plank.d1_mm,
    )
    material = ctx.materials_by_name[plank.name]
    return Board(
        material=None if material == ctx.default_material else material,
        insets=Insets(**insets_kwargs),
        role=plank.name,
    )


def _set_axis_pair(
    kwargs: dict[str, float], axis: Axis, lo_mm: float, hi_mm: float
) -> None:
    match axis:
        case Axis.X:
            kwargs["x_min_mm"] = lo_mm
            kwargs["x_max_mm"] = hi_mm
        case Axis.Y:
            kwargs["y_min_mm"] = lo_mm
            kwargs["y_max_mm"] = hi_mm
        case Axis.Z:
            kwargs["z_min_mm"] = lo_mm
            kwargs["z_max_mm"] = hi_mm


def _gap(
    grid: _Grid,
    along: range,
    across: range,
    lines_mm: Sequence[float],
    *,
    horizontal: bool,
) -> float | None:
    """Enclosed gap width walking ``along`` from a board's end toward the
    region edge, or ``None`` when another board blocks the line. Outside
    cells cost nothing; enclosed uncovered cells add their width."""
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
            gap_mm += lines_mm[a + 1] - lines_mm[a]
    return gap_mm


def _empty(grid: _Grid, i0: int, i1: int, j0: int, j1: int) -> Region:
    cells = [(i, j) for j in range(j0, j1) for i in range(i0, i1)]
    outside_count = sum(1 for i, j in cells if grid.outside[j][i])
    if outside_count == len(cells):
        return Void()
    if outside_count == 0:
        return Bay()
    raise ScanError(
        f"the empty region ({grid.hs_mm[i0]:g}, {grid.vs_mm[j0]:g})-"
        f"({grid.hs_mm[i1]:g}, {grid.vs_mm[j1]:g}) is partly enclosed and partly open "
        "to the outside; the outline is not a tree"
    )


def _clean_lines(
    grid: _Grid,
    inside: Sequence[int],
    lo: int,
    hi: int,
    preferred_thin_axis: Axis,
    *,
    across: bool,
    clearance_mm: float,
) -> list[int]:
    """Interior grid lines that a board in this region ends on and none crosses.

    Three filters. A line no board ends on separates nothing, and the grid is
    global, so without that test a neighbouring unit's shelf heights would
    slice this region's empty space into a dozen meaningless slabs. A line no
    board straddles is the guillotine condition itself. And lines closer
    together than the clearance are one joint, not a compartment, so only one
    of them survives: the face of a board thin along the cut axis, which is
    ``preferred_thin_axis``. Without that last rule a shelf held a
    millimetre off each side turns its two joint gaps into two one
    millimetre bays.
    """
    spans = [grid.cols[i] if across else grid.rows[i] for i in inside]
    faces = {edge for span in spans for edge in span}
    preferred = {
        edge
        for index in inside
        if grid.planks[index].thin_axis is preferred_thin_axis
        for edge in (grid.cols[index] if across else grid.rows[index])
    }
    coords_mm = grid.hs_mm if across else grid.vs_mm
    kept: list[int] = []
    for line in range(lo + 1, hi):
        if line not in faces or any(a < line < b for a, b in spans):
            continue
        if kept and coords_mm[line] - coords_mm[kept[-1]] <= clearance_mm:
            if line in preferred and kept[-1] not in preferred:
                kept[-1] = line
            continue
        if coords_mm[line] - coords_mm[lo] <= clearance_mm:
            continue
        if coords_mm[hi] - coords_mm[line] <= clearance_mm:
            continue
        kept.append(line)
    return kept


def _contained(grid: _Grid, i0: int, i1: int, j0: int, j1: int) -> list[int]:
    """Indices of the boards lying inside the region; a straddler is refused."""
    found: list[int] = []
    for index, ((pi0, pi1), (pj0, pj1)) in enumerate(
        zip(grid.cols, grid.rows, strict=True)
    ):
        if not (pi0 < i1 and pi1 > i0 and pj0 < j1 and pj1 > j0):
            continue
        if not (pi0 >= i0 and pi1 <= i1 and pj0 >= j0 and pj1 <= j1):
            raise ScanError(
                f"{grid.planks[index].name} crosses the boundary of the bay it lies in",
                (grid.planks[index].name,),
            )
        found.append(index)
    return found


def _has_bay(region: Region) -> bool:
    if isinstance(region, Bay):
        return True
    if isinstance(region, Division):
        return any(
            _has_bay(item) for item in region.items if not isinstance(item, Board)
        )
    return False


def _snap_lines(values_mm: Iterable[float], snap_mm: float) -> list[float]:
    """Sorted grid lines: each cluster of values within ``snap_mm`` of its own
    first member collapses to one line at the cluster's midpoint.

    Measuring from the cluster start rather than the previous value stops a
    run of small steps from chaining into one wide cluster, and stops four
    edges that should coincide from splitting because the outermost pair is a
    hair over the tolerance.
    """
    lines_mm: list[float] = []
    cluster_mm: list[float] = []
    for value_mm in sorted(values_mm):
        if cluster_mm and value_mm - cluster_mm[0] > snap_mm:
            lines_mm.append((cluster_mm[0] + cluster_mm[-1]) / 2.0)
            cluster_mm = []
        cluster_mm.append(value_mm)
    if cluster_mm:
        lines_mm.append((cluster_mm[0] + cluster_mm[-1]) / 2.0)
    return lines_mm


def _index_of(lines_mm: Sequence[float], value_mm: float, snap_mm: float) -> int:
    """Index of the grid line ``value_mm`` snapped to; the nearest one, since a
    cluster midpoint can sit up to half the tolerance from any member."""
    best = min(range(len(lines_mm)), key=lambda index: abs(lines_mm[index] - value_mm))
    if abs(lines_mm[best] - value_mm) > snap_mm:
        raise AssertionError(f"{value_mm} is not on the grid")
    return best


def _recover_rules(sizes_mm: Sequence[float], snap_mm: float) -> list[SizeRule]:
    """``Fill`` for every size another sibling matches within ``snap_mm``,
    ``Fixed(size, Basis.CLEAR)`` otherwise.

    A basis is not recoverable from geometry: a clear opening and a shelf
    spacing quoted face to face place the boards identically, so every
    recovered ``Fixed`` gets ``Basis.CLEAR``.
    """
    rules: list[SizeRule] = []
    for i, size_mm in enumerate(sizes_mm):
        has_twin = any(
            j != i and abs(other - size_mm) <= snap_mm
            for j, other in enumerate(sizes_mm)
        )
        rules.append(Fill() if has_twin else Fixed(size_mm=size_mm, basis=Basis.CLEAR))
    return rules


def _material_for_thickness_mm(
    catalog: Catalog, thickness_mm: float, snap_mm: float, board_name: str
) -> MaterialId:
    for entry in catalog:
        if abs(entry.thickness_mm - thickness_mm) <= snap_mm:
            return entry.id
    raise ScanError(
        f"{board_name}: no material has thickness {thickness_mm:g} mm", (board_name,)
    )


def _resolve_materials(
    catalog: Catalog, elevated: Sequence[_Elevated], snap_mm: float
) -> dict[str, MaterialId]:
    return {
        p.name: _material_for_thickness_mm(catalog, p.thickness_mm, snap_mm, p.name)
        for p in elevated
    }


def _default_material(materials_by_name: Mapping[str, MaterialId]) -> MaterialId:
    """The material the most boards resolved to: the catalog entry a scanned
    unit's ``default_material`` should be, since most boards inherit it."""
    return Counter(materials_by_name.values()).most_common(1)[0][0]


def _unit_size_mm(
    horizontal: Axis,
    vertical: Axis,
    depth_axis: Axis,
    h_mm: float,
    v_mm: float,
    d_mm: float,
) -> Vec3:
    extent_mm_by_axis = {horizontal: h_mm, vertical: v_mm, depth_axis: d_mm}
    return Vec3(
        extent_mm_by_axis[Axis.X], extent_mm_by_axis[Axis.Y], extent_mm_by_axis[Axis.Z]
    )


@dataclass(frozen=True)
class ScanResult:
    """Everything a scan produced: the ``Unit`` it could build, plus what it
    could not place and what it could not read at all."""

    unit: Unit
    # Boards thin through the depth axis, set aside rather than placed: see
    # the module docstring for why a back or a front cannot be placed safely.
    panels: tuple[Box, ...]
    # Parts the caller already knew it could not read, carried through
    # rather than dropped so a missing board is visible in the result.
    skipped: tuple[Skipped, ...]
    facing_evidence: FacingEvidence
    thicknesses_mm: frozenset[float]


def scan(
    boxes: Sequence[Box],
    catalog: Catalog,
    *,
    snap_mm: float = DEFAULT_SNAP_MM,
    clearance_mm: float = DEFAULT_CLEARANCE_MM,
    depth_axis: Axis | None = None,
    front_at_min: bool | None = None,
    skipped: Sequence[Skipped] = (),
) -> ScanResult:
    """The :class:`ScanResult` read from ``boxes``, or ``ScanError`` naming
    the offenders.

    ``depth_axis`` defaults to :func:`detect_depth_axis`; ``front_at_min``
    defaults to :func:`infer_facing`. Edges within ``snap_mm`` of each other
    are one grid line, and a board end may stop up to ``clearance_mm`` short
    of the region edge it spans to without breaking the region into two.
    """
    if not boxes:
        raise ScanError("no boxes to scan")
    if depth_axis is None:
        depth_axis = detect_depth_axis(boxes)
    facing_evidence: FacingEvidence
    if front_at_min is None:
        front_at_min, facing_evidence = infer_facing(boxes, depth_axis, snap_mm)
    else:
        facing_evidence = FacingEvidence.GIVEN

    horizontal, vertical = _elevation_axes(depth_axis)
    panels: list[Box] = []
    members: list[Box] = []
    for box in boxes:
        thin_axis = _classify_thin_axis(box)
        (panels if thin_axis is depth_axis else members).append(box)
    if not members:
        raise ScanError(
            f"every box is thin through the depth axis ({depth_axis.value}); nothing "
            "forms an elevation",
            (b.name for b in boxes),
        )

    elevated = [_elevate(b, horizontal, vertical, depth_axis) for b in members]
    materials_by_name = _resolve_materials(catalog, elevated, snap_mm)
    default_material = _default_material(materials_by_name)

    grid = _Grid(elevated, snap_mm)
    depth_lo_mm = min(p.d0_mm for p in elevated)
    depth_hi_mm = max(p.d1_mm for p in elevated)
    ctx = _ScanContext(
        horizontal=horizontal,
        vertical=vertical,
        depth_axis=depth_axis,
        depth_lo_mm=depth_lo_mm,
        depth_hi_mm=depth_hi_mm,
        clearance_mm=clearance_mm,
        snap_mm=snap_mm,
        materials_by_name=materials_by_name,
        default_material=default_material,
    )
    root = _region(grid, ctx, 0, len(grid.hs_mm) - 1, 0, len(grid.vs_mm) - 1)
    if not _has_bay(root):
        raise ScanError(
            "no enclosed bay: the outside reaches every void, so the shell has a gap "
            "wider than the clearance tolerance"
        )

    unit = Unit(
        size_mm=_unit_size_mm(
            horizontal,
            vertical,
            depth_axis,
            grid.hs_mm[-1] - grid.hs_mm[0],
            grid.vs_mm[-1] - grid.vs_mm[0],
            depth_hi_mm - depth_lo_mm,
        ),
        default_material=default_material,
        root=root,
        depth_axis=depth_axis,
        front_at_min=front_at_min,
    )
    return ScanResult(
        unit=unit,
        panels=tuple(panels),
        skipped=tuple(skipped),
        facing_evidence=facing_evidence,
        thicknesses_mm=frozenset(round(p.thickness_mm, 4) for p in elevated),
    )
