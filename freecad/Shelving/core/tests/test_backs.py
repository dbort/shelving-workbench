"""Tests for recognizing backs in a scan and placing them from solved boards."""

import dataclasses
from pathlib import Path

import pytest

from freecad.Shelving.core.backs import (
    BackFitError,
    BackSpec,
    place_backs,
    renamed_back_boards,
)
from freecad.Shelving.core.edit import merge_at, set_unit_size
from freecad.Shelving.core.expand import expand
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Back,
    BackEdge,
    Board,
    Division,
    Face,
    FollowedFace,
    Region,
    Unit,
)
from freecad.Shelving.core.scan import Box, boxes_from_json, scan

_TOL_MM = 1e-6
_MAGIC_START = Path(__file__).parent / "fixtures" / "real_magicstart_f1.boxes.json"


def _box(
    name: str,
    corner_mm: tuple[float, float, float],
    size_mm: tuple[float, float, float],
    *,
    irregular: bool = False,
) -> Box:
    return Box(name, Vec3(*corner_mm), Vec3(*size_mm), irregular=irregular)


def _magic_start() -> list[Box]:
    return boxes_from_json(_MAGIC_START.read_text(encoding="utf-8"))


def _carcass(*extra: Box) -> list[Box]:
    """A 600 x 300 x 900 closed box of 18 mm boards with a divider at the
    middle, front at the minimum of Y once a back says so."""
    return [
        _box("Bottom", (0.0, 0.0, 0.0), (600.0, 300.0, 18.0)),
        _box("Top", (0.0, 0.0, 882.0), (600.0, 300.0, 18.0)),
        _box("Left", (0.0, 0.0, 18.0), (18.0, 300.0, 864.0)),
        _box("Right", (582.0, 0.0, 18.0), (18.0, 300.0, 864.0)),
        _box("Divider", (291.0, 0.0, 18.0), (18.0, 300.0, 864.0)),
        *extra,
    ]


def _follows(board_id: str, face: Face) -> FollowedFace:
    return FollowedFace(board_id=board_id, face=face)


def _only_back(unit: Unit) -> Back:
    (back,) = unit.backs
    return back


def _placed(unit: Unit) -> BackSpec:
    (spec,) = place_backs(unit, expand(unit))
    return spec


def _board_ids(region: Region) -> set[str]:
    if not isinstance(region, Division):
        return set()
    out: set[str] = set()
    for item in region.items:
        if isinstance(item, Board):
            out.add(item.id)
        else:
            out |= _board_ids(item)
    return out


# Recognizing backs


def test_the_magic_start_overlay_back_follows_the_sides_floor_and_top() -> None:
    """The bottom edge follows the floor's underside rather than the plinth,
    and the top edge the top board's upper face, a face across a board's
    thickness, rather than the sides' ends at the same height."""
    result = scan(_magic_start())

    assert [panel.name for panel in result.panels] == ["Back"]
    back = _only_back(result.unit)
    assert back.name == "Back"
    assert back.irregular is False
    assert back.h_min == BackEdge(0.0, _follows("Left", Face.MIN))
    assert back.h_max == BackEdge(0.0, _follows("Right", Face.MAX))
    assert back.v_min == BackEdge(100.0, _follows("Floor", Face.MIN))
    assert back.v_max == BackEdge(0.0, _follows("Top", Face.MAX))
    assert back.rear_offset_mm == pytest.approx(0.0)
    assert back.size_mm == Vec3(500.0, 3.0, 660.0)


def test_an_overlay_back_at_the_minimum_of_the_depth_axis_is_a_back() -> None:
    result = scan(_carcass(_box("Back", (0.0, -3.0, 0.0), (600.0, 3.0, 900.0))))

    assert result.unit.front_at_min is False
    back = _only_back(result.unit)
    assert back.h_min.follows == _follows("Left", Face.MIN)
    assert back.v_max.follows == _follows("Top", Face.MAX)
    assert back.rear_offset_mm == pytest.approx(-3.0)


def test_a_back_captured_between_the_boards_follows_their_inner_faces() -> None:
    result = scan(_carcass(_box("Back", (18.0, 280.0, 18.0), (564.0, 6.0, 864.0))))

    assert result.unit.front_at_min is True
    back = _only_back(result.unit)
    assert back.h_min.follows == _follows("Left", Face.MAX)
    assert back.h_max.follows == _follows("Right", Face.MIN)
    assert back.v_min.follows == _follows("Bottom", Face.MAX)
    assert back.v_max.follows == _follows("Top", Face.MIN)
    assert back.rear_offset_mm == pytest.approx(-20.0)


def test_a_per_opening_back_follows_the_divider_beside_it() -> None:
    result = scan(_carcass(_box("Back", (18.0, 280.0, 18.0), (273.0, 6.0, 864.0))))

    back = _only_back(result.unit)
    assert back.h_min.follows == _follows("Left", Face.MAX)
    assert back.h_max.follows == _follows("Divider", Face.MIN)
    assert back.h_max.outer_offset_mm == pytest.approx(309.0)


def test_an_edge_meeting_no_board_face_follows_the_outer_face() -> None:
    result = scan(_carcass(_box("Back", (10.0, 300.0, 0.0), (580.0, 3.0, 900.0))))

    back = _only_back(result.unit)
    assert back.h_min == BackEdge(10.0, None)
    assert back.h_max == BackEdge(10.0, None)
    assert back.v_min.follows == _follows("Bottom", Face.MIN)


def test_with_the_facing_unknown_nothing_is_a_back() -> None:
    """Two overlay backs, one proud of each face, vote opposite ways, and
    the members are flush at both ends, so the facing stays unknown."""
    result = scan(
        _carcass(
            _box("Front", (0.0, -3.0, 0.0), (600.0, 3.0, 900.0)),
            _box("Rear", (0.0, 300.0, 0.0), (600.0, 3.0, 900.0)),
        )
    )

    assert result.unit.front_at_min is None
    assert result.unit.backs == ()
    assert sorted(panel.name for panel in result.panels) == ["Front", "Rear"]


def test_a_stock_thick_panel_proud_of_the_front_is_a_door_not_a_back() -> None:
    result = scan(
        _carcass(
            _box("Door", (0.0, -18.0, 0.0), (600.0, 18.0, 900.0)),
            _box("Back", (0.0, 300.0, 0.0), (600.0, 3.0, 900.0)),
        )
    )

    assert result.unit.front_at_min is True
    assert [back.name for back in result.unit.backs] == ["Back"]
    assert sorted(panel.name for panel in result.panels) == ["Back", "Door"]


def test_a_given_facing_that_disagrees_with_a_panel_makes_it_no_back() -> None:
    """A panel only follows as a back when its own reading agrees with the
    unit's facing, so it never follows the front."""
    boxes = _carcass(_box("Back", (0.0, 300.0, 0.0), (600.0, 3.0, 900.0)))

    assert scan(boxes, front_at_min=False).unit.backs == ()


def test_an_irregular_back_is_recognized_as_irregular() -> None:
    boxes = _carcass(
        _box("Back", (0.0, 300.0, 0.0), (600.0, 3.0, 900.0), irregular=True)
    )

    assert _only_back(scan(boxes).unit).irregular is True


# Placing backs


def _resized(unit: Unit, dx_mm: float, dy_mm: float, dz_mm: float) -> Unit:
    size_mm = unit.size_mm
    return set_unit_size(
        unit,
        Vec3(size_mm.x_mm + dx_mm, size_mm.y_mm + dy_mm, size_mm.z_mm + dz_mm),
    )


def test_a_magic_start_back_sits_where_it_was_read() -> None:
    spec = _placed(scan(_magic_start()).unit)

    assert spec == BackSpec(
        "Back", False, Vec3(500.0, 3.0, 660.0), Vec3(0.0, 397.0, 100.0)
    )


def test_a_deeper_magic_start_keeps_its_back_on_the_sides_rear_face() -> None:
    spec = _placed(_resized(scan(_magic_start()).unit, 0.0, 50.0, 0.0))

    assert spec.corner_mm.y_mm == pytest.approx(447.0, abs=_TOL_MM)
    assert spec.size_mm.y_mm == pytest.approx(3.0, abs=_TOL_MM)


def test_a_wider_magic_start_back_spans_both_sides() -> None:
    spec = _placed(_resized(scan(_magic_start()).unit, 120.0, 0.0, 0.0))

    assert spec.corner_mm.x_mm == pytest.approx(0.0, abs=_TOL_MM)
    assert spec.size_mm.x_mm == pytest.approx(620.0, abs=_TOL_MM)


def test_a_taller_magic_start_back_runs_from_the_floor_to_the_new_top() -> None:
    spec = _placed(_resized(scan(_magic_start()).unit, 0.0, 0.0, 40.0))

    assert spec.corner_mm.z_mm == pytest.approx(100.0, abs=_TOL_MM)
    assert spec.corner_mm.z_mm + spec.size_mm.z_mm == pytest.approx(800.0, abs=_TOL_MM)


def test_an_edge_on_the_outer_face_keeps_its_distance_from_it() -> None:
    unit = scan(_carcass(_box("Back", (10.0, 300.0, 0.0), (580.0, 3.0, 900.0)))).unit
    spec = _placed(_resized(unit, 100.0, 0.0, 0.0))

    assert spec.corner_mm.x_mm == pytest.approx(10.0, abs=_TOL_MM)
    assert spec.size_mm.x_mm == pytest.approx(680.0, abs=_TOL_MM)


def test_a_renamed_board_is_still_followed() -> None:
    unit = scan(_magic_start()).unit
    renames = {"Floor": "Floor001"}
    renamed = dataclasses.replace(unit, backs=renamed_back_boards(unit.backs, renames))
    back = _only_back(renamed)

    assert back.v_min.follows == _follows("Floor001", Face.MIN)
    assert back.h_min == _only_back(unit).h_min


def test_an_edge_whose_board_is_gone_falls_to_the_outer_face() -> None:
    """Merging away the divider a per-opening back's edge lies on succeeds,
    and the edge then keeps the distance it had at the read to the outer
    face."""
    unit = scan(_carcass(_box("Back", (18.0, 280.0, 18.0), (273.0, 6.0, 864.0)))).unit
    merged = merge_at(unit, "Divider")
    assert "Divider" not in _board_ids(merged.root)

    spec = _placed(_resized(merged, 100.0, 0.0, 0.0))

    assert spec.corner_mm.x_mm == pytest.approx(18.0, abs=_TOL_MM)
    assert spec.corner_mm.x_mm + spec.size_mm.x_mm == pytest.approx(
        700.0 - 309.0, abs=_TOL_MM
    )


def test_a_back_left_no_width_is_refused_by_name() -> None:
    unit = scan(_carcass(_box("Back", (0.0, 300.0, 0.0), (300.0, 3.0, 900.0)))).unit
    assert _only_back(unit).h_max == BackEdge(300.0, None)

    narrow = _resized(unit, -320.0, 0.0, 0.0)

    with pytest.raises(BackFitError) as raised:
        place_backs(narrow, expand(narrow))

    assert raised.value.name == "Back"


def test_an_irregular_back_moves_its_low_corner_and_keeps_its_size() -> None:
    boxes = [
        _box("Back", (0.0, 397.0, 100.0), (500.0, 3.0, 660.0), irregular=True)
        if box.name == "Back"
        else box
        for box in _magic_start()
    ]
    unit = scan(boxes).unit
    deeper = _resized(unit, 0.0, 50.0, 0.0)

    spec = _placed(deeper)

    assert spec.irregular is True
    assert spec.size_mm == Vec3(500.0, 3.0, 660.0)
    assert spec.corner_mm == Vec3(0.0, 447.0, 100.0)


def test_an_irregular_backs_low_edge_follows_a_moving_divider() -> None:
    """A back over the right opening starts at the divider's right face;
    widening the unit moves the divider, and the back's low corner with it."""
    unit = scan(
        _carcass(
            _box("Back", (309.0, 280.0, 18.0), (273.0, 6.0, 864.0), irregular=True)
        )
    ).unit
    assert _only_back(unit).h_min.follows == _follows("Divider", Face.MAX)

    spec = _placed(_resized(unit, 100.0, 0.0, 0.0))

    assert spec.corner_mm == Vec3(359.0, 280.0, 18.0)
    assert spec.size_mm == Vec3(273.0, 6.0, 864.0)
