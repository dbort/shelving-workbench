"""The elevation editor's task panel, with FreeCAD's GUI up.

``FreeCADGui.UiLoader``, and with it the ``Gui::QuantitySpinBox`` the
dimension field is built from, exists only once the GUI is running, which
this directory's ``conftest.py`` arranges (``.claude/docs/freecad-notes.md``,
"GUI-only widget access").

``EditUnitPanel`` is built directly rather than through
``FreeCADGui.Control.showDialog``: the task dialog machinery adds nothing
these tests assert.
"""

import sys
from collections.abc import Iterator
from types import TracebackType
from typing import cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets
from shiboken6 import Shiboken

from freecad.Shelving.core.layout import (
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Region,
    SizeRule,
)
from freecad.Shelving.editor import panel as panel_module
from freecad.Shelving.editor.panel import AncestorWatch, EditUnitPanel
from freecad.Shelving.editor.session import PROBE_PROPERTY, Session
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


class _Fixture:
    """A fresh document holding a ``VarSet`` with ``Len = 300 mm``, a unit
    with one shelf, and an open panel on it: ``lower`` and ``upper`` name
    the two bays either side of the shelf."""

    def __init__(self, name: str) -> None:
        self.doc = FreeCAD.newDocument(name)
        varset = cast(
            "FreeCAD.DocumentObject", self.doc.addObject("App::VarSet", "VarSet")
        )
        varset.addProperty("App::PropertyLength", "Len")
        setattr(varset, "Len", 300.0)  # noqa: B010 - a dynamic property
        self.container = create_unit(self.doc)
        self.doc.recompute()
        self.panel = EditUnitPanel(self.container)
        self.panel.form.resize(900, 1400)
        self.panel.form.show()
        _process_events()
        self.select(_bay_ids(self.session.unit.root)[0])
        self.panel.add_shelf_button.click()
        self.lower, self.upper = _bay_ids(self.session.unit.root)
        self.shelf = next(
            item.id
            for item in _shelf_run(self.session.unit.root).items
            if isinstance(item, Board)
        )

    @property
    def session(self) -> Session:
        return self.panel.session

    def select(self, node_id: str) -> None:
        self.panel.session.select(node_id)
        self.panel._refresh()

    def rule(self, region_id: str) -> SizeRule | None:
        return _rule_of(self.panel.session.unit.root, region_id)

    def type_size(self, text: str) -> None:
        line_edit = self.panel.size_field.line_edit
        line_edit.setFocus()
        line_edit.selectAll()
        QtTest.QTest.keyClicks(line_edit, text)
        QtTest.QTest.keyClick(line_edit, QtCore.Qt.Key.Key_Return)
        _process_events()

    def close(self) -> None:
        self.panel.reject()
        FreeCAD.closeDocument(self.doc.Name)


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every message the panel sends to FreeCAD's Notification Area, in
    order, instead of sending it. Requested before the panel is built, since
    the panel hands ``report_error`` to its size field at construction."""
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


def _shelf_run(region: Region) -> Division:
    """The ``Division`` the fixture's one shelf sits in."""
    assert isinstance(region, Division)
    for item in region.items:
        if isinstance(item, Division):
            if any(isinstance(child, Bay) for child in item.items):
                return item
            return _shelf_run(item)
    raise AssertionError("no run holding a bay")


def _mouse(
    view: QtWidgets.QGraphicsView,
    kind: QtCore.QEvent.Type,
    pos: QtCore.QPoint,
    buttons: QtCore.Qt.MouseButton,
) -> None:
    """Send one mouse event to ``view``'s viewport. ``QTest.mouseMove``
    carries no held button in Qt 6, so a drag is built from raw events."""
    viewport = view.viewport()
    event = QtGui.QMouseEvent(
        kind,
        QtCore.QPointF(pos),
        QtCore.QPointF(viewport.mapToGlobal(pos)),
        QtCore.Qt.MouseButton.LeftButton,
        buttons,
        QtCore.Qt.KeyboardModifier.NoModifier,
    )
    QtWidgets.QApplication.sendEvent(viewport, event)
    _process_events()


def _shelf_viewport_pos(fixture: _Fixture) -> QtCore.QPoint:
    """A viewport point on the shelf, away from every dimension label."""
    space = fixture.session.spaces[fixture.shelf]
    scene_point = QtCore.QPointF(
        space.origin.x_mm + 40.0,
        fixture.session.unit.size_mm.z_mm - space.origin.z_mm - space.size.z_mm / 2,
    )
    return fixture.panel.view.mapFromScene(scene_point)


def _press_move_release(fixture: _Fixture, dy_px: int) -> None:
    view = fixture.panel.view
    start = _shelf_viewport_pos(fixture)
    held = QtCore.Qt.MouseButton.LeftButton
    _mouse(view, QtCore.QEvent.Type.MouseButtonPress, start, held)
    # Two steps, so the second is a move after the drag has begun.
    for step_px in (dy_px // 2, dy_px):
        _mouse(
            view, QtCore.QEvent.Type.MouseMove, start + QtCore.QPoint(0, step_px), held
        )
    _mouse(
        view,
        QtCore.QEvent.Type.MouseButtonRelease,
        start + QtCore.QPoint(0, dy_px),
        QtCore.Qt.MouseButton.NoButton,
    )


def test_the_field_is_freecads_quantity_widget(unit_panel: _Fixture) -> None:
    widget = unit_panel.panel.size_field.quantity_widget
    assert widget is not None
    assert widget.inherits("Gui::QuantitySpinBox")


def test_a_typed_size_and_a_varset_expression(
    unit_panel: _Fixture, reported: list[str]
) -> None:
    unit_panel.select(unit_panel.lower)
    unit_panel.type_size("250")
    assert unit_panel.rule(unit_panel.lower) == Fixed(250.0)
    unit_panel.type_size("VarSet.Len - 20 mm")
    assert unit_panel.rule(unit_panel.lower) == Fixed(280.0)
    assert reported == []


def test_an_unchanged_focus_out_leaves_a_fill_region(unit_panel: _Fixture) -> None:
    unit_panel.select(unit_panel.upper)
    assert unit_panel.rule(unit_panel.upper) == Fill()
    unit_panel.panel.size_field.line_edit.editingFinished.emit()
    _process_events()
    assert unit_panel.rule(unit_panel.upper) == Fill()


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


def test_an_fx_binding_applies_then_leaves_the_field_editable(
    unit_panel: _Fixture,
) -> None:
    unit_panel.select(unit_panel.lower)
    widget = unit_panel.panel.size_field.quantity_widget
    assert widget is not None
    widget.setFocus()
    QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Equal)
    _process_events()
    _accept_formula_dialog("VarSet.Len - 20 mm")
    assert unit_panel.rule(unit_panel.lower) == Fixed(280.0)
    probe = unit_panel.session.probe
    assert probe is not None
    assert not any(path == PROBE_PROPERTY for path, _expr in probe.ExpressionEngine)
    assert not unit_panel.panel.size_field.line_edit.isReadOnly()
    # Typing still works after the selection moves away and back. (Upper
    # cannot take a typed size here: with lower fixed it is the run's only
    # slack absorber.)
    unit_panel.select(unit_panel.upper)
    unit_panel.select(unit_panel.lower)
    unit_panel.type_size("250")
    assert unit_panel.rule(unit_panel.lower) == Fixed(250.0)


def test_a_jittered_click_does_not_drag(unit_panel: _Fixture) -> None:
    jitter_px = QtWidgets.QApplication.startDragDistance() - 1
    _press_move_release(unit_panel, -jitter_px)
    assert unit_panel.rule(unit_panel.lower) == Fill()
    assert unit_panel.session.selected_id == unit_panel.shelf
    assert unit_panel.panel.delete_button.isEnabled()


def test_a_drag_keeps_the_basis(unit_panel: _Fixture) -> None:
    unit_panel.select(unit_panel.lower)
    unit_panel.type_size("300")
    unit_panel.panel.basis_combo.setCurrentIndex(1)
    _process_events()
    assert unit_panel.rule(unit_panel.lower) == Fixed(318.0, Basis.WITH_NEXT)
    _press_move_release(unit_panel, -40)
    rule = unit_panel.rule(unit_panel.lower)
    assert isinstance(rule, Fixed)
    assert rule.basis is Basis.WITH_NEXT
    assert rule.size_mm > 318.0 + _TOL_MM
    assert unit_panel.session.selected_id == unit_panel.lower
    assert unit_panel.panel.basis_combo.currentIndex() == 1


def test_untagged_objects_are_kept_unless_removed() -> None:
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
        panel.remove_untagged_button.click()
        _process_events()
        assert doc.getObject("HandAdded") is None
        assert not panel.untagged_box.isVisible()
        panel.reject()
        assert doc.getObject("HandAdded") is not None
        assert doc.getObject("ShelvingDimensionProbe") is None
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_the_plain_field_fallback(
    monkeypatch: pytest.MonkeyPatch, reported: list[str]
) -> None:
    """With no ``UiLoader`` the field is a plain line edit whose text goes
    to ``parseQuantity`` untouched, and a parse error is reported once,
    however the edit ends."""
    monkeypatch.setattr(FreeCADGui, "UiLoader", None, raising=False)
    fixture = _Fixture("panel_smoke_fallback")
    try:
        assert fixture.panel.size_field.quantity_widget is None
        fixture.select(fixture.lower)
        # parseQuantity reads this as 38.10 mm, where the quantity widget
        # reads the bare 1 as millimetres (.claude/docs/freecad-notes.md).
        fixture.type_size('1 + 1/2"')
        rule = fixture.rule(fixture.lower)
        assert isinstance(rule, Fixed)
        assert abs(rule.size_mm - 38.1) < _TOL_MM
        fixture.type_size('12 1/2"')
        assert len(reported) == 1
        # Leaving the field afterwards ends the same edit; no second popup.
        QtWidgets.QApplication.sendEvent(
            fixture.panel.size_field.line_edit,
            QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut),
        )
        _process_events()
        assert len(reported) == 1, reported
        assert fixture.rule(fixture.lower) == rule
    finally:
        fixture.close()


class _KeyRecorder(QtWidgets.QWidget):
    """A parent that counts the Return presses reaching it: what FreeCAD's
    task view would treat as OK."""

    def __init__(self) -> None:
        super().__init__()
        self.returns = 0

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            self.returns += 1
        super().keyPressEvent(event)


def test_unreadable_text_is_never_applied_and_keeps_return(
    unit_panel: _Fixture,
) -> None:
    recorder = _KeyRecorder()
    QtWidgets.QVBoxLayout(recorder).addWidget(unit_panel.panel.form)
    recorder.show()
    _process_events()
    unit_panel.select(unit_panel.lower)
    form_height_px = unit_panel.panel.form.sizeHint().height()

    unit_panel.type_size('12 1/2"')
    assert unit_panel.rule(unit_panel.lower) == Fill()
    assert recorder.returns == 0
    # Typing adds nothing to the panel: a widget appearing mid-edit changes
    # the panel's height, which makes the task panel scroll.
    assert unit_panel.panel.form.sizeHint().height() == form_height_px

    # Leaving the field with the text still unreadable applies nothing and
    # puts the last shown value back.
    field = unit_panel.panel.size_field
    assert field.quantity_widget is not None
    shown_text = f"{unit_panel.session.spaces[unit_panel.lower].size.z_mm:.2f}"
    QtWidgets.QApplication.sendEvent(
        field.quantity_widget, QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut)
    )
    _process_events()
    assert unit_panel.rule(unit_panel.lower) == Fill()
    assert field.line_edit.text().startswith(shown_text), field.line_edit.text()

    unit_panel.type_size("300")
    assert unit_panel.rule(unit_panel.lower) == Fixed(300.0)
    assert recorder.returns == 0


def test_an_unsolvable_size_explains_itself_without_ids(
    unit_panel: _Fixture, reported: list[str]
) -> None:
    unit_panel.select(unit_panel.lower)
    unit_panel.type_size("5000")
    (message,) = reported
    assert message.startswith("The fixed sizes add up to"), message
    assert unit_panel.lower not in message
    assert unit_panel.rule(unit_panel.lower) == Fill()


def test_a_drag_past_its_limit_reports_once(
    unit_panel: _Fixture, reported: list[str]
) -> None:
    view = unit_panel.panel.view
    start = _shelf_viewport_pos(unit_panel)
    held = QtCore.Qt.MouseButton.LeftButton
    # Each of these moves is far enough down to pass the bottom board.
    beyond_px = int(unit_panel.session.spaces[unit_panel.shelf].origin.z_mm) + 100
    _mouse(view, QtCore.QEvent.Type.MouseButtonPress, start, held)
    for step_px in (beyond_px, beyond_px + 20, beyond_px + 40):
        _mouse(
            view, QtCore.QEvent.Type.MouseMove, start + QtCore.QPoint(0, step_px), held
        )
    _mouse(
        view,
        QtCore.QEvent.Type.MouseButtonRelease,
        start + QtCore.QPoint(0, beyond_px + 40),
        QtCore.Qt.MouseButton.NoButton,
    )
    (message,) = reported
    assert "cannot move past" in message, message


def test_report_error_reaches_freecads_console() -> None:
    """The real call, unpatched: the two-argument form the stubs omit."""
    panel_module.report_error("panel smoke: report_error reached the console")


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


def test_a_split_refusal_names_no_region_id(
    unit_panel: _Fixture, reported: list[str]
) -> None:
    unit_panel.select(unit_panel.lower)
    unit_panel.type_size("10")
    unit_panel.select(unit_panel.lower)
    unit_panel.panel.add_shelf_button.click()
    _process_events()
    (message,) = reported
    assert "too small" in message, message
    assert unit_panel.lower not in message


def test_a_destroyed_field_ignores_late_events(
    unit_panel: _Fixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the task panel deletes its form, and Qt can still deliver a
    focus-out or ``editingFinished`` to the size field's callbacks during or
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
    field = unit_panel.panel.size_field
    unit_panel.select(unit_panel.lower)
    field.line_edit.setFocus()
    # Unreadable text, so a late focus-out would try to restore the value.
    QtTest.QTest.keyClicks(field.line_edit, '12 1/2"')
    Shiboken.delete(unit_panel.panel.form)
    _process_events()
    assert not Shiboken.isValid(field.widget)

    field._discard_unreadable()
    field._finished()
    _process_events()
    assert errors == []
