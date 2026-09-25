"""The elevation editor's task panel: a thin Qt shell over one ``Session``.

``EditUnitPanel`` satisfies the duck-typed protocol
``FreeCADGui.Control.showDialog`` expects: a ``form`` attribute (the
``QWidget`` shown in the task panel), ``getStandardButtons``, ``accept``,
``reject``. Every button calls a ``Session`` method and redraws from what it
returns, so no decision worth a unit test lives here. That matters because
``FreeCADGui.Control`` does not exist under ``freecadcmd``: the headless
coverage in :mod:`tools.freecad_editor_smoke` drives ``Session`` directly
and never reaches this module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import FreeCAD
from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.editor.scene import build_scene, hit_test
from freecad.Shelving.editor.session import EditFailure, Session, SplitDirection


class _EditorView(QtWidgets.QGraphicsView):
    """A ``QGraphicsView`` that reports the scene position of every click to
    ``on_click``, which is all the selection wiring the panel needs."""

    def __init__(self, on_click: Callable[[QtCore.QPointF], None]) -> None:
        super().__init__()
        self._on_click = on_click

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mousePressEvent(event)
        scene = self.scene()
        if scene is not None:
            self._on_click(self.mapToScene(event.position().toPoint()))


class EditUnitPanel:
    """One elevation-editing task panel over ``container``.

    Construction opens the session's one transaction; ``accept`` commits it
    and ``reject`` aborts it, so every edit made in the panel lands or
    reverts together.
    """

    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        self.session = Session(container)
        self.session.open()

        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Edit Unit")
        layout = QtWidgets.QVBoxLayout(self.form)

        self.view = _EditorView(self._on_scene_click)
        layout.addWidget(self.view)

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

        self.message_label = QtWidgets.QLabel("")
        layout.addWidget(self.message_label)

        self.add_divider_button.clicked.connect(lambda: self._split("horizontal"))
        self.add_shelf_button.clicked.connect(lambda: self._split("vertical"))
        self.delete_button.clicked.connect(self._merge)

        self._refresh()

    def _on_scene_click(self, point: QtCore.QPointF) -> None:
        scene = self.view.scene()
        node_id = hit_test(scene, point) if scene is not None else None
        self.session.select(node_id)
        self._refresh()

    def _split(self, direction: SplitDirection) -> None:
        self._show_result(self.session.split(direction))

    def _merge(self) -> None:
        self._show_result(self.session.merge())

    def _show_result(self, failure: EditFailure | None) -> None:
        self.message_label.setText("" if failure is None else failure.message)
        self._refresh()

    def _refresh(self) -> None:
        """Rebuild the scene from the session's current state and re-derive
        the two buttons' enabled state; called after every selection change
        and every edit attempt, successful or not."""
        scene = build_scene(
            self.session.unit, self.session.spaces, self.session.selected_id
        )
        self.view.setScene(scene)
        self.add_divider_button.setEnabled(self.session.can_split())
        self.add_shelf_button.setEnabled(self.session.can_split())
        self.delete_button.setEnabled(self.session.can_merge())

    def getStandardButtons(self) -> int:
        buttons = (
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        # PySide6-stubs types enum.Flag.value as the flag's own class rather
        # than int (verified: reveal_type shows StandardButton, not int, even
        # though the runtime value is a plain int); FreeCAD's own C++ side
        # only accepts a real int here.
        return cast("int", buttons.value)

    def accept(self) -> bool:
        self.session.commit()
        return True

    def reject(self) -> bool:
        self.session.cancel()
        return True
