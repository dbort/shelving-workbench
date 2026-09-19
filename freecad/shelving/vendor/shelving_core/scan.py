"""Scan axis-aligned boxes into a region-tree :class:`~shelving_core.layout.Unit`.

Real geometry, not stored intent: a FreeCAD export names solids and their
placements, and ``scan`` has to recover the same ``Unit`` shape
:mod:`shelving_core.expand` would have produced from it, or refuse and name
what it could not read. There is no second tree type here — the recursion
builds ``Bay``, ``Void``, ``Division``, and ``Board`` directly — because the
region model can already express what a scan needs to say: an enclosed
compartment, a stepped outline's void, a run of boards and sub-regions along
one axis, and a board's own end clearances as ``Insets``.

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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from .geometry import AxisIndex, Vec3
from .layout import Axis

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
    sizes = (box.size_mm.x_mm, box.size_mm.y_mm, box.size_mm.z_mm)
    if min(sizes) <= 0:
        raise ScanError(
            f"{box.name}: every extent must be positive, got "
            f"{sizes[0]:g} x {sizes[1]:g} x {sizes[2]:g}",
            (box.name,),
        )
    smallest = min(sizes)
    thin_axes = [index for index in range(3) if sizes[index] == smallest]
    if len(thin_axes) != 1:
        raise ScanError(
            f"{box.name}: no single thin axis (extents "
            f"{sizes[0]:g} x {sizes[1]:g} x {sizes[2]:g})",
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
        spans = [_span_mm(b, axis_index) for b in boxes]
        return max(hi for _, hi in spans) - min(lo for lo, _ in spans)

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
    lo_mm = min(lo for lo, _ in member_spans_mm)
    hi_mm = max(hi for _, hi in member_spans_mm)

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

    inset_at_min_mm = sum(lo - lo_mm for lo, _ in member_spans_mm)
    inset_at_max_mm = sum(hi_mm - hi for _, hi in member_spans_mm)
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


def _median(sorted_values: Sequence[float]) -> float:
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2:
        return sorted_values[mid]
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0
