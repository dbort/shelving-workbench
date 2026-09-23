"""The "Seed Catalog" command: ensure the active document has a material
catalog, seeding one from the in-code default when it has none.

The command id is ``Shelving_SeedCatalog``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.Shelving.commands.seed_catalog`` succeeds
under ``freecadcmd``; the functional smoke calls
``freecad.Shelving.catalog.ensure_catalog`` directly instead of the command,
which does nothing beyond wrap that call in a transaction and report
whether it found or created a catalog. Most commands never need this: every
catalog-consuming command already calls ``ensure_catalog`` itself. This one
exists for a user who wants to see or start editing the catalog before
doing anything else that would seed it as a side effect.
"""

import os
from typing import TYPE_CHECKING, TypedDict

import FreeCAD

from freecad.Shelving.catalog import ensure_catalog, find_catalog

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


class SeedCatalogCommand:
    """`Gui.Command` that ensures the active document has a material
    catalog, creating one from the in-code default if it has none, in one
    undo transaction."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Seed Catalog",
            "ToolTip": "Create the document's material catalog if it has none",
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
        had_one = find_catalog(doc) is not None
        doc.openTransaction("Seed Material Catalog")  # type: ignore[no-untyped-call]
        try:
            group = ensure_catalog(doc)
            doc.recompute()
        except Exception as err:  # noqa: BLE001 - report, don't crash the GUI
            doc.abortTransaction()  # type: ignore[no-untyped-call]
            print(f"REFUSED: {err}")
            return
        doc.commitTransaction()  # type: ignore[no-untyped-call]
        if had_one:
            print(f"found existing catalog {group.Name!r}")
        else:
            print(f"created catalog {group.Name!r}")


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
        Gui.addCommand("Shelving_SeedCatalog", SeedCatalogCommand())
