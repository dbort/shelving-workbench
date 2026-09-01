"""SVG renderer: document shape, the solver-to-SVG y-flip, and determinism.

``shelving_core.svg.to_svg`` builds its output with f-strings, so these tests
parse it back with :mod:`xml.etree.ElementTree` (parsing only; construction
stays library-free in the renderer) and assert on the resulting element tree:
the root element and its ``viewBox``, the rect and label counts for a known
tree, the exact placed geometry for a hand-computed case that proves +z maps to
smaller SVG ``y``, and byte-identical output across two calls.
"""

import xml.etree.ElementTree as ET

import pytest

from shelving_core.layout import (
    Carcass,
    Divider,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
    Weighted,
)
from shelving_core.solver import solve
from shelving_core.svg import to_svg

SVG_NS = "http://www.w3.org/2000/svg"


def _tag(name: str) -> str:
    return f"{{{SVG_NS}}}{name}"


def _rects_by_class(root: ET.Element, css_class: str) -> list[ET.Element]:
    return [r for r in root.findall(_tag("rect")) if r.get("class") == css_class]


def _flat_fill_carcass(orientation: Orientation, n_children: int) -> Carcass:
    """A single split of ``n_children`` equal ``Fill`` openings under the root."""
    root = Split(
        orientation=orientation,
        children=[Leaf(id=f"leaf{i}") for i in range(n_children)],
        rules=[Fill() for _ in range(n_children)],
        dividers=[Divider(id=f"div{i}") for i in range(n_children - 1)],
        id="root",
    )
    return Carcass(
        width_mm=100.0,
        height_mm=100.0,
        depth_mm=50.0,
        default_thickness_mm=10.0,
        root=root,
    )


def _nested_sample() -> Carcass:
    """Root HORIZONTAL split over a plain leaf and a 3-way VERTICAL split.

    Four leaves, three dividers (one at the root, two in the inner split), one
    of each rule kind.
    """
    inner = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(id="a"), Leaf(id="b"), Leaf(id="c")],
        rules=[Fill(), Weighted(2.0), Fill()],
        dividers=[Divider(id="di0"), Divider(id="di1")],
        id="inner",
    )
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[Leaf(id="solo"), inner],
        rules=[Fixed(400.0), Fill()],
        dividers=[Divider(id="dr0")],
        id="root",
    )
    return Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_thickness_mm=18.0,
        root=root,
    )


def test_output_parses_and_root_is_svg_with_viewbox() -> None:
    carcass = _nested_sample()
    root = ET.fromstring(to_svg(carcass, solve(carcass)))
    assert root.tag == _tag("svg")
    view_box = root.get("viewBox")
    assert view_box is not None
    # W = width + 2*margin; H = height + 2*margin + title band (2*font_size).
    assert view_box == "0 0 940.000 1864.000"
    assert root.get("width") == "940.000"
    assert root.get("height") == "1864.000"


def test_rect_and_label_counts_for_a_known_tree() -> None:
    carcass = _nested_sample()
    root = ET.fromstring(to_svg(carcass, solve(carcass)))

    n_leaves = 4
    n_dividers = 3
    assert len(root.findall(_tag("rect"))) == n_leaves + n_dividers + 1
    assert len(_rects_by_class(root, "carcass")) == 1
    assert len(_rects_by_class(root, "divider")) == n_dividers
    assert len(_rects_by_class(root, "leaf")) == n_leaves

    texts = root.findall(_tag("text"))
    label_texts = [t for t in texts if t.get("class") == "label"]
    title_texts = [t for t in texts if t.get("class") == "title"]
    assert len(label_texts) == n_leaves
    assert len(title_texts) == 1
    assert title_texts[0].text is not None
    assert title_texts[0].text.startswith("Carcass 900 x 1800 x 300 mm")

    # Every label carries its three lines: dimensions, short id, rule.
    for label in label_texts:
        tspans = label.findall(_tag("tspan"))
        assert len(tspans) == 3


def test_root_leaf_without_a_split_has_no_rule_line() -> None:
    carcass = Carcass(
        width_mm=100.0,
        height_mm=100.0,
        depth_mm=50.0,
        default_thickness_mm=10.0,
        root=Leaf(id="only"),
    )
    root = ET.fromstring(to_svg(carcass, solve(carcass)))
    (label,) = [t for t in root.findall(_tag("text")) if t.get("class") == "label"]
    tspans = label.findall(_tag("tspan"))
    assert [t.text for t in tspans] == ["80 x 80 mm", "only"]


def test_y_flip_places_higher_z_nearer_the_top() -> None:
    carcass = _flat_fill_carcass(Orientation.HORIZONTAL, 2)
    root = ET.fromstring(to_svg(carcass, solve(carcass)))
    low, high = _rects_by_class(root, "leaf")

    # Interior 80x80 at solver (10, 10); 80 mm split minus a 10 mm divider is
    # two 35 mm openings. Child 0 sits at solver z=10..45, child 1 at z=55..90.
    # margin 20, title band 24: svg_y = 44 + (100 - z - h).
    assert float(low.get("x", "nan")) == pytest.approx(30.0)
    assert float(low.get("y", "nan")) == pytest.approx(99.0)
    assert float(low.get("width", "nan")) == pytest.approx(80.0)
    assert float(low.get("height", "nan")) == pytest.approx(35.0)

    assert float(high.get("x", "nan")) == pytest.approx(30.0)
    assert float(high.get("y", "nan")) == pytest.approx(54.0)
    assert float(high.get("width", "nan")) == pytest.approx(80.0)
    assert float(high.get("height", "nan")) == pytest.approx(35.0)

    assert float(high.get("y", "nan")) < float(low.get("y", "nan"))


def test_three_way_split_renders_three_leaves_and_two_dividers() -> None:
    carcass = _flat_fill_carcass(Orientation.VERTICAL, 3)
    root = ET.fromstring(to_svg(carcass, solve(carcass)))
    assert len(_rects_by_class(root, "leaf")) == 3
    assert len(_rects_by_class(root, "divider")) == 2


def test_output_is_deterministic() -> None:
    carcass = _nested_sample()
    layout = solve(carcass)
    assert to_svg(carcass, layout) == to_svg(carcass, layout)


def test_markup_metacharacters_in_an_id_are_xml_escaped() -> None:
    raw_id = 'x<a>&"y'
    carcass = Carcass(
        width_mm=100.0,
        height_mm=100.0,
        depth_mm=50.0,
        default_thickness_mm=10.0,
        root=Leaf(id=raw_id),
    )
    svg = to_svg(carcass, solve(carcass))

    # Still well-formed with the metacharacters carried through the label text.
    root = ET.fromstring(svg)

    # The escaped forms are present and the raw run never appears in a text node.
    assert "&lt;" in svg
    assert "&gt;" in svg
    assert "&amp;" in svg
    assert "&quot;" in svg
    assert raw_id not in svg

    (label,) = [t for t in root.findall(_tag("text")) if t.get("class") == "label"]
    short_id_tspan = label.findall(_tag("tspan"))[1]
    assert short_id_tspan.text == raw_id[:8]


def test_scale_grows_size_attributes_but_leaves_viewbox_untouched() -> None:
    carcass = _nested_sample()
    layout = solve(carcass)
    base = ET.fromstring(to_svg(carcass, layout, scale=1.0))
    scaled = ET.fromstring(to_svg(carcass, layout, scale=2.0))

    assert scaled.get("viewBox") == base.get("viewBox")

    _, _, view_w, view_h = (base.get("viewBox") or "").split()
    assert float(scaled.get("width", "nan")) == pytest.approx(2.0 * float(view_w))
    assert float(scaled.get("height", "nan")) == pytest.approx(2.0 * float(view_h))
