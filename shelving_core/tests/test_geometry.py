"""Construction and axis accessors for ``Vec3`` and ``Space``."""

from shelving_core.geometry import Space, Vec3


def test_vec3_holds_its_three_components() -> None:
    v = Vec3(x_mm=1.0, y_mm=2.0, z_mm=3.0)
    assert v.x_mm == 1.0
    assert v.y_mm == 2.0
    assert v.z_mm == 3.0


def test_space_extent_mm_indexes_the_size_components() -> None:
    space = Space(origin=Vec3(10.0, 20.0, 30.0), size=Vec3(100.0, 200.0, 300.0))
    assert space.extent_mm(0) == 100.0
    assert space.extent_mm(1) == 200.0
    assert space.extent_mm(2) == 300.0


def test_space_max_corner_adds_origin_and_size() -> None:
    space = Space(origin=Vec3(10.0, 20.0, 30.0), size=Vec3(100.0, 200.0, 300.0))
    assert space.max_corner() == Vec3(110.0, 220.0, 330.0)
