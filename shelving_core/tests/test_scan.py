"""Tests for scanning axis-aligned boxes into a region-tree ``Unit``."""

import dataclasses
import json
from pathlib import Path

import pytest

from shelving_core.geometry import Vec3
from shelving_core.layout import Axis
from shelving_core.scan import (
    Box,
    FacingEvidence,
    ScanError,
    Skipped,
    boxes_from_json,
    detect_depth_axis,
    export_from_json,
    infer_facing,
)

FIXTURES = Path(__file__).parent / "fixtures"

REAL_STAIR_STEP = FIXTURES / "real_stair_step.boxes.json"
REAL_TWO_UNITS = FIXTURES / "real_two_units.boxes.json"
REAL_MAGICSTART_F1 = FIXTURES / "real_magicstart_f1.boxes.json"


def _box_json(
    name: str, corner: tuple[float, float, float], size: tuple[float, float, float]
) -> dict[str, object]:
    return {"name": name, "corner_mm": list(corner), "size_mm": list(size)}


def test_boxes_from_json_parses_real_stair_step() -> None:
    boxes = boxes_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    assert len(boxes) == 10
    assert all(isinstance(b, Box) for b in boxes)


def test_boxes_from_json_parses_real_magicstart_f1() -> None:
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    assert len(boxes) == 6


def test_boxes_from_json_parses_real_two_units() -> None:
    # 39 raw entries collapse to 28 distinct boxes; see the duplicate-collapse
    # test below for the reason.
    boxes = boxes_from_json(REAL_TWO_UNITS.read_text(encoding="utf-8"))
    assert len(boxes) == 28


def test_duplicate_entries_collapse_on_real_two_units() -> None:
    """39 raw entries collapse to 28 distinct boxes: a selection can reach one
    object by more than one path through the container tree."""
    text = REAL_TWO_UNITS.read_text(encoding="utf-8")
    assert len(json.loads(text)["boxes"]) == 39
    assert len(boxes_from_json(text)) == 28


def test_export_from_json_carries_skipped_parts() -> None:
    boxes, skipped = export_from_json(REAL_TWO_UNITS.read_text(encoding="utf-8"))
    assert len(boxes) == 28
    assert [s.name for s in skipped] == ["Sketch006", "Pad003"]
    assert all(isinstance(s, Skipped) for s in skipped)


def test_conflicting_duplicate_names_raise() -> None:
    clashing = json.dumps(
        {
            "boxes": [
                _box_json("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
                _box_json("Shelf", (9.0, 9.0, 9.0), (1.0, 1.0, 1.0)),
            ]
        }
    )
    with pytest.raises(ValueError, match="both named 'Shelf'"):
        boxes_from_json(clashing)


def test_identical_duplicate_names_collapse() -> None:
    identical = json.dumps(
        {
            "boxes": [
                _box_json("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
                _box_json("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
            ]
        }
    )
    assert len(boxes_from_json(identical)) == 1


def test_scan_error_carries_offending_object_names() -> None:
    err = ScanError("two boards overlap", ["A", "B"])
    assert err.objects == ("A", "B")


def _uniform_depth_boxes() -> list[Box]:
    """A closed rectangle with every member the same depth: no panels, no
    inset difference, so nothing distinguishes the two faces."""
    return [
        _box("Left", (0.0, 0.0, 0.0), (18.0, 300.0, 600.0)),
        _box("Right", (582.0, 0.0, 0.0), (18.0, 300.0, 600.0)),
        _box("Bottom", (0.0, 0.0, 0.0), (600.0, 300.0, 18.0)),
        _box("Top", (0.0, 0.0, 582.0), (600.0, 300.0, 18.0)),
    ]


def _box(
    name: str, corner: tuple[float, float, float], size: tuple[float, float, float]
) -> Box:
    return Box(name=name, corner_mm=Vec3(*corner), size_mm=Vec3(*size))


def test_detect_depth_axis_picks_the_smallest_bounding_box_extent() -> None:
    assert detect_depth_axis(_uniform_depth_boxes()) is Axis.Y


def test_uniform_depth_leaves_facing_undetermined() -> None:
    boxes = _uniform_depth_boxes()
    front_at_min, evidence = infer_facing(boxes, detect_depth_axis(boxes))
    assert front_at_min is None
    assert evidence is FacingEvidence.NONE


def test_magicstart_fixture_infers_front_at_min_from_its_overlay_back() -> None:
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    depth_axis = detect_depth_axis(boxes)
    assert depth_axis is Axis.Y
    front_at_min, evidence = infer_facing(boxes, depth_axis)
    assert front_at_min is True
    assert evidence is FacingEvidence.PANEL


def test_stock_thickness_back_flips_the_magicstart_facing() -> None:
    """The same panel at stock thickness reads as a door, which faces the
    opposite way from an overlay back."""
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    doored = [
        dataclasses.replace(b, size_mm=Vec3(b.size_mm.x_mm, 18.0, b.size_mm.z_mm))
        if b.name == "Back"
        else b
        for b in boxes
    ]
    front_at_min, evidence = infer_facing(doored, detect_depth_axis(doored))
    assert front_at_min is False
    assert evidence is FacingEvidence.PANEL


def test_stair_step_fixture_infers_facing_from_the_inset() -> None:
    boxes = boxes_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    depth_axis = detect_depth_axis(boxes)
    assert depth_axis is Axis.X
    front_at_min, evidence = infer_facing(boxes, depth_axis)
    assert front_at_min is True
    assert evidence is FacingEvidence.FLUSH_BACK
