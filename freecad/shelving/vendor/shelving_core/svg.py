"""Render a solved ``Carcass`` layout as a standalone SVG elevation string.

:func:`to_svg` is a pure function: it reads the split-tree from a ``Carcass``
(for structure, node ids, and the ``SplitRule`` that positioned each child), the
placed rectangles from a :class:`~shelving_core.solver.SolvedLayout`, and a
:class:`~shelving_core.materials.Catalog` (for the panel material each divider
resolves to), and returns one complete ``<svg>`` document. It never calls
``solve`` and never touches the filesystem.

The SVG is built with f-strings and ``str.join`` rather than a DOM library so
that :mod:`shelving_core` stays free of runtime dependencies. One SVG user unit
is one millimetre. Solver space has its origin at the front-bottom-left corner
with +z pointing up; SVG space has +y pointing down, so every rectangle and
text anchor is mapped through :func:`_svg_x` / :func:`_svg_y`, never an SVG
group ``transform`` (a scale-flip transform would mirror the label text).

Output is byte-deterministic for a given input: the tree is walked in pre-order
rather than iterating a dict, divider colours are assigned over the material ids
in ascending string order, and every coordinate is formatted with a fixed
``.3f`` spec instead of ``str``/``repr``.
"""

from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape

from shelving_core.layout import (
    Bay,
    Carcass,
    Fill,
    Fixed,
    Leaf,
    Split,
    SplitRule,
    Weighted,
)
from shelving_core.materials import Catalog, MaterialId
from shelving_core.solver import Rect, SolvedLayout

_COORD_SPEC = ".3f"
_LINE_HEIGHT_FACTOR = 1.2
_TITLE_BAND_FACTOR = 2.0

# Divider fill palette, assigned to the distinct material ids in use in
# ascending id order so the same materials always map to the same colours
# regardless of tree-walk order.
_DIVIDER_PALETTE: tuple[str, ...] = (
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


def rule_label(rule: SplitRule) -> str:
    """Human-readable one-liner for the rule that positioned a bay.

    ``Fixed 400 mm`` / ``Weighted 2`` / ``Fill``. Exhaustive over the
    ``SplitRule`` union.
    """
    match rule:
        case Fixed():
            return f"Fixed {rule.size_mm:g} mm"
        case Weighted():
            return f"Weighted {rule.weight:g}"
        case Fill():
            return "Fill"


def _svg_x(x_mm: float, margin_mm: float) -> float:
    """Solver X to SVG X: a straight offset by the left margin."""
    return margin_mm + x_mm


def _svg_y(
    z_mm: float,
    h_mm: float,
    carcass_height_mm: float,
    margin_mm: float,
    title_band_mm: float,
) -> float:
    """Solver Z to SVG Y: flip about the carcass height, then offset by the
    top margin and the title band."""
    return margin_mm + title_band_mm + (carcass_height_mm - z_mm - h_mm)


def _walk(
    bay: Bay,
    rule: SplitRule | None,
    layout: SolvedLayout,
    default_material: MaterialId,
    dividers_out: list[tuple[Rect, MaterialId]],
    leaves_out: list[tuple[str, Rect, SplitRule | None]],
) -> None:
    """Pre-order walk collecting divider and leaf placements.

    ``rule`` is the ``SplitRule`` that positioned ``bay`` within its parent
    split, or ``None`` for the carcass root. ``Split`` nodes contribute no rect
    of their own (their area is the union of their children); each child is
    visited in list order, with the divider that follows it appended right
    after so z-order stays deterministic. Each divider's placed ``Rect`` and
    resolved material id (its own ``material``, else ``default_material``) are
    collected; leaves keep their id for the short-id label.
    """
    match bay:
        case Leaf():
            leaves_out.append((bay.id, layout[bay.id], rule))
        case Split():
            for index, child in enumerate(bay.children):
                _walk(
                    child,
                    bay.rules[index],
                    layout,
                    default_material,
                    dividers_out,
                    leaves_out,
                )
                if index < len(bay.dividers):
                    divider = bay.dividers[index]
                    material_id = (
                        divider.material
                        if divider.material is not None
                        else default_material
                    )
                    dividers_out.append((layout[divider.id], material_id))


def _rect_line(
    css_class: str,
    rect: Rect,
    carcass_height_mm: float,
    margin_mm: float,
    title_band_mm: float,
    *,
    fill: str | None = None,
) -> str:
    """One ``<rect>`` element, geometry mapped through the y-flip helpers.

    ``fill`` is an inline colour override for the per-material divider fills;
    the class alone carries presentation for every other rect.
    """
    x = _svg_x(rect.x_mm, margin_mm)
    y = _svg_y(rect.z_mm, rect.height_mm, carcass_height_mm, margin_mm, title_band_mm)
    fill_attr = "" if fill is None else f' fill="{fill}"'
    return (
        f'  <rect class="{css_class}"{fill_attr} x="{_fmt(x)}" y="{_fmt(y)}" '
        f'width="{_fmt(rect.width_mm)}" height="{_fmt(rect.height_mm)}" />'
    )


def _label_line(
    lines: list[str],
    rect: Rect,
    carcass_height_mm: float,
    margin_mm: float,
    title_band_mm: float,
    font_size_mm: float,
    css_class: str = "label",
) -> str:
    """A centered ``<text>`` with one ``<tspan>`` per entry in ``lines``,
    stacked vertically about the rect's centre. ``css_class`` distinguishes the
    per-leaf labels from the per-divider material labels."""
    cx = _svg_x(rect.x_mm + rect.width_mm / 2.0, margin_mm)
    top = _svg_y(rect.z_mm, rect.height_mm, carcass_height_mm, margin_mm, title_band_mm)
    cy = top + rect.height_mm / 2.0
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
    """The ``<style>`` element: one rule per drawing class. Only the per-material
    divider and swatch fills are inline, since they vary per element."""
    size = f"{font_size_mm:g}px"
    return [
        "  <style>",
        "    .carcass { fill: none; stroke: #333333; stroke-width: 2; }",
        "    .divider { stroke: none; }",
        "    .leaf { fill: #f2f2f2; fill-opacity: 0.4; "
        "stroke: #666666; stroke-width: 1; }",
        "    .label { font-family: sans-serif; font-size: "
        f"{size}; fill: #222222; "
        "text-anchor: middle; dominant-baseline: middle; }",
        f"    .title {{ font-family: sans-serif; font-size: {size}; fill: #000000; }}",
        "    .divider-label { font-family: sans-serif; font-size: "
        f"{size}; fill: #222222; "
        "text-anchor: middle; dominant-baseline: middle; }",
        f"    .legend {{ font-family: sans-serif; font-size: {size}; fill: #222222; }}",
        "    .swatch { stroke: #333333; stroke-width: 1; }",
        "  </style>",
    ]


def _legend_block(
    used_ids: Sequence[MaterialId],
    colour_by_id: Mapping[MaterialId, str],
    catalog: Catalog,
    carcass_height_mm: float,
    margin_mm: float,
    title_band_mm: float,
    font_size_mm: float,
) -> list[str]:
    """Material legend below the elevation: a heading then one row per id.

    Rows follow ``used_ids`` order (ascending material id), each a colour swatch
    plus ``name``, ``thickness_mm``, and ``material_type``.
    """
    line_height_mm = font_size_mm * _LINE_HEIGHT_FACTOR
    top_mm = margin_mm + title_band_mm + carcass_height_mm + margin_mm
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


def to_svg(
    carcass: Carcass,
    layout: SolvedLayout,
    catalog: Catalog,
    *,
    scale: float = 1.0,
    margin_mm: float = 20.0,
    font_size_mm: float = 12.0,
) -> str:
    """Complete SVG document for ``carcass`` as placed by ``layout``.

    ``layout`` must be a complete solve of ``carcass``; a node id absent from it
    is a programmer error and raises ``KeyError``. ``catalog`` supplies the
    material each divider resolves to (its own ``material``, else
    ``carcass.default_material``); a material id absent from it raises
    ``KeyError``. ``scale`` multiplies only the root ``width``/``height``
    attributes, leaving the millimetre ``viewBox`` unchanged. ``margin_mm`` pads
    all four sides; a title band of twice ``font_size_mm`` sits above the drawing
    and a material legend below it.
    """
    title_band_mm = font_size_mm * _TITLE_BAND_FACTOR
    line_height_mm = font_size_mm * _LINE_HEIGHT_FACTOR

    dividers: list[tuple[Rect, MaterialId]] = []
    leaves: list[tuple[str, Rect, SplitRule | None]] = []
    _walk(carcass.root, None, layout, carcass.default_material, dividers, leaves)

    # Distinct material ids in use: the shell default plus every divider's
    # resolved material, in ascending id order so the palette assignment does
    # not depend on tree-walk order.
    used_ids = sorted({carcass.default_material} | {mid for _, mid in dividers})
    colour_by_id: dict[MaterialId, str] = {
        material_id: _DIVIDER_PALETTE[index % len(_DIVIDER_PALETTE)]
        for index, material_id in enumerate(used_ids)
    }

    # One heading row plus one row per material, then a bottom margin.
    legend_band_mm = line_height_mm * (len(used_ids) + 1) + margin_mm
    view_w = carcass.width_mm + 2.0 * margin_mm
    view_h = carcass.height_mm + 2.0 * margin_mm + title_band_mm + legend_band_mm

    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(view_w * scale)}" height="{_fmt(view_h * scale)}" '
        f'viewBox="0 0 {_fmt(view_w)} {_fmt(view_h)}">',
    ]
    parts.extend(_style_block(font_size_mm))

    # Carcass outline first, then every divider with its material label, then
    # every leaf with its label, then the title and legend: leaves and text
    # always sit above the divider fills.
    outline = Rect(
        x_mm=0.0, z_mm=0.0, width_mm=carcass.width_mm, height_mm=carcass.height_mm
    )
    parts.append(
        _rect_line("carcass", outline, carcass.height_mm, margin_mm, title_band_mm)
    )
    for rect, material_id in dividers:
        entry = catalog[material_id]
        parts.append(
            _rect_line(
                "divider",
                rect,
                carcass.height_mm,
                margin_mm,
                title_band_mm,
                fill=colour_by_id[material_id],
            )
        )
        parts.append(
            _label_line(
                [f"{entry.name} {entry.thickness_mm:g} mm"],
                rect,
                carcass.height_mm,
                margin_mm,
                title_band_mm,
                font_size_mm,
                css_class="divider-label",
            )
        )
    for leaf_id, rect, rule in leaves:
        parts.append(
            _rect_line("leaf", rect, carcass.height_mm, margin_mm, title_band_mm)
        )
        label_lines = [
            f"{rect.width_mm:g} x {rect.height_mm:g} mm",
            leaf_id[:8],
        ]
        if rule is not None:
            label_lines.append(rule_label(rule))
        parts.append(
            _label_line(
                label_lines,
                rect,
                carcass.height_mm,
                margin_mm,
                title_band_mm,
                font_size_mm,
            )
        )

    default_entry = catalog[carcass.default_material]
    title = (
        f"Carcass {carcass.width_mm:g} x {carcass.height_mm:g} x "
        f"{carcass.depth_mm:g} mm, default material: "
        f"{default_entry.name} ({default_entry.thickness_mm:g} mm)"
    )
    parts.append(
        f'  <text class="title" x="{_fmt(margin_mm)}" '
        f'y="{_fmt(margin_mm + font_size_mm)}">{_xml_escape(title)}</text>'
    )
    parts.extend(
        _legend_block(
            used_ids,
            colour_by_id,
            catalog,
            carcass.height_mm,
            margin_mm,
            title_band_mm,
            font_size_mm,
        )
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
