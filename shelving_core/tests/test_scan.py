"""Tests for scanning axis-aligned boxes into a region-tree ``Unit``."""

import json
from pathlib import Path

import pytest

from shelving_core.scan import (
    Box,
    ScanError,
    Skipped,
    boxes_from_json,
    export_from_json,
)

FIXTURES = Path(__file__).parent / "fixtures"

REAL_STAIR_STEP = FIXTURES / "real_stair_step.boxes.json"
REAL_TWO_UNITS = FIXTURES / "real_two_units.boxes.json"
REAL_MAGICSTART_F1 = FIXTURES / "real_magicstart_f1.boxes.json"


def _box(
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
                _box("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
                _box("Shelf", (9.0, 9.0, 9.0), (1.0, 1.0, 1.0)),
            ]
        }
    )
    with pytest.raises(ValueError, match="both named 'Shelf'"):
        boxes_from_json(clashing)


def test_identical_duplicate_names_collapse() -> None:
    identical = json.dumps(
        {
            "boxes": [
                _box("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
                _box("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
            ]
        }
    )
    assert len(boxes_from_json(identical)) == 1


def test_scan_error_carries_offending_object_names() -> None:
    err = ScanError("two boards overlap", ["A", "B"])
    assert err.objects == ("A", "B")
