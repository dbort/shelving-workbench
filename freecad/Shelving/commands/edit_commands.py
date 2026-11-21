"""The commands that edit the open unit: Add Shelf, Add Divider, Lock Width,
Lock Height, Constrain Equal and Constrain Even Spacing.

Each is active only while Edit Unit is open, on the toolbar the editor
shows then, in the 3D view's right-click menu and in the Shelving menu. A
selection one cannot use is refused through the Notification Area, saying
what to select, as the Sketcher's constraint commands explain a wrong
selection rather than graying out.
"""

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Literal, NamedTuple, TypedDict

from freecad.Shelving.editor.elevation import (
    ADD_ICON_SOURCES,
    ICON_SOURCES,
    LOCK_ICON_SOURCES,
    ElevationDirection,
)
from freecad.Shelving.editor.session import EDIT_COMMANDS, SplitDirection

if TYPE_CHECKING:
    from freecad.Shelving.editor.panel import ConstraintCommand, EditUnitPanel


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str
    CmdType: Literal["NoTransaction"]


class _Spec(NamedTuple):
    menu_text: str
    tooltip: str
    icon: str
    act: Callable[["EditUnitPanel"], None]


def _add(direction: SplitDirection) -> Callable[["EditUnitPanel"], None]:
    return lambda panel: panel.add(direction)


def _lock(direction: ElevationDirection) -> Callable[["EditUnitPanel"], None]:
    return lambda panel: panel.lock(direction)


def _constrain(command: "ConstraintCommand") -> Callable[["EditUnitPanel"], None]:
    return lambda panel: panel.constrain(command)


_SPECS: Mapping[str, _Spec] = {
    "Shelving_AddShelf": _Spec(
        "Add Shelf",
        "Add a shelf across the middle of each selected bay",
        ADD_ICON_SOURCES["vertical"],
        _add("vertical"),
    ),
    "Shelving_AddDivider": _Spec(
        "Add Divider",
        "Add a divider down the middle of each selected bay",
        ADD_ICON_SOURCES["horizontal"],
        _add("horizontal"),
    ),
    "Shelving_LockWidth": _Spec(
        "Lock Width",
        "Lock the width of each selected opening at its current size; "
        "a bay in a column locks the column's width",
        LOCK_ICON_SOURCES["horizontal"],
        _lock("horizontal"),
    ),
    "Shelving_LockHeight": _Spec(
        "Lock Height",
        "Lock the height of each selected opening at its current size; "
        "a bay in a row of bays locks the row's height",
        LOCK_ICON_SOURCES["vertical"],
        _lock("vertical"),
    ),
    "Shelving_ConstrainEqual": _Spec(
        "Constrain Equal",
        "Keep the selected openings the same size: select two or more "
        "widths, or two or more heights",
        ICON_SOURCES["equal"],
        _constrain("equal"),
    ),
    "Shelving_ConstrainEvenSpacing": _Spec(
        "Constrain Even Spacing",
        "Space the openings of one row or column evenly: select its "
        "first and last opening, or the two boards at its ends",
        ICON_SOURCES["even_spacing"],
        _constrain("even_spacing"),
    ),
}


class EditCommand:
    def __init__(self, spec: _Spec) -> None:
        self._spec = spec

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": self._spec.menu_text,
            "ToolTip": self._spec.tooltip,
            "Pixmap": self._spec.icon,
            # The session makes its own undo step.
            "CmdType": "NoTransaction",
        }

    def IsActive(self) -> bool:
        # Imported here: the panel needs Qt and Coin, which a headless
        # import of this module must not reach.
        from freecad.Shelving.editor.panel import active_panel

        return active_panel() is not None

    def Activated(self) -> None:
        from freecad.Shelving.editor.panel import active_panel

        panel = active_panel()
        if panel is not None:
            self._spec.act(panel)


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
        # Keyed by EDIT_COMMANDS, so an id without a spec fails at import.
        for _name in EDIT_COMMANDS:
            if _name != "Separator":
                Gui.addCommand(_name, EditCommand(_SPECS[_name]))
