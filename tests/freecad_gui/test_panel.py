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
from typing import Protocol, cast

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
from freecad.Shelving.editor.session import PROBE_PROPERTY, Session, UnitDimension
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
        # reads the bare 1 as millimeters (.claude/docs/freecad-notes.md).
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
    unit_panel.panel.add_divider_button.click()
    _process_events()
    sizes_mm: dict[UnitDimension, float] = {
        "width": 700.0,
        "depth": 300.0,
        "height": 900.0,
    }
    for dimension, size_mm in sizes_mm.items():
        assert _unit_field_mm(unit_panel, dimension) == pytest.approx(size_mm)

    (divider,) = _board_ids(unit_panel.session.unit.root) - before
    unit_panel.select(divider)
    unit_panel.panel.delete_button.click()
    _process_events()
    assert _board_ids(unit_panel.session.unit.root) == before
    for dimension, size_mm in sizes_mm.items():
        assert _unit_field_mm(unit_panel, dimension) == pytest.approx(size_mm)


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


def test_the_elevation_keeps_a_usable_height_in_a_short_panel(
    unit_panel: _Fixture,
) -> None:
    """The elevation keeps at least ``_MIN_VIEW_HEIGHT_PX`` in a short panel
    and takes most of a tall one."""
    form = unit_panel.panel.form
    form.resize(400, 200)
    _process_events()
    assert unit_panel.panel.view.height() >= panel_module._MIN_VIEW_HEIGHT_PX
    form.resize(400, 1400)
    _process_events()
    # A tall panel's spare height goes to the elevation.
    assert unit_panel.panel.view.height() > 1400 // 2
