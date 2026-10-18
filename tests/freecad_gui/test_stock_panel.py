"""The panel's Stock group and its Change Stock dialog, with FreeCAD's GUI
up and no 3D view, as ``tests/freecad_gui/test_panel.py`` builds the
panel."""

from collections.abc import Iterator

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.panel import STOCK_COLUMNS, EditUnitPanel
from freecad.Shelving.editor.stock_dialog import StockDialog
from freecad.Shelving.unit_ops import create_unit
from tests.freecad_materials import library_material

_UNIT_BOARDS = ("bottom", "left_side", "right_side", "top")


def _process_events() -> None:
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def _first_bay(region: Region) -> str:
    if isinstance(region, Bay):
        return region.id
    assert isinstance(region, Division)
    return next(
        _first_bay(item)
        for item in region.items
        if not isinstance(item, Board) and _holds_bay(item)
    )


def _holds_bay(region: Region) -> bool:
    if isinstance(region, Bay):
        return True
    return isinstance(region, Division) and any(
        _holds_bay(item) for item in region.items if not isinstance(item, Board)
    )


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every message the panel sends to FreeCAD's Notification Area, which
    records nothing under the offscreen GUI."""
    messages: list[str] = []
    monkeypatch.setattr(panel_module, "report_error", messages.append)
    return messages


@pytest.fixture
def panel(
    request: pytest.FixtureRequest, reported: list[str]
) -> Iterator[EditUnitPanel]:
    """A panel on a new unit holding one shelf, its only stock that of the
    four boards around it."""
    doc = FreeCAD.newDocument(request.node.name)
    container = create_unit(doc)
    doc.recompute()
    opened = EditUnitPanel(container)
    opened.form.resize(900, 1400)
    opened.form.show()
    _process_events()
    opened.session.select(_first_bay(opened.session.unit.root))
    assert opened.session.split("vertical") is None
    opened._refresh()
    try:
        yield opened
    finally:
        opened.reject()
        FreeCADGui.Selection.clearSelection()
        FreeCAD.closeDocument(doc.Name)


def _shelf(panel: EditUnitPanel) -> str:
    (shelf,) = set(panel.session.stock_groups()[0].board_ids) - set(_UNIT_BOARDS)
    return shelf


def _rows(panel: EditUnitPanel) -> list[QtWidgets.QTreeWidgetItem]:
    stock_list = panel.stock_list
    return [
        item
        for index in range(stock_list.topLevelItemCount())
        if (item := stock_list.topLevelItem(index)) is not None
    ]


def _freecad_selection(doc: FreeCAD.Document) -> list[str]:
    return sorted(obj.Name for obj in FreeCADGui.Selection.getSelection(doc.Name))


def _swap(panel: EditUnitPanel, board_ids: list[str], thickness_mm: float) -> None:
    panel.session.select_boards(board_ids)
    assert panel.session.swap_stock(thickness_mm=thickness_mm) is None
    panel._refresh()


def test_the_stock_group_lists_each_stock_below_the_unit(
    panel: EditUnitPanel,
) -> None:
    layout = panel.form.layout()
    assert layout is not None
    assert layout.indexOf(panel.stock_box) == layout.indexOf(panel.unit_box) + 1
    header = panel.stock_list.headerItem()
    assert header is not None
    assert [header.text(i) for i in range(len(STOCK_COLUMNS))] == list(STOCK_COLUMNS)
    shelf = _shelf(panel)
    _swap(panel, [shelf], 12.0)
    groups = panel.session.stock_groups()
    rows = _rows(panel)
    assert len(rows) == len(groups) == 2
    for row, group in zip(rows, groups, strict=True):
        assert (
            row.text(0)
            == FreeCAD.Units.Quantity(
                group.thickness_mm, FreeCAD.Units.Length
            ).UserString
        )
        assert row.text(1) == group.material
        assert not row.icon(2).isNull()
        assert row.text(3) == str(len(group.board_ids))
    assert rows[0].text(3) == "4"
    assert rows[1].text(3) == "1"


def test_clicking_a_row_selects_exactly_its_boards(panel: EditUnitPanel) -> None:
    doc = panel.session.container.Document
    shelf = _shelf(panel)
    _swap(panel, [shelf], 12.0)
    rows = _rows(panel)
    panel.stock_list.itemClicked.emit(rows[0], 0)
    _process_events()
    assert sorted(panel.session.selected_boards) == sorted(_UNIT_BOARDS)
    assert _freecad_selection(doc) == sorted(_UNIT_BOARDS)
    assert rows[0].isSelected() and not rows[1].isSelected()
    panel.stock_list.itemClicked.emit(rows[1], 0)
    _process_events()
    assert panel.session.selected_boards == (shelf,)
    assert _freecad_selection(doc) == [shelf]
    assert rows[1].isSelected() and not rows[0].isSelected()


def test_a_row_shows_selected_only_while_the_selection_is_its_boards(
    panel: EditUnitPanel,
) -> None:
    shelf = _shelf(panel)
    _swap(panel, [shelf], 12.0)
    rows = _rows(panel)
    panel.session.select_boards(["top", "bottom"])
    panel._refresh()
    assert not any(row.isSelected() for row in rows)
    panel.session.select_boards([*_UNIT_BOARDS, shelf])
    panel._refresh()
    assert not any(row.isSelected() for row in rows)
    panel.session.select(shelf)
    panel._refresh()
    assert rows[1].isSelected() and not rows[0].isSelected()


def test_change_stock_needs_a_board_and_two_boards_disable_the_basis(
    panel: EditUnitPanel,
) -> None:
    session = panel.session
    session.select(None)
    panel._refresh()
    assert not panel.change_stock_button.isEnabled()
    session.select(_first_bay(session.unit.root))
    panel._refresh()
    assert not panel.change_stock_button.isEnabled()
    assert panel.basis_combo.isEnabled()
    session.select("top")
    panel._refresh()
    assert panel.change_stock_button.isEnabled()
    session.select_boards(["top", "bottom"])
    panel._refresh()
    assert panel.change_stock_button.isEnabled()
    assert not panel.basis_combo.isEnabled()


def _open_dialog(panel: EditUnitPanel, board_ids: list[str]) -> StockDialog:
    panel.session.select_boards(board_ids)
    panel._refresh()
    panel.change_stock_button.click()
    _process_events()
    dialog = panel.stock_dialog
    assert dialog is not None and dialog.isVisible()
    return dialog


def test_the_dialog_offers_freecads_three_fields_each_unset(
    panel: EditUnitPanel,
) -> None:
    doc = panel.session.container.Document
    dialog = _open_dialog(panel, ["top", "bottom"])
    fields = {
        dialog.thickness_field.metaObject().className(),
        dialog.material_field.metaObject().className(),
        dialog.color_field.metaObject().className(),
    }
    assert fields == {
        "Gui::QuantitySpinBox",
        "MatGui::MaterialTreeWidget",
        "Gui::ColorButton",
    }
    checks = (dialog.thickness_check, dialog.material_check, dialog.color_check)
    assert not any(check.isChecked() for check in checks)
    groups = panel.session.stock_groups()
    steps = doc.UndoCount
    dialog.accept()
    _process_events()
    assert panel.stock_dialog is None
    assert doc.UndoCount == steps
    assert panel.session.stock_groups() == groups


def test_a_click_on_an_unchecked_field_checks_it(panel: EditUnitPanel) -> None:
    dialog = _open_dialog(panel, ["top"])
    rows = (
        (dialog.thickness_check, dialog.thickness_field),
        (dialog.material_check, dialog.material_field),
        (dialog.color_check, dialog.color_field),
    )
    for check, field in rows:
        # The press lands where a user's would: on the child under the
        # field's center, which for the spin box is its line edit.
        target = field.childAt(field.rect().center()) or field
        QTest.mouseClick(
            target, QtCore.Qt.MouseButton.LeftButton, pos=target.rect().center()
        )
        _process_events()
        assert check.isChecked()
        assert field.isEnabled()
        focused = dialog.focusWidget()
        assert focused is not None
        assert focused is field or field.isAncestorOf(focused)
        if field is dialog.thickness_field:
            # Typing then replaces the shown thickness.
            (line_edit,) = field.findChildren(QtWidgets.QLineEdit)
            assert line_edit.text()
            assert line_edit.selectedText() == line_edit.text()
    assert all(check.isChecked() for check, _field in rows)
    dialog.reject()
    _process_events()


def test_the_dialog_swaps_the_checked_fields(panel: EditUnitPanel) -> None:
    dialog = _open_dialog(panel, ["top"])
    dialog.thickness_check.setChecked(True)
    dialog.thickness_field.setProperty("rawValue", 12.0)
    dialog.material_check.setChecked(True)
    dialog.set_material(library_material("Wood").UUID)
    dialog.accept()
    _process_events()
    groups = panel.session.stock_groups()
    assert [(g.board_ids, g.thickness_mm, g.material) for g in groups][1] == (
        ("top",),
        12.0,
        "Wood",
    )
    assert panel.session.selected_boards == ("top",)
    assert len(_rows(panel)) == 2


def test_a_swap_that_cannot_fit_is_reported(
    panel: EditUnitPanel, reported: list[str]
) -> None:
    dialog = _open_dialog(panel, list(_UNIT_BOARDS))
    dialog.thickness_check.setChecked(True)
    dialog.thickness_field.setProperty("rawValue", 400.0)
    groups = panel.session.stock_groups()
    dialog.accept()
    _process_events()
    assert len(reported) == 1
    assert panel.session.stock_groups() == groups
