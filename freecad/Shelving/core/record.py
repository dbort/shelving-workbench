"""The stored rule record: the locked regions, keyed to survive a rescan.

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
stored lock takes its region's scanned size, and a region the record does
not name keeps whatever lock the scan gave it.

CONSEQUENCES of keying this way, because they are not obvious. Renaming or
deleting a bounding board invalidates its neighbors' keys; the correct
response, and what :func:`with_stored_rules` does, is to leave that region
as scanned rather than raise. The geometry scanned is still correct, only
the stored lock for that one region is lost.

A lock's :class:`~freecad.Shelving.core.layout.Basis` rides along in the
record, because it cannot be recovered from geometry: a clear opening and a
shelf spacing quoted face to face (``Basis.WITH_NEXT``) place their boards
identically, and a scan always locks in ``Basis.CLEAR``. A stored
``Basis.WITH_NEXT`` surviving a rescan is the only way that intent survives
at all.

A record in any other shape than :func:`rules_to_json` writes reads as no
record: the unit opens with only the locks the scan gives it, where raising
would leave it unopenable.

WHAT IS NOT IN THE RECORD. Anything but the locks. A unit's id, its depth
axis, and its facing are single values with an obvious home as ordinary
container properties (``sh-018``'s job, not this module's); a board's
material, provenance, and pinned size live on the board's own object. This
record exists because a bay or a void is not a board and so has nowhere else
to keep its lock.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Literal, TypedDict

from freecad.Shelving.core.layout import Basis, Board, Division, Item, Region, Unit

RULE_RECORD_VERSION: int = 1

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


class _LockDoc(TypedDict):
    basis: Literal["clear", "with_next"]


class _RuleRecordDoc(TypedDict):
    schema_version: int
    locks: dict[str, _LockDoc]


def rules_to_json(unit: Unit) -> str:
    """Every locked region in ``unit``, keyed by :func:`rule_key`, as JSON.

    ``{"schema_version": 1, "locks": {key: {"basis": "clear" | "with_next"}}}``,
    one entry per locked non-root region and none for an unlocked one.
    """
    locks: dict[str, _LockDoc] = {}
    for key, item in _iter_keyed_regions(unit.root):
        if item.lock is not None:
            locks[key] = {"basis": "clear" if item.lock is Basis.CLEAR else "with_next"}
    doc: _RuleRecordDoc = {"schema_version": RULE_RECORD_VERSION, "locks": locks}
    return json.dumps(doc)


def _parse(text: str) -> Mapping[str, Basis] | None:
    try:
        parsed: object = json.loads(text)
    except ValueError:
        return None
    if not isinstance(parsed, dict) or set(parsed) != {"schema_version", "locks"}:
        return None
    version: object = parsed["schema_version"]
    if isinstance(version, bool) or version != RULE_RECORD_VERSION:
        return None
    raw_locks: object = parsed["locks"]
    if not isinstance(raw_locks, dict):
        return None
    locks: dict[str, Basis] = {}
    for key, raw_lock in raw_locks.items():
        if not isinstance(key, str) or not isinstance(raw_lock, dict):
            return None
        if set(raw_lock) != {"basis"}:
            return None
        basis: object = raw_lock["basis"]
        if basis == Basis.CLEAR.value:
            locks[key] = Basis.CLEAR
        elif basis == Basis.WITH_NEXT.value:
            locks[key] = Basis.WITH_NEXT
        else:
            return None
    return locks


def rules_from_json(text: str) -> Mapping[str, Basis]:
    """Each stored lock's basis, keyed by :func:`rule_key`, from the record
    :func:`rules_to_json` emitted. A record in any other shape, or text that
    is not JSON, gives no locks; this never raises."""
    locks = _parse(text)
    return {} if locks is None else locks


def _locked_items(run: Division, locks: Mapping[str, Basis]) -> list[Item]:
    """``run``'s items, each region whose key ``locks`` names locked in its
    stored basis, and in ``Basis.CLEAR`` when that is ``Basis.WITH_NEXT``
    and no board follows it any more."""
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
        if basis is not None:
            new_item = dataclasses.replace(new_item, lock=basis)
        new_items.append(new_item)
    return new_items


def _with_stored_locks(region: Region, locks: Mapping[str, Basis]) -> Region:
    if not isinstance(region, Division):
        return region
    return dataclasses.replace(region, items=_locked_items(region, locks))


def with_stored_rules(unit: Unit, locks: Mapping[str, Basis]) -> Unit:
    """``unit``, as scanned, with each region whose :func:`rule_key` matches
    an entry in ``locks`` locked in that entry's basis at its scanned size,
    so every node keeps the space it had in ``unit``.

    A region no entry matches keeps the lock the scan gave it, or none; a
    key with no match, most often because a bounding board was renamed or
    deleted since the record was written, is not an error.
    """
    if not locks:
        return unit
    return dataclasses.replace(unit, root=_with_stored_locks(unit.root, locks))
