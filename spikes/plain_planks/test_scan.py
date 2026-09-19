"""Spike tests: scan round-trips ``expand``'s output and refuses non-trees.

Run with ``python -m pytest spikes`` from the repository root; ``pixi run
tests`` does not include this directory.
"""

import json
from pathlib import Path

import pytest

from shelving_core.layout import Fill, Fixed
from shelving_core.materials import Catalog, MaterialEntry, MaterialId
from spikes.plain_planks.carcass_model import (
    Bay,
    Carcass,
    Divider,
    Leaf,
    Orientation,
    PlankSpec,
    Split,
    expand,
    solve,
)
from spikes.plain_planks.scan import (
    Box,
    Cut,
    Divide,
    FacingEvidence,
    Open,
    Outside,
    Plane,
    ScanError,
    _snap_lines,
    boxes_from_json,
    boxes_from_specs,
    detect_axes,
    export_from_json,
    scan,
    thicknesses,
    to_carcass,
)

PLY18 = MaterialId("ply18")
MDF12 = MaterialId("mdf12")
CATALOG = Catalog(
    entries={
        PLY18: MaterialEntry(PLY18, "ply 18", 18.0, "plywood"),
        MDF12: MaterialEntry(MDF12, "mdf 12", 12.0, "mdf"),
    }
)
MATERIAL_FOR_THICKNESS = {18.0: PLY18, 12.0: MDF12}


def _plank_set(specs: list[PlankSpec]) -> list[tuple[str, tuple[float, ...]]]:
    return sorted(
        (
            spec.role.value,
            tuple(
                round(v, 6)
                for v in (
                    spec.size.x_mm,
                    spec.size.y_mm,
                    spec.size.z_mm,
                    spec.placement.x_mm,
                    spec.placement.y_mm,
                    spec.placement.z_mm,
                )
            ),
        )
        for spec in specs
    )


def _shape(bay: Bay) -> object:
    if isinstance(bay, Leaf):
        return "leaf"
    return (bay.orientation.value, tuple(_shape(child) for child in bay.children))


def _names(node: Divide) -> list[str]:
    """Plank names in item order, for asserting a split's shape."""
    return [i.plank.name for i in node.items if isinstance(i, Cut)]


def _kinds(node: Divide) -> str:
    """One character per item in order: P for a plank, o for an open bay,
    x for an outside region, D for a nested split."""
    out = ""
    for item in node.items:
        if isinstance(item, Cut):
            out += "P"
        elif isinstance(item, Open):
            out += "o"
        elif isinstance(item, Outside):
            out += "x"
        else:
            out += "D"
    return out


def _box(
    name: str, corner: tuple[float, float, float], size: tuple[float, float, float]
) -> Box:
    return Box(name=name, corner_mm=corner, size_mm=size)


def _carcass(root: Bay, width_mm: float = 900.0, height_mm: float = 1800.0) -> Carcass:
    return Carcass(
        width_mm=width_mm,
        height_mm=height_mm,
        depth_mm=300.0,
        default_material=PLY18,
        root=root,
    )


SAMPLE_TREES = {
    "leaf": _carcass(Leaf()),
    "three_fill_shelves": _carcass(
        Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf(), Leaf(), Leaf()],
            rules=[Fill(), Fill(), Fill(), Fill()],
            dividers=[Divider(), Divider(), Divider()],
        )
    ),
    "nested_mixed_material": _carcass(
        Split(
            orientation=Orientation.VERTICAL,
            children=[
                Leaf(),
                Split(
                    orientation=Orientation.HORIZONTAL,
                    children=[Leaf(), Leaf()],
                    rules=[Fill(), Fill()],
                    dividers=[Divider(material=MDF12)],
                ),
            ],
            rules=[Fixed(size_mm=300.0), Fill()],
            dividers=[Divider()],
        )
    ),
    "unequal_shelves": _carcass(
        Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf(), Leaf()],
            rules=[Fixed(size_mm=200.0), Fixed(size_mm=350.0), Fill()],
            dividers=[Divider(), Divider()],
        )
    ),
}


@pytest.mark.parametrize("name", sorted(SAMPLE_TREES))
def test_round_trip_reproduces_planks_and_topology(name: str) -> None:
    original = SAMPLE_TREES[name]
    specs = expand(original, CATALOG)
    rec = scan(boxes_from_specs(specs))
    recovered = to_carcass(rec, MATERIAL_FOR_THICKNESS)
    assert _shape(recovered.root) == _shape(original.root)
    assert _plank_set(expand(recovered, CATALOG)) == _plank_set(specs)


def test_rule_recovery_fill_for_equal_siblings_fixed_otherwise() -> None:
    equal = to_carcass(
        scan(boxes_from_specs(expand(SAMPLE_TREES["three_fill_shelves"], CATALOG))),
        MATERIAL_FOR_THICKNESS,
    )
    assert isinstance(equal.root, Split)
    assert all(isinstance(rule, Fill) for rule in equal.root.rules)

    unequal = to_carcass(
        scan(boxes_from_specs(expand(SAMPLE_TREES["unequal_shelves"], CATALOG))),
        MATERIAL_FOR_THICKNESS,
    )
    assert isinstance(unequal.root, Split)
    assert all(isinstance(rule, Fixed) for rule in unequal.root.rules)

    # Resizing an all-fill unit keeps its openings equal; the recovered rules
    # drive the solver the way the original ones did.
    taller = Carcass(
        width_mm=equal.width_mm,
        height_mm=equal.height_mm + 400.0,
        depth_mm=equal.depth_mm,
        default_material=equal.default_material,
        root=equal.root,
    )
    layout = solve(taller, CATALOG)
    heights = {round(layout[child.id].height_mm, 6) for child in equal.root.children}
    assert len(heights) == 1


def _woodworking_f0() -> list[Box]:
    # magicStart createF0 with thick=18, back=3, front=18, 600 x 400 x 720,
    # edgeband 0, shelf inset 1 mm per side; see Tools/magicStart.py.
    return [
        _box("Floor", (0.0, 18.0, 0.0), (600.0, 382.0, 18.0)),
        _box("Left", (0.0, 18.0, 18.0), (18.0, 382.0, 684.0)),
        _box("Right", (582.0, 18.0, 18.0), (18.0, 382.0, 684.0)),
        _box("Back", (18.0, 397.0, 18.0), (564.0, 3.0, 684.0)),
        _box("Top", (0.0, 18.0, 702.0), (600.0, 382.0, 18.0)),
        _box("Front", (18.0, 0.0, 18.0), (564.0, 18.0, 684.0)),
        _box("Shelf", (19.0, 36.0, 351.0), (562.0, 361.0, 18.0)),
    ]


def test_woodworking_cabinet_scans_with_clearance_and_panels() -> None:
    rec = scan(_woodworking_f0())
    assert sorted(p.name for p in rec.panels) == ["Back", "Front"]
    root = rec.root
    assert isinstance(root, Divide)
    assert (_kinds(root), _names(root)) == ("PDP", ["Floor", "Top"])
    middle = root.items[1]
    assert isinstance(middle, Divide)
    assert (_kinds(middle), _names(middle)) == ("PDP", ["Left", "Right"])
    inner = middle.items[1]
    assert isinstance(inner, Divide)
    assert (_kinds(inner), _names(inner)) == ("oPo", ["Shelf"])
    # The shelf is held a millimetre off each side. That is a joint gap, not a
    # pair of one millimetre bays, so it stays a clearance on the plank.
    (shelf,) = inner.cuts
    assert (shelf.clearance_lo_mm, shelf.clearance_hi_mm) == (1.0, 1.0)

    # The carcass depth is the floor's: 382 mm behind an 18 mm front panel.
    assert rec.d0_mm == 18.0
    # A proud front panel and a set-in back both say the low-Y face is the
    # front, so +X runs to the viewer's right and left/right labels are safe.
    assert rec.plane == Plane(depth=1, horizontal=0, vertical=2, front_at_min=True)
    assert rec.plane.screen_right_sign == 1
    carcass = to_carcass(rec, MATERIAL_FOR_THICKNESS)
    assert (carcass.width_mm, carcass.height_mm, carcass.depth_mm) == (
        600.0,
        720.0,
        382.0,
    )
    assert isinstance(carcass.root, Split)
    assert all(isinstance(rule, Fill) for rule in carcass.root.rules)


def _stair_step() -> list[Box]:
    # Three 400 mm columns of heights 1200 / 900 / 600, 18 mm stock, 300 deep.
    # Floor runs through; sides and risers stand on it and run up to their
    # column's top; each top is captured between its two uprights.
    t = 18.0
    d = 300.0
    return [
        _box("Floor", (0.0, 0.0, 0.0), (1200.0, d, t)),
        _box("Left", (0.0, 0.0, t), (t, d, 1200.0 - t)),
        _box("Riser1", (400.0, 0.0, t), (t, d, 1200.0 - t)),
        _box("Riser2", (800.0, 0.0, t), (t, d, 900.0 - t)),
        _box("Right", (1200.0 - t, 0.0, t), (t, d, 600.0 - t)),
        _box("Top1", (t, 0.0, 1200.0 - t), (400.0 - t, d, t)),
        _box("Top2", (400.0 + t, 0.0, 900.0 - t), (400.0 - t, d, t)),
        _box("Top3", (800.0 + t, 0.0, 600.0 - t), (400.0 - 2 * t, d, t)),
    ]


def test_stair_step_scans_with_outside_leaves() -> None:
    rec = scan(_stair_step())
    root = rec.root
    assert isinstance(root, Divide)
    # A floor running through, then everything above it.
    assert (_kinds(root), _names(root)) == ("PD", ["Floor"])
    columns = root.items[1]
    assert isinstance(columns, Divide)
    assert columns.orientation is Orientation.VERTICAL
    assert _kinds(columns) == "PDPDPDP"
    assert _names(columns) == ["Left", "Riser1", "Riser2", "Right"]
    # Each column is a bay under its own top. The two shorter columns have
    # empty space above them, which is outside the unit rather than a bay.
    expected = [("oP", "Top1"), ("oPx", "Top2"), ("oPx", "Top3")]
    for item, (shape, top) in zip(columns.items[1::2], expected, strict=True):
        assert isinstance(item, Divide)
        assert (_kinds(item), _names(item)) == (shape, [top])


def _closed_box(
    interior: list[Box], size_mm: float = 1000.0, t: float = 18.0
) -> list[Box]:
    d = 300.0
    return [
        _box("Bottom", (0.0, 0.0, 0.0), (size_mm, d, t)),
        _box("Top", (0.0, 0.0, size_mm - t), (size_mm, d, t)),
        _box("LeftSide", (0.0, 0.0, t), (t, d, size_mm - 2 * t)),
        _box("RightSide", (size_mm - t, 0.0, t), (t, d, size_mm - 2 * t)),
        *interior,
    ]


def test_pinwheel_is_refused_naming_the_cycle() -> None:
    t = 18.0
    d = 300.0
    pinwheel = _closed_box(
        [
            _box("A", (18.0, 0.0, 300.0), (582.0, d, t)),
            _box("B", (600.0, 0.0, 18.0), (t, d, 682.0)),
            _box("C", (400.0, 0.0, 700.0), (582.0, d, t)),
            _box("D", (382.0, 0.0, 318.0), (t, d, 664.0)),
        ]
    )
    with pytest.raises(ScanError, match="not a tree") as info:
        scan(pinwheel)
    assert sorted(info.value.objects) == ["A", "B", "C", "D"]


def test_overlap_is_refused_naming_both() -> None:
    boxes = _closed_box(
        [
            _box("ShelfA", (18.0, 0.0, 400.0), (964.0, 300.0, 18.0)),
            _box("ShelfB", (18.0, 0.0, 410.0), (964.0, 300.0, 18.0)),
        ]
    )
    with pytest.raises(ScanError, match="overlaps") as info:
        scan(boxes)
    assert sorted(info.value.objects) == ["ShelfA", "ShelfB"]


def test_a_plank_that_reaches_nothing_still_partitions() -> None:
    """A shelf floating clear of both sides is a valid guillotine partition, so
    scanning accepts it and the gaps beside it come back as bays.

    A plank-span rule would refuse this; cutting at every line no plank
    crosses cannot: [gap, shelf, gap] is a legal split. Whether a plank
    reaches its neighbours is a question about the thing being buildable,
    not about the layout being a tree, and nothing here asks it.
    """
    boxes = _closed_box([_box("Floating", (30.0, 0.0, 400.0), (940.0, 300.0, 18.0))])
    root = scan(boxes).root
    assert isinstance(root, Divide)
    middle = root.items[1]
    assert isinstance(middle, Divide)
    # The 12 mm and 42 mm gaps beside the shelf read as bays, which is what a
    # user would see and question.
    assert _kinds(middle) == "PoDoP"
    gaps = [i for i in middle.items if isinstance(i, Open)]
    assert [round(g.rect.width_mm, 1) for g in gaps] == [12.0, 12.0]

    # Held off each side by less than the clearance, it is one plank again.
    close = _closed_box([_box("Shelf", (20.0, 0.0, 400.0), (960.0, 300.0, 18.0))])
    close_root = scan(close).root
    assert isinstance(close_root, Divide)
    sides = close_root.items[1]
    assert isinstance(sides, Divide)
    inner = sides.items[1]
    assert isinstance(inner, Divide)
    assert (_kinds(inner), _names(inner)) == ("oPo", ["Shelf"])


def test_square_section_plank_is_refused() -> None:
    boxes = _closed_box([_box("Post", (18.0, 0.0, 18.0), (50.0, 300.0, 50.0))])
    with pytest.raises(ScanError, match="thin axis") as info:
        scan(boxes)
    assert info.value.objects == ("Post",)


def test_leaky_shell_is_refused() -> None:
    d = 300.0
    boxes = [
        _box("Bottom", (0.0, 0.0, 0.0), (1000.0, d, 18.0)),
        _box("ShortTop", (0.0, 0.0, 982.0), (900.0, d, 18.0)),
        _box("LeftSide", (0.0, 0.0, 18.0), (18.0, d, 964.0)),
        _box("RightSide", (982.0, 0.0, 18.0), (18.0, d, 964.0)),
    ]
    with pytest.raises(ScanError, match="no enclosed bay"):
        scan(boxes)


def _grid_unit(cols: int, rows: int) -> Carcass:
    def column() -> Split:
        return Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf() for _ in range(rows)],
            rules=[Fill() for _ in range(rows)],
            dividers=[Divider() for _ in range(rows - 1)],
        )

    return Carcass(
        width_mm=400.0 * cols,
        height_mm=300.0 * rows + 200.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.VERTICAL,
            children=[column() for _ in range(cols)],
            rules=[Fill() for _ in range(cols)],
            dividers=[Divider() for _ in range(cols - 1)],
        ),
    )


@pytest.mark.parametrize(("cols", "rows"), [(3, 4), (6, 10), (8, 14)])
def test_round_trip_holds_at_scale(cols: int, rows: int) -> None:
    original = _grid_unit(cols, rows)
    specs = expand(original, CATALOG)
    recovered = to_carcass(scan(boxes_from_specs(specs)), MATERIAL_FOR_THICKNESS)
    assert _shape(recovered.root) == _shape(original.root)
    assert _plank_set(expand(recovered, CATALOG)) == _plank_set(specs)


REAL_UNIT = Path(__file__).parent / "real_stair_step.boxes.json"


def test_real_stair_step_unit_scans() -> None:
    """A stair-step unit modelled in the FreeCAD GUI with Woodworking tools.

    Exported by ``export_boxes.py`` from a real project. It is the case that
    found the plane assumption and the snap tolerance, so it stays a fixture.
    """
    rec = scan(boxes_from_json(REAL_UNIT.read_text(encoding="utf-8")))

    # Modelled on the YZ plane rather than XZ. It has no back and no front, so
    # the only facing hint is the inset: the shallow planks are flush at high
    # X, making that the rear.
    assert rec.plane == Plane(depth=0, horizontal=1, vertical=2, front_at_min=True)
    assert rec.facing_evidence is FacingEvidence.FLUSH_BACK
    # Front at low X puts increasing Y to the viewer's left, so the upright at
    # maximum Y is the left side.
    assert rec.plane.screen_right_sign == -1
    assert round(rec.bbox.width_mm, 1) == 1828.8
    assert round(rec.bbox.height_mm, 1) == 1498.6
    # Two stock thicknesses and two depths: 8.5 in planks set back from 11.5 in.
    assert sorted(thicknesses(rec)) == [18.0086, 18.2626]
    assert sorted(rec.depths_mm) == [215.9, 292.1]
    assert not rec.panels, "the unit has no back or front"

    # The top runs through above everything. Under it, three uprights: a short
    # side, a middle divider, and one that runs down past the rest as a leg.
    root = rec.root
    assert isinstance(root, Divide)
    assert (_kinds(root), _names(root)) == ("DP", ["panelYX"])

    columns = root.items[0]
    assert isinstance(columns, Divide)
    assert columns.orientation is Orientation.VERTICAL
    assert _kinds(columns) == "PDPDP"
    assert _names(columns) == ["panelZX012", "panelZX007", "panelZX008"]

    # Left step: open below, because the unit is stepped at the bottom.
    left = columns.items[1]
    assert isinstance(left, Divide)
    assert (_kinds(left), _names(left)) == ("xPo", ["Shelf015"])

    right = columns.items[3]
    assert isinstance(right, Divide)
    assert (_kinds(right), _names(right)) == ("xPDPo", ["panelYX003", "Shelf013"])

    middle = right.items[2]
    assert isinstance(middle, Divide)
    assert (_kinds(middle), _names(middle)) == ("DPD", ["panelZX011"])
    for item, shelf in zip(middle.items[0::2], ["Shelf014", "Shelf016"], strict=True):
        assert isinstance(item, Divide)
        assert (_kinds(item), _names(item)) == ("oPo", [shelf])


def test_real_unit_needs_the_looser_snap() -> None:
    """A 0.05 mm tolerance splits edges that a real model means to be
    coincident."""
    boxes = boxes_from_json(REAL_UNIT.read_text(encoding="utf-8"))
    with pytest.raises(ScanError):
        scan(boxes, snap_mm=0.05)


def test_snap_lines_do_not_chain() -> None:
    """A run of small steps must not merge into one wide cluster."""
    values = [0.0, 0.4, 0.8, 1.2, 1.6]
    assert len(_snap_lines(values, 0.5)) == 3


def test_facing_flips_which_end_is_left() -> None:
    """The same elevation reads mirrored from either side, so left and right
    are a property of the viewer, never of the geometry."""
    plane = Plane(depth=0, horizontal=1, vertical=2, front_at_min=True)
    assert plane.screen_right_sign == -1
    assert plane._replace(front_at_min=False).screen_right_sign == 1

    # An XZ elevation viewed from low Y is FreeCAD's front view: +X to the right.
    xz = Plane(depth=1, horizontal=0, vertical=2, front_at_min=True)
    assert xz.screen_right_sign == 1
    assert xz._replace(front_at_min=False).screen_right_sign == -1


def test_inset_front_is_the_only_facing_hint_in_the_real_unit() -> None:
    """The rear of a unit is flush and the front may be inset for looks, so the
    flush end is the back. It is a weak hint: it says nothing unless the plank
    depths differ, which most units' do not."""
    boxes = boxes_from_json(REAL_UNIT.read_text(encoding="utf-8"))
    rec = scan(boxes)
    shallow = [p for p in rec.planks if round(p.depth_mm, 1) == 215.9]
    deep = [p for p in rec.planks if round(p.depth_mm, 1) == 292.1]
    assert shallow and deep
    # Flush at the high-depth end, inset by three inches at the low-depth end.
    assert {round(p.d1_mm, 2) for p in shallow} == {round(p.d1_mm, 2) for p in deep}
    assert round(min(p.d0_mm for p in shallow) - min(p.d0_mm for p in deep), 1) == 76.2
    assert rec.plane.front_at_min is True


def test_uniform_depth_leaves_facing_undetermined() -> None:
    """The common case: every plank the same depth, no back and no front. The
    two faces are identical, so nothing says which one a person stands at."""
    for name in sorted(SAMPLE_TREES):
        rec = scan(boxes_from_specs(expand(SAMPLE_TREES[name], CATALOG)))
        assert rec.plane.front_at_min is None, name
        assert rec.facing_evidence is FacingEvidence.NONE, name
        assert rec.plane.screen_right_sign is None, name


def test_an_explicit_facing_is_never_second_guessed() -> None:
    """A stored or user-set facing wins over any heuristic."""
    boxes = boxes_from_json(REAL_UNIT.read_text(encoding="utf-8"))
    axes = detect_axes(boxes)
    for front_at_min in (True, False):
        rec = scan(boxes, plane=axes._replace(front_at_min=front_at_min))
        assert rec.plane.front_at_min is front_at_min
        assert rec.facing_evidence is FacingEvidence.GIVEN


def test_back_panel_alone_determines_facing() -> None:
    """One panel set within the members is a back, which fixes the front."""
    boxes = _closed_box([]) + [_box("Back", (18.0, 290.0, 18.0), (964.0, 10.0, 964.0))]
    rec = scan(boxes)
    assert rec.plane.front_at_min is True
    assert [p.name for p in rec.panels] == ["Back"]


REAL_CABINET = Path(__file__).parent / "real_magicstart_f1.boxes.json"


def test_real_magicstart_cabinet_scans() -> None:
    """A cabinet generated by Woodworking's magicStart, read from the saved
    document rather than reconstructed from its source.

    Its lap order is the opposite of the synthetic F0 fixture above, and both
    come out of the same tool, which is why lap order is read from geometry
    rather than assumed.
    """
    rec = scan(boxes_from_json(REAL_CABINET.read_text(encoding="utf-8")))
    assert rec.plane.depth == 1 and rec.plane.horizontal == 0
    assert [p.name for p in rec.panels] == ["Back"]

    root = rec.root
    assert isinstance(root, Divide)
    assert root.orientation is Orientation.VERTICAL
    # The sides run the full height, the floor and top are captured between
    # them: the opposite lap order to the synthetic F0 fixture above.
    assert (_kinds(root), _names(root)) == ("PDP", ["Left", "Right"])

    inner = root.items[1]
    assert isinstance(inner, Divide)
    assert inner.orientation is Orientation.HORIZONTAL
    # The 100 mm plinth gap below the floor is open to the outside, so it is
    # not a bay.
    assert (_kinds(inner), _names(inner)) == ("xPoPoP", ["Floor", "Shelf", "Top"])
    plinth = inner.items[0]
    assert isinstance(plinth, Outside)
    assert round(plinth.rect.height_mm, 1) == 100.0
    # The shelf carries magicStart's 1 mm clearance at each side.
    assert (inner.cuts[1].clearance_lo_mm, inner.cuts[1].clearance_hi_mm) == (1.0, 1.0)


def test_a_thin_proud_panel_is_a_back_not_a_door() -> None:
    """The real cabinet's 3 mm back sits proud behind the carcass. Read as a
    door it would put the front at the wrong end and mirror every label."""
    rec = scan(boxes_from_json(REAL_CABINET.read_text(encoding="utf-8")))
    assert rec.facing_evidence is FacingEvidence.PANEL
    assert rec.plane.front_at_min is True
    # Front at low Y with X across is FreeCAD's own front view.
    assert rec.plane.screen_right_sign == 1

    # A proud panel of stock thickness at the same place is a door, and says
    # the opposite.
    boxes = boxes_from_json(REAL_CABINET.read_text(encoding="utf-8"))
    doored = [
        Box(b.name, b.corner_mm, (b.size_mm[0], 18.0, b.size_mm[2]))
        if b.name == "Back"
        else b
        for b in boxes
    ]
    assert scan(doored).plane.front_at_min is False


REAL_TWO_UNITS = Path(__file__).parent / "real_two_units.boxes.json"


def test_two_abutting_units_scan_together() -> None:
    """Two units from one project whose side panels meet, exported from a loose
    selection rather than a tidy container.

    This is the case a plank-span rule cannot handle. Neither unit's top board
    spans the pair, and the seam between them is two side panels face to face,
    so no single plank cuts the whole. Cutting at every line no plank crosses
    handles it, and the seam shows up as two plank items in a row.
    """
    boxes, skipped = export_from_json(REAL_TWO_UNITS.read_text(encoding="utf-8"))
    root = scan(boxes).root
    assert isinstance(root, Divide)
    # A bottom board, the two units, and the slab holding both their tops.
    assert (_kinds(root), _names(root)) == ("PDD", ["panelFaceYX"])

    tops = root.items[2]
    assert isinstance(tops, Divide)
    assert (_kinds(tops), _names(tops)) == ("PP", ["panelYX", "panelYX004"])
    left_top, right_top = tops.items
    assert isinstance(left_top, Cut) and isinstance(right_top, Cut)
    # Together they span the width; neither spans it alone.
    assert left_top.plank.h1_mm == right_top.plank.h0_mm

    body = root.items[1]
    assert isinstance(body, Divide)
    assert body.orientation is Orientation.VERTICAL
    assert _kinds(body) == "xDPPDP"
    assert _names(body) == ["panelZX008", "panelZX001", "panelZX"]
    # The seam: one unit's side and the next unit's side, touching.
    left_side, right_side = body.items[2], body.items[3]
    assert isinstance(left_side, Cut) and isinstance(right_side, Cut)
    assert left_side.plank.h1_mm == right_side.plank.h0_mm

    # This export carries the notched panel as skipped and eleven planks twice
    # over. Both are handled on the way in.
    assert [s.name for s in skipped] == ["Sketch006", "Pad003"]
    assert len({b.name for b in boxes}) == len(boxes)


def test_duplicate_entries_collapse_but_conflicts_do_not() -> None:
    """A selection can reach one object by two paths, so the same Name may be
    exported twice. Identical entries are one plank; differing ones are an
    error rather than an overlap deeper in."""
    text = REAL_TWO_UNITS.read_text(encoding="utf-8")
    assert len(json.loads(text)["boxes"]) == 39
    assert len(boxes_from_json(text)) == 28

    clashing = json.dumps(
        {
            "boxes": [
                {"name": "Shelf", "corner_mm": [0, 0, 0], "size_mm": [1, 1, 1]},
                {"name": "Shelf", "corner_mm": [9, 9, 9], "size_mm": [1, 1, 1]},
            ]
        }
    )
    with pytest.raises(ValueError, match="both named 'Shelf'"):
        boxes_from_json(clashing)
