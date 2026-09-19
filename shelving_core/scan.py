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

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .geometry import Vec3

# Real geometry disagrees at joints by tens of microns: a unit exported from
# FreeCAD had four supposedly-coincident edges spread over 0.09 mm. The snap
# has to absorb that and stay far below any real feature size.
DEFAULT_SNAP_MM = 0.5
DEFAULT_CLEARANCE_MM = 3.0


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
