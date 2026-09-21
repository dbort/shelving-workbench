"""The stored rule record: per-region size rules keyed to survive a rescan.

A rescan assigns every region a fresh :func:`~freecad.Shelving.core.layout.new_id`,
so a record keyed by region id would match nothing on the next scan and the
whole mechanism would be dead on arrival. Instead a region is keyed by the
boards that bound it along its division's axis: the item immediately before
it and immediately after it in its parent
:class:`~freecad.Shelving.core.layout.Division`'s ``items`` run. A board's
own id is stable for as long as the board is (see
:mod:`freecad.Shelving.core.scan`'s ``sh-018`` counterpart, which sets a
board's id to its FreeCAD object name), so the key is stable across a rescan
even though every region id is not. A region at either end of a run, or one
whose neighbour on a side is itself a region rather than a board, has no
bounding board on that side; :data:`NO_NEIGHBOR_SENTINEL` fills in rather than
an empty string, so a key read back is never ambiguous about which case it
is. Two regions in different divisions can never collide, because a board
bounds at most one region on each side within one run.

CONSEQUENCES of keying this way, because they are not obvious. Renaming or
deleting a bounding board invalidates its neighbours' keys; the correct
response, and what :func:`with_stored_rules` does, is to fall back to the
region's scanned rule rather than raise. The geometry scanned is still
correct, only the stored intent for that one region is lost, and the
equal-siblings heuristic (:mod:`freecad.Shelving.core.scan`) is the
documented fallback for it.

A ``Fixed`` rule's :class:`~freecad.Shelving.core.layout.Basis` rides along
in the record, because it cannot be recovered from geometry: a clear opening
and a shelf spacing quoted face to face (``Basis.WITH_NEXT``) place their
boards identically, and a scan always recovers ``Basis.CLEAR``. A stored
``Basis.WITH_NEXT`` surviving a rescan is the only way that intent survives
at all.

WHAT IS NOT IN THE RECORD. Only the per-region rules. A unit's id, its depth
axis, and its facing are single values with an obvious home as ordinary
container properties (``sh-018``'s job, not this module's); a board's
material, provenance, and pinned size live on the board's own object. This
record exists because a bay or a void is not a board and so has nowhere else
to keep its rule.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Literal, TypedDict

from freecad.Shelving.core.layout import (
    Basis,
    Bay,
    Board,
    Division,
    Fill,
    Fixed,
    Item,
    Region,
    SizeRule,
    Unit,
    Void,
    Weighted,
)

RULE_RECORD_VERSION: int = 1

# A FreeCAD object's internal Name is identifier-only (letters, digits,
# underscore), so any punctuation is safe here; printable characters are
# chosen over control characters so a key is legible when inspected directly.
KEY_SEPARATOR: str = "|"
NO_NEIGHBOR_SENTINEL: str = "~"


def rule_key(before: str | None, after: str | None) -> str:
    """The record key for a region bounded by board ids ``before`` and
    ``after`` in its division's run, either of which is ``None`` when that
    side has no bounding board (the end of the run, or a neighbour that is
    itself a region rather than a board)."""
    before_part = before if before is not None else NO_NEIGHBOR_SENTINEL
    after_part = after if after is not None else NO_NEIGHBOR_SENTINEL
    return f"{before_part}{KEY_SEPARATOR}{after_part}"


def _neighbor_board_id(items: Sequence[Item], index: int) -> str | None:
    """The id of ``items[index]`` when it exists and is a ``Board``, else
    ``None``: the "no bounding board on this side" case ``rule_key`` sentinels."""
    if not 0 <= index < len(items):
        return None
    neighbor = items[index]
    return neighbor.id if isinstance(neighbor, Board) else None


def _iter_region_rules(region: Region) -> Iterator[tuple[str, SizeRule]]:
    """``(key, rule)`` for every region in the subtree rooted at ``region``,
    excluding ``region`` itself: the root region has no division of its own
    and therefore no key, so callers pass ``unit.root`` to skip it while
    still reaching everything below it."""
    if not isinstance(region, Division):
        return
    items = region.items
    for index, item in enumerate(items):
        if isinstance(item, Board):
            continue
        before = _neighbor_board_id(items, index - 1)
        after = _neighbor_board_id(items, index + 1)
        yield rule_key(before, after), item.rule
        yield from _iter_region_rules(item)


class _FixedRuleDoc(TypedDict):
    type: Literal["fixed"]
    size_mm: float
    basis: Literal["clear", "with_next"]


class _WeightedRuleDoc(TypedDict):
    type: Literal["weighted"]
    weight: float


class _FillRuleDoc(TypedDict):
    type: Literal["fill"]


_RuleDoc = _FixedRuleDoc | _WeightedRuleDoc | _FillRuleDoc


class _RuleRecordDoc(TypedDict):
    schema_version: int
    rules: dict[str, _RuleDoc]


def _rule_to_doc(rule: SizeRule) -> _RuleDoc:
    match rule:
        case Fixed(size_mm=size_mm, basis=basis):
            basis_name: Literal["clear", "with_next"] = (
                "clear" if basis is Basis.CLEAR else "with_next"
            )
            fixed_doc: _FixedRuleDoc = {
                "type": "fixed",
                "size_mm": size_mm,
                "basis": basis_name,
            }
            return fixed_doc
        case Weighted(weight=weight):
            weighted_doc: _WeightedRuleDoc = {"type": "weighted", "weight": weight}
            return weighted_doc
        case Fill():
            fill_doc: _FillRuleDoc = {"type": "fill"}
            return fill_doc


def rules_to_json(unit: Unit) -> str:
    """Every region's rule in ``unit``, keyed by :func:`rule_key`, as JSON.

    ``{"schema_version": ..., "rules": {key: rule_doc}}``, one entry per
    non-root region. A ``Fixed`` rule's ``basis`` is carried along; see the
    module docstring for why.
    """
    rules = {key: _rule_to_doc(rule) for key, rule in _iter_region_rules(unit.root)}
    doc: _RuleRecordDoc = {"schema_version": RULE_RECORD_VERSION, "rules": rules}
    return json.dumps(doc)


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


def _rule_from_doc(raw: object) -> SizeRule:
    obj = _as_mapping(raw, "rule")
    rule_type = obj.get("type")
    if rule_type == "fixed":
        size_mm = _req_number(obj, "size_mm")
        basis_raw = obj.get("basis")
        if basis_raw == Basis.CLEAR.value:
            return Fixed(size_mm=size_mm, basis=Basis.CLEAR)
        if basis_raw == Basis.WITH_NEXT.value:
            return Fixed(size_mm=size_mm, basis=Basis.WITH_NEXT)
        raise ValueError(f"'basis' must be 'clear' or 'with_next', got {basis_raw!r}")
    if rule_type == "weighted":
        return Weighted(weight=_req_number(obj, "weight"))
    if rule_type == "fill":
        return Fill()
    raise ValueError(
        f"'type' must be 'fixed', 'weighted', or 'fill', got {rule_type!r}"
    )


def rules_from_json(text: str) -> Mapping[str, SizeRule]:
    """The record :func:`rules_to_json` emitted, or ``ValueError`` naming the
    problem: a version other than :data:`RULE_RECORD_VERSION`, or a
    malformed rule doc.
    """
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("top-level JSON value must be an object")
    version = parsed.get("schema_version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version != RULE_RECORD_VERSION
    ):
        raise ValueError(
            f"schema_version must be {RULE_RECORD_VERSION}, got {version!r}"
        )
    raw_rules = parsed.get("rules")
    if not isinstance(raw_rules, dict):
        raise ValueError("'rules' must be a JSON object")
    rules: dict[str, SizeRule] = {}
    for key, raw_rule in raw_rules.items():
        if not isinstance(key, str):
            raise ValueError(f"rule key must be a string, got {key!r}")
        rules[key] = _rule_from_doc(raw_rule)
    return rules


def _set_rule(region: Region, rule: SizeRule) -> Region:
    match region:
        case Bay():
            return dataclasses.replace(region, rule=rule)
        case Void():
            return dataclasses.replace(region, rule=rule)
        case Division():
            return dataclasses.replace(region, rule=rule)


def _rebuild_with_stored_rules(region: Region, rules: Mapping[str, SizeRule]) -> Region:
    """A copy of ``region`` with every descendant region's rule replaced by
    its matching entry in ``rules``, and left as scanned where no entry
    matches. ``region``'s own rule is untouched; the caller, which holds the
    parent run ``region`` sits in, is the one that knows ``region``'s key."""
    if not isinstance(region, Division):
        return region
    items = region.items
    new_items: list[Item] = []
    for index, item in enumerate(items):
        if isinstance(item, Board):
            new_items.append(item)
            continue
        before = _neighbor_board_id(items, index - 1)
        after = _neighbor_board_id(items, index + 1)
        key = rule_key(before, after)
        rebuilt = _rebuild_with_stored_rules(item, rules)
        new_items.append(_set_rule(rebuilt, rules.get(key, item.rule)))
    return dataclasses.replace(region, items=new_items)


def with_stored_rules(unit: Unit, rules: Mapping[str, SizeRule]) -> Unit:
    """``unit`` with every region whose :func:`rule_key` matches an entry in
    ``rules`` carrying that rule, and every other region left as scanned.

    A key with no match, most often because a bounding board was renamed or
    deleted since the record was written, is not an error: that region keeps
    whatever rule the scan it was rebuilt from assigned it.
    """
    return dataclasses.replace(unit, root=_rebuild_with_stored_rules(unit.root, rules))
