"""Print what the recogniser makes of a document exported by ``export_boxes.py``.

    pixi run -- python -m spikes.plain_planks.report Unit.boxes.json [min|max]

Prints the cut tree, or the refusal and the objects it names. Use it to feed
real GUI-modelled geometry to the recogniser without a FreeCAD round trip.

The optional second argument says which end of the depth axis is the front,
when the geometry does not (a unit with no back and no front). It changes no
sizes, only which end of the elevation is called left.
"""

from __future__ import annotations

import sys
from pathlib import Path

from spikes.plain_planks.recognise import (
    _AXIS_NAMES,
    FacingEvidence,
    Node,
    Open,
    Outside,
    Recognised,
    RecogniseError,
    boxes_from_json,
    detect_axes,
    recognise,
    thicknesses,
)


def _render(node: Node | None, indent: str = "") -> list[str]:
    if node is None:
        return [f"{indent}(no gap)"]
    if isinstance(node, Open):
        return [f"{indent}open bay {node.rect.width_mm:g} x {node.rect.height_mm:g} mm"]
    if isinstance(node, Outside):
        return [f"{indent}outside {node.rect.width_mm:g} x {node.rect.height_mm:g} mm"]
    lines = [
        f"{indent}{node.orientation.value} split of "
        f"{node.rect.width_mm:g} x {node.rect.height_mm:g} mm"
    ]
    for index, strip in enumerate(node.strips):
        lines.extend(_render(strip, indent + "    "))
        if index < len(node.cuts):
            cut = node.cuts[index]
            gaps = ""
            if cut.clearance_lo_mm or cut.clearance_hi_mm:
                gaps = (
                    f", clearance {cut.clearance_lo_mm:g} / {cut.clearance_hi_mm:g} mm"
                )
            lines.append(
                f"{indent}    -- {cut.plank.name} "
                f"({cut.plank.thickness_mm:g} mm thick{gaps})"
            )
    return lines


_FACING_WHY = {
    FacingEvidence.GIVEN: "you said so",
    FacingEvidence.PANEL: "a back or front panel says so",
    FacingEvidence.FLUSH_BACK: "the members are flush at one end and inset at "
    "the other, and the flush end is the rear -- a weak hint, and one that says "
    "nothing at all when every plank is the same depth",
}


def _facing_line(rec: Recognised) -> str:
    """Say plainly whether left and right in this report can be trusted, and on
    what evidence."""
    sign = rec.plane.screen_right_sign
    if sign is None:
        return (
            "  WARNING: nothing says which side this unit faces, so left and "
            "right below are a\n"
            "  coin flip -- read from the other side, the elevation mirrors. The "
            "tree, sizes, and\n"
            "  lap order are correct either way. Pass min or max to settle it."
        )
    across = _AXIS_NAMES[rec.plane.horizontal]
    towards = "right" if sign > 0 else "left"
    line = f"  increasing {across} runs to the viewer's {towards}"
    why = _FACING_WHY[rec.facing_evidence]
    if rec.facing_evidence is FacingEvidence.GIVEN:
        return f"{line} ({why})"
    return f"{line}\n  (a guess: {why})"


def report(rec: Recognised) -> str:
    depths = sorted(rec.depths_mm)
    lines = [
        f"{rec.plane}",
        _facing_line(rec),
        f"bounding rectangle {rec.bbox.width_mm:g} x {rec.bbox.height_mm:g} mm",
        f"members span depth {rec.d0_mm:g} to {rec.d0_mm + rec.depth_mm:g} "
        f"({rec.depth_mm:g} mm)",
        f"member depths {depths}" + (" -- per-plank depth" if len(depths) > 1 else ""),
        f"thicknesses {sorted(thicknesses(rec))}",
    ]
    if rec.panels:
        names = ", ".join(
            f"{p.name} ({p.thickness_mm:g} mm)"
            for p in sorted(rec.panels, key=lambda p: p.name)
        )
        lines.append(f"Y-thin panels set aside: {names}")
    lines.append("")
    lines.extend(_render(rec.root))
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if not 2 <= len(argv) <= 3:
        print(__doc__)
        return 2
    text = Path(argv[1]).read_text(encoding="utf-8")
    boxes = boxes_from_json(text)
    # Axes only: leaving the facing unset lets recognise infer it and report
    # what the inference rested on.
    plane = detect_axes(boxes)
    if len(argv) == 3:
        if argv[2] not in ("min", "max"):
            print("the front argument must be 'min' or 'max'")
            return 2
        plane = plane._replace(front_at_min=argv[2] == "min")
    try:
        rec = recognise(boxes, plane=plane)
    except RecogniseError as err:
        print(f"REFUSED: {err}")
        if err.objects:
            print("objects: " + ", ".join(err.objects))
        return 1
    print(report(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
