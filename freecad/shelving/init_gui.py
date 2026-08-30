"""Workbench registration for the Shelving Workbench.

FreeCAD imports this module at GUI startup. Under ``freecadcmd`` there is no GUI
and ``FreeCADGui`` cannot be imported, so the GUI base class and the
``addWorkbench`` call are guarded: importing this module headless must not
raise.
"""

import os

try:
    import FreeCADGui as Gui
except ImportError:
    Gui = None

_RESOURCE_DIR = os.path.join(os.path.dirname(__file__), "resources")

_WorkbenchBase = Gui.Workbench if Gui is not None else object


class ShelvingWorkbench(_WorkbenchBase):
    """FreeCAD workbench entry point for parametric shelving.

    M0 registers the workbench only; commands and the layout editor arrive in
    later milestones.
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


if Gui is not None:
    Gui.addWorkbench(ShelvingWorkbench())
