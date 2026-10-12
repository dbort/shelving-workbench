"""Spike: the "Spike: Edit Unit in 3D View" command."""

import os
import traceback
from typing import TYPE_CHECKING, TypedDict, cast

import FreeCAD

from freecad.Shelving import refusals
from freecad.Shelving.spikes.spike_log import LOG_PATH, log

_ICON = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "resources", "shelving.svg"
)


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


def _selected_container() -> FreeCAD.DocumentObject | None:
    import FreeCADGui as Gui

    from freecad.Shelving.container import unit_for_selection

    selection = cast("list[FreeCAD.DocumentObject]", Gui.Selection.getSelection())
    return unit_for_selection(selection)


class ViewportSpikeCommand:
    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Spike: Edit Unit in 3D View",
            "ToolTip": (
                "Temporary research spike: edit the selected unit in the 3D "
                f"view. Logs to {LOG_PATH}"
            ),
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return bool(FreeCAD.ActiveDocument) and _selected_container() is not None

    def Activated(self) -> None:
        import FreeCADGui as Gui

        from freecad.Shelving.spikes.viewport_panel import SpikePanel

        container = _selected_container()
        if container is None:
            return
        try:
            panel = SpikePanel(container)
        except Exception as err:  # noqa: BLE001 - report, don't crash the GUI
            log("spike failed to open:\n" + traceback.format_exc())
            refusals.report_error(f"Viewport spike could not open: {err}")
            return
        try:
            Gui.Control.showDialog(panel)
        except Exception as err:  # noqa: BLE001 - the transaction is open
            log("showDialog failed:\n" + traceback.format_exc())
            if panel.editor is not None:
                panel.editor.close()
            panel.session.cancel()
            refusals.report_error(f"Viewport spike could not open its panel: {err}")


if not TYPE_CHECKING:
    try:
        import FreeCADGui as Gui
    except ImportError:
        Gui = None
    else:
        if not hasattr(Gui, "addCommand"):
            Gui = None
    if Gui is not None:
        Gui.addCommand("Shelving_SpikeViewport", ViewportSpikeCommand())
