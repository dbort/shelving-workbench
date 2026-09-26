"""Build and hit-test a ``QGraphicsScene`` elevation for one ``Unit``.

The projection matches :mod:`freecad.Shelving.core.svg`: horizontal and
vertical are :func:`freecad.Shelving.core.scan.elevation_axes` of
``unit.depth_axis``, with vertical flipped so the drawing reads bottom-up
the way a real elevation does.

This module imports Qt and the layout-only parts of
:mod:`freecad.Shelving.core`, never FreeCAD: nothing here touches a document
or a transaction.
"""

from __future__ import annotations

from collections.abc import Mapping

from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.core.geometry import AxisIndex, Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Bay,
    Board,
    Division,
    Insets,
    Region,
    Unit,
    Void,
)
from freecad.Shelving.core.scan import elevation_axes

# The QGraphicsItem.setData key each item carries its node id under; Qt
# keys custom data by int, and any value works.
_ID_DATA_ROLE = 0

_BAY_BRUSH = QtGui.QBrush(QtGui.QColor(0xF2, 0xF2, 0xF2, 160))
_VOID_BRUSH = QtGui.QBrush(
    QtGui.QColor(0xDD, 0xDD, 0xDD, 120), QtCore.Qt.BrushStyle.BDiagPattern
)
_BOARD_BRUSH = QtGui.QBrush(QtGui.QColor(0xC6, 0x5F, 0x3D))
_DIVISION_BRUSH = QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush)

_NORMAL_PEN = QtGui.QPen(QtGui.QColor(0x33, 0x33, 0x33))
_SELECTED_PEN = QtGui.QPen(QtGui.QColor(0x2A, 0x7F, 0xFF))
_SELECTED_PEN.setWidthF(3.0)


def _axis_index(axis: Axis) -> AxisIndex:
    match axis:
        case Axis.X:
            return 0
        case Axis.Y:
            return 1
        case Axis.Z:
            return 2


def _component_mm(v: Vec3, axis_index: AxisIndex) -> float:
    return (v.x_mm, v.y_mm, v.z_mm)[axis_index]


def _apply_insets(axis: Axis, space: Space, insets: Insets) -> Space:
    """``space`` with ``insets`` applied to its two cross-section axes.

    Mirrors :func:`freecad.Shelving.core.expand._apply_insets` and
    :func:`freecad.Shelving.core.svg._apply_insets`; kept as its own copy
    here rather than imported, the way each module in this package keeps its
    own small geometry helpers instead of reaching into another module's
    private names.
    """
    origin = space.origin
    size = space.size
    match axis:
        case Axis.X:
            origin = Vec3(
                origin.x_mm,
                origin.y_mm + insets.y_min_mm,
                origin.z_mm + insets.z_min_mm,
            )
            size = Vec3(
                size.x_mm,
                size.y_mm - insets.y_min_mm - insets.y_max_mm,
                size.z_mm - insets.z_min_mm - insets.z_max_mm,
            )
        case Axis.Y:
            origin = Vec3(
                origin.x_mm + insets.x_min_mm,
                origin.y_mm,
                origin.z_mm + insets.z_min_mm,
            )
            size = Vec3(
                size.x_mm - insets.x_min_mm - insets.x_max_mm,
                size.y_mm,
                size.z_mm - insets.z_min_mm - insets.z_max_mm,
            )
        case Axis.Z:
            origin = Vec3(
                origin.x_mm + insets.x_min_mm,
                origin.y_mm + insets.y_min_mm,
                origin.z_mm,
            )
            size = Vec3(
                size.x_mm - insets.x_min_mm - insets.x_max_mm,
                size.y_mm - insets.y_min_mm - insets.y_max_mm,
                size.z_mm,
            )
    return Space(origin=origin, size=size)


def _rect_for(
    space: Space, horizontal: Axis, vertical: Axis, unit_vertical_mm: float
) -> QtCore.QRectF:
    """``space`` projected onto ``horizontal``/``vertical``, vertical flipped
    so the scene's Y axis (down in Qt) reads as up in the elevation."""
    h_index = _axis_index(horizontal)
    v_index = _axis_index(vertical)
    width_mm = space.extent_mm(h_index)
    height_mm = space.extent_mm(v_index)
    x_mm = _component_mm(space.origin, h_index)
    y_mm = unit_vertical_mm - _component_mm(space.origin, v_index) - height_mm
    return QtCore.QRectF(x_mm, y_mm, width_mm, height_mm)


def _space(spaces: Mapping[str, Space], node_id: str) -> Space:
    try:
        return spaces[node_id]
    except KeyError:
        raise KeyError(f"no solved space for node {node_id!r}") from None


def build_scene(
    unit: Unit, spaces: Mapping[str, Space], selected_id: str | None = None
) -> QtWidgets.QGraphicsScene:
    """A ``QGraphicsScene`` with one rect item per region and per board in
    ``unit``, positioned from ``spaces`` (see
    :func:`freecad.Shelving.core.solver.solve`). Every item carries its node
    id for :func:`hit_test`.

    Raises ``ValueError`` naming ``unit.id`` when ``unit.depth_axis`` is
    ``None``: a unit with no depth axis has no elevation plane to project
    onto. Raises ``KeyError`` when ``spaces`` lacks a node in ``unit``.
    ``selected_id``, when given, is the one item drawn with the
    selected pen; every other item gets the normal pen.
    """
    if unit.depth_axis is None:
        raise ValueError(f"unit {unit.id!r} has no depth_axis to draw an elevation on")
    horizontal, vertical = elevation_axes(unit.depth_axis)
    unit_vertical_mm = _component_mm(unit.size_mm, _axis_index(vertical))
    unit_horizontal_mm = _component_mm(unit.size_mm, _axis_index(horizontal))

    scene = QtWidgets.QGraphicsScene()
    scene.setSceneRect(0.0, 0.0, unit_horizontal_mm, unit_vertical_mm)

    def add_rect(node_id: str, space: Space, brush: QtGui.QBrush, depth: int) -> None:
        rect = _rect_for(space, horizontal, vertical, unit_vertical_mm)
        pen = _SELECTED_PEN if node_id == selected_id else _NORMAL_PEN
        item = scene.addRect(rect, pen, brush)
        # Z-value is nesting depth, so a click lands on the deepest item
        # rather than an ancestor Division whose rect covers the same point.
        item.setZValue(float(depth))
        item.setData(_ID_DATA_ROLE, node_id)

    def walk(region: Region, depth: int) -> None:
        match region:
            case Bay():
                add_rect(region.id, _space(spaces, region.id), _BAY_BRUSH, depth)
            case Void():
                add_rect(region.id, _space(spaces, region.id), _VOID_BRUSH, depth)
            case Division():
                add_rect(region.id, _space(spaces, region.id), _DIVISION_BRUSH, depth)
                for item in region.items:
                    if isinstance(item, Board):
                        board_space = _apply_insets(
                            region.axis, _space(spaces, item.id), item.insets
                        )
                        add_rect(item.id, board_space, _BOARD_BRUSH, depth + 1)
                    else:
                        walk(item, depth + 1)

    walk(unit.root, depth=0)
    return scene


def hit_test(scene: QtWidgets.QGraphicsScene, point: QtCore.QPointF) -> str | None:
    """The id of the topmost item at ``point`` (scene coordinates), or
    ``None`` when nothing is there.

    ``QGraphicsScene.items`` already orders by stacking order, topmost
    first, so the id belongs to whichever item's Z-value (nesting depth) is
    greatest among those covering ``point``.
    """
    for item in scene.items(point):
        node_id = item.data(_ID_DATA_ROLE)
        if isinstance(node_id, str):
            return node_id
    return None
