"""The "Create Unit" command: seed a new closed single-bay shelving unit.

The command id is ``Shelving_CreateUnit``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.Shelving.commands.create_unit`` succeeds
under ``freecadcmd``; the functional smoke calls
``freecad.Shelving.unit_ops.create_unit`` directly instead of the command,
which does nothing beyond wrap that call in a transaction and print what it
did.
"""

import os
from typing import TYPE_CHECKING, TypedDict

import FreeCAD

from freecad.Shelving.unit_ops import create_unit

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


class CreateUnitCommand:
    """`Gui.Command` that seeds a new `App::Part` with a closed single-bay
    unit at fixed defaults, in one undo transaction."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Create Unit",
            "ToolTip": "Seed a new closed single-bay shelving unit",
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
        doc.openTransaction("Create Shelving Unit")  # type: ignore[no-untyped-call]
        try:
            container = create_unit(doc)
            doc.recompute()
        except Exception as err:  # noqa: BLE001 - report, don't crash the GUI
            doc.abortTransaction()  # type: ignore[no-untyped-call]
            print(f"REFUSED: {err}")
            return
        doc.commitTransaction()  # type: ignore[no-untyped-call]
        board_count = len(getattr(container, "Group", []))
        print(f"created {container.Name!r} with {board_count} boards")


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
        Gui.addCommand("Shelving_CreateUnit", CreateUnitCommand())
