"""Lock Width, Lock Height, Constrain Equal and Constrain Even Spacing as
FreeCAD commands: the toolbar Edit Unit shows while it is open, the
Shelving menu, when the commands are active, what the Lock commands lock,
and how the commands refuse a selection they cannot use."""

from collections.abc import Iterator
from typing import cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtWidgets

from freecad.Shelving import init_gui
from freecad.Shelving.container import write_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Bay,
    Board,
    Division,
    Lock,
    Region,
    Unit,
)
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.panel import (
    CONSTRAINT_TOOLBAR_COMMANDS,
    CONSTRAINT_TOOLBAR_NAME,
    EditUnitPanel,
    active_panel,
)
from freecad.Shelving.unit_ops import create_unit

_COMMANDS = ("Shelving_ConstrainEqual", "Shelving_ConstrainEvenSpacing")
_LOCK_COMMANDS = ("Shelving_LockWidth", "Shelving_LockHeight")
_ALL_COMMANDS = (*_LOCK_COMMANDS, *_COMMANDS)
_T_MM = 18.0


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
    assert CONSTRAINT_TOOLBAR_COMMANDS == init_gui.CONSTRAINT_COMMANDS == _ALL_COMMANDS


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
    for text in (
        "Lock Width",
        "Lock Height",
        "Constrain Equal",
        "Constrain Even Spacing",
    ):
        assert text in texts, text
    assert active_panel() is None
    for name in _ALL_COMMANDS:
        assert not _is_active(name)
    assert _toolbar() is None


def test_the_toolbar_shows_exactly_while_an_edit_is_open_in_any_workbench(
    editing: EditUnitPanel,
) -> None:
    toolbar = _toolbar()
    assert toolbar is not None
    assert not toolbar.isHidden()
    assert [action.text() for action in toolbar.actions()] == [
        "Lock Width",
        "Lock Height",
        "Constrain Equal",
        "Constrain Even Spacing",
    ]
    for name in _ALL_COMMANDS:
        assert _is_active(name)
    for workbench in ("PartWorkbench", "NoneWorkbench", "ShelvingWorkbench"):
        FreeCADGui.activateWorkbench(workbench)
        _process_events()
        toolbar = _toolbar()
        assert toolbar is not None and not toolbar.isHidden(), workbench
    editing.reject()
    _process_events()
    assert _toolbar() is None
    for name in _ALL_COMMANDS:
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


@pytest.mark.parametrize(
    "name",
    [
        pytest.param(
            _COMMANDS[0], marks=pytest.mark.smoke("constrain selected openings equal")
        ),
        *_COMMANDS[1:],
    ],
)
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


def _columns() -> Unit:
    """A unit 654 mm tall of 18 mm boards, split by two dividers into three
    300 mm columns L, M and R, each split by one shelf: A1 300, A2 300;
    B1 200, B2 400; C1 250, C2 350, bottom to top."""

    def column(sizes_mm: tuple[float, float], shelf: str) -> Division:
        return Division(
            axis=Axis.Z,
            items=[
                Bay(size_mm=sizes_mm[0]),
                Board(thickness_mm=_T_MM, role=shelf),
                Bay(size_mm=sizes_mm[1]),
            ],
            size_mm=300.0,
        )

    return Unit(
        size_mm=Vec3(972.0, 300.0, 654.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=_T_MM, role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(thickness_mm=_T_MM, role="left_side"),
                        column((300.0, 300.0), "s1"),
                        Board(thickness_mm=_T_MM, role="d1"),
                        column((200.0, 400.0), "t1"),
                        Board(thickness_mm=_T_MM, role="d2"),
                        column((250.0, 350.0), "u1"),
                        Board(thickness_mm=_T_MM, role="right_side"),
                    ],
                    size_mm=618.0,
                ),
                Board(thickness_mm=_T_MM, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
        front_at_min=None,
    )


@pytest.fixture
def columns(
    request: pytest.FixtureRequest, reported: list[str]
) -> Iterator[EditUnitPanel]:
    """An open Edit Unit panel on :func:`_columns`."""
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = FreeCAD.newDocument(request.node.name)
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    write_container(container, _columns())
    doc.recompute()
    panel = EditUnitPanel(container)
    try:
        _process_events()
        yield panel
    finally:
        panel.reject()
        _process_events()
        FreeCAD.closeDocument(doc.Name)
        FreeCADGui.activateWorkbench("ShelvingWorkbench")


def _left(panel: EditUnitPanel) -> tuple[str, str, str]:
    """The ids of column L and of its lower and upper bays, A1 and A2."""
    root = panel.session.unit.root
    assert isinstance(root, Division)
    row = root.items[1]
    assert isinstance(row, Division)
    left = row.items[1]
    assert isinstance(left, Division)
    lower, _shelf, upper = left.items
    return left.id, lower.id, upper.id


def _boards(panel: EditUnitPanel) -> dict[str, tuple[float, float, float]]:
    found: dict[str, tuple[float, float, float]] = {}
    for obj in panel.session.container.Document.Objects:
        if obj.TypeId == "Part::Box":
            base = obj.Placement.Base
            found[obj.Name] = (base.x, base.y, base.z)
    return found


def _locks(panel: EditUnitPanel) -> list[str]:
    return [c.region_id for c in panel.session.constraints if isinstance(c, Lock)]


@pytest.mark.parametrize(
    ("name", "step", "locked"),
    [
        pytest.param(
            "Shelving_LockWidth",
            "Lock Width",
            "L",
            marks=pytest.mark.smoke("lock the width of a selected opening"),
        ),
        ("Shelving_LockHeight", "Lock Height", "A1"),
    ],
)
def test_lock_width_locks_the_column_and_lock_height_the_bay(
    columns: EditUnitPanel, reported: list[str], name: str, step: str, locked: str
) -> None:
    _left_id, a1, _a2 = _left(columns)
    doc = columns.session.container.Document
    boards = _boards(columns)
    columns.session.select(a1)
    steps = doc.UndoCount
    FreeCADGui.runCommand(name)
    _process_events()
    assert reported == []
    # The edit rescans, so the ids are read again.
    left, a1, _a2 = _left(columns)
    assert _locks(columns) == [{"L": left, "A1": a1}[locked]]
    assert doc.UndoCount == steps + 1
    assert doc.UndoNames[0] == step
    assert _boards(columns) == boards
    doc.undo()
    _process_events()
    columns.session.settle()
    assert _locks(columns) == []


def test_two_openings_in_one_column_make_one_width_lock(
    columns: EditUnitPanel, reported: list[str]
) -> None:
    _left_id, a1, a2 = _left(columns)
    columns.session.select_items([a1, a2])
    FreeCADGui.runCommand("Shelving_LockWidth")
    _process_events()
    assert reported == []
    assert _locks(columns) == [_left(columns)[0]]


@pytest.mark.parametrize("name", _LOCK_COMMANDS)
def test_a_lock_command_refuses_a_board_or_nothing_saying_to_select_openings(
    columns: EditUnitPanel, reported: list[str], name: str
) -> None:
    columns.session.select("s1")
    FreeCADGui.runCommand(name)
    columns.session.select(None)
    FreeCADGui.runCommand(name)
    _process_events()
    assert len(reported) == 2
    for message in reported:
        assert "Select one or more openings" in message, message
    assert _locks(columns) == []


def test_lock_width_refuses_a_bay_with_no_divider_naming_the_width_field(
    editing: EditUnitPanel, reported: list[str]
) -> None:
    editing.session.select(_bay_ids(editing.session.unit.root)[0])
    FreeCADGui.runCommand("Shelving_LockWidth")
    _process_events()
    assert len(reported) == 1
    assert "panel's Width field" in reported[0], reported
    assert editing.session.constraints == ()
