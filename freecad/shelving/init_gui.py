"""Workbench registration for the Shelving Workbench.

FreeCAD imports this module at GUI startup. Under ``freecadcmd`` there is no GUI:
``import FreeCADGui`` either fails outright or returns a stub without
``Workbench``. Both cases collapse to ``Gui = None`` so the GUI base class and
the ``addWorkbench`` call are skipped and importing this module headless does
not raise.
"""

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # The base is only referenced as a type here; the runtime branch below
    # picks the real class or ``object``.
    from FreeCADGui import Workbench as _WorkbenchBase
else:
    try:
        import FreeCADGui as Gui
    except ImportError:
        Gui = None
    else:
        # freecadcmd exposes a FreeCADGui stub lacking the GUI classes.
        if not hasattr(Gui, "Workbench"):
            Gui = None
    _WorkbenchBase = Gui.Workbench if Gui is not None else object

_RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")


class ShelvingWorkbench(_WorkbenchBase):
    """FreeCAD workbench entry point for parametric shelving.

    M3 adds the plank object layer below the unit container; the "Create Unit"
    command, toolbar, and layout editor arrive in later milestones.
    """

    MenuText = "Shelving"
    ToolTip = "Parametric shelving layout"
    Icon = os.path.join(_RESOURCE_DIR, "shelving.svg")

    def Initialize(self) -> None:
        pass

    def Activated(self) -> None:
        pass

    def Deactivated(self) -> None:
        pass

    def GetClassName(self) -> str:
        return "Gui::PythonWorkbench"


if not TYPE_CHECKING and Gui is not None:
    Gui.addWorkbench(ShelvingWorkbench())
