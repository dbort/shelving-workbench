"""The Edit Unit panel's Constraints group with FreeCAD's GUI up: its rows,
their checkboxes, delete buttons and redundancy marks, and the basis menu
for a selected constraint. Selection shared with the 3D view is
``tests/freecad_view/test_constraint_list.py``'s."""

from collections.abc import Iterator, Mapping
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
    ConstraintId,
    Division,
    Equal,
    EvenSpacing,
    Lock,
    RunEnd,
    Unit,
    region_lock,
)
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.constraint_list import (
    DELETE_COLUMN,
    MARK_COLUMN,
    REDUNDANT_TIP,
    TEXT_COLUMN,
    ConstraintList,
)
from freecad.Shelving.editor.elevation import ConstraintKind, ElevationDirection
from freecad.Shelving.editor.overlay import (
    TILE_PAD_PX,
    Tile,
    constraint_icon_image,
    lock_icon_image,
    text_tile_image,
    view_style,
)
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import ConstraintRow, RowKind

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


_AXIS_KINDS: Mapping[RowKind, tuple[ConstraintKind, ElevationDirection]] = {
    "equal_width": ("equal", "horizontal"),
    "equal_height": ("equal", "vertical"),
    "even_width": ("even_spacing", "horizontal"),
    "even_height": ("even_spacing", "vertical"),
}


def _drawn_icon(
    tree: QtWidgets.QTreeWidget, kind: RowKind, active: bool = True
) -> QtGui.QIcon:
    """The image for ``kind``: the view's own for an Equal or Even spacing
    through the depth, or else the icon of the command that makes it, with
    the view's corner X unless ``active``; for a Lock the icon of the
    command that makes it, or the bare tile when no command makes it; at
    the list's icon size on a tile of its background."""
    side_px = tree.style().pixelMetric(QtWidgets.QStyle.PixelMetric.PM_SmallIconSize)
    ratio = tree.devicePixelRatioF()
    base = tree.palette().color(QtGui.QPalette.ColorRole.Base)
    tile = Tile(
        (base.redF(), base.greenF(), base.blueF()), round(TILE_PAD_PX * ratio), 0.0
    )
    style = view_style(0)
    device_px = round(side_px * ratio)
    if kind == "lock":
        image = text_tile_image(tile, device_px, device_px)
    elif kind == "lock_width":
        image = lock_icon_image("horizontal", style.icon_rgb, tile, device_px)
    elif kind == "lock_height":
        image = lock_icon_image("vertical", style.icon_rgb, tile, device_px)
    elif kind in ("equal", "even_spacing"):
        image = constraint_icon_image(kind, style.icon_rgb, tile, device_px, active)
    else:
        constraint, direction = _AXIS_KINDS[kind]
        image = constraint_icon_image(
            constraint, style.icon_rgb, tile, device_px, active, direction
        )
    pixmap = QtGui.QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    return QtGui.QIcon(pixmap)


def test_rows_show_their_kind_size_and_the_views_icons(editing: _Editing) -> None:
    a, _b, _c = editing.bays()
    assert editing.panel.session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    tree = editing.rows.tree
    size = FreeCAD.Units.Quantity(_BAY_MM, FreeCAD.Units.Length).UserString
    # The lock was made after the Equal and the even spacing, so it comes
    # after them.
    equal, spacing, lock = (editing.item(i) for i in range(3))
    assert lock.text(TEXT_COLUMN).startswith("Lock Height")
    assert size in lock.text(TEXT_COLUMN)
    assert "Equal" in equal.text(TEXT_COLUMN) and size in equal.text(TEXT_COLUMN)
    assert equal.text(TEXT_COLUMN).startswith("Equal Height")
    assert spacing.text(TEXT_COLUMN) == "Even Height"
    height = _drawn_icon(tree, "lock_height")
    equals = _drawn_icon(tree, "equal_height")
    spaced = _drawn_icon(tree, "even_height")
    assert _image(height) != _image(equals)
    assert _image(height) != _image(spaced)
    assert _image(equals) != _image(spaced)
    assert _image(lock.icon(TEXT_COLUMN)) == _image(height)
    assert _image(equal.icon(TEXT_COLUMN)) == _image(equals)
    # The deactivated even spacing's icon is the view's, red with its X.
    marked = _drawn_icon(tree, "even_height", active=False)
    assert _image(spacing.icon(TEXT_COLUMN)) == _image(marked)
    assert _image(marked) != _image(spaced)


def test_a_lock_row_names_and_draws_the_command_that_makes_its_axis_lock(
    editing: _Editing,
) -> None:
    session = editing.panel.session
    (_bottom, row, _top) = cast("Division", session.unit.root).items
    column = cast("Division", row).items[1]
    a, _b, _c = editing.bays()
    assert session.set_lock(column.id, locked=True) is None
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    tree = editing.rows.tree
    width, height = editing.item(2), editing.item(3)
    assert width.text(TEXT_COLUMN).startswith("Lock Width")
    assert height.text(TEXT_COLUMN).startswith("Lock Height")
    width_icon = _drawn_icon(tree, "lock_width")
    height_icon = _drawn_icon(tree, "lock_height")
    assert _image(width_icon) != _image(height_icon)
    assert _image(width.icon(TEXT_COLUMN)) == _image(width_icon)
    assert _image(height.icon(TEXT_COLUMN)) == _image(height_icon)


def test_a_lock_no_command_makes_reads_lock_on_a_bare_tile(bare: _Editing) -> None:
    """A Lock through the depth, which only a scan makes."""
    rows = bare.rows
    row = ConstraintRow(
        constraint_id=ConstraintId("depth"),
        kind="lock",
        active=True,
        size_mm=None,
        redundant=False,
    )
    rows.show([row], ())
    item = bare.item(0)
    assert item.text(TEXT_COLUMN) == "Lock"
    assert _image(item.icon(TEXT_COLUMN)) == _image(_drawn_icon(rows.tree, "lock"))
    assert _image(_drawn_icon(rows.tree, "lock")) != _image(
        _drawn_icon(rows.tree, "lock_width")
    )


def test_width_rows_name_and_draw_the_width_commands(bare: _Editing) -> None:
    session = bare.panel.session
    session.select(bare.bays()[0])
    assert session.split("horizontal") is None
    pair = session.unit.root
    for index in (1, 1, 0):
        assert isinstance(pair, Division)
        pair = pair.items[index]
    assert isinstance(pair, Division) and pair.axis is Axis.X
    left, right = (item.id for item in pair.items if not isinstance(item, Board))
    session.select_items([left, right])
    assert session.equal_axis("horizontal") is None
    session.select_items([left, right])
    assert session.even_axis("horizontal") is None
    bare.panel._refresh()
    tree = bare.rows.tree
    equal, spacing = bare.item(0), bare.item(1)
    assert equal.text(TEXT_COLUMN).startswith("Equal Width")
    assert spacing.text(TEXT_COLUMN).startswith("Even Width")
    widths = _drawn_icon(tree, "equal_width")
    spaced = _drawn_icon(tree, "even_width")
    assert _image(widths) != _image(_drawn_icon(tree, "equal_height"))
    assert _image(spaced) != _image(_drawn_icon(tree, "even_height"))
    assert _image(equal.icon(TEXT_COLUMN)) == _image(widths)
    assert _image(spacing.icon(TEXT_COLUMN)) == _image(spaced)


@pytest.mark.parametrize(
    ("kind", "text"), [("equal", "Equal"), ("even_spacing", "Even spacing")]
)
def test_a_constraint_through_the_depth_reads_its_axis_free_name(
    bare: _Editing, kind: RowKind, text: str
) -> None:
    """A stored Equal or Even spacing may hold sizes through the depth,
    which no command makes."""
    rows = bare.rows
    row = ConstraintRow(
        constraint_id=ConstraintId("depth"),
        kind=kind,
        active=True,
        size_mm=None,
        redundant=False,
    )
    rows.show([row], ())
    item = bare.item(0)
    assert item.text(TEXT_COLUMN) == text
    assert _image(item.icon(TEXT_COLUMN)) == _image(_drawn_icon(rows.tree, kind))


def test_a_selected_rows_icon_keeps_its_colors(editing: _Editing) -> None:
    a, _b, _c = editing.bays()
    assert editing.panel.session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    tree = editing.rows.tree
    size = QtCore.QSize(16, 16)
    ratio = tree.devicePixelRatioF()
    for index in range(3):
        icon = editing.item(index).icon(TEXT_COLUMN)
        normal = icon.pixmap(size, ratio, QtGui.QIcon.Mode.Normal).toImage()
        selected = icon.pixmap(size, ratio, QtGui.QIcon.Mode.Selected).toImage()
        assert selected == normal, index


def test_every_row_has_a_checkbox_and_unchecking_a_lock_turns_it_off(
    editing: _Editing,
) -> None:
    a, _b, _c = editing.bays()
    session = editing.panel.session
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    equal, spacing, lock = (editing.item(i) for i in range(3))
    checkable = QtCore.Qt.ItemFlag.ItemIsUserCheckable
    assert lock.flags() & checkable and equal.flags() & checkable
    assert lock.checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Checked
    assert equal.checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Checked
    assert spacing.checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Unchecked
    lock.setCheckState(TEXT_COLUMN, QtCore.Qt.CheckState.Unchecked)
    _process_events()
    found = region_lock(session.unit, a)
    assert found is not None and not found.active
    assert session.container.Document.UndoNames[0] == "Deactivate Constraint"
    assert editing.item(2).checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Unchecked


def test_a_deactivated_lock_rows_icon_is_grayed_in_qts_disabled_mode(
    editing: _Editing,
) -> None:
    a, _b, _c = editing.bays()
    session = editing.panel.session
    assert session.set_lock(a, locked=True) is None
    found = region_lock(session.unit, a)
    assert found is not None
    assert session.set_constraint_active(found.id, False) is None
    editing.panel._refresh()
    tree = editing.rows.tree
    side_px = tree.style().pixelMetric(QtWidgets.QStyle.PixelMetric.PM_SmallIconSize)
    size = QtCore.QSize(side_px, side_px)
    ratio = tree.devicePixelRatioF()
    height = _drawn_icon(tree, "lock_height")
    grayed = height.pixmap(size, ratio, QtGui.QIcon.Mode.Disabled).toImage()
    icon = editing.item(2).icon(TEXT_COLUMN)
    for mode in (QtGui.QIcon.Mode.Normal, QtGui.QIcon.Mode.Selected):
        assert icon.pixmap(size, ratio, mode).toImage() == grayed
    assert grayed != height.pixmap(size, ratio).toImage()


def test_selecting_a_lock_row_selects_the_lock_and_its_basis_moves_nothing(
    editing: _Editing,
) -> None:
    a, _b, _c = editing.bays()
    session = editing.panel.session
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    found = region_lock(session.unit, a)
    assert found is not None
    editing.item(2).setSelected(True)
    _process_events()
    assert session.selected_constraints == (found.id,)
    assert session.selected_items == ()
    combo = editing.panel.basis_combo
    assert combo.isEnabled()
    assert combo.currentIndex() == 0
    spaces = session.spaces
    combo.setCurrentIndex(1)
    _process_events()
    changed = region_lock(session.unit, a)
    assert changed is not None
    assert (changed.id, changed.basis, changed.active) == (
        found.id,
        Basis.WITH_NEXT,
        True,
    )
    assert session.spaces == spaces


@pytest.mark.smoke("turn a constraint off and on in the constraint list")
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
    # Each row's icon follows its box: the X on the Equal, none on the even
    # spacing.
    tree = editing.rows.tree
    assert _image(editing.item(0).icon(TEXT_COLUMN)) == _image(
        _drawn_icon(tree, "equal_height", active=False)
    )
    assert _image(editing.item(1).icon(TEXT_COLUMN)) == _image(
        _drawn_icon(tree, "even_height")
    )


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
    spacing = editing.item(0)
    spacing.setCheckState(TEXT_COLUMN, QtCore.Qt.CheckState.Checked)
    _process_events()
    assert len(reported) == 1
    assert editing.item(0).checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Unchecked
    assert [c.active for c in session.constraints] == [False, True, True]


def test_a_delete_button_removes_its_constraint_a_lock_included(
    editing: _Editing,
) -> None:
    a, _b, _c = editing.bays()
    session = editing.panel.session
    assert session.set_lock(a, locked=True) is None
    editing.panel._refresh()
    button = editing.delete_button(0)
    assert button.toolTip() == "Delete"
    assert not button.icon().isNull()
    button.click()
    _process_events()
    assert [type(c) for c in session.constraints] == [EvenSpacing, Lock]
    editing.delete_button(1).click()
    _process_events()
    assert session.container.Document.UndoNames[0] == "Delete Constraint"
    assert [row.kind for row in editing.rows.rows] == ["even_height"]


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
    assert marked() == [True, False, True, True]
    doc.undo()
    _process_events()
    assert marked() == [False, False, False]
    doc.redo()
    _process_events()
    assert marked() == [True, False, True, True]


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
