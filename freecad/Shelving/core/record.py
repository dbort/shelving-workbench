"""The stored rule record: the locked regions and the constraints between
openings, keyed to survive a rescan.

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
whose neighbor on a side is itself a region rather than a board, has no
bounding board on that side; :data:`NO_NEIGHBOR_SENTINEL` fills in rather than
an empty string, so a key read back is never ambiguous about which case it
is. Two regions in different divisions can never collide, because a board
bounds at most one region on each side within one run.

GEOMETRY WINS. A rescan takes every region's size from the boards, so a
board moved by hand stays where it was moved. The record contributes only
what geometry cannot say: which regions are locked, and in which basis. A
stored lock takes its region's scanned size. A valid record is the whole
lock state: a region it does not name is unlocked, even where the scan
would have locked it, so an opening the user unlocked stays unlocked. The
scan's own locks stand only when the container holds no valid record.

CONSEQUENCES of keying this way, because they are not obvious. Renaming or
deleting a bounding board invalidates its neighbors' keys; the correct
response, and what :func:`with_stored_rules` does, is to leave that region
unlocked rather than raise. The geometry scanned is still correct, only the
stored lock for that one region is lost.

A lock's :class:`~freecad.Shelving.core.layout.Basis` rides along in the
record, because it cannot be recovered from geometry: a clear opening and a
shelf spacing quoted face to face (``Basis.WITH_NEXT``) place their boards
identically, and a scan always locks in ``Basis.CLEAR``. A stored
``Basis.WITH_NEXT`` surviving a rescan is the only way that intent survives
at all.

A constraint names its openings by the same keys, and an even spacing names
its run by the run's key and its ends by board id, so it survives a rescan
as a lock does. Geometry wins for constraints too: one the boards no longer
meet comes in deactivated rather than moving anything, and one naming a key
or board that matches nothing is left out (:func:`restore_rules`).

A record in any other shape than :func:`rules_to_json` writes, the version 1
record of locks alone included, reads as no record (:func:`parse_rules`
gives ``None``): the unit opens with the locks the scan gives it and no
constraints, where raising would leave it unopenable.

WHAT IS NOT IN THE RECORD. Anything but the locks and constraints. A unit's
id, its depth axis, and its facing are single values with an obvious home as
ordinary container properties (``sh-018``'s job, not this module's); a board's
material, provenance, and pinned size live on the board's own object. This
record exists because a bay or a void is not a board and so has nowhere else
to keep its lock or its constraints.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Literal, TypedDict

from freecad.Shelving.core.layout import (
    Basis,
    Board,
    Constraint,
    ConstraintId,
    Division,
    Equal,
    EvenSpacing,
    Item,
    Region,
    RunEnd,
    SpacingEnd,
    Unit,
    spacing_group,
)
from freecad.Shelving.core.solver import constraint_spread_mm, solve

RULE_RECORD_VERSION: int = 2

# A FreeCAD object's internal Name is identifier-only (letters, digits,
# underscore), so any punctuation is safe here; printable characters are
# chosen over control characters so a key is legible when inspected directly.
KEY_SEPARATOR: str = "|"
NO_NEIGHBOR_SENTINEL: str = "~"


def rule_key(before: str | None, after: str | None) -> str:
    """The record key for a region bounded by board ids ``before`` and
    ``after`` in its division's run, either of which is ``None`` when that
    side has no bounding board (the end of the run, or a neighbor that is
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


def _iter_keyed_regions(region: Region) -> Iterator[tuple[str, Region]]:
    """``(key, region)`` for every region in the subtree rooted at
    ``region``, excluding ``region`` itself: the root region has no division
    of its own and therefore no key, so callers pass ``unit.root`` to skip
    it while still reaching everything below it."""
    if not isinstance(region, Division):
        return
    items = region.items
    for index, item in enumerate(items):
        if isinstance(item, Board):
            continue
        before = _neighbor_board_id(items, index - 1)
        after = _neighbor_board_id(items, index + 1)
        yield rule_key(before, after), item
        yield from _iter_keyed_regions(item)


def region_keys(unit: Unit) -> Mapping[str, str]:
    """Each region's id in ``unit`` except the root's, keyed by its
    :func:`rule_key`: the key a rescan, which mints fresh region ids,
    finds the same region by."""
    return {key: item.id for key, item in _iter_keyed_regions(unit.root)}


def keys_by_region(unit: Unit) -> Mapping[str, str]:
    """Each region's :func:`rule_key` in ``unit``, keyed by its id; the root
    has none."""
    return {item.id: key for key, item in _iter_keyed_regions(unit.root)}


def unique_regions_by_key(unit: Unit) -> Mapping[str, str]:
    """Each region's id in ``unit`` keyed by its :func:`rule_key`, leaving
    out every key two regions share, so a key found here names one region
    without doubt."""
    found: dict[str, str] = {}
    shared: set[str] = set()
    for key, item in _iter_keyed_regions(unit.root):
        if key in found:
            shared.add(key)
        found[key] = item.id
    return {key: region_id for key, region_id in found.items() if key not in shared}


BasisName = Literal["clear", "with_next"]


class _LockDoc(TypedDict):
    basis: BasisName


class _EqualDoc(TypedDict):
    kind: Literal["equal"]
    basis: BasisName
    active: bool
    # The two openings' keys, in the constraint's order.
    openings: list[str]


class _EvenSpacingDoc(TypedDict):
    kind: Literal["even_spacing"]
    basis: BasisName
    active: bool
    # The run's key, or ROOT_RUN_SENTINEL for the root's run.
    run: str
    # A board id, or RUN_START_SENTINEL / RUN_END_SENTINEL.
    start: str
    end: str


class _RuleRecordDoc(TypedDict):
    schema_version: int
    locks: dict[str, _LockDoc]
    constraints: list[_EqualDoc | _EvenSpacingDoc]


# The root has no parent run and so no rule_key; neither sentinel holds the
# separator, so none can pass for a key or a board's Name.
ROOT_RUN_SENTINEL: str = "~root"
RUN_START_SENTINEL: str = "~start"
RUN_END_SENTINEL: str = "~end"

_RUN_END_NAMES: Mapping[RunEnd, str] = {
    RunEnd.START: RUN_START_SENTINEL,
    RunEnd.END: RUN_END_SENTINEL,
}


@dataclasses.dataclass(frozen=True)
class StoredEqual:
    """An :class:`~freecad.Shelving.core.layout.Equal` as the record keeps
    it."""

    # The two openings' rule keys, in the constraint's order.
    keys: tuple[str, str]
    basis: Basis
    active: bool


@dataclasses.dataclass(frozen=True)
class StoredEvenSpacing:
    """An :class:`~freecad.Shelving.core.layout.EvenSpacing` as the record
    keeps it."""

    # The run's rule key, or ROOT_RUN_SENTINEL.
    run_key: str
    start: SpacingEnd
    end: SpacingEnd
    basis: Basis
    active: bool


StoredConstraint = StoredEqual | StoredEvenSpacing


@dataclasses.dataclass(frozen=True)
class StoredRules:
    """What a valid record holds."""

    # Each stored lock's basis, by rule key.
    locks: Mapping[str, Basis] = dataclasses.field(default_factory=dict)
    # In the order the unit holds them.
    constraints: tuple[StoredConstraint, ...] = ()


def _basis_name(basis: Basis) -> BasisName:
    return "clear" if basis is Basis.CLEAR else "with_next"


def _end_name(end: SpacingEnd) -> str:
    return _RUN_END_NAMES[end] if isinstance(end, RunEnd) else end


def _constraint_doc(
    unit: Unit, constraint: Constraint, keys: Mapping[str, str]
) -> _EqualDoc | _EvenSpacingDoc | None:
    """``constraint`` as its record entry, or ``None`` when a region it
    names has no key in ``unit``."""
    if isinstance(constraint, Equal):
        first, second = (keys.get(region_id) for region_id in constraint.region_ids)
        if first is None or second is None:
            return None
        return {
            "kind": "equal",
            "basis": _basis_name(constraint.basis),
            "active": constraint.active,
            "openings": [first, second],
        }
    run_key = (
        ROOT_RUN_SENTINEL
        if constraint.run_id == unit.root.id
        else keys.get(constraint.run_id)
    )
    if run_key is None:
        return None
    return {
        "kind": "even_spacing",
        "basis": _basis_name(constraint.basis),
        "active": constraint.active,
        "run": run_key,
        "start": _end_name(constraint.start),
        "end": _end_name(constraint.end),
    }


def rules_to_json(unit: Unit) -> str:
    """Every locked region and every constraint in ``unit`` as JSON.

    ``{"schema_version": 2, "locks": {key: {"basis": "clear" |
    "with_next"}}, "constraints": [...]}``: one lock entry per locked
    non-root region, keyed by :func:`rule_key`, and none for an unlocked
    one. Each constraint entry has ``"kind"`` (``"equal"`` or
    ``"even_spacing"``), ``"basis"`` and ``"active"``; an Equal names its
    two openings' keys as ``"openings"``, and an even spacing names its
    run's key, :data:`ROOT_RUN_SENTINEL` for the root's, as ``"run"`` and
    its ends as ``"start"`` and ``"end"``, each a board id or
    :data:`RUN_START_SENTINEL` / :data:`RUN_END_SENTINEL`. A constraint
    naming a region with no key is left out.
    """
    locks: dict[str, _LockDoc] = {}
    for key, item in _iter_keyed_regions(unit.root):
        if item.lock is not None:
            locks[key] = {"basis": _basis_name(item.lock)}
    keys = keys_by_region(unit)
    constraints: list[_EqualDoc | _EvenSpacingDoc] = []
    for constraint in unit.constraints:
        entry = _constraint_doc(unit, constraint, keys)
        if entry is not None:
            constraints.append(entry)
    doc: _RuleRecordDoc = {
        "schema_version": RULE_RECORD_VERSION,
        "locks": locks,
        "constraints": constraints,
    }
    return json.dumps(doc)


def _parse_basis(raw: object) -> Basis | None:
    if raw == Basis.CLEAR.value:
        return Basis.CLEAR
    if raw == Basis.WITH_NEXT.value:
        return Basis.WITH_NEXT
    return None


def _parse_end(raw: object) -> SpacingEnd | None:
    if not isinstance(raw, str) or not raw:
        return None
    for end, name in _RUN_END_NAMES.items():
        if raw == name:
            return end
    return raw


def _unknown_basis(raw: object) -> bool:
    """Whether ``raw`` is a constraint entry whose ``"basis"`` is a string
    naming no :class:`~freecad.Shelving.core.layout.Basis`."""
    if not isinstance(raw, dict):
        return False
    basis: object = raw.get("basis")
    return isinstance(basis, str) and _parse_basis(basis) is None


def _parse_constraint(raw: object) -> StoredConstraint | None:
    if not isinstance(raw, dict):
        return None
    kind: object = raw.get("kind")
    basis = _parse_basis(raw.get("basis"))
    active: object = raw.get("active")
    if basis is None or not isinstance(active, bool):
        return None
    if kind == "equal":
        if set(raw) != {"kind", "basis", "active", "openings"}:
            return None
        openings: object = raw["openings"]
        if (
            not isinstance(openings, list)
            or len(openings) != 2
            or not all(isinstance(key, str) for key in openings)
        ):
            return None
        first: str = openings[0]
        second: str = openings[1]
        return StoredEqual(keys=(first, second), basis=basis, active=active)
    if kind == "even_spacing":
        if set(raw) != {"kind", "basis", "active", "run", "start", "end"}:
            return None
        run: object = raw["run"]
        start = _parse_end(raw["start"])
        end = _parse_end(raw["end"])
        if not isinstance(run, str) or start is None or end is None:
            return None
        return StoredEvenSpacing(
            run_key=run, start=start, end=end, basis=basis, active=active
        )
    return None


def parse_rules(text: str) -> StoredRules | None:
    """The locks and constraints in the record :func:`rules_to_json`
    emitted; ``None`` for a record in any other shape, a version 1 record
    included, or text that is not JSON, which an empty record never gives.
    A constraint entry whose basis is a string naming no basis is left out
    and the rest of the record read. Never raises."""
    try:
        parsed: object = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict) or set(parsed) != {
        "schema_version",
        "locks",
        "constraints",
    }:
        return None
    version: object = parsed["schema_version"]
    if isinstance(version, bool) or version != RULE_RECORD_VERSION:
        return None
    raw_locks: object = parsed["locks"]
    raw_constraints: object = parsed["constraints"]
    if not isinstance(raw_locks, dict) or not isinstance(raw_constraints, list):
        return None
    locks: dict[str, Basis] = {}
    for key, raw_lock in raw_locks.items():
        if not isinstance(key, str) or not isinstance(raw_lock, dict):
            return None
        if set(raw_lock) != {"basis"}:
            return None
        basis = _parse_basis(raw_lock["basis"])
        if basis is None:
            return None
        locks[key] = basis
    constraints: list[StoredConstraint] = []
    for raw in raw_constraints:
        if _unknown_basis(raw):
            # A basis this workbench does not know costs that constraint
            # alone, not every lock and constraint beside it.
            continue
        constraint = _parse_constraint(raw)
        if constraint is None:
            return None
        constraints.append(constraint)
    return StoredRules(locks=locks, constraints=tuple(constraints))


def rules_from_json(text: str) -> StoredRules:
    """:func:`parse_rules`, with a record in any other shape, or text that
    is not JSON, giving no locks and no constraints; never raises."""
    rules = parse_rules(text)
    return StoredRules() if rules is None else rules


def _locked_items(run: Division, locks: Mapping[str, Basis]) -> list[Item]:
    """``run``'s items, each region whose key ``locks`` names locked in its
    stored basis, and in ``Basis.CLEAR`` when that is ``Basis.WITH_NEXT``
    and no board follows it any more; every other region unlocked."""
    items = run.items
    new_items: list[Item] = []
    for index, item in enumerate(items):
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_item = _with_stored_locks(item, locks)
        key = rule_key(
            _neighbor_board_id(items, index - 1), _neighbor_board_id(items, index + 1)
        )
        basis = locks.get(key)
        if basis is Basis.WITH_NEXT and _neighbor_board_id(items, index + 1) is None:
            basis = Basis.CLEAR
        if new_item.lock is not basis:
            new_item = dataclasses.replace(new_item, lock=basis)
        new_items.append(new_item)
    return new_items


def _with_stored_locks(region: Region, locks: Mapping[str, Basis]) -> Region:
    if not isinstance(region, Division):
        return region
    return dataclasses.replace(region, items=_locked_items(region, locks))


def _restored_constraint(
    unit: Unit, stored: StoredConstraint, regions: Mapping[str, str]
) -> Constraint | None:
    """``stored`` named by ``unit``'s ids, or ``None`` when a key or board it
    names matches nothing there, or its ends no longer bound a run."""
    if isinstance(stored, StoredEqual):
        first, second = (regions.get(key) for key in stored.keys)
        if first is None or second is None or first == second:
            return None
        return Equal(
            region_ids=(first, second), basis=stored.basis, active=stored.active
        )
    run_id = (
        unit.root.id
        if stored.run_key == ROOT_RUN_SENTINEL
        else regions.get(stored.run_key)
    )
    if run_id is None:
        return None
    spacing = EvenSpacing(
        run_id=run_id,
        start=stored.start,
        end=stored.end,
        basis=stored.basis,
        active=stored.active,
    )
    return spacing if spacing_group(unit, spacing) is not None else None


def with_stored_rules(unit: Unit, rules: StoredRules | None) -> Unit:
    """``unit``, as scanned, with each region whose :func:`rule_key` matches
    a stored lock locked in that lock's basis and every other region
    unlocked, each at its scanned size, so every node keeps the space it
    had in ``unit``, and with each stored constraint whose keys and boards
    all match, as stored. Returns ``unit`` itself, with the scan's locks
    and no constraints, when ``rules`` is ``None``: no valid record.

    A region no lock matches, most often because a bounding board was
    renamed or deleted since the record was written, is unlocked, and a
    constraint naming such a region or board is left out; neither is an
    error. Moves nothing, even for a constraint the boards do not meet.
    """
    if rules is None:
        return unit
    locked = dataclasses.replace(unit, root=_with_stored_locks(unit.root, rules.locks))
    regions = unique_regions_by_key(locked)
    constraints: list[Constraint] = []
    for stored in rules.constraints:
        restored = _restored_constraint(locked, stored, regions)
        if restored is not None:
            constraints.append(restored)
    return dataclasses.replace(locked, constraints=tuple(constraints))


@dataclasses.dataclass(frozen=True)
class OpenReport:
    """What :func:`restore_rules` changed in the stored constraints."""

    # The constraints stored active that the boards miss by more than the
    # clearance, now deactivated, in the unit's order.
    deactivated: tuple[ConstraintId, ...] = ()
    # How many stored constraints named a region or board the unit no
    # longer has, and were left out.
    dropped: int = 0

    @property
    def empty(self) -> bool:
        """Whether nothing was deactivated or dropped."""
        return not self.deactivated and not self.dropped


def restore_rules(
    unit: Unit, rules: StoredRules | None, clearance_mm: float
) -> tuple[Unit, OpenReport]:
    """:func:`with_stored_rules`, with each active constraint whose regions'
    sizes in its basis differ by more than ``clearance_mm`` deactivated, and
    a report of what was deactivated and left out.

    Geometry wins: nothing moves, a constraint within ``clearance_mm`` stays
    active though the boards miss it, and a stored deactivated constraint
    stays deactivated even when they meet it. ``unit`` must lay out.
    """
    restored = with_stored_rules(unit, rules)
    if rules is None:
        return restored, OpenReport()
    spaces = solve(restored)
    constraints: list[Constraint] = []
    deactivated: list[ConstraintId] = []
    for constraint in restored.constraints:
        spread_mm = constraint_spread_mm(restored, spaces, constraint)
        if constraint.active and spread_mm is not None and spread_mm > clearance_mm:
            constraint = dataclasses.replace(constraint, active=False)
            deactivated.append(constraint.id)
        constraints.append(constraint)
    report = OpenReport(
        deactivated=tuple(deactivated),
        dropped=len(rules.constraints) - len(restored.constraints),
    )
    return dataclasses.replace(restored, constraints=tuple(constraints)), report
