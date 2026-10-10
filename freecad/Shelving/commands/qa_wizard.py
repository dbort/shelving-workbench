"""The "QA Wizard" command: show the manual QA dock.

Registered only while :func:`freecad.Shelving.qa.is_enabled` is true, and
only in the Shelving menu, since it is developer tooling.
"""

import os
from typing import TYPE_CHECKING, TypedDict

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


class QAWizardCommand:
    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "QA Wizard",
            "ToolTip": "Walk through the manual QA cases, recording each step",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return True

    def Activated(self) -> None:
        # Imported here: the dock needs Qt and FreeCAD's GUI, which a headless
        # import of this module must not reach.
        from freecad.Shelving.qa import dock

        dock.show()


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
        Gui.addCommand("Shelving_QAWizard", QAWizardCommand())
