"""The "Export Boxes" command: write a selected container's boards as JSON.

The command id is ``Shelving_ExportBoxes``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.shelving.commands.export_boxes`` succeeds
under ``freecadcmd``, where there is no GUI. This command never calls
``freecad.shelving.core.scan.scan``: it is the mechanism for capturing a unit that
scanning would refuse, so it has to write regardless of whether the boxes it
read would scan.
"""

import json
import os
from typing import TYPE_CHECKING, TypedDict, cast

import FreeCAD

from freecad.shelving.container import read_container
from freecad.shelving.core.scan import ScanError

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


def _selected_container() -> FreeCAD.DocumentObject:
    """The one selected container the command reads, or ``ScanError`` naming
    the current selection: anything other than exactly one ``App::Part``,
    ``App::LinkGroup``, or ``App::DocumentObjectGroup`` is refused, because
    the container is what decides which boards form one unit."""
    import FreeCADGui as Gui

    selection = cast("list[FreeCAD.DocumentObject]", Gui.Selection.getSelection())
    if len(selection) == 1 and any(
        selection[0].isDerivedFrom(kind) for kind in _CONTAINERS
    ):
        return selection[0]
    raise ScanError(
        "select exactly one App::Part, App::LinkGroup, or group to export; "
        "group the boards into one first",
        (obj.Name for obj in selection),
    )


def _export_path(obj: FreeCAD.DocumentObject) -> str:
    doc = obj.Document
    directory = (
        os.path.dirname(doc.FileName) if doc.FileName else os.path.expanduser("~")
    )
    safe = "".join(c if c.isalnum() else "_" for c in obj.Label).strip("_")
    return os.path.join(directory, f"{safe or 'boxes'}.boxes.json")


class ExportBoxesCommand:
    """`Gui.Command` that writes the selected container's boards and
    unreadable parts to a ``<label>.boxes.json`` file beside the document."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Export Boxes",
            "ToolTip": "Write the selected container's boards to JSON",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return bool(FreeCAD.ActiveDocument)

    def Activated(self) -> None:
        try:
            container = _selected_container()
        except ScanError as err:
            print(f"REFUSED: {err}")
            return
        boxes, skipped = read_container(container)
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
        path = _export_path(container)
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
