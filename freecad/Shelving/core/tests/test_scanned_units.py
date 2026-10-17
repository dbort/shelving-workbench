"""Units modeled outside this workbench, scanned from real exports: their
rules solve back to the measured boards and leave every edit somewhere to
go."""

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from freecad.Shelving.core.edit import move_board, set_size
from freecad.Shelving.core.expand import expand
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Item,
    Region,
    Unit,
    Void,
    Weighted,
)
from freecad.Shelving.core.scan import (
    DEFAULT_SNAP_MM,
    Box,
    _is_axis_wrap,
    _snap_lines,
    elevation_axes,
    export_from_json,
    scan,
)
from freecad.Shelving.core.solver import solve

FIXTURES = Path(__file__).parent / "fixtures"
_FIXTURE_NAMES = ("real_magicstart_f1", "real_stair_step", "real_two_units")


def _boxes(name: str) -> list[Box]:
    boxes, _skipped = export_from_json(
        (FIXTURES / f"{name}.boxes.json").read_text(encoding="utf-8")
    )
    return boxes


def _scanned(name: str) -> Unit:
    boxes, skipped = export_from_json(
        (FIXTURES / f"{name}.boxes.json").read_text(encoding="utf-8")
    )
    return scan(boxes, skipped=skipped).unit


def _component_mm(v: Vec3, axis: Axis) -> float:
    return {Axis.X: v.x_mm, Axis.Y: v.y_mm, Axis.Z: v.z_mm}[axis]


def _with_component_mm(v: Vec3, axis: Axis, value_mm: float) -> Vec3:
    return dataclasses.replace(v, **{f"{axis.value}_mm": value_mm})


def _divisions(region: Region) -> Iterator[Division]:
    if isinstance(region, Division):
        yield region
        for item in region.items:
            if not isinstance(item, Board):
                yield from _divisions(item)


def _boards(region: Region) -> Iterator[Board]:
    for division in _divisions(region):
        yield from (item for item in division.items if isinstance(item, Board))


def _regions(division: Division) -> list[Item]:
    return [
        item
        for item in division.items
        if not isinstance(item, Board) and not _is_axis_wrap(item)
    ]


def _sharing(division: Division) -> list[Item]:
    """The regions of ``division``'s run that share leftover space: its
    compartments, or its voids when it has no compartment."""
    regions = _regions(division)
    compartments: list[Item] = [item for item in regions if not isinstance(item, Void)]
    return compartments or regions


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_every_scanned_region_shares_space_in_proportion_to_its_size(
    name: str,
) -> None:
    """Only an axis-wrap division, and a void beside a compartment, is
    fixed. Each run's sharing regions are all ``Fill`` when they are all one
    size within the snap tolerance, and otherwise all ``Weighted`` by their
    scanned size."""
    unit = _scanned(name)
    spaces = solve(unit)
    for division in _divisions(unit.root):
        sharing = _sharing(division)
        for item in division.items:
            if _is_axis_wrap(item):
                assert isinstance(item.rule, Fixed)
            elif isinstance(item, Void) and item not in sharing:
                assert isinstance(item.rule, Fixed), item
                assert item.rule.size_mm == pytest.approx(
                    _component_mm(spaces[item.id].size, division.axis), abs=1e-6
                )
        if not sharing:
            continue
        sizes_mm = [
            _component_mm(spaces[item.id].size, division.axis) for item in sharing
        ]
        if max(sizes_mm) - min(sizes_mm) <= DEFAULT_SNAP_MM:
            assert all(isinstance(item.rule, Fill) for item in sharing)
            continue
        for item, size_mm in zip(sharing, sizes_mm, strict=True):
            assert isinstance(item, Bay | Void | Division)
            assert isinstance(item.rule, Weighted), item
            assert item.rule.weight == pytest.approx(size_mm, abs=1e-6)


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_a_scanned_unit_solves_back_to_its_measured_boards(name: str) -> None:
    """Every board's solved corner and size is within half the snap
    tolerance of the box it was measured from, in the unit's own frame."""
    boxes = {box.name: box for box in _boxes(name)}
    specs = expand(_scanned(name))
    first = specs[0]
    offset = Vec3(
        boxes[first.node_id].corner_mm.x_mm - first.placement.x_mm,
        boxes[first.node_id].corner_mm.y_mm - first.placement.y_mm,
        boxes[first.node_id].corner_mm.z_mm - first.placement.z_mm,
    )
    tolerance_mm = DEFAULT_SNAP_MM / 2 + 1e-9
    for spec in specs:
        box = boxes[spec.node_id]
        for axis in Axis:
            measured_corner_mm = _component_mm(box.corner_mm, axis) - _component_mm(
                offset, axis
            )
            assert _component_mm(spec.placement, axis) == pytest.approx(
                measured_corner_mm, abs=tolerance_mm
            ), (spec.node_id, axis)
            assert _component_mm(spec.size, axis) == pytest.approx(
                _component_mm(box.size_mm, axis), abs=tolerance_mm
            ), (spec.node_id, axis)


def test_two_side_by_side_tops_fill_their_run_exactly() -> None:
    """The two units' tops lie sideways in their run, so each carries its
    span as a rule. Their measured spans overrun the run by a fraction of a
    millimeter; their slot widths in the scan grid add up to it exactly."""
    boxes = {box.name: box for box in _boxes("real_two_units")}
    unit = _scanned("real_two_units")
    spaces = solve(unit)
    tops = next(
        division
        for division in _divisions(unit.root)
        if {item.id for item in division.items} == {"panelYX", "panelYX004"}
    )
    rules_mm = []
    measured_mm = []
    for top in tops.items:
        assert isinstance(top, Board) and isinstance(top.rule, Fixed)
        rules_mm.append(top.rule.size_mm)
        measured_mm.append(_component_mm(boxes[top.id].size_mm, tops.axis))
    run_mm = _component_mm(spaces[tops.id].size, tops.axis)
    assert sum(rules_mm) == pytest.approx(run_mm, abs=1e-9)
    assert abs(sum(measured_mm) - run_mm) > 1e-4


@pytest.mark.parametrize("name", ["real_stair_step", "real_two_units"])
def test_a_ruled_board_spans_its_slot_in_the_scan_grid(name: str) -> None:
    """A board lying across its run carries a rule whose size is the gap
    between two of the scan's snapped grid lines, the lines every sibling's
    size comes from, and its solved edges sit on those lines."""
    boxes = {box.name: box for box in _boxes(name)}
    unit = _scanned(name)
    spaces = solve(unit)
    placed = {spec.node_id for spec in expand(unit)}
    ruled = 0
    for division in _divisions(unit.root):
        axis = division.axis
        lines_mm = _snap_lines(
            [
                edge_mm
                for box_name in placed
                for edge_mm in (
                    _component_mm(boxes[box_name].corner_mm, axis),
                    _component_mm(boxes[box_name].corner_mm, axis)
                    + _component_mm(boxes[box_name].size_mm, axis),
                )
            ],
            DEFAULT_SNAP_MM,
        )
        for item in division.items:
            if not isinstance(item, Board) or item.rule is None:
                continue
            assert isinstance(item.rule, Fixed)
            ruled += 1
            low_mm = _component_mm(spaces[item.id].origin, axis)
            high_mm = low_mm + item.rule.size_mm
            assert min(abs(low_mm - line_mm) for line_mm in lines_mm) < 1e-6
            assert min(abs(high_mm - line_mm) for line_mm in lines_mm) < 1e-6
    assert ruled >= 2


def _first(region: Region, kind: type[Item], board_id: str = "") -> Item:
    for division in _divisions(region):
        for item in division.items:
            if isinstance(item, kind) and (not board_id or item.id == board_id):
                return item
    raise LookupError(kind)


def _thicknesses_hold(unit: Unit, spaces: dict[str, Space]) -> None:
    for division in _divisions(unit.root):
        for item in division.items:
            if isinstance(item, Board) and item.rule is None:
                assert _component_mm(
                    spaces[item.id].size, division.axis
                ) == pytest.approx(item.thickness_mm, abs=1e-6), item.id


def _resized(unit: Unit, axis: Axis, delta_mm: float) -> Unit:
    size_mm = unit.size_mm
    return dataclasses.replace(
        unit,
        size_mm=_with_component_mm(
            size_mm, axis, _component_mm(size_mm, axis) + delta_mm
        ),
    )


def _magic_start_column(unit: Unit) -> Division:
    """The column between the sides: plinth void, floor, lower bay, shelf,
    upper bay, top."""
    return next(
        division
        for division in _divisions(unit.root)
        if any(
            isinstance(item, Board) and item.id == "Shelf" for item in division.items
        )
    )


def test_magic_start_takes_a_typed_size_and_holds_its_floor() -> None:
    """The upper bay takes up the difference; the plinth gap, a void beside
    compartments, keeps its size, so the floor stays where it was."""
    unit = _scanned("real_magicstart_f1")
    lower_bay = [i for i in _magic_start_column(unit).items if isinstance(i, Bay)][0]
    floor_z_mm = solve(unit)["Floor"].origin.z_mm
    spaces = solve(set_size(unit, lower_bay.id, 300.0, Basis.CLEAR))
    assert spaces[lower_bay.id].size.z_mm == pytest.approx(300.0)
    assert spaces["Floor"].origin.z_mm == pytest.approx(floor_z_mm)


def test_magic_start_takes_a_shelf_drag() -> None:
    unit = _scanned("real_magicstart_f1")
    low_face_mm = solve(unit)["Shelf"].origin.z_mm + 30.0
    spaces = solve(move_board(unit, "Shelf", low_face_mm))
    assert spaces["Shelf"].origin.z_mm == pytest.approx(low_face_mm)


def test_magic_start_takes_a_thinner_shelf() -> None:
    unit = _scanned("real_magicstart_f1")
    column = _magic_start_column(unit)
    items = [
        dataclasses.replace(item, thickness_mm=12.0)
        if isinstance(item, Board) and item.id == "Shelf"
        else item
        for item in column.items
    ]
    thinner = dataclasses.replace(
        unit,
        root=_replaced(unit.root, column.id, dataclasses.replace(column, items=items)),
    )
    assert solve(thinner)["Shelf"].size.z_mm == pytest.approx(12.0)


def _replaced(region: Region, region_id: str, replacement: Region) -> Region:
    if region.id == region_id:
        return replacement
    if not isinstance(region, Division):
        return region
    return dataclasses.replace(
        region,
        items=[
            item if isinstance(item, Board) else _replaced(item, region_id, replacement)
            for item in region.items
        ],
    )


@pytest.mark.parametrize(
    ("name", "elevation_index"),
    [
        ("real_magicstart_f1", 1),
        ("real_magicstart_f1", 0),
        ("real_stair_step", 1),
        ("real_stair_step", 0),
        ("real_two_units", 1),
    ],
    ids=[
        "magic-start-taller",
        "magic-start-wider",
        "stair-step-taller",
        "stair-step-wider",
        "two-units-taller",
    ],
)
def test_a_scanned_unit_resizes_and_keeps_every_board_thickness(
    name: str, elevation_index: int
) -> None:
    """Grows the unit 40 mm along its horizontal (0) or vertical (1)
    elevation axis."""
    unit = _scanned(name)
    assert unit.depth_axis is not None
    axis = elevation_axes(unit.depth_axis)[elevation_index]
    resized = _resized(unit, axis, 40.0)
    spaces = dict(solve(resized))
    _thicknesses_hold(resized, spaces)


def test_magic_start_grows_taller_in_its_bays_and_keeps_its_plinth() -> None:
    """The plinth gap is a void beside compartments, so the two bays take
    all 40 mm, in proportion to their sizes."""
    unit = _scanned("real_magicstart_f1")
    before = solve(unit)
    column = _magic_start_column(unit)
    plinth = next(item for item in column.items if isinstance(item, Void))
    lower_bay, upper_bay = (item for item in column.items if isinstance(item, Bay))
    after = solve(_resized(unit, Axis.Z, 40.0))
    assert after[plinth.id].size.z_mm == pytest.approx(100.0)
    growth_mm = [
        after[bay.id].size.z_mm - before[bay.id].size.z_mm
        for bay in (lower_bay, upper_bay)
    ]
    assert sum(growth_mm) == pytest.approx(40.0)
    assert growth_mm[0] / growth_mm[1] == pytest.approx(253.0 / 353.0)
