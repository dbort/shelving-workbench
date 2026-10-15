"""The editor's size fields: FreeCAD's own quantity widget, and the wheel
rule every panel field follows.

The size field is FreeCAD's ``Gui::QuantitySpinBox``, so it accepts,
resolves, and displays exactly what every other length field in FreeCAD
does. This module reads only the resolved millimeter value it reports and
never looks at the typed text: the field takes an expression language
(units, arithmetic, names of document values), so any pattern check over
the text would refuse valid input, and a false refusal leaves the user no
workaround.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from freecad.Shelving.compat import override

# freecad-stubs declares UiLoader.createWidget without parameters and
# ExpressionBinding with no methods at all, so these Protocols state the
# signatures .claude/docs/freecad-notes.md verified.


class _UiLoader(Protocol):
    def createWidget(self, class_name: str, /) -> QtWidgets.QWidget | None: ...


class _ExpressionBinding(Protocol):
    def bind(self, obj: FreeCAD.DocumentObject, property_name: str, /) -> None: ...


class _ExpressionOwner(Protocol):
    def setExpression(self, path: str, expression: str | None, /) -> None: ...


class WheelFilter(QtCore.QObject):
    """Keeps the mouse wheel from changing a spin box or combo box it only
    passes over, as FreeCAD's own ``WheelEventFilter`` does when its
    ``ComboBoxWheelEventFilter`` preference is on: a wheel event reaches
    such a field only while it has focus, and the wheel never gives it
    focus."""

    def watch(self, widget: QtWidgets.QWidget) -> None:
        widget.setFocusPolicy(QtCore.Qt.FocusPolicy.StrongFocus)
        widget.installEventFilter(self)

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() != QtCore.QEvent.Type.Wheel:
            return False
        if isinstance(watched, QtWidgets.QWidget) and watched.hasFocus():
            return False
        # Left for the scroll area around the panel.
        event.ignore()
        return True


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

    @override
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


class _StepWatch(QtCore.QObject):
    """Notes, before the spin box sees it, every event that steps its value
    rather than editing its text: a spin arrow pressed, an arrow or page key,
    a wheel turn. ``stepping`` stays set until a key that edits text.
    Installed on the spin box and its line edit, but a mouse press counts
    only on the spin box itself: a click in the text places the caret or
    opens a menu whose paste edits text."""

    # Wheel events closer together than this are one turn of the wheel, so
    # a touchpad gesture past a limit reports its refusal once.
    _WHEEL_GAP_S = 0.5

    _STEP_KEYS = (
        QtCore.Qt.Key.Key_Up,
        QtCore.Qt.Key.Key_Down,
        QtCore.Qt.Key.Key_PageUp,
        QtCore.Qt.Key.Key_PageDown,
    )

    def __init__(self, spin: QtWidgets.QWidget) -> None:
        super().__init__(spin)
        self._spin = spin
        self.stepping = False
        # Counts presses and wheel turns, not repeats, so a caller can tell
        # one held arrow or one gesture from the next.
        self.bursts = 0
        self._last_wheel_s: float | None = None

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        kind = event.type()
        if kind == QtCore.QEvent.Type.KeyPress:
            self._last_wheel_s = None
            key_event = cast("QtGui.QKeyEvent", event)
            if key_event.key() in self._STEP_KEYS:
                if not key_event.isAutoRepeat():
                    self.bursts += 1
                self.stepping = True
            else:
                self.stepping = False
        elif kind == QtCore.QEvent.Type.MouseButtonPress:
            self._last_wheel_s = None
            if watched is self._spin:
                self.bursts += 1
            self.stepping = watched is self._spin
        elif kind == QtCore.QEvent.Type.Wheel:
            now_s = time.monotonic()
            if self._last_wheel_s is None or now_s - self._last_wheel_s > (
                self._WHEEL_GAP_S
            ):
                self.bursts += 1
            self._last_wheel_s = now_s
            self.stepping = True
        return False


class DimensionField:
    """A size input: FreeCAD's quantity widget, or, when the GUI cannot
    supply that widget, a plain line edit whose text goes to
    ``FreeCAD.Units.parseQuantity`` verbatim.

    The quantity widget binds to the property ``path`` of ``binding``, a
    real object of the document, so it resolves names of document values
    and offers FreeCAD's f(x) dialog. The binding only lends the field that
    context: an expression the dialog sets is resolved to its number, which
    the field reports, and then taken off the property again inside a
    transaction that is aborted, so it leaves no undo step and no
    expression behind.

    Text the quantity widget cannot resolve is never applied, and how the
    field looks while it holds such text is the widget's own business.
    Whether the text resolves is the widget's verdict, read from its
    ``acceptableInput``; this class never looks at the text itself.

    ``on_size`` receives the resolved millimeters; ``on_error`` receives
    ``parseQuantity``'s own message, from the fallback only. With
    ``apply_on_step``, each spin step reaches ``on_size`` at once, with no
    Return; the fallback field has no steps.
    """

    def __init__(
        self,
        binding: FreeCAD.DocumentObject | None,
        path: str,
        on_size: Callable[[float], None],
        on_error: Callable[[str], None],
        apply_on_step: bool = False,
    ) -> None:
        self._on_size = on_size
        self._on_error = on_error
        self._bound = binding
        self._path = path
        # Whether this field opened the transaction the f(x) dialog writes
        # its expression into.
        self._formula_transaction = False
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
            if binding is not None:
                binding_type = cast(
                    "Callable[[QtWidgets.QWidget], _ExpressionBinding]",
                    FreeCADGui.ExpressionBinding,
                )
                # Held for the widget's lifetime: the binding is what lets
                # the field resolve a VarSet name.
                self._binding = binding_type(spin)
                self._binding.bind(binding, path)
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
        # Whether the last on_size came from a spin step, and which press of
        # the arrows or wheel it belonged to.
        self.last_change_was_step = False
        self.step_burst = 0
        self._step_watch: _StepWatch | None = None
        if spin is not None and apply_on_step:
            self._step_watch = _StepWatch(spin)
            spin.installEventFilter(self._step_watch)
            self.line_edit.installEventFilter(self._step_watch)
            QtCore.QObject.connect(
                spin, QtCore.SIGNAL("valueChanged(double)"), self._value_changed
            )
        if spin is not None:
            # Accepting the f(x) dialog changes the value without any
            # editingFinished; the dialog closing is the only signal.
            QtCore.QObject.connect(
                spin,
                QtCore.SIGNAL("showFormulaDialog(bool)"),
                self._formula_dialog_toggled,
            )

    def _value_changed(self, _value: float) -> None:
        """Apply a spin step at once. A change from typing waits for Return
        or focus-out, so a half-typed 800 never applies as 8 or 80."""
        watch = self._step_watch
        if watch is None or not watch.stepping or not self._alive():
            return
        if self.quantity_widget is None or not self._acceptable():
            return
        value_mm = self.quantity_widget.property("rawValue")
        if isinstance(value_mm, float) and value_mm != self._shown_mm:
            self.last_change_was_step = True
            self.step_burst = watch.bursts
            self._on_size(value_mm)

    def _formula_dialog_toggled(self, shown: bool) -> None:
        if shown:
            # The dialog writes its expression straight into the bound
            # property, under a step of its own unless a transaction is
            # open; this one is aborted once the number is read.
            if FreeCAD.getActiveTransaction() is None:
                FreeCAD.setActiveTransaction("Shelving f(x)")
                self._formula_transaction = True
            return
        if not self._alive():
            return
        value_mm = (
            self.quantity_widget.property("rawValue")
            if self.quantity_widget is not None and self._acceptable()
            else None
        )
        owner = cast("_ExpressionOwner | None", self._bound)
        if owner is not None:
            # Clearing the expression is what makes the widget editable
            # again; the abort that follows leaves the property as it was.
            owner.setExpression(self._path, None)
        if self._formula_transaction:
            self._formula_transaction = False
            FreeCAD.closeActiveTransaction(True)
        if isinstance(value_mm, float) and value_mm != self._shown_mm:
            self.last_change_was_step = False
            self._on_size(value_mm)

    def _acceptable(self) -> bool:
        """The quantity widget's verdict on its current text; always
        ``True`` for the fallback field, which learns only by parsing."""
        if self.quantity_widget is None:
            return True
        return bool(self.quantity_widget.property("acceptableInput"))

    def _alive(self) -> bool:
        """Whether the field's widget still exists. Qt sends focus-out and
        ``editingFinished`` while it destroys the widget, when the panel
        closes or the application exits, after the widget is already
        unusable from Python."""
        return Shiboken.isValid(self.widget) and Shiboken.isValid(self.line_edit)

    def _discard_unreadable(self) -> None:
        """Put the last shown value back before the widget handles a
        focus-out. Left alone, the widget settles on whatever a prefix of the
        unreadable text resolved to and reports that as a finished edit."""
        if self._alive() and not self._acceptable():
            self.show_mm(self._shown_mm)

    def _finished(self) -> None:
        if not self._alive():
            return
        if self.quantity_widget is not None:
            # While the text is unacceptable, rawValue still holds the last
            # value some prefix of it resolved to (12 mm for 12 1/2").
            if not self._acceptable():
                return
            value_mm = self.quantity_widget.property("rawValue")
            if isinstance(value_mm, float) and value_mm != self._shown_mm:
                self.last_change_was_step = False
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
        self.last_change_was_step = False
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
