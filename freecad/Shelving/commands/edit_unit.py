"""The "Edit Unit" command: open the elevation editor on the selected container.

``FreeCADGui.Control.showDialog`` does not exist under ``freecadcmd``, so the
functional smoke drives :class:`freecad.Shelving.editor.session.Session`
directly rather than this command's ``Activated``, the same way
``tools/freecad_write_smoke.py`` calls ``unit_ops`` functions.
"""

import os
import time
from typing import TYPE_CHECKING, TypedDict, cast

import FreeCAD

from freecad.Shelving import debug_log

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


def _selected_container() -> FreeCAD.DocumentObject | None:
    """The unit container the current selection names, per
    :func:`freecad.Shelving.container.unit_for_selection`."""
    import FreeCADGui as Gui

    from freecad.Shelving.container import unit_for_selection

    selection = cast("list[FreeCAD.DocumentObject]", Gui.Selection.getSelection())
    return unit_for_selection(selection)


class EditUnitCommand:
    """`Gui.Command` that opens the elevation editor task panel on the
    selected container."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Edit Unit",
            "ToolTip": "Open the elevation editor for the selected unit",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        start_s = time.perf_counter()
        active = bool(FreeCAD.ActiveDocument) and _selected_container() is not None
        elapsed_ms = (time.perf_counter() - start_s) * 1000
        # FreeCAD polls IsActive continually, so only a slow call is worth a line.
        if elapsed_ms > 50:
            debug_log.log(f"edit unit: slow IsActive: {elapsed_ms:.1f} ms")
        return active

    def Activated(self) -> None:
        run = debug_log.begin("edit unit")
        try:
            self._activate(run)
        except BaseException:
            run.end("raised")
            raise

    def _activate(self, run: debug_log.Invocation) -> None:
        import FreeCADGui as Gui

        selection = cast("list[FreeCAD.DocumentObject]", Gui.Selection.getSelection())
        run.lap("selection: " + ", ".join(f"{o.Name} ({o.TypeId})" for o in selection))
        container = _selected_container()
        run.lap(f"resolve unit: {container.Name if container else None}")
        if container is None:
            print(
                "REFUSED: select one unit's container, or parts that all "
                "belong to the same unit"
            )
            run.end("refused")
            return
        # Imported here, as resize_unit.py does with Qt: a PySide6 import
        # failure on some user's FreeCAD build would otherwise stop init_gui
        # from registering every Shelving command, not only this one.
        from PySide6 import QtCore

        from freecad.Shelving.editor.panel import EditUnitPanel

        run.lap("import panel")
        try:
            panel = EditUnitPanel(container)
        except Exception as err:  # noqa: BLE001 - report, don't crash the GUI
            print(f"REFUSED: {err}")
            run.end("refused")
            return
        run.lap("build panel")
        try:
            Gui.Control.showDialog(panel)
        except Exception as err:  # noqa: BLE001 - the transaction EditUnitPanel
            # already opened would otherwise stay open with no dialog left to
            # commit or abort it (showDialog raises RuntimeError when another
            # task dialog is already active).
            panel.session.cancel()
            print(f"REFUSED: {err}")
            run.end("refused")
            return
        run.lap("showDialog")

        # Layout and first paint of the docked panel happen after showDialog
        # returns, on the next pass of the event loop, so the run ends there.
        def _first_pass() -> None:
            run.lap("first event-loop pass after showDialog")
            run.end()

        QtCore.QTimer.singleShot(0, _first_pass)


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
        Gui.addCommand("Shelving_EditUnit", EditUnitCommand())
