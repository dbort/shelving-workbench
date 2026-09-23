"""Tests for rendering a ``ScanResult`` as text."""

from dataclasses import replace
from pathlib import Path

from freecad.Shelving.core.materials import Catalog, MaterialEntry, MaterialId
from freecad.Shelving.core.report import report
from freecad.Shelving.core.scan import Skipped, boxes_from_json, scan

PLY = MaterialId("ply18")
MDF = MaterialId("mdf12")
CATALOG = Catalog(
    entries={
        PLY: MaterialEntry(PLY, "ply 18", 18.0, "plywood"),
        MDF: MaterialEntry(MDF, "mdf 12", 12.0, "mdf"),
    }
)

FIXTURES = Path(__file__).parent / "fixtures"
REAL_STAIR_STEP = FIXTURES / "real_stair_step.boxes.json"
REAL_MAGICSTART_F1 = FIXTURES / "real_magicstart_f1.boxes.json"


def test_stair_step_report_shows_plane_facing_and_tree() -> None:
    boxes = boxes_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    result = scan(boxes, CATALOG)
    text = report(result)
    lines = text.splitlines()

    assert lines[0] == "depth axis x, size 292.1 x 1828.8 x 1498.6 mm"
    assert lines[1] == (
        "front at the minimum end of the depth axis (the members sit flush "
        "at one end and inset at the other, and the flush end is the rear)"
    )
    assert lines[2] == ""
    assert lines[3] == "division along z"
    assert "  division along y, 1480.34 mm (clear)" in lines
    # panelZX012 (330.2 mm) is shorter than its tallest neighbor panelZX008
    # (1480.3374 mm), so it is nested a level deeper, under its own void.
    assert "    division along z" in lines
    assert "      board panelZX012 (default material)" in lines
    assert "skipped" not in text


def test_magicstart_report_names_the_panel_evidence_and_insets() -> None:
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    result = scan(boxes, CATALOG)
    text = report(result)

    assert text.splitlines()[0] == "depth axis y, size 500 x 397 x 760 mm"
    assert "a back or front panel says so" in text
    assert "board Shelf (default material), insets x 1/1" in text
    assert "void, 100 mm (clear)" in text


def test_undetermined_facing_warns_left_and_right_are_a_coin_flip() -> None:
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    result = scan(boxes, CATALOG, front_at_min=None)
    # magicStart's overlay back infers a facing on its own; strip it back out
    # so the warning path is what's under test, not the inference.
    undetermined_unit = replace(result.unit, front_at_min=None)
    undetermined = replace(result, unit=undetermined_unit)
    text = report(undetermined)

    assert "WARNING: nothing says which side this unit faces" in text
    assert "coin flip" in text
    assert "the tree is correct either way" in text


def test_skipped_parts_render_as_a_block_with_reasons() -> None:
    boxes = boxes_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    result = scan(
        boxes,
        CATALOG,
        skipped=[
            Skipped(
                name="Pad001",
                label="Notch",
                type="PartDesign::Pad",
                reason="a box minus 1 rectangular cutout(s): 50 x 18 x 100 mm",
            )
        ],
    )
    text = report(result)

    assert "skipped (1):" in text
    assert (
        "Notch [PartDesign::Pad]: a box minus 1 rectangular cutout(s): 50 x 18 x 100 mm"
        in text
    )
