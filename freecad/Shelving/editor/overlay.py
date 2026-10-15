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
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeAlias

import FreeCAD
from pivy import coin

from freecad.Shelving.editor.elevation import (
    LIFT_MM,
    DimensionLabel,
    ElevationFrame,
    LabelColor,
    Overlay,
    Rect,
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


def _view_color(name: str, default: int) -> RGB:
    """A packed 0xRRGGBBAA color from FreeCAD's View preferences."""
    packed = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").GetUnsigned(
        name, default
    )
    return (
        ((packed >> 24) & 0xFF) / 255,
        ((packed >> 16) & 0xFF) / 255,
        ((packed >> 8) & 0xFF) / 255,
    )


@dataclass(frozen=True)
class Style:
    """The colors and text size the drawing uses."""

    selected_rgb: RGB
    locked_rgb: RGB
    unlocked_rgb: RGB
    label_size_pt: int

    def label_rgb(self, color: LabelColor) -> RGB:
        if color == "selected":
            return self.selected_rgb
        return self.locked_rgb if color == "locked" else self.unlocked_rgb


def view_style(label_size_pt: int) -> Style:
    """FreeCAD's selection color and the Sketcher's dimension colors, read
    from the View preferences now: red for a size that drives (a locked
    opening), blue for one that only reports. Defaults from FreeCAD 1.1."""
    return Style(
        selected_rgb=_view_color("SelectionColor", 0x1CAD1CFF),
        locked_rgb=_view_color("ConstrainedDimColor", 0xFF2600FF),
        unlocked_rgb=_view_color("NonDrivingConstrDimColor", 0x0026FFFF),
        label_size_pt=label_size_pt,
    )


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
    node.getField("string").setValue(label.text)
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
) -> Coin:
    """The whole drawing for ``overlay`` on ``frame``'s face, in elevation
    coordinates, unpickable so FreeCAD's picking sees the boards beneath."""
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
    dimensions = coin.SoSeparator()
    for layer in (fills, outlines, dimensions):
        content.addChild(layer)
    lift_mm = frame.z_sign * LIFT_MM
    for face in overlay.faces:
        rgb = _VOID_RGB if face.kind == "void" else _BAY_RGB
        fills.addChild(face_node(face.rect, 0.0, rgb, _FILL_TRANSPARENCY))
    for outline in overlay.outlines:
        selected = outline.role == "selected"
        outlines.addChild(
            outline_node(
                outline.rect,
                lift_mm,
                style.selected_rgb if selected else _OUTLINE_RGB,
                _THICK_LINE_PX if selected else _THIN_LINE_PX,
            )
        )
    if preview is not None:
        outlines.addChild(
            face_node(preview, 1.5 * lift_mm, style.selected_rgb, _PREVIEW_TRANSPARENCY)
        )
        outlines.addChild(
            outline_node(preview, 1.5 * lift_mm, style.selected_rgb, _THICK_LINE_PX)
        )
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


def arrow_geometry(rgb: RGB) -> Coin:
    """A double-headed arrow along local x from -1 to 1, for a dragger part:
    Coin's own translator is pale grey and hard to see."""
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
