"""Several boards selected at once in the 3D view, under CAD navigation, on
the Woodworking workbench's Magic Start unit: FreeCAD's own selection
gestures make the selection, the single-item controls step aside, and
Delete removes every selected board or none."""

from typing import cast

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtWidgets

from freecad.Shelving.editor.elevation import board_ids
from freecad.Shelving.editor.panel import EditUnitPanel
from tests.freecad_view.editor import (
    add_board,
    bay_ids,
    board_targets,
    click_region,
    click_task_button,
    edit_unit,
    editor_of,
    gui_step,
    press_delete,
    selection,
)
from tests.freecad_view.view import ViewDriver

_CTRL = QtCore.Qt.KeyboardModifier.ControlModifier


def _freecad_boards(panel: EditUnitPanel) -> set[str]:
    """The unit's boards FreeCAD's selection names, whole or by an element,
    directly or through the link group holding them."""
    boards = board_ids(panel.session.unit)
    names: set[str] = set()
    for obj, subs in selection():
        for path in (obj, *(part for sub in subs for part in sub.split(".")[:-1])):
            if path in boards:
                names.add(path)
    return names


def _face(panel: EditUnitPanel, board_id: str) -> FreeCAD.Vector:
    return board_targets(editor_of(panel), board_id)["Face"]


def _assert_mirrored(panel: EditUnitPanel, expected: tuple[str, ...]) -> None:
    assert panel.session.selected_boards == expected
    assert _freecad_boards(panel) == set(expected)


def test_ctrl_click_adds_a_board_and_removes_a_selected_one(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    panel = edit_unit(container, driver)
    session = panel.session
    shelf, top = _face(panel, "Shelf"), _face(panel, "Top")
    driver.click(shelf)
    _assert_mirrored(panel, ("Shelf",))
    assert session.selected_id == "Shelf"
    driver.click(top, _CTRL)
    _assert_mirrored(panel, ("Shelf", "Top"))
    assert session.selected_id is None
    driver.click(shelf, _CTRL)
    _assert_mirrored(panel, ("Top",))
    assert session.selected_id == "Top"
    driver.click(shelf, _CTRL)
    _assert_mirrored(panel, ("Top", "Shelf"))
    driver.click(top, _CTRL)
    driver.click(shelf, _CTRL)
    _assert_mirrored(panel, ())
    click_task_button("Close", driver)


def _tree_items(labels: set[str]) -> list[QtWidgets.QTreeWidgetItem]:
    main_window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    found: list[QtWidgets.QTreeWidgetItem] = []
    for tree in main_window.findChildren(QtWidgets.QTreeWidget):
        iterator = QtWidgets.QTreeWidgetItemIterator(tree)
        while iterator.value() is not None:
            item = iterator.value()
            if item.text(0) in labels:
                found.append(item)
            iterator += 1
    return found


def test_two_boards_selected_in_the_tree_are_the_sessions_selection(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    panel = edit_unit(container, driver)
    doc = container.Document
    labels = {doc.getObject(name).Label for name in ("Shelf", "Top")}
    items = _tree_items(labels)
    assert len(items) == 2
    tree = items[0].treeWidget()
    assert tree is not None
    tree.clearSelection()
    for item in items:
        item.setSelected(True)
    driver.pump()
    assert sorted(panel.session.selected_boards) == ["Shelf", "Top"]
    assert panel.session.selected_id is None
    click_task_button("Close", driver)


def test_ctrl_click_on_an_opening_keeps_the_boards(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    """Every opening has the back panel behind it, which FreeCAD's own
    Ctrl-click adds to its selection."""
    container, driver = magic_start
    panel = edit_unit(container, driver)
    editor = editor_of(panel)
    session = panel.session
    driver.click(_face(panel, "Shelf"))
    driver.click(_face(panel, "Top"), _CTRL)
    upper = bay_ids(session.unit.root)[1]
    driver.click(
        editor.to_document(*editor.frame.rect(session.spaces[upper]).center_mm),
        _CTRL,
    )
    driver.pump()
    _assert_mirrored(panel, ("Shelf", "Top"))
    assert all(obj != "Back" for obj, _subs in selection())
    click_task_button("Close", driver)


def test_a_plain_click_returns_to_a_single_selection(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    panel = edit_unit(container, driver)
    session = panel.session
    for name in ("Shelf", "Top"):
        driver.click(_face(panel, name), _CTRL)
    _assert_mirrored(panel, ("Shelf", "Top"))
    driver.click(_face(panel, "Floor"))
    _assert_mirrored(panel, ("Floor",))
    assert session.selected_id == "Floor"
    driver.click(_face(panel, "Top"), _CTRL)
    lower = bay_ids(session.unit.root)[0]
    click_region(panel, lower, driver)
    driver.pump()
    assert session.selected_id == lower
    _assert_mirrored(panel, ())
    click_task_button("Close", driver)


def test_a_dimension_click_returns_to_its_region(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    panel = edit_unit(container, driver)
    editor = editor_of(panel)
    session = panel.session
    driver.click(_face(panel, "Shelf"))
    driver.click(_face(panel, "Top"), _CTRL)
    label = editor.overlay.labels[0]
    driver.click(driver.qt_point(editor.to_document(*label.text_at_mm)))
    driver.pump()
    assert session.selected_id == label.region_id
    _assert_mirrored(panel, ())
    click_task_button("Close", driver)


def test_several_boards_show_no_arrow_and_no_add_buttons(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    panel = edit_unit(container, driver)
    editor = editor_of(panel)
    driver.click(_face(panel, "Shelf"))
    assert editor.arrow is not None
    driver.click(_face(panel, "Floor"), _CTRL)
    _assert_mirrored(panel, ("Shelf", "Floor"))
    assert editor.arrow is None
    assert not editor.add_bar.isVisible()
    assert not editor.board_padlock.isVisible()
    click_task_button("Close", driver)


def test_delete_removes_two_inner_boards_as_one_step(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    doc = container.Document
    panel = edit_unit(container, driver)
    added = add_board(panel, "vertical", driver)
    driver.click(_face(panel, "Shelf"), _CTRL)
    _assert_mirrored(panel, (added, "Shelf"))
    names = list(doc.UndoNames)
    press_delete(driver)
    assert list(doc.UndoNames) == ["Delete Boards", *names]
    assert doc.getObject(added) is None
    assert doc.getObject("Shelf") is None
    _assert_mirrored(panel, ())
    gui_step("Std_Undo", driver)
    assert doc.getObject(added) is not None
    assert doc.getObject("Shelf") is not None
    assert {added, "Shelf"} <= board_ids(panel.session.unit)
    click_task_button("Close", driver)


def test_delete_with_a_carcass_board_refuses_them_all_once(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
    reported: list[str],
) -> None:
    container, driver = magic_start
    doc = container.Document
    panel = edit_unit(container, driver)
    driver.click(_face(panel, "Shelf"))
    driver.click(_face(panel, "Left"), _CTRL)
    _assert_mirrored(panel, ("Shelf", "Left"))
    names = list(doc.UndoNames)
    press_delete(driver)
    # Recorded rather than counted: the Notification Area does not count a
    # message an earlier test already showed (xvfb-gui-testing.md).
    assert len(reported) == 1
    assert "end of its row" in reported[0]
    assert list(doc.UndoNames) == names
    assert doc.getObject("Shelf") is not None
    _assert_mirrored(panel, ("Shelf", "Left"))
    click_task_button("Close", driver)


def test_a_stock_row_selects_its_boards_whole_with_the_view_open(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    panel = edit_unit(container, driver)
    session = panel.session
    editor = editor_of(panel)

    def click_row(index: int) -> QtWidgets.QTreeWidgetItem:
        row = panel.stock_list.topLevelItem(index)
        assert row is not None
        panel.stock_list.itemClicked.emit(row, 0)
        driver.pump()
        return row

    (group,) = session.stock_groups()
    row = click_row(0)
    assert set(session.selected_boards) == set(group.board_ids)
    assert _freecad_boards(panel) == set(group.board_ids)
    assert all(subs == () for _obj, subs in selection())
    assert row.isSelected()
    assert editor.arrow is None
    editor.select("Shelf")
    assert session.swap_stock(thickness_mm=12.0) is None
    driver.pump()
    panel._refresh()
    row = click_row(1)
    assert session.selected_boards == ("Shelf",)
    assert selection() == [("Shelf", ())]
    assert row.isSelected()
    assert editor.arrow is not None and editor.arrow.board_id == "Shelf"
    click_task_button("Close", driver)
