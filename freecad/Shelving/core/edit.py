"""Tree-rewriting edits for the elevation editor: split a bay, merge a board,
remove several boards, size a region, change what a size measures, lock or
unlock a region, drag a board, change boards' thickness, and make, remove,
activate or deactivate Equal and even spacing constraints or change what
they measure.

A region an active :class:`~freecad.Shelving.core.layout.Lock` names holds
its size through edits; any other takes whatever size the boards around it
leave. Any region but the root may lock, and holds at most one Lock. Where
the locks determine the unit's size along an axis, that size is a reference:
:func:`set_unit_size` refuses to change it, and every other edit lets it
follow the locks with the unit's fixed point holding. Every edit returns a unit
whose stored sizes are already solved: one that moves boards solves them with
:func:`~freecad.Shelving.core.solver.solve_axis`, moving the boards as little
as possible from where they stood before the edit. A caller treats a
:class:`~freecad.Shelving.core.solver.LayoutSolveError` from an edit or from
laying out its result as its own kind of refusal, distinct from
:class:`EditError`.

Every active constraint holds through every edit, and the structural edits
carry the constraints over to the new tree, dropping those whose openings or
end boards they remove (:func:`carry_constraints`).

``split_region`` and ``merge_at`` are each other's exact inverse while every
constraint holds. No edit here mutates the argument ``Unit``: untouched
subtrees are shared by reference with the result, so the argument must stay
unmodified for the result to stay valid.

Imports no Qt and no FreeCAD, so the fast suite exercises every edit
directly, the same way :mod:`freecad.Shelving.core.solver` does.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Constraint,
    ConstraintId,
    Division,
    Equal,
    EvenSpacing,
    Item,
    Lock,
    Region,
    RunEnd,
    SpacingEnd,
    Unit,
    constraint_regions,
    find_division,
    is_locked,
    parent_divisions,
    region_along,
    region_lock,
    spacing_group,
)
from freecad.Shelving.core.record import keys_by_region, unique_regions_by_key
from freecad.Shelving.core.scan import elevation_axes
from freecad.Shelving.core.solver import (
    EPS_MM,
    FIXED_FRACTION,
    LayoutSolveError,
    board_extent_mm,
    constraint_axis,
    constraint_spread_mm,
    fixing_locks,
    solve,
    solve_axis,
)
from freecad.Shelving.core.stock import source_board


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


def split_region(unit: Unit, region_id: str, axis: Axis) -> Unit:
    """``unit`` with the ``Bay`` named ``region_id`` replaced by a board on
    ``axis``, splitting it into two bays of equal size and moving nothing
    else while every constraint still holds.

    When ``region_id``'s parent ``Division`` runs along a *different* axis
    than ``axis``, the replacement is a new ``Division`` on ``axis`` holding
    ``Bay``, ``Board``, ``Bay``, taking the split ``Bay``'s own size and its
    Lock in the slot it occupied; both new bays are unlocked. Otherwise
    ``region_id``'s parent already runs along ``axis``, and the two new bays
    splice directly into the parent's own ``items`` in ``region_id``'s
    place. When the split bay had a Lock, the first half takes it and the
    second gets a new one just after it, both in ``Basis.CLEAR`` and as
    active as the bay's was. A same-axis ``Division`` nested inside another
    is one that scanning cannot tell apart from a flat run of the same
    boards (bug-006).

    The new board takes its thickness from the board
    :func:`~freecad.Shelving.core.stock.source_board` picks, and carries that
    board's id as its ``stock_from``. Raises :class:`EditError` naming
    ``region_id`` when it names a ``Void``, a ``Division``, no region in
    ``unit`` at all, or a ``Bay`` too small to hold the new board and still
    leave two positive-sized halves, or when ``unit`` has no board to copy
    stock from.

    The constraints carry over as :func:`carry_constraints` carries them,
    and an active one the new board leaves unmet, as when it adds an
    opening to an even spacing, is solved again. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when that solve
    finds no layout.
    """
    if unit.root.id == region_id and not isinstance(unit.root, Bay):
        raise EditError(region_id, "Only an open compartment can be split.")
    spaces = solve(unit)
    if region_id not in spaces:
        raise EditError(region_id, "That is not part of this unit.")
    source = source_board(unit, spaces, region_id, axis)
    if source is None:
        raise EditError(
            region_id, "This unit has no board for a new board to copy its stock from."
        )
    board = Board(thickness_mm=source.thickness_mm, stock_from=source.id)
    if not isinstance(unit.root, Division):
        raise EditError(region_id, "That is not part of this unit.")
    replaced_root, replacement = _split_in_division(
        unit.root, region_id, axis, board, spaces
    )
    if replacement is None:
        raise EditError(region_id, "That is not part of this unit.")
    split = dataclasses.replace(
        unit,
        root=replaced_root,
        constraints=_split_locks(unit.constraints, region_id, replacement),
    )
    return _structural(unit, split)


def _split_in_division(
    division: Division,
    region_id: str,
    axis: Axis,
    board: Board,
    spaces: Mapping[str, Space],
) -> tuple[Division, Sequence[Item] | None]:
    """``division`` with the bay ``region_id`` split, and the items that
    replaced it; ``None`` for those when it holds no such region."""
    items = division.items
    for index, item in enumerate(items):
        if isinstance(item, Board):
            continue
        if item.id == region_id:
            if not isinstance(item, Bay):
                raise EditError(region_id, "Only an open compartment can be split.")
            replacement = _split_replacement(item, division, axis, board, spaces)
            new_items = items[:index] + replacement + items[index + 1 :]
            return dataclasses.replace(division, items=new_items), replacement
        if isinstance(item, Division):
            new_child, found = _split_in_division(item, region_id, axis, board, spaces)
            if found is not None:
                new_items = items[:index] + [new_child] + items[index + 1 :]
                return dataclasses.replace(division, items=new_items), found
    return division, None


def _split_locks(
    constraints: tuple[Constraint, ...], region_id: str, replacement: Sequence[Item]
) -> tuple[Constraint, ...]:
    """``constraints`` with the split bay ``region_id``'s Lock moved onto
    ``replacement``, as :func:`split_region` describes."""
    out: list[Constraint] = []
    for constraint in constraints:
        if not isinstance(constraint, Lock) or constraint.region_id != region_id:
            out.append(constraint)
            continue
        first = replacement[0]
        out.append(dataclasses.replace(constraint, region_id=first.id))
        if len(replacement) == 1:
            continue
        out[-1] = dataclasses.replace(out[-1], basis=Basis.CLEAR)
        out.append(
            Lock(
                region_id=replacement[-1].id,
                basis=Basis.CLEAR,
                active=constraint.active,
            )
        )
    return tuple(out)


def _split_replacement(
    bay: Bay,
    parent: Division,
    axis: Axis,
    board: Board,
    spaces: Mapping[str, Space],
) -> list[Item]:
    """The item(s) replacing ``bay`` in ``parent``: one wrapping ``Division``
    when ``axis`` differs from ``parent.axis``, or the flat splice
    ``[Bay, Board, Bay]`` in the bay's own place when it matches."""
    size_before_mm = spaces[bay.id].extent_mm(axis.component_index)
    half_mm = (size_before_mm - board.thickness_mm) / 2
    if half_mm <= EPS_MM:
        raise EditError(
            bay.id,
            f"This {size_before_mm:.1f} mm opening is too small to hold a "
            f"{board.thickness_mm:.1f} mm board with room on both sides.",
        )
    if parent.axis != axis:
        division = Division(
            axis=axis,
            items=[Bay(size_mm=half_mm), board, Bay(size_mm=half_mm)],
            size_mm=bay.size_mm,
        )
        return [division]
    return [Bay(size_mm=half_mm), board, Bay(size_mm=half_mm)]


def merge_at(unit: Unit, board_id: str) -> Unit:
    """``unit`` with the ``Board`` named ``board_id`` removed and the regions
    either side of it merged into one, moving nothing else while every
    constraint still holds.

    The merged region takes the first (lower-index) neighbor's id and a size
    of the neighbors' combined size plus the removed board's extent. When
    both neighbors had a Lock, it keeps the first's, in ``Basis.CLEAR`` and
    active only when both were; otherwise it has none. That is the exact
    inverse of :func:`split_region`. *Unless* the merge leaves its enclosing
    ``Division`` with only that one item left: the ``Division`` itself is
    then replaced by it, taking the ``Division``'s own size and Lock
    instead, which is what makes a split-then-merge round trip
    return the tree to its original shape rather than leaving a degenerate
    one-item ``Division`` behind. The second neighbor is discarded whole:
    when it is itself a ``Division``, every board and region in its subtree
    disappears with it, silently, rather than being refused, since the
    letter of "regions either side merged into one" does not distinguish a
    leaf region from a subtree. Raises :class:`EditError` naming
    ``board_id`` when it names no board in ``unit``, or a board whose
    neighbor on either side is missing (the end of a run) or is itself a
    ``Board`` rather than a region.

    A collapse can promote a surviving ``Division`` (``before``'s own
    subtree, carried up whole) to sit where the collapsing ``Division``
    used to, one level up in the tree. When that promoted ``Division``'s
    axis matches its *new* parent's axis, leaving it in place would produce
    bug-006's same-axis nesting through merge, so its items splice into the
    new parent's run in its place instead, each keeping its size and Lock.

    The constraints carry over as :func:`carry_constraints` carries them,
    so an Equal or even spacing on either merged region or ending at the
    board is dropped, as is a Lock on a region the merge discards, and an
    active one left unmet is solved again. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when that solve
    finds no layout.
    """
    return _structural(unit, _merged(unit, board_id))


@dataclasses.dataclass(frozen=True)
class _Merge:
    """Which regions one merge joined."""

    # The neighbor whose id the merged region takes.
    before_id: str
    # The neighbor discarded.
    after_id: str
    # The Division the merged region replaced, when the merge left it
    # holding nothing else.
    collapsed_id: str | None


def _merged(unit: Unit, board_id: str) -> Unit:
    """:func:`merge_at`'s tree edit alone, with its Locks moved and every
    other constraint left as it was."""
    new_root, merge, _collapsed = _merge_at(unit.root, board_id)
    if merge is None:
        raise EditError(board_id, "That is not a board of this unit.")
    merged = dataclasses.replace(
        unit, root=new_root, constraints=_merged_locks(unit.constraints, merge)
    )
    return _without_lost_locks(merged)


def _merged_locks(
    constraints: tuple[Constraint, ...], merge: _Merge
) -> tuple[Constraint, ...]:
    """``constraints`` with the Locks of ``merge``'s regions moved as
    :func:`merge_at` describes."""
    first = next(
        (
            c
            for c in constraints
            if isinstance(c, Lock) and c.region_id == merge.before_id
        ),
        None,
    )
    second = next(
        (
            c
            for c in constraints
            if isinstance(c, Lock) and c.region_id == merge.after_id
        ),
        None,
    )
    out: list[Constraint] = []
    for constraint in constraints:
        if constraint is second:
            continue
        if constraint is first:
            if second is None or merge.collapsed_id is not None:
                continue
            constraint = dataclasses.replace(
                constraint,
                basis=Basis.CLEAR,
                active=constraint.active and second.active,
            )
        elif (
            isinstance(constraint, Lock) and constraint.region_id == merge.collapsed_id
        ):
            constraint = dataclasses.replace(constraint, region_id=merge.before_id)
        out.append(constraint)
    return tuple(out)


def _without_lost_locks(unit: Unit) -> Unit:
    """``unit`` without the Locks whose regions its tree no longer holds."""
    present = keys_by_region(unit)
    kept = tuple(
        c for c in unit.constraints if not isinstance(c, Lock) or c.region_id in present
    )
    if len(kept) == len(unit.constraints):
        return unit
    return dataclasses.replace(unit, constraints=kept)


def _merge_at(region: Region, board_id: str) -> tuple[Region, _Merge | None, bool]:
    """``region`` with ``board_id`` merged away, which regions the merge
    joined, ``None`` when no board of that id is in its subtree, and whether
    *this call* collapsed ``region`` itself down to one promoted item. The third element
    is never true for a collapse passed up from deeper in the tree, so the
    caller splices only a ``Division`` this merge promoted, and leaves alone
    one that was same-axis nested for some other reason (unreachable through
    scanning or this module).
    """
    if not isinstance(region, Division):
        return region, None, False
    items = region.items
    for index, item in enumerate(items):
        if isinstance(item, Board) and item.id == board_id:
            if index == 0 or index == len(items) - 1:
                raise EditError(
                    board_id,
                    "This board is at the end of its row or column, so removing "
                    "it would not join two openings.",
                )
            before, after = items[index - 1], items[index + 1]
            if isinstance(before, Board) or isinstance(after, Board):
                raise EditError(
                    board_id,
                    "This board has another board beside it, so removing it "
                    "would not join two openings.",
                )
            merged: Region = dataclasses.replace(
                before,
                size_mm=before.size_mm + board_extent_mm(item) + after.size_mm,
            )
            merged_items = items[: index - 1] + [merged] + items[index + 2 :]
            if len(merged_items) == 1:
                collapsed = dataclasses.replace(merged, size_mm=region.size_mm)
                return collapsed, _Merge(before.id, after.id, region.id), True
            joined = _Merge(before.id, after.id, None)
            return dataclasses.replace(region, items=merged_items), joined, False
    new_items: list[Item] = []
    found: _Merge | None = None
    for item in items:
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_child, child_found, child_collapsed = _merge_at(item, board_id)
        if (
            child_collapsed
            and isinstance(new_child, Division)
            and new_child.axis == region.axis
        ):
            new_items.extend(new_child.items)
        else:
            new_items.append(new_child)
        found = found or child_found
    if found is not None:
        return dataclasses.replace(region, items=new_items), found, False
    return region, None, False


def remove_boards(unit: Unit, board_ids: Sequence[str]) -> Unit:
    """``unit`` with each board ``board_ids`` names removed by
    :func:`merge_at`, in order.

    A board that an earlier removal in this call discarded, as the second
    neighbor of a merge discards a whole subtree, is skipped. Raises the
    first :class:`EditError` any removal raises, so a refused board refuses
    the whole edit, including one ``board_ids`` names that is not a board of
    ``unit``. The constraints carry over and settle once, after the last
    removal, as for :func:`merge_at`.
    """
    present = _board_ids(unit.root)
    result = unit
    for board_id in board_ids:
        if board_id in present and board_id not in _board_ids(result.root):
            continue
        result = _merged(result, board_id)
    return _structural(unit, result)


def _board_ids(region: Region) -> frozenset[str]:
    if not isinstance(region, Division):
        return frozenset()
    ids: set[str] = set()
    for item in region.items:
        if isinstance(item, Board):
            ids.add(item.id)
        else:
            ids |= _board_ids(item)
    return frozenset(ids)


def set_thickness(unit: Unit, board_ids: Collection[str], thickness_mm: float) -> Unit:
    """``unit`` with each board ``board_ids`` names given ``thickness_mm``
    along its run, its outer size and every lock unchanged.

    The boards around the changed ones move as little as possible: a locked
    ``Basis.WITH_NEXT`` spacing keeps its spacing, so the board after it
    takes the change on its low face, and a locked ``Basis.CLEAR`` opening
    keeps its own size. Raises :class:`EditError` naming the offending id
    when ``thickness_mm`` is not positive, or when an id names nothing in
    ``unit``, a region, or a board whose size along its run comes from its
    ``extent_mm`` rather than its thickness; raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when the run
    cannot hold the new thickness.
    """
    if thickness_mm <= 0:
        raise EditError(
            next(iter(board_ids), unit.id),
            f"A thickness must be more than zero; got {thickness_mm:.1f} mm.",
        )
    axes: list[Axis] = []
    for board_id in board_ids:
        found = _locate(unit.root, board_id)
        if found is None:
            raise EditError(board_id, "That is not part of this unit.")
        parent, index = found
        item = parent.items[index]
        if not isinstance(item, Board):
            raise EditError(board_id, "That is an opening, not a board.")
        if item.extent_mm is not None:
            raise EditError(
                board_id,
                "This board's size along its row is set by the layout, not by "
                "its thickness.",
            )
        if parent.axis not in axes:
            axes.append(parent.axis)
    spaces = solve(unit)
    targets = frozenset(board_ids)
    spacings = frozenset(
        c.region_id
        for c in unit.constraints
        if isinstance(c, Lock) and c.active and c.basis is Basis.WITH_NEXT
    )
    result = dataclasses.replace(
        unit, root=_with_thickness(unit.root, targets, thickness_mm, spacings)
    )
    for axis in axes:
        result = solve_axis(result, spaces, axis, MIN_DRAG_GAP_MM)
    return result


def _with_thickness(
    region: Region,
    board_ids: frozenset[str],
    thickness_mm: float,
    spacings: frozenset[str],
) -> Region:
    """``region`` with every board in ``board_ids`` at ``thickness_mm``,
    copying only the paths down to them. A region in ``spacings``, the
    regions active ``Basis.WITH_NEXT`` locks hold, just before a changed
    board keeps its spacing, so its stored clear size takes the opposite
    change."""
    if not isinstance(region, Division):
        return region
    new_items: list[Item] = []
    changed = False
    for index, item in enumerate(region.items):
        if isinstance(item, Board):
            new_item: Item = (
                dataclasses.replace(item, thickness_mm=thickness_mm)
                if item.id in board_ids
                else item
            )
        else:
            new_item = _with_thickness(item, board_ids, thickness_mm, spacings)
            after = region.items[index + 1] if index + 1 < len(region.items) else None
            if (
                isinstance(after, Board)
                and after.id in board_ids
                and new_item.id in spacings
            ):
                new_item = dataclasses.replace(
                    new_item,
                    size_mm=new_item.size_mm + after.thickness_mm - thickness_mm,
                )
        changed = changed or new_item is not item
        new_items.append(new_item)
    return dataclasses.replace(region, items=new_items) if changed else region


def _locate(region: Region, node_id: str) -> tuple[Division, int] | None:
    """The ``Division`` whose ``items`` hold the node named ``node_id`` in
    ``region``'s subtree, and its index there, or ``None`` when no item
    matches (``region`` itself included, since it has no parent here)."""
    if not isinstance(region, Division):
        return None
    for index, item in enumerate(region.items):
        if item.id == node_id:
            return region, index
    for item in region.items:
        if isinstance(item, Board):
            continue
        found = _locate(item, node_id)
        if found is not None:
            return found
    return None


def _locate_region(unit: Unit, region_id: str) -> tuple[Division, int]:
    """:func:`_locate` for a region a size edit may act on. Raises
    :class:`EditError` naming ``region_id`` when it is the tree's root (its
    extent is the unit's own size), a board, or absent."""
    if unit.root.id == region_id:
        raise EditError(
            region_id,
            "That is the whole unit: resize the unit to change its size.",
        )
    found = _locate(unit.root, region_id)
    if found is None:
        raise EditError(region_id, "That is not part of this unit.")
    parent, index = found
    if isinstance(parent.items[index], Board):
        raise EditError(region_id, "That is a board; select an opening to size.")
    return found


def _next_board(parent: Division, index: int, basis: Basis) -> Board | None:
    """The board a ``basis`` size at ``parent.items[index]`` measures across:
    ``None`` for ``Basis.CLEAR``. Raises :class:`EditError` for
    ``Basis.WITH_NEXT`` when the next item is missing or is not a board."""
    if basis is Basis.CLEAR:
        return None
    region_id = parent.items[index].id
    if index + 1 < len(parent.items):
        after = parent.items[index + 1]
        if isinstance(after, Board):
            return after
    raise EditError(
        region_id,
        "This opening has no board after it, so it has no spacing to measure.",
    )


def _with_size(region: Region, region_id: str, size_mm: float) -> Region:
    """``region`` with the region named ``region_id`` at ``size_mm``,
    copying only the path down to it."""
    if region.id == region_id:
        return dataclasses.replace(region, size_mm=size_mm)
    if not isinstance(region, Division):
        return region
    new_items: list[Item] = []
    changed = False
    for item in region.items:
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_item = _with_size(item, region_id, size_mm)
        changed = changed or new_item is not item
        new_items.append(new_item)
    return dataclasses.replace(region, items=new_items) if changed else region


def _locked(unit: Unit, region_id: str, basis: Basis) -> Unit:
    """``unit`` with the region ``region_id`` held by an active Lock in
    ``basis``: its Lock, turned on and changed in place, or a new one after
    the other constraints."""
    found = region_lock(unit, region_id)
    if found is None:
        return dataclasses.replace(
            unit, constraints=(*unit.constraints, Lock(region_id, basis))
        )
    return _with_constraint(unit, dataclasses.replace(found, basis=basis, active=True))


def _fixed_offset_mm(unit: Unit, axis: Axis, size_mm: Vec3) -> float:
    """How far past ``unit``'s minimum corner along ``axis`` its fixed side
    lies on a box of size ``size_mm``."""
    index = axis.component_index
    return FIXED_FRACTION[unit.fixed_point.side(axis)] * size_mm.component_mm(index)


def fixed_point_mm(unit: Unit) -> Vec3:
    """``unit``'s fixed point in the frame its boards are written in: on
    each axis the low face, the midpoint or the high face of the box
    ``unit.size_mm`` measures, as ``unit.fixed_point`` names."""
    position_mm = unit.position_mm
    return Vec3(
        position_mm.x_mm + _fixed_offset_mm(unit, Axis.X, unit.size_mm),
        position_mm.y_mm + _fixed_offset_mm(unit, Axis.Y, unit.size_mm),
        position_mm.z_mm + _fixed_offset_mm(unit, Axis.Z, unit.size_mm),
    )


# The narrowest opening an edit leaves: a drag or a resize stops pushing an
# opening there, and a typed size under it is refused. Undo, Redo and
# reopening each rescan the boards, and a rescan drops a region whose faces
# sit within the scan's clearance plus its snap, so the floor stays clear of
# both.
MIN_DRAG_GAP_MM = 5.0


def set_unit_size(unit: Unit, size_mm: Vec3) -> Unit:
    """``unit`` with outer size ``size_mm`` and :func:`fixed_point_mm` where
    it was.

    Inside, the boards move as little as possible: the openings beside the
    outer faces that move take up the change, and push the boards beyond
    them once they reach :data:`MIN_DRAG_GAP_MM`. An axis whose size
    ``size_mm`` leaves as it is changes nothing there, even when locks
    determine it. Raises :class:`EditError` naming ``unit.id`` when any axis
    of ``size_mm`` is not positive, and a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when the locks
    and that minimum leave no room for the size, or when it changes a size
    the locks determine (:func:`~freecad.Shelving.core.solver.size_fixed_by`),
    naming those locks.
    """
    for axis, value_mm in zip(
        Axis, (size_mm.x_mm, size_mm.y_mm, size_mm.z_mm), strict=True
    ):
        if value_mm <= 0:
            raise EditError(
                unit.id,
                f"A unit's size along {axis.value} must be more than zero; "
                f"got {value_mm:.1f} mm.",
            )
    spaces = solve(unit)
    result = unit
    for axis in Axis:
        index = axis.component_index
        wanted_mm = size_mm.component_mm(index)
        if wanted_mm == unit.size_mm.component_mm(index):
            continue
        result = solve_axis(result, spaces, axis, MIN_DRAG_GAP_MM, size_mm=wanted_mm)
    return result


def set_size(unit: Unit, region_id: str, size_mm: float, basis: Basis) -> Unit:
    """``unit`` with the region named ``region_id`` locked at ``size_mm``
    measured in ``basis``, the boards around it moved as little as possible
    and the unit's outer size unchanged; when both boards bounding the
    region are free, each moves half the change. The region's Lock is
    turned on and takes ``basis``, or a new one is added after the other
    constraints.

    Raises :class:`EditError` naming ``region_id`` when the clear size
    ``size_mm`` gives is under :data:`MIN_DRAG_GAP_MM`, whatever the
    region's size now, since the next scan would drop so narrow an opening;
    when ``basis`` is ``Basis.WITH_NEXT`` and the next item in the region's
    run is not a board; or when ``region_id`` names the root, a board, or
    nothing in ``unit``. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when the other
    locks and the minimum leave no room for the size.
    """
    parent, index = _locate_region(unit, region_id)
    board = _next_board(parent, index, basis)
    clear_mm = size_mm if board is None else size_mm - board.thickness_mm
    if clear_mm < MIN_DRAG_GAP_MM - EPS_MM:
        raise EditError(
            region_id,
            f"That leaves the opening {clear_mm:.1f} mm, under the "
            f"{MIN_DRAG_GAP_MM:.1f} mm minimum.",
        )
    spaces = solve(unit)
    edited = _locked(
        dataclasses.replace(unit, root=_with_size(unit.root, region_id, clear_mm)),
        region_id,
        basis,
    )
    return solve_axis(edited, spaces, parent.axis, MIN_DRAG_GAP_MM)


def size_in_basis_mm(
    parent: Division,
    index: int,
    clear_mm: float,
    basis: Basis,
) -> float:
    """``clear_mm`` restated in ``basis`` for ``parent.items[index]``.

    A spacing adds the next board's ``thickness_mm`` rather than its extent
    along the run, the same amount :func:`set_size` subtracts; the two
    differ for a board carrying an ``extent_mm``. Raises :class:`EditError`
    naming the region for ``Basis.WITH_NEXT`` when no board follows it.
    """
    board = _next_board(parent, index, basis)
    if board is None:
        return clear_mm
    return clear_mm + board.thickness_mm


def set_basis(unit: Unit, region_id: str, basis: Basis) -> Unit:
    """``unit`` with the region named ``region_id`` locked in ``basis`` at
    its current size, moving nothing: its Lock turned on and changed in
    place, or a new one after the other constraints.

    Raises :class:`EditError` naming ``region_id`` when ``basis`` is
    ``Basis.WITH_NEXT`` and the next item in the region's run is not a
    board, or when ``region_id`` names the root, a board, or nothing in
    ``unit``.
    """
    parent, index = _locate_region(unit, region_id)
    _next_board(parent, index, basis)
    return _locked(unit, region_id, basis)


def run_axis(unit: Unit, node_id: str) -> Axis:
    """The axis of the run holding the node named ``node_id``: the axis its
    size or thickness is measured along. Raises :class:`EditError` naming
    ``node_id`` when it names the root or nothing in ``unit``."""
    found = _locate(unit.root, node_id)
    if found is None:
        raise EditError(node_id, "That is not part of this unit.")
    return found[0].axis


def _board_and_region_before(unit: Unit, board_id: str) -> tuple[Division, int]:
    """The run holding ``board_id`` and the index of the region immediately
    before it. Raises :class:`EditError` naming ``board_id`` when it names
    no board, or a board with no region immediately before it."""
    found = _locate(unit.root, board_id)
    if found is None or not isinstance(found[0].items[found[1]], Board):
        raise EditError(board_id, "That is not a board of this unit.")
    parent, index = found
    if index == 0 or isinstance(parent.items[index - 1], Board):
        raise EditError(
            board_id,
            "This board has no opening below or left of it for a drag to resize.",
        )
    return parent, index - 1


def region_before(unit: Unit, board_id: str) -> str:
    """The id of the region immediately before the board ``board_id`` in its
    run, the one whose dimension a drag's arrow sits beside. Raises
    :class:`EditError` naming ``board_id`` when it names no board, or a board
    with no region immediately before it."""
    parent, index = _board_and_region_before(unit, board_id)
    return parent.items[index].id


def lock(unit: Unit, region_id: str) -> Unit:
    """``unit`` with the region named ``region_id`` locked at its current
    size, moving nothing: its deactivated Lock turned on, keeping its basis,
    or a new ``Basis.CLEAR`` Lock appended after the other constraints.
    Returns ``unit`` itself when an active Lock already holds the region.
    Raises :class:`EditError` for the root, a board, or an unknown id. The
    lock may make the unit's size along the run a reference, or duplicate
    other constraints; neither is refused.
    """
    _locate_region(unit, region_id)
    if is_locked(unit, region_id):
        return unit
    found = region_lock(unit, region_id)
    return _locked(unit, region_id, Basis.CLEAR if found is None else found.basis)


def unlock(unit: Unit, region_id: str) -> Unit:
    """``unit`` without the active Lock holding the region named
    ``region_id``, moving nothing. Returns ``unit`` itself when no active
    Lock holds it. Raises :class:`EditError` for the root, a board, or an
    unknown id."""
    _locate_region(unit, region_id)
    found = region_lock(unit, region_id)
    if found is None or not found.active:
        return unit
    return remove_constraints(unit, (found.id,))


@dataclasses.dataclass(frozen=True)
class Held:
    """What keeps a drag from moving a board, as :func:`held_by` finds it."""

    # The active Locks to remove, low side first.
    locks: tuple[ConstraintId, ...] = ()
    # The other active constraints that hold the board with those Locks
    # removed, in the unit's order. No unlock frees a board one holds.
    constraints: tuple[ConstraintId, ...] = ()

    @property
    def free(self) -> bool:
        """Whether a drag may move the board as it is."""
        return not self.locks and not self.constraints


def held_by(unit: Unit, board_id: str) -> Held | None:
    """What holds the board ``board_id`` against a drag.

    :attr:`Held.free` when a drag may move the board: with the unit's outer
    faces held, the active constraints leave its position free, whatever the
    openings' minimum widths allow. Otherwise the fewest Locks whose removal
    frees it, or that removal leaves to the other constraints: the Lock
    nearest the board on each blocked side, low side first, and further ones
    only when those leave it held, as across nested runs. When other
    constraints still hold it with those removed, they are named and the
    board stays held whatever is unlocked. ``None`` when
    ``board_id`` names no board, or the boards alone hold it, as for a
    carcass board.
    """
    found = _locate(unit.root, board_id)
    if found is None or not isinstance(found[0].items[found[1]], Board):
        return None
    axis = found[0].axis
    axis_index = axis.component_index
    spaces = solve(unit)
    board_space = spaces[board_id]
    low_face_mm = board_space.origin_mm(axis_index)
    high_face_mm = low_face_mm + board_space.extent_mm(axis_index)
    order: dict[ConstraintId, int] = {
        constraint.id: index for index, constraint in enumerate(unit.constraints)
    }
    held_region = {
        c.id: spaces[c.region_id]
        for c in unit.constraints
        if isinstance(c, Lock) and c.region_id in spaces
    }
    low_side: list[ConstraintId] = []
    high_side: list[ConstraintId] = []
    while True:
        fixing = fixing_locks(unit, spaces, board_id, axis, low_side + high_side)
        if fixing is None:
            return Held(locks=tuple(low_side + high_side))
        if not fixing:
            return None
        locks = [c for c in fixing if c in held_region]
        if not locks:
            return Held(
                locks=tuple(low_side + high_side),
                constraints=tuple(sorted(fixing, key=order.__getitem__)),
            )
        below = [c for c in locks if held_region[c].origin_mm(axis_index) < low_face_mm]
        above = [c for c in locks if c not in below]
        if below:
            low_side.append(
                max(
                    below,
                    key=lambda c: (
                        held_region[c].origin_mm(axis_index)
                        + held_region[c].extent_mm(axis_index)
                    ),
                )
            )
        if above:
            high_side.append(
                min(
                    above,
                    key=lambda c: held_region[c].origin_mm(axis_index) - high_face_mm,
                )
            )


def require_movable(unit: Unit, board_id: str) -> None:
    """Return when a drag may move the board ``board_id``. Raises
    :class:`EditError` naming ``board_id`` when :func:`held_by` gives
    ``None`` or names other constraints, and naming the region of the
    nearest holding Lock when it names only Locks."""
    held = held_by(unit, board_id)
    if held is None:
        raise EditError(board_id, "This board has no opening on each side to move.")
    if held.constraints:
        raise EditError(board_id, "A constraint holds this board in place.")
    if held.locks:
        holder = next(
            c.region_id
            for c in unit.constraints
            if isinstance(c, Lock) and c.id == held.locks[0]
        )
        raise EditError(holder, "A locked opening holds this board in place.")


def move_board(unit: Unit, board_id: str, low_face_mm: float) -> Unit:
    """``unit`` with the board named ``board_id`` dragged so its low face
    along its run's axis sits at ``low_face_mm`` (a unit-frame coordinate),
    or as near to it as the constraints allow.

    The unit's outer faces hold and every lock keeps its size, so boards
    joined to the dragged one through locked regions move with it. Every
    other board moves as little as it can: an opening shrinks until it
    reaches :data:`MIN_DRAG_GAP_MM`, or its current size when that is
    already smaller, and then pushes the boards ahead of it, in nested runs
    too. Nothing is locked or unlocked. Raises :class:`EditError` as
    :func:`require_movable` does.
    """
    require_movable(unit, board_id)
    axis = run_axis(unit, board_id)
    return solve_axis(
        unit, solve(unit), axis, MIN_DRAG_GAP_MM, target=(board_id, low_face_mm)
    )


@dataclasses.dataclass(frozen=True)
class Measurement:
    """A region's size as the editor shows it."""

    # What the region's size measures: its Lock's basis, active or not, or
    # Basis.CLEAR for a region with none, which is what a typed size would
    # lock it in.
    basis: Basis
    # Whether an active Lock holds the region.
    fixed: bool
    clear_mm: float
    # clear_mm plus the next board's thickness_mm, the number a
    # Basis.WITH_NEXT lock measures; None when no board follows the region.
    spacing_mm: float | None

    @property
    def size_mm(self) -> float:
        """The size in :attr:`basis`: the number a field shows for it."""
        if self.basis is Basis.WITH_NEXT and self.spacing_mm is not None:
            return self.spacing_mm
        return self.clear_mm


def measure(unit: Unit, region_id: str, spaces: Mapping[str, Space]) -> Measurement:
    """The :class:`Measurement` of the region named ``region_id``, read from
    ``spaces``, which must be ``unit``'s solve. Raises :class:`EditError`
    when ``region_id`` names the root, a board, or nothing, the regions
    :func:`set_size` refuses."""
    parent, index = _locate_region(unit, region_id)
    region = parent.items[index]
    assert not isinstance(region, Board)
    clear_mm = spaces[region_id].extent_mm(parent.axis.component_index)
    spacing_mm: float | None = None
    if index + 1 < len(parent.items) and isinstance(parent.items[index + 1], Board):
        spacing_mm = size_in_basis_mm(parent, index, clear_mm, Basis.WITH_NEXT)
    found = region_lock(unit, region_id)
    return Measurement(
        basis=Basis.CLEAR if found is None else found.basis,
        fixed=found is not None and found.active,
        clear_mm=clear_mm,
        spacing_mm=spacing_mm,
    )


def _region_carried(
    region_id: str,
    before_keys: Mapping[str, str],
    after_keys: Mapping[str, str],
    after_by_key: Mapping[str, str],
) -> str | None:
    """The id in the edited tree of the region ``region_id`` named before
    the edit: its own id while the boards bounding it are unchanged, else
    the one region bounded as it was; ``None`` when its bounding boards
    changed, as when a board beside it was deleted or a board added along
    its run split it."""
    key = before_keys.get(region_id)
    if key is None:
        return None
    if after_keys.get(region_id) == key:
        return region_id
    return after_by_key.get(key)


def _run_carried(
    spacing: EvenSpacing,
    before: Unit,
    after: Unit,
    before_keys: Mapping[str, str],
    after_by_key: Mapping[str, str],
) -> Division | None:
    """The run ``spacing`` lies in after the edit: the one holding a board
    end, else the run found again as :func:`_region_carried` finds a region,
    or the root when the run was the root. ``None`` when that run is gone
    or now runs along another axis."""
    old_run = find_division(before.root, spacing.run_id)
    if old_run is None:
        return None
    for end in (spacing.start, spacing.end):
        if not isinstance(end, RunEnd):
            found = _locate(after.root, end)
            run = None if found is None else found[0]
            return run if run is not None and run.axis is old_run.axis else None
    if old_run.id == before.root.id:
        run_id: str | None = after.root.id
    else:
        run_id = _region_carried(
            old_run.id, before_keys, keys_by_region(after), after_by_key
        )
    run = None if run_id is None else find_division(after.root, run_id)
    return run if run is not None and run.axis is old_run.axis else None


def carry_constraints(before: Unit, after: Unit) -> Unit:
    """``after``, an edit of ``before``'s tree, with the constraints that
    still hold their regions renamed to them and the rest dropped.

    ``after`` carries ``before``'s constraints with its Locks already moved
    by the edit, since only the edit knows which region takes a Lock; a
    Lock whose region ``after`` no longer holds is dropped. An ``Equal`` is
    dropped when either opening's bounding boards changed: deleting a board
    beside it merges it away, and a board added along its run splits it. A
    board added across its run keeps it, since its slot and size are
    unchanged. An ``EvenSpacing`` is kept while its ends are still in one
    run along its axis, in order, whatever happens between them. Keeps each
    constraint's order, id and active flag.
    """
    before_keys = keys_by_region(before)
    after_keys = keys_by_region(after)
    after_by_key = unique_regions_by_key(after)
    carried: list[Constraint] = []
    for constraint in after.constraints:
        if isinstance(constraint, Lock):
            if constraint.region_id in after_keys:
                carried.append(constraint)
            continue
        if isinstance(constraint, Equal):
            first, second = (
                _region_carried(region_id, before_keys, after_keys, after_by_key)
                for region_id in constraint.region_ids
            )
            if first is None or second is None:
                continue
            carried.append(dataclasses.replace(constraint, region_ids=(first, second)))
            continue
        run = _run_carried(constraint, before, after, before_keys, after_by_key)
        if run is None:
            continue
        moved = dataclasses.replace(constraint, run_id=run.id)
        if spacing_group(after, moved) is None:
            continue
        carried.append(moved)
    return dataclasses.replace(after, constraints=tuple(carried))


def settle_constraints(unit: Unit) -> Unit:
    """``unit`` with every axis that holds an active constraint its sizes
    miss by more than :data:`~freecad.Shelving.core.solver.EPS_MM` solved
    again, moving the boards as little as possible; ``unit`` itself when
    every active constraint holds. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when no layout
    meets them."""
    spaces = solve(unit)
    axes: list[Axis] = []
    for constraint in unit.constraints:
        if not constraint.active:
            continue
        spread_mm = constraint_spread_mm(unit, spaces, constraint)
        axis = constraint_axis(unit, constraint)
        if spread_mm is None or spread_mm <= EPS_MM or axis is None:
            continue
        if axis not in axes:
            axes.append(axis)
    result = unit
    for axis in axes:
        result = solve_axis(result, spaces, axis, MIN_DRAG_GAP_MM)
    return result


def _structural(before: Unit, after: Unit) -> Unit:
    """``after``, a structural edit of ``before``, with the constraints
    carried over and settled."""
    if not before.constraints:
        return after
    return settle_constraints(carry_constraints(before, after))


def _opening(unit: Unit, region_id: str) -> tuple[Division, int]:
    """The run holding the opening ``region_id`` and its index there. Raises
    :class:`EditError` naming ``region_id`` when it names a board, the whole
    unit, or nothing."""
    if unit.root.id == region_id:
        raise EditError(region_id, "Select openings, not the whole unit.")
    found = _locate(unit.root, region_id)
    if found is None:
        raise EditError(region_id, "That is not part of this unit.")
    if isinstance(found[0].items[found[1]], Board):
        raise EditError(region_id, "Select openings for Equal, not boards.")
    return found


def add_equal(unit: Unit, region_ids: Sequence[str]) -> Unit:
    """``unit`` with an :class:`~freecad.Shelving.core.layout.Equal` between
    each two openings next to each other in ``region_ids``, so N openings
    make N-1 constraints chained in that order, appended after its others.
    The first opening keeps its size and the others change to match it, as
    the Sketcher's Equal takes the first selection's size, with the unit's
    size unchanged and the other boards moving as little as possible. When
    the locks and constraints rule out keeping both sizes, the openings meet
    wherever moving the boards least puts them, and the unit's size changes
    only where the locks and constraints fix it.

    Raises :class:`EditError` when ``region_ids`` holds fewer than two
    distinct openings, names a board, the whole unit or nothing, or names
    openings whose runs lie along different axes. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` naming the
    locks and constraints that rule the new ones out.
    """
    distinct = list(dict.fromkeys(region_ids))
    if len(distinct) < 2:
        raise EditError(
            distinct[0] if distinct else unit.id,
            "Select two or more openings to make equal.",
        )
    axes = {_opening(unit, region_id)[0].axis for region_id in distinct}
    if len(axes) > 1:
        raise EditError(
            distinct[0],
            "Select openings that are all widths or all heights to make equal.",
        )
    added = tuple(
        Equal(region_ids=(first, second))
        for first, second in zip(distinct, distinct[1:], strict=False)
    )
    edited = dataclasses.replace(unit, constraints=(*unit.constraints, *added))
    return _solved_holding(unit, edited, axes.pop(), distinct[:1])


def _solved_holding(unit: Unit, edited: Unit, axis: Axis, held: Sequence[str]) -> Unit:
    """``edited``, ``unit`` with constraints added, solved along ``axis``
    from where ``unit``'s boards stand, each region ``held`` names and the
    unit itself keeping its current size there, as a Lock would hold it,
    wherever the locks and constraints allow. When they rule that out, it
    is solved as :func:`~freecad.Shelving.core.solver.solve_axis` solves
    ``edited`` alone. ``edited``'s constraints come back unchanged.
    Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` only when
    ``edited`` itself has no layout."""
    spaces = solve(unit)
    holding = edited
    for region_id in held:
        holding = lock(holding, region_id)
    if holding is not edited:
        # Without size_mm a hold whose Locks fill the run would resize the
        # unit; pinning the size makes that a conflict, so it falls back.
        try:
            solved = solve_axis(
                holding,
                spaces,
                axis,
                MIN_DRAG_GAP_MM,
                size_mm=unit.size_mm.component_mm(axis.component_index),
            )
        except LayoutSolveError:
            pass
        else:
            return dataclasses.replace(solved, constraints=edited.constraints)
    return solve_axis(edited, spaces, axis, MIN_DRAG_GAP_MM)


def _spacing_end(run: Division, index: int, step: int) -> SpacingEnd | None:
    """What bounds ``run.items[index]`` on the side ``step`` points to: the
    board there, the run's own end, or ``None`` for another region."""
    neighbor = index + step
    if neighbor < 0:
        return RunEnd.START
    if neighbor >= len(run.items):
        return RunEnd.END
    item = run.items[neighbor]
    return item.id if isinstance(item, Board) else None


def add_even_spacing(unit: Unit, node_ids: Sequence[str]) -> Unit:
    """``unit`` with an :class:`~freecad.Shelving.core.layout.EvenSpacing`
    appended after its other constraints. Its ends and the unit's size stay
    as they are and the openings between them share the span. When the
    locks and constraints rule out holding the ends, the openings share
    whatever span moving the boards least leaves them, and the unit's size
    changes only where the locks and constraints fix it.

    ``node_ids`` names two boards of one run, which become its ends, or two
    or more openings of one run: then its group runs from the first opening
    to the last in run order, and each end is the board bounding it there
    or the run's own end. Raises :class:`EditError` for any other
    selection, for an opening bounded there by another opening, and when
    fewer than two openings lie between the ends. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` naming the
    locks and constraints that rule it out.
    """
    return _add_even_spacing(
        unit,
        node_ids,
        "Select two boards of one row or column, or two or more openings of "
        "one row or column, to space evenly.",
    )


def _add_even_spacing(unit: Unit, node_ids: Sequence[str], what: str) -> Unit:
    """:func:`add_even_spacing`, refusing a selection of the wrong shape
    with the message ``what``."""
    distinct = list(dict.fromkeys(node_ids))
    if len(distinct) < 2:
        raise EditError(distinct[0] if distinct else unit.id, what)
    found = [_locate(unit.root, node_id) for node_id in distinct]
    if any(place is None for place in found) or unit.root.id in distinct:
        raise EditError(distinct[0], what)
    places = [place for place in found if place is not None]
    run = places[0][0]
    if any(place[0] is not run for place in places):
        raise EditError(distinct[0], what)
    indices = sorted(index for _run, index in places)
    boards = [isinstance(run.items[index], Board) for index in indices]
    start: SpacingEnd | None
    end: SpacingEnd | None
    if all(boards) and len(indices) == 2:
        start, end = run.items[indices[0]].id, run.items[indices[1]].id
    elif not any(boards):
        start = _spacing_end(run, indices[0], -1)
        end = _spacing_end(run, indices[-1], 1)
        if start is None or end is None:
            raise EditError(
                distinct[0],
                "Select the boards at the ends instead: an opening at an end "
                "of this selection has another opening beside it, with no "
                "board between them.",
            )
    else:
        raise EditError(distinct[0], what)
    spacing = EvenSpacing(run_id=run.id, start=start, end=end)
    edited = dataclasses.replace(unit, constraints=(*unit.constraints, spacing))
    group = spacing_group(edited, spacing)
    if group is None or len(group) < 2:
        raise EditError(
            distinct[0],
            "Select ends with two or more openings between them to space evenly.",
        )
    # Holding everything outside the span keeps its ends where they stand.
    # In a nested run the ends also move when an enclosing run along the
    # same axis shifts the run, which the least-movement solve does to
    # spare the boards inside the span, so every enclosing run along
    # run.axis is held too.
    held = [
        item.id
        for item in run.items
        if not isinstance(item, Board) and item.id not in group
    ]
    parents = parent_divisions(unit.root)
    parent = parents.get(run.id)
    while parent is not None:
        if parent.axis == run.axis:
            held.extend(item.id for item in parent.items if not isinstance(item, Board))
        parent = parents.get(parent.id)
    return _solved_holding(unit, edited, run.axis, held)


# The elevation word an axis-taking command's messages use. Whole sentences
# per word follow, so each translates on its own.
_Elevation = Literal["width", "height"]

_SELECT_TO_EQUAL: Mapping[_Elevation, str] = {
    "width": "Select openings in two or more columns to make their widths equal.",
    "height": "Select openings in two or more rows to make their heights equal.",
}
_NO_BOARDS_TO_EQUAL: Mapping[_Elevation, str] = {
    "width": "Select openings for Equal Width, not boards.",
    "height": "Select openings for Equal Height, not boards.",
}
_UNIT_SIZE_TO_EQUAL: Mapping[_Elevation, str] = {
    "width": (
        "A selected opening's width is the unit's width. Select openings in "
        "two or more columns to make their widths equal."
    ),
    "height": (
        "A selected opening's height is the unit's height. Select openings in "
        "two or more rows to make their heights equal."
    ),
}
_SELECT_TO_SPACE: Mapping[_Elevation, str] = {
    "width": (
        "Select two dividers of one row, or openings in two or more columns "
        "of one row, to space their widths evenly."
    ),
    "height": (
        "Select two shelves of one column, or openings in two or more rows "
        "of one column, to space their heights evenly."
    ),
}
_UNIT_SIZE_TO_SPACE: Mapping[_Elevation, str] = {
    "width": (
        "A selected opening's width is the unit's width. Select two dividers "
        "of one row, or openings in two or more columns of one row, to space "
        "their widths evenly."
    ),
    "height": (
        "A selected opening's height is the unit's height. Select two shelves "
        "of one column, or openings in two or more rows of one column, to "
        "space their heights evenly."
    ),
}


def _elevation(unit: Unit, axis: Axis) -> _Elevation:
    """Whether ``axis`` is ``unit``'s elevation height or, for any other
    axis, its width; a unit with no depth axis stands upright along Z."""
    depth_axis = Axis.Y if unit.depth_axis is None else unit.depth_axis
    return "height" if axis is elevation_axes(depth_axis)[1] else "width"


def _is_board(unit: Unit, node_id: str) -> bool:
    found = _locate(unit.root, node_id)
    return found is not None and isinstance(found[0].items[found[1]], Board)


def _openings_along(
    unit: Unit, node_ids: Sequence[str], axis: Axis, unit_size: str
) -> list[str]:
    """The distinct regions, in selection order, whose sizes along ``axis``
    hold the openings ``node_ids`` names, each found by
    :func:`~freecad.Shelving.core.layout.region_along`. Raises
    :class:`EditError` with the message ``unit_size`` naming the first
    opening whose size along ``axis`` is the unit's own, and as
    :func:`add_equal` does for the whole unit or an unknown id. The caller
    has already refused boards."""
    found: dict[str, None] = {}
    for node_id in node_ids:
        _opening(unit, node_id)
        target = region_along(unit, node_id, axis)
        if target is None:
            raise EditError(node_id, unit_size)
        found[target] = None
    return list(found)


def add_equal_along(unit: Unit, node_ids: Sequence[str], axis: Axis) -> Unit:
    """:func:`add_equal` on the regions whose sizes along ``axis`` hold the
    openings ``node_ids`` names, each the opening itself or its nearest
    enclosing region whose run lies along ``axis``, as Lock Width and Lock
    Height find them. Picks resolving to one region count once, keeping
    the first's place in selection order.

    Raises :class:`EditError` when ``node_ids`` names a board, the whole
    unit or nothing, an opening whose size along ``axis`` is the unit's
    own, or fewer than two distinct regions, and a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` as
    :func:`add_equal` does.
    """
    word = _elevation(unit, axis)
    board = next((n for n in node_ids if _is_board(unit, n)), None)
    if board is not None:
        raise EditError(board, _NO_BOARDS_TO_EQUAL[word])
    regions = _openings_along(unit, node_ids, axis, _UNIT_SIZE_TO_EQUAL[word])
    if len(regions) < 2:
        raise EditError(node_ids[0] if node_ids else unit.id, _SELECT_TO_EQUAL[word])
    return add_equal(unit, regions)


def add_even_spacing_along(unit: Unit, node_ids: Sequence[str], axis: Axis) -> Unit:
    """:func:`add_even_spacing` along ``axis``: openings resolve as
    :func:`add_equal_along` resolves them, and boards must lie in a run
    along ``axis``.

    Raises :class:`EditError` for a selection mixing boards and openings,
    for boards whose run lies along another axis, for an opening whose
    size along ``axis`` is the unit's own, and for anything
    :func:`add_even_spacing` refuses; a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` as it raises.
    """
    word = _elevation(unit, axis)
    what = _SELECT_TO_SPACE[word]
    boards = [_is_board(unit, node_id) for node_id in node_ids]
    if any(boards):
        if not all(boards):
            raise EditError(node_ids[0], what)
        across = next((n for n in node_ids if run_axis(unit, n) is not axis), None)
        if across is not None:
            raise EditError(across, what)
        return _add_even_spacing(unit, node_ids, what)
    regions = _openings_along(unit, node_ids, axis, _UNIT_SIZE_TO_SPACE[word])
    return _add_even_spacing(unit, regions, what)


def remove_constraints(unit: Unit, constraint_ids: Collection[ConstraintId]) -> Unit:
    """``unit`` without the constraints ``constraint_ids`` names, active or
    deactivated, moving nothing. Raises :class:`EditError` naming the first
    id that names no constraint of ``unit``."""
    known = {constraint.id for constraint in unit.constraints}
    for constraint_id in constraint_ids:
        if constraint_id not in known:
            raise EditError(constraint_id, "That constraint is not part of this unit.")
    return dataclasses.replace(
        unit,
        constraints=tuple(c for c in unit.constraints if c.id not in constraint_ids),
    )


def _constraint(unit: Unit, constraint_id: ConstraintId) -> Constraint:
    """The constraint of ``unit`` named ``constraint_id``. Raises
    :class:`EditError` naming it when ``unit`` has none."""
    for constraint in unit.constraints:
        if constraint.id == constraint_id:
            return constraint
    raise EditError(constraint_id, "That constraint is not part of this unit.")


def _with_constraint(unit: Unit, replacement: Constraint) -> Unit:
    """``unit`` with the constraint sharing ``replacement``'s id replaced by
    it, in place."""
    return dataclasses.replace(
        unit,
        constraints=tuple(
            replacement if c.id == replacement.id else c for c in unit.constraints
        ),
    )


def _solved_constraint(unit: Unit, edited: Unit, constraint: Constraint) -> Unit:
    """``edited``, ``unit`` with ``constraint`` changed, solved along its
    axis from where ``unit``'s boards stand; ``edited`` itself when the
    constraint holds no region."""
    axis = constraint_axis(edited, constraint)
    if axis is None:
        return edited
    return solve_axis(edited, solve(unit), axis, MIN_DRAG_GAP_MM)


def set_constraint_active(
    unit: Unit, constraint_id: ConstraintId, active: bool
) -> Unit:
    """``unit`` with the constraint ``constraint_id`` activated or
    deactivated; ``unit`` itself when it already is. Deactivating moves
    nothing, and neither does activating a Lock, which holds its opening at
    its current size. Activating any other solves it in, moving the boards
    as little as possible, as adding it new would.

    Raises :class:`EditError` naming ``constraint_id`` when ``unit`` has no
    such constraint, and a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` naming the
    locks and constraints, this one included, that rule an activation out.
    """
    constraint = _constraint(unit, constraint_id)
    if constraint.active is active:
        return unit
    changed = dataclasses.replace(constraint, active=active)
    edited = _with_constraint(unit, changed)
    if not active or isinstance(changed, Lock):
        return edited
    return _solved_constraint(unit, edited, changed)


def remove_deactivated(unit: Unit) -> Unit:
    """``unit`` without its deactivated constraints, moving nothing; the
    active ones keep their order."""
    return dataclasses.replace(
        unit, constraints=tuple(c for c in unit.constraints if c.active)
    )


def set_constraint_basis(unit: Unit, constraint_id: ConstraintId, basis: Basis) -> Unit:
    """``unit`` with the constraint ``constraint_id`` measuring its openings
    in ``basis``; ``unit`` itself when it already does. An active
    constraint is solved again in its new basis, moving the boards as
    little as possible; a deactivated one or a Lock moves nothing.

    Raises :class:`EditError` naming ``constraint_id`` when ``unit`` has no
    such constraint, and naming an opening for ``Basis.WITH_NEXT`` when no
    board follows that opening in its run. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` as
    :func:`set_constraint_active` does.
    """
    constraint = _constraint(unit, constraint_id)
    if constraint.basis is basis:
        return unit
    for region_id in constraint_regions(unit, constraint):
        _next_board(*_locate_region(unit, region_id), basis)
    changed = dataclasses.replace(constraint, basis=basis)
    edited = _with_constraint(unit, changed)
    if not changed.active or isinstance(changed, Lock):
        return edited
    return _solved_constraint(unit, edited, changed)
