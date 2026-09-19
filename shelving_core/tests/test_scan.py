"""Tests for scanning axis-aligned boxes into a region-tree ``Unit``."""

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from shelving_core.expand import BoardSpec, expand
from shelving_core.geometry import Vec3
from shelving_core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Item,
    Unit,
    Void,
)
from shelving_core.materials import Catalog, MaterialEntry, MaterialId
from shelving_core.scan import (
    Box,
    FacingEvidence,
    ScanError,
    Skipped,
    _contained,
    _elevate,
    _Elevated,
    _empty,
    _Grid,
    boxes_from_json,
    detect_depth_axis,
    export_from_json,
    infer_facing,
    scan,
)

PLY = MaterialId("ply18")
MDF = MaterialId("mdf12")
CATALOG = Catalog(
    entries={
        PLY: MaterialEntry(PLY, "ply 18", 18.0, "plywood"),
        MDF: MaterialEntry(MDF, "mdf 12", 12.0, "mdf"),
    }
)

FIXTURES = Path(__file__).parent / "fixtures"

REAL_STAIR_STEP = FIXTURES / "real_stair_step.boxes.json"
REAL_TWO_UNITS = FIXTURES / "real_two_units.boxes.json"
REAL_MAGICSTART_F1 = FIXTURES / "real_magicstart_f1.boxes.json"


def _box_json(
    name: str, corner: tuple[float, float, float], size: tuple[float, float, float]
) -> dict[str, object]:
    return {"name": name, "corner_mm": list(corner), "size_mm": list(size)}


def test_boxes_from_json_parses_real_stair_step() -> None:
    boxes = boxes_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    assert len(boxes) == 10
    assert all(isinstance(b, Box) for b in boxes)


def test_boxes_from_json_parses_real_magicstart_f1() -> None:
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    assert len(boxes) == 6


def test_boxes_from_json_parses_real_two_units() -> None:
    # 39 raw entries collapse to 28 distinct boxes; see the duplicate-collapse
    # test below for the reason.
    boxes = boxes_from_json(REAL_TWO_UNITS.read_text(encoding="utf-8"))
    assert len(boxes) == 28


def test_duplicate_entries_collapse_on_real_two_units() -> None:
    """39 raw entries collapse to 28 distinct boxes: a selection can reach one
    object by more than one path through the container tree."""
    text = REAL_TWO_UNITS.read_text(encoding="utf-8")
    assert len(json.loads(text)["boxes"]) == 39
    assert len(boxes_from_json(text)) == 28


def test_export_from_json_carries_skipped_parts() -> None:
    boxes, skipped = export_from_json(REAL_TWO_UNITS.read_text(encoding="utf-8"))
    assert len(boxes) == 28
    assert [s.name for s in skipped] == ["Sketch006", "Pad003"]
    assert all(isinstance(s, Skipped) for s in skipped)


def test_conflicting_duplicate_names_raise() -> None:
    clashing = json.dumps(
        {
            "boxes": [
                _box_json("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
                _box_json("Shelf", (9.0, 9.0, 9.0), (1.0, 1.0, 1.0)),
            ]
        }
    )
    with pytest.raises(ValueError, match="both named 'Shelf'"):
        boxes_from_json(clashing)


def test_identical_duplicate_names_collapse() -> None:
    identical = json.dumps(
        {
            "boxes": [
                _box_json("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
                _box_json("Shelf", (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)),
            ]
        }
    )
    assert len(boxes_from_json(identical)) == 1


def test_scan_error_carries_offending_object_names() -> None:
    err = ScanError("two boards overlap", ["A", "B"])
    assert err.objects == ("A", "B")


def _uniform_depth_boxes() -> list[Box]:
    """A closed rectangle with every member the same depth: no panels, no
    inset difference, so nothing distinguishes the two faces."""
    return [
        _box("Left", (0.0, 0.0, 0.0), (18.0, 300.0, 600.0)),
        _box("Right", (582.0, 0.0, 0.0), (18.0, 300.0, 600.0)),
        _box("Bottom", (0.0, 0.0, 0.0), (600.0, 300.0, 18.0)),
        _box("Top", (0.0, 0.0, 582.0), (600.0, 300.0, 18.0)),
    ]


def _box(
    name: str, corner: tuple[float, float, float], size: tuple[float, float, float]
) -> Box:
    return Box(name=name, corner_mm=Vec3(*corner), size_mm=Vec3(*size))


def test_detect_depth_axis_picks_the_smallest_bounding_box_extent() -> None:
    assert detect_depth_axis(_uniform_depth_boxes()) is Axis.Y


def _six_sided_shell(
    width_mm: float = 600.0,
    depth_mm: float = 400.0,
    height_mm: float = 300.0,
    thickness_mm: float = 18.0,
) -> list[Box]:
    """A fully enclosed shell: a wall on every face, so any axis is a valid
    depth axis and scanning still finds an enclosed bay whichever one a
    caller picks."""
    t_mm = thickness_mm
    return [
        _box("Left", (0.0, 0.0, 0.0), (t_mm, depth_mm, height_mm)),
        _box("Right", (width_mm - t_mm, 0.0, 0.0), (t_mm, depth_mm, height_mm)),
        _box("Bottom", (t_mm, 0.0, 0.0), (width_mm - 2 * t_mm, depth_mm, t_mm)),
        _box(
            "Top",
            (t_mm, 0.0, height_mm - t_mm),
            (width_mm - 2 * t_mm, depth_mm, t_mm),
        ),
        _box(
            "Front",
            (t_mm, 0.0, t_mm),
            (width_mm - 2 * t_mm, t_mm, height_mm - 2 * t_mm),
        ),
        _box(
            "Back",
            (t_mm, depth_mm - t_mm, t_mm),
            (width_mm - 2 * t_mm, t_mm, height_mm - 2 * t_mm),
        ),
    ]


def test_explicit_depth_axis_changes_which_axis_the_tree_divides_along() -> None:
    """``detect_depth_axis`` would pick Z, the shell's smallest extent; an
    explicit ``depth_axis=Axis.Y`` overrides that, setting aside the Front
    and Back panels instead of Bottom and Top, and the inner division cuts
    along Z instead of Y."""
    boxes = _six_sided_shell()
    assert detect_depth_axis(boxes) is Axis.Z

    default = scan(boxes, CATALOG)
    assert default.unit.depth_axis is Axis.Z
    assert sorted(p.name for p in default.panels) == ["Bottom", "Top"]
    default_root = default.unit.root
    assert isinstance(default_root, Division)
    default_inner = default_root.items[1]
    assert isinstance(default_inner, Division)
    assert default_inner.axis is Axis.Y

    override = scan(boxes, CATALOG, depth_axis=Axis.Y)
    assert override.unit.depth_axis is Axis.Y
    assert sorted(p.name for p in override.panels) == ["Back", "Front"]
    override_root = override.unit.root
    assert isinstance(override_root, Division)
    override_inner = override_root.items[1]
    assert isinstance(override_inner, Division)
    assert override_inner.axis is Axis.Z


def test_uniform_depth_leaves_facing_undetermined() -> None:
    boxes = _uniform_depth_boxes()
    front_at_min, evidence = infer_facing(boxes, detect_depth_axis(boxes))
    assert front_at_min is None
    assert evidence is FacingEvidence.NONE


def test_magicstart_fixture_infers_front_at_min_from_its_overlay_back() -> None:
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    depth_axis = detect_depth_axis(boxes)
    assert depth_axis is Axis.Y
    front_at_min, evidence = infer_facing(boxes, depth_axis)
    assert front_at_min is True
    assert evidence is FacingEvidence.PANEL


def test_stock_thickness_back_flips_the_magicstart_facing() -> None:
    """The same panel at stock thickness reads as a door, which faces the
    opposite way from an overlay back."""
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    doored = [
        dataclasses.replace(b, size_mm=Vec3(b.size_mm.x_mm, 18.0, b.size_mm.z_mm))
        if b.name == "Back"
        else b
        for b in boxes
    ]
    front_at_min, evidence = infer_facing(doored, detect_depth_axis(doored))
    assert front_at_min is False
    assert evidence is FacingEvidence.PANEL


def test_stair_step_fixture_infers_facing_from_the_inset() -> None:
    boxes = boxes_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    depth_axis = detect_depth_axis(boxes)
    assert depth_axis is Axis.X
    front_at_min, evidence = infer_facing(boxes, depth_axis)
    assert front_at_min is True
    assert evidence is FacingEvidence.FLUSH_BACK


@pytest.mark.parametrize("front_at_min", [True, False])
def test_explicit_front_at_min_is_never_second_guessed(front_at_min: bool) -> None:
    """The magicStart fixture's overlay back infers front at the minimum end
    (``FacingEvidence.PANEL``); passing an explicit ``front_at_min``, in both
    directions, must come back verbatim with ``FacingEvidence.GIVEN`` rather
    than being recomputed from the geometry."""
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    result = scan(boxes, CATALOG, front_at_min=front_at_min)
    assert result.unit.front_at_min is front_at_min
    assert result.facing_evidence is FacingEvidence.GIVEN


def _closed_box(
    interior: list[Box],
    size_mm: float = 1000.0,
    thickness_mm: float = 18.0,
    depth_mm: float = 300.0,
) -> list[Box]:
    return [
        _box("Bottom", (0.0, 0.0, 0.0), (size_mm, depth_mm, thickness_mm)),
        _box(
            "Top",
            (0.0, 0.0, size_mm - thickness_mm),
            (size_mm, depth_mm, thickness_mm),
        ),
        _box(
            "LeftSide",
            (0.0, 0.0, thickness_mm),
            (thickness_mm, depth_mm, size_mm - 2 * thickness_mm),
        ),
        _box(
            "RightSide",
            (size_mm - thickness_mm, 0.0, thickness_mm),
            (thickness_mm, depth_mm, size_mm - 2 * thickness_mm),
        ),
        *interior,
    ]


def test_overlap_is_refused_naming_both() -> None:
    boxes = _closed_box(
        [
            _box("ShelfA", (18.0, 0.0, 400.0), (964.0, 300.0, 18.0)),
            _box("ShelfB", (18.0, 0.0, 410.0), (964.0, 300.0, 18.0)),
        ]
    )
    with pytest.raises(ScanError, match="overlaps") as info:
        scan(boxes, CATALOG)
    assert sorted(info.value.objects) == ["ShelfA", "ShelfB"]


def test_board_crossing_a_bay_boundary_is_refused() -> None:
    """The guillotine recursion never hands ``_contained`` a window a
    contained board straddles (every cut line it chooses is a face of every
    board inside the parent window), so this exercises the check directly:
    a caller asking whether board "A" is confined to a narrower window than
    its own face reaches into.
    """
    members = (
        _Elevated("A", 0.0, 70.0, 0.0, 18.0, 0.0, 300.0, Axis.Z, 18.0),
        _Elevated("B", 50.0, 90.0, 18.0, 118.0, 0.0, 300.0, Axis.X, 18.0),
    )
    grid = _Grid(members, 0.5)
    i0, i1 = grid.hs_mm.index(0.0), grid.hs_mm.index(50.0)
    j0, j1 = grid.vs_mm.index(0.0), grid.vs_mm.index(18.0)
    with pytest.raises(
        ScanError, match="crosses the boundary of the bay it lies in"
    ) as info:
        _contained(grid, i0, i1, j0, j1)
    assert info.value.objects == ("A",)


def test_pinwheel_is_refused_naming_the_cycle() -> None:
    thickness_mm, depth_mm = 18.0, 300.0
    pinwheel = _closed_box(
        [
            _box("A", (18.0, 0.0, 300.0), (582.0, depth_mm, thickness_mm)),
            _box("B", (600.0, 0.0, 18.0), (thickness_mm, depth_mm, 682.0)),
            _box("C", (400.0, 0.0, 700.0), (582.0, depth_mm, thickness_mm)),
            _box("D", (382.0, 0.0, 318.0), (thickness_mm, depth_mm, 664.0)),
        ]
    )
    with pytest.raises(ScanError, match="not a tree") as info:
        scan(pinwheel, CATALOG)
    assert sorted(info.value.objects) == ["A", "B", "C", "D"]


def test_partly_enclosed_partly_open_region_is_refused() -> None:
    """A caller may query any window, not only ones the recursion would
    naturally construct; this drives ``_empty`` directly with a window
    spanning a fully enclosed box and a separate, open-topped one, since the
    recursion itself never straddles two unrelated cavities with no board
    face between them to cut at.
    """
    boxes = [
        _box("L-Bottom", (0.0, 0.0, 0.0), (118.0, 300.0, 18.0)),
        _box("L-Top", (0.0, 0.0, 118.0), (118.0, 300.0, 18.0)),
        _box("L-Left", (0.0, 0.0, 18.0), (18.0, 300.0, 100.0)),
        _box("L-Right", (100.0, 0.0, 18.0), (18.0, 300.0, 100.0)),
        _box("R-Bottom", (1000.0, 0.0, 0.0), (118.0, 300.0, 18.0)),
        _box("R-Left", (1000.0, 0.0, 18.0), (18.0, 300.0, 100.0)),
        _box("R-Right", (1082.0, 0.0, 18.0), (18.0, 300.0, 100.0)),
    ]
    elevated = tuple(_elevate(b, Axis.X, Axis.Z, Axis.Y) for b in boxes)
    grid = _Grid(elevated, 0.5)
    i0, i1 = grid.hs_mm.index(18.0), grid.hs_mm.index(1082.0)
    j0, j1 = grid.vs_mm.index(18.0), grid.vs_mm.index(118.0)
    with pytest.raises(ScanError, match="partly enclosed and partly open"):
        _empty(grid, i0, i1, j0, j1)


def test_no_enclosed_bay_is_refused() -> None:
    depth_mm = 300.0
    boxes = [
        _box("Bottom", (0.0, 0.0, 0.0), (1000.0, depth_mm, 18.0)),
        _box("ShortTop", (0.0, 0.0, 982.0), (900.0, depth_mm, 18.0)),
        _box("LeftSide", (0.0, 0.0, 18.0), (18.0, depth_mm, 964.0)),
        _box("RightSide", (982.0, 0.0, 18.0), (18.0, depth_mm, 964.0)),
    ]
    with pytest.raises(ScanError, match="no enclosed bay"):
        scan(boxes, CATALOG)


def test_square_section_box_is_refused() -> None:
    boxes = _closed_box([_box("Post", (18.0, 0.0, 18.0), (50.0, 300.0, 50.0))])
    with pytest.raises(ScanError, match="no single thin axis") as info:
        scan(boxes, CATALOG)
    assert info.value.objects == ("Post",)


def test_thickness_matching_no_catalog_entry_is_refused() -> None:
    wrong_catalog = Catalog(
        entries={PLY: MaterialEntry(PLY, "ply 12", 12.0, "plywood")}
    )
    boxes = _closed_box([])
    with pytest.raises(ScanError, match="no material has thickness") as info:
        scan(boxes, wrong_catalog)
    assert info.value.objects == ("Bottom",)


def _shape(region: Bay | Division | Void) -> object:
    if isinstance(region, Bay):
        return "Bay"
    if isinstance(region, Void):
        return "Void"

    def item_shape(item: Item) -> object:
        return item.role if isinstance(item, Board) else _shape(item)

    return (region.axis.value, tuple(item_shape(item) for item in region.items))


def test_missing_board_reports_its_bay_as_void_not_open_quietly() -> None:
    """A dropped board does not fail a scan; it makes an enclosed bay read as
    open, which is why the missing board must be reported in ``skipped``
    rather than the scan simply succeeding as if the unit had fewer bays."""

    def shape(with_top: bool) -> list[Box]:
        boxes = [
            _box("Bottom", (0.0, 0.0, 0.0), (1000.0, 300.0, 18.0)),
            _box("LeftSide", (0.0, 0.0, 18.0), (18.0, 300.0, 964.0)),
            _box("RightSide", (982.0, 0.0, 18.0), (18.0, 300.0, 964.0)),
            _box("Shelf", (18.0, 0.0, 500.0), (964.0, 300.0, 18.0)),
        ]
        if with_top:
            boxes.append(_box("Top", (0.0, 0.0, 982.0), (1000.0, 300.0, 18.0)))
        return boxes

    complete = scan(shape(True), CATALOG)
    missing_top = Skipped(
        name="Top", label="Top", type="Part::Box", reason="missing from export"
    )
    incomplete = scan(shape(False), CATALOG, skipped=[missing_top])

    assert incomplete.skipped == (missing_top,)
    complete_root = complete.unit.root
    incomplete_root = incomplete.unit.root
    assert isinstance(complete_root, Division)
    assert isinstance(incomplete_root, Division)
    complete_shelf_div = complete_root.items[1]
    incomplete_shelf_div = incomplete_root.items[1]
    assert isinstance(complete_shelf_div, Division)
    assert isinstance(incomplete_shelf_div, Division)
    complete_inner = complete_shelf_div.items[1]
    incomplete_inner = incomplete_shelf_div.items[1]
    assert isinstance(complete_inner, Division)
    assert isinstance(incomplete_inner, Division)
    assert _shape(complete_inner) == ("z", ("Bay", "Shelf", "Bay"))
    assert _shape(incomplete_inner) == ("z", ("Bay", "Shelf", "Void"))


def _b(role: str, material: MaterialId | None = None) -> Board:
    """A board whose id matches its role, so a scanned board's role (set
    from the ``Box.name`` scanning read, which is ``expand``'s ``node_id``,
    the board's id) can be compared directly against the hand-built role."""
    return Board(role=role, id=role, material=material)


def _closed_box_unit() -> Unit:
    """Four equal bays behind three shelves: the equal-siblings case."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1800.0),
        default_material=PLY,
        root=Division(
            axis=Axis.Z,
            items=[
                _b("bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        _b("left"),
                        Division(
                            axis=Axis.Z,
                            items=[
                                Bay(),
                                _b("shelf1"),
                                Bay(),
                                _b("shelf2"),
                                Bay(),
                                _b("shelf3"),
                                Bay(),
                            ],
                        ),
                        _b("right"),
                    ],
                ),
                _b("top"),
            ],
        ),
    )


def _stepped_unit() -> Unit:
    """A short column with open space above its top, captured as a ``Void``."""
    return Unit(
        size_mm=Vec3(1218.0, 300.0, 1200.0),
        default_material=PLY,
        root=Division(
            axis=Axis.Z,
            items=[
                _b("floor"),
                Division(
                    axis=Axis.X,
                    items=[
                        _b("left"),
                        Division(axis=Axis.Z, items=[Bay(), _b("top_left")]),
                        _b("mid"),
                        Division(axis=Axis.Z, items=[Bay(), _b("top_right"), Void()]),
                        _b("right"),
                    ],
                ),
            ],
        ),
    )


def _second_material_unit() -> Unit:
    """One MDF shelf splitting the interior into two unequal bays: the
    unequal-siblings case, and the second-material case together."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 1800.0),
        default_material=PLY,
        root=Division(
            axis=Axis.Z,
            items=[
                _b("bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        _b("left"),
                        Division(
                            axis=Axis.Z,
                            items=[
                                Bay(rule=Fixed(300.0, basis=Basis.CLEAR)),
                                _b("shelf", material=MDF),
                                Bay(rule=Fill()),
                            ],
                        ),
                        _b("right"),
                    ],
                ),
                _b("top"),
            ],
        ),
    )


ROUND_TRIP_UNITS = {
    "closed_box": _closed_box_unit,
    "stepped": _stepped_unit,
    "second_material": _second_material_unit,
}


def _board_multiset(
    specs: Sequence[BoardSpec],
) -> list[tuple[float, float, float, float, float, float]]:
    return sorted(
        (
            round(s.size.x_mm, 6),
            round(s.size.y_mm, 6),
            round(s.size.z_mm, 6),
            round(s.placement.x_mm, 6),
            round(s.placement.y_mm, 6),
            round(s.placement.z_mm, 6),
        )
        for s in specs
    )


def _region_rules(region: Bay | Void | Division) -> list[type[object]]:
    """Every non-``Board`` item's rule type, pre-order, for asserting the
    equal-siblings recovery separately from the shape comparison."""
    rules: list[type[object]] = []
    if isinstance(region, Division):
        for item in region.items:
            if not isinstance(item, Board):
                rules.append(type(item.rule))
                rules.extend(_region_rules(item))
    return rules


@pytest.mark.parametrize("name", sorted(ROUND_TRIP_UNITS))
def test_round_trip_reproduces_tree_shape_and_boards(name: str) -> None:
    original = ROUND_TRIP_UNITS[name]()
    specs = expand(original, CATALOG)
    boxes = [Box(name=s.node_id, corner_mm=s.placement, size_mm=s.size) for s in specs]

    result = scan(boxes, CATALOG)

    assert _shape(result.unit.root) == _shape(original.root)
    recovered_specs = expand(result.unit, CATALOG)
    assert _board_multiset(recovered_specs) == _board_multiset(specs)


def test_equal_siblings_recover_as_fill() -> None:
    original = _closed_box_unit()
    boxes = [
        Box(name=s.node_id, corner_mm=s.placement, size_mm=s.size)
        for s in expand(original, CATALOG)
    ]
    result = scan(boxes, CATALOG)
    # The outermost two levels have exactly one region sibling each (nothing
    # to compare against), then the four equal bays behind the three
    # shelves: those must recover as Fill, not Fixed at their solved size.
    assert _region_rules(result.unit.root) == [Fixed, Fixed, Fill, Fill, Fill, Fill]


def test_unequal_siblings_recover_as_fixed() -> None:
    original = _second_material_unit()
    boxes = [
        Box(name=s.node_id, corner_mm=s.placement, size_mm=s.size)
        for s in expand(original, CATALOG)
    ]
    result = scan(boxes, CATALOG)
    assert _region_rules(result.unit.root) == [Fixed, Fixed, Fixed, Fixed]


def test_thicknesses_mm_reports_every_distinct_board_thickness() -> None:
    """``_second_material_unit`` mixes 18 mm ply with a 12 mm MDF shelf, so
    the reported set must carry both rather than collapsing to one."""
    original = _second_material_unit()
    boxes = [
        Box(name=s.node_id, corner_mm=s.placement, size_mm=s.size)
        for s in expand(original, CATALOG)
    ]
    result = scan(boxes, CATALOG)
    assert result.thicknesses_mm == frozenset({18.0, 12.0})


def _kinds_names(division: Division) -> tuple[str, list[str]]:
    """One character per item (``P`` board, ``o`` open bay, ``x`` void,
    ``D`` nested division) plus the boards' roles in order, mirroring the
    spike's own ``_kinds``/``_names`` test helpers."""
    kinds = ""
    names: list[str] = []
    for item in division.items:
        if isinstance(item, Board):
            kinds += "P"
            names.append(item.role)
        elif isinstance(item, Bay):
            kinds += "o"
        elif isinstance(item, Void):
            kinds += "x"
        else:
            kinds += "D"
    return kinds, names


def _division(item: Item) -> Division:
    assert isinstance(item, Division)
    return item


def test_real_magicstart_f1_whole_tree() -> None:
    """Sides running the full height with floor, shelf and top captured
    between them, a 100 mm plinth ``Void`` below the floor, 1 mm insets on
    the shelf, the back in ``panels``, front at minimum depth."""
    boxes = boxes_from_json(REAL_MAGICSTART_F1.read_text(encoding="utf-8"))
    result = scan(boxes, CATALOG)

    assert [p.name for p in result.panels] == ["Back"]
    assert result.unit.depth_axis is Axis.Y
    assert result.unit.front_at_min is True
    assert result.facing_evidence is FacingEvidence.PANEL

    root = _division(result.unit.root)
    assert root.axis is Axis.X
    assert _kinds_names(root) == ("PDP", ["Left", "Right"])

    inner = _division(root.items[1])
    assert inner.axis is Axis.Z
    assert _kinds_names(inner) == ("xPoPoP", ["Floor", "Shelf", "Top"])
    plinth = inner.items[0]
    assert isinstance(plinth, Void)

    floor = inner.items[1]
    assert isinstance(floor, Board)
    assert (floor.insets.y_min_mm, floor.insets.y_max_mm) == (0.0, 3.0)

    shelf = inner.items[3]
    assert isinstance(shelf, Board)
    assert (shelf.insets.x_min_mm, shelf.insets.x_max_mm) == (1.0, 1.0)


def test_real_stair_step_whole_tree() -> None:
    """A top board over everything, three uprights under it, ``Void`` below
    each step, and the two inner shelves under their own divider."""
    boxes = boxes_from_json(REAL_STAIR_STEP.read_text(encoding="utf-8"))
    result = scan(boxes, CATALOG)

    root = _division(result.unit.root)
    assert root.axis is Axis.Z
    assert _kinds_names(root) == ("DP", ["panelYX"])

    columns = _division(root.items[0])
    assert columns.axis is Axis.Y
    assert _kinds_names(columns) == (
        "PDPDP",
        ["panelZX012", "panelZX007", "panelZX008"],
    )

    left = _division(columns.items[1])
    assert left.axis is Axis.Z
    assert _kinds_names(left) == ("xPo", ["Shelf015"])
    assert isinstance(left.items[0], Void)

    right = _division(columns.items[3])
    assert right.axis is Axis.Z
    assert _kinds_names(right) == ("xPDPo", ["panelYX003", "Shelf013"])
    assert isinstance(right.items[0], Void)

    middle = _division(right.items[2])
    assert middle.axis is Axis.Y
    assert _kinds_names(middle) == ("DPD", ["panelZX011"])
    shelves = ["Shelf014", "Shelf016"]
    for item, shelf_name in zip(middle.items[0::2], shelves, strict=True):
        sub = _division(item)
        assert sub.axis is Axis.Z
        assert _kinds_names(sub) == ("oPo", [shelf_name])


def test_real_two_units_whole_tree() -> None:
    """Both seams present as adjacent ``Board`` items, the units' two top
    boards side by side, and the notched panel appearing in ``skipped``
    rather than as a board."""
    boxes, skipped = export_from_json(REAL_TWO_UNITS.read_text(encoding="utf-8"))
    result = scan(boxes, CATALOG, skipped=skipped)

    assert [s.name for s in result.skipped] == ["Sketch006", "Pad003"]

    root = _division(result.unit.root)
    assert root.axis is Axis.Z
    assert _kinds_names(root) == ("PDD", ["panelFaceYX"])

    tops = _division(root.items[2])
    assert tops.axis is Axis.Y
    # Together the two units' top boards span the width; neither spans it
    # alone, so they show up as two adjacent Board items, not one.
    assert _kinds_names(tops) == ("PP", ["panelYX", "panelYX004"])

    body = _division(root.items[1])
    assert body.axis is Axis.Y
    assert _kinds_names(body) == ("xDPPDP", ["panelZX008", "panelZX001", "panelZX"])
    # The seam: one unit's side and the next unit's side, touching.
    left_side, right_side = body.items[2], body.items[3]
    assert isinstance(left_side, Board) and left_side.role == "panelZX008"
    assert isinstance(right_side, Board) and right_side.role == "panelZX001"


def _find_pad(nodes: list[dict[str, object]]) -> dict[str, object] | None:
    for node in nodes:
        if node.get("type") == "PartDesign::Pad":
            return node
        children = node.get("children")
        if isinstance(children, list):
            found = _find_pad(children)
            if found is not None:
                return found
    return None


REAL_NOTCHED_PANEL = FIXTURES / "real_notched_panel.inspect.json"


def test_real_notched_panel_reads_as_skipped() -> None:
    """The inspection record of a notched panel: a box with a rectangular
    bite taken out of it, which ``export_boxes.py`` would list under
    ``skipped`` rather than export as a ``Box``, because it is a PartDesign
    solid, not a ``Part::Box``."""
    nodes = json.loads(REAL_NOTCHED_PANEL.read_text(encoding="utf-8"))
    pad = _find_pad(nodes)
    assert pad is not None
    solid = pad["solid"]
    assert isinstance(solid, dict)
    assert solid["is_plain_box"] is False
    assert solid["is_box_minus_boxes"] is True

    skipped = Skipped(
        name=str(pad["name"]),
        label=str(pad["label"]),
        type=str(pad["type"]),
        reason="a PartDesign solid, not a Part::Box",
    )
    assert skipped == Skipped(
        name="Pad003",
        label="panel2pad",
        type="PartDesign::Pad",
        reason="a PartDesign solid, not a Part::Box",
    )
