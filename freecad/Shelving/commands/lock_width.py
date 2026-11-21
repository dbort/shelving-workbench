"""The "Lock Width" command: lock, at its current size, the region each
selected opening's width belongs to, as the Sketcher's
Constrain Horizontal Distance fixes a horizontal distance.

Active only while Edit Unit is open, on the toolbar the editor shows then
and in the Shelving menu. A selection it cannot use is refused through the
Notification Area, saying what to select, as the Sketcher's constraint
commands explain a wrong selection rather than graying out.
"""

from typing import TYPE_CHECKING, Literal, TypedDict


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str
    CmdType: Literal["NoTransaction"]


class LockWidthCommand:
    def GetResources(self) -> _CommandResources:
        # Imported here: the editor needs Qt and Coin, which a headless
        # import of this module must not reach.
        from freecad.Shelving.editor.overlay import LOCK_ICON_SOURCES

        return {
            "MenuText": "Lock Width",
            "ToolTip": (
                "Lock the width of each selected opening at its current size; "
                "a bay in a column locks the column's width"
            ),
            "Pixmap": LOCK_ICON_SOURCES["horizontal"],
            # The session makes its own undo step.
            "CmdType": "NoTransaction",
        }

    def IsActive(self) -> bool:
        from freecad.Shelving.editor.panel import active_panel

        return active_panel() is not None

    def Activated(self) -> None:
        from freecad.Shelving.editor.panel import active_panel

        panel = active_panel()
        if panel is not None:
            panel.lock("horizontal")


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
        Gui.addCommand("Shelving_LockWidth", LockWidthCommand())
