"""Render a solved ``Carcass`` layout as a standalone SVG elevation string.

:func:`to_svg` is a pure function: it reads the split-tree from a ``Carcass``
(for structure, node ids, and the ``SplitRule`` that positioned each child) and
the placed rectangles from a :class:`~shelving_core.solver.SolvedLayout`, and
returns one complete ``<svg>`` document. It never calls ``solve`` and never
touches the filesystem.

The SVG is built with f-strings and ``str.join`` rather than a DOM library so
that :mod:`shelving_core` stays free of runtime dependencies. One SVG user unit
is one millimetre. Solver space has its origin at the front-bottom-left corner
with +z pointing up; SVG space has +y pointing down, so every rectangle and
text anchor is mapped through :func:`_svg_x` / :func:`_svg_y`, never an SVG
group ``transform`` (a scale-flip transform would mirror the label text).

Output is byte-deterministic for a given input: the tree is walked in pre-order
rather than iterating a dict, and every coordinate is formatted with a fixed
``.3f`` spec instead of ``str``/``repr``.
"""

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
from shelving_core.solver import Rect, SolvedLayout

_COORD_SPEC = ".3f"
_LINE_HEIGHT_FACTOR = 1.2
_TITLE_BAND_FACTOR = 2.0


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
    dividers_out: list[Rect],
    leaves_out: list[tuple[str, Rect, SplitRule | None]],
) -> None:
    """Pre-order walk collecting divider and leaf placements.

    ``rule`` is the ``SplitRule`` that positioned ``bay`` within its parent
    split, or ``None`` for the carcass root. ``Split`` nodes contribute no rect
    of their own (their area is the union of their children); each child is
    visited in list order, with the divider that follows it appended right
    after so z-order stays deterministic. Dividers carry no label, so only their
    placed ``Rect`` is collected; leaves keep their id for the short-id label.
    """
    match bay:
        case Leaf():
            leaves_out.append((bay.id, layout[bay.id], rule))
        case Split():
            for index, child in enumerate(bay.children):
                _walk(child, bay.rules[index], layout, dividers_out, leaves_out)
                if index < len(bay.dividers):
                    dividers_out.append(layout[bay.dividers[index].id])


def _rect_line(
    css_class: str,
    rect: Rect,
    carcass_height_mm: float,
    margin_mm: float,
    title_band_mm: float,
) -> str:
    """One ``<rect>`` element, geometry mapped through the y-flip helpers."""
    x = _svg_x(rect.x_mm, margin_mm)
    y = _svg_y(rect.z_mm, rect.height_mm, carcass_height_mm, margin_mm, title_band_mm)
    return (
        f'  <rect class="{css_class}" x="{_fmt(x)}" y="{_fmt(y)}" '
        f'width="{_fmt(rect.width_mm)}" height="{_fmt(rect.height_mm)}" />'
    )


def _label_line(
    lines: list[str],
    rect: Rect,
    carcass_height_mm: float,
    margin_mm: float,
    title_band_mm: float,
    font_size_mm: float,
) -> str:
    """A centered ``<text class="label">`` with one ``<tspan>`` per entry in
    ``lines``, stacked vertically about the rect's centre."""
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
    return f'  <text class="label">{"".join(tspans)}</text>'


def _style_block(font_size_mm: float) -> list[str]:
    """The ``<style>`` element: one rule per drawing class, no inline presentation."""
    size = f"{font_size_mm:g}px"
    return [
        "  <style>",
        "    .carcass { fill: none; stroke: #333333; stroke-width: 2; }",
        "    .divider { fill: #888888; stroke: none; }",
        "    .leaf { fill: #f2f2f2; fill-opacity: 0.4; "
        "stroke: #666666; stroke-width: 1; }",
        "    .label { font-family: sans-serif; font-size: "
        f"{size}; fill: #222222; "
        "text-anchor: middle; dominant-baseline: middle; }",
        f"    .title {{ font-family: sans-serif; font-size: {size}; fill: #000000; }}",
        "  </style>",
    ]


def to_svg(
    carcass: Carcass,
    layout: SolvedLayout,
    *,
    scale: float = 1.0,
    margin_mm: float = 20.0,
    font_size_mm: float = 12.0,
) -> str:
    """Complete SVG document for ``carcass`` as placed by ``layout``.

    ``layout`` must be a complete solve of ``carcass``; a node id absent from it
    is a programmer error and raises ``KeyError``. ``scale`` multiplies only the
    root ``width``/``height`` attributes, leaving the millimetre ``viewBox``
    unchanged. ``margin_mm`` pads all four sides; a title band of twice
    ``font_size_mm`` is added above the drawing for the ``<text class="title">``.
    """
    title_band_mm = font_size_mm * _TITLE_BAND_FACTOR
    view_w = carcass.width_mm + 2.0 * margin_mm
    view_h = carcass.height_mm + 2.0 * margin_mm + title_band_mm

    dividers: list[Rect] = []
    leaves: list[tuple[str, Rect, SplitRule | None]] = []
    _walk(carcass.root, None, layout, dividers, leaves)

    parts: list[str] = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{_fmt(view_w * scale)}" height="{_fmt(view_h * scale)}" '
        f'viewBox="0 0 {_fmt(view_w)} {_fmt(view_h)}">',
    ]
    parts.extend(_style_block(font_size_mm))

    # Carcass outline first, then every divider, then every leaf with its label,
    # then the title: leaves and text always sit above the divider fills.
    outline = Rect(
        x_mm=0.0, z_mm=0.0, width_mm=carcass.width_mm, height_mm=carcass.height_mm
    )
    parts.append(
        _rect_line("carcass", outline, carcass.height_mm, margin_mm, title_band_mm)
    )
    for rect in dividers:
        parts.append(
            _rect_line("divider", rect, carcass.height_mm, margin_mm, title_band_mm)
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

    title = (
        f"Carcass {carcass.width_mm:g} x {carcass.height_mm:g} x "
        f"{carcass.depth_mm:g} mm"
    )
    parts.append(
        f'  <text class="title" x="{_fmt(margin_mm)}" '
        f'y="{_fmt(margin_mm + font_size_mm)}">{_xml_escape(title)}</text>'
    )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
