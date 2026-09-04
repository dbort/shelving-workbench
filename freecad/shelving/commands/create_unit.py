"""The "Create Unit" command: seed one `ShelvingUnit` into the active document.

The command id is ``Shelving_CreateUnit``. `Gui.addCommand` runs behind a
headless guard so ``import freecad.shelving.commands.create_unit`` succeeds under
``freecadcmd``, where there is no GUI; the functional smoke calls
`make_shelving_unit` directly instead of the command.
"""

import os
from typing import TYPE_CHECKING, TypedDict

import FreeCAD

from freecad.shelving.objects.shelving_unit import make_shelving_unit

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


class CreateUnitCommand:
    """`Gui.Command` that creates a parametric shelving unit and recomputes it
    inside a single undo transaction."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Create Unit",
            "ToolTip": "Create a parametric shelving unit",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return bool(FreeCAD.ActiveDocument)

    def Activated(self) -> None:
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return
        # freecad-stubs leaves the transaction methods unannotated.
        doc.openTransaction("Create Shelving Unit")  # type: ignore[no-untyped-call]
        make_shelving_unit(doc)
        doc.recompute()
        doc.commitTransaction()  # type: ignore[no-untyped-call]


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
