"""The "Export Boxes" command: write a selected container's boards as JSON.

The command id is ``Shelving_ExportBoxes``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.Shelving.commands.export_boxes`` succeeds
under ``freecadcmd``, where there is no GUI. This command never calls
``freecad.Shelving.core.scan.scan``: it is the mechanism for capturing a unit that
scanning would refuse, so it has to write regardless of whether the boxes it
read would scan.
"""

import json
import os
from typing import TYPE_CHECKING, TypedDict, cast

import FreeCAD

from freecad.Shelving import refusals
from freecad.Shelving.container import read_container
from freecad.Shelving.temp_dirs import export_path

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")

_CONTAINERS = ("App::Part", "App::LinkGroup", "App::DocumentObjectGroup")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


class _BoxRecord(TypedDict):
    name: str
    corner_mm: list[float]
    size_mm: list[float]


class _SkippedRecord(TypedDict):
    name: str
    label: str
    type: str
    reason: str


class _Export(TypedDict):
    boxes: list[_BoxRecord]
    skipped: list[_SkippedRecord]


def _selected_container() -> FreeCAD.DocumentObject | None:
    """The one selected container the command reads, or ``None`` after
    refusing the current selection: anything other than exactly one
    ``App::Part``, ``App::LinkGroup``, or ``App::DocumentObjectGroup`` is
    refused, because the container is what decides which boards form one
    unit."""
    import FreeCADGui as Gui

    selection = cast("list[FreeCAD.DocumentObject]", Gui.Selection.getSelection())
    if len(selection) == 1 and any(
        selection[0].isDerivedFrom(kind) for kind in _CONTAINERS
    ):
        return selection[0]
    refusals.report_refusal(
        "Export Boxes needs exactly one container selected.",
        (obj.Name for obj in selection),
        refusals.SUGGESTIONS["not_one_container"],
    )
    return None


class ExportBoxesCommand:
    """`Gui.Command` that writes the selected container's boards and
    unreadable parts to a ``<label>.boxes.json`` file in the user's exports
    folder (:func:`freecad.Shelving.temp_dirs.export_path`)."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Export Boxes",
            "ToolTip": "Write the selected container's boards to JSON",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return bool(FreeCAD.ActiveDocument)

    def Activated(self) -> None:
        container = _selected_container()
        if container is None:
            return
        boxes, skipped, _record = read_container(container)
        export: _Export = {
            "boxes": [
                {
                    "name": box.name,
                    "corner_mm": [
                        box.corner_mm.x_mm,
                        box.corner_mm.y_mm,
                        box.corner_mm.z_mm,
                    ],
                    "size_mm": [box.size_mm.x_mm, box.size_mm.y_mm, box.size_mm.z_mm],
                }
                for box in boxes
            ],
            "skipped": [
                {
                    "name": part.name,
                    "label": part.label,
                    "type": part.type,
                    "reason": part.reason,
                }
                for part in skipped
            ],
        }
        path = export_path(container)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(export, handle, indent=2)
        print(f"exported {len(boxes)} box(es), skipped {len(skipped)}: {path}")


if not TYPE_CHECKING:
    try:
        import FreeCADGui as Gui
    except ImportError:
        Gui = None
    else:
        # freecadcmd exposes a FreeCADGui stub without the command registry.
        if not hasattr(Gui, "addCommand"):
            Gui = None
    if Gui is not None:
        Gui.addCommand("Shelving_ExportBoxes", ExportBoxesCommand())
