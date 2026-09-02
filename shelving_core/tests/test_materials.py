"""Construction guards, mapping protocol, and JSON round-tripping for the catalog."""

import pytest

from shelving_core.materials import Catalog, MaterialEntry, MaterialId


def _entry(
    mid: str,
    *,
    name: str | None = None,
    thickness_mm: float = 18.0,
    material_type: str = "plywood",
    nominal_thickness: str | None = None,
) -> MaterialEntry:
    return MaterialEntry(
        id=MaterialId(mid),
        name=name if name is not None else f"{mid} panel",
        thickness_mm=thickness_mm,
        material_type=material_type,
        nominal_thickness=nominal_thickness,
    )


def _catalog(*entries: MaterialEntry) -> Catalog:
    return Catalog(entries={entry.id: entry for entry in entries})


def test_entry_rejects_empty_id() -> None:
    with pytest.raises(ValueError, match="id"):
        _entry("")


def test_entry_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        _entry("ply18", name="")


def test_entry_rejects_empty_material_type() -> None:
    with pytest.raises(ValueError, match="material_type"):
        _entry("ply18", material_type="")


def test_entry_rejects_nonpositive_thickness() -> None:
    with pytest.raises(ValueError, match="thickness_mm"):
        _entry("ply18", thickness_mm=0.0)


def test_getitem_returns_the_entry() -> None:
    entry = _entry("ply18")
    assert _catalog(entry)[MaterialId("ply18")] is entry


def test_getitem_missing_id_raises_keyerror_with_message() -> None:
    catalog = _catalog(_entry("ply18"))
    with pytest.raises(KeyError, match="no material 'mdf12' in catalog"):
        catalog[MaterialId("mdf12")]


def test_get_returns_none_for_a_missing_id() -> None:
    catalog = _catalog(_entry("ply18"))
    assert catalog.get(MaterialId("ply18")) is not None
    assert catalog.get(MaterialId("mdf12")) is None


def test_contains_checks_membership_by_id() -> None:
    catalog = _catalog(_entry("ply18"))
    assert MaterialId("ply18") in catalog
    assert MaterialId("mdf12") not in catalog


def test_iter_yields_entry_values_in_insertion_order() -> None:
    a, b, c = _entry("a"), _entry("b"), _entry("c")
    assert list(_catalog(a, b, c)) == [a, b, c]


def test_json_round_trip_preserves_order_and_every_field() -> None:
    catalog = _catalog(
        _entry("ply18", name="18 mm birch ply", nominal_thickness='3/4"'),
        _entry("mdf12", name="12 mm MDF", thickness_mm=12.0, material_type="mdf"),
        _entry("sw20", name="20 mm oak", thickness_mm=20.0, material_type="solid wood"),
    )

    restored = Catalog.from_dict(catalog.to_dict())
    assert restored == catalog

    restored_json = Catalog.from_json(catalog.to_json())
    assert restored_json == catalog

    assert [entry.id for entry in restored_json] == ["ply18", "mdf12", "sw20"]
    ply = restored_json[MaterialId("ply18")]
    assert ply.name == "18 mm birch ply"
    assert ply.nominal_thickness == '3/4"'
    mdf = restored_json[MaterialId("mdf12")]
    assert mdf.thickness_mm == 12.0
    assert mdf.material_type == "mdf"
    assert mdf.nominal_thickness is None


def test_to_dict_shape_matches_the_published_format() -> None:
    doc = _catalog(_entry("ply18", name="18 mm ply")).to_dict()
    assert doc == {
        "schema_version": 1,
        "materials": [
            {
                "id": "ply18",
                "name": "18 mm ply",
                "thickness_mm": 18.0,
                "material_type": "plywood",
                "nominal_thickness": None,
            }
        ],
    }


def test_from_dict_rejects_bad_schema_version() -> None:
    doc = _catalog(_entry("ply18")).to_dict()
    with pytest.raises(ValueError, match="schema_version"):
        Catalog.from_dict({**doc, "schema_version": 2})


def test_from_dict_rejects_missing_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        Catalog.from_dict({"materials": []})


def test_from_dict_rejects_materials_that_are_not_a_list() -> None:
    with pytest.raises(ValueError, match="materials"):
        Catalog.from_dict({"schema_version": 1, "materials": {}})


def test_from_dict_rejects_a_duplicate_id() -> None:
    with pytest.raises(ValueError, match="duplicate material id"):
        Catalog.from_dict(
            {
                "schema_version": 1,
                "materials": [
                    {
                        "id": "ply18",
                        "name": "first",
                        "thickness_mm": 18.0,
                        "material_type": "plywood",
                        "nominal_thickness": None,
                    },
                    {
                        "id": "ply18",
                        "name": "second",
                        "thickness_mm": 19.0,
                        "material_type": "plywood",
                        "nominal_thickness": None,
                    },
                ],
            }
        )


def test_from_dict_rejects_a_missing_required_key() -> None:
    with pytest.raises(ValueError, match="missing required key"):
        Catalog.from_dict(
            {
                "schema_version": 1,
                "materials": [
                    {"id": "ply18", "name": "ply", "material_type": "plywood"}
                ],
            }
        )


def test_from_dict_rejects_a_wrong_value_type() -> None:
    with pytest.raises(ValueError, match="thickness_mm"):
        Catalog.from_dict(
            {
                "schema_version": 1,
                "materials": [
                    {
                        "id": "ply18",
                        "name": "ply",
                        "thickness_mm": "18",
                        "material_type": "plywood",
                        "nominal_thickness": None,
                    }
                ],
            }
        )
