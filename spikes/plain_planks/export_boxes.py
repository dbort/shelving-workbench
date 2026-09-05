"""Export the ``Part::Box`` planks under a container as JSON for the recogniser.

Run as a macro in the FreeCAD GUI with one container selected (an
``App::Part``, ``App::LinkGroup``, or plain group), or with several boxes
selected. The JSON lands next to the document as ``<label>.boxes.json`` and the
path is printed to the report view. Under ``freecadcmd`` the same function can
be called on a container object directly.

A rotated box is refused, because the recogniser only handles axis-aligned
planks; anything that is not a ``Part::Box`` is listed under ``skipped``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Protocol, TypedDict, cast

import FreeCAD

_ROTATION_TOL_DEG = 1e-6


class BoxRecord(TypedDict):
    name: str
    label: str
    corner_mm: list[float]
    size_mm: list[float]


class SkippedRecord(TypedDict):
    name: str
    type: str
    reason: str


class Export(TypedDict):
    container: str
    boxes: list[BoxRecord]
    skipped: list[SkippedRecord]


class BoxObject(Protocol):
    """The ``Part::Box`` surface the export reads; the stubs type only the
    generic ``DocumentObject``."""

    Name: str
    Label: str
    Placement: FreeCAD.Placement
    Length: FreeCAD.Quantity
    Width: FreeCAD.Quantity
    Height: FreeCAD.Quantity


def _children(obj: FreeCAD.DocumentObject) -> list[FreeCAD.DocumentObject]:
    # LinkGroup children live in ElementList; Part, Body, and plain groups use
    # Group. An object with neither is a leaf.
    for attr in ("ElementList", "Group"):
        members = getattr(obj, attr, None)
        if isinstance(members, list):
            return [m for m in members if isinstance(m, FreeCAD.DocumentObject)]
    return []


def _walk(
    obj: FreeCAD.DocumentObject, placement: FreeCAD.Placement
) -> Iterator[tuple[FreeCAD.DocumentObject, FreeCAD.Placement]]:
    """Every descendant leaf with the accumulated placement of its containers.

    ``getGlobalPlacement`` only composes through geo-feature groups, and a
    ``LinkGroup`` is not one, so the container chain is composed here.
    """
    children = _children(obj)
    if not children:
        yield obj, placement
        return
    own = getattr(obj, "Placement", None)
    if isinstance(own, FreeCAD.Placement):
        placement = placement.multiply(own)
    for child in children:
        yield from _walk(child, placement)


def export_container(obj: FreeCAD.DocumentObject) -> Export:
    boxes: list[BoxRecord] = []
    skipped: list[SkippedRecord] = []
    for leaf, container_placement in _walk(obj, FreeCAD.Placement()):
        if not leaf.isDerivedFrom("Part::Box"):
            skipped.append(
                {"name": leaf.Name, "type": leaf.TypeId, "reason": "not a Part::Box"}
            )
            continue
        box = cast("BoxObject", leaf)
        placement = container_placement.multiply(box.Placement)
        if abs(placement.Rotation.Angle) > _ROTATION_TOL_DEG:
            raise ValueError(
                f"{box.Name} ({box.Label}) is rotated; only axis-aligned boxes "
                "are supported"
            )
        base = placement.Base
        boxes.append(
            {
                "name": box.Name,
                "label": box.Label,
                "corner_mm": [base.x, base.y, base.z],
                "size_mm": [box.Length.Value, box.Width.Value, box.Height.Value],
            }
        )
    return {"container": obj.Label, "boxes": boxes, "skipped": skipped}


def export_selection() -> str:
    """Export the GUI selection and return the path written."""
    import FreeCADGui

    selection = FreeCADGui.Selection.getSelection()
    if not selection:
        raise ValueError("select a container (Part, LinkGroup, or group) or some boxes")
    if len(selection) == 1:
        export = export_container(selection[0])
    else:
        export = {"container": "selection", "boxes": [], "skipped": []}
        for obj in selection:
            part = export_container(obj)
            export["boxes"].extend(part["boxes"])
            export["skipped"].extend(part["skipped"])
    doc = selection[0].Document
    directory = (
        os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
    )
    safe = "".join(c if c.isalnum() else "_" for c in export["container"]).strip("_")
    path = os.path.join(directory, f"{safe or 'boxes'}.boxes.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(export, handle, indent=2)
    # print reaches the report view in the GUI and stdout under freecadcmd.
    kept = len(export["boxes"])
    skipped_count = len(export["skipped"])
    print(f"exported {kept} boxes, skipped {skipped_count}: {path}")
    return path


if __name__ == "__main__":
    export_selection()
