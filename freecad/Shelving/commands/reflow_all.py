"""The "Reflow All" command: rescan and rewrite every shelving unit in the
active document, in one transaction.

The command id is ``Shelving_ReflowAll``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.Shelving.commands.reflow_all`` succeeds
under ``freecadcmd``; the functional smoke calls
``freecad.Shelving.unit_ops.reflow_all`` directly instead of the command,
which does nothing beyond source the catalog, wrap the call in a
transaction, and report per unit. This is the only way a changed catalog
entry (a thickness edit, most commonly) reaches the boards using it:
nothing in this workbench recomputes on its own.
"""

import os
from typing import TYPE_CHECKING, TypedDict

import FreeCAD

from freecad.Shelving.catalog import ensure_catalog, read_catalog
from freecad.Shelving.unit_ops import reflow_all

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


class ReflowAllCommand:
    """`Gui.Command` that rescans and rewrites every container carrying a
    ``ShelvingUnitId`` in the active document against its catalog, in one
    undo transaction. A unit that refuses does not stop the others; every
    result and every refusal prints, one line each."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Reflow All",
            "ToolTip": "Rescan and rewrite every shelving unit against the catalog",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return bool(FreeCAD.ActiveDocument)

    def Activated(self) -> None:
        doc = FreeCAD.ActiveDocument
        # IsActive already required this; re-checked so mypy sees doc as
        # non-None rather than trusting the GUI never calls Activated
        # without it.
        if doc is None:
            return
        doc.openTransaction("Reflow All Shelving Units")  # type: ignore[no-untyped-call]
        try:
            catalog = read_catalog(ensure_catalog(doc))
            result = reflow_all(doc, catalog)
            doc.recompute()
        except Exception as err:  # noqa: BLE001 - report, don't crash the GUI
            doc.abortTransaction()  # type: ignore[no-untyped-call]
            print(f"REFUSED: {err}")
            return
        doc.commitTransaction()  # type: ignore[no-untyped-call]
        for name, write_result in result.succeeded:
            print(
                f"{name}: updated {len(write_result.updated)}, "
                f"created {len(write_result.created)}, "
                f"deleted {len(write_result.deleted)}, "
                f"left alone {len(write_result.left_alone)}"
            )
        for name, message in result.failed:
            print(f"{name}: REFUSED: {message}")


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
        Gui.addCommand("Shelving_ReflowAll", ReflowAllCommand())
