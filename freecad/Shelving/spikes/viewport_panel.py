"""Spike: the Edit Unit panel with its elevation moved into the 3D view.

The panel's own controls stay as they are, which makes it the slim panel
the research settled on; its elevation view is hidden, and a group of
spike switches sits on top.
"""

from __future__ import annotations

import time
from typing import override

import FreeCAD
from PySide6 import QtWidgets

from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import EditFailure
from freecad.Shelving.spikes.spike_log import LOG_PATH, log
from freecad.Shelving.spikes.viewport_editor import ViewportEditor


class SpikePanel(EditUnitPanel):
    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        # Read by _refresh, which the base constructor already calls.
        self.editor: ViewportEditor | None = None
        log(f"===== spike opened on {container.Name} ({container.Label})")
        super().__init__(container)
        try:
            self.view.setVisible(False)
            self._add_spike_controls()
            self.editor = ViewportEditor(self)
        except BaseException:
            if self.editor is not None:
                self.editor.close()
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

    # The editor's Host protocol

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
        return super().accept()

    @override
    def reject(self) -> bool:
        log("reject (Cancel or Escape)")
        if self.editor is not None:
            self.editor.close()
        return super().reject()
