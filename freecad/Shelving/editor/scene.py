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

from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    Insets,
    Region,
    Unit,
    Void,
)
from freecad.Shelving.core.scan import elevation_axes

# The QGraphicsItem.setData key each item carries its node id under; Qt
# keys custom data by int, and any value works.
_ID_DATA_ROLE = 0
# The key a dimension's items carry their part under: "line", "witness",
# "arrow", "label" or "readout". Rect items carry nothing here.
_DIMENSION_DATA_ROLE = 1

_BAY_BRUSH = QtGui.QBrush(QtGui.QColor(0xF2, 0xF2, 0xF2, 160))
_VOID_BRUSH = QtGui.QBrush(
    QtGui.QColor(0xDD, 0xDD, 0xDD, 120), QtCore.Qt.BrushStyle.BDiagPattern
)
_BOARD_BRUSH = QtGui.QBrush(QtGui.QColor(0xC6, 0x5F, 0x3D))
_DIVISION_BRUSH = QtGui.QBrush(QtCore.Qt.BrushStyle.NoBrush)

_NORMAL_PEN = QtGui.QPen(QtGui.QColor(0x33, 0x33, 0x33))
_SELECTED_PEN = QtGui.QPen(QtGui.QColor(0x2A, 0x7F, 0xFF))
_SELECTED_PEN.setWidthF(3.0)

_DIMENSION_PEN = QtGui.QPen(QtGui.QColor(0x1F, 0x4E, 0x79))
_DIMENSION_PEN.setWidthF(1.5)
_SELECTED_DIMENSION_PEN = QtGui.QPen(QtGui.QColor(0x2A, 0x7F, 0xFF))
_SELECTED_DIMENSION_PEN.setWidthF(3.0)
_READOUT_BRUSH = QtGui.QBrush(QtGui.QColor(0x66, 0x66, 0x66))
# Above every rect, whatever its nesting depth, so a dimension stays visible
# and clickable over the regions it annotates.
_DIMENSION_Z = 1000.0
# How far each witness line runs either side of its dimension line.
_WITNESS_HALF_MM = 12.0
# Arrowhead length and half-width. A short dimension gets shorter heads, at
# most a third of its span each, so the two never meet.
_ARROW_LENGTH_MM = 10.0
_ARROW_HALF_WIDTH_MM = 3.5
# The labels' height. QFont.setPixelSize sizes a scene item's text in item
# coordinates, so this is scene millimetres whatever the view's zoom.
_LABEL_PIXEL_SIZE = 16


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
    h_index = horizontal.component_index
    v_index = vertical.component_index
    width_mm = space.extent_mm(h_index)
    height_mm = space.extent_mm(v_index)
    x_mm = space.origin.component_mm(h_index)
    y_mm = unit_vertical_mm - space.origin.component_mm(v_index) - height_mm
    return QtCore.QRectF(x_mm, y_mm, width_mm, height_mm)


def _space(spaces: Mapping[str, Space], node_id: str) -> Space:
    try:
        return spaces[node_id]
    except KeyError:
        raise KeyError(f"no solved space for node {node_id!r}") from None


def _format_mm(value_mm: float) -> str:
    return f"{value_mm:.2f}".rstrip("0").rstrip(".")


def _add_dimension(
    scene: QtWidgets.QGraphicsScene,
    region_id: str,
    run_is_horizontal: bool,
    low_mm: float,
    high_mm: float,
    cross_mm: float,
    unit_vertical_mm: float,
    text: str,
    readout: str | None,
    selected: bool,
) -> None:
    """Draw one dimension from ``low_mm`` to ``high_mm`` along the run's
    axis, with its dimension line at ``cross_mm`` on the other elevation axis
    (both unit-frame millimetres), and a witness line lying on each face it
    measures, each end of the dimension line an arrowhead whose tip touches
    that witness line."""

    def to_scene(along_mm: float, across_mm: float) -> QtCore.QPointF:
        if run_is_horizontal:
            return QtCore.QPointF(along_mm, unit_vertical_mm - across_mm)
        return QtCore.QPointF(across_mm, unit_vertical_mm - along_mm)

    pen = _SELECTED_DIMENSION_PEN if selected else _DIMENSION_PEN

    def tag(item: QtWidgets.QGraphicsItem, part: str) -> None:
        item.setZValue(_DIMENSION_Z)
        item.setData(_ID_DATA_ROLE, region_id)
        item.setData(_DIMENSION_DATA_ROLE, part)

    line = scene.addLine(
        QtCore.QLineF(to_scene(low_mm, cross_mm), to_scene(high_mm, cross_mm)), pen
    )
    tag(line, "line")
    arrow_mm = min(_ARROW_LENGTH_MM, abs(high_mm - low_mm) / 3)
    for tip_mm, base_mm in ((low_mm, low_mm + arrow_mm), (high_mm, high_mm - arrow_mm)):
        head = QtGui.QPolygonF(
            [
                to_scene(tip_mm, cross_mm),
                to_scene(base_mm, cross_mm - _ARROW_HALF_WIDTH_MM),
                to_scene(base_mm, cross_mm + _ARROW_HALF_WIDTH_MM),
            ]
        )
        arrow = scene.addPolygon(head, pen, QtGui.QBrush(pen.color()))
        tag(arrow, "arrow")
    for face_mm in (low_mm, high_mm):
        witness = scene.addLine(
            QtCore.QLineF(
                to_scene(face_mm, cross_mm - _WITNESS_HALF_MM),
                to_scene(face_mm, cross_mm + _WITNESS_HALF_MM),
            ),
            pen,
        )
        tag(witness, "witness")

    font = QtGui.QFont()
    font.setPixelSize(_LABEL_PIXEL_SIZE)
    anchor = to_scene((low_mm + high_mm) / 2, cross_mm)
    label = scene.addSimpleText(text, font)
    label.setBrush(QtGui.QBrush(pen.color()))
    label.setPos(anchor.x() + 2.0, anchor.y() - _LABEL_PIXEL_SIZE - 2.0)
    tag(label, "label")
    if readout is not None:
        readout_item = scene.addSimpleText(readout, font)
        readout_item.setBrush(_READOUT_BRUSH)
        readout_item.setPos(anchor.x() + 2.0, anchor.y() + 2.0)
        tag(readout_item, "readout")


def _add_region_dimensions(
    scene: QtWidgets.QGraphicsScene,
    division: Division,
    spaces: Mapping[str, Space],
    horizontal: Axis,
    vertical: Axis,
    unit_vertical_mm: float,
    selected_id: str | None,
) -> None:
    """One dimension per region directly in ``division``'s run, measured the
    way its rule measures it: a clear opening spans the region itself, a
    ``Basis.WITH_NEXT`` spacing spans on through the board after it. The
    other measurement, when the region has a board after it, is the
    readout. Draws nothing for a run along the depth axis, which the
    elevation cannot show."""
    if division.axis not in (horizontal, vertical):
        return
    run_is_horizontal = division.axis == horizontal
    along_index = division.axis.component_index
    across_index = (vertical if run_is_horizontal else horizontal).component_index
    for index, item in enumerate(division.items):
        if isinstance(item, Board):
            continue
        space = _space(spaces, item.id)
        low_mm = space.origin_mm(along_index)
        clear_high_mm = low_mm + space.extent_mm(along_index)
        spacing_high_mm: float | None = None
        if index + 1 < len(division.items):
            after = division.items[index + 1]
            if isinstance(after, Board):
                after_space = _space(spaces, after.id)
                spacing_high_mm = after_space.origin_mm(
                    along_index
                ) + after_space.extent_mm(along_index)
        clear_text = _format_mm(clear_high_mm - low_mm)
        # A nested Division's dimension sits off its centre line, where its
        # own children's dimensions cross it.
        fraction = 0.25 if isinstance(item, Division) else 0.5
        cross_mm = space.origin_mm(across_index) + fraction * space.extent_mm(
            across_index
        )
        spacing = isinstance(item.rule, Fixed) and item.rule.basis is Basis.WITH_NEXT
        readout: str | None
        if spacing and spacing_high_mm is not None:
            high_mm = spacing_high_mm
            text = _format_mm(spacing_high_mm - low_mm)
            readout = f"clear {clear_text}"
        else:
            high_mm = clear_high_mm
            text = clear_text
            readout = (
                None
                if spacing_high_mm is None
                else f"spacing {_format_mm(spacing_high_mm - low_mm)}"
            )
        _add_dimension(
            scene,
            item.id,
            run_is_horizontal,
            low_mm,
            high_mm,
            cross_mm,
            unit_vertical_mm,
            text,
            readout,
            item.id == selected_id,
        )


def elevation_point_mm(unit: Unit, point: QtCore.QPointF) -> Vec3:
    """The unit-frame point under scene position ``point``, with the depth
    axis component 0. The inverse of the projection :func:`build_scene`
    draws with; raises ``ValueError`` when ``unit.depth_axis`` is ``None``."""
    if unit.depth_axis is None:
        raise ValueError(f"unit {unit.id!r} has no depth_axis to draw an elevation on")
    horizontal, vertical = elevation_axes(unit.depth_axis)
    unit_vertical_mm = unit.size_mm.component_mm(vertical.component_index)
    components = [0.0, 0.0, 0.0]
    components[horizontal.component_index] = point.x()
    components[vertical.component_index] = unit_vertical_mm - point.y()
    return Vec3(*components)


def build_scene(
    unit: Unit, spaces: Mapping[str, Space], selected_id: str | None = None
) -> QtWidgets.QGraphicsScene:
    """A ``QGraphicsScene`` with one rect item per region and per board in
    ``unit``, positioned from ``spaces`` (see
    :func:`freecad.Shelving.core.solver.solve`), plus a dimension for every
    region in a run along an elevation axis. Every item carries its node id
    for :func:`hit_test`; a dimension's items carry their region's id.

    Raises ``ValueError`` naming ``unit.id`` when ``unit.depth_axis`` is
    ``None``: a unit with no depth axis has no elevation plane to project
    onto. Raises ``KeyError`` when ``spaces`` lacks a node in ``unit``.
    ``selected_id``, when given, is the one item drawn with the
    selected pen; every other item gets the normal pen.
    """
    if unit.depth_axis is None:
        raise ValueError(f"unit {unit.id!r} has no depth_axis to draw an elevation on")
    horizontal, vertical = elevation_axes(unit.depth_axis)
    unit_vertical_mm = unit.size_mm.component_mm(vertical.component_index)
    unit_horizontal_mm = unit.size_mm.component_mm(horizontal.component_index)

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
                _add_region_dimensions(
                    scene,
                    region,
                    spaces,
                    horizontal,
                    vertical,
                    unit_vertical_mm,
                    selected_id,
                )
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
    first, so the id belongs to whichever item's Z-value is greatest among
    those covering ``point``: a dimension's label or readout over any rect,
    else the deepest rect. A dimension's lines and arrows are never hit: a
    spacing line crosses a board, and a press there must still grab the
    board.
    """
    for item in scene.items(point):
        if item.data(_DIMENSION_DATA_ROLE) in ("line", "witness", "arrow"):
            continue
        node_id = item.data(_ID_DATA_ROLE)
        if isinstance(node_id, str):
            return node_id
    return None
