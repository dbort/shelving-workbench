"""Tree-rewriting edits for the elevation editor: split a bay, merge a board,
size a region, change what a size measures, lock or unlock a region, drag a
board.

A region with a ``Fixed`` rule is locked: it keeps its size. One with a
``Weighted`` or ``Fill`` rule is unlocked and shares what is left of its
run.

``split_region`` and ``merge_at`` are each other's exact inverse. No edit
here mutates the argument ``Unit``: untouched subtrees are shared by
reference with the result, so the argument must stay unmodified for the
result to stay valid. No edit re-solves its own result; a caller does that
and treats a :class:`~freecad.Shelving.core.solver.LayoutSolveError` from it
as its own kind of refusal, distinct from :class:`EditError`. An edit that
preserves geometry solves the argument ``unit`` once to read every node's
pre-edit size: it needs the region's *actual* solved extent, not only its
rule object, since a rule can be ``Basis.WITH_NEXT`` or weighted against
siblings.

Imports no Qt and no FreeCAD, so the fast suite exercises every edit
directly, the same way :mod:`freecad.Shelving.core.solver` does.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

from freecad.Shelving.core.geometry import AxisIndex, Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
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
    Weighted,
)
from freecad.Shelving.core.solver import solve
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
    """Whether ``item`` is a region with a ``Fixed`` rule; a board never is."""
    return not isinstance(item, Board) and isinstance(item.rule, Fixed)


def _refuse_last_unlocked(parent: Division, index: int) -> None:
    """Raise :class:`EditError` naming ``parent.items[index]`` when locking it
    would leave its run no unlocked region. A region already locked passes:
    a run an older record left with none keeps what it was allowed."""
    region = parent.items[index]
    if isinstance(region, Board) or is_locked(region):
        return
    if not any(
        not isinstance(item, Board) and not is_locked(item)
        for other, item in enumerate(parent.items)
        if other != index
    ):
        raise EditError(region.id, _LAST_UNLOCKED)


def _axis_index(axis: Axis) -> AxisIndex:
    match axis:
        case Axis.X:
            return 0
        case Axis.Y:
            return 1
        case Axis.Z:
            return 2


def _driven_weight(rule: SizeRule | None) -> float | None:
    """``rule``'s weight in ``distribute()``'s slack sharing, or ``None`` when
    ``rule`` is ``Fixed`` or absent (a board whose own ``rule`` is unset takes
    its thickness, not a share of slack, so it never anchors a ratio)."""
    if isinstance(rule, Weighted):
        return rule.weight
    if isinstance(rule, Fill):
        return 1.0
    return None


def _other_driven_anchor(
    items: Sequence[Item],
    exclude_indices: Collection[int],
    spaces: Mapping[str, Space],
    axis_index: AxisIndex,
) -> tuple[float, float] | None:
    """The ``(weight, solved size_mm)`` of the first driven (``Weighted`` or
    ``Fill``) item in ``items`` outside ``exclude_indices``, or ``None`` when
    none exists.

    Every driven item sharing one ``distribute()`` call has the same
    size-per-weight ratio, so any one of them anchors the
    computation that keeps every *other* driven sibling at its pre-edit
    size; ``None`` means the edited pair was the run's only driven item, so
    nothing else needs preserving and the caller may use ``Fill``.
    """
    for index, item in enumerate(items):
        if index in exclude_indices:
            continue
        weight = _driven_weight(item.rule)
        if weight is None:
            continue
        return weight, spaces[item.id].extent_mm(axis_index)
    return None


def split_region(unit: Unit, region_id: str, axis: Axis) -> Unit:
    """``unit`` with the ``Bay`` named ``region_id`` replaced by a board on
    ``axis``, splitting it into two bays.

    When ``region_id``'s parent ``Division`` runs along a *different* axis
    than ``axis``, the replacement is a new ``Division`` on ``axis`` holding
    ``Bay``, ``Board``, ``Bay``, carrying the split ``Bay``'s own rule so
    the slot it occupied in its parent still claims the same share of
    space; a fresh run has no other region to preserve, so both new bays
    are always ``Fill``. Otherwise ``region_id``'s parent already runs
    along ``axis``, and the two new bays splice directly into the parent's
    own ``items`` in ``region_id``'s place. A same-axis ``Division`` nested
    inside another is one that scanning cannot tell apart from a flat run of
    the same boards, so it would re-solve to different sizes (bug-006). The
    spliced bays get rules chosen so ``solve`` reproduces every other
    region's pre-edit size in that run: a ``Fixed`` bay splits into
    two ``Fixed`` halves of ``(size - thickness) / 2``; a ``Weighted`` or
    ``Fill`` bay splits into two ``Weighted`` halves solved against another
    driven sibling in the run, or two ``Fill`` halves when no such sibling
    exists.

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
            replacement = _split_replacement(item, division, index, axis, board, spaces)
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
    index: int,
    axis: Axis,
    board: Board,
    spaces: Mapping[str, Space],
) -> list[Item]:
    """The item(s) replacing ``bay`` at ``parent.items[index]``: one wrapping
    ``Division`` when ``axis`` differs from ``parent.axis`` (a fresh run, so
    its two ``Bay`` children are always ``Fill``), or the flat splice
    ``[Bay, Board, Bay]`` in the bay's own place when it matches, with
    geometry-preserving rules from :func:`_split_halves_rules`.
    """
    if parent.axis != axis:
        division = Division(
            axis=axis,
            items=[Bay(), board, Bay()],
            rule=bay.rule,
        )
        return [division]
    rule1, rule2 = _split_halves_rules(
        bay, parent.items, index, axis, board.thickness_mm, spaces
    )
    return [Bay(rule=rule1), board, Bay(rule=rule2)]


def _split_halves_rules(
    bay: Bay,
    items: Sequence[Item],
    index: int,
    axis: Axis,
    thickness_mm: float,
    spaces: Mapping[str, Space],
) -> tuple[SizeRule, SizeRule]:
    axis_index = _axis_index(axis)
    size_before_mm = spaces[bay.id].extent_mm(axis_index)
    half_mm = (size_before_mm - thickness_mm) / 2
    if half_mm <= 0:
        raise EditError(
            bay.id,
            f"This {size_before_mm:.1f} mm opening is too small to hold a "
            f"{thickness_mm:.1f} mm board with room on both sides.",
        )
    if isinstance(bay.rule, Fixed):
        fixed_rule: SizeRule = Fixed(size_mm=half_mm, basis=Basis.CLEAR)
        return fixed_rule, fixed_rule
    anchor = _other_driven_anchor(items, {index}, spaces, axis_index)
    if anchor is None:
        return Fill(), Fill()
    anchor_weight, anchor_size_mm = anchor
    weighted_rule: SizeRule = Weighted(weight=half_mm * anchor_weight / anchor_size_mm)
    return weighted_rule, weighted_rule


def merge_at(unit: Unit, board_id: str) -> Unit:
    """``unit`` with the ``Board`` named ``board_id`` removed and the regions
    either side of it merged into one.

    The merged region takes the first (lower-index) neighbor's id, and a
    rule chosen so ``solve`` reproduces every other region's pre-edit size in
    the run: the neighbors' combined size plus the removed board's
    thickness, ``Fixed`` when both neighbors were ``Fixed``, otherwise a
    ``Weighted`` weight solved against another driven sibling in the run (or
    ``Fill`` when no such sibling exists), the exact inverse of
    :func:`split_region`'s own rule choice. *Unless* the merge leaves its
    enclosing ``Division`` with only that one item left: the ``Division``
    itself is then replaced by it, taking the ``Division``'s own rule
    instead, which is what makes a split-then-merge round trip return the
    tree to its original shape rather than leaving a degenerate one-item
    ``Division`` behind. The second neighbor is discarded whole: when it is
    itself a ``Division``, every board and region in its subtree disappears
    with it, silently, rather than being refused, since the letter of
    "regions either side merged into one" does not distinguish a leaf region
    from a subtree. Raises :class:`EditError` naming ``board_id`` when it
    names no board in ``unit``, or a board whose neighbor on either side is
    missing (the end of a run) or is itself a ``Board`` rather than a
    region.

    A collapse can promote a surviving ``Division`` (``before``'s own
    subtree, carried up whole) to sit where the collapsing ``Division``
    used to, one level up in the tree. When that promoted ``Division``'s
    axis matches its *new* parent's axis, leaving it in place would produce
    bug-006's same-axis nesting through merge, so its items splice into the
    new parent's run in its place instead, with
    ``Fixed`` items keeping the size they already had. A driven item gets a
    fresh geometry-preserving weight against the new run's other driven
    siblings when the new run has one, the same as :func:`split_region`'s
    splice case; when it has none, every driven item spliced in keeps its
    own rule unchanged, since it and its formerly-nested siblings were
    already the promoted ``Division``'s only claimants on the slack it
    itself used to claim (see :func:`_splice_collapsed_child`).
    """
    spaces = solve(unit)
    new_root, found, _collapsed = _merge_at(unit.root, board_id, spaces)
    if not found:
        raise EditError(board_id, "That is not a board of this unit.")
    return dataclasses.replace(unit, root=new_root)


def _merge_at(
    region: Region, board_id: str, spaces: Mapping[str, Space]
) -> tuple[Region, bool, bool]:
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
    axis_index = _axis_index(region.axis)
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
            merged_rule = _merged_rule(
                before, after, item, items, index, axis_index, spaces
            )
            merged: Region = dataclasses.replace(before, rule=merged_rule)
            merged_items = items[: index - 1] + [merged] + items[index + 2 :]
            if len(merged_items) == 1:
                collapsed = dataclasses.replace(merged, rule=region.rule)
                return collapsed, True, True
            return dataclasses.replace(region, items=merged_items), True, False
    new_items: list[Item] = []
    changed = False
    for index, item in enumerate(items):
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_child, child_found, child_collapsed = _merge_at(item, board_id, spaces)
        if (
            child_collapsed
            and isinstance(new_child, Division)
            and new_child.axis == region.axis
        ):
            new_items.extend(
                _splice_collapsed_child(items, index, axis_index, new_child, spaces)
            )
        else:
            new_items.append(new_child)
        changed = changed or child_found
    if changed:
        return dataclasses.replace(region, items=new_items), True, False
    return region, False, False


def _splice_collapsed_child(
    items: Sequence[Item],
    index: int,
    axis_index: AxisIndex,
    new_child: Division,
    spaces: Mapping[str, Space],
) -> list[Item]:
    """``new_child``'s own items, each with a rule under which ``solve`` gives
    it its pre-merge size once it sits directly in ``items`` (``new_child``'s
    new parent's run). ``Fixed`` items and boards are returned unchanged.
    """
    anchor = _other_driven_anchor(items, {index}, spaces, axis_index)
    if anchor is None:
        # With no other driven sibling, new_child was the only driven claimant
        # on this run's slack, so its children inherit exactly that slack and
        # their existing weight ratios already divide it the same way.
        # Resetting them to Fill would equalize unequal children and move
        # boards (bug-006).
        return list(new_child.items)
    anchor_weight, anchor_size_mm = anchor
    spliced: list[Item] = []
    for child_item in new_child.items:
        if isinstance(child_item, Board) or _driven_weight(child_item.rule) is None:
            spliced.append(child_item)
            continue
        size_mm = spaces[child_item.id].extent_mm(axis_index)
        new_rule: SizeRule = Weighted(weight=size_mm * anchor_weight / anchor_size_mm)
        spliced.append(dataclasses.replace(child_item, rule=new_rule))
    return spliced


def _merged_rule(
    before: Region,
    after: Region,
    board: Board,
    items: Sequence[Item],
    board_index: int,
    axis_index: AxisIndex,
    spaces: Mapping[str, Space],
) -> SizeRule:
    size1_mm = spaces[before.id].extent_mm(axis_index)
    size2_mm = spaces[after.id].extent_mm(axis_index)
    thickness_mm = spaces[board.id].extent_mm(axis_index)
    target_mm = size1_mm + thickness_mm + size2_mm
    if isinstance(before.rule, Fixed) and isinstance(after.rule, Fixed):
        return Fixed(size_mm=target_mm, basis=Basis.CLEAR)
    exclude = {board_index - 1, board_index, board_index + 1}
    anchor = _other_driven_anchor(items, exclude, spaces, axis_index)
    if anchor is None:
        return Fill()
    anchor_weight, anchor_size_mm = anchor
    return Weighted(weight=target_mm * anchor_weight / anchor_size_mm)


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
    extent is the unit's own size, never a rule), a board, or absent."""
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
    ``Basis.WITH_NEXT`` when the next item is missing or is not a board,
    which the solver could not resolve."""
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


def _with_rule(region: Region, region_id: str, rule: SizeRule) -> Region:
    """``region`` with the rule of the region named ``region_id`` replaced,
    copying only the path down to it."""
    if region.id == region_id:
        return dataclasses.replace(region, rule=rule)
    if not isinstance(region, Division):
        return region
    new_items: list[Item] = []
    changed = False
    for item in region.items:
        if isinstance(item, Board):
            new_items.append(item)
            continue
        new_item = _with_rule(item, region_id, rule)
        changed = changed or new_item is not item
        new_items.append(new_item)
    return dataclasses.replace(region, items=new_items) if changed else region


def set_unit_size(unit: Unit, size_mm: Vec3) -> Unit:
    """``unit`` with outer size ``size_mm`` and its tree unchanged; the solve
    decides where the change goes. Raises :class:`EditError` naming
    ``unit.id`` when any axis of ``size_mm`` is not positive."""
    for axis, value_mm in zip(
        Axis, (size_mm.x_mm, size_mm.y_mm, size_mm.z_mm), strict=True
    ):
        if value_mm <= 0:
            raise EditError(
                unit.id,
                f"A unit's size along {axis.value} must be more than zero; "
                f"got {value_mm:.1f} mm.",
            )
    return dataclasses.replace(unit, size_mm=size_mm)


def set_size(unit: Unit, region_id: str, size_mm: float, basis: Basis) -> Unit:
    """``unit`` with the region named ``region_id`` given the rule
    ``Fixed(size_mm, basis)``; every other rule is left as it was, so driven
    siblings take up the difference when the result is solved.

    Raises :class:`EditError` naming ``region_id`` when ``size_mm`` is not
    positive, when ``basis`` is ``Basis.WITH_NEXT`` and the next item in the
    region's run is not a board, when ``region_id`` names the root, a
    board, or nothing in ``unit``, or when it names its run's last unlocked
    region.
    """
    parent, index = _locate_region(unit, region_id)
    _refuse_last_unlocked(parent, index)
    if size_mm <= 0:
        raise EditError(
            region_id, f"A size must be more than zero; got {size_mm:.1f} mm."
        )
    _next_board(parent, index, basis)
    rule = Fixed(size_mm=size_mm, basis=basis)
    return dataclasses.replace(unit, root=_with_rule(unit.root, region_id, rule))


def size_in_basis_mm(
    parent: Division,
    index: int,
    clear_mm: float,
    basis: Basis,
) -> float:
    """``clear_mm`` restated in ``basis`` for ``parent.items[index]``.

    A spacing adds the next board's ``thickness_mm`` rather than its solved
    extent, because that is what the solver subtracts when it resolves
    ``Basis.WITH_NEXT``; the two differ for a board carrying its own rule.
    Raises :class:`EditError` naming the region for ``Basis.WITH_NEXT``
    when no board follows it.
    """
    board = _next_board(parent, index, basis)
    if board is None:
        return clear_mm
    return clear_mm + board.thickness_mm


def set_basis(unit: Unit, region_id: str, basis: Basis) -> Unit:
    """``unit`` with the region named ``region_id`` measured in ``basis``,
    its stored size recomputed so ``solve`` places every node exactly where
    it did before.

    The region's rule becomes ``Fixed`` whatever it was: a ``Weighted`` or
    ``Fill`` region is fixed at its current solved size, and from then on no
    longer shares slack. Raises :class:`EditError` on the same terms as
    :func:`set_size`; raises
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` when ``unit``
    itself does not solve.
    """
    parent, index = _locate_region(unit, region_id)
    spaces = solve(unit)
    clear_mm = spaces[region_id].extent_mm(_axis_index(parent.axis))
    size_mm = size_in_basis_mm(parent, index, clear_mm, basis)
    return set_size(unit, region_id, size_mm, basis)


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
    """``unit`` with the region named ``region_id`` fixed at its solved clear
    size, so ``solve`` places every node where it did. Returns ``unit``
    itself when the region is already locked. Raises :class:`EditError` on
    :func:`set_size`'s terms, including for its run's last unlocked region.
    """
    parent, index = _locate_region(unit, region_id)
    if is_locked(parent.items[index]):
        return unit
    clear_mm = solve(unit)[region_id].extent_mm(_axis_index(parent.axis))
    return set_size(unit, region_id, clear_mm, Basis.CLEAR)


def unlock(unit: Unit, region_id: str) -> Unit:
    """``unit`` with the region named ``region_id`` sharing what is left of
    its run at the weight that holds its solved size, so ``solve`` places
    every node where it did; ``Fill`` when no other region of the run is
    unlocked. Returns ``unit`` itself when the region is already unlocked.
    Raises :class:`EditError` on :func:`set_size`'s terms for the root, a
    board, or an unknown id."""
    parent, index = _locate_region(unit, region_id)
    if not is_locked(parent.items[index]):
        return unit
    axis_index = _axis_index(parent.axis)
    spaces = solve(unit)
    anchor = _other_driven_anchor(parent.items, {index}, spaces, axis_index)
    rule: SizeRule = Fill()
    if anchor is not None:
        anchor_weight, anchor_size_mm = anchor
        size_mm = spaces[region_id].extent_mm(axis_index)
        rule = Weighted(weight=size_mm * anchor_weight / anchor_size_mm)
    return dataclasses.replace(unit, root=_with_rule(unit.root, region_id, rule))


# The narrowest a drag leaves either region it resizes. Undo, Redo and
# reopening each rescan the boards, and a rescan drops a region whose faces
# sit within the scan's clearance plus its snap, so the floor stays clear of
# both.
MIN_DRAG_GAP_MM = 5.0


@dataclasses.dataclass(frozen=True)
class _Side:
    """What lies past a board toward one end of its run."""

    # The index of the first unlocked region, the one a drag resizes; None
    # when only boards and locked regions reach the end of the run.
    free_index: int | None
    # The locked region nearest the board on this side, if any.
    nearest_locked: str | None


def _side(parent: Division, index: int, step: Literal[-1, 1]) -> _Side:
    nearest_locked: str | None = None
    other = index + step
    while 0 <= other < len(parent.items):
        item = parent.items[other]
        if not isinstance(item, Board):
            if not is_locked(item):
                return _Side(other, nearest_locked)
            if nearest_locked is None:
                nearest_locked = item.id
        other += step
    return _Side(None, nearest_locked)


def _sides(unit: Unit, board_id: str) -> tuple[Division, _Side, _Side] | None:
    """The run holding the board ``board_id`` and its low and high sides, or
    ``None`` when ``board_id`` names no board."""
    found = _locate(unit.root, board_id)
    if found is None or not isinstance(found[0].items[found[1]], Board):
        return None
    parent, index = found
    return parent, _side(parent, index, -1), _side(parent, index, 1)


def held_by(unit: Unit, board_id: str) -> tuple[str, ...] | None:
    """The locked regions to unlock so a drag may move the board
    ``board_id``: on each side where only boards and locked regions lie
    between it and the end of its run, the locked region nearest the board,
    low side first. Empty when a drag may move the board; ``None`` when
    ``board_id`` names no board, or a side holds no region at all, as
    beside a carcass board, so no unlock would free it."""
    found = _sides(unit, board_id)
    if found is None:
        return None
    _parent, low, high = found
    held: list[str] = []
    for side in (low, high):
        if side.free_index is not None:
            continue
        if side.nearest_locked is None:
            return None
        held.append(side.nearest_locked)
    return tuple(held)


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
    or as near to it as the run allows.

    Every board joined to it through locked regions moves by the same
    distance. Only the first unlocked region on each side changes size, and
    both stay unlocked, reweighted so every other region of the run keeps
    its solved size. Neither resized region shrinks below
    :data:`MIN_DRAG_GAP_MM`, or below its current size when that is already
    smaller: a ``low_face_mm`` past that point stops the board there, as a
    scroll bar's thumb stops at the end of its track. Raises
    :class:`EditError` naming ``board_id`` when :func:`held_by` gives
    ``None``, and naming the nearest holding region when it gives a
    non-empty tuple.
    """
    require_movable(unit, board_id)
    found = _sides(unit, board_id)
    assert found is not None
    parent, low, high = found
    # held_by is empty, so each side has an unlocked region.
    assert low.free_index is not None and high.free_index is not None
    axis_index = _axis_index(parent.axis)
    spaces = solve(unit)
    before = parent.items[low.free_index]
    after = parent.items[high.free_index]
    old_before_mm = spaces[before.id].extent_mm(axis_index)
    old_after_mm = spaces[after.id].extent_mm(axis_index)
    # A floor at the current size keeps a region already narrower than the
    # minimum from pushing the board away the moment a drag starts.
    lowest_shift_mm = min(MIN_DRAG_GAP_MM, old_before_mm) - old_before_mm
    highest_shift_mm = old_after_mm - min(MIN_DRAG_GAP_MM, old_after_mm)
    shift_mm = min(
        max(low_face_mm - spaces[board_id].origin_mm(axis_index), lowest_shift_mm),
        highest_shift_mm,
    )
    before_mm = old_before_mm + shift_mm
    after_mm = old_after_mm - shift_mm
    # Both resized regions are unlocked, so the run has an anchor, and the
    # two new weights keep the run's total weight.
    anchor = _other_driven_anchor(parent.items, (), spaces, axis_index)
    assert anchor is not None
    anchor_weight, anchor_size_mm = anchor
    root = unit.root
    for region, size_mm in ((before, before_mm), (after, after_mm)):
        rule = Weighted(weight=size_mm * anchor_weight / anchor_size_mm)
        root = _with_rule(root, region.id, rule)
    return dataclasses.replace(unit, root=root)


@dataclasses.dataclass(frozen=True)
class Measurement:
    """A region's size as the editor shows it."""

    # What the region's size measures: its Fixed rule's basis, or
    # Basis.CLEAR for a Weighted or Fill region, which is what a typed size
    # would fix it in.
    basis: Basis
    # Whether the region's rule is Fixed; False means it shares slack.
    fixed: bool
    clear_mm: float
    # clear_mm plus the next board's thickness_mm, the number a Basis.WITH_NEXT
    # rule stores; None when no board follows the region.
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
    clear_mm = spaces[region_id].extent_mm(_axis_index(parent.axis))
    spacing_mm: float | None = None
    if index + 1 < len(parent.items) and isinstance(parent.items[index + 1], Board):
        spacing_mm = size_in_basis_mm(parent, index, clear_mm, Basis.WITH_NEXT)
    fixed = isinstance(region.rule, Fixed)
    basis = region.rule.basis if isinstance(region.rule, Fixed) else Basis.CLEAR
    return Measurement(
        basis=basis, fixed=fixed, clear_mm=clear_mm, spacing_mm=spacing_mm
    )
