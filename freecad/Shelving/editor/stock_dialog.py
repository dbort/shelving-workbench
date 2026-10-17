"""The "Change stock…" dialog: a new thickness, material and color for the
selected boards, each optional.

Each field is FreeCAD's own: the thickness is a ``Gui::QuantitySpinBox``
as the panel's size fields build it, the material is the
``MatGui::MaterialTreeWidget`` the FEM and CAM workbenches pick materials
with, and the color is FreeCAD's ``Gui::ColorButton``. A blank field could
not tell "leave as it is" from a value, so each has a checkbox, unchecked
at the start, and an unchecked field changes nothing. The dialog only
collects the change; :meth:`freecad.Shelving.editor.session.Session.swap_stock`
makes it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, cast

import FreeCADGui
from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.compat import override
from freecad.Shelving.core.stock import Color


class _UiLoader(Protocol):
    def createWidget(self, class_name: str, /) -> QtWidgets.QWidget | None: ...


class _MaterialTree(Protocol):
    """``MatGui.MaterialTreeWidget``'s wrapper, which no stub types."""

    # The selected material's UUID; empty while none is.
    UUID: str


@dataclass(frozen=True)
class StockChange:
    """What the dialog was accepted with; ``None`` leaves that part of the
    stock as it is."""

    thickness_mm: float | None
    material_uuid: str | None
    color: Color | None


def _created(class_name: str) -> QtWidgets.QWidget:
    # freecad-stubs declares UiLoader.createWidget without parameters, and
    # only a running GUI has UiLoader at all.
    loader_type = cast(
        "Callable[[], _UiLoader] | None", getattr(FreeCADGui, "UiLoader", None)
    )
    widget = None if loader_type is None else loader_type().createWidget(class_name)
    if widget is None:
        raise RuntimeError(f"FreeCAD's GUI offers no {class_name}")
    return widget


class StockDialog(QtWidgets.QDialog):
    """Collects a :class:`StockChange`, its fields showing ``thickness_mm``
    and ``color`` until the user changes them. Needs FreeCAD's GUI up."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        thickness_mm: float,
        color: Color | None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Change Stock")
        layout = QtWidgets.QVBoxLayout(self)
        explanation = QtWidgets.QLabel(
            "Check each part of the stock to change on the selected boards."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid)

        self.thickness_check = QtWidgets.QCheckBox("Thickness")
        self.thickness_field = _created("Gui::QuantitySpinBox")
        self.thickness_field.setProperty("unit", "mm")
        self.thickness_field.setProperty("rawValue", thickness_mm)

        self.material_check = QtWidgets.QCheckBox("Material")
        self.material_field = _created("MatGui::MaterialTreeWidget")
        # The wrapper is held for the widget's life; _MaterialTree types the
        # one attribute read from it.
        import MatGui

        self._material = cast(
            "_MaterialTree", MatGui.MaterialTreeWidget(self.material_field)
        )

        self.color_check = QtWidgets.QCheckBox("Color")
        self.color_field = _created("Gui::ColorButton")
        if color is not None:
            self.color_field.setProperty("color", QtGui.QColor(*color))

        rows = (
            (self.thickness_check, self.thickness_field),
            (self.material_check, self.material_field),
            (self.color_check, self.color_field),
        )
        for row, (check, field) in enumerate(rows):
            grid.addWidget(check, row, 0, QtCore.Qt.AlignmentFlag.AlignTop)
            grid.addWidget(field, row, 1)
            field.setEnabled(False)
            check.toggled.connect(field.setEnabled)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok
            | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_material(self, uuid: str) -> None:
        """Select the library material ``uuid`` in the material field."""
        self._material.UUID = uuid

    def change(self) -> StockChange:
        """The parts of the stock whose box is checked. A checked material
        with none picked counts as unchecked."""
        thickness_mm: float | None = None
        if self.thickness_check.isChecked():
            value_mm = self.thickness_field.property("rawValue")
            if isinstance(value_mm, float):
                thickness_mm = value_mm
        material_uuid: str | None = None
        if self.material_check.isChecked() and self._material.UUID:
            material_uuid = self._material.UUID
        color: Color | None = None
        if self.color_check.isChecked():
            picked = cast("QtGui.QColor", self.color_field.property("color"))
            color = (picked.red(), picked.green(), picked.blue())
        return StockChange(thickness_mm, material_uuid, color)

    @override
    def accept(self) -> None:
        # Text the quantity widget cannot resolve would apply whatever a
        # prefix of it resolved to, so OK waits for a readable thickness.
        if self.thickness_check.isChecked() and not self.thickness_field.property(
            "acceptableInput"
        ):
            return
        super().accept()
