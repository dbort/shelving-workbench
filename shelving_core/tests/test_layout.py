"""Construction and validation for the region-tree data model."""

import pytest

from shelving_core.geometry import Vec3
from shelving_core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    Insets,
    Unit,
    Void,
    Weighted,
    new_id,
)
from shelving_core.materials import MaterialId

PLY = MaterialId("ply18")


def test_division_rejects_empty_items() -> None:
    with pytest.raises(ValueError, match="items"):
        Division(axis=Axis.X, items=[])


def test_unit_size_x_mm_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm.x_mm"):
        Unit(
            size_mm=Vec3(0.0, 1800.0, 300.0),
            default_material=PLY,
            root=Bay(),
        )


def test_unit_size_y_mm_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm.y_mm"):
        Unit(
            size_mm=Vec3(900.0, -1.0, 300.0),
            default_material=PLY,
            root=Bay(),
        )


def test_unit_size_z_mm_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm.z_mm"):
        Unit(
            size_mm=Vec3(900.0, 1800.0, 0.0),
            default_material=PLY,
            root=Bay(),
        )


def test_unit_default_material_must_be_nonempty() -> None:
    with pytest.raises(ValueError, match="default_material"):
        Unit(
            size_mm=Vec3(900.0, 1800.0, 300.0),
            default_material=MaterialId(""),
            root=Bay(),
        )


def test_fixed_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm"):
        Fixed(0.0)


def test_weighted_weight_must_be_positive() -> None:
    with pytest.raises(ValueError, match="weight"):
        Weighted(0.0)


def test_fixed_basis_defaults_to_clear() -> None:
    assert Fixed(400.0).basis is Basis.CLEAR


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


def test_ids_survive_construction() -> None:
    board = Board(id="my-board")
    bay = Bay(id="my-bay")
    void = Void(id="my-void")
    division = Division(axis=Axis.Z, items=[board], id="my-division")
    unit = Unit(
        size_mm=Vec3(900.0, 1800.0, 300.0),
        default_material=PLY,
        root=division,
        id="my-unit",
    )
    assert board.id == "my-board"
    assert bay.id == "my-bay"
    assert void.id == "my-void"
    assert division.id == "my-division"
    assert unit.id == "my-unit"
