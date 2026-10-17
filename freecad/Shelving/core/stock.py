"""A board's stock: which existing board a board the editor creates takes
it from, and how the editor groups a unit's boards by it.

A board's stock is its thickness plus whatever material, appearance and grain
the document gives it. The core sees only the thickness; it names the source
board so the write path can copy the rest from that board's object, and
groups what the document layer reads back.

Imports no Qt and no FreeCAD, so the fast suite exercises it directly.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from freecad.Shelving.core.geometry import Space
from freecad.Shelving.core.layout import Axis, Bay, Board, Division, Item, Region, Unit


@dataclass(frozen=True)
class _Placed:
    """A node and the path down to it."""

    item: Item
    # Each enclosing ``Division`` from the root down, paired with the index
    # of the item the path continues through; the last pair holds ``item``.
    path: tuple[tuple[Division, int], ...]


def _walk(
    region: Region, path: tuple[tuple[Division, int], ...] = ()
) -> Iterator[_Placed]:
    """Every item under ``region``, in pre-order."""
    if not isinstance(region, Division):
        return
    for index, item in enumerate(region.items):
        item_path = (*path, (region, index))
        yield _Placed(item, item_path)
        if not isinstance(item, Board):
            yield from _walk(item, item_path)


def _holds_bay(item: Item) -> bool:
    if isinstance(item, Bay):
        return True
    if isinstance(item, Division):
        return any(_holds_bay(child) for child in item.items)
    return False


def _is_carcass_path(path: tuple[tuple[Division, int], ...]) -> bool:
    axis = path[-1][0].axis
    low_clear = True
    high_clear = True
    # Only divisions along the board's own run lie between it and the unit's
    # edge in that direction; a division across it holds side-by-side
    # neighbors, which are beside the board, not beyond its faces.
    for division, index in path:
        if division.axis is not axis:
            continue
        if any(_holds_bay(item) for item in division.items[:index]):
            low_clear = False
        if any(_holds_bay(item) for item in division.items[index + 1 :]):
            high_clear = False
    return low_clear or high_clear


def is_carcass(unit: Unit, board_id: str) -> bool:
    """Whether the board named ``board_id`` is part of the unit's carcass.

    A board is carcass when, along its run, one of its sides holds no
    ``Bay`` all the way to the unit's edge: only ``Void``, other boards, or
    nothing. A floor raised over a plinth gap is carcass by this rule even
    though it is not at the unit's bounding box. Raises ``KeyError`` when
    ``board_id`` names no board in ``unit``.
    """
    for placed in _walk(unit.root):
        if isinstance(placed.item, Board) and placed.item.id == board_id:
            return _is_carcass_path(placed.path)
    raise KeyError(board_id)


def _center_mm(space: Space) -> tuple[float, float, float]:
    return (
        space.origin.x_mm + space.size.x_mm / 2,
        space.origin.y_mm + space.size.y_mm / 2,
        space.origin.z_mm + space.size.z_mm / 2,
    )


def source_board(
    unit: Unit, spaces: Mapping[str, Space], region_id: str, axis: Axis
) -> Board | None:
    """The board a new board on ``axis`` splitting the region ``region_id``
    copies its stock from, or ``None`` when ``unit`` has no board at all.

    ``spaces`` is ``unit`` solved. A candidate is parallel to the new board
    when it runs along ``axis`` with no rule of its own, since a board with
    a rule is not thin along its run. The first non-empty tier wins, and
    within a tier the board whose center is nearest ``region_id``'s center,
    the first in pre-order on a tie:

    1. a parallel interior board in the run the new board joins;
    2. a parallel interior board anywhere in the unit;
    3. a parallel carcass board;
    4. any board.

    Raises ``KeyError`` when ``region_id`` is absent from ``spaces``.
    """
    target_mm = _center_mm(spaces[region_id])
    parent_id: str | None = None
    boards: list[_Placed] = []
    for placed in _walk(unit.root):
        if placed.item.id == region_id:
            parent_id = placed.path[-1][0].id
        if isinstance(placed.item, Board):
            boards.append(placed)

    def parallel(placed: _Placed) -> bool:
        assert isinstance(placed.item, Board)
        return placed.path[-1][0].axis is axis and placed.item.rule is None

    interior = [p for p in boards if parallel(p) and not _is_carcass_path(p.path)]
    # A split across its parent's axis starts a fresh run holding only the
    # new board, so only a same-axis split joins a run with other boards.
    same_run = [p for p in interior if p.path[-1][0].id == parent_id]
    carcass = [p for p in boards if parallel(p) and _is_carcass_path(p.path)]
    for tier in (same_run, interior, carcass, boards):
        if tier:
            nearest = min(
                tier, key=lambda p: math.dist(_center_mm(spaces[p.item.id]), target_mm)
            )
            assert isinstance(nearest.item, Board)
            return nearest.item
    return None


# A color as 0 to 255 per red, green and blue channel.
Color = tuple[int, int, int]


@dataclass(frozen=True)
class BoardStock:
    """What the document gives one board, as :func:`group_stocks` reads it."""

    board_id: str
    thickness_mm: float
    # The name of the board's FreeCAD material; None when it has none.
    material: str | None
    # The board's most common face color; None when it is not known, as
    # without FreeCAD's GUI.
    color: Color | None


@dataclass(frozen=True)
class StockGroup:
    """The boards sharing one stock."""

    thickness_mm: float
    material: str | None
    color: Color | None
    # In the order the records listed them.
    board_ids: tuple[str, ...]


# Thicknesses closer than this are one stock: a solve or a scan's snapping
# can leave float noise in two boards cut from the same sheet.
_THICKNESS_DIGITS = 6


def group_stocks(records: Iterable[BoardStock]) -> Sequence[StockGroup]:
    """One group per distinct (thickness, material, color) among
    ``records``, the group holding most boards first, a tie going to the
    group whose first board comes first in ``records``. A group's
    thickness is its first board's."""
    groups: dict[tuple[float, str | None, Color | None], list[BoardStock]] = {}
    for record in records:
        key = (
            round(record.thickness_mm, _THICKNESS_DIGITS),
            record.material,
            record.color,
        )
        groups.setdefault(key, []).append(record)
    # dict keeps first-seen order, and sorted is stable, so ties keep it.
    ordered = sorted(groups.values(), key=lambda members: -len(members))
    return [
        StockGroup(
            thickness_mm=members[0].thickness_mm,
            material=members[0].material,
            color=members[0].color,
            board_ids=tuple(member.board_id for member in members),
        )
        for members in ordered
    ]
