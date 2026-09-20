"""Tests for rendering a solved ``Unit`` as an SVG elevation string."""

import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

import pytest

from freecad.shelving.core.geometry import Vec3
from freecad.shelving.core.layout import (
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
from freecad.shelving.core.materials import Catalog, MaterialEntry, MaterialId
from freecad.shelving.core.scan import Box, export_from_json, scan
from freecad.shelving.core.solver import solve
from freecad.shelving.core.svg import rule_label, to_svg

SVG_TAG = "{http://www.w3.org/2000/svg}svg"
RECT_TAG = "{http://www.w3.org/2000/svg}rect"
TEXT_TAG = "{http://www.w3.org/2000/svg}text"
TSPAN_TAG = "{http://www.w3.org/2000/svg}tspan"

FIXTURES = Path(__file__).parent / "fixtures"
REAL_STAIR_STEP = FIXTURES / "real_stair_step.boxes.json"
REAL_MAGICSTART_F1 = FIXTURES / "real_magicstart_f1.boxes.json"

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


def _unit_with_distinct_dims(*, depth_axis: Axis | None) -> Unit:
    """Same shape as ``_closed_unit`` but with three different extents on
    X, Y, and Z, so projecting onto the wrong axis pair changes the viewBox
    rather than coincidentally matching it."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
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


def _view_box(document: str) -> tuple[float, float, float, float]:
    raw = (ET.fromstring(document).get("viewBox") or "").split()
    min_x, min_y, view_w, view_h = (float(v) for v in raw)
    return min_x, min_y, view_w, view_h


def _labels(document: str) -> list[str]:
    """Every ``<text>`` element's joined ``<tspan>`` text, in document order."""
    return [
        "".join(tspan.text or "" for tspan in text.iter(TSPAN_TAG))
        for text in ET.fromstring(document).iter(TEXT_TAG)
    ]


def _catalog_from_thicknesses(boxes: Sequence[Box]) -> Catalog:
    """A generic material per distinct board thickness in ``boxes``.

    Built from the fixture's own geometry rather than a hand-picked catalog.
    The round to four decimal places only merges the sub-thousandth jitter
    real exported geometry has between nominally identical boards (see
    :attr:`~freecad.shelving.core.scan.ScanResult.thicknesses_mm`); it must not round
    away real precision the way a whole-millimetre bucket would, because a
    region ``scan`` recovers as ``Fixed`` at its exact measured size only
    solves again if the catalog resolves its board back to that same
    thickness.
    """
    thicknesses_mm = sorted(
        {round(min(b.size_mm.x_mm, b.size_mm.y_mm, b.size_mm.z_mm), 4) for b in boxes}
    )
    return Catalog(
        entries={
            MaterialId(f"generic{t}"): MaterialEntry(
                id=MaterialId(f"generic{t}"),
                name=f"{t} mm stock",
                thickness_mm=float(t),
                material_type="generic",
            )
            for t in thicknesses_mm
        }
    )


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


def test_axis_override_renders_a_unit_with_no_depth_axis() -> None:
    unit = _unit_with_distinct_dims(depth_axis=None)
    spaces = solve(unit, CATALOG)
    document = to_svg(unit, spaces, CATALOG, axis=Axis.Y)
    assert ET.fromstring(document).tag == SVG_TAG


def test_axis_override_projects_onto_the_given_axis_pair() -> None:
    """``axis=Axis.Y`` projects onto (X, Z); ``axis=Axis.Z`` projects onto
    (X, Y), exercising ``_elevation_axes``'s Z-is-depth branch and the
    ``v_index == 1`` path through ``_Frame.rect`` that every other test in
    this suite (all built with ``depth_axis=Axis.Y``) leaves unexercised."""
    unit = _unit_with_distinct_dims(depth_axis=None)
    spaces = solve(unit, CATALOG)
    document_y = to_svg(unit, spaces, CATALOG, axis=Axis.Y)
    document_z = to_svg(unit, spaces, CATALOG, axis=Axis.Z)

    _, _, view_w_y, view_h_y = _view_box(document_y)
    _, _, view_w_z, view_h_z = _view_box(document_z)

    # Both project X (600 mm) horizontally, so the viewBox width agrees.
    assert view_w_y == pytest.approx(view_w_z)
    # axis=Y draws Z (900 mm) vertical; axis=Z draws Y (300 mm) vertical. The
    # title band and legend band are identical (same boards, same
    # materials), so the whole height difference is attributable to the
    # swapped vertical extent.
    assert (view_h_y - view_h_z) == pytest.approx(unit.size_mm.z_mm - unit.size_mm.y_mm)


def test_axis_override_wins_over_a_conflicting_depth_axis() -> None:
    conflicting = _unit_with_distinct_dims(depth_axis=Axis.Z)
    overridden_document = to_svg(
        conflicting, solve(conflicting, CATALOG), CATALOG, axis=Axis.Y
    )

    reference = _unit_with_distinct_dims(depth_axis=Axis.Y)
    reference_document = to_svg(reference, solve(reference, CATALOG), CATALOG)

    # axis=Y overrides depth_axis=Z, so both project the same axis pair and
    # their viewBoxes agree despite the differing depth_axis.
    assert _view_box(overridden_document) == _view_box(reference_document)


def test_rendering_the_same_unit_twice_is_identical() -> None:
    unit = _closed_unit()
    spaces = solve(unit, CATALOG)
    assert to_svg(unit, spaces, CATALOG) == to_svg(unit, spaces, CATALOG)


def test_rendering_the_same_fixture_scanned_twice_from_scratch_is_identical() -> None:
    """Rendering one shared ``Unit``/``Space`` map twice (as the test above
    does) is true for any pure function and would not catch output that
    depends on iteration order of a ``set`` or unordered ``dict``, because
    such a set iterates the same way twice in one process. Scanning the
    fixture twice gives each render its own fresh ``uuid4`` node ids and its
    own freshly-inserted catalog dict, so this fails if legend colour
    assignment or the walk ever starts depending on that incidental order
    rather than tree order and first-appearance order."""

    def render() -> str:
        boxes, skipped = export_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
        catalog = _catalog_from_thicknesses(boxes)
        result = scan(boxes, catalog, skipped=skipped, snap_mm=0.1)
        spaces = solve(result.unit, catalog)
        return to_svg(result.unit, spaces, catalog)

    assert render() == render()


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


def test_board_insets_render_at_their_inset_extent_on_both_projected_axes() -> None:
    insets = Insets(x_min_mm=10.0, x_max_mm=10.0, z_min_mm=5.0, z_max_mm=5.0)
    plain = _unit_with_shelf_insets(Insets())
    inset = _unit_with_shelf_insets(insets)
    plain_document = to_svg(plain, solve(plain, CATALOG), CATALOG)
    inset_document = to_svg(inset, solve(inset, CATALOG), CATALOG)

    plain_rect = next(r for r in _rects(plain_document) if r.get("class") == "board")
    inset_rect = next(r for r in _rects(inset_document) if r.get("class") == "board")
    plain_x, plain_y, plain_w, plain_h = (
        float(plain_rect.get(attr, "")) for attr in ("x", "y", "width", "height")
    )
    inset_x, inset_y, inset_w, inset_h = (
        float(inset_rect.get(attr, "")) for attr in ("x", "y", "width", "height")
    )

    # Horizontal (X) is not flipped: the low inset shifts x right by exactly
    # x_min_mm, and the width shrinks by x_min_mm + x_max_mm.
    assert inset_x == pytest.approx(plain_x + insets.x_min_mm)
    assert inset_w == pytest.approx(plain_w - insets.x_min_mm - insets.x_max_mm)
    # Vertical (Z) is flipped about the unit's height: the low (bottom)
    # inset still shifts y down by z_min_mm, because the flip and the
    # height shrink cancel one of the two terms that would otherwise apply.
    assert inset_y == pytest.approx(plain_y + insets.z_min_mm)
    assert inset_h == pytest.approx(plain_h - insets.z_min_mm - insets.z_max_mm)


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


def test_real_stair_step_renders_end_to_end_with_a_void() -> None:
    boxes, skipped = export_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    catalog = _catalog_from_thicknesses(boxes)
    # Two of this fixture's real thicknesses (18.0086 mm, 18.2626 mm) are only
    # 0.25 mm apart, closer together than scan's default 0.5 mm snap; a tight
    # snap here keeps each board matching its own catalog entry rather than
    # its neighbour's, which a solve downstream depends on to balance exactly.
    result = scan(boxes, catalog, skipped=skipped, snap_mm=0.1)
    spaces = solve(result.unit, catalog)
    document = to_svg(result.unit, spaces, catalog)
    assert ET.fromstring(document).tag == SVG_TAG
    assert any(r.get("class") == "void" for r in _rects(document))


def test_real_magicstart_f1_renders_end_to_end_with_its_plinth_void() -> None:
    boxes, skipped = export_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    catalog = _catalog_from_thicknesses(boxes)
    result = scan(boxes, catalog, skipped=skipped, snap_mm=0.1)
    spaces = solve(result.unit, catalog)
    document = to_svg(result.unit, spaces, catalog)
    assert ET.fromstring(document).tag == SVG_TAG
    assert any(r.get("class") == "void" for r in _rects(document))
