"""Material catalog data model and its JSON form.

A ``Catalog`` is an ordered collection of ``MaterialEntry`` records keyed by a
stable string id. Each entry carries the one dimension the solver needs, the
actual panel ``thickness_mm``, plus descriptive fields. Panels and dividers in
``shelving_core.layout`` reference an entry by ``MaterialId``; the solver
resolves the id to a thickness.

The JSON form is a stable interop contract, published as
``materials.schema.json`` beside this module. ``Catalog.from_dict`` rebuilds the
catalog through the real constructors so their validation runs; it does not
consult the schema at runtime. The schema is kept honest by
``tests/test_materials_schema.py``.

This module depends only on the standard library and imports nothing from
``shelving_core``, so ``layout`` may import ``MaterialId`` from here without a
cycle.
"""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Literal, NewType, TypedDict

MaterialId = NewType("MaterialId", str)

MATERIALS_SCHEMA_VERSION: int = 1


@dataclass(frozen=True)
class MaterialEntry:
    """One stock entry: an id, descriptive fields, and the actual thickness.

    ``thickness_mm`` is the measured panel thickness the solver subtracts for
    dividers and the carcass shell. ``nominal_thickness`` is a free human label
    for the callout thickness (``'3/4"'``, ``'18 mm'``), not a millimetre value,
    hence no ``_mm`` suffix; ``None`` when unset.
    """

    id: MaterialId
    name: str
    thickness_mm: float
    material_type: str
    nominal_thickness: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("MaterialEntry.id must be non-empty")
        if not self.name:
            raise ValueError("MaterialEntry.name must be non-empty")
        if not self.material_type:
            raise ValueError("MaterialEntry.material_type must be non-empty")
        if self.thickness_mm <= 0:
            raise ValueError(
                f"MaterialEntry.thickness_mm must be > 0, got {self.thickness_mm}"
            )


@dataclass(frozen=True)
class Catalog:
    """Insertion-ordered map from ``MaterialId`` to ``MaterialEntry``."""

    entries: Mapping[MaterialId, MaterialEntry]

    def __getitem__(self, mid: MaterialId) -> MaterialEntry:
        try:
            return self.entries[mid]
        except KeyError:
            raise KeyError(f"no material {mid!r} in catalog") from None

    def get(self, mid: MaterialId) -> MaterialEntry | None:
        return self.entries.get(mid)

    def __contains__(self, mid: object) -> bool:
        return mid in self.entries

    def __iter__(self) -> Iterator[MaterialEntry]:
        return iter(self.entries.values())

    def to_dict(self) -> "CatalogDoc":
        return {
            "schema_version": 1,
            "materials": [
                {
                    "id": str(entry.id),
                    "name": entry.name,
                    "thickness_mm": entry.thickness_mm,
                    "material_type": entry.material_type,
                    "nominal_thickness": entry.nominal_thickness,
                }
                for entry in self.entries.values()
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Catalog":
        # Parsed external JSON is a type-erasing boundary: every value
        # arrives as ``object`` and is narrowed with isinstance before it
        # reaches a constructor.
        version = data.get("schema_version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != MATERIALS_SCHEMA_VERSION
        ):
            raise ValueError(
                f"schema_version must be {MATERIALS_SCHEMA_VERSION}, got {version!r}"
            )
        raw_materials = data.get("materials")
        if not isinstance(raw_materials, list):
            raise ValueError(f"'materials' must be a JSON array, got {raw_materials!r}")
        entries: dict[MaterialId, MaterialEntry] = {}
        for node in raw_materials:
            obj = _as_mapping(node, "material entry")
            entry = MaterialEntry(
                id=MaterialId(_req_str(obj, "id")),
                name=_req_str(obj, "name"),
                thickness_mm=_req_number(obj, "thickness_mm"),
                material_type=_req_str(obj, "material_type"),
                nominal_thickness=_opt_str(obj, "nominal_thickness"),
            )
            if entry.id in entries:
                raise ValueError(f"duplicate material id {entry.id!r}")
            entries[entry.id] = entry
        return cls(entries=entries)

    @classmethod
    def from_json(cls, s: str) -> "Catalog":
        parsed = json.loads(s)
        if not isinstance(parsed, dict):
            raise ValueError("top-level JSON value must be an object")
        return cls.from_dict(parsed)


class MaterialEntryDoc(TypedDict):
    id: str
    name: str
    thickness_mm: float
    material_type: str
    nominal_thickness: str | None


class CatalogDoc(TypedDict):
    schema_version: Literal[1]
    materials: list[MaterialEntryDoc]


def _as_mapping(value: object, what: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{what} must be a JSON object, got {value!r}")
    narrowed: Mapping[str, object] = value
    return narrowed


def _req_number(obj: Mapping[str, object], key: str) -> float:
    if key not in obj:
        raise ValueError(f"missing required key {key!r}")
    value = obj[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"key {key!r} must be a number, got {value!r}")
    return float(value)


def _req_str(obj: Mapping[str, object], key: str) -> str:
    if key not in obj:
        raise ValueError(f"missing required key {key!r}")
    value = obj[key]
    if not isinstance(value, str):
        raise ValueError(f"key {key!r} must be a string, got {value!r}")
    return value


def _opt_str(obj: Mapping[str, object], key: str) -> str | None:
    if key not in obj or obj[key] is None:
        return None
    value = obj[key]
    if not isinstance(value, str):
        raise ValueError(f"key {key!r} must be a string or null, got {value!r}")
    return value
