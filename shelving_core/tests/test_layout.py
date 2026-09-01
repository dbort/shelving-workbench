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


def _sample_carcass() -> Carcass:
    """A two-level tree whose inner split has three children."""
    inner = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(id="b"), Leaf(id="c"), Leaf(id="d")],
        rules=[Fill(), Weighted(2.0), Fixed(150.0)],
        dividers=[
            Divider(thickness_mm=None, id="dv1"),
            Divider(thickness_mm=12.0, id="dv2"),
        ],
        id="inner",
    )
    root = Split(
        orientation=Orientation.HORIZONTAL,
        children=[Leaf(id="a"), inner],
        rules=[Fixed(400.0), Fill()],
        dividers=[Divider(thickness_mm=None, id="dv0")],
        id="root",
    )
    return Carcass(
        width_mm=900.0,
        height_mm=1800.0,
        depth_mm=300.0,
        default_thickness_mm=18.0,
        root=root,
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
            default_thickness_mm=18.0,
            root=Leaf(),
        )


def test_carcass_height_must_be_positive() -> None:
    with pytest.raises(ValueError, match="height_mm"):
        Carcass(
            width_mm=900.0,
            height_mm=-1.0,
            depth_mm=300.0,
            default_thickness_mm=18.0,
            root=Leaf(),
        )


def test_carcass_depth_must_be_positive() -> None:
    with pytest.raises(ValueError, match="depth_mm"):
        Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=0.0,
            default_thickness_mm=18.0,
            root=Leaf(),
        )


def test_carcass_default_thickness_must_be_nonnegative() -> None:
    with pytest.raises(ValueError, match="default_thickness_mm"):
        Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_thickness_mm=-0.1,
            root=Leaf(),
        )


def test_fixed_size_must_be_positive() -> None:
    with pytest.raises(ValueError, match="size_mm"):
        Fixed(0.0)


def test_weighted_weight_must_be_positive() -> None:
    with pytest.raises(ValueError, match="weight"):
        Weighted(0.0)


def test_divider_thickness_must_be_nonnegative() -> None:
    with pytest.raises(ValueError, match="thickness_mm"):
        Divider(thickness_mm=-1.0)


def test_divider_thickness_none_is_allowed() -> None:
    assert Divider(thickness_mm=None).thickness_mm is None


def test_json_round_trip_preserves_ids_and_structure() -> None:
    carcass = _sample_carcass()

    restored = Carcass.from_dict(carcass.to_dict())
    assert restored == carcass

    restored_json = Carcass.from_json(carcass.to_json())
    assert restored_json == carcass

    root = restored.root
    assert isinstance(root, Split)
    assert root.id == "root"
    assert [child.id for child in root.children] == ["a", "inner"]
    inner = root.children[1]
    assert isinstance(inner, Split)
    assert [child.id for child in inner.children] == ["b", "c", "d"]
    assert [divider.id for divider in inner.dividers] == ["dv1", "dv2"]
    assert inner.dividers[0].thickness_mm is None
    assert inner.dividers[1].thickness_mm == 12.0
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
                    "width_mm": 900.0,
                    "height_mm": 1800.0,
                    "depth_mm": 300.0,
                    "default_thickness_mm": 18.0,
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
                    "width_mm": 900.0,
                    "height_mm": 1800.0,
                    "depth_mm": 300.0,
                    "default_thickness_mm": 18.0,
                    "root": {
                        "kind": "split",
                        "id": "r",
                        "orientation": "horizontal",
                        "children": [
                            {"kind": "leaf", "id": "a"},
                            {"kind": "leaf", "id": "b"},
                        ],
                        "rules": [{"type": "fill"}, {"type": "elastic"}],
                        "dividers": [{"id": "d", "thickness_mm": None}],
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
                    "width_mm": 900.0,
                    "height_mm": 1800.0,
                    "depth_mm": 300.0,
                    "root": {"kind": "leaf", "id": "a"},
                },
            }
        )
