"""``materials.schema.json`` is a valid Draft 2020-12 schema and matches ``to_dict``.

The schema is the published interop contract for the material catalog.
``Catalog.from_dict`` does not consult it at runtime (the dataclass constructors
are the guard), so these tests keep the schema honest against the model.
"""

import json
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # untyped third-party API
import pytest
from jsonschema import Draft202012Validator

from shelving_core.materials import Catalog, MaterialEntry, MaterialId


def _schema() -> Mapping[str, object]:
    text = files("shelving_core").joinpath("materials.schema.json").read_text()
    loaded: Mapping[str, object] = json.loads(text)
    return loaded


def _entry(mid: str, thickness_mm: float, nominal: str | None) -> MaterialEntry:
    return MaterialEntry(
        id=MaterialId(mid),
        name=f"{mid} panel",
        thickness_mm=thickness_mm,
        material_type="plywood",
        nominal_thickness=nominal,
    )


def _two_entry_catalog() -> Catalog:
    entries = (
        _entry("ply18", 18.0, '3/4"'),
        _entry("mdf12", 12.0, None),
    )
    return Catalog(entries={entry.id: entry for entry in entries})


def _empty_catalog() -> Catalog:
    return Catalog(entries={})


def test_schema_file_is_a_valid_draft202012_schema() -> None:
    Draft202012Validator.check_schema(_schema())


@pytest.mark.parametrize("catalog", [_empty_catalog(), _two_entry_catalog()])
def test_to_dict_output_validates_against_schema(catalog: Catalog) -> None:
    Draft202012Validator(_schema()).validate(catalog.to_dict())


def _valid_doc() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(_two_entry_catalog().to_json())
    return loaded


def _with_bad_schema_version() -> dict[str, Any]:
    doc = _valid_doc()
    doc["schema_version"] = 2
    return doc


def _with_missing_required_key() -> dict[str, Any]:
    doc = _valid_doc()
    del doc["materials"][0]["material_type"]
    return doc


def _with_nonpositive_thickness() -> dict[str, Any]:
    doc = _valid_doc()
    doc["materials"][0]["thickness_mm"] = 0.0
    return doc


def _with_unexpected_extra_key() -> dict[str, Any]:
    doc = _valid_doc()
    doc["materials"][0]["grain"] = "long"
    return doc


@pytest.mark.parametrize(
    "doc",
    [
        _with_bad_schema_version(),
        _with_missing_required_key(),
        _with_nonpositive_thickness(),
        _with_unexpected_extra_key(),
    ],
)
def test_invalid_docs_fail_schema_validation(doc: dict[str, Any]) -> None:
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(_schema()).validate(doc)
