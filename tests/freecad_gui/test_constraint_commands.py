"""Constrain Equal and Constrain Even Spacing as FreeCAD commands: the
toolbar Edit Unit shows while it is open, the Shelving menu, when the
commands are active, and how they refuse a selection they cannot use."""

from collections.abc import Iterator
from typing import cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtWidgets

from freecad.Shelving import init_gui
from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.panel import (
    CONSTRAINT_TOOLBAR_COMMANDS,
    CONSTRAINT_TOOLBAR_NAME,
    EditUnitPanel,
    active_panel,
)
from freecad.Shelving.unit_ops import create_unit

_COMMANDS = ("Shelving_ConstrainEqual", "Shelving_ConstrainEvenSpacing")


def _process_events() -> None:
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    # Outside an event loop, processEvents leaves deleteLater undone.
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _main_window() -> QtWidgets.QMainWindow:
    return cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())


def _toolbar() -> QtWidgets.QToolBar | None:
    return _main_window().findChild(QtWidgets.QToolBar, CONSTRAINT_TOOLBAR_NAME)


def _is_active(name: str) -> bool:
    return FreeCADGui.Command.get(name).isActive()


def _bay_ids(region: Region) -> list[str]:
    if isinstance(region, Bay):
        return [region.id]
    if isinstance(region, Division):
        return [
            bay_id
            for item in region.items
            if not isinstance(item, Board)
            for bay_id in _bay_ids(item)
        ]
    return []


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(panel_module, "report_error", messages.append)
    return messages


@pytest.fixture
def editing(
    request: pytest.FixtureRequest, reported: list[str]
) -> Iterator[EditUnitPanel]:
    """An open Edit Unit panel on a unit whose one bay is split by a shelf,
    with the Shelving workbench active."""
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = FreeCAD.newDocument(request.node.name)
    container = create_unit(doc)
    doc.recompute()
    panel = EditUnitPanel(container)
    try:
        panel.session.select(_bay_ids(panel.session.unit.root)[0])
        assert panel.session.split("vertical") is None
        _process_events()
        yield panel
    finally:
        panel.reject()
        _process_events()
        FreeCAD.closeDocument(doc.Name)
        FreeCADGui.activateWorkbench("ShelvingWorkbench")


def test_the_panel_toolbar_holds_the_menus_constraint_commands() -> None:
    assert CONSTRAINT_TOOLBAR_COMMANDS == init_gui.CONSTRAINT_COMMANDS == _COMMANDS


def test_the_commands_are_in_the_menu_and_inactive_outside_an_edit() -> None:
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    _process_events()
    menus = [
        cast("QtWidgets.QMenu", action.menu())
        for action in _main_window().menuBar().actions()
        if action.text().replace("&", "") == "Shelving"
    ]
    (menu,) = menus
    texts = [action.text() for action in menu.actions()]
    assert "Constrain Equal" in texts
    assert "Constrain Even Spacing" in texts
    assert active_panel() is None
    for name in _COMMANDS:
        assert not _is_active(name)
    assert _toolbar() is None


def test_the_toolbar_shows_exactly_while_an_edit_is_open_in_any_workbench(
    editing: EditUnitPanel,
) -> None:
    toolbar = _toolbar()
    assert toolbar is not None
    assert not toolbar.isHidden()
    assert [action.text() for action in toolbar.actions()] == [
        "Constrain Equal",
        "Constrain Even Spacing",
    ]
    for name in _COMMANDS:
        assert _is_active(name)
    for workbench in ("PartWorkbench", "NoneWorkbench", "ShelvingWorkbench"):
        FreeCADGui.activateWorkbench(workbench)
        _process_events()
        toolbar = _toolbar()
        assert toolbar is not None and not toolbar.isHidden(), workbench
    editing.reject()
    _process_events()
    assert _toolbar() is None
    for name in _COMMANDS:
        assert not _is_active(name)


@pytest.mark.parametrize("name", _COMMANDS)
def test_a_selection_a_command_cannot_use_is_refused_saying_what_to_select(
    editing: EditUnitPanel, reported: list[str], name: str
) -> None:
    lower = _bay_ids(editing.session.unit.root)[0]
    editing.session.select(lower)
    FreeCADGui.runCommand(name)
    _process_events()
    assert len(reported) == 1
    assert "Select" in reported[0], reported
    assert editing.session.constraints == ()


@pytest.mark.parametrize("name", _COMMANDS)
def test_a_command_constrains_the_selected_openings(
    editing: EditUnitPanel, reported: list[str], name: str
) -> None:
    editing.session.select_items(_bay_ids(editing.session.unit.root))
    FreeCADGui.runCommand(name)
    _process_events()
    assert reported == []
    (constraint,) = editing.session.constraints
    assert constraint.active
    assert editing.session.selected_items == ()
