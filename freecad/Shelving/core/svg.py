"""Render a solved ``Unit`` as a standalone SVG elevation string.

:func:`to_svg` is a pure function: it reads the region tree from a ``Unit``
(for structure, node ids, and the ``SizeRule`` that positioned each region),
the placed spaces from a solved ``Mapping[str, Space]`` (see
:func:`freecad.Shelving.core.solver.solve`), and a
:class:`~freecad.Shelving.core.materials.Catalog` (for the material each board
resolves to), and returns one complete ``<svg>`` document. It never solves,
scans, or touches the filesystem.

The SVG is built with f-strings and ``str.join`` rather than a DOM library so
that :mod:`freecad.Shelving.core` stays free of runtime dependencies. One SVG user
unit is one millimetre. The unit's local frame has its origin at the
front-bottom-left corner with ``+Z`` pointing up; SVG space has ``+y``
pointing down, so every rectangle and text anchor is mapped through
:func:`_svg_x` / :func:`_svg_y`, never an SVG group ``transform`` (a
scale-flip transform would mirror the label text).

A unit has no single "the" elevation plane: it is projected along whichever
axis is given, or else its ``depth_axis``, onto the other two. A ``Division``
along the depth axis places its items front to back, invisible to a flat
projection; the walk still draws each one, so two boards stacked that way
paint the same rectangle in tree order rather than merge into one.

Output is byte-deterministic for a given input: the tree is walked in
pre-order rather than iterating a dict or a set, legend colours are assigned
in first-appearance order of material id, and every coordinate is formatted
with a fixed ``.3f`` spec instead of ``str``/``repr``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import NamedTuple
from xml.sax.saxutils import escape

from freecad.Shelving.core.geometry import AxisIndex, Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Insets,
    Region,
    SizeRule,
    Unit,
    Void,
    Weighted,
)
from freecad.Shelving.core.materials import Catalog, MaterialId

_COORD_SPEC = ".3f"
_LINE_HEIGHT_FACTOR = 1.2
_TITLE_BAND_FACTOR = 2.0

# Fill palette for boards, assigned to the distinct resolved material ids in
# first-appearance order of the walk, so the same input always maps a given
# material to the same colour regardless of how many other materials appear.
_MATERIAL_PALETTE: tuple[str, ...] = (
    "#c65f3d",
    "#3d7ac6",
    "#4ca64c",
    "#b59a3c",
    "#8a5cb5",
    "#3fa6a0",
    "#b5567f",
    "#6f7d34",
)


def _fmt(value: float) -> str:
    """Fixed-precision format for every coordinate, so output is byte-stable."""
    return f"{value:{_COORD_SPEC}}"


def _xml_escape(text: str) -> str:
    """Escape ``& < >`` and the double quote for use in text nodes or attributes."""
    return escape(text, {'"': "&quot;"})


def rule_label(rule: SizeRule) -> str:
    """Human-readable one-liner for a region's ``SizeRule``.

    ``Fixed 400 mm`` / ``Fixed 400 mm (with next)`` / ``Weighted 2`` /
    ``Fill``. A ``Fixed`` rule reads differently per ``Basis``: a
    ``WITH_NEXT`` size is quoted face to face with the next item, a
    ``CLEAR`` size is the region's own extent, and showing them the same
    would defeat the point of drawing dimensions at all.
    """
    match rule:
        case Fixed(basis=Basis.WITH_NEXT):
            return f"Fixed {rule.size_mm:g} mm (with next)"
        case Fixed():
            return f"Fixed {rule.size_mm:g} mm"
        case Weighted():
            return f"Weighted {rule.weight:g}"
        case Fill():
            return "Fill"


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


def _elevation_axes(depth_axis: Axis) -> tuple[Axis, Axis]:
    """The axis pair an elevation is drawn on: horizontal across, vertical up.

    Vertical is Z unless Z is the depth axis, in which case Y stands in;
    horizontal is whichever axis is left. The same convention
    :mod:`freecad.Shelving.core.scan` uses to choose its grid, so a scanned unit's
    depth axis reads the same way here as it did when it was recovered.
    """
    vertical = Axis.Z if depth_axis is not Axis.Z else Axis.Y
    horizontal = next(
        axis for axis in (Axis.X, Axis.Y, Axis.Z) if axis not in (depth_axis, vertical)
    )
    return horizontal, vertical


def _svg_x(h_mm: float, margin_mm: float) -> float:
    """A millimetre position on the horizontal projected axis to SVG X: a
    straight offset by the left margin."""
    return margin_mm + h_mm


def _svg_y(
    v_mm: float,
    extent_v_mm: float,
    unit_vertical_mm: float,
    margin_mm: float,
    title_band_mm: float,
) -> float:
    """A millimetre position on the vertical projected axis to SVG Y: flipped
    about the unit's projected height, then offset by the top margin and the
    title band."""
    return margin_mm + title_band_mm + (unit_vertical_mm - v_mm - extent_v_mm)


def _rect_line(
    css_class: str,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    *,
    fill: str | None = None,
) -> str:
    """One ``<rect>`` element at already-projected SVG coordinates.

    ``fill`` is an inline colour override for the per-material board fills;
    the class alone carries presentation for every other rect.
    """
    fill_attr = "" if fill is None else f' fill="{fill}"'
    return (
        f'  <rect class="{css_class}"{fill_attr} x="{_fmt(x_mm)}" y="{_fmt(y_mm)}" '
        f'width="{_fmt(width_mm)}" height="{_fmt(height_mm)}" />'
    )


def _label_line(
    lines: Sequence[str],
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    font_size_mm: float,
    css_class: str = "label",
) -> str:
    """A centered ``<text>`` with one ``<tspan>`` per entry in ``lines``,
    stacked vertically about the rect's centre at already-projected SVG
    coordinates. ``css_class`` distinguishes the per-kind label styles."""
    cx_mm = x_mm + width_mm / 2.0
    cy_mm = y_mm + height_mm / 2.0
    line_height_mm = font_size_mm * _LINE_HEIGHT_FACTOR
    first_y_mm = cy_mm - (len(lines) - 1) / 2.0 * line_height_mm
    tspans: list[str] = []
    for index, text in enumerate(lines):
        if index == 0:
            pos = f'x="{_fmt(cx_mm)}" y="{_fmt(first_y_mm)}"'
        else:
            pos = f'x="{_fmt(cx_mm)}" dy="{_fmt(line_height_mm)}"'
        tspans.append(f"<tspan {pos}>{_xml_escape(text)}</tspan>")
    return f'  <text class="{css_class}">{"".join(tspans)}</text>'


def _style_block(font_size_mm: float) -> list[str]:
    """The ``<style>`` element: one rule per drawing class. Only the
    per-material board and swatch fills are inline, since they vary per
    element."""
    size = f"{font_size_mm:g}px"
    return [
        "  <style>",
        "    .unit { fill: none; stroke: #333333; stroke-width: 2; }",
        "    .bay { fill: #f2f2f2; fill-opacity: 0.4; "
        "stroke: #666666; stroke-width: 1; }",
        "    .void { fill: #dddddd; fill-opacity: 0.5; "
        "stroke: #999999; stroke-width: 1; stroke-dasharray: 6 3; }",
        "    .board { stroke: #333333; stroke-width: 1; }",
        "    .label { font-family: sans-serif; font-size: "
        f"{size}; fill: #222222; "
        "text-anchor: middle; dominant-baseline: middle; }",
        "    .void-label { font-family: sans-serif; font-size: "
        f"{size}; fill: #666666; font-style: italic; "
        "text-anchor: middle; dominant-baseline: middle; }",
        "    .board-label { font-family: sans-serif; font-size: "
        f"{size}; fill: #222222; "
        "text-anchor: middle; dominant-baseline: middle; }",
        f"    .title {{ font-family: sans-serif; font-size: {size}; fill: #000000; }}",
        f"    .legend {{ font-family: sans-serif; font-size: {size}; fill: #222222; }}",
        "    .swatch { stroke: #333333; stroke-width: 1; }",
        "  </style>",
    ]


def _legend_block(
    used_ids: Sequence[MaterialId],
    colour_by_id: Mapping[MaterialId, str],
    catalog: Catalog,
    unit_vertical_mm: float,
    margin_mm: float,
    title_band_mm: float,
    font_size_mm: float,
) -> list[str]:
    """Material legend below the elevation: a heading then one row per id, in
    ``used_ids`` order (first appearance in the walk) so the output stays
    deterministic without depending on a sort of the id strings.
    """
    line_height_mm = font_size_mm * _LINE_HEIGHT_FACTOR
    top_mm = margin_mm + title_band_mm + unit_vertical_mm + margin_mm
    left_mm = _svg_x(0.0, margin_mm)
    lines = [
        f'  <text class="legend" x="{_fmt(left_mm)}" '
        f'y="{_fmt(top_mm)}">Materials</text>'
    ]
    for index, material_id in enumerate(used_ids):
        entry = catalog[material_id]
        row_y_mm = top_mm + (index + 1) * line_height_mm
        lines.append(
            f'  <rect class="swatch" fill="{colour_by_id[material_id]}" '
            f'x="{_fmt(left_mm)}" y="{_fmt(row_y_mm - font_size_mm)}" '
            f'width="{_fmt(font_size_mm)}" height="{_fmt(font_size_mm)}" />'
        )
        text = f"{entry.name}  {entry.thickness_mm:g} mm  {entry.material_type}"
        lines.append(
            f'  <text class="legend" x="{_fmt(left_mm + font_size_mm * 1.6)}" '
            f'y="{_fmt(row_y_mm)}">{_xml_escape(text)}</text>'
        )
    return lines


def _apply_insets(axis: Axis, space: Space, insets: Insets) -> Space:
    """``space`` with ``insets`` applied to its two cross-section axes.

    The pair on ``axis`` itself (the enclosing division's axis) is ignored: a
    board always fills that axis with its solved extent, its catalog
    thickness unless ``rule`` overrides it, never an inset. Mirrors
    :func:`freecad.Shelving.core.expand._apply_insets`; kept
    as its own copy here rather than imported, the way each module in this
    package keeps its own small geometry helpers instead of reaching into
    another module's private names.
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


def _space(spaces: Mapping[str, Space], node_id: str) -> Space:
    try:
        return spaces[node_id]
    except KeyError:
        raise KeyError(f"no solved space for node {node_id!r}") from None


class _Rect(NamedTuple):
    """A rect already projected onto SVG user-unit (millimetre) coordinates.

    Field order matches the positional parameters of :func:`_rect_line` and
    :func:`_label_line`, so a caller can splat an instance straight into
    either with ``*rect``.
    """

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float


@dataclass(frozen=True)
class _Frame:
    """Fixed layout parameters threaded through the walk's drawing calls."""

    horizontal: Axis
    vertical: Axis
    unit_vertical_mm: float
    margin_mm: float
    title_band_mm: float
    font_size_mm: float

    def rect(self, space: Space) -> _Rect:
        """``space`` projected onto this frame's axis pair, with the
        vertical axis flipped."""
        h_index = _axis_index(self.horizontal)
        v_index = _axis_index(self.vertical)
        width_mm = space.extent_mm(h_index)
        height_mm = space.extent_mm(v_index)
        x_mm = _svg_x(_component_mm(space.origin, h_index), self.margin_mm)
        y_mm = _svg_y(
            _component_mm(space.origin, v_index),
            height_mm,
            self.unit_vertical_mm,
            self.margin_mm,
            self.title_band_mm,
        )
        return _Rect(x_mm=x_mm, y_mm=y_mm, width_mm=width_mm, height_mm=height_mm)


def _walk(
    region: Region,
    spaces: Mapping[str, Space],
    bays_out: list[tuple[Bay, Space]],
    voids_out: list[tuple[Void, Space]],
    boards_out: list[tuple[Board, Space]],
) -> None:
    """Pre-order walk collecting each drawn region and board's placement.

    A ``Division`` contributes no rect of its own, its area is the union of
    its items, so only ``Bay``, ``Void``, and ``Board`` are recorded; each
    ``Board``'s space already has its ``Insets`` applied against the
    enclosing division's axis.
    """
    match region:
        case Bay():
            bays_out.append((region, _space(spaces, region.id)))
        case Void():
            voids_out.append((region, _space(spaces, region.id)))
        case Division():
            for item in region.items:
                if isinstance(item, Board):
                    board_space = _apply_insets(
                        region.axis, _space(spaces, item.id), item.insets
                    )
                    boards_out.append((item, board_space))
                else:
                    _walk(item, spaces, bays_out, voids_out, boards_out)


def to_svg(
    unit: Unit,
    spaces: Mapping[str, Space],
    catalog: Catalog,
    *,
    axis: Axis | None = None,
    scale: float = 1.0,
    margin_mm: float = 20.0,
    font_size_mm: float = 12.0,
) -> str:
    """Complete SVG document for ``unit`` as placed by ``spaces``.

    ``spaces`` must be a complete solve of ``unit`` (see
    :func:`freecad.Shelving.core.solver.solve`); a node id absent from it is a
    programmer error and raises ``KeyError``. ``catalog`` supplies the
    material each board resolves to (its own ``material``, else
    ``unit.default_material``); a material id absent from it raises
    ``KeyError``. The projection is onto ``axis`` when given, else
    ``unit.depth_axis``; when both are ``None`` this raises ``ValueError``
    naming ``unit.id``, because a unit that has never been scanned has no
    depth axis and guessing one would draw a wrong picture silently.
    ``scale`` multiplies only the root ``width``/``height`` attributes,
    leaving the millimetre ``viewBox`` unchanged. ``margin_mm`` pads all four
    sides; a title band of twice ``font_size_mm`` sits above the drawing and
    a material legend below it.
    """
    depth_axis = axis if axis is not None else unit.depth_axis
    if depth_axis is None:
        raise ValueError(f"unit {unit.id!r} has no depth_axis and no axis was given")
    horizontal, vertical = _elevation_axes(depth_axis)

    unit_h_mm = _component_mm(unit.size_mm, _axis_index(horizontal))
    unit_v_mm = _component_mm(unit.size_mm, _axis_index(vertical))
    title_band_mm = font_size_mm * _TITLE_BAND_FACTOR
    line_height_mm = font_size_mm * _LINE_HEIGHT_FACTOR
    frame = _Frame(
        horizontal=horizontal,
        vertical=vertical,
        unit_vertical_mm=unit_v_mm,
        margin_mm=margin_mm,
        title_band_mm=title_band_mm,
        font_size_mm=font_size_mm,
    )

    bays: list[tuple[Bay, Space]] = []
    voids: list[tuple[Void, Space]] = []
    boards: list[tuple[Board, Space]] = []
    _walk(unit.root, spaces, bays, voids, boards)

    # Distinct resolved material ids, in first-appearance order of the walk
    # (tree order), so the palette assignment does not depend on a sort of
    # the id strings.
    material_order: list[MaterialId] = []
    seen_materials: set[MaterialId] = set()
    for board, _ in boards:
        material_id = board.material or unit.default_material
        if material_id not in seen_materials:
            seen_materials.add(material_id)
            material_order.append(material_id)
    colour_by_id: dict[MaterialId, str] = {
        material_id: _MATERIAL_PALETTE[index % len(_MATERIAL_PALETTE)]
        for index, material_id in enumerate(material_order)
    }

    # One heading row plus one row per material, then a bottom margin.
    legend_band_mm = line_height_mm * (len(material_order) + 1) + margin_mm
    view_w_mm = unit_h_mm + 2.0 * margin_mm
    view_h_mm = unit_v_mm + 2.0 * margin_mm + title_band_mm + legend_band_mm

    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(view_w_mm * scale)}" height="{_fmt(view_h_mm * scale)}" '
        f'viewBox="0 0 {_fmt(view_w_mm)} {_fmt(view_h_mm)}">',
    ]
    parts.extend(_style_block(font_size_mm))

    # Boards paint over the open regions beneath them, so bays and voids are
    # drawn before boards; every label sits above the fill it names.
    outline_space = Space(origin=Vec3(0.0, 0.0, 0.0), size=unit.size_mm)
    outline_rect = frame.rect(outline_space)
    parts.append(_rect_line("unit", *outline_rect))

    for bay, space in bays:
        rect = frame.rect(space)
        parts.append(_rect_line("bay", *rect))
        parts.append(
            _label_line(
                [f"{rect.width_mm:g} x {rect.height_mm:g} mm", rule_label(bay.rule)],
                *rect,
                font_size_mm,
            )
        )

    for void, space in voids:
        rect = frame.rect(space)
        parts.append(_rect_line("void", *rect))
        parts.append(
            _label_line(
                [
                    "not part of the unit",
                    f"{rect.width_mm:g} x {rect.height_mm:g} mm",
                    rule_label(void.rule),
                ],
                *rect,
                font_size_mm,
                css_class="void-label",
            )
        )

    for board, space in boards:
        material_id = board.material or unit.default_material
        entry = catalog[material_id]
        rect = frame.rect(space)
        parts.append(_rect_line("board", *rect, fill=colour_by_id[material_id]))
        label_lines = [line for line in (board.role,) if line]
        label_lines.append(f"{entry.name} {entry.thickness_mm:g} mm")
        parts.append(
            _label_line(
                label_lines,
                *rect,
                font_size_mm,
                css_class="board-label",
            )
        )

    default_entry = catalog[unit.default_material]
    title = (
        f"Unit {unit.size_mm.x_mm:g} x {unit.size_mm.y_mm:g} x "
        f"{unit.size_mm.z_mm:g} mm, default material: "
        f"{default_entry.name} ({default_entry.thickness_mm:g} mm)"
    )
    parts.append(
        f'  <text class="title" x="{_fmt(margin_mm)}" '
        f'y="{_fmt(margin_mm + font_size_mm)}">{_xml_escape(title)}</text>'
    )
    parts.extend(
        _legend_block(
            material_order,
            colour_by_id,
            catalog,
            unit_v_mm,
            margin_mm,
            title_band_mm,
            font_size_mm,
        )
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
