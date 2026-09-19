"""Tests for rendering a solved ``Unit`` as an SVG elevation string."""

import re
import xml.etree.ElementTree as ET

import pytest

from shelving_core.geometry import Vec3
from shelving_core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    Insets,
    Unit,
    Void,
)
from shelving_core.materials import Catalog, MaterialEntry, MaterialId
from shelving_core.solver import solve
from shelving_core.svg import rule_label, to_svg

SVG_TAG = "{http://www.w3.org/2000/svg}svg"
RECT_TAG = "{http://www.w3.org/2000/svg}rect"
TEXT_TAG = "{http://www.w3.org/2000/svg}text"
TSPAN_TAG = "{http://www.w3.org/2000/svg}tspan"

PLY = MaterialId("ply18")
MDF = MaterialId("mdf12")
CATALOG = Catalog(
    entries={
        PLY: MaterialEntry(PLY, "18 mm ply", 18.0, "plywood"),
        MDF: MaterialEntry(MDF, "12 mm MDF", 12.0, "mdf"),
    }
)


def _closed_unit(*, depth_axis: Axis | None = Axis.Y) -> Unit:
    """Bottom, one open bay, top, stacked along Z: no step in the outline."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 600.0),
        default_material=PLY,
        depth_axis=depth_axis,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom", id="bottom"),
                Bay(id="middle"),
                Board(role="top", id="top"),
            ],
            id="root",
        ),
    )


def _stepped_unit() -> Unit:
    """Same outer size and rule as ``_closed_unit``, its middle bay a void."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 600.0),
        default_material=PLY,
        depth_axis=Axis.Y,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom", id="bottom"),
                Void(id="middle"),
                Board(role="top", id="top"),
            ],
            id="root",
        ),
    )


def _unit_with_shelf_insets(insets: Insets) -> Unit:
    """A single shelf in a division along the depth axis, so its insets show
    on both projected axes (X and Z) rather than only one."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 600.0),
        default_material=PLY,
        depth_axis=Axis.Y,
        root=Division(
            axis=Axis.Y,
            items=[Board(role="shelf", id="shelf", insets=insets), Bay(id="rest")],
            id="root",
        ),
    )


def _rects(document: str) -> list[ET.Element]:
    return ET.fromstring(document).findall(f".//{RECT_TAG}")


def _labels(document: str) -> list[str]:
    """Every ``<text>`` element's joined ``<tspan>`` text, in document order."""
    return [
        "".join(tspan.text or "" for tspan in text.iter(TSPAN_TAG))
        for text in ET.fromstring(document).iter(TEXT_TAG)
    ]


def test_document_parses_with_svg_root_tag() -> None:
    unit = _closed_unit()
    spaces = solve(unit, CATALOG)
    document = to_svg(unit, spaces, CATALOG)
    assert ET.fromstring(document).tag == SVG_TAG


def test_viewbox_matches_the_units_projected_extent_plus_margins() -> None:
    unit = _closed_unit()
    spaces = solve(unit, CATALOG)
    margin_mm = 20.0
    document = to_svg(unit, spaces, CATALOG, margin_mm=margin_mm)
    root = ET.fromstring(document)
    view_box = (root.get("viewBox") or "").split()
    min_x, min_y, view_w, view_h = (float(v) for v in view_box)
    assert (min_x, min_y) == (0.0, 0.0)
    # depth_axis=Y projects onto X (horizontal) and Z (vertical).
    assert view_w == pytest.approx(unit.size_mm.x_mm + 2 * margin_mm)
    # The vertical extent also carries a title band and a legend band, so it
    # is strictly more than the bare projected height plus margins.
    assert view_h > unit.size_mm.z_mm + 2 * margin_mm


def test_scale_changes_root_size_but_leaves_viewbox_alone() -> None:
    unit = _closed_unit()
    spaces = solve(unit, CATALOG)
    plain = ET.fromstring(to_svg(unit, spaces, CATALOG))
    scaled = ET.fromstring(to_svg(unit, spaces, CATALOG, scale=2.0))
    assert plain.get("viewBox") == scaled.get("viewBox")
    assert float(scaled.get("width", "")) == pytest.approx(
        2.0 * float(plain.get("width", ""))
    )
    assert float(scaled.get("height", "")) == pytest.approx(
        2.0 * float(plain.get("height", ""))
    )


def test_material_absent_from_catalog_raises_key_error() -> None:
    unit = _closed_unit()
    spaces = solve(unit, CATALOG)
    with pytest.raises(KeyError):
        to_svg(unit, spaces, Catalog(entries={}))


def test_node_id_absent_from_spaces_raises_key_error() -> None:
    unit = _closed_unit()
    spaces = dict(solve(unit, CATALOG))
    del spaces["middle"]
    with pytest.raises(KeyError):
        to_svg(unit, spaces, CATALOG)


def test_unit_with_no_depth_axis_and_no_axis_argument_raises_value_error() -> None:
    unit = _closed_unit(depth_axis=None)
    spaces = solve(unit, CATALOG)
    with pytest.raises(ValueError, match=re.escape(unit.id)):
        to_svg(unit, spaces, CATALOG)


def test_rendering_the_same_unit_twice_is_identical() -> None:
    unit = _closed_unit()
    spaces = solve(unit, CATALOG)
    assert to_svg(unit, spaces, CATALOG) == to_svg(unit, spaces, CATALOG)


def test_fixed_basis_changes_the_rule_label() -> None:
    clear = rule_label(Fixed(400.0, Basis.CLEAR))
    with_next = rule_label(Fixed(400.0, Basis.WITH_NEXT))
    assert clear != with_next


def test_void_renders_distinct_from_a_bay_of_the_same_outer_size() -> None:
    closed = _closed_unit()
    stepped = _stepped_unit()
    closed_document = to_svg(closed, solve(closed, CATALOG), CATALOG)
    stepped_document = to_svg(stepped, solve(stepped, CATALOG), CATALOG)

    assert closed_document != stepped_document
    assert not any(r.get("class") == "void" for r in _rects(closed_document))
    assert any(r.get("class") == "void" for r in _rects(stepped_document))

    # Same outer size: the swapped region solves to the same span either way,
    # so the difference is attributable to the void, not to a size change.
    closed_root = ET.fromstring(closed_document)
    stepped_root = ET.fromstring(stepped_document)
    assert closed_root.get("viewBox") == stepped_root.get("viewBox")


def test_board_insets_render_a_smaller_rect_on_both_projected_axes() -> None:
    plain = _unit_with_shelf_insets(Insets())
    inset = _unit_with_shelf_insets(
        Insets(x_min_mm=10.0, x_max_mm=10.0, z_min_mm=5.0, z_max_mm=5.0)
    )
    plain_document = to_svg(plain, solve(plain, CATALOG), CATALOG)
    inset_document = to_svg(inset, solve(inset, CATALOG), CATALOG)

    plain_rect = next(r for r in _rects(plain_document) if r.get("class") == "board")
    inset_rect = next(r for r in _rects(inset_document) if r.get("class") == "board")
    assert float(inset_rect.get("width", "")) < float(plain_rect.get("width", ""))
    assert float(inset_rect.get("height", "")) < float(plain_rect.get("height", ""))


def test_two_boards_face_to_face_render_as_two_adjoining_rects() -> None:
    unit = Unit(
        size_mm=Vec3(600.0, 300.0, 600.0),
        default_material=PLY,
        depth_axis=Axis.Y,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="lowerboard", id="lower", material=PLY),
                Board(role="upperboard", id="upper", material=MDF),
                Bay(id="bay"),
            ],
            id="root",
        ),
    )
    document = to_svg(unit, solve(unit, CATALOG), CATALOG)
    board_rects = [r for r in _rects(document) if r.get("class") == "board"]
    assert len(board_rects) == 2
    lower, upper = board_rects
    # SVG y is flipped relative to the solver's z, but adjoining boards still
    # share an edge: the lower board's top y equals the upper board's bottom.
    assert float(lower.get("y", "")) == pytest.approx(
        float(upper.get("y", "")) + float(upper.get("height", ""))
    )
    labels = _labels(document)
    assert any("lowerboard" in label for label in labels)
    assert any("upperboard" in label for label in labels)
