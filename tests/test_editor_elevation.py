"""The in-view editor's elevation frame and drawing plan, under plain
pytest: ``elevation.py`` imports neither FreeCAD nor Qt."""

import dataclasses

import pytest

from freecad.Shelving.core.edit import lock
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    Unit,
    Void,
)
from freecad.Shelving.core.solver import solve
from freecad.Shelving.editor.elevation import (
    DimensionLabel,
    Rect,
    arrow_for,
    board_space,
    dragged_to_mm,
    elevation_frame,
    held_padlock,
    label_at,
    label_size_pt,
    plan_overlay,
    region_at,
    split_preview,
)

_T_MM = 18.0


def _bookcase(front_at_min: bool | None = None) -> Unit:
    """A 900 x 300 x 600 carcass, depth along Y, holding a column of two
    bays split by one shelf beside a void."""
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
                                Bay(id="lower", rule=Fixed(200.0)),
                                Board(thickness_mm=_T_MM, id="shelf"),
                                Bay(id="upper"),
                            ],
                        ),
                        Board(thickness_mm=_T_MM, id="divider"),
                        Void(id="void"),
                        Board(thickness_mm=_T_MM, id="right"),
                    ],
                ),
                Board(thickness_mm=_T_MM, id="top"),
            ],
        ),
        depth_axis=Axis.Y,
        front_at_min=front_at_min,
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


def test_unit_and_elevation_points_round_trip() -> None:
    for frame in (
        elevation_frame(_bookcase(front_at_min=False)),
        elevation_frame(_UNIT, "back"),
    ):
        point = Vec3(120.0, 40.0, 310.0)
        assert _close(frame.to_unit(*frame.from_unit(point)), point)


def test_a_face_per_opening_on_the_face_itself() -> None:
    overlay = plan_overlay(_UNIT, _SPACES, elevation_frame(_UNIT), None)
    kinds = {face.region_id: face.kind for face in overlay.faces}
    assert kinds == {"lower": "bay", "upper": "bay", "void": "void"}
    lower = next(face for face in overlay.faces if face.region_id == "lower")
    assert lower.rect == Rect(_T_MM, _T_MM, 441.0, _T_MM + 200.0)


def test_selection_shows_as_an_outline() -> None:
    frame = elevation_frame(_UNIT)
    for node_id in ("lower", "shelf"):
        overlay = plan_overlay(_UNIT, _SPACES, frame, node_id)
        selected = [o for o in overlay.outlines if o.role == "selected"]
        assert len(selected) == 1
    overlay = plan_overlay(_UNIT, _SPACES, frame, "shelf")
    (outline,) = [o for o in overlay.outlines if o.role == "selected"]
    assert outline.rect == frame.rect(_SPACES["shelf"])


def _labels(selected: str | None = None, unit: Unit = _UNIT) -> list[DimensionLabel]:
    spaces = solve(unit)
    return list(plan_overlay(unit, spaces, elevation_frame(unit), selected).labels)


def test_a_dimension_per_region_in_each_run() -> None:
    ids = sorted(label.region_id for label in _labels())
    assert ids == sorted(["row", "column", "void", "lower", "upper"])


def test_a_dimension_reads_its_size_and_color() -> None:
    by_id = {label.region_id: label for label in _labels()}
    assert by_id["lower"].text == "200"
    assert by_id["lower"].color == "locked"
    assert by_id["upper"].color == "unlocked"
    assert by_id["upper"].text == "346"
    selected = {label.region_id: label for label in _labels("upper")}
    assert selected["upper"].color == "unlocked"


def test_a_spacing_spans_through_the_next_board() -> None:
    spacing = Unit(
        size_mm=_UNIT.size_mm,
        root=Division(
            axis=Axis.Z,
            id="root",
            items=[
                Bay(id="lower", rule=Fixed(218.0, Basis.WITH_NEXT)),
                Board(thickness_mm=_T_MM, id="shelf"),
                Bay(id="upper"),
            ],
        ),
        depth_axis=Axis.Y,
    )
    (label,) = [x for x in _labels(unit=spacing) if x.region_id == "lower"]
    assert label.text == "218"
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
    their dimensions go one row out past their own edge: the row's left of
    the unit, the column's below it, past the bottom board."""
    by_id = {label.region_id: label for label in _labels()}
    outside_mm = 0.06 * 900.0
    assert by_id["row"].start_mm[0] == pytest.approx(-outside_mm)
    assert by_id["column"].start_mm[1] == pytest.approx(_T_MM - outside_mm)


def test_a_run_through_the_depth_draws_no_dimension() -> None:
    unit = Unit(
        size_mm=Vec3(900.0, 300.0, 600.0),
        root=Division(
            axis=Axis.Y,
            items=[Bay(id="front"), Board(thickness_mm=_T_MM), Bay(id="rear")],
        ),
        depth_axis=Axis.Y,
    )
    assert _labels(unit=unit) == []


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
    return DimensionLabel(region_id, at_mm, at_mm, "1", "unlocked", 0.5, lockable=True)


def test_label_at_takes_the_nearest_within_reach_and_the_later_on_a_tie() -> None:
    labels = [
        _label("a", (0.0, 0.0)),
        _label("b", (10.0, 0.0)),
        _label("c", (0.0, 0.0)),
    ]

    def project(h_mm: float, v_mm: float) -> tuple[float, float]:
        return (h_mm, v_mm)

    assert label_at(labels, project, 9.0, 0.0) == labels[1]
    assert label_at(labels, project, 1.0, 0.0) == labels[2]
    assert label_at(labels, project, 100.0, 0.0) is None


def test_split_preview_is_where_the_new_board_goes() -> None:
    frame = elevation_frame(_UNIT)
    preview = split_preview(_UNIT, frame, "upper", Axis.Z)
    assert preview is not None
    upper = frame.rect(_SPACES["upper"])
    assert preview.h0_mm == pytest.approx(upper.h0_mm)
    assert preview.v1_mm - preview.v0_mm == pytest.approx(_T_MM)
    assert upper.v0_mm < preview.v0_mm < upper.v1_mm
    assert split_preview(_UNIT, frame, "shelf", Axis.Z) is None


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
    unlocked = _bookcase()
    lower = Bay(id="lower")
    _replace_lower(unlocked, lower)
    arrow = arrow_for(unlocked, solve(unlocked), frame, "shelf")
    assert arrow is not None
    assert arrow.vertical
    relocked = lock(unlocked, "upper")
    assert arrow_for(relocked, solve(relocked), frame, "shelf") is None


def test_every_dimension_but_a_lone_unlocked_regions_can_lock() -> None:
    lockable = {label.region_id: label.lockable for label in _labels()}
    assert lockable == {
        "row": False,
        "column": True,
        "void": True,
        "lower": True,
        "upper": True,
    }
    locked_row = _bookcase()
    root = locked_row.root
    assert isinstance(root, Division)
    root.items[1] = dataclasses.replace(root.items[1], rule=Fixed(564.0))
    (row,) = [x for x in _labels(unit=locked_row) if x.region_id == "row"]
    assert row.lockable


def test_a_held_board_gets_a_padlock_where_its_arrow_would_be() -> None:
    frame = elevation_frame(_UNIT)
    padlock = held_padlock(_UNIT, _SPACES, frame, "shelf")
    assert padlock is not None
    assert padlock.holders == ("lower",)
    # Beside the lower bay's dimension, level with the shelf, where an arrow would sit.
    unlocked = _bookcase()
    _replace_lower(unlocked, Bay(id="lower"))
    arrow = arrow_for(unlocked, solve(unlocked), frame, "shelf")
    assert arrow is not None
    assert padlock.at_mm[0] == pytest.approx(arrow.at_mm[0])
    shelf = board_space(_UNIT, _SPACES, "shelf")
    assert shelf is not None
    assert padlock.at_mm[1] == pytest.approx(frame.rect(shelf).center_mm[1])
    for movable_or_carcass in ("divider", "top", "lower"):
        assert held_padlock(_UNIT, _SPACES, frame, movable_or_carcass) is None


def test_a_selected_held_board_outlines_the_openings_holding_it() -> None:
    frame = elevation_frame(_UNIT)
    overlay = plan_overlay(_UNIT, _SPACES, frame, "shelf")
    holding = [o.rect for o in overlay.outlines if o.role == "holding"]
    assert holding == [frame.rect(_SPACES["lower"])]
    for other in ("divider", "lower", None):
        overlay = plan_overlay(_UNIT, _SPACES, frame, other)
        assert all(o.role != "holding" for o in overlay.outlines)


def _replace_lower(unit: Unit, bay: Bay) -> None:
    root = unit.root
    assert isinstance(root, Division)
    row = root.items[1]
    assert isinstance(row, Division)
    column = row.items[1]
    assert isinstance(column, Division)
    column.items[0] = bay


@pytest.mark.parametrize(
    ("font_px", "ratio", "dpi", "expected"),
    [(13, 1.0, 96.0, 10), (13, 2.0, 72.0, 26), (13, 1.0, 0.0, 10), (0, 1.0, 96.0, 1)],
)
def test_label_size_follows_the_sketcher(
    font_px: int, ratio: float, dpi: float, expected: int
) -> None:
    assert label_size_pt(font_px, ratio, dpi) == expected
