"""Spike: the Edit Unit panel with its elevation moved into the 3D view.

The panel's own controls stay as they are, which makes it the slim panel
the research settled on; its elevation view is hidden, and a group of
spike switches sits on top.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable

import FreeCAD
from PySide6 import QtWidgets

from freecad.Shelving.compat import override
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import EditFailure, SplitDirection, UnitDimension
from freecad.Shelving.spikes.edit_history import EditHistory
from freecad.Shelving.spikes.spike_log import LOG_PATH, log
from freecad.Shelving.spikes.viewport_editor import ViewportEditor


class SpikePanel(EditUnitPanel):
    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        # Read by _refresh, which the base constructor already calls.
        self.editor: ViewportEditor | None = None
        self.history: EditHistory | None = None
        log(f"===== spike opened on {container.Name} ({container.Label})")
        super().__init__(container)
        try:
            self.history = EditHistory(self.session, self._history_moved)
            self.view.setVisible(False)
            # The view's own buttons and the delete key replace these.
            for button in (
                self.add_divider_button,
                self.add_shelf_button,
                self.delete_button,
            ):
                button.setVisible(False)
            self._add_spike_controls()
            self.editor = ViewportEditor(self)
        except BaseException:
            if self.editor is not None:
                self.editor.close()
            if self.history is not None:
                self.history.finish(keep=False)
            else:
                self.session.cancel()
            raise

    def _add_spike_controls(self) -> None:
        box = QtWidgets.QGroupBox("Viewport spike")
        layout = QtWidgets.QFormLayout(box)
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("Ours (FreeCAD selection off)", "ours")
        self.mode_combo.addItem("FreeCAD's, boards only", "native")
        layout.addRow("Click picking", self.mode_combo)
        self.on_top_check = QtWidgets.QCheckBox("Draw overlay over the solids")
        layout.addRow(self.on_top_check)
        self.hide_check = QtWidgets.QCheckBox("Hide other objects")
        layout.addRow(self.hide_check)
        self.front_button = QtWidgets.QPushButton("Back to front view")
        layout.addRow(self.front_button)
        note_row = QtWidgets.QHBoxLayout()
        self.note_edit = QtWidgets.QLineEdit()
        self.note_edit.setPlaceholderText("What you just tried or saw")
        self.note_button = QtWidgets.QPushButton("Log note")
        note_row.addWidget(self.note_edit, 1)
        note_row.addWidget(self.note_button)
        layout.addRow(note_row)
        path_label = QtWidgets.QLabel(f"Log: {LOG_PATH}")
        path_label.setWordWrap(True)
        path_label.setTextInteractionFlags(
            path_label.textInteractionFlags()
            | path_label.textInteractionFlags().TextSelectableByMouse
        )
        layout.addRow(path_label)
        form_layout = self.form.layout()
        if isinstance(form_layout, QtWidgets.QBoxLayout):
            form_layout.insertWidget(0, box)

        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.on_top_check.toggled.connect(self._on_top_toggled)
        self.hide_check.toggled.connect(self._hide_toggled)
        self.front_button.clicked.connect(self._front)
        self.note_button.clicked.connect(self._note)
        self.note_edit.returnPressed.connect(self._note)

    def _mode_changed(self, _index: int) -> None:
        if self.editor is not None:
            mode = "native" if self.mode_combo.currentData() == "native" else "ours"
            self.editor.set_selection_mode(mode)

    def _on_top_toggled(self, on: bool) -> None:
        if self.editor is not None:
            self.editor.set_on_top(on)

    def _hide_toggled(self, hide: bool) -> None:
        if self.editor is not None:
            self.editor.set_hide_others(hide)

    def _front(self) -> None:
        if self.editor is not None:
            self.editor.frame_camera()

    def _note(self) -> None:
        text = self.note_edit.text().strip()
        if text:
            log(f"NOTE: {text}")
            self.note_edit.clear()

    # Every edit is one history step; the panel's own controls call these.

    @override
    def _split(self, direction: SplitDirection) -> None:
        name = "Add shelf" if direction == "vertical" else "Add divider"
        self.run_edit(name, lambda: self.session.split(direction))

    @override
    def _merge(self) -> None:
        self.run_edit("Delete board", self.session.merge)

    @override
    def _resize(self, dimension: UnitDimension, size_mm: float) -> None:
        with self._step(f"Change unit {dimension}"):
            super()._resize(dimension, size_mm)

    @override
    def _set_size(self, size_mm: float) -> None:
        self.run_edit("Change size", lambda: self.session.set_size(size_mm))

    @override
    def _set_basis(self, index: int) -> None:
        with self._step("Change what the size measures"):
            super()._set_basis(index)

    @override
    def _delete_untagged(self) -> None:
        with self._step("Delete parts"):
            super()._delete_untagged()

    def _step(self, name: str) -> contextlib.AbstractContextManager[None]:
        if self.history is None:
            return contextlib.nullcontext()
        return self.history.step(name)

    def _history_moved(self, failure: EditFailure | None) -> None:
        if self.editor is not None:
            self.editor.history_moved()
        self.show_result(failure)

    # The editor's Host protocol

    def run_edit(self, name: str, edit: Callable[[], EditFailure | None]) -> None:
        with self._step(name):
            failure = edit()
        self.show_result(failure)

    def select_node(self, node_id: str | None) -> None:
        self.session.select(node_id)
        self._refresh()

    def show_result(self, failure: EditFailure | None) -> None:
        if failure is not None:
            log(f"edit refused: {failure.message}")
        self._show_result(failure)

    @override
    def _refresh(self) -> None:
        start_s = time.perf_counter()
        super()._refresh()
        if self.editor is not None:
            panel_ms = (time.perf_counter() - start_s) * 1000
            self.editor.rebuild()
            if not self.editor.dragging:
                log(
                    f"panel refresh {panel_ms:.1f} ms, "
                    f"selected {self.session.selected_id}"
                )

    @override
    def accept(self) -> bool:
        log("accept (OK)")
        if self.editor is not None:
            self.editor.close()
        if self.history is None:
            return super().accept()
        self.history.finish(keep=True)
        return True

    @override
    def reject(self) -> bool:
        log("reject (Cancel or Escape)")
        if self.editor is not None:
            self.editor.close()
        if self.history is None:
            return super().reject()
        self.history.finish(keep=False)
        return True
