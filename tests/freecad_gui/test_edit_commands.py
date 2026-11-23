"""The commands that edit the open unit, as FreeCAD commands: the toolbar
Edit Unit shows while it is open, the Shelving menu, when the commands are
active, what the add, Lock, Equal and Even commands do, and how the commands
refuse a selection they cannot use."""

import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtWidgets

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
    constraint_regions,
)
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.elevation import board_ids
from freecad.Shelving.editor.panel import (
    EDIT_TOOLBAR_NAME,
    EditUnitPanel,
    active_panel,
)
from freecad.Shelving.editor.session import EDIT_COMMANDS
from freecad.Shelving.unit_ops import create_unit

_COMMANDS = (
    "Shelving_ConstrainEqualWidth",
    "Shelving_ConstrainEqualHeight",
    "Shelving_ConstrainEvenSpacing",
)
_LOCK_COMMANDS = ("Shelving_LockWidth", "Shelving_LockHeight")
_ADD_COMMANDS = (
    ("Shelving_AddShelf", "Add Shelf"),
    ("Shelving_AddDivider", "Add Divider"),
)
_ALL_COMMANDS = tuple(name for name in EDIT_COMMANDS if name != "Separator")
_MENU_TEXTS = [
    "Add Shelf",
    "Add Divider",
    "Lock Width",
    "Lock Height",
    "Equal Width",
    "Equal Height",
    "Even Spacing",
]
_T_MM = 18.0


def _process_events() -> None:
    for _ in range(5):
        QtWidgets.QApplication.processEvents()
    # Outside an event loop, processEvents leaves deleteLater undone.
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _main_window() -> QtWidgets.QMainWindow:
    return cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())


def _toolbar() -> QtWidgets.QToolBar | None:
    return _main_window().findChild(QtWidgets.QToolBar, EDIT_TOOLBAR_NAME)


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


def test_the_commands_are_in_the_menu_and_inactive_outside_an_edit() -> None:
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    _process_events()
    menus = [
        cast("QtWidgets.QMenu", action.menu())
        for action in _main_window().menuBar().actions()
        if action.text().replace("&", "") == "Shelving"
    ]
    (menu,) = menus
    texts = [action.text() for action in menu.actions() if not action.isSeparator()]
    start = texts.index(_MENU_TEXTS[0])
    assert texts[start : start + len(_MENU_TEXTS)] == _MENU_TEXTS
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
    actions = toolbar.actions()
    assert [a.text() for a in actions if not a.isSeparator()] == _MENU_TEXTS
    assert actions[2].isSeparator()
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
    assert editing.toolbar is None
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


@contextmanager
def _editing(name: str, unit: Unit) -> Iterator[EditUnitPanel]:
    """An open Edit Unit panel on ``unit``, written to a new document."""
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = FreeCAD.newDocument(name)
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    write_container(container, unit)
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


@pytest.fixture
def columns(
    request: pytest.FixtureRequest, reported: list[str]
) -> Iterator[EditUnitPanel]:
    """An open Edit Unit panel on :func:`_columns`."""
    with _editing(request.node.name, _columns()) as panel:
        yield panel


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


def test_each_constraint_command_has_its_own_icon() -> None:
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    pixmaps = [FreeCADGui.Command.get(name).getInfo()["pixmap"] for name in _COMMANDS]
    assert len(set(pixmaps)) == len(_COMMANDS)
    for pixmap in pixmaps:
        assert not FreeCADGui.getIcon(pixmap).isNull(), pixmap


def test_even_spacing_replaces_even_width_and_even_height() -> None:
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    info = FreeCADGui.Command.get("Shelving_ConstrainEvenSpacing").getInfo()
    assert os.path.basename(info["pixmap"]) == "Constraint_EvenSpacing.svg"
    # The FreeCADGui stubs leave out listCommands, which FreeCAD itself has.
    commands = FreeCADGui.listCommands()  # pyrefly: ignore[missing-attribute]
    # Built from parts, so a grep for the retired ids finds only real uses.
    for direction in ("Width", "Height"):
        assert f"Shelving_ConstrainEven{direction}" not in commands


# Indices into the columns unit's bays A1, A2, B1, B2, C1, C2.
@pytest.mark.parametrize(
    ("name", "step", "picks", "regions"),
    [
        pytest.param(
            "Shelving_ConstrainEqualWidth",
            "Equal Width",
            (0, 2),
            ("L", "M"),
            marks=pytest.mark.smoke("make the widths of two columns equal"),
        ),
        ("Shelving_ConstrainEqualHeight", "Equal Height", (0, 2), ("A1", "B1")),
        ("Shelving_ConstrainEvenSpacing", "Even Width", (0, 4), ("L", "M", "R")),
        ("Shelving_ConstrainEvenSpacing", "Even Height", (0, 1), ("A1", "A2")),
    ],
)
def test_a_constraint_command_resolves_each_pick_along_its_axis(
    columns: EditUnitPanel,
    reported: list[str],
    name: str,
    step: str,
    picks: tuple[int, ...],
    regions: tuple[str, ...],
) -> None:
    session = columns.session
    doc = session.container.Document
    bays = _bay_ids(session.unit.root)
    steps = doc.UndoCount
    session.select_items([bays[index] for index in picks])
    FreeCADGui.runCommand(name)
    _process_events()
    assert reported == []
    assert doc.UndoCount == steps + 1
    assert doc.UndoNames[0] == step
    assert session.selected_items == ()
    (constraint,) = session.constraints
    assert constraint.active
    # The edit rescans, so the ids are read again.
    root = session.unit.root
    assert isinstance(root, Division)
    row = root.items[1]
    assert isinstance(row, Division)
    names = {"L": row.items[1].id, "M": row.items[3].id, "R": row.items[5].id}
    bays = _bay_ids(root)
    names.update(zip(("A1", "A2", "B1", "B2", "C1", "C2"), bays, strict=True))
    assert constraint_regions(session.unit, constraint) == tuple(
        names[region] for region in regions
    )


@pytest.mark.parametrize(
    ("name", "select", "says"),
    [
        ("Shelving_ConstrainEqualWidth", ("s1",), "not boards"),
        ("Shelving_ConstrainEqualHeight", ("s1",), "not boards"),
        # Shelves of two columns lie in different runs.
        ("Shelving_ConstrainEvenSpacing", ("s1", "t1"), "two shelves of one column"),
    ],
)
def test_a_constraint_command_refuses_boards_it_cannot_use(
    columns: EditUnitPanel,
    reported: list[str],
    name: str,
    select: tuple[str, ...],
    says: str,
) -> None:
    columns.session.select_items(list(select))
    FreeCADGui.runCommand(name)
    _process_events()
    assert len(reported) == 1
    assert "Select" in reported[0] and says in reported[0], reported
    assert columns.session.constraints == ()


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


@pytest.mark.parametrize(
    ("name", "step"),
    [
        pytest.param(
            *_ADD_COMMANDS[0],
            marks=pytest.mark.smoke("add a shelf to each selected bay"),
        ),
        _ADD_COMMANDS[1],
    ],
)
def test_an_add_command_splits_every_selected_bay_in_one_step(
    columns: EditUnitPanel, reported: list[str], name: str, step: str
) -> None:
    session = columns.session
    doc = session.container.Document
    a1, b1 = _bay_ids(session.unit.root)[0], _bay_ids(session.unit.root)[2]
    before = board_ids(session.unit)
    steps = doc.UndoCount
    session.select_items([a1, b1])
    FreeCADGui.runCommand(name)
    _process_events()
    assert reported == []
    assert doc.UndoCount == steps + 1
    assert doc.UndoNames[0] == step
    added = board_ids(session.unit) - before
    assert len(added) == 2
    assert set(session.selected_items) == added


def _thin_bay() -> Unit:
    """A unit whose narrow left column, 10 mm wide, holds a 10 mm square
    bay under a shelf, too small for an 18 mm board either way, beside a
    300 mm wide bay."""
    return Unit(
        size_mm=Vec3(364.0, 300.0, 364.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=_T_MM, role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(thickness_mm=_T_MM, role="left_side"),
                        Division(
                            axis=Axis.Z,
                            items=[
                                Bay(size_mm=10.0),
                                Board(thickness_mm=_T_MM, role="s1"),
                                Bay(size_mm=300.0),
                            ],
                            size_mm=10.0,
                        ),
                        Board(thickness_mm=_T_MM, role="d1"),
                        Bay(size_mm=300.0),
                        Board(thickness_mm=_T_MM, role="right_side"),
                    ],
                    size_mm=328.0,
                ),
                Board(thickness_mm=_T_MM, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
        front_at_min=None,
    )


@pytest.mark.parametrize(("name", "_step"), _ADD_COMMANDS)
def test_an_add_command_refuses_nothing_a_board_or_a_thin_bay_changing_nothing(
    request: pytest.FixtureRequest, reported: list[str], name: str, _step: str
) -> None:
    with _editing(request.node.name, _thin_bay()) as panel:
        session = panel.session
        doc = session.container.Document
        thin, _narrow, roomy = _bay_ids(session.unit.root)
        names = list(doc.UndoNames)
        selections: list[list[str]] = [[], [roomy, "s1"], [roomy, thin]]
        for selection in selections:
            unit = session.unit
            session.select_items(selection)
            FreeCADGui.runCommand(name)
            _process_events()
            assert session.unit is unit, selection
            assert list(doc.UndoNames) == names, selection
        assert len(reported) == 3
