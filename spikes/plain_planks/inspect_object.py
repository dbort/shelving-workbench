"""Describe the selected objects: what they are, and how box-like their solids are.

Run as a macro in the FreeCAD GUI with one or more objects selected, a container
or a single part. It prints a tree of what is inside and, for every object that
carries a solid, whether that solid is a rectangular box, a box with rectangular
bites taken out of it, or something else.

That last question is the one that decides how a plank-like part can be handled:
a solid whose difference from its own bounding box decomposes into boxes can be
modelled as a plank plus cutouts, and one that cannot has to be carried opaquely.

Nothing is modified. Output goes to the report view and to the clipboard-friendly
JSON file named at the end.
"""

from __future__ import annotations

import json
import os
from typing import Any

import FreeCAD

# Shape queries come back loosely typed, and they are the whole point of this
# script, so values are taken as Any and narrowed by hand. Confined to this
# diagnostic; nothing imports it.
import Part

_TOL_MM = 1e-6
# A face counts as axis-aligned when its normal is within this of an axis.
_NORMAL_TOL = 1e-6


def _children(obj: Any) -> list[Any]:
    for attr in ("ElementList", "Group"):
        members = getattr(obj, attr, None)
        if isinstance(members, list):
            return [m for m in members if hasattr(m, "TypeId")]
    return []


def _shape(obj: Any) -> Any | None:
    shape = getattr(obj, "Shape", None)
    if shape is None or getattr(shape, "isNull", None) is None or shape.isNull():
        return None
    return shape


def _axis_aligned(shape: Any) -> bool:
    """Every face planar with a normal along X, Y, or Z."""
    for face in shape.Faces:
        surface = face.Surface
        if not isinstance(surface, Part.Plane):
            return False
        n = surface.Axis
        components = sorted(abs(c) for c in (n.x, n.y, n.z))
        if abs(components[2] - 1.0) > _NORMAL_TOL or components[1] > _NORMAL_TOL:
            return False
    return True


def _box_of(bound: Any) -> Any:
    return Part.makeBox(
        max(bound.XLength, _TOL_MM),
        max(bound.YLength, _TOL_MM),
        max(bound.ZLength, _TOL_MM),
        FreeCAD.Vector(bound.XMin, bound.YMin, bound.ZMin),
    )


def _describe_solid(shape: Any) -> dict[str, Any]:
    """Size, and whether the solid is a box, a box minus boxes, or neither."""
    bound = shape.BoundBox
    info: dict[str, Any] = {
        "bbox_min_mm": [bound.XMin, bound.YMin, bound.ZMin],
        "bbox_size_mm": [bound.XLength, bound.YLength, bound.ZLength],
        "volume_mm3": shape.Volume,
        "bbox_volume_mm3": bound.XLength * bound.YLength * bound.ZLength,
        "faces": len(shape.Faces),
        "solids": len(shape.Solids),
        "axis_aligned": _axis_aligned(shape),
    }
    # A sketch or a datum has faces but no volume; saying so beats reporting it
    # as a failed box.
    info["is_solid"] = shape.Volume > _TOL_MM and len(shape.Solids) > 0
    if not info["is_solid"]:
        return info
    missing_mm3 = info["bbox_volume_mm3"] - shape.Volume
    info["missing_mm3"] = missing_mm3
    info["is_plain_box"] = (
        len(shape.Faces) == 6
        and info["axis_aligned"]
        and abs(missing_mm3) <= max(1e-6 * info["bbox_volume_mm3"], _TOL_MM)
    )
    if info["is_plain_box"]:
        info["cutouts"] = []
        return info

    # What the bounding box has that the solid does not. If every piece of that
    # is itself a box, the part is a plank plus rectangular cutouts.
    try:
        leftover = _box_of(bound).cut(shape)
    except Exception as err:  # noqa: BLE001 - diagnostic only
        info["cutout_error"] = str(err)
        return info
    pieces = []
    for solid in leftover.Solids:
        piece_bound = solid.BoundBox
        piece_bbox_mm3 = piece_bound.XLength * piece_bound.YLength * piece_bound.ZLength
        pieces.append(
            {
                "min_mm": [piece_bound.XMin, piece_bound.YMin, piece_bound.ZMin],
                "size_mm": [
                    piece_bound.XLength,
                    piece_bound.YLength,
                    piece_bound.ZLength,
                ],
                "volume_mm3": solid.Volume,
                "faces": len(solid.Faces),
                "is_box": len(solid.Faces) == 6
                and _axis_aligned(solid)
                and abs(piece_bbox_mm3 - solid.Volume)
                <= max(1e-6 * piece_bbox_mm3, _TOL_MM),
            }
        )
    info["cutouts"] = pieces
    info["is_box_minus_boxes"] = bool(pieces) and all(p["is_box"] for p in pieces)
    return info


def _placement(obj: Any) -> dict[str, Any] | None:
    placement = getattr(obj, "Placement", None)
    if placement is None:
        return None
    return {
        "base_mm": [placement.Base.x, placement.Base.y, placement.Base.z],
        "rotation_deg": placement.Rotation.Angle * 180.0 / 3.141592653589793,
        "axis": [
            placement.Rotation.Axis.x,
            placement.Rotation.Axis.y,
            placement.Rotation.Axis.z,
        ],
    }


def describe(obj: Any, depth: int = 0) -> dict[str, Any]:
    shape = _shape(obj)
    node: dict[str, Any] = {
        "name": obj.Name,
        "label": obj.Label,
        "type": obj.TypeId,
        "depth": depth,
        "has_shape": shape is not None,
        "placement": _placement(obj),
    }
    if shape is not None:
        node["solid"] = _describe_solid(shape)
    kids = _children(obj)
    if kids:
        node["children"] = [describe(child, depth + 1) for child in kids]
    return node


def _line(node: dict[str, Any]) -> str:
    pad = "  " * node["depth"]
    bits = [f"{pad}{node['label']}  [{node['type']}]"]
    solid = node.get("solid")
    if solid is not None:
        size = solid["bbox_size_mm"]
        bits.append(
            f"{pad}    bbox {size[0]:.4g} x {size[1]:.4g} x {size[2]:.4g} mm, "
            f"{solid['faces']} faces, {solid['solids']} solid(s)"
        )
        if not solid.get("is_solid", True):
            verdict = "no solid (a sketch, a datum, or empty)"
        elif solid["is_plain_box"]:
            verdict = "a plain box"
        elif solid.get("is_box_minus_boxes"):
            n = len(solid["cutouts"])
            verdict = f"a box minus {n} rectangular cutout(s)"
        elif not solid["axis_aligned"]:
            verdict = "NOT axis-aligned (has non-planar or angled faces)"
        else:
            verdict = "axis-aligned but not a box minus boxes"
        bits.append(f"{pad}    -> {verdict}")
        for piece in solid.get("cutouts", []):
            s = piece["size_mm"]
            m = piece["min_mm"]
            bits.append(
                f"{pad}       cutout {s[0]:.4g} x {s[1]:.4g} x {s[2]:.4g} mm at "
                f"({m[0]:.4g}, {m[1]:.4g}, {m[2]:.4g}) "
                f"{'box' if piece['is_box'] else 'NOT a box'}"
            )
    place = node.get("placement")
    if place is not None and abs(place["rotation_deg"]) > 1e-6:
        bits.append(f"{pad}    rotated {place['rotation_deg']:.4g} deg")
    lines = bits
    for child in node.get("children", []):
        lines.append(_line(child))
    return "\n".join(lines)


def inspect_selection() -> str:
    import FreeCADGui

    selection = FreeCADGui.Selection.getSelection()
    if not selection:
        raise ValueError("select a container or a part")
    nodes = [describe(obj) for obj in selection]
    for node in nodes:
        print(_line(node))
    doc = selection[0].Document
    directory = (
        os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
    )
    path = os.path.join(directory, "inspect.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(nodes, handle, indent=2)
    print(f"\nwrote {path}")
    return path


if __name__ == "__main__":
    inspect_selection()
