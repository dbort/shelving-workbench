"""The Edit Unit panel's constraint list and the 3D view selecting together:
a row picks its constraint or opening in the view, and a pick in the view
picks its row."""

import FreeCAD
from PySide6 import QtCore

from freecad.Shelving.core.layout import Board, Division, Region
from freecad.Shelving.editor.panel import EditUnitPanel
from tests.freecad_view.editor import (
    bay_ids,
    board_targets,
    click_region,
    click_task_button,
    edit_unit,
    editor_of,
    zoom_on,
)
from tests.freecad_view.view import ViewDriver


def _column(
    container: FreeCAD.DocumentObject, driver: ViewDriver
) -> tuple[EditUnitPanel, list[str]]:
    """Edit Unit with the bay split into a column of three, A locked, an
    Equal on A and B and an even spacing over all three, and A, B and C
    bottom to top: rows Equal, Even spacing, lock A."""
    panel = edit_unit(container, driver)
    session = panel.session
    session.select(bay_ids(session.unit.root)[0])
    assert session.split("vertical") is None
    session.select(bay_ids(session.unit.root)[1])
    assert session.split("vertical") is None
    a, b, c = bay_ids(session.unit.root)
    session.select_items([a, b])
    panel.constrain("equal_height")
    session.select_items([a, c])
    panel.constrain("even_height")
    assert session.set_lock(a, locked=True) is None
    session.select(None)
    panel._refresh()
    driver.pump()
    return panel, [a, b, c]


def _click_row(
    panel: EditUnitPanel, index: int, driver: ViewDriver, adding: bool = False
) -> None:
    """Select row ``index`` as a click on it does, or a Ctrl-click when
    ``adding``. Under Xvfb the task panel docks in an overlay that stays
    hidden until hovered (bug-011), so no mouse event reaches the list;
    the selection model gets the commands an extended-selection click
    gives it."""
    tree = panel.constraint_list.tree
    item = tree.topLevelItem(index)
    assert item is not None
    flag = QtCore.QItemSelectionModel.SelectionFlag
    command = (flag.Toggle if adding else flag.ClearAndSelect) | flag.Rows
    tree.setCurrentItem(item, 0, command)
    driver.pump()


def _board_after(region: Region, region_id: str) -> str | None:
    """The board just after ``region_id`` in its run, if one is."""
    if not isinstance(region, Division):
        return None
    for index, item in enumerate(region.items):
        if item.id == region_id:
            after = region.items[index + 1] if index + 1 < len(region.items) else None
            return after.id if isinstance(after, Board) else None
        if not isinstance(item, Board):
            found = _board_after(item, region_id)
            if found is not None:
                return found
    return None


def _selected_rows(panel: EditUnitPanel) -> list[int]:
    tree = panel.constraint_list.tree
    return [
        index
        for index in range(tree.topLevelItemCount())
        if (item := tree.topLevelItem(index)) is not None and item.isSelected()
    ]


def test_rows_select_their_constraints_in_the_view(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (_a, _b, _c) = _column(unit, driver)
    session = panel.session
    equal, spacing, lock = session.constraints
    _click_row(panel, 0, driver)
    assert session.selected_constraints == (equal.id,)
    assert session.selected_items == ()
    _click_row(panel, 1, driver, adding=True)
    assert session.selected_constraints == (equal.id, spacing.id)
    assert _selected_rows(panel) == [0, 1]
    _click_row(panel, 2, driver)
    assert session.selected_constraints == (lock.id,)
    assert session.selected_items == ()
    assert _selected_rows(panel) == [2]
    click_task_button("Close", driver)


def test_picks_in_the_view_select_their_rows(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, _c) = _column(unit, driver)
    session = panel.session
    editor = editor_of(panel)
    _equal, spacing, _lock = session.constraints
    icon = next(
        node.icon for node in editor.icon_nodes if node.icon.constraint_id == spacing.id
    )
    driver.click(editor.icon_center(icon))
    assert session.selected_constraints == (spacing.id,)
    assert _selected_rows(panel) == [1]
    click_region(panel, a, driver)
    assert session.selected_items == (a,)
    assert _selected_rows(panel) == []
    click_region(panel, b, driver)
    assert _selected_rows(panel) == []
    shelf = _board_after(session.unit.root, a)
    assert shelf is not None
    driver.click(editor.icon_center(icon))
    assert _selected_rows(panel) == [1]
    zoom_on(editor, shelf, 300.0, driver)
    driver.click(board_targets(editor, shelf)["Face"])
    assert session.selected_items == (shelf,)
    assert _selected_rows(panel) == []
    click_task_button("Close", driver)
