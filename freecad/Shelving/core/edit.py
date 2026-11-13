"""Tree-rewriting edits for the elevation editor: split a bay, merge a board,
remove several boards, size a region, change what a size measures, lock or
unlock a region, drag a board, change boards' thickness, and make or remove
Equal and even spacing constraints.

A region with a ``lock`` holds its size through edits; an unlocked one
takes whatever size the boards around it leave. Any region may lock. Where
the locks determine the unit's size along an axis, that size is a reference:
:func:`set_unit_size` refuses to change it, and every other edit lets it
follow the locks with the unit's fixed point holding. Every edit returns a unit
whose stored sizes are already solved: one that moves boards solves them with
:func:`~freecad.Shelving.core.solver.solve_axis`, moving the boards as little
as possible from where they stood before the edit. A caller treats a
:class:`~freecad.Shelving.core.solver.LayoutSolveError` from an edit or from
laying out its result as its own kind of refusal, distinct from
:class:`EditError`.

An active constraint holds through every edit as a lock does, and the
structural edits carry the constraints over to the new tree, dropping those
whose openings or end boards they remove (:func:`carry_constraints`).

``split_region`` and ``merge_at`` are each other's exact inverse while every
constraint holds. No edit
here mutates the argument ``Unit``: untouched subtrees are shared by
reference with the result, so the argument must stay unmodified for the
result to stay valid.

Imports no Qt and no FreeCAD, so the fast suite exercises every edit
directly, the same way :mod:`freecad.Shelving.core.solver` does.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence

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
    Region,
    RunEnd,
    SpacingEnd,
    Unit,
    find_division,
    spacing_group,
)
from freecad.Shelving.core.record import keys_by_region, unique_regions_by_key
from freecad.Shelving.core.solver import (
    EPS_MM,
    FIXED_FRACTION,
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


def is_locked(item: Item) -> bool:
    """Whether ``item`` is a region with a lock; a board never is."""
    return not isinstance(item, Board) and item.lock is not None


def split_region(unit: Unit, region_id: str, axis: Axis) -> Unit:
    """``unit`` with the ``Bay`` named ``region_id`` replaced by a board on
    ``axis``, splitting it into two bays of equal size and moving nothing
    else while every constraint still holds.

    When ``region_id``'s parent ``Division`` runs along a *different* axis
    than ``axis``, the replacement is a new ``Division`` on ``axis`` holding
    ``Bay``, ``Board``, ``Bay``, carrying the split ``Bay``'s own size and
    lock in the slot it occupied; both new bays are unlocked. Otherwise
    ``region_id``'s parent already runs along ``axis``, and the two new bays
    splice directly into the parent's own ``items`` in ``region_id``'s
    place, each locked in ``Basis.CLEAR`` when the split bay was locked. A
    same-axis ``Division`` nested inside another is one that scanning cannot
    tell apart from a flat run of the same boards (bug-006).

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
    replaced_root, found = _split_in_division(unit.root, region_id, axis, board, spaces)
    if not found:
        raise EditError(region_id, "That is not part of this unit.")
    return _structural(unit, dataclasses.replace(unit, root=replaced_root))


def _split_in_division(
    division: Division,
    region_id: str,
    axis: Axis,
    board: Board,
    spaces: Mapping[str, Space],
) -> tuple[Division, bool]:
    items = division.items
    for index, item in enumerate(items):
        if isinstance(item, Board):
            continue
        if item.id == region_id:
            if not isinstance(item, Bay):
                raise EditError(region_id, "Only an open compartment can be split.")
            replacement = _split_replacement(item, division, axis, board, spaces)
            new_items = items[:index] + replacement + items[index + 1 :]
            return dataclasses.replace(division, items=new_items), True
        if isinstance(item, Division):
            new_child, found = _split_in_division(item, region_id, axis, board, spaces)
            if found:
                new_items = items[:index] + [new_child] + items[index + 1 :]
                return dataclasses.replace(division, items=new_items), True
    return division, False


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
            lock=bay.lock,
        )
        return [division]
    lock = None if bay.lock is None else Basis.CLEAR
    return [Bay(size_mm=half_mm, lock=lock), board, Bay(size_mm=half_mm, lock=lock)]


def merge_at(unit: Unit, board_id: str) -> Unit:
    """``unit`` with the ``Board`` named ``board_id`` removed and the regions
    either side of it merged into one, moving nothing else while every
    constraint still holds.

    The merged region takes the first (lower-index) neighbor's id and a size
    of the neighbors' combined size plus the removed board's extent, locked
    in ``Basis.CLEAR`` when both neighbors were locked and unlocked
    otherwise, the exact inverse of :func:`split_region`. *Unless* the merge
    leaves its enclosing ``Division`` with only that one item left: the
    ``Division`` itself is then replaced by it, taking the ``Division``'s own
    size and lock instead, which is what makes a split-then-merge round trip
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
    new parent's run in its place instead, each keeping its size and lock.

    The constraints carry over as :func:`carry_constraints` carries them,
    so one on either merged region or ending at the board is dropped, and
    an active one left unmet is solved again. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when that solve
    finds no layout.
    """
    return _structural(unit, _merged(unit, board_id))


def _merged(unit: Unit, board_id: str) -> Unit:
    """:func:`merge_at`'s tree edit alone, its constraints left as they
    were."""
    new_root, found, _collapsed = _merge_at(unit.root, board_id)
    if not found:
        raise EditError(board_id, "That is not a board of this unit.")
    return dataclasses.replace(unit, root=new_root)


def _merge_at(region: Region, board_id: str) -> tuple[Region, bool, bool]:
    """``region`` with ``board_id`` merged away, whether a board of that id
    was found anywhere in its subtree, and whether *this call*
    collapsed ``region`` itself down to one promoted item. The third element
    is never true for a collapse passed up from deeper in the tree, so the
    caller splices only a ``Division`` this merge promoted, and leaves alone
    one that was same-axis nested for some other reason (unreachable through
    scanning or this module).
    """
    if not isinstance(region, Division):
        return region, False, False
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
            both_locked = before.lock is not None and after.lock is not None
            merged: Region = dataclasses.replace(
                before,
                size_mm=before.size_mm + board_extent_mm(item) + after.size_mm,
                lock=Basis.CLEAR if both_locked else None,
            )
            merged_items = items[: index - 1] + [merged] + items[index + 2 :]
            if len(merged_items) == 1:
                collapsed = dataclasses.replace(
                    merged, size_mm=region.size_mm, lock=region.lock
                )
                return collapsed, True, True
            return dataclasses.replace(region, items=merged_items), True, False
    new_items: list[Item] = []
    changed = False
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
        changed = changed or child_found
    if changed:
        return dataclasses.replace(region, items=new_items), True, False
    return region, False, False


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
    result = dataclasses.replace(
        unit, root=_with_thickness(unit.root, targets, thickness_mm)
    )
    for axis in axes:
        result = solve_axis(result, spaces, axis, MIN_DRAG_GAP_MM)
    return result


def _with_thickness(
    region: Region, board_ids: frozenset[str], thickness_mm: float
) -> Region:
    """``region`` with every board in ``board_ids`` at ``thickness_mm``,
    copying only the paths down to them. A ``Basis.WITH_NEXT`` lock just
    before a changed board keeps its spacing, so its stored clear size takes
    the opposite change."""
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
            new_item = _with_thickness(item, board_ids, thickness_mm)
            after = region.items[index + 1] if index + 1 < len(region.items) else None
            if (
                isinstance(after, Board)
                and after.id in board_ids
                and new_item.lock is Basis.WITH_NEXT
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


def _with_region(
    region: Region,
    region_id: str,
    lock: Basis | None,
    size_mm: float | None = None,
) -> Region:
    """``region`` with the region named ``region_id`` given ``lock``, and
    ``size_mm`` when that is set, copying only the path down to it."""
    if region.id == region_id:
        if size_mm is None:
            return dataclasses.replace(region, lock=lock)
        return dataclasses.replace(region, lock=lock, size_mm=size_mm)
    if not isinstance(region, Division):
        return region
    new_items: list[Item] = []
    changed = False
    for item in region.items:
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_item = _with_region(item, region_id, lock, size_mm)
        changed = changed or new_item is not item
        new_items.append(new_item)
    return dataclasses.replace(region, items=new_items) if changed else region


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
    region are free, each moves half the change.

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
    edited = dataclasses.replace(
        unit, root=_with_region(unit.root, region_id, basis, clear_mm)
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
    its current size, moving nothing.

    Raises :class:`EditError` naming ``region_id`` when ``basis`` is
    ``Basis.WITH_NEXT`` and the next item in the region's run is not a
    board, or when ``region_id`` names the root, a board, or nothing in
    ``unit``.
    """
    parent, index = _locate_region(unit, region_id)
    _next_board(parent, index, basis)
    return dataclasses.replace(unit, root=_with_region(unit.root, region_id, basis))


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
    """``unit`` with the region named ``region_id`` locked in
    ``Basis.CLEAR`` at its current size, moving nothing. Returns ``unit``
    itself when the region is already locked. Raises :class:`EditError` for
    the root, a board, or an unknown id. The lock may make the unit's size
    along the run a reference, or duplicate other locks; neither is refused.
    """
    parent, index = _locate_region(unit, region_id)
    if is_locked(parent.items[index]):
        return unit
    return dataclasses.replace(
        unit, root=_with_region(unit.root, region_id, Basis.CLEAR)
    )


def unlock(unit: Unit, region_id: str) -> Unit:
    """``unit`` with the region named ``region_id`` unlocked, moving nothing.
    Returns ``unit`` itself when the region is already unlocked. Raises
    :class:`EditError` for the root, a board, or an unknown id."""
    parent, index = _locate_region(unit, region_id)
    if not is_locked(parent.items[index]):
        return unit
    return dataclasses.replace(unit, root=_with_region(unit.root, region_id, None))


@dataclasses.dataclass(frozen=True)
class Held:
    """What keeps a drag from moving a board, as :func:`held_by` finds it."""

    # The locked regions to unlock, low side first.
    locks: tuple[str, ...] = ()
    # The active constraints that hold the board with those locks unlocked,
    # in the unit's order. No unlock frees a board one holds.
    constraints: tuple[ConstraintId, ...] = ()

    @property
    def free(self) -> bool:
        """Whether a drag may move the board as it is."""
        return not self.locks and not self.constraints


def held_by(unit: Unit, board_id: str) -> Held | None:
    """What holds the board ``board_id`` against a drag.

    :attr:`Held.free` when a drag may move the board: with the unit's outer
    faces held, the locks and active constraints leave its position free,
    whatever the openings' minimum widths allow. Otherwise the fewest locks
    whose unlocking frees it, or that unlocking leaves to the constraints:
    the locked region nearest the board on each blocked side, low side
    first, and further ones only when those leave it held, as across nested
    runs. When constraints still hold it with those unlocked, they are
    named and the board stays held whatever is unlocked. ``None`` when
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
    order: dict[str, int] = {
        constraint.id: index for index, constraint in enumerate(unit.constraints)
    }
    low_side: list[str] = []
    high_side: list[str] = []
    while True:
        fixing = fixing_locks(unit, spaces, board_id, axis, low_side + high_side)
        if fixing is None:
            return Held(locks=tuple(low_side + high_side))
        if not fixing:
            return None
        regions = [r for r in fixing if r not in order]
        if not regions:
            return Held(
                locks=tuple(low_side + high_side),
                constraints=tuple(
                    ConstraintId(c) for c in sorted(fixing, key=order.__getitem__)
                ),
            )
        below = [r for r in regions if spaces[r].origin_mm(axis_index) < low_face_mm]
        above = [r for r in regions if r not in below]
        if below:
            low_side.append(
                max(
                    below,
                    key=lambda r: (
                        spaces[r].origin_mm(axis_index)
                        + spaces[r].extent_mm(axis_index)
                    ),
                )
            )
        if above:
            high_side.append(
                min(
                    above,
                    key=lambda r: spaces[r].origin_mm(axis_index) - high_face_mm,
                )
            )


def require_movable(unit: Unit, board_id: str) -> None:
    """Return when a drag may move the board ``board_id``. Raises
    :class:`EditError` naming ``board_id`` when :func:`held_by` gives
    ``None`` or names constraints, and naming the nearest holding region
    when it names only locks."""
    held = held_by(unit, board_id)
    if held is None:
        raise EditError(board_id, "This board has no opening on each side to move.")
    if held.constraints:
        raise EditError(board_id, "A constraint holds this board in place.")
    if held.locks:
        raise EditError(held.locks[0], "A locked opening holds this board in place.")


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

    # What the region's size measures: its lock's basis, or Basis.CLEAR for
    # an unlocked region, which is what a typed size would lock it in.
    basis: Basis
    # Whether the region is locked.
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
    return Measurement(
        basis=region.lock or Basis.CLEAR,
        fixed=region.lock is not None,
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
    """``after``, an edit of ``before``'s tree, with ``before``'s
    constraints that still hold their regions renamed to them and the rest
    dropped.

    An ``Equal`` is dropped when either opening's bounding boards changed:
    deleting a board beside it merges it away, and a board added along its
    run splits it. A board added across its run keeps it, since its slot
    and size are unchanged. An ``EvenSpacing`` is kept while its ends are
    still in one run along its axis, in order, whatever happens between
    them. Keeps each constraint's order, id and active flag.
    """
    before_keys = keys_by_region(before)
    after_keys = keys_by_region(after)
    after_by_key = unique_regions_by_key(after)
    carried: list[Constraint] = []
    for constraint in before.constraints:
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
    make N-1 constraints chained in that order, appended after its others
    and solved by moving the boards as little as possible.

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
    return solve_axis(edited, solve(unit), axes.pop(), MIN_DRAG_GAP_MM)


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
    appended after its other constraints and solved by moving the boards as
    little as possible.

    ``node_ids`` names two boards of one run, which become its ends, or two
    or more openings of one run: then its group runs from the first opening
    to the last in run order, and each end is the board bounding it there
    or the run's own end. Raises :class:`EditError` for any other
    selection, for an opening bounded there by another opening, and when
    fewer than two openings lie between the ends. Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` naming the
    locks and constraints that rule it out.
    """
    distinct = list(dict.fromkeys(node_ids))
    what = (
        "Select two boards of one row or column, or two or more openings of "
        "one row or column, to space evenly."
    )
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
                "An opening at an end of this selection has another opening "
                "beside it, with no board between them to space from.",
            )
    else:
        raise EditError(distinct[0], what)
    spacing = EvenSpacing(run_id=run.id, start=start, end=end)
    edited = dataclasses.replace(unit, constraints=(*unit.constraints, spacing))
    group = spacing_group(edited, spacing)
    if group is None or len(group) < 2:
        raise EditError(
            distinct[0],
            "Even spacing needs two or more openings between its ends.",
        )
    return solve_axis(edited, solve(unit), run.axis, MIN_DRAG_GAP_MM)


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
