"""Offscreen-GUI check for the elevation editor's task panel.

``FreeCADGui.UiLoader``, and with it the ``Gui::QuantitySpinBox`` the
dimension field is built from, exists only in the full GUI, so
``tools/run-tests.sh`` runs this under ``QT_QPA_PLATFORM=offscreen freecad``
rather than ``freecadcmd`` (``docs/freecadcmd-notes.md``, "GUI-only widget
access"). The GUI keeps running after a script returns, so this ends in
``os._exit`` with the pass/fail status. It reports on ``sys.__stderr__``,
the process's own stream, since the GUI may route ``sys.stdout`` to its
Report view.

``EditUnitPanel`` is built directly rather than through
``FreeCADGui.Control.showDialog``: the task dialog machinery adds nothing
this check asserts.
"""

import os
import sys
import traceback
from collections.abc import Callable
from typing import cast

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import FreeCAD  # noqa: E402
import FreeCADGui  # noqa: E402
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
    for step in (dy_px // 2, dy_px):
        _mouse(view, QtCore.QEvent.Type.MouseMove, start + QtCore.QPoint(0, step), held)
    _mouse(
        view,
        QtCore.QEvent.Type.MouseButtonRelease,
        start + QtCore.QPoint(0, dy_px),
        QtCore.Qt.MouseButton.NoButton,
    )


def check_the_field_is_freecads_quantity_widget() -> None:
    fixture = _Fixture("panel_smoke_widget")
    try:
        widget = fixture.panel.size_field.quantity_widget
        assert widget is not None
        assert widget.inherits("Gui::QuantitySpinBox")
    finally:
        fixture.close()


def check_a_typed_size_and_a_varset_expression() -> None:
    fixture = _Fixture("panel_smoke_typed")
    try:
        fixture.select(fixture.lower)
        fixture.type_size("250")
        assert fixture.rule(fixture.lower) == Fixed(250.0), fixture.rule(fixture.lower)
        fixture.type_size("VarSet.Len - 20 mm")
        assert fixture.rule(fixture.lower) == Fixed(280.0), fixture.rule(fixture.lower)
        assert fixture.panel.message_label.text() == ""
    finally:
        fixture.close()


def check_an_unchanged_focus_out_leaves_a_fill_region() -> None:
    fixture = _Fixture("panel_smoke_focus_out")
    try:
        fixture.select(fixture.upper)
        assert fixture.rule(fixture.upper) == Fill()
        fixture.panel.size_field.line_edit.editingFinished.emit()
        _process_events()
        assert fixture.rule(fixture.upper) == Fill(), fixture.rule(fixture.upper)
    finally:
        fixture.close()


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


def check_an_fx_binding_applies_then_leaves_the_field_editable() -> None:
    fixture = _Fixture("panel_smoke_fx")
    try:
        fixture.select(fixture.lower)
        widget = fixture.panel.size_field.quantity_widget
        assert widget is not None
        widget.setFocus()
        QtTest.QTest.keyClick(widget, QtCore.Qt.Key.Key_Equal)
        _process_events()
        _accept_formula_dialog("VarSet.Len - 20 mm")
        assert fixture.rule(fixture.lower) == Fixed(280.0), fixture.rule(fixture.lower)
        probe = fixture.session.probe
        assert probe is not None
        assert not any(path == PROBE_PROPERTY for path, _expr in probe.ExpressionEngine)
        assert not fixture.panel.size_field.line_edit.isReadOnly()
        # Typing still works after the selection moves away and back. (Upper
        # cannot take a typed size here: with lower fixed it is the run's
        # only slack absorber.)
        fixture.select(fixture.upper)
        fixture.select(fixture.lower)
        fixture.type_size("250")
        assert fixture.rule(fixture.lower) == Fixed(250.0), fixture.rule(fixture.lower)
    finally:
        fixture.close()


def check_a_jittered_click_does_not_drag() -> None:
    fixture = _Fixture("panel_smoke_jitter")
    try:
        jitter_px = QtWidgets.QApplication.startDragDistance() - 1
        _press_move_release(fixture, -jitter_px)
        assert fixture.rule(fixture.lower) == Fill(), fixture.rule(fixture.lower)
        assert fixture.session.selected_id == fixture.shelf
        assert fixture.panel.delete_button.isEnabled()
    finally:
        fixture.close()


def check_a_drag_keeps_the_basis() -> None:
    fixture = _Fixture("panel_smoke_drag")
    try:
        fixture.select(fixture.lower)
        fixture.type_size("300")
        fixture.panel.basis_combo.setCurrentIndex(1)
        _process_events()
        assert fixture.rule(fixture.lower) == Fixed(318.0, Basis.WITH_NEXT)
        _press_move_release(fixture, -40)
        rule = fixture.rule(fixture.lower)
        assert isinstance(rule, Fixed), rule
        assert rule.basis is Basis.WITH_NEXT, rule
        assert rule.size_mm > 318.0 + _TOL_MM, rule
        assert fixture.session.selected_id == fixture.lower
        assert fixture.panel.basis_combo.currentIndex() == 1
    finally:
        fixture.close()


def check_untagged_objects_are_kept_unless_removed() -> None:
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
        assert panel.untagged_list.count() == 1
        item = panel.untagged_list.item(0)
        assert item is not None
        assert item.checkState() == QtCore.Qt.CheckState.Unchecked
        item.setCheckState(QtCore.Qt.CheckState.Checked)
        # A refresh keeps the check.
        panel._refresh()
        item = panel.untagged_list.item(0)
        assert item is not None
        assert item.checkState() == QtCore.Qt.CheckState.Checked
        panel.remove_untagged_button.click()
        _process_events()
        assert doc.getObject("HandAdded") is None
        assert not panel.untagged_box.isVisible()
        panel.reject()
        assert doc.getObject("HandAdded") is not None
        assert doc.getObject("ShelvingDimensionProbe") is None
    finally:
        FreeCAD.closeDocument(doc.Name)


def check_the_plain_field_fallback() -> None:
    """With no ``UiLoader`` the field is a plain line edit whose text goes
    to ``parseQuantity`` untouched, and a parse error reaches the message
    line."""
    loader = getattr(FreeCADGui, "UiLoader")  # noqa: B009 - restored below
    setattr(FreeCADGui, "UiLoader", None)  # noqa: B010 - restored below
    try:
        fixture = _Fixture("panel_smoke_fallback")
    finally:
        setattr(FreeCADGui, "UiLoader", loader)  # noqa: B010
    try:
        assert fixture.panel.size_field.quantity_widget is None
        fixture.select(fixture.lower)
        # parseQuantity reads this as 38.10 mm, where the quantity widget
        # reads the bare 1 as millimetres (docs/freecadcmd-notes.md).
        fixture.type_size('1 + 1/2"')
        rule = fixture.rule(fixture.lower)
        assert isinstance(rule, Fixed), rule
        assert abs(rule.size_mm - 38.1) < _TOL_MM, rule
        fixture.type_size('12 1/2"')
        assert fixture.panel.message_label.text() != ""
        assert fixture.rule(fixture.lower) == rule
    finally:
        fixture.close()


_CHECKS: tuple[Callable[[], None], ...] = (
    check_the_field_is_freecads_quantity_widget,
    check_a_typed_size_and_a_varset_expression,
    check_an_unchanged_focus_out_leaves_a_fill_region,
    check_an_fx_binding_applies_then_leaves_the_field_editable,
    check_a_jittered_click_does_not_drag,
    check_a_drag_keeps_the_basis,
    check_untagged_objects_are_kept_unless_removed,
    check_the_plain_field_fallback,
)


def main() -> int:
    report = sys.__stderr__
    assert report is not None
    failed = 0
    for check in _CHECKS:
        try:
            check()
        except Exception:  # noqa: BLE001 - reported, then the next check runs
            failed += 1
            print(f"FAIL {check.__name__}", file=report)
            traceback.print_exc(file=report)
        else:
            print(f"ok   {check.__name__}", file=report)
    if failed == 0:
        print("shelving panel OK", file=report)
    report.flush()
    return 1 if failed else 0


os._exit(main())
