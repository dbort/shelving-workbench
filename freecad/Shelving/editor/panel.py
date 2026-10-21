"""The editor's task panel: a thin Qt shell over one ``Session`` and the
in-view editor working on it.

``EditUnitPanel`` satisfies the duck-typed protocol
``FreeCADGui.Control.showDialog`` expects: a ``form`` attribute (the
``QWidget`` shown in the task panel), ``getStandardButtons``, ``accept``,
``reject``. The unit's own size and fixed point, its boards' stock and
the selected opening's basis are edited here; everything else is edited in
the 3D view (:mod:`freecad.Shelving.editor.view_editor`). ``FreeCADGui.Control`` does
not exist under ``freecadcmd``, so :mod:`tests.freecad_gui.test_panel`
exercises this module under the offscreen GUI instead.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from functools import partial

import FreeCAD
from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.compat import override
from freecad.Shelving.core.layout import Basis
from freecad.Shelving.core.stock import Color, StockGroup
from freecad.Shelving.debug_log import Stopwatch
from freecad.Shelving.editor.fields import DimensionField, WheelFilter
from freecad.Shelving.editor.overlay import RGB, marker_rgb
from freecad.Shelving.editor.session import (
    FIELD_PROPERTIES,
    EditFailure,
    Session,
    UnitDimension,
)
from freecad.Shelving.editor.stock_dialog import StockDialog
from freecad.Shelving.editor.view_editor import (
    View3D,
    ViewEditor,
    marker_path,
    select_in_freecad,
)
from freecad.Shelving.refusals import report_error

_UNIT_DIMENSIONS: tuple[tuple[UnitDimension, str], ...] = (
    ("width", "Width"),
    ("depth", "Depth"),
    ("height", "Height"),
)

# Whole sentences per dimension, so each translates on its own.
_FIXED_TIPS: Mapping[UnitDimension, str] = {
    "width": "The side that stays put when the width changes",
    "depth": "The side that stays put when the depth changes",
    "height": "The side that stays put when the height changes",
}

# The stock list's columns; a row's board count stands alone in the last, so
# no text depends on how many boards it counts.
STOCK_COLUMNS = ("Thickness", "Material", "Color", "Boards")
_SWATCH_PX = 16

_BASIS_CHOICES: tuple[tuple[str, Basis], ...] = (
    ("Clear opening", Basis.CLEAR),
    ("Spacing (through the next board)", Basis.WITH_NEXT),
)


class FirstEvents(QtCore.QObject):
    """Calls ``on_event`` with a name the first time each event type in
    ``names`` reaches ``target``, then stops filtering; the event itself
    is passed through untouched.

    Parented to ``target``, so it lives exactly as long as the widget. It
    keeps no reference to ``target``: a Python wrapper outliving its
    widget is what PySide can hand back, dead, for the next widget made
    at the same address.
    """

    def __init__(
        self,
        target: QtCore.QObject,
        names: Mapping[QtCore.QEvent.Type, str],
        on_event: Callable[[str], None],
    ) -> None:
        super().__init__(target)
        self._pending = dict(names)
        self._on_event = on_event
        target.installEventFilter(self)

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        name = self._pending.pop(event.type(), None)
        if name is not None:
            self._on_event(name)
            if not self._pending:
                watched.removeEventFilter(self)
        return False


def _swatch(color: Color) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(_SWATCH_PX, _SWATCH_PX)
    pixmap.fill(QtGui.QColor(*color))
    return QtGui.QIcon(pixmap)


def _thickness_text(thickness_mm: float) -> str:
    """``thickness_mm`` in the user's unit system, as FreeCAD shows a
    length."""
    return FreeCAD.Units.Quantity(thickness_mm, FreeCAD.Units.Length).UserString


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


class MarkedLabel(QtWidgets.QLabel):
    """A one-line label with the fixed point marker before its text, in
    ``rgb``, as tall as the font's capital letters and standing on the
    text's baseline. The marker is painted as a path, so it stays sharp at
    any font size and device pixel ratio."""

    def __init__(self, text: str, rgb: RGB) -> None:
        super().__init__(text)
        self._rgb = rgb
        self.setAlignment(
            QtCore.Qt.AlignmentFlag.AlignLeft | QtCore.Qt.AlignmentFlag.AlignVCenter
        )
        self._fit_margin()

    def marker_rect(self) -> QtCore.QRectF:
        """Where the marker is painted, in the label's own coordinates."""
        side_px = QtGui.QFontMetricsF(self.font()).capHeight()
        # Where QStyle.drawItemText puts the baseline of a line centered in
        # the contents, so the marker stands on the same line as the text.
        metrics = self.fontMetrics()
        contents = self.contentsRect()
        baseline_px = (
            contents.top()
            + (contents.height() - metrics.height()) // 2
            + metrics.ascent()
        )
        return QtCore.QRectF(0.0, baseline_px - side_px, side_px, side_px)

    def _fit_margin(self) -> None:
        metrics = QtGui.QFontMetricsF(self.font())
        # A space's width apart, as a glyph would sit before a word.
        left_px = math.ceil(metrics.capHeight() + metrics.horizontalAdvance(" "))
        self.setContentsMargins(left_px, 0, 0, 0)

    # The parameters keep the names PySide's stubs give them, which an
    # override must match.
    @override
    def changeEvent(self, arg__1: QtCore.QEvent) -> None:
        super().changeEvent(arg__1)
        if arg__1.type() == QtCore.QEvent.Type.FontChange:
            self._fit_margin()

    @override
    def paintEvent(self, arg__1: QtGui.QPaintEvent) -> None:
        super().paintEvent(arg__1)
        rect = self.marker_rect()
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.translate(rect.topLeft())
        painter.fillPath(marker_path(rect.width()), QtGui.QColor.fromRgbF(*self._rgb))
        painter.end()


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

    @override
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
    """One editing task panel over ``container``, editing in ``view``.

    Construction opens the session and the in-view editor, each edit is its
    own undo step, and Close, through ``accept`` or ``reject``, ends both
    with every step left in place. Without a ``view``, as under the
    offscreen GUI tests, which cannot draw one, the panel's own controls
    are the whole editor.
    """

    def __init__(
        self, container: FreeCAD.DocumentObject, view: View3D | None = None
    ) -> None:
        watch = Stopwatch("panel")
        self.session = Session(container)
        watch.lap("session")
        self.session.open(lambda settle: QtCore.QTimer.singleShot(0, settle))
        self.session.on_change = self._follow_document
        watch.lap("open session")
        self.editor: ViewEditor | None = None
        # Without this, a failure building the form or the in-view editor
        # would leave the session following the document with no dialog to
        # end it.
        try:
            self._build(watch)
            if view is not None:
                self.editor = ViewEditor(self.session, view, self._refresh)
                watch.lap("view editor")
        except BaseException:
            self.session.close()
            raise

    def _build(self, watch: Stopwatch) -> None:
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Edit Unit")
        # FreeCADGui.Control.closeDialog(), which another command or the
        # document's closing may call, deletes the form without calling
        # accept or reject.
        self.form.destroyed.connect(lambda: self._end())
        layout = QtWidgets.QVBoxLayout(self.form)
        self._wheel_filter = WheelFilter(self.form)

        self.unit_box = QtWidgets.QGroupBox("Unit")
        unit_layout = QtWidgets.QGridLayout(self.unit_box)
        # A side name such as "Top" alone does not say what it picks, so the
        # choices sit under a column header naming them.
        # The header carries the marker the 3D view draws at the point.
        self.unit_headers: tuple[QtWidgets.QLabel, MarkedLabel] = (
            QtWidgets.QLabel("Size"),
            MarkedLabel("Fixed point", marker_rgb()),
        )
        for column, header in enumerate(self.unit_headers, start=1):
            unit_layout.addWidget(header, 0, column)
        unit_layout.setColumnStretch(1, 1)
        self.unit_fields: dict[UnitDimension, DimensionField] = {}
        # Each lists session.fixed_choices(dimension) in order.
        self.fixed_combos: dict[UnitDimension, QtWidgets.QComboBox] = {}
        for row, (dimension, label) in enumerate(_UNIT_DIMENSIONS, start=1):
            field = DimensionField(
                self.session.container,
                FIELD_PROPERTIES[dimension],
                partial(self._resize, dimension),
                report_error,
                apply_on_step=True,
            )
            self._wheel_filter.watch(field.widget)
            combo = QtWidgets.QComboBox()
            for choice in self.session.fixed_choices(dimension):
                combo.addItem(choice.label)
            combo.setToolTip(_FIXED_TIPS[dimension])
            combo.setAccessibleName(_FIXED_TIPS[dimension])
            self._wheel_filter.watch(combo)
            combo.currentIndexChanged.connect(partial(self._set_fixed_side, dimension))
            row_label = QtWidgets.QLabel(label)
            row_label.setBuddy(field.widget)
            unit_layout.addWidget(row_label, row, 0)
            unit_layout.addWidget(field.widget, row, 1)
            unit_layout.addWidget(combo, row, 2)
            self.unit_fields[dimension] = field
            self.fixed_combos[dimension] = combo
        layout.addWidget(self.unit_box)
        # The step press whose refusal was last reported: holding an arrow
        # past a limit re-solves on every repeat, and one report per press
        # is enough.
        self._reported_step_burst: tuple[UnitDimension, int] | None = None

        self.stock_box = QtWidgets.QGroupBox("Stock")
        stock_layout = QtWidgets.QVBoxLayout(self.stock_box)
        self.stock_list = QtWidgets.QTreeWidget()
        self.stock_list.setColumnCount(len(STOCK_COLUMNS))
        self.stock_list.setHeaderLabels(list(STOCK_COLUMNS))
        self.stock_list.setRootIsDecorated(False)
        self.stock_list.setUniformRowHeights(True)
        self.stock_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.SingleSelection
        )
        stock_layout.addWidget(self.stock_list)
        self.change_stock_button = QtWidgets.QPushButton("Change stock…")
        stock_layout.addWidget(self.change_stock_button)
        layout.addWidget(self.stock_box)
        # The groups the rows show, in row order.
        self.stock_groups: Sequence[StockGroup] = ()
        # The open Change Stock dialog, if any.
        self.stock_dialog: StockDialog | None = None

        basis_row = QtWidgets.QFormLayout()
        self.basis_combo = QtWidgets.QComboBox()
        for text, _basis in _BASIS_CHOICES:
            self.basis_combo.addItem(text)
        self._wheel_filter.watch(self.basis_combo)
        basis_row.addRow("Opening size measures", self.basis_combo)
        layout.addLayout(basis_row)

        self.hide_others_check = QtWidgets.QCheckBox("Hide other objects")
        layout.addWidget(self.hide_others_check)

        self.untagged_box = QtWidgets.QGroupBox("Objects this workbench did not create")
        untagged_layout = QtWidgets.QVBoxLayout(self.untagged_box)
        explanation = QtWidgets.QLabel(
            "These objects are in the unit but were not generated by the "
            "Shelving workbench. It deletes one only when you select it here "
            "and press Delete Selected, and each row says whether the "
            "workbench moves it with the unit's boards. Undo restores "
            "anything deleted."
        )
        explanation.setWordWrap(True)
        untagged_layout.addWidget(explanation)
        # One row per object: a checkbox beside a wrapping label, since
        # neither a QCheckBox's own text nor a QListWidget item wraps, and a
        # long reason would otherwise scroll the task panel sideways.
        self.untagged_rows = QtWidgets.QVBoxLayout()
        untagged_layout.addLayout(self.untagged_rows)
        # Keyed by object Name, in the order session.untagged lists them.
        self.untagged_checks: dict[str, QtWidgets.QCheckBox] = {}
        self.delete_untagged_button = QtWidgets.QPushButton("Delete Selected")
        untagged_layout.addWidget(self.delete_untagged_button)
        layout.addWidget(self.untagged_box)
        layout.addStretch(1)

        self.basis_combo.currentIndexChanged.connect(self._set_basis)
        self.stock_list.itemClicked.connect(self._stock_clicked)
        self.change_stock_button.clicked.connect(self._open_stock_dialog)
        self.delete_untagged_button.clicked.connect(self._delete_untagged)
        self.hide_others_check.toggled.connect(self._hide_others)
        watch.lap("widgets")

        self._refresh()
        watch.lap("first refresh")

    def _resize(self, dimension: UnitDimension, size_mm: float) -> None:
        field = self.unit_fields[dimension]
        failure = self.session.resize(dimension, size_mm)
        if failure is None:
            self._reported_step_burst = None
        elif not field.last_change_was_step:
            report_error(failure.message)
        elif self._reported_step_burst != (dimension, field.step_burst):
            report_error(failure.message)
            self._reported_step_burst = (dimension, field.step_burst)
        self._refresh()

    def _set_fixed_side(self, dimension: UnitDimension, index: int) -> None:
        choices = self.session.fixed_choices(dimension)
        self._show_result(self.session.set_fixed_side(dimension, choices[index].side))

    def _set_basis(self, index: int) -> None:
        self._show_result(self.session.set_basis(_BASIS_CHOICES[index][1]))

    def _stock_clicked(self, item: QtWidgets.QTreeWidgetItem, _column: int) -> None:
        index = self.stock_list.indexOfTopLevelItem(item)
        if 0 <= index < len(self.stock_groups):
            self.select_stock(self.stock_groups[index])

    def select_stock(self, group: StockGroup) -> None:
        """Select exactly ``group``'s boards, in the session and in FreeCAD's
        selection."""
        if self.editor is not None:
            # The editor's change callback is this panel's refresh.
            self.editor.select_boards(group.board_ids)
            return
        self.session.select_boards(group.board_ids)
        select_in_freecad(self.session.container.Document.Name, group.board_ids)
        self._refresh()

    def _open_stock_dialog(self) -> None:
        boards = self.session.selected_boards
        if not boards:
            return
        # The fields start from the first selected board's stock.
        group = next(g for g in self.session.stock_groups() if boards[0] in g.board_ids)
        dialog = StockDialog(self.form, group.thickness_mm, group.color)
        dialog.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.accepted.connect(lambda: self._swap_stock(dialog))

        def closed(_result: int) -> None:
            if self.stock_dialog is dialog:
                self.stock_dialog = None

        dialog.finished.connect(closed)
        self.stock_dialog = dialog
        # Window-modal without a nested event loop, as a task panel's own
        # dialogs open.
        dialog.open()

    def _swap_stock(self, dialog: StockDialog) -> None:
        change = dialog.change()
        self._show_result(
            self.session.swap_stock(
                change.thickness_mm, change.material_uuid, change.color
            )
        )

    def _refresh_stock(self) -> None:
        """Rebuild the rows when the groups changed, and show as selected
        the row whose boards are exactly the selection."""
        groups = self.session.stock_groups()
        if list(groups) != list(self.stock_groups):
            self.stock_groups = groups
            self.stock_list.clear()
            for group in groups:
                item = QtWidgets.QTreeWidgetItem(
                    [
                        _thickness_text(group.thickness_mm),
                        group.material or "",
                        "",
                        str(len(group.board_ids)),
                    ]
                )
                if group.color is not None:
                    item.setIcon(2, _swatch(group.color))
                self.stock_list.addTopLevelItem(item)
        selected = set(self.session.selected_boards)
        self.stock_list.blockSignals(True)
        self.stock_list.clearSelection()
        for index, group in enumerate(groups):
            if selected and set(group.board_ids) == selected:
                item = self.stock_list.topLevelItem(index)
                if item is not None:
                    item.setSelected(True)
        self.stock_list.blockSignals(False)
        self.change_stock_button.setEnabled(bool(selected))

    def _hide_others(self, hide: bool) -> None:
        if self.editor is not None:
            self.editor.set_hide_others(hide)

    def _checked_untagged(self) -> list[str]:
        """The names of the untagged objects currently checked in the list."""
        return [name for name, box in self.untagged_checks.items() if box.isChecked()]

    def _rebuild_untagged_rows(self) -> None:
        """Recreate the rows when the listed objects changed, keeping the
        check of every object still listed; otherwise leave them alone, so a
        redraw during a drag does not rebuild widgets."""
        names = [entry.name for entry in self.session.untagged]
        if names == list(self.untagged_checks):
            return
        checked = set(self._checked_untagged())
        while self.untagged_rows.count():
            item = self.untagged_rows.takeAt(0)
            row_widget = item.widget() if item is not None else None
            if row_widget is not None:
                row_widget.deleteLater()
        self.untagged_checks = {}
        for entry in self.session.untagged:
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

    def _delete_untagged(self) -> None:
        self._show_result(self.session.delete_untagged(self._checked_untagged()))

    def _follow_document(self) -> None:
        """Show the unit an Undo or Redo left, or close the panel when it
        left none, as Sketcher's edit mode ends when its sketch is undone."""
        if not self.session.lost:
            if self.editor is not None:
                self.editor.history_moved()
            self._refresh()
            return
        import FreeCADGui

        self._end()
        FreeCADGui.Control.closeDialog()

    def autoClosedOnDeletedDocument(self) -> None:
        """FreeCAD's call as it closes the dialog with its document, when the
        command asked it to (``setAutoCloseOnDeletedDocument``), as
        Assembly's task panels do."""
        self._end()

    def _show_result(self, failure: EditFailure | None) -> None:
        if failure is not None:
            report_error(failure.message)
        self._refresh()

    def _refresh(self) -> None:
        """Show the session's current state in every control and in the
        view; called after every edit attempt, successful or not."""
        for dimension, field in self.unit_fields.items():
            field.show_mm(self.session.unit_dimension_mm(dimension))
        for dimension, combo in self.fixed_combos.items():
            choices = self.session.fixed_choices(dimension)
            side = self.session.fixed_side(dimension)
            combo.blockSignals(True)
            for index, choice in enumerate(choices):
                combo.setItemText(index, choice.label)
            combo.setCurrentIndex(
                next(i for i, choice in enumerate(choices) if choice.side == side)
            )
            combo.blockSignals(False)
        measurement = self.session.selected_measurement()
        self.basis_combo.blockSignals(True)
        if measurement is None:
            self.basis_combo.setEnabled(False)
        else:
            bases = [basis for _text, basis in _BASIS_CHOICES]
            self.basis_combo.setCurrentIndex(bases.index(measurement.basis))
            # With no board after the region there is no spacing to measure.
            self.basis_combo.setEnabled(measurement.spacing_mm is not None)
        self.basis_combo.blockSignals(False)
        self._refresh_stock()
        self._rebuild_untagged_rows()
        self.untagged_box.setVisible(bool(self.session.untagged))
        if self.editor is not None:
            self.editor.rebuild()

    def _end(self) -> None:
        if self.stock_dialog is not None:
            self.stock_dialog.reject()
        if self.editor is not None:
            self.editor.close()
            # Let go of the editor, and with it its last hold on the view's
            # widgets, without waiting for the garbage collector.
            self.editor = None
        self.session.close()

    def getStandardButtons(self) -> int:
        # Edits stay as undo steps, as Sketcher's do, so there is nothing
        # for a Cancel to put back that Undo cannot.
        buttons = QtWidgets.QDialogButtonBox.StandardButton.Close
        # FreeCAD's C++ side accepts only a real int here, not the flag.
        return buttons.value

    def accept(self) -> bool:
        self._end()
        return True

    def reject(self) -> bool:
        # FreeCAD calls this for Close, and for Escape.
        self._end()
        return True
