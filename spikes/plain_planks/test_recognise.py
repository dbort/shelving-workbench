"""Spike tests: recognise round-trips ``expand``'s output and refuses non-trees.

Run with ``python -m pytest spikes`` from the repository root; ``pixi run
tests`` does not include this directory.
"""

import pytest

from shelving_core.expand import PlankSpec, expand
from shelving_core.layout import (
    Bay,
    Carcass,
    Divider,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
)
from shelving_core.materials import Catalog, MaterialEntry, MaterialId
from shelving_core.solver import solve
from spikes.plain_planks.recognise import (
    Box,
    CutSplit,
    Open,
    Outside,
    RecogniseError,
    boxes_from_specs,
    recognise,
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
    rec = recognise(boxes_from_specs(specs))
    recovered = to_carcass(rec, MATERIAL_FOR_THICKNESS)
    assert _shape(recovered.root) == _shape(original.root)
    assert _plank_set(expand(recovered, CATALOG)) == _plank_set(specs)


def test_rule_recovery_fill_for_equal_siblings_fixed_otherwise() -> None:
    equal = to_carcass(
        recognise(
            boxes_from_specs(expand(SAMPLE_TREES["three_fill_shelves"], CATALOG))
        ),
        MATERIAL_FOR_THICKNESS,
    )
    assert isinstance(equal.root, Split)
    assert all(isinstance(rule, Fill) for rule in equal.root.rules)

    unequal = to_carcass(
        recognise(boxes_from_specs(expand(SAMPLE_TREES["unequal_shelves"], CATALOG))),
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


def test_woodworking_cabinet_recognises_with_clearance_and_panels() -> None:
    rec = recognise(_woodworking_f0())
    assert sorted(p.name for p in rec.panels) == ["Back", "Front"]
    root = rec.root
    assert isinstance(root, CutSplit)
    assert [c.plank.name for c in root.cuts] == ["Floor", "Top"]
    middle = root.strips[1]
    assert isinstance(middle, CutSplit)
    assert [c.plank.name for c in middle.cuts] == ["Left", "Right"]
    inner = middle.strips[1]
    assert isinstance(inner, CutSplit)
    (shelf,) = inner.cuts
    assert shelf.plank.name == "Shelf"
    assert (shelf.clearance_lo_mm, shelf.clearance_hi_mm) == (1.0, 1.0)
    assert all(isinstance(s, Open) for s in inner.strips)

    # The carcass depth is the floor's: 382 mm behind an 18 mm front panel.
    assert rec.y0_mm == 18.0
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


def test_stair_step_recognises_with_outside_leaves() -> None:
    rec = recognise(_stair_step())
    root = rec.root
    assert isinstance(root, CutSplit)
    assert root.orientation is Orientation.HORIZONTAL
    assert [c.plank.name for c in root.cuts] == ["Floor"]
    assert root.strips[0] is None
    columns = root.strips[1]
    assert isinstance(columns, CutSplit)
    assert columns.orientation is Orientation.VERTICAL
    assert [c.plank.name for c in columns.cuts] == ["Left", "Riser1", "Riser2", "Right"]
    assert columns.strips[0] is None and columns.strips[4] is None
    expected_above = [None, Outside, Outside]
    tops = ["Top1", "Top2", "Top3"]
    for strip, top_name, above in zip(
        columns.strips[1:4], tops, expected_above, strict=True
    ):
        assert isinstance(strip, CutSplit)
        assert strip.orientation is Orientation.HORIZONTAL
        assert [c.plank.name for c in strip.cuts] == [top_name]
        assert isinstance(strip.strips[0], Open)
        if above is None:
            assert strip.strips[1] is None
        else:
            assert isinstance(strip.strips[1], above)


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
    with pytest.raises(RecogniseError, match="not a tree") as info:
        recognise(pinwheel)
    assert sorted(info.value.objects) == ["A", "B", "C", "D"]


def test_overlap_is_refused_naming_both() -> None:
    boxes = _closed_box(
        [
            _box("ShelfA", (18.0, 0.0, 400.0), (964.0, 300.0, 18.0)),
            _box("ShelfB", (18.0, 0.0, 410.0), (964.0, 300.0, 18.0)),
        ]
    )
    with pytest.raises(RecogniseError, match="overlaps") as info:
        recognise(boxes)
    assert sorted(info.value.objects) == ["ShelfA", "ShelfB"]


def test_gap_wider_than_clearance_is_refused() -> None:
    boxes = _closed_box([_box("Floating", (30.0, 0.0, 400.0), (940.0, 300.0, 18.0))])
    with pytest.raises(RecogniseError, match="full span") as info:
        recognise(boxes)
    assert info.value.objects == ("Floating",)
    # The same shelf recognises when the clearance tolerance admits the gap.
    rec = recognise(boxes, clearance_mm=12.0)
    assert isinstance(rec.root, CutSplit)


def test_square_section_plank_is_refused() -> None:
    boxes = _closed_box([_box("Post", (18.0, 0.0, 18.0), (50.0, 300.0, 50.0))])
    with pytest.raises(RecogniseError, match="thin axis") as info:
        recognise(boxes)
    assert info.value.objects == ("Post",)


def test_leaky_shell_is_refused() -> None:
    d = 300.0
    boxes = [
        _box("Bottom", (0.0, 0.0, 0.0), (1000.0, d, 18.0)),
        _box("ShortTop", (0.0, 0.0, 982.0), (900.0, d, 18.0)),
        _box("LeftSide", (0.0, 0.0, 18.0), (18.0, d, 964.0)),
        _box("RightSide", (982.0, 0.0, 18.0), (18.0, d, 964.0)),
    ]
    with pytest.raises(RecogniseError, match="no enclosed bay"):
        recognise(boxes)


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
    recovered = to_carcass(recognise(boxes_from_specs(specs)), MATERIAL_FOR_THICKNESS)
    assert _shape(recovered.root) == _shape(original.root)
    assert _plank_set(expand(recovered, CATALOG)) == _plank_set(specs)
