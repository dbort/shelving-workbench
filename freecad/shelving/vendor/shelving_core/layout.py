"""Split-tree data model for a shelving ``Carcass`` and its JSON form.

A ``Carcass`` is the shelving box: outer dimensions, a default material
reference, and a root ``Bay``. A ``Bay`` is either a ``Leaf`` (an open
compartment) or a ``Split`` (an orientation, an ordered list of two or more
child bays, one ``SplitRule`` per child, and one fewer ``Divider`` than
children).

The JSON form is a stable interop contract, published as
``layout.schema.json`` beside this module. ``Carcass.from_dict`` rebuilds a tree
through the real constructors so their validation runs; it does not consult the
schema at runtime. The schema is kept honest by ``tests/test_schema.py``.
"""

import enum
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal, TypedDict

from shelving_core.materials import MaterialId

SCHEMA_VERSION: int = 1


def new_id() -> str:
    """Fresh node identifier: the string form of a random UUID4."""
    return str(uuid.uuid4())


class Orientation(enum.StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


class LapOrder(enum.StrEnum):
    CAPTURED = "captured"
    THROUGH = "through"


@dataclass
class Fixed:
    """Rule: the child opening takes exactly ``size_mm``. Drives the layout."""

    size_mm: float

    def __post_init__(self) -> None:
        if self.size_mm <= 0:
            raise ValueError(f"Fixed.size_mm must be > 0, got {self.size_mm}")


@dataclass
class Weighted:
    """Rule: the child opening takes a share of slack proportional to ``weight``."""

    weight: float

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError(f"Weighted.weight must be > 0, got {self.weight}")


@dataclass
class Fill:
    """Rule: weight-1 shorthand for ``Weighted(1.0)``."""


SplitRule = Fixed | Weighted | Fill


@dataclass
class Leaf:
    """An open compartment. Carries only its persistent id."""

    id: str = field(default_factory=new_id)


@dataclass
class Divider:
    """The panel between two consecutive split children."""

    # ``None`` inherits ``Carcass.default_material``; the solver resolves the id
    # to a thickness, this model keeps the ``None`` verbatim.
    material: MaterialId | None = None
    # Reserved per-joint lap-order override (which member runs continuous
    # through the joint); no layout or expansion code reads it in M2.
    lap: LapOrder | None = None
    id: str = field(default_factory=new_id)


@dataclass
class Split:
    """A bay divided into two or more child bays along one axis.

    ``rules`` is parallel to ``children`` (one rule per child); ``dividers`` has
    one fewer entry, one per gap between consecutive children.
    """

    orientation: Orientation
    children: list["Bay"]
    rules: list[SplitRule]
    dividers: list[Divider]
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if len(self.children) < 2:
            raise ValueError(
                f"Split.children must have at least 2 entries, got {len(self.children)}"
            )
        if len(self.rules) != len(self.children):
            raise ValueError(
                f"Split.rules count ({len(self.rules)}) must equal children count "
                f"({len(self.children)})"
            )
        if len(self.dividers) != len(self.children) - 1:
            raise ValueError(
                f"Split.dividers count ({len(self.dividers)}) must equal children "
                f"count minus one ({len(self.children) - 1})"
            )


Bay = Leaf | Split


@dataclass
class Carcass:
    """The shelving box: outer dimensions, a default material, and a root bay."""

    width_mm: float
    height_mm: float
    depth_mm: float
    # Catalog id; its thickness applies to the shell panels and to any
    # ``Divider`` that sets no ``material`` of its own.
    default_material: MaterialId
    root: Bay
    # This unit's persistent identity, assigned once and preserved across edits.
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.width_mm <= 0:
            raise ValueError(f"Carcass.width_mm must be > 0, got {self.width_mm}")
        if self.height_mm <= 0:
            raise ValueError(f"Carcass.height_mm must be > 0, got {self.height_mm}")
        if self.depth_mm <= 0:
            raise ValueError(f"Carcass.depth_mm must be > 0, got {self.depth_mm}")
        if not self.default_material:
            raise ValueError("Carcass.default_material must be non-empty")

    def to_dict(self) -> "CarcassDoc":
        return {
            "schema_version": 1,
            "carcass": {
                "id": self.id,
                "width_mm": self.width_mm,
                "height_mm": self.height_mm,
                "depth_mm": self.depth_mm,
                "default_material": str(self.default_material),
                "root": _bay_to_doc(self.root),
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Carcass":
        # Parsed external JSON is a genuine type-erasing boundary: every value
        # arrives as ``object`` and is narrowed with isinstance / match before
        # it reaches a constructor.
        version = data.get("schema_version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != SCHEMA_VERSION
        ):
            raise ValueError(
                f"schema_version must be {SCHEMA_VERSION}, got {version!r}"
            )
        body = _as_mapping(data.get("carcass"), "'carcass'")
        return cls(
            width_mm=_req_number(body, "width_mm"),
            height_mm=_req_number(body, "height_mm"),
            depth_mm=_req_number(body, "depth_mm"),
            default_material=MaterialId(_req_str(body, "default_material")),
            root=_bay_from_doc(body.get("root")),
            id=_req_str(body, "id"),
        )

    @classmethod
    def from_json(cls, s: str) -> "Carcass":
        parsed = json.loads(s)
        if not isinstance(parsed, dict):
            raise ValueError("top-level JSON value must be an object")
        return cls.from_dict(parsed)


class FixedRuleDoc(TypedDict):
    type: Literal["fixed"]
    size_mm: float


class WeightedRuleDoc(TypedDict):
    type: Literal["weighted"]
    weight: float


class FillRuleDoc(TypedDict):
    type: Literal["fill"]


RuleDoc = FixedRuleDoc | WeightedRuleDoc | FillRuleDoc


class DividerDoc(TypedDict):
    id: str
    material: str | None
    lap: Literal["captured", "through"] | None


class LeafDoc(TypedDict):
    kind: Literal["leaf"]
    id: str


class SplitDoc(TypedDict):
    kind: Literal["split"]
    id: str
    orientation: Literal["horizontal", "vertical"]
    children: list["BayDoc"]
    rules: list[RuleDoc]
    dividers: list[DividerDoc]


BayDoc = LeafDoc | SplitDoc


class CarcassBody(TypedDict):
    id: str
    width_mm: float
    height_mm: float
    depth_mm: float
    default_material: str
    root: BayDoc


class CarcassDoc(TypedDict):
    schema_version: Literal[1]
    carcass: CarcassBody


def _orientation_tag(orientation: Orientation) -> Literal["horizontal", "vertical"]:
    match orientation:
        case Orientation.HORIZONTAL:
            return "horizontal"
        case Orientation.VERTICAL:
            return "vertical"


def _lap_tag(lap: LapOrder) -> Literal["captured", "through"]:
    match lap:
        case LapOrder.CAPTURED:
            return "captured"
        case LapOrder.THROUGH:
            return "through"


def _rule_to_doc(rule: SplitRule) -> RuleDoc:
    match rule:
        case Fixed(size_mm=size_mm):
            return {"type": "fixed", "size_mm": size_mm}
        case Weighted(weight=weight):
            return {"type": "weighted", "weight": weight}
        case Fill():
            return {"type": "fill"}


def _divider_to_doc(divider: Divider) -> DividerDoc:
    return {
        "id": divider.id,
        "material": None if divider.material is None else str(divider.material),
        "lap": None if divider.lap is None else _lap_tag(divider.lap),
    }


def _bay_to_doc(bay: Bay) -> BayDoc:
    match bay:
        case Leaf():
            return {"kind": "leaf", "id": bay.id}
        case Split():
            return {
                "kind": "split",
                "id": bay.id,
                "orientation": _orientation_tag(bay.orientation),
                "children": [_bay_to_doc(child) for child in bay.children],
                "rules": [_rule_to_doc(rule) for rule in bay.rules],
                "dividers": [_divider_to_doc(divider) for divider in bay.dividers],
            }


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


def _req_list(obj: Mapping[str, object], key: str) -> list[object]:
    if key not in obj:
        raise ValueError(f"missing required key {key!r}")
    value = obj[key]
    if not isinstance(value, list):
        raise ValueError(f"key {key!r} must be an array, got {value!r}")
    return value


def _orientation_from_doc(value: object) -> Orientation:
    match value:
        case "horizontal":
            return Orientation.HORIZONTAL
        case "vertical":
            return Orientation.VERTICAL
        case _:
            raise ValueError(f"unknown orientation {value!r}")


def _rule_from_doc(node: object) -> SplitRule:
    obj = _as_mapping(node, "rule")
    rule_type = obj.get("type")
    match rule_type:
        case "fixed":
            return Fixed(size_mm=_req_number(obj, "size_mm"))
        case "weighted":
            return Weighted(weight=_req_number(obj, "weight"))
        case "fill":
            return Fill()
        case _:
            raise ValueError(f"unknown rule type {rule_type!r}")


def _divider_from_doc(node: object) -> Divider:
    obj = _as_mapping(node, "divider")
    divider_id = _req_str(obj, "id")
    return Divider(
        material=_divider_material_from_doc(obj),
        lap=_divider_lap_from_doc(obj),
        id=divider_id,
    )


def _divider_material_from_doc(obj: Mapping[str, object]) -> MaterialId | None:
    if "material" not in obj or obj["material"] is None:
        return None
    value = obj["material"]
    if not isinstance(value, str):
        raise ValueError(f"divider 'material' must be a string or null, got {value!r}")
    return MaterialId(value)


def _divider_lap_from_doc(obj: Mapping[str, object]) -> LapOrder | None:
    if "lap" not in obj or obj["lap"] is None:
        return None
    value = obj["lap"]
    match value:
        case "captured":
            return LapOrder.CAPTURED
        case "through":
            return LapOrder.THROUGH
        case _:
            raise ValueError(
                f"divider 'lap' must be 'captured', 'through', or null, got {value!r}"
            )


def _bay_from_doc(node: object) -> Bay:
    obj = _as_mapping(node, "bay")
    node_id = _req_str(obj, "id")
    kind = obj.get("kind")
    match kind:
        case "leaf":
            return Leaf(id=node_id)
        case "split":
            return Split(
                orientation=_orientation_from_doc(obj.get("orientation")),
                children=[_bay_from_doc(child) for child in _req_list(obj, "children")],
                rules=[_rule_from_doc(rule) for rule in _req_list(obj, "rules")],
                dividers=[
                    _divider_from_doc(divider) for divider in _req_list(obj, "dividers")
                ],
                id=node_id,
            )
        case _:
            raise ValueError(f"unknown bay kind {kind!r}")
