"""``layout.schema.json`` is a valid Draft 2020-12 schema and matches ``to_dict``.

The schema is the published interop contract. ``from_dict`` does not consult it
at runtime (the dataclass constructors are the guard), so these tests are what
keep the schema honest against the model.
"""

import json
from collections.abc import Mapping
from importlib.resources import files
from typing import Any

import jsonschema  # type: ignore[import-untyped]  # untyped third-party API
import pytest
from jsonschema import Draft202012Validator

from shelving_core.layout import (
    Carcass,
    Divider,
    Fill,
    Fixed,
    LapOrder,
    Leaf,
    Orientation,
    Split,
    Weighted,
)
from shelving_core.materials import MaterialId

PLY = MaterialId("ply18")
MDF = MaterialId("mdf12")


def _schema() -> Mapping[str, object]:
    # Parsed JSON handed only to the untyped jsonschema API; its internal shape
    # is jsonschema's contract, not this suite's, so it stays at object.
    text = files("shelving_core").joinpath("layout.schema.json").read_text()
    loaded: Mapping[str, object] = json.loads(text)
    return loaded


def _nested_carcass() -> Carcass:
    inner = Split(
        orientation=Orientation.VERTICAL,
        children=[Leaf(id="b"), Leaf(id="c"), Leaf(id="d")],
        rules=[Fill(), Weighted(2.0), Fixed(150.0)],
        dividers=[
            Divider(material=None, id="dv1"),
            Divider(material=MDF, lap=LapOrder.THROUGH, id="dv2"),
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


def _leaf_carcass() -> Carcass:
    return Carcass(
        width_mm=600.0,
        height_mm=600.0,
        depth_mm=300.0,
        default_material=PLY,
        root=Leaf(id="only"),
        id="unit-leaf",
    )


def test_schema_file_is_a_valid_draft202012_schema() -> None:
    Draft202012Validator.check_schema(_schema())


@pytest.mark.parametrize("carcass", [_leaf_carcass(), _nested_carcass()])
def test_to_dict_output_validates_against_schema(carcass: Carcass) -> None:
    Draft202012Validator(_schema()).validate(carcass.to_dict())


def _valid_doc() -> dict[str, Any]:
    # Parsed external JSON is a genuine type-erasing boundary, and the corruption
    # helpers below subscript through several levels, so this is Any rather than
    # object: a plain, freely mutable dict (not the CarcassDoc TypedDict) that
    # each helper can corrupt one field of without fighting the type checker.
    loaded: dict[str, Any] = json.loads(_nested_carcass().to_json())
    return loaded


def _with_bad_schema_version() -> dict[str, Any]:
    doc = _valid_doc()
    doc["schema_version"] = 2
    return doc


def _with_unknown_kind() -> dict[str, Any]:
    doc = _valid_doc()
    doc["carcass"]["root"] = {"kind": "triple", "id": "x"}
    return doc


def _with_unknown_rule_type() -> dict[str, Any]:
    doc = _valid_doc()
    doc["carcass"]["root"]["rules"][0] = {"type": "elastic"}
    return doc


def _with_missing_required_key() -> dict[str, Any]:
    doc = _valid_doc()
    del doc["carcass"]["default_material"]
    return doc


def _with_wrong_value_type() -> dict[str, Any]:
    doc = _valid_doc()
    doc["carcass"]["width_mm"] = "900"
    return doc


def _with_negative_size_mm() -> dict[str, Any]:
    doc = _valid_doc()
    doc["carcass"]["root"]["rules"][0] = {"type": "fixed", "size_mm": -5.0}
    return doc


def _with_legacy_default_thickness() -> dict[str, Any]:
    doc = _valid_doc()
    doc["carcass"]["default_thickness_mm"] = 18.0
    return doc


def _with_legacy_divider_thickness() -> dict[str, Any]:
    doc = _valid_doc()
    doc["carcass"]["root"]["dividers"][0]["thickness_mm"] = 18.0
    return doc


@pytest.mark.parametrize(
    "doc",
    [
        _with_bad_schema_version(),
        _with_unknown_kind(),
        _with_unknown_rule_type(),
        _with_missing_required_key(),
        _with_wrong_value_type(),
        _with_negative_size_mm(),
        _with_legacy_default_thickness(),
        _with_legacy_divider_thickness(),
    ],
)
def test_invalid_docs_fail_schema_validation(doc: dict[str, Any]) -> None:
    with pytest.raises(jsonschema.ValidationError):
        Draft202012Validator(_schema()).validate(doc)
