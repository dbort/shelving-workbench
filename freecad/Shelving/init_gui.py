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

TOOLBAR_COMMANDS = (
    "Shelving_Scan",
    "Shelving_ExportBoxes",
    "Shelving_CreateUnit",
    "Shelving_EditUnit",
)


def menu_commands() -> list[str]:
    """The Shelving menu's command ids: the toolbar's, plus the QA Wizard
    while its developer flag is on."""
    from freecad.Shelving import qa

    return [*TOOLBAR_COMMANDS, *(["Shelving_QAWizard"] if qa.is_enabled() else [])]


class ShelvingWorkbench(_WorkbenchBase):
    """FreeCAD workbench entry point for parametric shelving."""

    MenuText = "Shelving"
    ToolTip = "Parametric shelving layout"
    Icon = os.path.join(_RESOURCE_DIR, "shelving.svg")

    def Initialize(self) -> None:
        # Deferred so a headless `import freecad.Shelving.init_gui` never reaches
        # GUI-only code: each command module runs `Gui.addCommand` at import.
        from freecad.Shelving.commands import (  # noqa: F401
            create_unit,
            edit_unit,
            export_boxes,
            qa_wizard,
            scan,
        )

        self.appendToolbar("Shelving", list(TOOLBAR_COMMANDS))
        # freecad-stubs leaves `appendMenu` unannotated.
        self.appendMenu("Shelving", menu_commands())  # type: ignore[no-untyped-call]

    def Activated(self) -> None:
        pass

    def Deactivated(self) -> None:
        pass

    def GetClassName(self) -> str:
        return "Gui::PythonWorkbench"


if not TYPE_CHECKING and Gui is not None:
    Gui.addWorkbench(ShelvingWorkbench())
