"""The in-view editor's elevation frame and drawing plan, under plain
pytest: ``elevation.py`` imports neither FreeCAD nor Qt."""

import dataclasses
from collections.abc import Collection

import pytest

from freecad.Shelving.core.edit import add_equal, add_even_spacing, lock, set_unit_size
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    ConstraintId,
    Division,
    FixedSide,
    Lock,
    Unit,
    Void,
)
from freecad.Shelving.core.solver import solve
from freecad.Shelving.editor.elevation import (
    FIRST_CONSTRAINT_SLOT,
    DimensionLabel,
    FixedChoice,
    Overlay,
    Rect,
    Side,
    arrow_for,
    dragged_to_mm,
    elevation_frame,
    fixed_choices,
    icon_at,
    icon_center_px,
    label_at,
    label_size_pt,
    plan_overlay,
    region_along,
    region_at,
    run_direction,
)

_T_MM = 18.0
# The spacing of the rows of dimensions outside the unit.
_ROW_MM = 40.0


_LOWER_LOCK = ConstraintId("lower-lock")


def _bookcase(front_at_min: bool | None = None, *, locked: bool = True) -> Unit:
    """A 900 x 300 x 600 carcass, depth along Y, holding a column of two
    bays split by one shelf beside a void; the lower bay is locked, by
    :data:`_LOWER_LOCK`, unless ``locked`` is false."""
    return Unit(
        size_mm=Vec3(900.0, 300.0, 600.0),
        root=Division(
            axis=Axis.Z,
            id="root",
            items=[
                Board(thickness_mm=_T_MM, id="bottom"),
                Division(
                    axis=Axis.X,
                    id="row",
                    items=[
                        Board(thickness_mm=_T_MM, id="left"),
                        Division(
                            axis=Axis.Z,
                            id="column",
                            items=[
                                Bay(size_mm=200.0, id="lower"),
                                Board(thickness_mm=_T_MM, id="shelf"),
                                Bay(size_mm=346.0, id="upper"),
                            ],
                            size_mm=423.0,
                        ),
                        Board(thickness_mm=_T_MM, id="divider"),
                        Void(size_mm=423.0, id="void"),
                        Board(thickness_mm=_T_MM, id="right"),
                    ],
                    size_mm=564.0,
                ),
                Board(thickness_mm=_T_MM, id="top"),
            ],
        ),
        depth_axis=Axis.Y,
        front_at_min=front_at_min,
        constraints=(Lock("lower", id=_LOWER_LOCK),) if locked else (),
    )


_UNIT = _bookcase()
_SPACES = solve(_UNIT)


def _close(a: Vec3, b: Vec3) -> bool:
    return all(a.component_mm(i) == pytest.approx(b.component_mm(i)) for i in (0, 1, 2))


def test_the_default_front_is_freecads_front_view() -> None:
    """Facing unknown, the camera looks from -Y with X to the right and Z
    up, as FreeCAD's front view does."""
    frame = elevation_frame(_UNIT)
    assert frame.h_dir == Vec3(1.0, 0.0, 0.0)
    assert frame.v_dir == Vec3(0.0, 0.0, 1.0)
    assert frame.z_dir == Vec3(0.0, -1.0, 0.0)
    assert frame.origin_mm == Vec3(0.0, 0.0, 0.0)
    assert frame.z_sign == 1.0


def test_the_back_frame_keeps_the_axes_on_the_far_face() -> None:
    front = elevation_frame(_UNIT)
    back = elevation_frame(_UNIT, "back")
    assert (back.h_dir, back.v_dir, back.z_dir) == (
        front.h_dir,
        front.v_dir,
        front.z_dir,
    )
    assert back.origin_mm == Vec3(0.0, 300.0, 0.0)
    assert back.z_sign == -1.0
    assert back.rect(_SPACES["lower"]) == front.rect(_SPACES["lower"])


def test_a_front_at_the_far_end_turns_the_horizontal_round() -> None:
    unit = _bookcase(front_at_min=False)
    frame = elevation_frame(unit)
    assert frame.h_dir == Vec3(-1.0, 0.0, 0.0)
    assert frame.z_dir == Vec3(0.0, 1.0, 0.0)
    assert frame.origin_mm == Vec3(900.0, 300.0, 0.0)
    # The void at the unit's +X end is on the left seen from +Y.
    rect = frame.rect(solve(unit)["void"])
    assert rect.h0_mm == pytest.approx(_T_MM)


def test_a_depth_along_x_draws_y_across() -> None:
    unit = Unit(
        size_mm=Vec3(300.0, 900.0, 600.0),
        root=Bay(id="bay"),
        depth_axis=Axis.X,
        front_at_min=True,
    )
    frame = elevation_frame(unit)
    assert frame.horizontal == Axis.Y
    assert frame.z_dir == Vec3(-1.0, 0.0, 0.0)
    assert frame.rect(solve(unit)["bay"]) == Rect(0.0, 0.0, 900.0, 600.0)


@pytest.mark.parametrize("front_at_min", [None, False])
@pytest.mark.parametrize("side", ["front", "back"])
def test_an_offset_unit_draws_the_same_elevation_from_its_position(
    front_at_min: bool | None, side: Side
) -> None:
    """The frame starts at the unit's position, so an offset unit's overlay
    and arrows in elevation coordinates are the origin unit's, and only the
    arrow's unit-frame grab point carries the offset."""
    shift_mm = Vec3(100.0, -300.0, 50.0)

    def shifted(point: Vec3) -> Vec3:
        return Vec3(
            point.x_mm + shift_mm.x_mm,
            point.y_mm + shift_mm.y_mm,
            point.z_mm + shift_mm.z_mm,
        )

    at_origin = _bookcase(front_at_min)
    offset = dataclasses.replace(at_origin, position_mm=shift_mm)
    origin_frame = elevation_frame(at_origin, side)
    offset_frame = elevation_frame(offset, side)
    assert _close(offset_frame.origin_mm, shifted(origin_frame.origin_mm))
    assert plan_overlay(
        offset, solve(offset), offset_frame, "shelf", _ROW_MM
    ) == plan_overlay(at_origin, solve(at_origin), origin_frame, "shelf", _ROW_MM)
    origin_arrow = arrow_for(at_origin, solve(at_origin), origin_frame, "divider")
    offset_arrow = arrow_for(offset, solve(offset), offset_frame, "divider")
    assert origin_arrow is not None and offset_arrow is not None
    assert offset_arrow.at_mm == origin_arrow.at_mm
    assert _close(offset_arrow.grab_mm, shifted(origin_arrow.grab_mm))


@pytest.mark.parametrize(
    ("depth_axis", "front_at_min", "width", "height", "depth"),
    [
        # Unknown facing: the frame faces -Y, so Left is -X and Front -Y.
        (Axis.Y, None, ("min", "max"), ("min", "max"), ("min", "max")),
        (Axis.Y, True, ("min", "max"), ("min", "max"), ("min", "max")),
        # Seen from +Y, the unit's +X end is on the left.
        (Axis.Y, False, ("max", "min"), ("min", "max"), ("max", "min")),
        # Depth along X, front at -X: the elevation runs along -Y.
        (Axis.X, True, ("max", "min"), ("min", "max"), ("min", "max")),
        (Axis.X, False, ("min", "max"), ("min", "max"), ("max", "min")),
    ],
)
def test_fixed_choices_name_the_sides_as_the_editor_shows_them(
    depth_axis: Axis,
    front_at_min: bool | None,
    width: tuple[FixedSide, FixedSide],
    height: tuple[FixedSide, FixedSide],
    depth: tuple[FixedSide, FixedSide],
) -> None:
    unit = dataclasses.replace(
        _bookcase(front_at_min),
        depth_axis=depth_axis,
        size_mm=Vec3(300.0, 900.0, 600.0)
        if depth_axis == Axis.X
        else Vec3(900.0, 300.0, 600.0),
    )
    frame = elevation_frame(unit)
    for axis, names, (first, last) in (
        (frame.horizontal, ("Left", "Right"), width),
        (frame.vertical, ("Bottom", "Top"), height),
        (depth_axis, ("Front", "Back"), depth),
    ):
        assert fixed_choices(unit, axis) == (
            FixedChoice(names[0], first),
            FixedChoice("Center", "center"),
            FixedChoice(names[1], last),
        ), axis


def test_the_front_choice_is_the_end_the_frame_faces() -> None:
    for front_at_min in (None, True, False):
        unit = _bookcase(front_at_min)
        frame = elevation_frame(unit)
        front = fixed_choices(unit, Axis.Y)[0]
        assert front.label == "Front"
        facing_max = frame.z_dir.y_mm > 0
        assert front.side == ("max" if facing_max else "min"), front_at_min
        left = fixed_choices(unit, Axis.X)[0]
        left_at_max = frame.h_dir.x_mm < 0
        assert left.side == ("max" if left_at_max else "min"), front_at_min


def test_unit_and_elevation_points_round_trip() -> None:
    for frame in (
        elevation_frame(_bookcase(front_at_min=False)),
        elevation_frame(_UNIT, "back"),
    ):
        point = Vec3(120.0, 40.0, 310.0)
        assert _close(frame.to_unit(*frame.from_unit(point)), point)


def test_a_face_per_opening_on_the_face_itself() -> None:
    overlay = plan_overlay(_UNIT, _SPACES, elevation_frame(_UNIT), None, _ROW_MM)
    kinds = {face.region_id: face.kind for face in overlay.faces}
    assert kinds == {"lower": "bay", "upper": "bay", "void": "void"}
    lower = next(face for face in overlay.faces if face.region_id == "lower")
    assert lower.rect == Rect(_T_MM, _T_MM, 441.0, _T_MM + 200.0)


def test_selection_shows_as_an_outline() -> None:
    frame = elevation_frame(_UNIT)
    for node_id in ("lower", "shelf"):
        overlay = plan_overlay(_UNIT, _SPACES, frame, node_id, _ROW_MM)
        selected = [o for o in overlay.outlines if o.role == "selected"]
        assert len(selected) == 1
    overlay = plan_overlay(_UNIT, _SPACES, frame, "shelf", _ROW_MM)
    (outline,) = [o for o in overlay.outlines if o.role == "selected"]
    assert outline.rect == frame.rect(_SPACES["shelf"])


def _labels(selected: str | None = None, unit: Unit = _UNIT) -> list[DimensionLabel]:
    spaces = solve(unit)
    return list(
        plan_overlay(unit, spaces, elevation_frame(unit), selected, _ROW_MM).labels
    )


def _region_ids(unit: Unit) -> list[str]:
    ids: list[str] = []

    def visit(region: Division | Bay | Void) -> None:
        if region is not unit.root:
            ids.append(region.id)
        if isinstance(region, Division):
            for item in region.items:
                if not isinstance(item, Board):
                    visit(item)

    visit(unit.root)
    return ids


def _every_label(unit: Unit = _UNIT) -> list[DimensionLabel]:
    """The labels with every region selected, so each one draws its
    dimension wherever it goes."""
    return list(
        plan_overlay(
            unit,
            solve(unit),
            elevation_frame(unit),
            None,
            _ROW_MM,
            selected_items=_region_ids(unit),
        ).labels
    )


def test_a_dimension_per_region_in_each_run_when_every_region_is_selected() -> None:
    ids = sorted(label.region_id for label in _every_label())
    assert ids == sorted(["row", "column", "void", "lower", "upper"])


def test_a_dimension_reads_its_size_and_role() -> None:
    by_id = {label.region_id: label for label in _every_label()}
    assert by_id["lower"].size_mm == pytest.approx(200.0)
    assert by_id["lower"].role == "driving"
    assert by_id["lower"].lock_id == _LOWER_LOCK
    assert by_id["upper"].role == "reference"
    assert by_id["upper"].lock_id is None
    assert by_id["upper"].size_mm == pytest.approx(346.0)
    assert not any(label.selected for label in by_id.values())


def test_a_deactivated_lock_draws_deactivated_and_holds_no_board() -> None:
    off = dataclasses.replace(
        _UNIT, constraints=(Lock("lower", active=False, id=_LOWER_LOCK),)
    )
    (label,) = _labels(unit=off)
    assert (label.region_id, label.role) == ("lower", "deactivated")
    frame = elevation_frame(off)
    overlay = plan_overlay(off, solve(off), frame, None, _ROW_MM)
    assert overlay.icons == []
    assert arrow_for(off, solve(off), frame, "shelf") is not None


def test_a_spacing_spans_through_the_next_board() -> None:
    spacing = Unit(
        size_mm=_UNIT.size_mm,
        root=Division(
            axis=Axis.Z,
            id="root",
            items=[
                Bay(size_mm=200.0, id="lower"),
                Board(thickness_mm=_T_MM, id="shelf"),
                Bay(size_mm=382.0, id="upper"),
            ],
        ),
        depth_axis=Axis.Y,
        constraints=(Lock("lower", Basis.WITH_NEXT),),
    )
    (label,) = [x for x in _every_label(spacing) if x.region_id == "lower"]
    assert label.size_mm == pytest.approx(218.0)
    assert label.length_mm == pytest.approx(218.0)


def test_a_bay_dimension_runs_two_thirds_across_with_its_text_a_third_along() -> None:
    (label,) = [x for x in _labels() if x.region_id == "lower"]
    rect = elevation_frame(_UNIT).rect(_SPACES["lower"])
    assert label.start_mm == (pytest.approx(rect.h0_mm + 2 / 3 * 423.0), rect.v0_mm)
    assert label.end_mm[1] == pytest.approx(rect.v1_mm)
    assert label.text_at_mm[1] == pytest.approx(rect.v0_mm + 200.0 / 3)
    assert label.text_shift_mm == pytest.approx(-200.0 / 6)


def test_a_region_holding_others_dimensions_outside_the_unit() -> None:
    """The row and the column reach the unit's edges past boards only, so
    their dimensions go one row out from the unit's outer face on their own
    side: the row's left of the unit, the column's below it, the bottom
    board's thickness no nearer than the row's."""
    by_id = {label.region_id: label for label in _every_label()}
    assert by_id["row"].start_mm[0] == pytest.approx(-_ROW_MM)
    assert by_id["column"].start_mm[1] == pytest.approx(-_ROW_MM)


def test_resizing_the_unit_leaves_its_outer_dimensions_rows_in_place() -> None:
    """Only a dimension's length follows the unit's size: the rows keep
    their spacing whatever the unit's longer side."""
    taller = set_unit_size(_UNIT, Vec3(_UNIT.size_mm.x_mm, _UNIT.size_mm.y_mm, 1800.0))
    before = {label.region_id: label for label in _every_label()}
    after = {label.region_id: label for label in _every_label(taller)}
    assert after["row"].start_mm[0] == pytest.approx(before["row"].start_mm[0])
    assert after["column"].start_mm[1] == pytest.approx(before["column"].start_mm[1])
    assert after["row"].length_mm > before["row"].length_mm


def test_a_run_through_the_depth_draws_no_dimension() -> None:
    unit = Unit(
        size_mm=Vec3(900.0, 300.0, 600.0),
        root=Division(
            axis=Axis.Y,
            items=[
                Bay(size_mm=141.0, id="front"),
                Board(thickness_mm=_T_MM),
                Bay(size_mm=141.0, id="rear"),
            ],
        ),
        depth_axis=Axis.Y,
    )
    assert _every_label(unit) == []


@pytest.mark.parametrize(
    ("h_mm", "v_mm", "expected"),
    [
        (200.0, 100.0, "lower"),
        (200.0, 400.0, "upper"),
        (700.0, 300.0, "void"),
        (200.0, _T_MM + 200.0 + _T_MM / 2, None),
        (5.0, 300.0, None),
        (-10.0, -10.0, None),
    ],
)
def test_region_at_finds_the_opening_under_a_point(
    h_mm: float, v_mm: float, expected: str | None
) -> None:
    frame = elevation_frame(_UNIT)
    assert region_at(_UNIT, _SPACES, frame, h_mm, v_mm) == expected


def _label(region_id: str, at_mm: tuple[float, float]) -> DimensionLabel:
    return DimensionLabel(region_id, at_mm, at_mm, 1.0, "reference", 0.5)


def _upright_label(region_id: str, at_mm: tuple[float, float]) -> DimensionLabel:
    h_mm, v_mm = at_mm
    return DimensionLabel(
        region_id, (h_mm, v_mm - 1.0), (h_mm, v_mm + 1.0), 2.0, "reference", 0.5
    )


def test_label_at_takes_a_point_on_a_text_tile_and_the_later_of_two() -> None:
    labels = [
        _label("a", (0.0, 0.0)),
        _label("b", (100.0, 0.0)),
        _label("c", (0.0, 0.0)),
        _upright_label("d", (0.0, 100.0)),
    ]

    def project(h_mm: float, v_mm: float) -> tuple[float, float]:
        return (h_mm, v_mm)

    def tile_px(_label: DimensionLabel) -> tuple[float, float]:
        return (40.0, 10.0)

    # Just inside a long tile's corner, and on its edge.
    assert label_at(labels, project, tile_px, 119.0, 4.0) == labels[1]
    assert label_at(labels, project, tile_px, 120.0, -5.0) == labels[1]
    assert label_at(labels, project, tile_px, 1.0, 0.0) == labels[2]
    # Past the tile's end, and past its height.
    assert label_at(labels, project, tile_px, 122.0, 0.0) is None
    assert label_at(labels, project, tile_px, 100.0, 7.0) is None
    # A vertical dimension's tile stands upright.
    assert label_at(labels, project, tile_px, 4.0, 119.0) == labels[3]
    assert label_at(labels, project, tile_px, 19.0, 100.0) is None


def test_a_movable_board_gets_an_arrow_beside_the_dimension_before_it() -> None:
    frame = elevation_frame(_UNIT)
    arrow = arrow_for(_UNIT, _SPACES, frame, "divider")
    assert arrow is not None
    assert not arrow.vertical
    row = frame.rect(_SPACES["row"])
    assert arrow.at_mm[1] > row.v0_mm + 2 / 3 * (row.v1_mm - row.v0_mm)
    assert arrow.length_mm == pytest.approx(0.08 * 900.0)
    moved = dragged_to_mm(arrow, 10.0)
    assert moved.x_mm == pytest.approx(arrow.grab_mm.x_mm + 10.0)


def test_held_and_carcass_boards_get_no_arrow() -> None:
    frame = elevation_frame(_UNIT)
    # Only boards and the locked lower bay lie below the shelf.
    assert arrow_for(_UNIT, _SPACES, frame, "shelf") is None
    assert arrow_for(_UNIT, _SPACES, frame, "top") is None
    assert arrow_for(_UNIT, _SPACES, frame, "lower") is None
    unlocked = _bookcase(locked=False)
    arrow = arrow_for(unlocked, solve(unlocked), frame, "shelf")
    assert arrow is not None
    assert arrow.vertical
    relocked = lock(unlocked, "upper")
    assert arrow_for(relocked, solve(relocked), frame, "shelf") is None


def test_a_region_alone_in_its_run_gets_a_dimension_when_selected() -> None:
    """The row is the only region in its run, and selecting it still draws
    its dimension: any region but the whole unit may lock."""
    assert "row" in {label.region_id for label in _labels("row")}


def test_flagged_regions_get_the_holding_outline_unless_selected() -> None:
    frame = elevation_frame(_UNIT)
    overlay = plan_overlay(
        _UNIT, _SPACES, frame, "upper", _ROW_MM, ("upper", "void", "gone")
    )
    holding = [o.rect for o in overlay.outlines if o.role == "holding"]
    assert holding == [frame.rect(_SPACES["void"])]
    selected = [o.rect for o in overlay.outlines if o.role == "selected"]
    assert selected == [frame.rect(_SPACES["upper"])]


def test_a_selected_held_board_outlines_the_openings_holding_it() -> None:
    frame = elevation_frame(_UNIT)
    overlay = plan_overlay(_UNIT, _SPACES, frame, "shelf", _ROW_MM)
    holding = [o.rect for o in overlay.outlines if o.role == "holding"]
    assert holding == [frame.rect(_SPACES["lower"])]
    for other in ("divider", "lower", None):
        overlay = plan_overlay(_UNIT, _SPACES, frame, other, _ROW_MM)
        assert all(o.role != "holding" for o in overlay.outlines)


@pytest.mark.parametrize(
    ("font_px", "ratio", "dpi", "expected"),
    [(13, 1.0, 96.0, 10), (13, 2.0, 72.0, 26), (13, 1.0, 0.0, 10), (0, 1.0, 96.0, 1)],
)
def test_label_size_follows_the_sketcher(
    font_px: int, ratio: float, dpi: float, expected: int
) -> None:
    assert label_size_pt(font_px, ratio, dpi) == expected


# --- constraint icons and outlines (sh-048) ---------------------------------


def _column(sizes_mm: tuple[float, ...] = (300.0, 300.0, 300.0)) -> Unit:
    """A column of 18 mm boards: bottom, A, s1, B, s2, C, top."""
    items: list[Board | Bay] = [Board(thickness_mm=_T_MM, id="bottom")]
    for index, size_mm in enumerate(sizes_mm):
        items.append(Bay(size_mm=size_mm, id="ABC"[index]))
        last = index == len(sizes_mm) - 1
        items.append(Board(thickness_mm=_T_MM, id="top" if last else f"s{index + 1}"))
    return Unit(
        size_mm=Vec3(600.0, 300.0, _T_MM * (len(sizes_mm) + 1) + sum(sizes_mm)),
        root=Division(axis=Axis.Z, items=list(items), id="column"),
        depth_axis=Axis.Y,
    )


def _overlay(
    unit: Unit,
    *,
    selected_id: str | None = None,
    flagged: Collection[str] = (),
    selected_items: Collection[str] = (),
    selected_constraints: Collection[ConstraintId] = (),
) -> Overlay:
    return plan_overlay(
        unit,
        solve(unit),
        elevation_frame(unit),
        selected_id,
        _ROW_MM,
        flagged,
        selected_items=selected_items,
        selected_constraints=selected_constraints,
    )


def test_an_equal_draws_an_icon_at_each_of_its_openings() -> None:
    unit = add_equal(_column(), ["A", "C"])
    (equal,) = unit.constraints
    icons = _overlay(unit).icons
    assert [
        (i.label.region_id, i.kind, i.slot, i.active, i.selected) for i in icons
    ] == [
        ("A", "equal", 0, True, False),
        ("C", "equal", 0, True, False),
    ]
    assert {i.constraint_id for i in icons} == {equal.id}


def test_an_even_spacing_draws_an_icon_at_every_opening_of_its_group() -> None:
    unit = add_even_spacing(add_equal(_column(), ["A", "B"]), ["A", "C"])
    icons = _overlay(unit).icons
    assert [(i.label.region_id, i.kind, i.slot) for i in icons] == [
        ("A", "equal", 0),
        ("B", "equal", 0),
        ("A", "even_spacing", 1),
        ("B", "even_spacing", 1),
        ("C", "even_spacing", 0),
    ]


def test_icons_lead_the_row_after_the_text_and_a_lock_draws_none() -> None:
    unit = add_equal(_column(), ["A", "C"])
    unit = lock(unit, "B")
    overlay = _overlay(unit)
    assert {label.region_id: label.role for label in overlay.labels} == {
        "A": "reference",
        "B": "driving",
        "C": "reference",
    }
    assert [(i.label.region_id, i.slot) for i in overlay.icons] == [
        ("A", FIRST_CONSTRAINT_SLOT),
        ("C", FIRST_CONSTRAINT_SLOT),
    ]


def test_an_icon_reports_selection_and_activation_independently() -> None:
    unit = add_equal(_column(), ["A", "B", "C"])
    first, second = unit.constraints
    off = dataclasses.replace(
        unit, constraints=(first, dataclasses.replace(second, active=False))
    )

    def flags(
        selected: Collection[ConstraintId],
    ) -> dict[tuple[ConstraintId, str], tuple[bool, bool]]:
        return {
            (i.constraint_id, i.label.region_id): (i.selected, i.active)
            for i in _overlay(off, selected_constraints=selected).icons
        }

    assert flags([first.id]) == {
        (first.id, "A"): (True, True),
        (first.id, "B"): (True, True),
        (second.id, "B"): (False, False),
        (second.id, "C"): (False, False),
    }
    # A selected deactivated constraint stays deactivated.
    assert flags([second.id]) == {
        (first.id, "A"): (False, True),
        (first.id, "B"): (False, True),
        (second.id, "B"): (True, False),
        (second.id, "C"): (True, False),
    }


def test_icons_sit_past_the_text_clear_of_it_and_of_each_other() -> None:
    unit = add_even_spacing(add_equal(_column(), ["A", "B"]), ["A", "C"])
    overlay = _overlay(unit)
    # One pixel a millimeter, so the text's center doubles as its pixel
    # position.
    text_width_px, icon_px, gap_px = 60.0, 16.0, 3.0
    boxes: list[tuple[float, float, float, float]] = []
    for label in overlay.labels:
        h_mm, v_mm = label.text_at_mm
        half_w_px, half_h_px = (
            (text_width_px / 2, 8.0) if label.horizontal else (8.0, text_width_px / 2)
        )
        boxes.append(
            (h_mm - half_w_px, v_mm - half_h_px, h_mm + half_w_px, v_mm + half_h_px)
        )
    for icon in overlay.icons:
        x_px, y_px = icon_center_px(
            icon, icon.label.text_at_mm, text_width_px, icon_px, gap_px
        )
        half_px = icon_px / 2
        boxes.append((x_px - half_px, y_px - half_px, x_px + half_px, y_px + half_px))
    for index, a in enumerate(boxes):
        for b in boxes[index + 1 :]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


def test_icon_at_finds_the_icon_under_a_point() -> None:
    unit = add_even_spacing(add_equal(_column(), ["A", "B"]), ["A", "C"])
    overlay = _overlay(unit)
    row = overlay.icons

    def project(h_mm: float, v_mm: float) -> tuple[float, float]:
        return (h_mm, v_mm)

    for entry in row:
        x_px, y_px = icon_center_px(entry, entry.label.text_at_mm, 40.0, 16.0, 3.0)
        assert icon_at(row, project, lambda _: 40.0, 16.0, 3.0, x_px, y_px) == entry
    first = row[0]
    x0_px, y0_px = first.label.text_at_mm
    assert icon_at(row, project, lambda _: 40.0, 16.0, 3.0, x0_px, y0_px) is None
    # The first icon sits right after the text, the second one place on.
    second = next(i for i in row if i.label == first.label and i is not first)
    for entry, along_px in ((first, 31.0), (second, 50.0)):
        x_px, y_px = icon_center_px(entry, (0.0, 0.0), 40.0, 16.0, 3.0)
        assert x_px + y_px == pytest.approx(along_px)


def _roles(overlay: Overlay, region_id: str, unit: Unit) -> list[str]:
    frame = elevation_frame(unit)
    rect = frame.rect(solve(unit)[region_id])
    return [outline.role for outline in overlay.outlines if outline.rect == rect]


def test_a_selected_constraint_outlines_its_openings_as_selected() -> None:
    unit = add_equal(_column(), ["A", "C"])
    (equal,) = unit.constraints
    overlay = _overlay(unit, selected_constraints=[equal.id])
    assert _roles(overlay, "A", unit) == ["selected"]
    assert _roles(overlay, "C", unit) == ["selected"]
    assert _roles(overlay, "B", unit) == ["region"]


def test_several_selected_openings_are_each_outlined() -> None:
    unit = _column()
    overlay = _overlay(unit, selected_items=["A", "C"])
    assert _roles(overlay, "A", unit) == ["selected"]
    assert _roles(overlay, "C", unit) == ["selected"]


def test_a_board_an_even_spacing_holds_shows_its_group_and_no_arrow() -> None:
    unit = add_even_spacing(_column(), ["A", "C"])
    overlay = _overlay(unit, selected_id="s1")
    for region_id in "ABC":
        assert _roles(overlay, region_id, unit) == ["holding"]
    frame = elevation_frame(unit)
    assert arrow_for(unit, solve(unit), frame, "s1") is None


def test_a_flagged_constraint_outlines_its_openings() -> None:
    unit = add_equal(_column(), ["A", "C"])
    (equal,) = unit.constraints
    overlay = _overlay(unit, flagged=[equal.id])
    assert _roles(overlay, "A", unit) == ["holding"]
    assert _roles(overlay, "B", unit) == ["region"]


# --- dimensions as the Sketcher draws them ----------------------------------


def _columns() -> Unit:
    """A unit 654 mm tall of 18 mm boards, split by two dividers into three
    300 mm columns L, M and R, each split by one shelf: A1 300, s1, A2 300;
    B1 200, t1, B2 400; C1 250, u1, C2 350, bottom to top."""

    def column(
        name: str, lower: str, upper: str, shelf: str, sizes_mm: tuple[float, float]
    ) -> Division:
        return Division(
            axis=Axis.Z,
            id=name,
            items=[
                Bay(size_mm=sizes_mm[0], id=lower),
                Board(thickness_mm=_T_MM, id=shelf),
                Bay(size_mm=sizes_mm[1], id=upper),
            ],
            size_mm=300.0,
        )

    row = Division(
        axis=Axis.X,
        id="row",
        items=[
            Board(thickness_mm=_T_MM, id="left"),
            column("L", "A1", "A2", "s1", (300.0, 300.0)),
            Board(thickness_mm=_T_MM, id="d1"),
            column("M", "B1", "B2", "t1", (200.0, 400.0)),
            Board(thickness_mm=_T_MM, id="d2"),
            column("R", "C1", "C2", "u1", (250.0, 350.0)),
            Board(thickness_mm=_T_MM, id="right"),
        ],
        size_mm=618.0,
    )
    return Unit(
        size_mm=Vec3(972.0, 300.0, 654.0),
        root=Division(
            axis=Axis.Z,
            id="root",
            items=[
                Board(thickness_mm=_T_MM, id="bottom"),
                row,
                Board(thickness_mm=_T_MM, id="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def _drawn(overlay: Overlay) -> dict[str, tuple[str, bool]]:
    return {label.region_id: (label.role, label.selected) for label in overlay.labels}


def test_nothing_locked_constrained_or_selected_draws_no_dimension() -> None:
    assert _overlay(_columns()).labels == []


def test_a_lock_draws_its_dimension_driving_deactivated_or_selected() -> None:
    unit = lock(_columns(), "A1")
    (a1_lock,) = unit.constraints
    assert _drawn(_overlay(unit)) == {"A1": ("driving", False)}
    off = dataclasses.replace(
        unit, constraints=(dataclasses.replace(a1_lock, active=False),)
    )
    assert _drawn(_overlay(off)) == {"A1": ("deactivated", False)}
    assert _drawn(_overlay(unit, selected_constraints=[a1_lock.id])) == {
        "A1": ("driving", True)
    }


def test_a_selected_opening_draws_both_sizes_as_reference() -> None:
    unit = _columns()
    expected = {"A1": ("reference", False), "L": ("reference", False)}
    assert _drawn(_overlay(unit, selected_id="A1")) == expected
    assert _drawn(_overlay(unit, selected_items=["A1"])) == expected


def test_a_selected_region_keeps_its_lock_drawn_unselected() -> None:
    """Selecting the region recolors nothing, as selecting Sketcher
    geometry leaves its dimensions' colors alone."""
    unit = lock(_columns(), "L")
    assert _drawn(_overlay(unit, selected_id="A1")) == {
        "A1": ("reference", False),
        "L": ("driving", False),
    }


def test_a_selected_column_draws_the_lone_row_spanning_the_unit_height() -> None:
    """The row is alone between the bottom and top, so its height is the
    unit's own: Lock Height refuses it, but a selected column still shows
    it."""
    assert _drawn(_overlay(_columns(), selected_id="L")) == {
        "L": ("reference", False),
        "row": ("reference", False),
    }


def test_a_bay_in_a_lone_column_shows_the_columns_width() -> None:
    unit = dataclasses.replace(
        _column(),
        root=Division(
            axis=Axis.X,
            id="root",
            items=[
                Board(thickness_mm=_T_MM, id="left"),
                dataclasses.replace(_column().root, size_mm=564.0),
                Board(thickness_mm=_T_MM, id="right"),
            ],
        ),
    )
    assert region_along(unit, "A", Axis.X) is None
    assert set(_drawn(_overlay(unit, selected_id="A"))) == {"A", "column"}


def test_an_equal_draws_its_openings_as_reference_with_its_icon_first() -> None:
    unit = add_equal(_columns(), ["A1", "B1"])
    (equal,) = unit.constraints
    overlay = _overlay(unit)
    assert _drawn(overlay) == {
        "A1": ("reference", False),
        "B1": ("reference", False),
    }
    assert [(i.label.region_id, i.constraint_id, i.slot) for i in overlay.icons] == [
        ("A1", equal.id, 0),
        ("B1", equal.id, 0),
    ]
    off = dataclasses.replace(
        unit, constraints=(dataclasses.replace(equal, active=False),)
    )
    assert set(_drawn(_overlay(off))) == {"A1", "B1"}


@pytest.mark.parametrize(
    ("node_id", "axis", "expected"),
    [
        ("A1", Axis.X, "L"),
        ("A2", Axis.X, "L"),
        ("A1", Axis.Z, "A1"),
        ("L", Axis.X, "L"),
        ("L", Axis.Z, None),
        ("row", Axis.Z, None),
        ("s1", Axis.X, None),
        ("root", Axis.X, None),
        ("nothing", Axis.X, None),
        ("A1", Axis.Y, None),
    ],
)
def test_region_along_finds_the_region_owning_a_size(
    node_id: str, axis: Axis, expected: str | None
) -> None:
    assert region_along(_columns(), node_id, axis) == expected


def test_a_bay_with_no_divider_has_no_width_of_its_own() -> None:
    unit = _column()
    assert region_along(unit, "A", Axis.X) is None
    assert region_along(unit, "A", Axis.Z) == "A"
    # Between two sides, the column is alone in a run spanning the unit.
    sided = dataclasses.replace(
        unit,
        root=Division(
            axis=Axis.X,
            id="root",
            items=[
                Board(thickness_mm=_T_MM, id="left"),
                dataclasses.replace(unit.root, size_mm=564.0),
                Board(thickness_mm=_T_MM, id="right"),
            ],
        ),
    )
    assert region_along(sided, "A", Axis.X) is None
    assert region_along(sided, "B", Axis.Z) == "B"


def test_a_run_direction_names_the_lock_command_and_none_through_the_depth() -> None:
    unit = _columns()
    frame = elevation_frame(unit)
    assert run_direction(unit, frame, "L") == "horizontal"
    assert run_direction(unit, frame, "A1") == "vertical"
    for none in ("root", "s1", "nothing"):
        assert run_direction(unit, frame, none) is None
    depth = Unit(
        size_mm=Vec3(900.0, 300.0, 600.0),
        root=Division(
            axis=Axis.Y,
            items=[
                Bay(size_mm=141.0, id="front"),
                Board(thickness_mm=_T_MM),
                Bay(size_mm=141.0, id="rear"),
            ],
        ),
        depth_axis=Axis.Y,
    )
    assert run_direction(depth, elevation_frame(depth), "front") is None


def _nested() -> Unit:
    """A unit whose left column holds a lower row of two openings, SA and
    SB, so SA's width and the column's both reach the unit's bottom past
    boards alone: the column's width takes the first row below the unit,
    SA's the second."""
    sub = Division(
        axis=Axis.X,
        id="sub",
        items=[
            Division(
                axis=Axis.Z, id="SA", items=[Bay(size_mm=300.0, id="a1")], size_mm=200.0
            ),
            Board(thickness_mm=_T_MM, id="sub_board"),
            Bay(size_mm=182.0, id="SB"),
        ],
        size_mm=300.0,
    )
    left = Division(
        axis=Axis.Z,
        id="colL",
        items=[sub, Board(thickness_mm=_T_MM, id="shelf"), Bay(size_mm=246.0)],
        size_mm=400.0,
    )
    return Unit(
        size_mm=Vec3(900.0, 300.0, 600.0),
        root=Division(
            axis=Axis.Z,
            id="root",
            items=[
                Board(thickness_mm=_T_MM, id="bottom"),
                Division(
                    axis=Axis.X,
                    id="row",
                    items=[
                        Board(thickness_mm=_T_MM, id="left"),
                        left,
                        Board(thickness_mm=_T_MM, id="divider"),
                        Bay(size_mm=446.0, id="colR"),
                        Board(thickness_mm=_T_MM, id="right"),
                    ],
                    size_mm=564.0,
                ),
                Board(thickness_mm=_T_MM, id="top"),
            ],
        ),
        depth_axis=Axis.Y,
    )


def test_an_outer_dimension_keeps_its_row_when_the_one_inside_it_is_hidden() -> None:
    unit = _nested()
    every = {label.region_id: label for label in _every_label(unit)}
    assert every["colL"].start_mm[1] == pytest.approx(-_ROW_MM)
    assert every["SA"].start_mm[1] == pytest.approx(-2 * _ROW_MM)
    alone = {
        label.region_id: label for label in _overlay(unit, selected_id="SA").labels
    }
    assert "colL" not in alone
    assert alone["SA"].start_mm == every["SA"].start_mm
