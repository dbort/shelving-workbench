"""The elevation editor's task panel: a thin Qt shell over one ``Session``.

``EditUnitPanel`` satisfies the duck-typed protocol
``FreeCADGui.Control.showDialog`` expects: a ``form`` attribute (the
``QWidget`` shown in the task panel), ``getStandardButtons``, ``accept``,
``reject``. Every control calls a ``Session`` method and redraws from what it
returns; the decisions left here are input handling (the start-drag
threshold, reporting only a changed size, keeping checked items across a
redraw). ``FreeCADGui.Control`` does not exist under ``freecadcmd``, so
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


_BASIS_CHOICES: tuple[tuple[str, Basis], ...] = (
    ("Clear opening", Basis.CLEAR),
    ("Spacing (through the next board)", Basis.WITH_NEXT),
)


def _format_mm(value_mm: float) -> str:
    return f"{value_mm:.2f} mm"


class _DimensionField:
    """The size input: FreeCAD's quantity widget bound to the session's
    probe object, or, when the GUI cannot supply that widget, a plain line
    edit whose text goes to ``FreeCAD.Units.parseQuantity`` verbatim.

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
        # What show_mm last displayed. editingFinished also fires when the
        # field merely loses focus, and reporting an unchanged value would
        # quietly fix a region that shares leftover space.
        self._shown_mm: float | None = None
        self._shown_text = ""
        # The spin box blocks Return on text it cannot resolve, so this fires
        # only for input it accepted.
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

    def _finished(self) -> None:
        if self.quantity_widget is not None:
            value_mm = self.quantity_widget.property("rawValue")
            if isinstance(value_mm, float) and value_mm != self._shown_mm:
                self._on_size(value_mm)
            return
        text = self.line_edit.text()
        if text == self._shown_text:
            return
        try:
            quantity = FreeCAD.Units.parseQuantity(text)
        except Exception as err:  # noqa: BLE001 - its message is the report
            self._on_error(str(err))
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
            self._show_message,
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

        self.message_label = QtWidgets.QLabel("")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        self.untagged_box = QtWidgets.QGroupBox("Objects this workbench did not create")
        untagged_layout = QtWidgets.QVBoxLayout(self.untagged_box)
        explanation = QtWidgets.QLabel(
            "These objects are in the unit but were not generated by the "
            "Shelving workbench, so it leaves them alone unless you select "
            "them here and press Remove. Cancel restores anything removed."
        )
        explanation.setWordWrap(True)
        untagged_layout.addWidget(explanation)
        self.untagged_list = QtWidgets.QListWidget()
        untagged_layout.addWidget(self.untagged_list)
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
        self._refresh()

    def _on_scene_drag(self, point: QtCore.QPointF) -> None:
        if self._dragging:
            self._show_result(
                self.session.drag_to(elevation_point_mm(self.session.unit, point))
            )

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
        return [
            str(item.data(QtCore.Qt.ItemDataRole.UserRole))
            for item in (
                self.untagged_list.item(row)
                for row in range(self.untagged_list.count())
            )
            if item is not None and item.checkState() == QtCore.Qt.CheckState.Checked
        ]

    def _remove_untagged(self) -> None:
        self._show_result(self.session.remove_untagged(self._checked_untagged()))

    def _show_message(self, message: str) -> None:
        self.message_label.setText(message)

    def _show_result(self, failure: EditFailure | None) -> None:
        self.message_label.setText("" if failure is None else failure.message)
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

        checked = set(self._checked_untagged())
        self.untagged_list.clear()
        for entry in self.session.left_alone:
            item = QtWidgets.QListWidgetItem(
                f"{entry.label} ({entry.name}): {entry.reason}"
            )
            item.setData(QtCore.Qt.ItemDataRole.UserRole, entry.name)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked
                if entry.name in checked
                else QtCore.Qt.CheckState.Unchecked
            )
            self.untagged_list.addItem(item)
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
