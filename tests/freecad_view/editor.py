"""Edit Unit as a user runs it with the 3D view up: the toolbar command,
its task panel, the controls it puts in the view, and the Notification
Area."""

import gc
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtWidgets

from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import SplitDirection
from freecad.Shelving.editor.view_editor import ViewEditor
from tests.freecad_view.view import ViewDriver


def run_command(
    command: str, selected: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(selected)
    FreeCADGui.runCommand(command)
    driver.pump()


def edit_unit(container: FreeCAD.DocumentObject, driver: ViewDriver) -> EditUnitPanel:
    """Run Edit Unit on ``container`` and return the panel it opened."""
    earlier = {id(obj) for obj in gc.get_objects() if isinstance(obj, EditUnitPanel)}
    run_command("Shelving_EditUnit", container, driver)
    (panel,) = [
        obj
        for obj in gc.get_objects()
        if isinstance(obj, EditUnitPanel) and id(obj) not in earlier
    ]
    assert FreeCADGui.Control.activeDialog()
    # Points are aimed at where the turn toward the unit leaves the camera.
    for _ in range(100):
        if not editor_of(panel).turning:
            break
        driver.pump(50)
    assert not editor_of(panel).turning
    driver.pump()
    return panel


def press_task_button(text: str) -> None:
    """Press the open task dialog's ``text`` button, leaving what it sets
    off for the caller to wait on. In a fresh profile FreeCAD 1.1 docks
    Tasks in the right-hand overlay panel, which stays hidden until hovered,
    so the button is pressed with ``click``, the signal a mouse click on it
    emits."""
    main_window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    (button,) = [
        button
        for box in main_window.findChildren(QtWidgets.QDialogButtonBox)
        for button in box.buttons()
        if button.text() == text
    ]
    button.click()


def click_task_button(text: str, driver: ViewDriver) -> None:
    """Press the open task dialog's ``text`` button and wait until what it
    set off has run, a camera turn back included."""
    press_task_button(text)
    driver.pump()


def notification_count() -> int:
    main_window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    button = main_window.statusBar().findChild(
        QtWidgets.QPushButton, "notificationArea"
    )
    assert button is not None
    text = button.text()
    return int(text) if text.isdigit() else 0


class _CommandStates(Protocol):
    def isCommandActive(self, name: str, /) -> bool: ...


def command_active(name: str) -> bool:
    """Whether FreeCAD would run the command ``name`` now."""
    # freecad-stubs leaves isCommandActive out of FreeCADGui.
    return cast("_CommandStates", FreeCADGui).isCommandActive(name)


def gui_step(command: str, driver: ViewDriver) -> None:
    """Run ``Std_Undo`` or ``Std_Redo`` as a user does, with keyboard focus
    in the 3D view: FreeCAD disables both while it sits in one of a task
    panel's widgets, such as a basis menu."""
    driver.viewport.setFocus()
    driver.pump()
    assert command_active(command), command
    FreeCADGui.runCommand(command)
    driver.pump()


def editor_of(panel: EditUnitPanel) -> ViewEditor:
    assert panel.editor is not None
    return panel.editor


def bay_ids(region: Region) -> list[str]:
    """Every ``Bay`` id under ``region``, in run order: lowest first."""
    if isinstance(region, Bay):
        return [region.id]
    if not isinstance(region, Division):
        return []
    return [
        bay_id
        for item in region.items
        if not isinstance(item, Board)
        for bay_id in bay_ids(item)
    ]


def click_region(panel: EditUnitPanel, region_id: str, driver: ViewDriver) -> None:
    """Click the middle of the opening ``region_id`` in the view."""
    editor = editor_of(panel)
    rect = editor.frame.rect(panel.session.spaces[region_id])
    driver.click(editor.to_document(*rect.center_mm))


def add_board(
    panel: EditUnitPanel, direction: SplitDirection, driver: ViewDriver
) -> str:
    """Select the first bay and press its in-view add button for
    ``direction``; returns the new board, which the editor selects."""
    click_region(panel, bay_ids(panel.session.unit.root)[0], driver)
    editor_of(panel).add_bar.buttons[direction].click()
    driver.pump()
    selected = panel.session.selected_id
    assert selected is not None
    return selected


def press_delete(driver: ViewDriver) -> None:
    driver.key(QtCore.Qt.Key.Key_Delete)
    driver.pump()
