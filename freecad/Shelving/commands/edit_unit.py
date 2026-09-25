"""The "Edit Unit" command: open the elevation editor on the selected container.

The command id is ``Shelving_EditUnit``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.Shelving.commands.edit_unit`` succeeds
under ``freecadcmd``. ``Activated`` shows
:class:`freecad.Shelving.editor.panel.EditUnitPanel` through
``FreeCADGui.Control.showDialog``, which does not exist under ``freecadcmd``
(see ``docs/freecadcmd-notes.md`` and this repo's sh-020 Frontier Advice);
the functional smoke drives :class:`freecad.Shelving.editor.session.Session`
directly instead, the same way ``tools/freecad_write_smoke.py`` calls
``unit_ops`` functions rather than going through a command's ``Activated``.
"""

import os
from typing import TYPE_CHECKING, TypedDict, cast

import FreeCAD

from freecad.Shelving.editor.panel import EditUnitPanel

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")

_CONTAINERS = ("App::Part", "App::LinkGroup", "App::DocumentObjectGroup")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


def _selected_container() -> FreeCAD.DocumentObject | None:
    """The one selected container to edit, or ``None`` when the selection is
    not exactly one ``App::Part``, ``App::LinkGroup``, or group."""
    import FreeCADGui as Gui

    selection = cast("list[FreeCAD.DocumentObject]", Gui.Selection.getSelection())
    if len(selection) == 1 and any(
        selection[0].isDerivedFrom(kind) for kind in _CONTAINERS
    ):
        return selection[0]
    return None


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
        return bool(FreeCAD.ActiveDocument) and _selected_container() is not None

    def Activated(self) -> None:
        container = _selected_container()
        if container is None:
            print(
                "REFUSED: select exactly one App::Part, App::LinkGroup, or "
                "group to edit"
            )
            return
        import FreeCADGui as Gui

        Gui.Control.showDialog(EditUnitPanel(container))


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
