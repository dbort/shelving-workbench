"""The "Constrain Even Spacing" command: keep every opening between two
ends of one row or column the same size.

Active only while Edit Unit is open, on the toolbar the editor shows then
and in the Shelving menu. A selection it cannot use is refused through the
Notification Area, saying what to select.
"""

from typing import TYPE_CHECKING, Literal, TypedDict


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str
    CmdType: Literal["NoTransaction"]


class ConstrainEvenSpacingCommand:
    def GetResources(self) -> _CommandResources:
        # Imported here: the editor needs Qt and Coin, which a headless
        # import of this module must not reach.
        from freecad.Shelving.editor.overlay import ICON_SOURCES

        return {
            "MenuText": "Constrain Even Spacing",
            "ToolTip": (
                "Space the openings of one row or column evenly: select its "
                "first and last opening, or the two boards at its ends"
            ),
            "Pixmap": ICON_SOURCES["even_spacing"],
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
            panel.constrain("even_spacing")


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
        Gui.addCommand("Shelving_ConstrainEvenSpacing", ConstrainEvenSpacingCommand())
