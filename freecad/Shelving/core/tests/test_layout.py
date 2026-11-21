"""Construction and validation for the region-tree data model."""

import pytest

from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Insets,
    Lock,
    Unit,
    Void,
    constraint_regions,
    is_locked,
    new_id,
    region_lock,
)


def test_division_rejects_empty_items() -> None:
    with pytest.raises(ValueError, match="items"):
        Division(axis=Axis.X, items=[])


def test_unit_size_x_mm_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm.x_mm"):
        Unit(
            size_mm=Vec3(0.0, 1800.0, 300.0),
            root=Bay(),
        )


def test_unit_size_y_mm_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm.y_mm"):
        Unit(
            size_mm=Vec3(900.0, -1.0, 300.0),
            root=Bay(),
        )


def test_unit_size_z_mm_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm.z_mm"):
        Unit(
            size_mm=Vec3(900.0, 1800.0, 0.0),
            root=Bay(),
        )


@pytest.mark.parametrize("thickness_mm", [0.0, -18.0])
def test_board_thickness_mm_must_be_positive(thickness_mm: float) -> None:
    with pytest.raises(ValueError, match="thickness_mm"):
        Board(thickness_mm=thickness_mm)


@pytest.mark.parametrize("extent_mm", [0.0, -5.0])
def test_board_extent_mm_must_be_positive(extent_mm: float) -> None:
    with pytest.raises(ValueError, match="extent_mm"):
        Board(thickness_mm=18.0, extent_mm=extent_mm)


def test_a_lock_defaults_to_an_active_clear_lock_with_its_own_id() -> None:
    first, second = Lock("bay"), Lock("bay")
    assert (first.region_id, first.basis, first.active) == ("bay", Basis.CLEAR, True)
    assert first.id != second.id


def test_a_lock_holds_its_one_region_and_only_an_active_one_locks() -> None:
    on = Lock("A", Basis.WITH_NEXT)
    off = Lock("B", active=False)
    unit = Unit(
        size_mm=Vec3(300.0, 300.0, 618.0),
        root=Division(
            axis=Axis.Z,
            items=[Bay(size_mm=300.0, id="A"), Board(18.0), Bay(size_mm=300.0, id="B")],
        ),
        constraints=(on, off),
    )
    assert constraint_regions(unit, on) == ("A",)
    assert region_lock(unit, "A") is on
    assert region_lock(unit, "B") is off
    assert is_locked(unit, "A") and not is_locked(unit, "B")
    assert region_lock(unit, "C") is None


def test_insets_default_to_zero_on_all_six_faces() -> None:
    insets = Insets()
    assert insets.x_min_mm == 0.0
    assert insets.x_max_mm == 0.0
    assert insets.y_min_mm == 0.0
    assert insets.y_max_mm == 0.0
    assert insets.z_min_mm == 0.0
    assert insets.z_max_mm == 0.0


def test_new_id_calls_differ() -> None:
    assert new_id() != new_id()


def test_board_pinned_size_mm_defaults_to_none() -> None:
    assert Board(thickness_mm=18.0).pinned_size_mm is None


def test_board_pinned_size_mm_can_be_set() -> None:
    size_mm = Vec3(400.0, 18.0, 250.0)
    assert Board(thickness_mm=18.0, pinned_size_mm=size_mm).pinned_size_mm == size_mm


def test_unit_depth_axis_and_front_at_min_default_to_none() -> None:
    unit = Unit(
        size_mm=Vec3(900.0, 1800.0, 300.0),
        root=Bay(),
    )
    assert unit.depth_axis is None
    assert unit.front_at_min is None


def test_unit_depth_axis_and_front_at_min_can_be_set() -> None:
    unit = Unit(
        size_mm=Vec3(900.0, 1800.0, 300.0),
        root=Bay(),
        depth_axis=Axis.Y,
        front_at_min=True,
    )
    assert unit.depth_axis is Axis.Y
    assert unit.front_at_min is True


def test_ids_survive_construction() -> None:
    board = Board(thickness_mm=18.0, id="my-board")
    bay = Bay(id="my-bay")
    void = Void(id="my-void")
    division = Division(axis=Axis.Z, items=[board], id="my-division")
    unit = Unit(
        size_mm=Vec3(900.0, 1800.0, 300.0),
        root=division,
        id="my-unit",
    )
    assert board.id == "my-board"
    assert bay.id == "my-bay"
    assert void.id == "my-void"
    assert division.id == "my-division"
    assert unit.id == "my-unit"
