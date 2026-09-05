"""Print what the recogniser makes of a document exported by ``export_boxes.py``.

    pixi run -- python -m spikes.plain_planks.report Unit.boxes.json

Prints the cut tree, or the refusal and the objects it names. Use it to feed
real GUI-modelled geometry to the recogniser without a FreeCAD round trip.
"""

from __future__ import annotations

import sys
from pathlib import Path

from spikes.plain_planks.recognise import (
    Node,
    Open,
    Outside,
    Recognised,
    RecogniseError,
    boxes_from_json,
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


def report(rec: Recognised) -> str:
    depths = sorted(rec.depths_mm)
    lines = [
        f"{rec.plane}",
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
    if len(argv) != 2:
        print(__doc__)
        return 2
    text = Path(argv[1]).read_text(encoding="utf-8")
    try:
        rec = recognise(boxes_from_json(text))
    except RecogniseError as err:
        print(f"REFUSED: {err}")
        if err.objects:
            print("objects: " + ", ".join(err.objects))
        return 1
    print(report(rec))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
