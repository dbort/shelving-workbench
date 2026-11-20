"""Coin nodes for the in-view editor: the drawing an
:class:`~freecad.Shelving.editor.elevation.Overlay` describes, and the
drag arrow's geometry.

Coin defers translucent shapes and sorts them by distance from the camera,
and ``SoDatumLabel`` always counts itself translucent, so a fill could land
over a dimension and dim it depending on the view. An
``SoTransparencyType`` of ``BLEND`` draws the drawing in scene order
instead: fills, then outlines, then dimensions.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeAlias, TypeVar

import FreeCAD
from pivy import coin
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from freecad.Shelving.editor.elevation import (
    LIFT_MM,
    ConstraintKind,
    DimensionLabel,
    ElevationFrame,
    LabelColor,
    OutlineRole,
    Overlay,
    Rect,
    RowIcon,
)

# pivy ships no type information, so every Coin node and field is untyped.
Coin: TypeAlias = Any

RGB = tuple[float, float, float]

_BAY_RGB: RGB = (0.85, 0.85, 0.85)
_VOID_RGB: RGB = (0.6, 0.6, 0.6)
_OUTLINE_RGB: RGB = (0.2, 0.2, 0.2)
_FILL_TRANSPARENCY = 0.6
_PREVIEW_TRANSPARENCY = 0.3
_THIN_LINE_PX = 1.0
_THICK_LINE_PX = 3.0
_DIMENSION_LINE_PX = 1.5


_VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
# FreeCAD 1.1's background colors for keys left unset, probed in its 3D
# view (.claude/docs/freecad-notes.md): the plain color, the gradient's
# top and bottom, and its middle, which matches their average.
_BACKGROUND_DEFAULT = 0xEAE5DCFF
_GRADIENT_TOP_DEFAULT = 0x333365FF
_GRADIENT_BOTTOM_DEFAULT = 0xABABC1FF
_GRADIENT_MIDDLE_DEFAULT = 0x6F6F93FF


class ViewParams(Protocol):
    """The part of a FreeCAD parameter group the background reading uses."""

    def GetBool(self, name: str, default: bool, /) -> bool: ...
    def GetUnsigned(self, name: str, default: int, /) -> int: ...


def _unpacked(packed: int) -> RGB:
    return (
        ((packed >> 24) & 0xFF) / 255,
        ((packed >> 16) & 0xFF) / 255,
        ((packed >> 8) & 0xFF) / 255,
    )


def _view_color(name: str, default: int) -> RGB:
    """A packed 0xRRGGBBAA color from FreeCAD's View preferences."""
    return _unpacked(FreeCAD.ParamGet(_VIEW_PARAMS).GetUnsigned(name, default))


def background_rgb(params: ViewParams) -> RGB:
    """The 3D view's background color as the View preferences ``params``
    set it. With neither gradient on, it is ``BackgroundColor``. A gradient
    gives its middle: ``BackgroundColor4`` when ``UseBackgroundColorMid``
    is set, otherwise halfway between ``BackgroundColor2`` and
    ``BackgroundColor3``."""
    # As FreeCAD's viewer reads them: Gradient defaults to on, and the
    # dialog's Simple choice is never read.
    gradient = params.GetBool("Gradient", True) or params.GetBool(
        "RadialGradient", False
    )
    if not gradient:
        return _unpacked(params.GetUnsigned("BackgroundColor", _BACKGROUND_DEFAULT))
    if params.GetBool("UseBackgroundColorMid", False):
        return _unpacked(
            params.GetUnsigned("BackgroundColor4", _GRADIENT_MIDDLE_DEFAULT)
        )
    top = _unpacked(params.GetUnsigned("BackgroundColor2", _GRADIENT_TOP_DEFAULT))
    bottom = _unpacked(params.GetUnsigned("BackgroundColor3", _GRADIENT_BOTTOM_DEFAULT))
    red, green, blue = ((a + b) / 2 for a, b in zip(top, bottom, strict=True))
    return (red, green, blue)


@dataclass(frozen=True)
class Style:
    """The colors and text size the drawing uses."""

    selected_rgb: RGB
    locked_rgb: RGB
    unlocked_rgb: RGB
    marker_rgb: RGB
    label_size_pt: int
    # A constraint's icon, whether it is active or deactivated: a
    # deactivated one carries a corner X instead of another color.
    icon_rgb: RGB = (1.0, 38 / 255, 0.0)
    # The tile under each dimension's text, padlock and constraint icon:
    # the view's own background, which the theme picks the dimension and
    # icon colors to stand out against, where an opening's fill would blur
    # them.
    tile_rgb: RGB = (247 / 255, 247 / 255, 247 / 255)

    def label_rgb(self, color: LabelColor) -> RGB:
        return self.locked_rgb if color == "locked" else self.unlocked_rgb

    def constraint_icon_rgb(self, selected: bool) -> RGB:
        """The selection color for a selected constraint's icon, the icon
        color otherwise, whatever the constraint's activation. The Sketcher's
        ``constrColor`` grays a deactivated icon, which its selection color
        then hides; the corner X carries activation here instead."""
        return self.selected_rgb if selected else self.icon_rgb

    def outline_rgb(self, role: OutlineRole) -> RGB:
        """The selection color for "selected", the locked dimension color
        for "holding", so a holding region reads as the lock it is, and a
        dark gray for "region"."""
        if role == "selected":
            return self.selected_rgb
        if role == "holding":
            return self.locked_rgb
        return _OUTLINE_RGB


def marker_rgb() -> RGB:
    """The fixed point marker's color, read from the View preferences now:
    the Sketcher's own billboard icon color, by default FreeCAD 1.1's red."""
    return _view_color("ConstrainedIcoColor", 0xFF2600FF)


def view_style(label_size_pt: int) -> Style:
    """FreeCAD's selection color and the Sketcher's dimension and
    constraint icon colors, read from the View preferences now: red for a
    size that drives (a locked opening), blue for one that only reports,
    and the fixed point's marker in the color of the Sketcher's own
    billboard icons. A constraint's icon takes the Sketcher's icon color
    and sits with each padlock and dimension text on a tile of the view's
    background. Defaults from FreeCAD 1.1."""
    return Style(
        selected_rgb=_view_color("SelectionColor", 0x1CAD1CFF),
        locked_rgb=_view_color("ConstrainedDimColor", 0xFF2600FF),
        unlocked_rgb=_view_color("NonDrivingConstrDimColor", 0x0026FFFF),
        marker_rgb=marker_rgb(),
        label_size_pt=label_size_pt,
        icon_rgb=_view_color("ConstrainedIcoColor", 0xFF2600FF),
        tile_rgb=background_rgb(FreeCAD.ParamGet(_VIEW_PARAMS)),
    )


# The workbench's own icons in the Sketcher's constraint style. Drawing
# Equal as well as Even spacing keeps the pair matched and spares
# importing SketcherGui, whose import alone registers the Sketcher's icons
# (.claude/docs/freecad-notes.md).
_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
ICON_SOURCES: Mapping[ConstraintKind, str] = {
    "equal": os.path.join(_RESOURCES, "Constraint_Equal.svg"),
    "even_spacing": os.path.join(_RESOURCES, "Constraint_EvenSpacing.svg"),
}


# The tile's margin around a glyph or a dimension's text, and its corner
# radius, in logical pixels.
TILE_PAD_PX = 2
TILE_RADIUS_PX = 3


@dataclass(frozen=True)
class Tile:
    """The tile a padlock's or constraint icon's glyph, or a dimension's
    text, sits on, in device pixels."""

    rgb: RGB
    pad_px: int
    radius_px: float


def icon_side_px() -> int:
    """The constraint icon's side in logical pixels: the Sketcher's
    ``ConstraintSymbolSize`` preference, by default the application font's
    pixel size, as ``EditModeCoinManager`` reads it."""
    default_px = QtGui.QFontInfo(QtWidgets.QApplication.font()).pixelSize()
    return FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").GetInt(
        "ConstraintSymbolSize", default_px
    )


def text_tile_image(tile: Tile, width_px: int, height_px: int) -> QtGui.QImage:
    """``tile`` alone, ``width_px`` by ``height_px`` device pixels, its
    rounded corners transparent."""
    image = QtGui.QImage(width_px, height_px, QtGui.QImage.Format.Format_RGBA8888)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.setPen(QtCore.Qt.PenStyle.NoPen)
    painter.setBrush(QtGui.QColor.fromRgbF(*tile.rgb))
    painter.drawRoundedRect(
        QtCore.QRectF(0, 0, width_px, height_px), tile.radius_px, tile.radius_px
    )
    painter.end()
    return image


def _on_tile(glyph: QtGui.QImage, tile: Tile, side_px: int) -> QtGui.QImage:
    """``glyph`` drawn ``tile.pad_px`` in from each edge of ``tile``,
    ``side_px`` device pixels square."""
    image = text_tile_image(tile, side_px, side_px)
    painter = QtGui.QPainter(image)
    painter.drawImage(QtCore.QPointF(tile.pad_px, tile.pad_px), glyph)
    painter.end()
    return image


# The deactivated mark: an X in the glyph square's top-right corner, where
# both SVGs leave the most room, spanning this fraction of the glyph's
# side. A gap cleared around its strokes parts it from any glyph shape it
# crosses. The stroke and gap have a one-pixel floor so the X stays legible
# at the smallest ConstraintSymbolSize.
_CORNER_X_SIDE = 0.45
_CORNER_X_STROKE = 0.1
_CORNER_X_GAP = 0.04


def _corner_x_widths_px(glyph_px: int) -> tuple[float, float]:
    """The X's stroke width and the width of the gap cleared along it."""
    stroke_px = max(1.0, _CORNER_X_STROKE * glyph_px)
    return stroke_px, stroke_px + 2 * max(1.0, _CORNER_X_GAP * glyph_px)


def corner_x_extent_px(glyph_px: int) -> float:
    """The side of the square in a ``glyph_px`` glyph's top-right corner
    that holds every pixel the deactivated mark changes, before
    antialiasing spreads its edge by up to a pixel."""
    stroke_px, gap_px = _corner_x_widths_px(glyph_px)
    return _CORNER_X_SIDE * glyph_px - stroke_px / 2 + gap_px / 2


def _draw_corner_x(painter: QtGui.QPainter, glyph_px: int) -> None:
    """Paint the deactivated mark onto the ``glyph_px`` glyph ``painter``
    draws, opaque on a cleared gap."""
    stroke_px, gap_px = _corner_x_widths_px(glyph_px)
    side_px = _CORNER_X_SIDE * glyph_px
    # The stroke's own half width keeps its round caps inside the glyph
    # square; the gap may run off it, where nothing is drawn.
    inset_px = stroke_px / 2
    left_px = glyph_px - side_px + inset_px
    right_px = glyph_px - inset_px
    top_px = inset_px
    bottom_px = side_px - inset_px
    strokes = [
        QtCore.QLineF(left_px, top_px, right_px, bottom_px),
        QtCore.QLineF(left_px, bottom_px, right_px, top_px),
    ]
    painter.save()
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(QtCore.Qt.GlobalColor.black)
    pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
    pen.setWidthF(gap_px)
    painter.setPen(pen)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_Clear)
    painter.drawLines(strokes)
    pen.setWidthF(stroke_px)
    painter.setPen(pen)
    painter.setCompositionMode(
        QtGui.QPainter.CompositionMode.CompositionMode_SourceOver
    )
    painter.drawLines(strokes)
    painter.restore()


def constraint_icon_image(
    kind: ConstraintKind, rgb: RGB, tile: Tile, side_px: int, active: bool = True
) -> QtGui.QImage:
    """``kind``'s icon on ``tile``, ``side_px`` device pixels square, with a
    corner X unless ``active``. The glyph, ``tile.pad_px`` in from each
    edge, fills every painted pixel with ``rgb`` at its own coverage, as the
    Sketcher's ``renderConstrIcon`` recolors its icons with a source-in
    fill, so the X takes ``rgb`` as well; the tile's rounded corners stay
    transparent."""
    glyph_px = side_px - 2 * tile.pad_px
    glyph = QtGui.QImage(glyph_px, glyph_px, QtGui.QImage.Format.Format_RGBA8888)
    glyph.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(glyph)
    QtSvg.QSvgRenderer(ICON_SOURCES[kind]).render(painter)
    if not active:
        _draw_corner_x(painter, glyph_px)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(glyph.rect(), QtGui.QColor.fromRgbF(*rgb))
    painter.end()
    return _on_tile(glyph, tile, side_px)


# The padlock glyph's proportions on its square, designed at 14 pixels:
# the body's inset from the left and right edges and its top and height,
# the stroke, the shackle's box, and how far an open shackle swings.
_PADLOCK_DESIGN_PX = 14.0
_PADLOCK_INSET = 2 / _PADLOCK_DESIGN_PX
_PADLOCK_BODY_TOP = 0.45
_PADLOCK_BODY_HEIGHT = 0.5
_PADLOCK_STROKE = 1.6 / _PADLOCK_DESIGN_PX
_PADLOCK_SHACKLE_LEFT = 4 / _PADLOCK_DESIGN_PX
_PADLOCK_SHACKLE_TOP = 1.5 / _PADLOCK_DESIGN_PX
_PADLOCK_SHACKLE_HEIGHT = 0.6
_PADLOCK_SWING_RIGHT = 0.18
_PADLOCK_SWING_UP = 1 / _PADLOCK_DESIGN_PX


def padlock_image(locked: bool, rgb: RGB, tile: Tile, side_px: int) -> QtGui.QImage:
    """A padlock in ``rgb`` on ``tile``, ``side_px`` device pixels square: a
    filled body under a shackle, closed when ``locked``, swung open off the
    body's left side otherwise. The glyph sits ``tile.pad_px`` in from each
    edge, as :func:`constraint_icon_image` places its own, and the tile's
    rounded corners stay transparent."""
    glyph_px = side_px - 2 * tile.pad_px
    glyph = QtGui.QImage(glyph_px, glyph_px, QtGui.QImage.Format.Format_RGBA8888)
    glyph.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(glyph)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    color = QtGui.QColor.fromRgbF(*rgb)
    pen = QtGui.QPen(color)
    pen.setWidthF(_PADLOCK_STROKE * glyph_px)
    painter.setPen(pen)
    inset_px = _PADLOCK_INSET * glyph_px
    body = QtCore.QRectF(
        inset_px,
        _PADLOCK_BODY_TOP * glyph_px,
        glyph_px - 2 * inset_px,
        _PADLOCK_BODY_HEIGHT * glyph_px,
    )
    shackle_left_px = _PADLOCK_SHACKLE_LEFT * glyph_px
    shackle = QtCore.QRectF(
        shackle_left_px,
        _PADLOCK_SHACKLE_TOP * glyph_px,
        glyph_px - 2 * shackle_left_px,
        _PADLOCK_SHACKLE_HEIGHT * glyph_px,
    )
    if not locked:
        shackle.translate(
            _PADLOCK_SWING_RIGHT * glyph_px, -_PADLOCK_SWING_UP * glyph_px
        )
    painter.drawArc(shackle, 0, 180 * 16)
    painter.drawLine(
        QtCore.QPointF(shackle.right(), shackle.center().y()),
        QtCore.QPointF(shackle.right(), body.top()),
    )
    if locked:
        painter.drawLine(
            QtCore.QPointF(shackle.left(), shackle.center().y()),
            QtCore.QPointF(shackle.left(), body.top()),
        )
    painter.fillRect(body, color)
    painter.end()
    return _on_tile(glyph, tile, side_px)


def coin_rgba(image: QtGui.QImage) -> tuple[int, int, bytes]:
    """``image``, in RGBA8888, as the width, height and bytes an ``SoImage``
    takes: rows from the bottom up, where Qt runs them top down."""
    pixels = bytes(image.constBits())
    stride = image.bytesPerLine()
    row_bytes = image.width() * 4
    rows = [
        pixels[start : start + row_bytes] for start in range(0, len(pixels), stride)
    ]
    return image.width(), image.height(), b"".join(reversed(rows))


def padded_icon_image(
    icon: QtGui.QImage, horizontal: bool, lead_px: int
) -> QtGui.QImage:
    """``icon`` after ``lead_px`` transparent device pixels: to its left for
    a horizontal dimension, below it for a vertical one, so an image
    anchored at the text's center by its left or bottom edge puts the icon
    that far along the line, whatever the zoom."""
    side_px = icon.width()
    width_px = side_px + lead_px if horizontal else side_px
    height_px = side_px if horizontal else side_px + lead_px
    padded = QtGui.QImage(width_px, height_px, QtGui.QImage.Format.Format_RGBA8888)
    padded.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(padded)
    painter.drawImage(QtCore.QPointF(lead_px if horizontal else 0, 0), icon)
    painter.end()
    return padded


def _material(rgb: RGB, transparency: float = 0.0) -> Coin:
    material = coin.SoMaterial()
    material.diffuseColor.setValue(*rgb)
    material.transparency.setValue(transparency)
    return material


def _corners(rect: Rect, z_mm: float) -> list[list[float]]:
    return [
        [rect.h0_mm, rect.v0_mm, z_mm],
        [rect.h1_mm, rect.v0_mm, z_mm],
        [rect.h1_mm, rect.v1_mm, z_mm],
        [rect.h0_mm, rect.v1_mm, z_mm],
    ]


def face_node(rect: Rect, z_mm: float, rgb: RGB, transparency: float) -> Coin:
    group = coin.SoSeparator()
    coordinates = coin.SoCoordinate3()
    coordinates.point.setValues(0, 4, _corners(rect, z_mm))
    faces = coin.SoFaceSet()
    faces.numVertices.setValue(4)
    for node in (_material(rgb, transparency), coordinates, faces):
        group.addChild(node)
    return group


def outline_node(rect: Rect, z_mm: float, rgb: RGB, width_px: float) -> Coin:
    group = coin.SoSeparator()
    style = coin.SoDrawStyle()
    style.lineWidth.setValue(width_px)
    corners = _corners(rect, z_mm)
    coordinates = coin.SoCoordinate3()
    coordinates.point.setValues(0, 5, [*corners, corners[0]])
    lines = coin.SoLineSet()
    lines.numVertices.setValue(5)
    for node in (_material(rgb), style, coordinates, lines):
        group.addChild(node)
    return group


def length_text(length_mm: float) -> str:
    """``length_mm`` in the user's unit system with its unit, as FreeCAD
    shows a length, less the trailing zeros of a decimal fraction."""
    text = FreeCAD.Units.Quantity(length_mm, FreeCAD.Units.Length).UserString
    # UserString writes the number in the default QLocale, so the point may
    # be a comma, and the other of the two a group separator. FreeCAD pads
    # every length to the Decimals preference, but a fraction such as 5/8
    # must keep its digits.
    point = re.escape(QtCore.QLocale().decimalPoint())
    trailing_zeros = re.compile(rf"{point}(\d*?)0+(?!\d)")
    return trailing_zeros.sub(
        lambda match: match[0][0] + match[1] if match[1] else "", text
    )


def datum_label_node(
    label: DimensionLabel, z_mm: float, style: Style, normal: FreeCAD.Vector
) -> Coin:
    """``label`` as the Sketcher's own dimension node. ``normal`` is the
    front face's normal in document coordinates on either face: the node
    compares it with the camera's direction to decide which way its text
    reads, so a normal in the local frame would mirror the text."""
    rgb = style.label_rgb(label.color)
    node = coin.SoType.fromName("SoDatumLabel").createInstance()
    (h0_mm, v0_mm), (h1_mm, v1_mm) = label.start_mm, label.end_mm
    node.getField("pnts").setValues(0, 2, [[h0_mm, v0_mm, z_mm], [h1_mm, v1_mm, z_mm]])
    node.getField("norm").setValue(normal.x, normal.y, normal.z)
    node.getField("string").setValue(length_text(label.size_mm))
    node.getField("textColor").setValue(*rgb)
    node.getField("size").setValue(style.label_size_pt)
    node.getField("param2").setValue(label.text_shift_mm)
    node.getField("lineWidth").setValue(_DIMENSION_LINE_PX)
    group = coin.SoSeparator()
    group.addChild(_material(rgb))
    group.addChild(node)
    return group


def drawing_node(
    overlay: Overlay,
    frame: ElevationFrame,
    style: Style,
    normal: FreeCAD.Vector,
    preview: Rect | None,
    text_tiles: Sequence[TextTileNode] = (),
) -> Coin:
    """The whole drawing for ``overlay`` on ``frame``'s face, in elevation
    coordinates, unpickable so FreeCAD's picking sees the boards beneath.
    ``text_tiles`` draw after the outlines and before every dimension, so a
    tile hides fills and faces but no dimension's line, arrowhead or
    text."""
    content = coin.SoSeparator()
    pick_style = coin.SoPickStyle()
    pick_style.style = coin.SoPickStyle.UNPICKABLE
    content.addChild(pick_style)
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    content.addChild(light)
    transparency = coin.SoTransparencyType()
    transparency.getField("value").setValue(coin.SoTransparencyType.BLEND)
    content.addChild(transparency)
    fills = coin.SoSeparator()
    # A fill must not hide the dimension lines behind it from the depth
    # test, since SoDatumLabel draws its lines in the face's own plane. The
    # offset draws a fill in front of a solid face in the same plane, such
    # as a back panel's, without moving it off the face.
    no_depth_write = coin.SoDepthBuffer()
    no_depth_write.getField("write").setValue(False)
    fills.addChild(no_depth_write)
    offset = coin.SoPolygonOffset()
    offset.factor.setValue(-1.0)
    offset.units.setValue(-1.0)
    fills.addChild(offset)
    outlines = coin.SoSeparator()
    tiles = coin.SoSeparator()
    # As the icons' images draw: over every face, and leaving the depth
    # buffer to the dimensions drawn after.
    tiles_depth = coin.SoDepthBuffer()
    tiles_depth.getField("test").setValue(False)
    tiles_depth.getField("write").setValue(False)
    tiles.addChild(tiles_depth)
    dimensions = coin.SoSeparator()
    for layer in (fills, outlines, tiles, dimensions):
        content.addChild(layer)
    lift_mm = frame.z_sign * LIFT_MM
    for face in overlay.faces:
        rgb = _VOID_RGB if face.kind == "void" else _BAY_RGB
        fills.addChild(face_node(face.rect, 0.0, rgb, _FILL_TRANSPARENCY))
    for outline in overlay.outlines:
        outlines.addChild(
            outline_node(
                outline.rect,
                lift_mm,
                style.outline_rgb(outline.role),
                _THIN_LINE_PX if outline.role == "region" else _THICK_LINE_PX,
            )
        )
    if preview is not None:
        outlines.addChild(
            face_node(preview, 1.5 * lift_mm, style.selected_rgb, _PREVIEW_TRANSPARENCY)
        )
        outlines.addChild(
            outline_node(preview, 1.5 * lift_mm, style.selected_rgb, _THICK_LINE_PX)
        )
    for tile in text_tiles:
        tiles.addChild(tile.root)
    for label in overlay.labels:
        dimensions.addChild(datum_label_node(label, 2 * lift_mm, style, normal))
    if overlay.labels:
        dimensions.addChild(_label_bounds_node(overlay.labels, 3 * lift_mm))
    return content


def _label_bounds_node(labels: Sequence[DimensionLabel], z_mm: float) -> Coin:
    """Invisible points just past the dimensions' height, so the scene's
    bounding box reaches them. ``SoDatumLabel`` gives its own box no depth,
    and FreeCAD's orthographic camera clips just in front of the scene's
    box: with the camera square on to the unit, it clipped the dimensions'
    lines and text and left only their arrowheads, which ``SoDatumLabel``
    draws on the face itself."""
    group = coin.SoSeparator()
    style = coin.SoDrawStyle()
    style.style = coin.SoDrawStyle.INVISIBLE
    corners = [
        [h_mm, v_mm, z_mm]
        for label in labels
        for h_mm, v_mm in (label.start_mm, label.end_mm, label.text_at_mm)
    ]
    coordinates = coin.SoCoordinate3()
    coordinates.point.setValues(0, len(corners), corners)
    points = coin.SoPointSet()
    for node in (style, coordinates, points):
        group.addChild(node)
    return group


def _image_group(depth_free: bool = True) -> tuple[Coin, Coin]:
    """A group whose shapes nothing picks, and the translation that places
    its image. With ``depth_free`` it draws over every shape before it,
    with no depth test or write."""
    group = coin.SoSeparator()
    pick_style = coin.SoPickStyle()
    pick_style.style = coin.SoPickStyle.UNPICKABLE
    group.addChild(pick_style)
    if depth_free:
        depth = coin.SoDepthBuffer()
        depth.getField("test").setValue(False)
        depth.getField("write").setValue(False)
        group.addChild(depth)
    translation = coin.SoTranslation()
    group.addChild(translation)
    return group, translation


class PointMarker:
    """An image drawn at a point, facing the camera at any orientation as
    the Sketcher's constraint icons are, over every shape in the scene and
    unpickable, so a click lands on whatever is beneath it. The image keeps
    its device-pixel size at every zoom.
    """

    def __init__(self) -> None:
        # Goes under the elevation frame's transform.
        self.root: Coin = coin.SoSeparator()
        self._switch: Coin = coin.SoSwitch()
        self.root.addChild(self._switch)
        content, self.translation = _image_group()
        self._switch.addChild(content)
        self._switch.whichChild.setValue(0)
        self.image: Coin = coin.SoImage()
        self.image.horAlignment = coin.SoImage.CENTER
        self.image.vertAlignment = coin.SoImage.HALF
        content.addChild(self.image)
        self.drawn = QtGui.QImage()

    def place(self, at_mm: tuple[float, float, float]) -> None:
        """Center the image on the elevation point ``at_mm``."""
        self.translation.translation.setValue(*at_mm)

    def set_image(self, image: QtGui.QImage) -> None:
        """Show ``image``, in RGBA8888, at one image pixel a device pixel."""
        # Kept for reading back: pivy decodes an SoSFImage's bytes as text.
        self.drawn = image
        width_px, height_px, rgba = coin_rgba(image)
        self.image.image.setValue(coin.SbVec2s(width_px, height_px), 4, rgba)

    def show(self, shown: bool) -> None:
        self._switch.whichChild.setValue(0 if shown else coin.SO_SWITCH_NONE)

    @property
    def shown(self) -> bool:
        return int(self._switch.whichChild.getValue()) == 0


IconT = TypeVar("IconT", bound=RowIcon)


class IconNode(Generic[IconT]):
    """A padlock's or constraint's icon, drawn as :class:`PointMarker`
    draws its image, after its dimension's text along the line."""

    def __init__(self, icon: IconT) -> None:
        self.icon = icon
        self.root, translation = _image_group()
        h_mm, v_mm = icon.label.text_at_mm
        translation.translation.setValue(h_mm, v_mm, 0.0)
        self.image: Coin = coin.SoImage()
        if icon.label.horizontal:
            self.image.horAlignment = coin.SoImage.LEFT
            self.image.vertAlignment = coin.SoImage.HALF
        else:
            self.image.horAlignment = coin.SoImage.CENTER
            self.image.vertAlignment = coin.SoImage.BOTTOM
        self.root.addChild(self.image)
        self.drawn = QtGui.QImage()

    def set_image(self, image: QtGui.QImage) -> None:
        """Show ``image``, from :func:`padded_icon_image`, at one image pixel
        a device pixel."""
        # Kept for reading back: pivy decodes an SoSFImage's bytes as text.
        self.drawn = image
        width_px, height_px, rgba = coin_rgba(image)
        self.image.image.setValue(coin.SbVec2s(width_px, height_px), 4, rgba)


class TextTileNode:
    """The tile under a dimension's text, centered on it, facing the camera
    and keeping its device-pixel size as the text does. It takes the depth
    settings of the layer :func:`drawing_node` puts it in."""

    def __init__(self, label: DimensionLabel, z_mm: float, image: QtGui.QImage) -> None:
        self.label = label
        # The layer turns the depth test off for every tile at once.
        self.root, translation = _image_group(depth_free=False)
        h_mm, v_mm = label.text_at_mm
        translation.translation.setValue(h_mm, v_mm, z_mm)
        self.image: Coin = coin.SoImage()
        self.image.horAlignment = coin.SoImage.CENTER
        self.image.vertAlignment = coin.SoImage.HALF
        self.root.addChild(self.image)
        # Kept for reading back: pivy decodes an SoSFImage's bytes as text.
        self.drawn = image
        width_px, height_px, rgba = coin_rgba(image)
        self.image.image.setValue(coin.SbVec2s(width_px, height_px), 4, rgba)


def arrow_geometry(rgb: RGB) -> Coin:
    """A double-headed arrow along local x from -1 to 1, for a dragger part:
    Coin's own translator is pale gray and hard to see."""
    group = coin.SoSeparator()
    light = coin.SoLightModel()
    light.model = coin.SoLightModel.BASE_COLOR
    group.addChild(light)
    group.addChild(_material(rgb))
    # Coin's cylinder and cone stand along y; a quarter turn about z lays
    # them along x.
    turn = coin.SoRotationXYZ()
    turn.axis = coin.SoRotationXYZ.Z
    turn.angle = -math.pi / 2
    group.addChild(turn)
    shaft = coin.SoCylinder()
    shaft.radius = 0.12
    shaft.height = 1.2
    group.addChild(shaft)
    for sign in (1.0, -1.0):
        head = coin.SoSeparator()
        place = coin.SoTranslation()
        place.translation.setValue(0.0, sign * 0.8, 0.0)
        head.addChild(place)
        if sign < 0:
            flip = coin.SoRotationXYZ()
            flip.axis = coin.SoRotationXYZ.X
            flip.angle = math.pi
            head.addChild(flip)
        cone = coin.SoCone()
        cone.bottomRadius = 0.3
        cone.height = 0.4
        head.addChild(cone)
        group.addChild(head)
    return group


def coin_destroys_draggers_safely() -> bool:
    """Whether this Coin has the coin3d/coin#556 fix (4.0.4 or later):
    before it, destroying a dragger that has been dragged crashes FreeCAD
    on macOS, where FreeCAD 1.1's bundle ships Coin 4.0.3."""
    # The string reads like "SIM Coin 4.0.3".
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", str(coin.SoDB.getVersion()))
    if found is None:
        return False
    major, minor, patch = (int(part) for part in found.groups())
    return (major, minor, patch) >= (4, 0, 4)
