"""Carcass expansion: shell geometry, divider planks, identity, and errors."""

import pytest

from shelving_core.expand import PlankRole, PlankSpec, Vec3, expand, total_volume_mm3
from shelving_core.layout import (
    Carcass,
    Divider,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
    Weighted,
)
from shelving_core.materials import Catalog, MaterialEntry, MaterialId
from shelving_core.solver import LayoutSolveError, solve

PLY18 = MaterialId("ply18")
MDF12 = MaterialId("mdf12")


def _catalog() -> Catalog:
    return Catalog(
        entries={
            PLY18: MaterialEntry(
                id=PLY18, name="18 mm ply", thickness_mm=18.0, material_type="plywood"
            ),
            MDF12: MaterialEntry(
                id=MDF12, name="12 mm MDF", thickness_mm=12.0, material_type="mdf"
            ),
        }
    )


def _assert_vec3(actual: Vec3, x_mm: float, y_mm: float, z_mm: float) -> None:
    assert actual.x_mm == pytest.approx(x_mm, abs=1e-6)
    assert actual.y_mm == pytest.approx(y_mm, abs=1e-6)
    assert actual.z_mm == pytest.approx(z_mm, abs=1e-6)


def _by_role(specs: list[PlankSpec], role: PlankRole) -> PlankSpec:
    matches = [spec for spec in specs if spec.role == role]
    assert len(matches) == 1, f"expected exactly one {role}, got {len(matches)}"
    return matches[0]


def test_bare_leaf_emits_four_shell_planks() -> None:
    carcass = Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Leaf(),
    )
    specs = expand(carcass, _catalog())
    assert [spec.role for spec in specs] == [
        PlankRole.BOTTOM,
        PlankRole.TOP,
        PlankRole.LEFT_SIDE,
        PlankRole.RIGHT_SIDE,
    ]

    bottom = _by_role(specs, PlankRole.BOTTOM)
    _assert_vec3(bottom.size, 900.0, 300.0, 18.0)
    _assert_vec3(bottom.placement, 0.0, 0.0, 0.0)

    top = _by_role(specs, PlankRole.TOP)
    _assert_vec3(top.size, 900.0, 300.0, 18.0)
    _assert_vec3(top.placement, 0.0, 0.0, 1782.0)

    left = _by_role(specs, PlankRole.LEFT_SIDE)
    _assert_vec3(left.size, 18.0, 300.0, 1764.0)
    _assert_vec3(left.placement, 0.0, 0.0, 18.0)

    right = _by_role(specs, PlankRole.RIGHT_SIDE)
    _assert_vec3(right.size, 18.0, 300.0, 1764.0)
    _assert_vec3(right.placement, 882.0, 0.0, 18.0)

    assert all(spec.material == PLY18 for spec in specs)

    expected_volume = 2 * (900.0 * 300.0 * 18.0) + 2 * (18.0 * 300.0 * 1764.0)
    assert total_volume_mm3(specs) == pytest.approx(expected_volume, abs=1e-6)


def test_horizontal_split_adds_a_shelf_plank() -> None:
    divider = Divider(id="d0")
    carcass = Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf()],
            rules=[Fill(), Fill()],
            dividers=[divider],
        ),
    )
    catalog = _catalog()
    specs = expand(carcass, catalog)
    assert len(specs) == 5

    shelf = specs[4]
    assert shelf.role == PlankRole.SHELF
    assert shelf.node_id == "d0"
    _assert_vec3(shelf.size, 900.0 - 2 * 18.0, 300.0, 18.0)

    solved_rect = solve(carcass, catalog)[divider.id]
    _assert_vec3(shelf.placement, solved_rect.x_mm, 0.0, solved_rect.z_mm)
    _assert_vec3(shelf.size, solved_rect.width_mm, 300.0, solved_rect.height_mm)


def test_vertical_split_adds_a_divider_plank() -> None:
    carcass = Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.VERTICAL,
            children=[Leaf(), Leaf()],
            rules=[Fill(), Fill()],
            dividers=[Divider(id="d0")],
        ),
    )
    specs = expand(carcass, _catalog())
    assert len(specs) == 5

    divider = specs[4]
    assert divider.role == PlankRole.DIVIDER
    _assert_vec3(divider.size, 18.0, 300.0, 1800.0 - 2 * 18.0)


def test_divider_material_override_is_confined_to_that_plank() -> None:
    catalog = _catalog()

    def build(divider: Divider) -> Carcass:
        return Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_material=PLY18,
            root=Split(
                orientation=Orientation.VERTICAL,
                children=[Leaf(id="left"), Leaf(id="right")],
                rules=[Fill(), Fill()],
                dividers=[divider],
            ),
        )

    baseline = build(Divider(id="d0"))
    overridden = build(Divider(material=MDF12, id="d0"))

    override_plank = expand(overridden, catalog)[4]
    assert override_plank.material == MDF12
    # A vertical divider's thickness runs along X; the override drops it 18 -> 12.
    assert override_plank.size.x_mm == pytest.approx(12.0, abs=1e-6)

    # The shell still resolves to the 18 mm default, so the interior span is
    # unchanged; only the thinner divider frees space, widening each sibling
    # opening relative to the inherited-thickness case.
    baseline_opening = solve(baseline, catalog)["left"].width_mm
    override_opening = solve(overridden, catalog)["left"].width_mm
    assert override_opening > baseline_opening


def test_shell_node_ids_are_stable_and_role_scoped() -> None:
    carcass = Carcass(
        width_mm=800.0,
        height_mm=1600.0,
        depth_mm=280.0,
        default_material=PLY18,
        root=Leaf(),
    )
    catalog = _catalog()
    first = expand(carcass, catalog)
    second = expand(carcass, catalog)

    for spec in first:
        assert spec.node_id == f"{carcass.id}:{spec.role.value}"
    assert [spec.node_id for spec in first] == [spec.node_id for spec in second]


def _nested_sample() -> Carcass:
    """4 dividers over 3 splits, one override."""
    top = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(), Leaf(), Leaf()],
        rules=[Fill(), Fill(), Fill()],
        dividers=[Divider(material=MDF12), Divider()],
    )
    bottom = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(), Leaf()],
        rules=[Fixed(300.0), Weighted(2.0)],
        dividers=[Divider()],
    )
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[top, bottom],
        rules=[Weighted(1.0), Fixed(500.0)],
        dividers=[Divider()],
    )
    return Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=root,
    )


def test_nested_sample_count_and_volume() -> None:
    carcass = _nested_sample()
    catalog = _catalog()
    specs = expand(carcass, catalog)

    divider_count = 4
    assert len(specs) == 4 + divider_count

    thickness_mm = 18.0
    shell_volume = 2 * (carcass.width_mm * carcass.depth_mm * thickness_mm) + 2 * (
        thickness_mm * carcass.depth_mm * (carcass.height_mm - 2 * thickness_mm)
    )
    layout = solve(carcass, catalog)
    divider_ids = _collect_divider_ids(carcass.root)
    divider_volume = sum(
        layout[node_id].width_mm * carcass.depth_mm * layout[node_id].height_mm
        for node_id in divider_ids
    )
    assert total_volume_mm3(specs) == pytest.approx(
        shell_volume + divider_volume, abs=1e-6
    )


def _collect_divider_ids(bay: Leaf | Split) -> list[str]:
    if isinstance(bay, Leaf):
        return []
    ids: list[str] = []
    for child in bay.children:
        ids.extend(_collect_divider_ids(child))
    ids.extend(divider.id for divider in bay.dividers)
    return ids


def test_missing_default_material_raises_key_error() -> None:
    carcass = Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=MaterialId("absent"),
        root=Leaf(),
    )
    with pytest.raises(KeyError):
        expand(carcass, _catalog())


def test_overconstrained_layout_raises_layout_solve_error() -> None:
    carcass = Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY18,
        root=Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf()],
            rules=[Fixed(2000.0), Fixed(2000.0)],
            dividers=[Divider()],
        ),
    )
    with pytest.raises(LayoutSolveError):
        expand(carcass, _catalog())
