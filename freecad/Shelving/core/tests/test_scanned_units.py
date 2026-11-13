"""Units modeled outside this workbench, scanned from real exports: their
measured sizes lay out back to the measured boards, and every edit has
somewhere to go."""

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from freecad.Shelving.core.edit import (
    MIN_DRAG_GAP_MM,
    move_board,
    set_size,
    set_thickness,
    set_unit_size,
)
from freecad.Shelving.core.expand import expand
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Item,
    Region,
    Unit,
    Void,
)
from freecad.Shelving.core.record import (
    rules_from_json,
    rules_to_json,
    with_stored_rules,
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
from freecad.Shelving.core.solver import solve, solve_axis

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


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_a_scan_locks_only_axis_wraps_and_voids_beside_a_compartment(
    name: str,
) -> None:
    unit = _scanned(name)
    for division in _divisions(unit.root):
        compartments = [
            item
            for item in division.items
            if isinstance(item, Bay | Division) and not _is_axis_wrap(item)
        ]
        for item in division.items:
            if isinstance(item, Board):
                continue
            beside = isinstance(item, Void) and bool(compartments)
            if _is_axis_wrap(item) or beside:
                assert item.lock is Basis.CLEAR, item
            else:
                assert item.lock is None, item


@pytest.mark.parametrize("name", _FIXTURE_NAMES)
def test_a_unit_read_and_solved_with_no_edit_moves_no_board(name: str) -> None:
    """Reading back the record the unit would store, then solving each
    elevation axis with nothing changed, keeps every board within 1e-6 mm."""
    unit = _scanned(name)
    before = solve(unit)
    read = with_stored_rules(unit, rules_from_json(rules_to_json(unit)))
    assert unit.depth_axis is not None
    for axis in elevation_axes(unit.depth_axis):
        read = solve_axis(read, solve(read), axis, MIN_DRAG_GAP_MM)
    after = solve(read)
    for board in _boards(unit.root):
        for axis in Axis:
            index = axis.component_index
            assert after[board.id].origin_mm(index) == pytest.approx(
                before[board.id].origin_mm(index), abs=1e-6
            ), board.id
            assert after[board.id].extent_mm(index) == pytest.approx(
                before[board.id].extent_mm(index), abs=1e-6
            ), board.id


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
    span as its extent. Their measured spans overrun the run by a fraction of a
    millimeter; their slot widths in the scan grid add up to it exactly."""
    boxes = {box.name: box for box in _boxes("real_two_units")}
    unit = _scanned("real_two_units")
    spaces = solve(unit)
    tops = next(
        division
        for division in _divisions(unit.root)
        if {item.id for item in division.items} == {"panelYX", "panelYX004"}
    )
    extents_mm: list[float] = []
    measured_mm = []
    for top in tops.items:
        assert isinstance(top, Board) and top.extent_mm is not None
        extents_mm.append(top.extent_mm)
        measured_mm.append(_component_mm(boxes[top.id].size_mm, tops.axis))
    run_mm = _component_mm(spaces[tops.id].size, tops.axis)
    assert sum(extents_mm) == pytest.approx(run_mm, abs=1e-9)
    assert abs(sum(measured_mm) - run_mm) > 1e-4


@pytest.mark.parametrize("name", ["real_stair_step", "real_two_units"])
def test_a_board_with_an_extent_spans_its_slot_in_the_scan_grid(name: str) -> None:
    """A board lying across its run carries an extent that is the gap
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
            if not isinstance(item, Board) or item.extent_mm is None:
                continue
            ruled += 1
            low_mm = _component_mm(spaces[item.id].origin, axis)
            high_mm = low_mm + item.extent_mm
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
            if isinstance(item, Board) and item.extent_mm is None:
                assert _component_mm(
                    spaces[item.id].size, division.axis
                ) == pytest.approx(item.thickness_mm, abs=1e-6), item.id


def _resized(unit: Unit, axis: Axis, delta_mm: float) -> Unit:
    size_mm = unit.size_mm
    return set_unit_size(
        unit, _with_component_mm(size_mm, axis, _component_mm(size_mm, axis) + delta_mm)
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
    """The shelf moves up and the upper bay takes up the difference; the
    plinth gap, a void beside compartments, keeps its size, so the floor
    stays where it was."""
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
    assert spaces["Shelf"].origin.z_mm == pytest.approx(low_face_mm, abs=1e-3)


def test_magic_start_takes_a_thinner_shelf() -> None:
    unit = _scanned("real_magicstart_f1")
    thinner = set_thickness(unit, ["Shelf"], 12.0)
    assert solve(thinner)["Shelf"].size.z_mm == pytest.approx(12.0)


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


def test_magic_start_grows_taller_in_its_upper_bay_and_keeps_its_plinth() -> None:
    """The bay beside the top, which moves, takes all 40 mm; the shelf and
    the plinth gap, a void beside compartments, hold still."""
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
    assert growth_mm == pytest.approx([0.0, 40.0])
    assert after["Shelf"] == before["Shelf"]
