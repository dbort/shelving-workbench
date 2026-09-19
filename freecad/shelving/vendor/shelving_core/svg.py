"""Render a solved ``Unit`` as a standalone SVG elevation string.

:func:`to_svg` is a pure function: it reads the region tree from a ``Unit``
(for structure, node ids, and the ``SizeRule`` that positioned each region),
the placed spaces from a solved ``Mapping[str, Space]`` (see
:func:`shelving_core.solver.solve`), and a
:class:`~shelving_core.materials.Catalog` (for the material each board
resolves to), and returns one complete ``<svg>`` document. It never solves,
scans, or touches the filesystem.

The SVG is built with f-strings and ``str.join`` rather than a DOM library so
that :mod:`shelving_core` stays free of runtime dependencies. One SVG user
unit is one millimetre. The unit's local frame has its origin at the
front-bottom-left corner with ``+Z`` pointing up; SVG space has ``+y``
pointing down, so every rectangle and text anchor is mapped through
:func:`_svg_x` / :func:`_svg_y`, never an SVG group ``transform`` (a
scale-flip transform would mirror the label text).

A unit has no single "the" elevation plane: it is projected along whichever
axis is given, or else its ``depth_axis``, onto the other two.

Output is byte-deterministic for a given input: the tree is walked in
pre-order rather than iterating a dict or a set, legend colours are assigned
in first-appearance order of material id, and every coordinate is formatted
with a fixed ``.3f`` spec instead of ``str``/``repr``.
"""

from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

from .geometry import AxisIndex, Vec3
from .layout import Axis, Basis, Fill, Fixed, SizeRule, Weighted
from .materials import Catalog, MaterialId

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
    :mod:`shelving_core.scan` uses to choose its grid, so a scanned unit's
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
    x: float,
    y: float,
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
        f'  <rect class="{css_class}"{fill_attr} x="{_fmt(x)}" y="{_fmt(y)}" '
        f'width="{_fmt(width_mm)}" height="{_fmt(height_mm)}" />'
    )


def _label_line(
    lines: Sequence[str],
    x: float,
    y: float,
    width_mm: float,
    height_mm: float,
    font_size_mm: float,
    css_class: str = "label",
) -> str:
    """A centered ``<text>`` with one ``<tspan>`` per entry in ``lines``,
    stacked vertically about the rect's centre at already-projected SVG
    coordinates. ``css_class`` distinguishes the per-kind label styles."""
    cx = x + width_mm / 2.0
    cy = y + height_mm / 2.0
    line_height = font_size_mm * _LINE_HEIGHT_FACTOR
    first_y = cy - (len(lines) - 1) / 2.0 * line_height
    tspans: list[str] = []
    for index, text in enumerate(lines):
        if index == 0:
            pos = f'x="{_fmt(cx)}" y="{_fmt(first_y)}"'
        else:
            pos = f'x="{_fmt(cx)}" dy="{_fmt(line_height)}"'
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
        row_y = top_mm + (index + 1) * line_height_mm
        lines.append(
            f'  <rect class="swatch" fill="{colour_by_id[material_id]}" '
            f'x="{_fmt(left_mm)}" y="{_fmt(row_y - font_size_mm)}" '
            f'width="{_fmt(font_size_mm)}" height="{_fmt(font_size_mm)}" />'
        )
        text = f"{entry.name}  {entry.thickness_mm:g} mm  {entry.material_type}"
        lines.append(
            f'  <text class="legend" x="{_fmt(left_mm + font_size_mm * 1.6)}" '
            f'y="{_fmt(row_y)}">{_xml_escape(text)}</text>'
        )
    return lines
