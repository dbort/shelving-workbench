"""The "Scan Unit" command: read a selected container and report its layout.

The command id is ``Shelving_Scan``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.shelving.commands.scan`` succeeds under
``freecadcmd``, where there is no GUI; the functional smoke calls
``read_container`` and ``scan`` directly instead of the command.
"""

import os
from typing import TYPE_CHECKING, TypedDict, cast

import FreeCAD

from freecad.shelving.container import read_container
from freecad.shelving.core.report import report
from freecad.shelving.core.scan import ScanError, scan
from freecad.shelving.default_catalog import DEFAULT_CATALOG

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")

_CONTAINERS = ("App::Part", "App::LinkGroup", "App::DocumentObjectGroup")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


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
        "select exactly one App::Part, App::LinkGroup, or group to scan; "
        "group the boards into one first",
        (obj.Name for obj in selection),
    )


def _select_offenders(err: ScanError) -> None:
    """Clear the selection and select the objects ``err`` names, so a
    refusal is visible in the 3D view rather than only as report-view text."""
    import FreeCADGui as Gui

    Gui.Selection.clearSelection()
    doc = FreeCAD.ActiveDocument
    if doc is None:
        return
    for name in err.objects:
        obj = doc.getObject(name)
        if obj is not None:
            Gui.Selection.addSelection(obj)


class ScanCommand:
    """`Gui.Command` that reads the selected container and prints what
    scanning made of it, or a refusal naming the objects that defeated it."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Scan Unit",
            "ToolTip": "Read the selected container and report its layout",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return bool(FreeCAD.ActiveDocument)

    def Activated(self) -> None:
        try:
            container = _selected_container()
            boxes, skipped = read_container(container)
            result = scan(boxes, DEFAULT_CATALOG, skipped=skipped)
        except ScanError as err:
            print(f"REFUSED: {err}")
            if err.objects:
                print("objects: " + ", ".join(err.objects))
            _select_offenders(err)
            return
        print(report(result))


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
        Gui.addCommand("Shelving_Scan", ScanCommand())
