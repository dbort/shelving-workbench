"""Construction validation and JSON round-tripping for the split-tree model."""

import pytest

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
from shelving_core.materials import MaterialId

PLY = MaterialId("ply18")
MDF = MaterialId("mdf12")


def _sample_carcass() -> Carcass:
    """A two-level tree whose inner split has three children."""
    inner = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(id="b"), Leaf(id="c"), Leaf(id="d")],
        rules=[Fill(), Weighted(2.0), Fixed(150.0)],
        dividers=[
            Divider(material=None, id="dv1"),
            Divider(material=MDF, lap="through", id="dv2"),
        ],
        id="inner",
    )
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[Leaf(id="a"), inner],
        rules=[Fixed(400.0), Fill()],
        dividers=[Divider(material=None, id="dv0")],
        id="root",
    )
    return Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_material=PLY,
        root=root,
        id="unit-1",
    )


def test_split_requires_at_least_two_children() -> None:
    with pytest.raises(ValueError, match="children"):
        Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf()],
            rules=[Fill()],
            dividers=[],
        )


def test_split_rules_must_match_children_count() -> None:
    with pytest.raises(ValueError, match="rules count"):
        Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf()],
            rules=[Fill()],
            dividers=[Divider()],
        )


def test_split_dividers_must_be_one_fewer_than_children() -> None:
    with pytest.raises(ValueError, match="dividers count"):
        Split(
            orientation=Orientation.HORIZONTAL,
            children=[Leaf(), Leaf()],
            rules=[Fill(), Fill()],
            dividers=[],
        )


def test_carcass_width_must_be_positive() -> None:
    with pytest.raises(ValueError, match="width_mm"):
        Carcass(
            width_mm=0.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_material=PLY,
            root=Leaf(),
        )


def test_carcass_height_must_be_positive() -> None:
    with pytest.raises(ValueError, match="height_mm"):
        Carcass(
            width_mm=900.0,
            height_mm=-1.0,
            depth_mm=300.0,
            default_material=PLY,
            root=Leaf(),
        )


def test_carcass_depth_must_be_positive() -> None:
    with pytest.raises(ValueError, match="depth_mm"):
        Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=0.0,
            default_material=PLY,
            root=Leaf(),
        )


def test_carcass_default_material_must_be_nonempty() -> None:
    with pytest.raises(ValueError, match="default_material"):
        Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_material=MaterialId(""),
            root=Leaf(),
        )


def test_fixed_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm"):
        Fixed(0.0)


def test_weighted_weight_must_be_positive() -> None:
    with pytest.raises(ValueError, match="weight"):
        Weighted(0.0)


def test_divider_defaults_have_no_material_or_lap() -> None:
    divider = Divider()
    assert divider.material is None
    assert divider.lap is None


def test_divider_lap_must_be_a_known_value() -> None:
    with pytest.raises(ValueError, match="lap"):
        Divider(lap="mitre")  # type: ignore[arg-type]  # negative test


def test_json_round_trip_preserves_ids_and_structure() -> None:
    carcass = _sample_carcass()

    restored = Carcass.from_dict(carcass.to_dict())
    assert restored == carcass

    restored_json = Carcass.from_json(carcass.to_json())
    assert restored_json == carcass

    assert restored.id == "unit-1"
    assert restored.default_material == "ply18"

    root = restored.root
    assert isinstance(root, Split)
    assert root.id == "root"
    assert [child.id for child in root.children] == ["a", "inner"]
    inner = root.children[1]
    assert isinstance(inner, Split)
    assert [child.id for child in inner.children] == ["b", "c", "d"]
    assert [divider.id for divider in inner.dividers] == ["dv1", "dv2"]
    assert inner.dividers[0].material is None
    assert inner.dividers[0].lap is None
    assert inner.dividers[1].material == "mdf12"
    assert inner.dividers[1].lap == "through"
    assert isinstance(inner.rules[1], Weighted)
    assert isinstance(inner.rules[2], Fixed)


def test_from_dict_rejects_bad_schema_version() -> None:
    doc = _sample_carcass().to_dict()
    bad = {**doc, "schema_version": 2}
    with pytest.raises(ValueError, match="schema_version"):
        Carcass.from_dict(bad)


def test_from_dict_rejects_missing_schema_version() -> None:
    body = _sample_carcass().to_dict()["carcass"]
    with pytest.raises(ValueError, match="schema_version"):
        Carcass.from_dict({"carcass": body})


def test_from_dict_rejects_unknown_bay_kind() -> None:
    with pytest.raises(ValueError, match="kind"):
        Carcass.from_dict(
            {
                "schema_version": 1,
                "carcass": {
                    "id": "u",
                    "width_mm": 900.0,
                    "height_mm": 1800.0,
                    "depth_mm": 300.0,
                    "default_material": "ply18",
                    "root": {"kind": "triple", "id": "x"},
                },
            }
        )


def test_from_dict_rejects_unknown_rule_type() -> None:
    with pytest.raises(ValueError, match="rule type"):
        Carcass.from_dict(
            {
                "schema_version": 1,
                "carcass": {
                    "id": "u",
                    "width_mm": 900.0,
                    "height_mm": 1800.0,
                    "depth_mm": 300.0,
                    "default_material": "ply18",
                    "root": {
                        "kind": "split",
                        "id": "r",
                        "orientation": "horizontal",
                        "children": [
                            {"kind": "leaf", "id": "a"},
                            {"kind": "leaf", "id": "b"},
                        ],
                        "rules": [{"type": "fill"}, {"type": "elastic"}],
                        "dividers": [{"id": "d"}],
                    },
                },
            }
        )


def test_from_dict_rejects_structurally_malformed_doc() -> None:
    with pytest.raises(ValueError, match="missing required key"):
        Carcass.from_dict(
            {
                "schema_version": 1,
                "carcass": {
                    "id": "u",
                    "width_mm": 900.0,
                    "height_mm": 1800.0,
                    "depth_mm": 300.0,
                    "root": {"kind": "leaf", "id": "a"},
                },
            }
        )
