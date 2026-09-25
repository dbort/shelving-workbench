"""Tree-rewriting edits for the elevation editor: split a bay, merge a board.

``split_region`` and ``merge_at`` are each other's exact inverse. Both take
a :class:`~freecad.Shelving.core.layout.Unit` and a
:class:`~freecad.Shelving.core.materials.Catalog`, and return a new
``Unit``, never mutating the argument: every rebuilt node is a fresh
dataclass, and every untouched subtree is reused by reference rather than
copied, so the argument's own objects are never written to. Neither
function re-solves its own result; a caller does that and is responsible
for treating a
:class:`~freecad.Shelving.core.solver.LayoutSolveError` from that as its
own kind of refusal, distinct from :class:`EditError`. Both call
:func:`~freecad.Shelving.core.solver.solve` once, on the argument ``unit``,
to read every node's pre-edit size: geometry-preserving rules (see
``split_region`` and ``merge_at``) need the *actual* solved extent of the
region being edited, not merely its own rule object, since a rule can be
``Basis.WITH_NEXT`` or itself weighted against siblings that have since
moved.

Imports no Qt and no FreeCAD, so the fast suite exercises every edit
directly, the same way :mod:`freecad.Shelving.core.solver` does.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection, Mapping, Sequence

from freecad.Shelving.core.geometry import AxisIndex, Space
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
from freecad.Shelving.core.materials import Catalog, MaterialId
from freecad.Shelving.core.solver import solve


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
    size-per-weight ratio, so any single one of them anchors the
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


def split_region(
    unit: Unit,
    region_id: str,
    axis: Axis,
    catalog: Catalog,
    material: MaterialId | None = None,
) -> Unit:
    """``unit`` with the ``Bay`` named ``region_id`` replaced by a board on
    ``axis``, splitting it into two bays.

    When ``region_id``'s parent ``Division`` already runs along ``axis``
    (or ``region_id`` is the tree's own root), the replacement is a new
    ``Division`` on ``axis`` holding ``Bay``, ``Board``, ``Bay``, carrying
    the split ``Bay``'s own rule so the slot it occupied in its parent still
    claims the same share of space; a fresh run has no other region to
    preserve, so both new bays are always ``Fill``. Otherwise ``region_id``'s
    parent already runs along ``axis``: rather than nest a same-axis
    ``Division`` inside another, which scanning cannot tell apart from a
    flat run of the same boards and would then re-solve to different sizes
    (bug-006), the two new bays splice directly into the parent's own
    ``items`` in ``region_id``'s place, with rules chosen so ``solve``
    reproduces every other region's pre-edit size in that run: a ``Fixed``
    bay splits into two ``Fixed`` halves of ``(size - thickness) / 2``; a
    ``Weighted`` or ``Fill`` bay splits into two ``Weighted`` halves solved
    against another driven sibling in the run, or two ``Fill`` halves when
    no such sibling exists.

    ``material`` is the new board's material, ``None`` meaning it inherits
    ``unit.default_material`` the same as any other board. Raises
    :class:`EditError` naming ``region_id`` when it names a ``Void``, a
    ``Division``, no region in ``unit`` at all, or a ``Bay`` too small to
    hold the new board and still leave two positive-sized halves.
    """
    if unit.root.id == region_id:
        if not isinstance(unit.root, Bay):
            kind = type(unit.root).__name__
            raise EditError(
                region_id, f"cannot split {kind} {region_id!r}: only a Bay can be split"
            )
        new_root: Region = Division(
            axis=axis,
            items=[Bay(), Board(material=material), Bay()],
            rule=unit.root.rule,
        )
        return dataclasses.replace(unit, root=new_root)
    if not isinstance(unit.root, Division):
        raise EditError(region_id, f"no region with id {region_id!r}")
    spaces = solve(unit, catalog)
    thickness_mm = catalog[material or unit.default_material].thickness_mm
    replaced_root, found = _split_in_division(
        unit.root, region_id, axis, material, thickness_mm, spaces
    )
    if not found:
        raise EditError(region_id, f"no region with id {region_id!r}")
    return dataclasses.replace(unit, root=replaced_root)


def _split_in_division(
    division: Division,
    region_id: str,
    axis: Axis,
    material: MaterialId | None,
    thickness_mm: float,
    spaces: Mapping[str, Space],
) -> tuple[Division, bool]:
    items = division.items
    for index, item in enumerate(items):
        if isinstance(item, Board):
            continue
        if item.id == region_id:
            if not isinstance(item, Bay):
                kind = type(item).__name__
                raise EditError(
                    region_id,
                    f"cannot split {kind} {region_id!r}: only a Bay can be split",
                )
            replacement = _split_replacement(
                item, division, index, axis, material, thickness_mm, spaces
            )
            new_items = items[:index] + replacement + items[index + 1 :]
            return dataclasses.replace(division, items=new_items), True
        if isinstance(item, Division):
            new_child, found = _split_in_division(
                item, region_id, axis, material, thickness_mm, spaces
            )
            if found:
                new_items = items[:index] + [new_child] + items[index + 1 :]
                return dataclasses.replace(division, items=new_items), True
    return division, False


def _split_replacement(
    bay: Bay,
    parent: Division,
    index: int,
    axis: Axis,
    material: MaterialId | None,
    thickness_mm: float,
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
            items=[Bay(), Board(material=material), Bay()],
            rule=bay.rule,
        )
        return [division]
    rule1, rule2 = _split_halves_rules(
        bay, parent.items, index, axis, thickness_mm, spaces
    )
    return [Bay(rule=rule1), Board(material=material), Bay(rule=rule2)]


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
            f"cannot split {bay.id!r}: its {size_before_mm:g}mm opening cannot "
            f"hold a {thickness_mm:g}mm board and still leave two positive bays",
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


def merge_at(unit: Unit, board_id: str, catalog: Catalog) -> Unit:
    """``unit`` with the ``Board`` named ``board_id`` removed and the regions
    either side of it merged into one.

    The merged region takes the first (lower-index) neighbour's id, and a
    rule chosen so ``solve`` reproduces every other region's pre-edit size in
    the run: the neighbours' combined size plus the removed board's
    thickness, ``Fixed`` when both neighbours were ``Fixed``, otherwise a
    ``Weighted`` weight solved against another driven sibling in the run (or
    ``Fill`` when no such sibling exists), the exact inverse of
    :func:`split_region`'s own rule choice. *Unless* the merge leaves its
    enclosing ``Division`` with only that one item left: the ``Division``
    itself is then replaced by it, taking the ``Division``'s own rule
    instead, which is what makes a split-then-merge round trip return the
    tree to its original shape rather than leaving a degenerate one-item
    ``Division`` behind. The second neighbour is discarded whole: when it is
    itself a ``Division``, every board and region in its subtree disappears
    with it, silently, rather than being refused, since the letter of
    "regions either side merged into one" does not distinguish a leaf region
    from a subtree. Raises :class:`EditError` naming ``board_id`` when it
    names no board in ``unit``, or a board whose neighbour on either side is
    missing (the end of a run) or is itself a ``Board`` rather than a
    region.
    """
    spaces = solve(unit, catalog)
    new_root, found = _merge_at(unit.root, board_id, spaces)
    if not found:
        raise EditError(board_id, f"no board with id {board_id!r}")
    return dataclasses.replace(unit, root=new_root)


def _merge_at(
    region: Region, board_id: str, spaces: Mapping[str, Space]
) -> tuple[Region, bool]:
    if not isinstance(region, Division):
        return region, False
    items = region.items
    axis_index = _axis_index(region.axis)
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
            merged_rule = _merged_rule(
                before, after, item, items, index, axis_index, spaces
            )
            merged: Region = dataclasses.replace(before, rule=merged_rule)
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
        new_child, child_found = _merge_at(item, board_id, spaces)
        new_items.append(new_child)
        changed = changed or child_found
    if changed:
        return dataclasses.replace(region, items=new_items), True
    return region, False


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
