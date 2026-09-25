"""Tree-rewriting edits for the elevation editor: split a bay, merge a board.

``split_region`` and ``merge_at`` are each other's exact inverse and the only
two edits this module knows. Both take a :class:`~freecad.Shelving.core.layout.Unit`
and return a new one, never mutating the argument: every rebuilt node is a
fresh dataclass, and every untouched subtree is reused by reference rather
than copied, so the argument's own objects are never written to. Neither
function calls the solver; a caller re-solves the returned ``Unit`` itself
and is responsible for treating a
:class:`~freecad.Shelving.core.solver.LayoutSolveError` from that as its own
kind of refusal, distinct from :class:`EditError`.

Imports no Qt and no FreeCAD, so the fast suite exercises every edit
directly, the same way :mod:`freecad.Shelving.core.solver` does.
"""

from __future__ import annotations

import dataclasses

from freecad.Shelving.core.layout import (
    Axis,
    Bay,
    Board,
    Division,
    Item,
    Region,
    Unit,
)
from freecad.Shelving.core.materials import MaterialId


class EditError(ValueError):
    """A structurally impossible edit request.

    ``node_id`` is the id the caller named: the region asked to split, or the
    board asked to merge at. A session catches this alongside
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` and reports both
    the message and ``node_id`` to its panel without writing anything.
    """

    def __init__(self, node_id: str, message: str) -> None:
        super().__init__(message)
        self.node_id = node_id


def split_region(
    unit: Unit,
    region_id: str,
    axis: Axis,
    material: MaterialId | None = None,
) -> Unit:
    """``unit`` with the ``Bay`` named ``region_id`` replaced by a board on
    ``axis``, splitting it into two equal bays.

    The new ``Division``'s own rule is the split ``Bay``'s rule, so the slot
    it now occupies in its parent still claims the same share of space the
    single bay did; the two new bays are both ``Fill``, splitting that share
    equally between them. ``material`` is the new board's material, ``None``
    meaning it inherits ``unit.default_material`` the same as any other
    board. Raises :class:`EditError` naming ``region_id`` when it names a
    ``Void``, a ``Division``, or no region in ``unit`` at all.
    """
    new_root, found = _split_region(unit.root, region_id, axis, material)
    if not found:
        raise EditError(region_id, f"no region with id {region_id!r}")
    return dataclasses.replace(unit, root=new_root)


def _split_region(
    region: Region,
    region_id: str,
    axis: Axis,
    material: MaterialId | None,
) -> tuple[Region, bool]:
    if region.id == region_id:
        if not isinstance(region, Bay):
            kind = type(region).__name__
            raise EditError(
                region_id, f"cannot split {kind} {region_id!r}: only a Bay can be split"
            )
        division = Division(
            axis=axis,
            items=[Bay(), Board(material=material), Bay()],
            rule=region.rule,
        )
        return division, True
    if not isinstance(region, Division):
        return region, False
    new_items: list[Item] = []
    found = False
    for item in region.items:
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_child, child_found = _split_region(item, region_id, axis, material)
        new_items.append(new_child)
        found = found or child_found
    if found:
        return dataclasses.replace(region, items=new_items), True
    return region, False


def merge_at(unit: Unit, board_id: str) -> Unit:
    """``unit`` with the ``Board`` named ``board_id`` removed and the regions
    either side of it merged into one.

    The merged region is the first (lower-index) neighbour, carrying that
    neighbour's own rule, *unless* the merge leaves its enclosing
    ``Division`` with only that one item left: the ``Division`` itself is
    then replaced by it, taking the ``Division``'s own rule instead, which is
    what makes this the exact inverse of :func:`split_region` (whose new
    ``Division`` starts out carrying the split ``Bay``'s rule) rather than
    leaving a degenerate one-item ``Division`` behind. The second neighbour
    is discarded whole: when it is itself a ``Division``, every board and
    region in its subtree disappears with it, silently, rather than being
    refused, since the letter of "regions either side merged into one" does
    not distinguish a leaf region from a subtree. Raises :class:`EditError`
    naming ``board_id`` when it names no board in ``unit``, or a board whose
    neighbour on either side is missing (the end of a run) or is itself a
    ``Board`` rather than a region.
    """
    new_root, found = _merge_at(unit.root, board_id)
    if not found:
        raise EditError(board_id, f"no board with id {board_id!r}")
    return dataclasses.replace(unit, root=new_root)


def _merge_at(region: Region, board_id: str) -> tuple[Region, bool]:
    if not isinstance(region, Division):
        return region, False
    items = region.items
    for index, item in enumerate(items):
        if isinstance(item, Board) and item.id == board_id:
            if index == 0 or index == len(items) - 1:
                raise EditError(
                    board_id,
                    f"board {board_id!r} has no neighbour on one side and cannot "
                    "be merged",
                )
            before, after = items[index - 1], items[index + 1]
            if isinstance(before, Board) or isinstance(after, Board):
                raise EditError(
                    board_id,
                    f"board {board_id!r}'s neighbours are not both regions",
                )
            merged: Region = before
            merged_items = items[: index - 1] + [merged] + items[index + 2 :]
            if len(merged_items) == 1:
                collapsed = dataclasses.replace(merged, rule=region.rule)
                return collapsed, True
            return dataclasses.replace(region, items=merged_items), True
    new_items: list[Item] = []
    changed = False
    for item in items:
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_child, child_found = _merge_at(item, board_id)
        new_items.append(new_child)
        changed = changed or child_found
    if changed:
        return dataclasses.replace(region, items=new_items), True
    return region, False
