"""Workbench registration for the Shelving Workbench.

FreeCAD imports this module at GUI startup. Under ``freecadcmd`` there is no GUI:
``import FreeCADGui`` either fails outright or returns a stub without
``Workbench``. Both cases collapse to ``Gui = None`` so the GUI base class and
the ``addWorkbench`` call are skipped and importing this module headless does
not raise.
"""

import os
from typing import TYPE_CHECKING

from freecad.Shelving.compat import override

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
    "Shelving_ExportBoxes",
    "Shelving_CreateUnit",
    "Shelving_EditUnit",
)

# On the toolbar Edit Unit shows while it is open, in whatever workbench,
# as the Sketcher's edit-mode toolbars are, and grayed in the menu outside
# it.
CONSTRAINT_COMMANDS = (
    "Shelving_LockWidth",
    "Shelving_LockHeight",
    "Shelving_ConstrainEqual",
    "Shelving_ConstrainEvenSpacing",
)


def menu_commands() -> list[str]:
    """The Shelving menu's command ids: the toolbar's, the constraint
    commands, and the QA Wizard while its developer flag is on."""
    from freecad.Shelving import qa

    return [
        *TOOLBAR_COMMANDS,
        "Separator",
        *CONSTRAINT_COMMANDS,
        *(["Shelving_QAWizard"] if qa.is_enabled() else []),
    ]


class ShelvingWorkbench(_WorkbenchBase):
    """FreeCAD workbench entry point for parametric shelving."""

    MenuText = "Shelving"
    ToolTip = "Parametric shelving layout"
    Icon = os.path.join(_RESOURCE_DIR, "shelving.svg")

    @override
    def Initialize(self) -> None:
        # Deferred so a headless `import freecad.Shelving.init_gui` never reaches
        # GUI-only code: each command module runs `Gui.addCommand` at import.
        from freecad.Shelving.commands import (  # noqa: F401
            constrain_equal,
            constrain_even_spacing,
            create_unit,
            edit_unit,
            export_boxes,
            lock_height,
            lock_width,
            qa_wizard,
        )

        self.appendToolbar("Shelving", list(TOOLBAR_COMMANDS))
        self.appendMenu("Shelving", menu_commands())

    @override
    def Activated(self) -> None:
        pass

    @override
    def Deactivated(self) -> None:
        pass

    @override
    def GetClassName(self) -> str:
        return "Gui::PythonWorkbench"


if not TYPE_CHECKING and Gui is not None:
    Gui.addWorkbench(ShelvingWorkbench())
