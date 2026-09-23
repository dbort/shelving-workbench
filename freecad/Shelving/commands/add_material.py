"""The "Add Material" command: append a blank catalog entry and select it.

The command id is ``Shelving_AddMaterial``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.Shelving.commands.add_material`` succeeds
under ``freecadcmd``; the functional smoke calls
``freecad.Shelving.catalog.add_entry`` directly instead of the command,
which does nothing beyond seed the catalog if needed, add the entry, select
it, and wrap both in a transaction. There is no dialog: the new entry's
``MaterialId`` is a placeholder and its ``Thickness`` is zero, both left for
the user to fill in through the property editor, which is why this command
selects the entry rather than only reporting its name.
"""

import os
from typing import TYPE_CHECKING, TypedDict

import FreeCAD

from freecad.Shelving.catalog import add_entry, ensure_catalog

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


class AddMaterialCommand:
    """`Gui.Command` that appends a blank catalog entry to the active
    document's material catalog, seeding the catalog first if it has none,
    in one undo transaction, and selects the new entry."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Add Material",
            "ToolTip": "Add a blank catalog entry to edit in the property editor",
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
        doc.openTransaction("Add Material")  # type: ignore[no-untyped-call]
        try:
            group = ensure_catalog(doc)
            entry = add_entry(group)
            doc.recompute()
        except Exception as err:  # noqa: BLE001 - report, don't crash the GUI
            doc.abortTransaction()  # type: ignore[no-untyped-call]
            print(f"REFUSED: {err}")
            return
        doc.commitTransaction()  # type: ignore[no-untyped-call]
        import FreeCADGui as Gui

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(entry)
        print(f"added {entry.Name!r} to {group.Name!r}; fill in its properties")


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
        Gui.addCommand("Shelving_AddMaterial", AddMaterialCommand())
