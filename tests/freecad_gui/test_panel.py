"""The editor's task panel and its size fields, with FreeCAD's GUI up.

``FreeCADGui.UiLoader``, and with it the ``Gui::QuantitySpinBox`` the
size fields are built from, exists only once the GUI is running, which
this directory's ``conftest.py`` arranges (``.claude/docs/freecad-notes.md``,
"GUI-only widget access").

``EditUnitPanel`` is built directly, with no 3D view, rather than through
``FreeCADGui.Control.showDialog``: the offscreen GUI cannot draw a 3D view,
and the task dialog machinery adds nothing these tests assert. What happens
in the view is ``tests/freecad_view/``'s.
"""

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from types import TracebackType
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import Shiboken

from freecad.Shelving.compat import override
from freecad.Shelving.core.layout import (
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    Region,
    SizeRule,
)
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.fields import DimensionField
from freecad.Shelving.editor.panel import AncestorWatch, EditUnitPanel
from freecad.Shelving.editor.session import Session, UnitDimension
from freecad.Shelving.unit_ops import create_unit

_TOL_MM = 1e-6


def _process_events() -> None:
    for _ in range(5):
        QtWidgets.QApplication.processEvents()


def _bay_ids(region: Region) -> list[str]:
    """Every ``Bay`` id under ``region``, in run order: lowest first."""
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


def _rule_of(region: Region, region_id: str) -> SizeRule | None:
    if region.id == region_id:
        return region.rule
    if isinstance(region, Division):
        for item in region.items:
            if isinstance(item, Board):
                continue
            found = _rule_of(item, region_id)
            if found is not None:
                return found
    return None


def _new_document(name: str) -> FreeCAD.Document:
    """A fresh document holding a ``VarSet`` with ``Len = 300 mm``."""
    doc = FreeCAD.newDocument(name)
    varset = cast("FreeCAD.DocumentObject", doc.addObject("App::VarSet", "VarSet"))
    varset.addProperty("App::PropertyLength", "Len")
    setattr(varset, "Len", 300.0)  # noqa: B010 - a dynamic property
    return doc


class _Fixture:
    """A fresh document holding a ``VarSet`` with ``Len = 300 mm``, a unit
    with one shelf, and an open panel on it: ``lower`` and ``upper`` name
    the two bays either side of the shelf."""

    def __init__(self, name: str) -> None:
        self.doc = _new_document(name)
        self.container = create_unit(self.doc)
        self.doc.recompute()
        self.panel = EditUnitPanel(self.container)
        self.panel.form.resize(900, 1400)
        self.panel.form.show()
        _process_events()
        self.select(_bay_ids(self.session.unit.root)[0])
        assert self.session.split("vertical") is None
        self.panel._refresh()
        self.lower, self.upper = _bay_ids(self.session.unit.root)

    @property
    def session(self) -> Session:
        return self.panel.session

    def select(self, node_id: str) -> None:
        self.panel.session.select(node_id)
        self.panel._refresh()

    def rule(self, region_id: str) -> SizeRule | None:
        return _rule_of(self.panel.session.unit.root, region_id)

    def close(self) -> None:
        self.panel.reject()
        FreeCAD.closeDocument(self.doc.Name)


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every message the panel sends to FreeCAD's Notification Area, in
    order, instead of sending it. Requested before the panel is built, since
    the panel hands ``report_error`` to its fields at construction."""
    messages: list[str] = []
    monkeypatch.setattr(panel_module, "report_error", messages.append)
    return messages


@pytest.fixture
def unit_panel(
    request: pytest.FixtureRequest, reported: list[str]
) -> Iterator[_Fixture]:
    """A :class:`_Fixture` in a document named after the test, closed after
    it, pass or fail."""
    fixture = _Fixture(request.node.name)
    try:
        yield fixture
    finally:
        fixture.close()


def test_standard_buttons_are_a_plain_int(unit_panel: _Fixture) -> None:
    """FreeCAD's task dialog rejects the Qt flag itself."""
    buttons = unit_panel.panel.getStandardButtons()
    assert type(buttons) is int
    assert buttons == QtWidgets.QDialogButtonBox.StandardButton.Close.value


def test_the_panel_holds_only_the_units_size_the_basis_and_its_lists(
    unit_panel: _Fixture,
) -> None:
    form = unit_panel.panel.form
    assert form.findChildren(QtWidgets.QGraphicsView) == []
    spins = form.findChildren(QtWidgets.QAbstractSpinBox)
    assert sorted(spins, key=id) == sorted(
        (f.widget for f in unit_panel.panel.unit_fields.values()), key=id
    )
    assert sorted(form.findChildren(QtWidgets.QComboBox), key=id) == sorted(
        [unit_panel.panel.basis_combo, *unit_panel.panel.fixed_combos.values()],
        key=id,
    )
    buttons = [button.text() for button in form.findChildren(QtWidgets.QAbstractButton)]
    assert sorted(buttons) == ["Change stock…", "Delete Selected", "Hide other objects"]
    assert not unit_panel.panel.hide_others_check.isChecked()
    # The unit has nothing this workbench did not create.
    assert not unit_panel.panel.untagged_box.isVisible()


def _wheel_down(widget: QtWidgets.QWidget) -> None:
    center = QtCore.QPointF(widget.rect().center())
    event = QtGui.QWheelEvent(
        center,
        QtCore.QPointF(widget.mapToGlobal(center.toPoint())),
        QtCore.QPoint(0, 0),
        QtCore.QPoint(0, -120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QtWidgets.QApplication.sendEvent(widget, event)
    _process_events()


def test_the_wheel_changes_no_field_it_passes_over(unit_panel: _Fixture) -> None:
    unit_panel.select(unit_panel.lower)
    form = unit_panel.panel.form
    doc = unit_panel.doc
    fields: list[QtWidgets.QWidget] = [
        *form.findChildren(QtWidgets.QAbstractSpinBox),
        *form.findChildren(QtWidgets.QComboBox),
    ]
    assert unit_panel.panel.basis_combo.isEnabled()
    unit_panel.panel.hide_others_check.setFocus()
    _process_events()
    for widget in fields:
        assert not widget.hasFocus()
        undo_names = list(doc.UndoNames)
        value = (
            widget.currentIndex()
            if isinstance(widget, QtWidgets.QComboBox)
            else widget.property("rawValue")
        )
        _wheel_down(widget)
        line_edit = widget.findChild(QtWidgets.QLineEdit)
        if line_edit is not None:
            _wheel_down(line_edit)
        after = (
            widget.currentIndex()
            if isinstance(widget, QtWidgets.QComboBox)
            else widget.property("rawValue")
        )
        assert after == value, widget
        assert list(doc.UndoNames) == undo_names, widget


def test_the_basis_menu_measures_the_selected_opening(unit_panel: _Fixture) -> None:
    combo = unit_panel.panel.basis_combo
    unit_panel.select(unit_panel.lower)
    assert combo.isEnabled()
    assert combo.currentIndex() == 0
    combo.setCurrentIndex(1)
    _process_events()
    rule = unit_panel.rule(unit_panel.lower)
    assert isinstance(rule, Fixed)
    assert rule.basis is Basis.WITH_NEXT
    # A board has no basis to choose.
    shelf = next(
        node_id
        for node_id in unit_panel.session.spaces
        if unit_panel.doc.getObject(node_id) is not None
        and node_id not in ("bottom", "top", "left_side", "right_side")
    )
    unit_panel.select(shelf)
    assert not combo.isEnabled()


def test_untagged_objects_are_kept_unless_deleted() -> None:
    doc = FreeCAD.newDocument("panel_smoke_untagged")
    try:
        container = create_unit(doc)
        cube = cast("FreeCAD.DocumentObject", doc.addObject("Part::Box", "HandAdded"))
        for name, value_mm in (("Length", 400.0), ("Width", 5.0), ("Height", 400.0)):
            setattr(cube, name, value_mm)
        cast("FreeCAD.DocumentObjectGroup", container).addObject(cube)
        doc.recompute()
        panel = EditUnitPanel(container)
        panel.form.show()
        _process_events()
        assert panel.untagged_box.isVisible()
        assert list(panel.untagged_checks) == ["HandAdded"]
        box = panel.untagged_checks["HandAdded"]
        assert not box.isChecked()
        # The reason wraps instead of widening the panel.
        labels = panel.untagged_box.findChildren(QtWidgets.QLabel)
        reason_labels = [label for label in labels if "HandAdded" in label.text()]
        assert len(reason_labels) == 1
        assert reason_labels[0].wordWrap()
        box.setChecked(True)
        # A refresh keeps the check.
        panel._refresh()
        assert panel.untagged_checks["HandAdded"].isChecked()
        panel.delete_untagged_button.click()
        _process_events()
        assert doc.getObject("HandAdded") is None
        assert not panel.untagged_box.isVisible()
        panel.reject()
        assert doc.getObject("HandAdded") is None
        doc.undo()
        assert doc.getObject("HandAdded") is not None
    finally:
        FreeCAD.closeDocument(doc.Name)


class _LinkGroupObject(Protocol):
    ElementList: list[FreeCAD.DocumentObject]


class _BoxObject(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


_MAGIC_START = (
    Path(__file__).parent.parent
    / "freecad"
    / "fixtures"
    / "woodworking_magic_start_default.FCStd"
)


def test_a_back_is_listed_as_following_the_boards_and_deletes(
    tmp_path: Path,
) -> None:
    """Magic Start's back gets a row saying it follows the boards beside a
    door's row with its own reason; the explanation does not say every
    listed object is left alone; Delete Selected deletes the back, and a
    resize after it still works."""
    path = tmp_path / _MAGIC_START.name
    shutil.copyfile(_MAGIC_START, path)
    doc = FreeCAD.openDocument(str(path))
    try:
        container = doc.getObject("LinkGroup")
        assert container is not None
        door = cast("_BoxObject", doc.addObject("Part::Box", "Door"))
        door.Length, door.Width, door.Height = 500.0, 18.0, 660.0
        door.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, -18.0, 100.0), FreeCAD.Rotation()
        )
        link_group = cast("_LinkGroupObject", container)
        link_group.ElementList = [
            *link_group.ElementList,
            cast("FreeCAD.DocumentObject", door),
        ]
        doc.recompute()
        panel = EditUnitPanel(container)
        panel.form.show()
        _process_events()

        assert list(panel.untagged_checks) == ["Back", "Door"]
        back_name = panel.untagged_checks["Back"].accessibleName()
        door_name = panel.untagged_checks["Door"].accessibleName()
        assert back_name.startswith("Furniture - Back board (Back): ")
        assert "follows the unit's boards" in back_name
        assert "follows" not in door_name
        texts = [
            label.text() for label in panel.untagged_box.findChildren(QtWidgets.QLabel)
        ]
        assert not any("leaves them alone" in text for text in texts)

        panel.untagged_checks["Back"].setChecked(True)
        panel.delete_untagged_button.click()
        _process_events()
        assert doc.getObject("Back") is None
        assert list(panel.untagged_checks) == ["Door"]
        assert panel.session.resize("width", 600.0) is None
        panel.reject()
    finally:
        FreeCAD.closeDocument(doc.Name)


class _SizeField:
    """A :class:`DimensionField` bound to a fresh unit's container, shown
    in a window of its own, recording every size it reports."""

    def __init__(self, name: str, apply_on_step: bool = False) -> None:
        self.doc = _new_document(name)
        self.container = create_unit(self.doc)
        self.doc.recompute()
        self.sizes_mm: list[float] = []
        self.errors: list[str] = []
        self.field = DimensionField(
            self.container,
            "Placement.Base.x",
            self.sizes_mm.append,
            self.errors.append,
            apply_on_step=apply_on_step,
        )
        self.window = QtWidgets.QWidget()
        QtWidgets.QVBoxLayout(self.window).addWidget(self.field.widget)
        self.window.show()
        self.field.show_mm(200.0)
        _process_events()

    def type(self, text: str) -> None:
        line_edit = self.field.line_edit
        line_edit.setFocus()
        line_edit.selectAll()
        QtTest.QTest.keyClicks(line_edit, text)
        QtTest.QTest.keyClick(line_edit, QtCore.Qt.Key.Key_Return)
        _process_events()

    def close(self) -> None:
        # A test may have handed the window to a parent that deleted it.
        if Shiboken.isValid(self.window):
            Shiboken.delete(self.window)
        FreeCAD.closeDocument(self.doc.Name)


@pytest.fixture
def size_field(request: pytest.FixtureRequest) -> Iterator[_SizeField]:
    fixture = _SizeField(request.node.name)
    try:
        yield fixture
    finally:
        fixture.close()


def test_the_field_is_freecads_quantity_widget(size_field: _SizeField) -> None:
    widget = size_field.field.quantity_widget
    assert widget is not None
    assert widget.inherits("Gui::QuantitySpinBox")


def test_a_typed_size_and_a_varset_expression(size_field: _SizeField) -> None:
    size_field.type("250")
    size_field.type("VarSet.Len - 20 mm")
    assert size_field.sizes_mm == [250.0, 280.0]
    assert size_field.errors == []


def test_an_unchanged_focus_out_reports_nothing(size_field: _SizeField) -> None:
    size_field.field.line_edit.editingFinished.emit()
    _process_events()
    assert size_field.sizes_mm == []


def _accept_formula_dialog(expression: str) -> None:
    dialogs = [
        widget
        for widget in QtWidgets.QApplication.allWidgets()
        if widget.inherits("Gui::Dialog::DlgExpressionInput") and widget.isVisible()
    ]
    assert len(dialogs) == 1, dialogs
    dialog = dialogs[0]
    assert isinstance(dialog, QtWidgets.QDialog)
    # FreeCAD 1.1's expression field is a Gui::ExpressionTextEdit, a
    # QPlainTextEdit subclass.
    (text_edit,) = [
        child
        for child in dialog.findChildren(QtWidgets.QPlainTextEdit)
        if child.objectName() == "expression"
    ]
    text_edit.setPlainText(expression)
    _process_events()
    dialog.accept()
    _process_events()


def _open_formula_dialog(widget: QtWidgets.QWidget) -> None:
    widget.setFocus()
    QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Equal)
    _process_events()


def test_an_fx_expression_applies_and_leaves_no_trace(size_field: _SizeField) -> None:
    """The number is reported; the expression is gone from the bound
    property, which never moved, no undo step records it, and the field is
    editable again."""
    doc = size_field.doc
    doc.UndoMode = 1
    undo_names = list(doc.UndoNames)
    widget = size_field.field.quantity_widget
    assert widget is not None
    _open_formula_dialog(widget)
    _accept_formula_dialog("VarSet.Len - 20 mm")
    assert size_field.sizes_mm == [280.0]
    assert list(size_field.container.ExpressionEngine) == []
    assert FreeCAD.getActiveTransaction() is None
    doc.recompute()
    placement = cast("_Placed", size_field.container).Placement
    assert placement.Base == FreeCAD.Vector(0, 0, 0)
    assert list(doc.UndoNames) == undo_names
    assert not size_field.field.line_edit.isReadOnly()
    size_field.type("250")
    assert size_field.sizes_mm == [280.0, 250.0]


def test_the_plain_field_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no ``UiLoader`` the field is a plain line edit whose text goes
    to ``parseQuantity`` untouched, and a parse error is reported once,
    however the edit ends."""
    monkeypatch.setattr(FreeCADGui, "UiLoader", None, raising=False)
    fixture = _SizeField("panel_smoke_fallback")
    try:
        assert fixture.field.quantity_widget is None
        # parseQuantity reads this as 38.10 mm, where the quantity widget
        # reads the bare 1 as millimeters (.claude/docs/freecad-notes.md).
        fixture.type('1 + 1/2"')
        assert len(fixture.sizes_mm) == 1
        assert abs(fixture.sizes_mm[0] - 38.1) < _TOL_MM
        fixture.type('12 1/2"')
        assert len(fixture.errors) == 1
        # Leaving the field afterwards ends the same edit; no second popup.
        QtWidgets.QApplication.sendEvent(
            fixture.field.line_edit,
            QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut),
        )
        _process_events()
        assert len(fixture.errors) == 1, fixture.errors
        assert len(fixture.sizes_mm) == 1
    finally:
        fixture.close()


class _KeyRecorder(QtWidgets.QWidget):
    """A parent that counts the Return presses reaching it: what FreeCAD's
    task view would treat as OK."""

    def __init__(self) -> None:
        super().__init__()
        self.returns = 0

    @override
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.returns += 1
        super().keyPressEvent(event)


def test_unreadable_text_is_never_applied_and_keeps_return(
    size_field: _SizeField,
) -> None:
    recorder = _KeyRecorder()
    QtWidgets.QVBoxLayout(recorder).addWidget(size_field.window)
    recorder.show()
    _process_events()
    window_height_px = size_field.window.sizeHint().height()

    size_field.type('12 1/2"')
    assert size_field.sizes_mm == []
    assert recorder.returns == 0
    # Typing adds nothing around the field: a widget appearing mid-edit
    # changes the panel's height, which makes the task panel scroll.
    assert size_field.window.sizeHint().height() == window_height_px

    # Leaving the field with the text still unreadable applies nothing and
    # puts the last shown value back.
    field = size_field.field
    assert field.quantity_widget is not None
    QtWidgets.QApplication.sendEvent(
        field.quantity_widget, QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut)
    )
    _process_events()
    assert size_field.sizes_mm == []
    assert field.line_edit.text().startswith("200"), field.line_edit.text()

    size_field.type("300")
    assert size_field.sizes_mm == [300.0]
    assert recorder.returns == 0
    recorder.close()


def test_a_destroyed_field_ignores_late_events(
    size_field: _SizeField, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the task panel deletes its form, and Qt can still deliver a
    focus-out or ``editingFinished`` to a size field's callbacks during or
    after that. They must do nothing rather than touch the deleted widget,
    whose errors PySide6 would report through ``sys.excepthook`` (or, from
    a finalizer, ``sys.unraisablehook``)."""
    errors: list[BaseException] = []

    def record(
        kind: type[BaseException],
        value: BaseException,
        traceback: TracebackType | None,
    ) -> None:
        errors.append(value)

    def record_unraisable(unraisable: "sys.UnraisableHookArgs") -> None:
        if unraisable.exc_value is not None:
            errors.append(unraisable.exc_value)

    monkeypatch.setattr(sys, "excepthook", record)
    monkeypatch.setattr(sys, "unraisablehook", record_unraisable)
    field = size_field.field
    field.line_edit.setFocus()
    # Unreadable text, so a late focus-out would try to restore the value.
    QtTest.QTest.keyClicks(field.line_edit, '12 1/2"')
    Shiboken.delete(size_field.window)
    _process_events()
    assert not Shiboken.isValid(field.widget)

    field._discard_unreadable()
    field._finished()
    field._formula_dialog_toggled(False)
    _process_events()
    assert errors == []


def test_an_fx_unit_size_leaves_close_adding_nothing(unit_panel: _Fixture) -> None:
    doc = unit_panel.doc
    objects_before = len(doc.Objects)
    widget = unit_panel.panel.unit_fields["height"].quantity_widget
    assert widget is not None
    _open_formula_dialog(widget)
    _accept_formula_dialog("VarSet.Len * 3 + 100 mm")
    assert unit_panel.session.unit_dimension_mm("height") == pytest.approx(1000.0)
    names = list(doc.UndoNames)
    assert names[0] == "Resize Unit"
    unit_panel.panel.reject()
    assert list(doc.UndoNames) == names
    assert len(doc.Objects) == objects_before
    assert not doc.HasPendingTransaction


class _Placed(Protocol):
    Placement: FreeCAD.Placement


def _unit_field_mm(unit_panel: _Fixture, dimension: UnitDimension) -> float:
    spin = unit_panel.panel.unit_fields[dimension].quantity_widget
    assert spin is not None
    value_mm = spin.property("rawValue")
    assert isinstance(value_mm, float)
    return value_mm


def _type_unit_size(unit_panel: _Fixture, dimension: UnitDimension, text: str) -> None:
    line_edit = unit_panel.panel.unit_fields[dimension].line_edit
    line_edit.setFocus()
    line_edit.selectAll()
    QtTest.QTest.keyClicks(line_edit, text)
    QtTest.QTest.keyClick(line_edit, QtCore.Qt.Key.Key_Return)
    _process_events()


def _box_mm(unit_panel: _Fixture, name: str, attribute: str) -> float:
    return float(getattr(unit_panel.doc.getObject(name), attribute))


def test_the_unit_section_shows_the_units_size(unit_panel: _Fixture) -> None:
    assert _unit_field_mm(unit_panel, "width") == pytest.approx(600.0)
    assert _unit_field_mm(unit_panel, "depth") == pytest.approx(300.0)
    assert _unit_field_mm(unit_panel, "height") == pytest.approx(900.0)


def test_a_typed_height_resizes_the_unit_on_return(unit_panel: _Fixture) -> None:
    _type_unit_size(unit_panel, "height", "1000")
    unit_panel.doc.recompute()
    for name in ("left_side", "right_side"):
        assert _box_mm(unit_panel, name, "Height") == pytest.approx(964.0)
    assert _unit_field_mm(unit_panel, "height") == pytest.approx(1000.0)


def test_typing_alone_does_not_resize(unit_panel: _Fixture) -> None:
    """A half-typed value never applies: 1000 passes through 1, 10 and 100."""
    line_edit = unit_panel.panel.unit_fields["height"].line_edit
    line_edit.setFocus()
    line_edit.selectAll()
    QtTest.QTest.keyClicks(line_edit, "1000")
    _process_events()
    assert unit_panel.session.unit_dimension_mm("height") == pytest.approx(900.0)


def test_a_spin_step_resizes_at_once(unit_panel: _Fixture) -> None:
    field = unit_panel.panel.unit_fields["width"]
    spin = field.quantity_widget
    assert spin is not None
    top_length_mm = _box_mm(unit_panel, "top", "Length")
    spin.setFocus()
    QtTest.QTest.keyClick(spin, QtCore.Qt.Key.Key_Up)
    _process_events()
    unit_panel.doc.recompute()
    step_mm = _unit_field_mm(unit_panel, "width") - 600.0
    assert step_mm > 0
    assert unit_panel.session.unit_dimension_mm("width") == pytest.approx(
        600.0 + step_mm
    )
    assert _box_mm(unit_panel, "top", "Length") == pytest.approx(
        top_length_mm + step_mm
    )


def test_a_refused_unit_size_reports_and_changes_nothing(
    unit_panel: _Fixture, reported: list[str]
) -> None:
    def snapshot() -> list[tuple[str, str, float, float, float]]:
        return [
            (
                obj.Name,
                str(cast("_Placed", obj).Placement),
                _box_mm(unit_panel, obj.Name, "Length"),
                _box_mm(unit_panel, obj.Name, "Width"),
                _box_mm(unit_panel, obj.Name, "Height"),
            )
            for obj in unit_panel.doc.Objects
            if obj.TypeId == "Part::Box"
        ]

    before = snapshot()
    _type_unit_size(unit_panel, "height", "30")
    unit_panel.doc.recompute()
    (message,) = reported
    assert message
    after = snapshot()
    assert after == before
    assert _unit_field_mm(unit_panel, "height") == pytest.approx(900.0)


def _board_ids(region: Region) -> set[str]:
    if not isinstance(region, Division):
        return set()
    ids: set[str] = set()
    for item in region.items:
        ids |= {item.id} if isinstance(item, Board) else _board_ids(item)
    return ids


def test_the_unit_fields_follow_every_edit(unit_panel: _Fixture) -> None:
    _type_unit_size(unit_panel, "width", "700")
    before = _board_ids(unit_panel.session.unit.root)
    unit_panel.select(unit_panel.upper)
    assert unit_panel.session.split("horizontal") is None
    unit_panel.panel._refresh()
    sizes_mm: dict[UnitDimension, float] = {
        "width": 700.0,
        "depth": 300.0,
        "height": 900.0,
    }
    for dimension, size_mm in sizes_mm.items():
        assert _unit_field_mm(unit_panel, dimension) == pytest.approx(size_mm)

    (divider,) = _board_ids(unit_panel.session.unit.root) - before
    unit_panel.select(divider)
    assert unit_panel.session.merge() is None
    unit_panel.panel._refresh()
    assert _board_ids(unit_panel.session.unit.root) == before
    for dimension, size_mm in sizes_mm.items():
        assert _unit_field_mm(unit_panel, dimension) == pytest.approx(size_mm)


def _combo_texts(combo: QtWidgets.QComboBox) -> list[str]:
    return [combo.itemText(index) for index in range(combo.count())]


def test_each_size_field_offers_its_fixed_sides(unit_panel: _Fixture) -> None:
    combos = unit_panel.panel.fixed_combos
    assert _combo_texts(combos["width"]) == ["Left", "Center", "Right"]
    assert _combo_texts(combos["height"]) == ["Bottom", "Center", "Top"]
    assert _combo_texts(combos["depth"]) == ["Front", "Center", "Back"]
    for combo in combos.values():
        assert combo.currentIndex() == 0


def test_a_fixed_side_choice_is_an_undo_step_the_panel_follows(
    unit_panel: _Fixture,
) -> None:
    """Choosing "Top" adds one "Set Fixed Point" step and moves no board; a
    taller unit then grows downward. Undo and Redo inside the edit move the
    choice shown, and it survives Close and a new panel."""
    doc = unit_panel.doc
    combo = unit_panel.panel.fixed_combos["height"]
    placements = {
        obj.Name: str(cast("_Placed", obj).Placement)
        for obj in doc.Objects
        if obj.TypeId == "Part::Box"
    }
    names = list(doc.UndoNames)
    combo.setCurrentIndex(2)
    _process_events()
    assert list(doc.UndoNames) == ["Set Fixed Point", *names]
    assert {
        name: str(cast("_Placed", doc.getObject(name)).Placement) for name in placements
    } == placements
    assert unit_panel.session.fixed_side("height") == "max"

    top_z_mm = float(cast("_Placed", doc.getObject("top")).Placement.Base.z)
    _type_unit_size(unit_panel, "height", "1000")
    doc.recompute()
    assert float(
        cast("_Placed", doc.getObject("top")).Placement.Base.z
    ) == pytest.approx(top_z_mm, abs=_TOL_MM)
    assert float(
        cast("_Placed", doc.getObject("bottom")).Placement.Base.z
    ) == pytest.approx(-100.0, abs=_TOL_MM)

    doc.undo()
    doc.undo()
    _process_events()
    assert combo.currentIndex() == 0
    doc.redo()
    _process_events()
    assert combo.currentIndex() == 2

    unit_panel.panel.reject()
    # The fixture closes this one.
    unit_panel.panel = EditUnitPanel(unit_panel.container)
    assert unit_panel.panel.fixed_combos["height"].currentIndex() == 2
    assert unit_panel.panel.fixed_combos["width"].currentIndex() == 0


def test_a_held_arrow_past_a_limit_reports_once(
    unit_panel: _Fixture, reported: list[str]
) -> None:
    """55 mm leaves the two openings around the shelf 0.5 mm each; every
    repeat of a held down arrow past that refuses, and only the first
    refusal of the press is reported."""
    _type_unit_size(unit_panel, "height", "55")
    assert unit_panel.session.unit_dimension_mm("height") == pytest.approx(55.0)
    spin = unit_panel.panel.unit_fields["height"].quantity_widget
    assert spin is not None
    spin.setFocus()
    for auto_repeat in (False, True, True, True):
        event = QtGui.QKeyEvent(
            QtCore.QEvent.Type.KeyPress,
            QtCore.Qt.Key.Key_Down,
            QtCore.Qt.KeyboardModifier.NoModifier,
            "",
            auto_repeat,
        )
        QtWidgets.QApplication.sendEvent(spin, event)
        _process_events()
    assert len(reported) == 1, reported
    assert unit_panel.session.unit_dimension_mm("height") == pytest.approx(55.0)


def _wheel_down(widget: QtWidgets.QWidget) -> None:
    center = QtCore.QPointF(widget.rect().center())
    event = QtGui.QWheelEvent(
        center,
        QtCore.QPointF(widget.mapToGlobal(center.toPoint())),
        QtCore.QPoint(0, 0),
        QtCore.QPoint(0, -120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QtWidgets.QApplication.sendEvent(widget, event)
    _process_events()


def test_a_wheel_turn_past_a_limit_reports_once(
    unit_panel: _Fixture, reported: list[str]
) -> None:
    """Each notch steps the height down until the openings around the shelf
    would vanish; the notches past that are one turn of the wheel, and only
    its first refusal is reported."""
    _type_unit_size(unit_panel, "height", "60")
    spin = unit_panel.panel.unit_fields["height"].quantity_widget
    assert spin is not None
    spin.setFocus()
    _wheel_down(spin)
    step_mm = 60.0 - unit_panel.session.unit_dimension_mm("height")
    assert step_mm > 0
    for _notch in range(int(10.0 / step_mm) + 2):
        _wheel_down(spin)
    assert len(reported) == 1, reported
    assert 54.0 < unit_panel.session.unit_dimension_mm("height") < 60.0


def test_ancestor_watch_names_the_container_hiding_the_form() -> None:
    """A form on a background tab: the snapshot shows which ancestor hides
    it, bringing the tab forward reports the Show that reveals it, and once
    the form has been shown nothing more is reported."""
    tabs = QtWidgets.QTabWidget()
    tabs.addTab(QtWidgets.QWidget(), "Model")
    page = QtWidgets.QWidget()
    form = QtWidgets.QWidget()
    QtWidgets.QVBoxLayout(page).addWidget(form)
    tabs.addTab(page, "Tasks")
    tabs.show()
    _process_events()
    try:
        lines: list[str] = []
        watch = AncestorWatch(form, lines.append)
        watch.snapshot("start")
        assert any("not visible" in line for line in lines), lines
        assert any("child on page 1, current page 0" in line for line in lines), lines
        assert any("current tab 'Model'" in line for line in lines), lines

        lines.clear()
        tabs.setCurrentIndex(1)
        _process_events()
        assert any(
            line.startswith("form shown: ") and "child on the current page" in line
            for line in lines
        ), lines

        lines.clear()
        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)
        _process_events()
        watch.snapshot("after shown")
        assert lines == []
    finally:
        tabs.close()


def _plain_group_unit(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    """A fresh unit's boards moved into an ``App::DocumentObjectGroup``, a
    container with no ``Placement`` of its own."""
    part = create_unit(doc)
    doc.recompute()
    boards = list(cast("FreeCAD.DocumentObjectGroup", part).Group)
    group = cast(
        "FreeCAD.DocumentObjectGroup",
        doc.addObject("App::DocumentObjectGroup", "Plain"),
    )
    for board in boards:
        cast("FreeCAD.DocumentObjectGroup", part).removeObject(board)
        group.addObject(board)
    doc.removeObject(part.Name)
    doc.recompute()
    return cast("FreeCAD.DocumentObject", group)


def test_a_plain_group_unit_takes_sizes_and_fx() -> None:
    doc = _new_document("panel_plain_group")
    try:
        doc.UndoMode = 1
        group = _plain_group_unit(doc)
        assert not hasattr(group, "Placement")
        panel = EditUnitPanel(group)
        panel.form.show()
        _process_events()
        widget = panel.unit_fields["height"].quantity_widget
        assert widget is not None
        _open_formula_dialog(widget)
        _accept_formula_dialog("VarSet.Len * 3 + 100 mm")
        assert panel.session.unit_dimension_mm("height") == pytest.approx(1000.0)
        line_edit = panel.unit_fields["width"].line_edit
        line_edit.setFocus()
        line_edit.selectAll()
        QtTest.QTest.keyClicks(line_edit, "700")
        QtTest.QTest.keyClick(line_edit, QtCore.Qt.Key.Key_Return)
        _process_events()
        assert panel.session.unit_dimension_mm("width") == pytest.approx(700.0)
        assert list(doc.UndoNames)[:2] == ["Resize Unit", "Resize Unit"]
        panel.reject()
        assert [name for name in group.PropertiesList if "ShelvingField" in name] == []
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_unit_placed_by_an_expression_keeps_its_fields_editable() -> None:
    doc = _new_document("panel_placed_by_expression")
    try:
        container = create_unit(doc)
        container.setExpression("Placement.Base.x", "VarSet.Len")
        doc.recompute()
        panel = EditUnitPanel(container)
        panel.form.show()
        _process_events()
        for field in panel.unit_fields.values():
            assert not field.line_edit.isReadOnly()
        line_edit = panel.unit_fields["width"].line_edit
        line_edit.setFocus()
        line_edit.selectAll()
        QtTest.QTest.keyClicks(line_edit, "700")
        QtTest.QTest.keyClick(line_edit, QtCore.Qt.Key.Key_Return)
        _process_events()
        assert panel.session.unit_dimension_mm("width") == pytest.approx(700.0)
        panel.reject()
        assert ("Placement.Base.x", "VarSet.Len") in [
            (path.lstrip("."), expression)
            for path, expression in container.ExpressionEngine
        ]
    finally:
        FreeCAD.closeDocument(doc.Name)
