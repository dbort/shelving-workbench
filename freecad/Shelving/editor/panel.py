"""The elevation editor's task panel: a thin Qt shell over one ``Session``.

``EditUnitPanel`` satisfies the duck-typed protocol
``FreeCADGui.Control.showDialog`` expects: a ``form`` attribute (the
``QWidget`` shown in the task panel), ``getStandardButtons``, ``accept``,
``reject``. Every control calls a ``Session`` method and redraws from what it
returns; the decisions left here are input handling: the start-drag
threshold, reporting only a changed size, never applying text the quantity
widget rejects (consuming its Return, restoring the shown value when focus
leaves), reporting only a drag's first failure, and keeping checked items
across a redraw. ``FreeCADGui.Control`` does not exist under ``freecadcmd``, so
:mod:`tools.freecad_panel_smoke` exercises this module under the offscreen
GUI instead.

The dimension field is FreeCAD's own ``Gui::QuantitySpinBox``, so it
accepts, resolves, and displays exactly what every other length field in
FreeCAD does. This module reads only the resolved millimetre value it
reports and never looks at the typed text.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.core.layout import Basis
from freecad.Shelving.debug_log import Stopwatch
from freecad.Shelving.editor.scene import build_scene, elevation_point_mm, hit_test
from freecad.Shelving.editor.session import (
    PROBE_PROPERTY,
    EditFailure,
    Session,
    SplitDirection,
)

# freecad-stubs declares UiLoader.createWidget without parameters and
# ExpressionBinding with no methods at all, so these Protocols state the
# signatures docs/freecadcmd-notes.md verified.


class _UiLoader(Protocol):
    def createWidget(self, class_name: str, /) -> QtWidgets.QWidget | None: ...


class _ExpressionBinding(Protocol):
    def bind(self, obj: FreeCAD.DocumentObject, property_name: str, /) -> None: ...


# freecad-stubs declares PrintTranslatedUserError with one argument, but
# FreeCAD 1.0 and 1.1 accept (notifier, message), and the notifier is what
# labels the popup in the Notification Area.
_print_user_error = cast(
    "Callable[[str, str], None]", FreeCAD.Console.PrintTranslatedUserError
)


def report_error(message: str) -> None:
    """Show ``message`` as a Shelving error in FreeCAD's Notification Area,
    which pops it up briefly and keeps it in the Report view."""
    _print_user_error("Shelving", message + "\n")


_BASIS_CHOICES: tuple[tuple[str, Basis], ...] = (
    ("Clear opening", Basis.CLEAR),
    ("Spacing (through the next board)", Basis.WITH_NEXT),
)


def _format_mm(value_mm: float) -> str:
    return f"{value_mm:.2f} mm"


class _FieldEventFilter(QtCore.QObject):
    """Consumes every Return and Enter key press on the widgets it is
    installed on, calling ``on_return`` instead, and calls ``on_focus_out``
    before the widget itself sees a focus-out. Unconsumed, a Return the
    quantity widget rejects reaches the task panel, which treats it as OK
    and closes the editor."""

    def __init__(
        self,
        parent: QtCore.QObject,
        on_return: Callable[[], None],
        on_focus_out: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self._on_return = on_return
        self._on_focus_out = on_focus_out

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.FocusOut:
            self._on_focus_out()
            return False
        if event.type() != QtCore.QEvent.Type.KeyPress:
            return False
        key = cast("QtGui.QKeyEvent", event).key()
        if key not in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter):
            return False
        self._on_return()
        return True


class _DimensionField:
    """The size input: FreeCAD's quantity widget bound to the session's
    probe object, or, when the GUI cannot supply that widget, a plain line
    edit whose text goes to ``FreeCAD.Units.parseQuantity`` verbatim.

    Text the quantity widget cannot resolve is never applied, and how the
    field looks while it holds such text is the widget's own business.
    Whether the text resolves is the widget's verdict, read from its
    ``acceptableInput``; this class never looks at the text itself.

    ``on_size`` receives the resolved millimetres; ``on_error`` receives
    ``parseQuantity``'s own message, from the fallback only;
    ``on_expression_done`` is called once the f(x) dialog closes, after any
    ``on_size`` it caused.
    """

    def __init__(
        self,
        probe: FreeCAD.DocumentObject | None,
        on_size: Callable[[float], None],
        on_error: Callable[[str], None],
        on_expression_done: Callable[[], None],
    ) -> None:
        self._on_size = on_size
        self._on_error = on_error
        self._on_expression_done = on_expression_done
        loader_type = cast(
            "Callable[[], _UiLoader] | None", getattr(FreeCADGui, "UiLoader", None)
        )
        spin = (
            loader_type().createWidget("Gui::QuantitySpinBox")
            if loader_type is not None
            else None
        )
        self.quantity_widget = spin
        if spin is not None:
            spin.setProperty("unit", "mm")
            if probe is not None:
                binding_type = cast(
                    "Callable[[QtWidgets.QWidget], _ExpressionBinding]",
                    FreeCADGui.ExpressionBinding,
                )
                # Held for the widget's lifetime: the binding is what lets
                # the field resolve a VarSet name.
                self._binding = binding_type(spin)
                self._binding.bind(probe, PROBE_PROPERTY)
            line_edit = spin.findChild(QtWidgets.QLineEdit)
            assert line_edit is not None
            self.line_edit = line_edit
            self.widget: QtWidgets.QWidget = spin
        else:
            self.line_edit = QtWidgets.QLineEdit()
            self.widget = self.line_edit
        self._event_filter = _FieldEventFilter(
            self.widget, self._finished, self._discard_unreadable
        )
        self.widget.installEventFilter(self._event_filter)
        if self.line_edit is not self.widget:
            self.line_edit.installEventFilter(self._event_filter)
        # What show_mm last displayed. editingFinished also fires when the
        # field merely loses focus, and reporting an unchanged value would
        # quietly fix a region that shares leftover space.
        self._shown_mm: float | None = None
        self._shown_text = ""
        # The fallback text parseQuantity last refused. A consumed Return and
        # the focus-out after it both finish the same edit, and the refusal
        # is reported once.
        self._rejected_text: str | None = None
        self.line_edit.editingFinished.connect(self._finished)
        if spin is not None:
            # Accepting the f(x) dialog changes the value without any
            # editingFinished; the dialog closing is the only signal.
            QtCore.QObject.connect(
                spin,
                QtCore.SIGNAL("showFormulaDialog(bool)"),
                self._formula_dialog_toggled,
            )

    def _formula_dialog_toggled(self, shown: bool) -> None:
        if not shown:
            self._finished()
            self._on_expression_done()

    def _acceptable(self) -> bool:
        """The quantity widget's verdict on its current text; always
        ``True`` for the fallback field, which learns only by parsing."""
        if self.quantity_widget is None:
            return True
        return bool(self.quantity_widget.property("acceptableInput"))

    def _discard_unreadable(self) -> None:
        """Put the last shown value back before the widget handles a
        focus-out. Left alone, the widget settles on whatever a prefix of the
        unreadable text resolved to and reports that as a finished edit."""
        if not self._acceptable():
            self.show_mm(self._shown_mm)

    def _finished(self) -> None:
        if self.quantity_widget is not None:
            # While the text is unacceptable, rawValue still holds the last
            # value some prefix of it resolved to (12 mm for 12 1/2").
            if not self._acceptable():
                return
            value_mm = self.quantity_widget.property("rawValue")
            if isinstance(value_mm, float) and value_mm != self._shown_mm:
                self._on_size(value_mm)
            return
        text = self.line_edit.text()
        if text in (self._shown_text, self._rejected_text):
            return
        try:
            quantity = FreeCAD.Units.parseQuantity(text)
        except Exception as err:  # noqa: BLE001 - its message is the report
            self._rejected_text = text
            self._on_error(str(err).strip())
            return
        self._on_size(float(quantity.Value))

    def show_mm(self, value_mm: float | None) -> None:
        """Display ``value_mm``, or clear the field for ``None``; never
        reports back through ``on_size``."""
        self.widget.setEnabled(value_mm is not None)
        self.widget.blockSignals(True)
        if self.quantity_widget is not None:
            if value_mm is not None:
                self.quantity_widget.setProperty("rawValue", value_mm)
                # Read back rather than kept: the widget may round what it
                # stores, and _finished compares against its own value.
                shown_mm = self.quantity_widget.property("rawValue")
                self._shown_mm = shown_mm if isinstance(shown_mm, float) else value_mm
            else:
                self._shown_mm = None
        else:
            self._shown_text = "" if value_mm is None else f"{value_mm:g} mm"
            self._rejected_text = None
            self.line_edit.setText(self._shown_text)
        self.widget.blockSignals(False)


class _EditorView(QtWidgets.QGraphicsView):
    """A ``QGraphicsView`` that reports the scene position of every press to
    ``on_click``, every move with the left button held to ``on_drag`` once
    the pointer has travelled the platform's start-drag distance from the
    press, and every release to ``on_release``."""

    def __init__(
        self,
        on_click: Callable[[QtCore.QPointF], None],
        on_drag: Callable[[QtCore.QPointF], None],
        on_release: Callable[[], None],
    ) -> None:
        super().__init__()
        self._on_click = on_click
        self._on_drag = on_drag
        self._on_release = on_release
        # The viewport position of the current press, held until the pointer
        # travels the start-drag distance; without it a click's jitter would
        # resize the region below the clicked board.
        self._press_pos: QtCore.QPoint | None = None
        self._drag_started = False
        # Called once, with the paint's duration in ms, on the first paint of
        # the elevation; the Edit Unit run's debug_log timing ends there.
        self.on_first_paint: Callable[[float], None] | None = None

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        callback = self.on_first_paint
        if callback is None:
            super().paintEvent(event)
            return
        self.on_first_paint = None
        start_s = time.perf_counter()
        super().paintEvent(event)
        callback((time.perf_counter() - start_s) * 1000)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mousePressEvent(event)
        scene = self.scene()
        if scene is not None:
            self._press_pos = event.position().toPoint()
            self._drag_started = False
            self._on_click(self.mapToScene(self._press_pos))

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        if not event.buttons() & QtCore.Qt.MouseButton.LeftButton:
            return
        pos = event.position().toPoint()
        if not self._drag_started:
            if self._press_pos is None:
                return
            travelled_px = (pos - self._press_pos).manhattanLength()
            if travelled_px < QtWidgets.QApplication.startDragDistance():
                return
            self._drag_started = True
        self._on_drag(self.mapToScene(pos))

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        self._press_pos = None
        self._drag_started = False
        self._on_release()


class FirstEvents(QtCore.QObject):
    """Calls ``on_event`` with a name the first time each event type in
    ``names`` reaches ``target``, then stops filtering; the event itself
    is passed through untouched.

    Parented to ``target``, so it lives exactly as long as the widget.
    """

    def __init__(
        self,
        target: QtCore.QObject,
        names: Mapping[QtCore.QEvent.Type, str],
        on_event: Callable[[str], None],
    ) -> None:
        super().__init__(target)
        self._target = target
        self._pending = dict(names)
        self._on_event = on_event
        target.installEventFilter(self)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        name = self._pending.pop(event.type(), None)
        if name is not None:
            self._on_event(name)
            if not self._pending:
                self._target.removeEventFilter(self)
        return False


def _describe(widget: QtWidgets.QWidget, child: QtWidgets.QWidget | None) -> str:
    """``widget``'s type, name, and whether it lets ``child`` (the next
    widget down toward the form, when known) be seen."""
    # PySide6-stubs types className() as bytes; at runtime it is a str.
    class_name: object = widget.metaObject().className()
    parts = [class_name if isinstance(class_name, str) else repr(class_name)]
    if widget.objectName():
        parts.append(repr(widget.objectName()))
    parts.append("visible" if widget.isVisible() else "not visible")
    if widget.isHidden():
        parts.append("hidden itself")
    if isinstance(widget, QtWidgets.QStackedWidget) and child is not None:
        current = widget.currentIndex()
        page = widget.indexOf(child)
        parts.append(
            "child on the current page"
            if page == current
            else f"child on page {page}, current page {current}"
        )
    if isinstance(widget, QtWidgets.QTabWidget):
        parts.append(f"current tab {widget.tabText(widget.currentIndex())!r}")
    if isinstance(widget, QtWidgets.QDockWidget):
        parts.append("floating" if widget.isFloating() else "docked")
    return ", ".join(parts)


class AncestorWatch(QtCore.QObject):
    """Reports through ``on_line`` how each ancestor of ``form`` stands, and
    every Show or Hide among them, until ``form`` is first shown; then
    reports the ancestors once more and stops. Qt delivers a newly shown
    ancestor's Show after its children's, so that last report, set against
    an earlier :meth:`snapshot`, is what names the ancestor that revealed the
    form.

    Exists to name whichever container keeps a shown task dialog's form out
    of sight (bug-011). Parented to ``form``, so it lives exactly as long as
    the form.
    """

    def __init__(self, form: QtWidgets.QWidget, on_line: Callable[[str], None]) -> None:
        super().__init__(form)
        self._form = form
        self._on_line = on_line
        self._watched: list[QtWidgets.QWidget] = []
        self._done = False
        form.installEventFilter(self)

    def snapshot(self, when: str) -> None:
        """Report the form's ancestors as they are now, nearest first, and
        start watching any not already watched. May be called again: the
        task view can reparent the form after ``showDialog`` returns. Does
        nothing once the form has been shown."""
        if self._done:
            return
        self._report_chain(when, watch=True)

    def _report_chain(self, when: str, *, watch: bool) -> None:
        child: QtWidgets.QWidget = self._form
        parent = child.parentWidget()
        if parent is None:
            self._on_line(f"{when}: form has no parent")
        depth = 1
        while parent is not None:
            self._on_line(f"{when}: ancestor {depth}: {_describe(parent, child)}")
            if watch and not any(watched is parent for watched in self._watched):
                parent.installEventFilter(self)
                self._watched.append(parent)
            child, parent = parent, parent.parentWidget()
            depth += 1

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        kind = event.type()
        if kind not in (QtCore.QEvent.Type.Show, QtCore.QEvent.Type.Hide):
            return False
        if watched is self._form:
            if kind == QtCore.QEvent.Type.Show:
                self._report_chain("form shown", watch=False)
                self._stop()
            return False
        if isinstance(watched, QtWidgets.QWidget):
            verb = "shown" if kind == QtCore.QEvent.Type.Show else "hidden"
            self._on_line(f"{verb}: {_describe(watched, None)}")
        return False

    def _stop(self) -> None:
        self._done = True
        self._form.removeEventFilter(self)
        for watched in self._watched:
            try:
                watched.removeEventFilter(self)
            except RuntimeError:
                # The ancestor was already deleted, taking its filters with it.
                pass
        self._watched = []


class EditUnitPanel:
    """One elevation-editing task panel over ``container``.

    Construction opens the session's one transaction; ``accept`` commits it
    and ``reject`` aborts it, so every edit made in the panel lands or
    reverts together.
    """

    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        watch = Stopwatch("panel")
        self.session = Session(container)
        watch.lap("session")
        self.session.open()
        watch.lap("open transaction")

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Edit Unit")
        layout = QtWidgets.QVBoxLayout(self.form)

        self.view = _EditorView(
            self._on_scene_click, self._on_scene_drag, self._on_scene_release
        )
        layout.addWidget(self.view)
        self._dragging = False
        # A drag re-solves on every pointer move, so one held past a limit
        # would otherwise raise a popup per move.
        self._drag_failure_reported = False

        button_row = QtWidgets.QHBoxLayout()
        self.add_divider_button = QtWidgets.QPushButton("Add Divider")
        self.add_shelf_button = QtWidgets.QPushButton("Add Shelf")
        self.delete_button = QtWidgets.QPushButton("Delete")
        for button in (
            self.add_divider_button,
            self.add_shelf_button,
            self.delete_button,
        ):
            button_row.addWidget(button)
        layout.addLayout(button_row)

        dimension_row = QtWidgets.QHBoxLayout()
        dimension_row.addWidget(QtWidgets.QLabel("Size"))
        self.size_field = _DimensionField(
            self.session.probe,
            self._set_size,
            report_error,
            self._expression_done,
        )
        dimension_row.addWidget(self.size_field.widget)
        self.basis_combo = QtWidgets.QComboBox()
        for text, _basis in _BASIS_CHOICES:
            self.basis_combo.addItem(text)
        dimension_row.addWidget(self.basis_combo)
        layout.addLayout(dimension_row)
        self.readout_label = QtWidgets.QLabel("")
        layout.addWidget(self.readout_label)

        self.untagged_box = QtWidgets.QGroupBox("Objects this workbench did not create")
        untagged_layout = QtWidgets.QVBoxLayout(self.untagged_box)
        explanation = QtWidgets.QLabel(
            "These objects are in the unit but were not generated by the "
            "Shelving workbench, so it leaves them alone unless you select "
            "them here and press Remove. Cancel restores anything removed."
        )
        explanation.setWordWrap(True)
        untagged_layout.addWidget(explanation)
        # One row per object: a checkbox beside a wrapping label, since
        # neither a QCheckBox's own text nor a QListWidget item wraps, and a
        # long reason would otherwise scroll the task panel sideways.
        self.untagged_rows = QtWidgets.QVBoxLayout()
        untagged_layout.addLayout(self.untagged_rows)
        # Keyed by object Name, in the order session.left_alone lists them.
        self.untagged_checks: dict[str, QtWidgets.QCheckBox] = {}
        self.remove_untagged_button = QtWidgets.QPushButton("Remove Selected")
        untagged_layout.addWidget(self.remove_untagged_button)
        layout.addWidget(self.untagged_box)

        self.add_divider_button.clicked.connect(lambda: self._split("horizontal"))
        self.add_shelf_button.clicked.connect(lambda: self._split("vertical"))
        self.delete_button.clicked.connect(self._merge)
        self.basis_combo.currentIndexChanged.connect(self._set_basis)
        self.remove_untagged_button.clicked.connect(self._remove_untagged)
        watch.lap("widgets")

        self._refresh()
        watch.lap("first refresh (scene build)")

    def _on_scene_click(self, point: QtCore.QPointF) -> None:
        scene = self.view.scene()
        node_id = hit_test(scene, point) if scene is not None else None
        self.session.select(node_id)
        # A board with no region before it cannot be dragged, but a press on
        # it still selects it for Delete, so that refusal is not reported.
        self._dragging = (
            node_id is not None
            and self.session.can_merge()
            and self.session.begin_drag(
                node_id, elevation_point_mm(self.session.unit, point)
            )
            is None
        )
        self._drag_failure_reported = False
        self._refresh()

    def _on_scene_drag(self, point: QtCore.QPointF) -> None:
        if not self._dragging:
            return
        failure = self.session.drag_to(elevation_point_mm(self.session.unit, point))
        if failure is not None and not self._drag_failure_reported:
            self._drag_failure_reported = True
            report_error(failure.message)
        self._refresh()

    def _on_scene_release(self) -> None:
        if self._dragging:
            self.session.end_drag()
            self._dragging = False

    def _split(self, direction: SplitDirection) -> None:
        self._show_result(self.session.split(direction))

    def _merge(self) -> None:
        self._show_result(self.session.merge())

    def _set_size(self, size_mm: float) -> None:
        self._show_result(self.session.set_size(size_mm))

    def _expression_done(self) -> None:
        self.session.clear_probe_expression()
        self._refresh()

    def _set_basis(self, index: int) -> None:
        self._show_result(self.session.set_basis(_BASIS_CHOICES[index][1]))

    def _checked_untagged(self) -> list[str]:
        """The names of the untagged objects currently checked in the list."""
        return [name for name, box in self.untagged_checks.items() if box.isChecked()]

    def _rebuild_untagged_rows(self) -> None:
        """Recreate the rows when the listed objects changed, keeping the
        check of every object still listed; otherwise leave them alone, so a
        redraw during a drag does not rebuild widgets."""
        names = [entry.name for entry in self.session.left_alone]
        if names == list(self.untagged_checks):
            return
        checked = set(self._checked_untagged())
        while self.untagged_rows.count():
            item = self.untagged_rows.takeAt(0)
            row_widget = item.widget() if item is not None else None
            if row_widget is not None:
                row_widget.deleteLater()
        self.untagged_checks = {}
        for entry in self.session.left_alone:
            text = f"{entry.label} ({entry.name}): {entry.reason}"
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            box = QtWidgets.QCheckBox()
            box.setChecked(entry.name in checked)
            box.setAccessibleName(text)
            label = QtWidgets.QLabel(text)
            label.setWordWrap(True)
            label.setBuddy(box)
            row_layout.addWidget(box, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            row_layout.addWidget(label, 1)
            self.untagged_rows.addWidget(row)
            self.untagged_checks[entry.name] = box

    def _remove_untagged(self) -> None:
        self._show_result(self.session.remove_untagged(self._checked_untagged()))

    def _show_result(self, failure: EditFailure | None) -> None:
        if failure is not None:
            report_error(failure.message)
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild the scene and every control from the session's current
        state; called after every selection change and every edit attempt,
        successful or not."""
        scene = build_scene(
            self.session.unit, self.session.spaces, self.session.selected_id
        )
        self.view.setScene(scene)
        self.add_divider_button.setEnabled(self.session.can_split())
        self.add_shelf_button.setEnabled(self.session.can_split())
        self.delete_button.setEnabled(self.session.can_merge())

        measurement = self.session.selected_measurement()
        self.size_field.show_mm(None if measurement is None else measurement.size_mm)
        self.basis_combo.blockSignals(True)
        if measurement is None:
            self.basis_combo.setEnabled(False)
            self.readout_label.setText("")
        else:
            bases = [basis for _text, basis in _BASIS_CHOICES]
            self.basis_combo.setCurrentIndex(bases.index(measurement.basis))
            # With no board after the region there is no spacing to measure.
            self.basis_combo.setEnabled(measurement.spacing_mm is not None)
            readout = f"clear {_format_mm(measurement.clear_mm)}"
            if measurement.spacing_mm is not None:
                readout += f", spacing {_format_mm(measurement.spacing_mm)}"
            if not measurement.fixed:
                readout += " (shares the leftover space)"
            self.readout_label.setText(readout)
        self.basis_combo.blockSignals(False)

        self._rebuild_untagged_rows()
        self.untagged_box.setVisible(bool(self.session.left_alone))

    def getStandardButtons(self) -> int:
        buttons = (
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        # PySide6-stubs types enum.Flag.value as the flag's own class rather
        # than int: reveal_type shows StandardButton, though the runtime value
        # is a plain int. FreeCAD's own C++ side only accepts a real int here.
        return cast("int", buttons.value)

    def accept(self) -> bool:
        self.session.commit()
        return True

    def reject(self) -> bool:
        self.session.cancel()
        return True
