"""Split-tree data model for a shelving ``Carcass`` and its JSON form.

A ``Carcass`` is the shelving box: outer dimensions, a default panel thickness,
and a root ``Bay``. A ``Bay`` is either a ``Leaf`` (an open compartment) or a
``Split`` (an orientation, an ordered list of two or more child bays, one
``SplitRule`` per child, and one fewer ``Divider`` than children).

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

SCHEMA_VERSION: int = 1


def new_id() -> str:
    """Fresh node identifier: the string form of a random UUID4."""
    return str(uuid.uuid4())


class Orientation(enum.StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


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
    """The panel between two consecutive split children.

    ``thickness_mm`` of ``None`` means "inherit ``Carcass.default_thickness_mm``";
    the solver resolves it, this model keeps the ``None`` verbatim.
    """

    thickness_mm: float | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.thickness_mm is not None and self.thickness_mm < 0:
            raise ValueError(
                f"Divider.thickness_mm must be None or >= 0, got {self.thickness_mm}"
            )


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
    """The shelving box: outer dimensions, a default thickness, and a root bay."""

    width_mm: float
    height_mm: float
    depth_mm: float
    default_thickness_mm: float
    root: Bay

    def __post_init__(self) -> None:
        if self.width_mm <= 0:
            raise ValueError(f"Carcass.width_mm must be > 0, got {self.width_mm}")
        if self.height_mm <= 0:
            raise ValueError(f"Carcass.height_mm must be > 0, got {self.height_mm}")
        if self.depth_mm <= 0:
            raise ValueError(f"Carcass.depth_mm must be > 0, got {self.depth_mm}")
        if self.default_thickness_mm < 0:
            raise ValueError(
                f"Carcass.default_thickness_mm must be >= 0, got "
                f"{self.default_thickness_mm}"
            )

    def to_dict(self) -> "CarcassDoc":
        return {
            "schema_version": 1,
            "carcass": {
                "width_mm": self.width_mm,
                "height_mm": self.height_mm,
                "depth_mm": self.depth_mm,
                "default_thickness_mm": self.default_thickness_mm,
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
            default_thickness_mm=_req_number(body, "default_thickness_mm"),
            root=_bay_from_doc(body.get("root")),
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
    thickness_mm: float | None


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
    width_mm: float
    height_mm: float
    depth_mm: float
    default_thickness_mm: float
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


def _rule_to_doc(rule: SplitRule) -> RuleDoc:
    match rule:
        case Fixed(size_mm=size_mm):
            return {"type": "fixed", "size_mm": size_mm}
        case Weighted(weight=weight):
            return {"type": "weighted", "weight": weight}
        case Fill():
            return {"type": "fill"}


def _divider_to_doc(divider: Divider) -> DividerDoc:
    return {"id": divider.id, "thickness_mm": divider.thickness_mm}


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
    if "thickness_mm" not in obj:
        raise ValueError("missing required key 'thickness_mm'")
    raw = obj["thickness_mm"]
    if raw is None:
        return Divider(thickness_mm=None, id=divider_id)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(
            f"divider 'thickness_mm' must be a number or null, got {raw!r}"
        )
    return Divider(thickness_mm=float(raw), id=divider_id)


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
