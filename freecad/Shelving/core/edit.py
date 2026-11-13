"""Tree-rewriting edits for the elevation editor: split a bay, merge a board,
remove several boards, size a region, change what a size measures, lock or
unlock a region, drag a board, change boards' thickness.

A region with a ``lock`` holds its size through edits; an unlocked one
takes whatever size the boards around it leave. Every edit returns a unit
whose stored sizes are already solved: one that moves boards solves them with
:func:`~freecad.Shelving.core.solver.solve_axis`, moving the boards as little
as possible from where they stood before the edit. A caller treats a
:class:`~freecad.Shelving.core.solver.LayoutSolveError` from an edit or from
laying out its result as its own kind of refusal, distinct from
:class:`EditError`.

``split_region`` and ``merge_at`` are each other's exact inverse. No edit
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
    Division,
    Item,
    Region,
    Unit,
)
from freecad.Shelving.core.solver import (
    EPS_MM,
    FIXED_FRACTION,
    board_extent_mm,
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


_LAST_UNLOCKED = (
    "One opening in each row stays unlocked, to take up changes to the unit's size."
)


def is_locked(item: Item) -> bool:
    """Whether ``item`` is a region with a lock; a board never is."""
    return not isinstance(item, Board) and item.lock is not None


def _refuse_last_unlocked(parent: Division, index: int) -> None:
    """Raise :class:`EditError` naming ``parent.items[index]`` when locking it
    would leave its run no unlocked region. A region already locked passes:
    a run a scan left with none keeps what it was allowed."""
    region = parent.items[index]
    if isinstance(region, Board) or is_locked(region):
        return
    if not any(
        not isinstance(item, Board) and not is_locked(item)
        for other, item in enumerate(parent.items)
        if other != index
    ):
        raise EditError(region.id, _LAST_UNLOCKED)


def split_region(unit: Unit, region_id: str, axis: Axis) -> Unit:
    """``unit`` with the ``Bay`` named ``region_id`` replaced by a board on
    ``axis``, splitting it into two bays of equal size and moving nothing
    else.

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
    return dataclasses.replace(unit, root=replaced_root)


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
    either side of it merged into one, moving nothing else.

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
    """
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
    ``unit``.
    """
    present = _board_ids(unit.root)
    result = unit
    for board_id in board_ids:
        if board_id in present and board_id not in _board_ids(result.root):
            continue
        result = merge_at(result, board_id)
    return result


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
    it was, unless locks already determine its size along an axis, in which
    case asking for that size changes nothing there.

    Inside, the boards move as little as possible: the openings beside the
    outer faces that move take up the change, and push the boards beyond
    them once they reach :data:`MIN_DRAG_GAP_MM`. Raises :class:`EditError`
    naming ``unit.id`` when any axis of ``size_mm`` is not positive, and a
    ``"conflict"`` :class:`~freecad.Shelving.core.solver.LayoutSolveError`
    when the locks and that minimum leave no room for the size.
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
    run is not a board; when ``region_id`` names the root, a board, or
    nothing in ``unit``; or when it names its run's last unlocked region.
    Raises a ``"conflict"``
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when the other
    locks and the minimum leave no room for the size.
    """
    parent, index = _locate_region(unit, region_id)
    _refuse_last_unlocked(parent, index)
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
    board, when ``region_id`` names the root, a board, or nothing in
    ``unit``, or when it names its run's last unlocked region.
    """
    parent, index = _locate_region(unit, region_id)
    _refuse_last_unlocked(parent, index)
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
    the root, a board, an unknown id, or its run's last unlocked region.
    """
    parent, index = _locate_region(unit, region_id)
    if is_locked(parent.items[index]):
        return unit
    _refuse_last_unlocked(parent, index)
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


def held_by(unit: Unit, board_id: str) -> tuple[str, ...] | None:
    """The locked regions to unlock so a drag may move the board
    ``board_id``.

    Empty when a drag may move the board: with the unit's outer faces held,
    the locks leave its position free, whatever the openings' minimum
    widths allow. Otherwise the fewest locks whose unlocking frees it: the
    locked region nearest the board on each blocked side, low side first,
    and further ones only when those leave it held, as across nested runs.
    ``None`` when ``board_id`` names no board, or no unlock frees it, as for
    a carcass board.
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
    low_side: list[str] = []
    high_side: list[str] = []
    while True:
        fixing = fixing_locks(unit, spaces, board_id, axis, low_side + high_side)
        if fixing is None:
            return tuple(low_side + high_side)
        if not fixing:
            return None
        below = [r for r in fixing if spaces[r].origin_mm(axis_index) < low_face_mm]
        above = [r for r in fixing if r not in below]
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
    ``None``, and naming the nearest holding region when it gives a
    non-empty tuple."""
    held = held_by(unit, board_id)
    if held is None:
        raise EditError(board_id, "This board has no opening on each side to move.")
    if held:
        raise EditError(held[0], "A locked opening holds this board in place.")


def move_board(unit: Unit, board_id: str, low_face_mm: float) -> Unit:
    """``unit`` with the board named ``board_id`` dragged so its low face
    along its run's axis sits at ``low_face_mm`` (a unit-frame coordinate),
    or as near to it as the constraints allow.

    The unit's outer faces hold and every lock keeps its size, so boards
    joined to the dragged one through locked regions move with it. Every
    other board moves as little as it can: an opening shrinks until it
    reaches :data:`MIN_DRAG_GAP_MM`, or its current size when that is
    already smaller, and then pushes the boards ahead of it, in nested runs
    too. Nothing is locked or unlocked. Raises :class:`EditError` naming
    ``board_id`` when :func:`held_by` gives ``None``, and naming the nearest
    holding region when it gives a non-empty tuple.
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
