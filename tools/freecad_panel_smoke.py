"""Offscreen-GUI check for the elevation editor's task panel.

A self-invoking pytest module, like ``tools/freecad_scan_smoke.py``, but run
under ``QT_QPA_PLATFORM=offscreen freecad`` rather than ``freecadcmd``:
``FreeCADGui.UiLoader``, and with it the ``Gui::QuantitySpinBox`` the
dimension field is built from, exists only in the full GUI
(``docs/freecadcmd-notes.md``, "GUI-only widget access").

``EditUnitPanel`` is built directly rather than through
``FreeCADGui.Control.showDialog``: the task dialog machinery adds nothing
this check asserts.
"""

import os
import sys

# The self-invocation comes before any FreeCAD import, so a module that
# fails to import is a pytest collection error with a failing status rather
# than an exception the GUI swallows while it keeps running forever. The
# environment variable stops pytest's own reimport of this file from
# recursing (docs/freecadcmd-notes.md). The GUI routes sys.stdout to its
# Report view, so the report goes to the process's own streams, and once a
# document has been opened sys.exit reports 1 whatever its argument, so the
# run ends in os._exit with pytest's status.
if os.environ.get("_FREECAD_PANEL_SMOKE_RUNNING") != "1":
    os.environ["_FREECAD_PANEL_SMOKE_RUNNING"] = "1"
    _exit_code = 1
    try:
        import pytest

        if sys.__stdout__ is not None and sys.__stderr__ is not None:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
        _exit_code = pytest.main([__file__, "-v"])
    finally:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(_exit_code)

from collections.abc import Iterator  # noqa: E402
from typing import cast  # noqa: E402

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import FreeCAD  # noqa: E402
import FreeCADGui  # noqa: E402
import pytest  # noqa: E402
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

from freecad.Shelving.core.layout import (  # noqa: E402
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Region,
    SizeRule,
)
from freecad.Shelving.editor.panel import EditUnitPanel  # noqa: E402
from freecad.Shelving.editor.session import PROBE_PROPERTY, Session  # noqa: E402
from freecad.Shelving.unit_ops import create_unit  # noqa: E402

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
def unit_panel(request: pytest.FixtureRequest) -> Iterator[_Fixture]:
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


def test_a_typed_size_and_a_varset_expression(unit_panel: _Fixture) -> None:
    unit_panel.select(unit_panel.lower)
    unit_panel.type_size("250")
    assert unit_panel.rule(unit_panel.lower) == Fixed(250.0)
    unit_panel.type_size("VarSet.Len - 20 mm")
    assert unit_panel.rule(unit_panel.lower) == Fixed(280.0)
    assert unit_panel.panel.message_label.text() == ""


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
    (line_edit,) = [
        child
        for child in dialog.findChildren(QtWidgets.QLineEdit)
        if child.objectName() == "expression"
    ]
    line_edit.setText(expression)
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


def test_the_plain_field_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no ``UiLoader`` the field is a plain line edit whose text goes
    to ``parseQuantity`` untouched, and a parse error reaches the message
    line."""
    monkeypatch.setattr(FreeCADGui, "UiLoader", None, raising=False)
    fixture = _Fixture("panel_smoke_fallback")
    try:
        assert fixture.panel.size_field.quantity_widget is None
        fixture.select(fixture.lower)
        # parseQuantity reads this as 38.10 mm, where the quantity widget
        # reads the bare 1 as millimetres (docs/freecadcmd-notes.md).
        fixture.type_size('1 + 1/2"')
        rule = fixture.rule(fixture.lower)
        assert isinstance(rule, Fixed)
        assert abs(rule.size_mm - 38.1) < _TOL_MM
        fixture.type_size('12 1/2"')
        assert fixture.panel.message_label.text() != ""
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


def test_unreadable_text_is_flagged_never_applied_and_keeps_return(
    unit_panel: _Fixture,
) -> None:
    recorder = _KeyRecorder()
    QtWidgets.QVBoxLayout(recorder).addWidget(unit_panel.panel.form)
    recorder.show()
    _process_events()
    unit_panel.select(unit_panel.lower)
    status = unit_panel.panel.size_field.status_label
    assert not status.isVisible()

    unit_panel.type_size('12 1/2"')
    assert status.isVisible()
    assert status.text() != ""
    assert unit_panel.rule(unit_panel.lower) == Fill()
    assert recorder.returns == 0

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
    assert not status.isVisible()

    unit_panel.type_size("300")
    assert unit_panel.rule(unit_panel.lower) == Fixed(300.0)
    assert not status.isVisible()
    assert recorder.returns == 0


def test_an_unsolvable_size_explains_itself_without_ids(unit_panel: _Fixture) -> None:
    unit_panel.select(unit_panel.lower)
    unit_panel.type_size("5000")
    message = unit_panel.panel.message_label.text()
    assert message.startswith("The fixed sizes add up to"), message
    assert unit_panel.lower not in message
    assert unit_panel.rule(unit_panel.lower) == Fill()
