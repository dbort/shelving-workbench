"""The Edit Unit panel's Constraints group with FreeCAD's GUI up: its rows,
their checkboxes, delete buttons and redundancy marks, and the basis menu
for a selected constraint. Selection shared with the 3D view is
``tests/freecad_view/test_constraint_list.py``'s."""

import dataclasses
from collections.abc import Iterator
from typing import cast

import FreeCAD
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.container import write_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Constraint,
    Division,
    Equal,
    EvenSpacing,
    RunEnd,
    Unit,
)
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.constraint_list import (
    DELETE_COLUMN,
    MARK_COLUMN,
    REDUNDANT_TIP,
    TEXT_COLUMN,
    ConstraintList,
    disabled_icon,
)
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import ConstraintRow, LockRow

_T_MM = 18.0
_BAY_MM = 288.0


def _process_events() -> None:
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def _column_unit(
    a: Bay, b: Bay, c: Bay, column_id: str, *constraints: Constraint
) -> Unit:
    """A closed 936 mm carcass whose column holds ``a``, ``b`` and ``c``,
    288 mm each, behind ``shelf_a`` and ``shelf_b``."""
    column = Division(
        axis=Axis.Z,
        items=[
            a,
            Board(thickness_mm=_T_MM, role="shelf_a"),
            b,
            Board(thickness_mm=_T_MM, role="shelf_b"),
            c,
        ],
        size_mm=564.0,
        id=column_id,
    )
    return Unit(
        size_mm=Vec3(600.0, 300.0, 936.0),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=_T_MM, role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(thickness_mm=_T_MM, role="left_side"),
                        column,
                        Board(thickness_mm=_T_MM, role="right_side"),
                    ],
                    size_mm=900.0,
                ),
                Board(thickness_mm=_T_MM, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
        front_at_min=None,
        constraints=constraints,
    )


class _Editing:
    """An open panel on the column, its constraints as given."""

    def __init__(self, name: str, *kinds: str) -> None:
        a, b, c = (Bay(size_mm=_BAY_MM) for _ in range(3))
        column_id = "column"
        made: list[Constraint] = []
        for kind in kinds:
            if kind == "equal":
                made.append(Equal(region_ids=(a.id, b.id)))
            elif kind == "equal_off":
                made.append(Equal(region_ids=(a.id, b.id), active=False))
            elif kind == "spacing":
                made.append(
                    EvenSpacing(run_id=column_id, start=RunEnd.START, end=RunEnd.END)
                )
            elif kind == "spacing_off":
                made.append(
                    EvenSpacing(
                        run_id=column_id,
                        start=RunEnd.START,
                        end=RunEnd.END,
                        active=False,
                    )
                )
        self.doc = FreeCAD.newDocument(name)
        self.container = cast(
            "FreeCAD.DocumentObject", self.doc.addObject("App::Part", "Unit")
        )
        write_container(self.container, _column_unit(a, b, c, column_id, *made))
        self.doc.recompute()
        self.panel = EditUnitPanel(self.container)
        self.panel.form.resize(400, 1200)
        self.panel.form.show()
        _process_events()

    @property
    def rows(self) -> ConstraintList:
        return self.panel.constraint_list

    def bays(self) -> list[str]:
        root = self.panel.session.unit.root
        assert isinstance(root, Division)
        middle = root.items[1]
        assert isinstance(middle, Division)
        column = middle.items[1]
        assert isinstance(column, Division)
        return [item.id for item in column.items if not isinstance(item, Board)]

    def item(self, index: int) -> QtWidgets.QTreeWidgetItem:
        found = self.rows.tree.topLevelItem(index)
        assert found is not None
        return found

    def delete_button(self, index: int) -> QtWidgets.QToolButton:
        button = self.rows.tree.itemWidget(self.item(index), DELETE_COLUMN)
        assert isinstance(button, QtWidgets.QToolButton)
        return button

    def close(self) -> None:
        # No events in between, as test_panel closes: the closed panel's
        # form stays shown here, where FreeCAD would delete it, and its
        # size fields name properties the session has removed.
        self.panel.reject()
        FreeCAD.closeDocument(self.doc.Name)


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    messages: list[str] = []
    monkeypatch.setattr(panel_module, "report_error", messages.append)
    return messages


@pytest.fixture
def editing(request: pytest.FixtureRequest, reported: list[str]) -> Iterator[_Editing]:
    """The column with an Equal on A and B and a deactivated even spacing
    over the whole column, in that order."""
    fixture = _Editing(request.node.name, "equal", "spacing_off")
    try:
        yield fixture
    finally:
        fixture.close()


@pytest.fixture
def bare(request: pytest.FixtureRequest, reported: list[str]) -> Iterator[_Editing]:
    """The column with no lock and no constraint."""
    fixture = _Editing(request.node.name)
    try:
        yield fixture
    finally:
        fixture.close()


def _image(icon: QtGui.QIcon) -> QtGui.QImage:
    return icon.pixmap(QtCore.QSize(16, 16)).toImage()


def test_the_group_follows_the_unit_group_and_shows_with_no_rows(
    bare: _Editing,
) -> None:
    layout = bare.panel.form.layout()
    assert layout is not None
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    unit_index = widgets.index(bare.panel.unit_box)
    assert widgets[unit_index + 1] is bare.rows.box
    assert bare.rows.box.title() == "Constraints"
    assert bare.rows.box.isVisible()
    assert bare.rows.tree.topLevelItemCount() == 0
    assert not bare.rows.delete_deactivated_button.isEnabled()


def test_rows_list_locks_then_constraints_with_icon_and_size(
    editing: _Editing,
) -> None:
    a, _b, c = editing.bays()
    session = editing.panel.session
    assert session.set_lock(c, locked=True) is None
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    rows = editing.rows.rows
    assert [type(row) for row in rows] == [
        LockRow,
        LockRow,
        ConstraintRow,
        ConstraintRow,
    ]
    size = FreeCAD.Units.Quantity(_BAY_MM, FreeCAD.Units.Length).UserString
    texts = [editing.item(i).text(TEXT_COLUMN) for i in range(4)]
    assert "Lock" in texts[0] and size in texts[0]
    assert "Lock" in texts[1] and size in texts[1]
    assert "Equal" in texts[2] and size in texts[2]
    assert texts[3] == "Even spacing"
    for index, row in enumerate(rows):
        assert _image(editing.item(index).icon(TEXT_COLUMN)) == _image(
            editing.rows.row_icon(row)
        )
    spacing = rows[3]
    assert isinstance(spacing, ConstraintRow)
    tree = editing.rows.tree
    side_px = tree.style().pixelMetric(QtWidgets.QStyle.PixelMetric.PM_SmallIconSize)
    on = editing.rows.row_icon(dataclasses.replace(spacing, active=True))
    grayed = disabled_icon(on, side_px, tree.devicePixelRatioF())
    assert _image(editing.item(3).icon(TEXT_COLUMN)) == _image(grayed)
    assert _image(editing.item(3).icon(TEXT_COLUMN)) != _image(on)


def test_a_constraint_row_has_a_checkbox_a_lock_row_none(editing: _Editing) -> None:
    a, _b, _c = editing.bays()
    assert editing.panel.session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    lock, equal, spacing = (editing.item(i) for i in range(3))
    checkable = QtCore.Qt.ItemFlag.ItemIsUserCheckable
    assert not lock.flags() & checkable
    assert equal.flags() & checkable
    assert equal.checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Checked
    assert spacing.checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Unchecked


def test_checking_and_unchecking_turn_a_constraint_on_and_off(
    editing: _Editing,
) -> None:
    equal, spacing = editing.item(0), editing.item(1)
    equal.setCheckState(TEXT_COLUMN, QtCore.Qt.CheckState.Unchecked)
    _process_events()
    assert [c.active for c in editing.panel.session.constraints] == [False, False]
    spacing.setCheckState(TEXT_COLUMN, QtCore.Qt.CheckState.Checked)
    _process_events()
    assert [c.active for c in editing.panel.session.constraints] == [False, True]
    assert editing.item(1).checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Checked


def test_a_refused_activation_stays_unchecked_and_reports(
    editing: _Editing, reported: list[str]
) -> None:
    a, _b, c = editing.bays()
    session = editing.panel.session
    (equal_id, _spacing_id) = (r.id for r in session.constraints)
    assert session.delete_constraint(equal_id) is None
    session.select(c)
    assert session.set_size(200.0) is None
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    spacing = editing.item(2)
    spacing.setCheckState(TEXT_COLUMN, QtCore.Qt.CheckState.Checked)
    _process_events()
    assert len(reported) == 1
    assert editing.item(2).checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Unchecked
    assert [c.active for c in session.constraints] == [False]


def test_a_delete_button_removes_its_constraint_or_unlocks_its_opening(
    editing: _Editing,
) -> None:
    a, _b, _c = editing.bays()
    session = editing.panel.session
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    button = editing.delete_button(1)
    assert button.toolTip() == "Delete"
    assert not button.icon().isNull()
    button.click()
    _process_events()
    assert [type(c) for c in session.constraints] == [EvenSpacing]
    editing.delete_button(0).click()
    _process_events()
    assert session.container.Document.UndoNames[0] == "Unlock Opening"
    assert [type(row) for row in editing.rows.rows] == [ConstraintRow]


def test_delete_deactivated_is_enabled_exactly_while_one_is(
    editing: _Editing,
) -> None:
    session = editing.panel.session
    button = editing.rows.delete_deactivated_button
    assert button.isEnabled()
    steps = session.container.Document.UndoCount
    button.click()
    _process_events()
    assert [type(c) for c in session.constraints] == [Equal]
    assert session.container.Document.UndoCount == steps + 1
    assert not button.isEnabled()


def test_redundant_rows_carry_a_mark_that_follows_every_edit_and_undo(
    editing: _Editing,
) -> None:
    a, b, _c = editing.bays()
    session = editing.panel.session
    doc = session.container.Document

    def marked() -> list[bool]:
        tree = editing.rows.tree
        found: list[bool] = []
        for index in range(tree.topLevelItemCount()):
            item = editing.item(index)
            mark = not item.icon(MARK_COLUMN).isNull()
            assert mark == (item.toolTip(TEXT_COLUMN) == REDUNDANT_TIP)
            found.append(mark)
        return found

    assert marked() == [False, False]
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    assert marked() == [False, False, False]
    assert session.set_lock(b, locked=True) is None
    editing.panel._refresh()
    assert marked() == [True, True, True, False]
    doc.undo()
    _process_events()
    assert marked() == [False, False, False]
    doc.redo()
    _process_events()
    assert marked() == [True, True, True, False]


def test_undoing_a_deactivation_checks_the_box_again(editing: _Editing) -> None:
    editing.item(0).setCheckState(TEXT_COLUMN, QtCore.Qt.CheckState.Unchecked)
    _process_events()
    assert editing.item(0).checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Unchecked
    editing.panel.session.container.Document.undo()
    _process_events()
    assert editing.item(0).checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Checked


def test_the_basis_menu_serves_a_lone_selected_constraint(editing: _Editing) -> None:
    session = editing.panel.session
    combo = editing.panel.basis_combo
    model = cast("QtGui.QStandardItemModel", combo.model())
    equal_id, spacing_id = (c.id for c in session.constraints)
    session.select_constraints([equal_id, spacing_id])
    editing.panel._refresh()
    assert not combo.isEnabled()
    session.select_constraints([equal_id])
    editing.panel._refresh()
    assert combo.isEnabled()
    assert combo.currentIndex() == 0
    assert model.item(1).isEnabled()
    combo.setCurrentIndex(1)
    _process_events()
    assert [c.basis for c in session.constraints] == [Basis.WITH_NEXT, Basis.CLEAR]
    # C, the even spacing's last opening, has no board after it in its run.
    session.select_constraints([session.constraints[1].id])
    editing.panel._refresh()
    assert combo.isEnabled()
    assert not model.item(1).isEnabled()
