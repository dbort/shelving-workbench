"""Tree-rewriting edits for the elevation editor: split a bay, merge a board,
size a region, change what a size measures, drag a board.

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


def split_region(
    unit: Unit,
    region_id: str,
    axis: Axis,
    catalog: Catalog,
    material: MaterialId | None = None,
) -> Unit:
    """``unit`` with the ``Bay`` named ``region_id`` replaced by a board on
    ``axis``, splitting it into two bays.

    When ``region_id``'s parent ``Division`` runs along a *different* axis
    than ``axis`` (or ``region_id`` is the tree's own root, which has no
    parent), the replacement is a new ``Division`` on ``axis`` holding
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
    spaces = solve(unit, catalog)
    new_root, found, _collapsed = _merge_at(unit.root, board_id, spaces)
    if not found:
        raise EditError(board_id, f"no board with id {board_id!r}")
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
        raise EditError(region_id, f"no region with id {region_id!r}")
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


def set_size(unit: Unit, region_id: str, size_mm: float, basis: Basis) -> Unit:
    """``unit`` with the region named ``region_id`` given the rule
    ``Fixed(size_mm, basis)``; every other rule is left as it was, so driven
    siblings take up the difference when the result is solved.

    Raises :class:`EditError` naming ``region_id`` when ``size_mm`` is not
    positive, when ``basis`` is ``Basis.WITH_NEXT`` and the next item in the
    region's run is not a board, or when ``region_id`` names the root, a
    board, or nothing in ``unit``.
    """
    parent, index = _locate_region(unit, region_id)
    if size_mm <= 0:
        raise EditError(
            region_id, f"A size must be more than zero; got {size_mm:.1f} mm."
        )
    _next_board(parent, index, basis)
    rule = Fixed(size_mm=size_mm, basis=basis)
    return dataclasses.replace(unit, root=_with_rule(unit.root, region_id, rule))


def _size_in_basis_mm(
    unit: Unit,
    parent: Division,
    index: int,
    clear_mm: float,
    basis: Basis,
    catalog: Catalog,
) -> float:
    """``clear_mm`` restated in ``basis`` for ``parent.items[index]``.

    A spacing adds the next board's catalog thickness rather than its solved
    extent, because that is what the solver subtracts when it resolves
    ``Basis.WITH_NEXT``; the two differ for a board carrying its own rule.
    """
    board = _next_board(parent, index, basis)
    if board is None:
        return clear_mm
    return clear_mm + catalog[board.material or unit.default_material].thickness_mm


def set_basis(unit: Unit, region_id: str, basis: Basis, catalog: Catalog) -> Unit:
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
    spaces = solve(unit, catalog)
    clear_mm = spaces[region_id].extent_mm(_axis_index(parent.axis))
    size_mm = _size_in_basis_mm(unit, parent, index, clear_mm, basis, catalog)
    return set_size(unit, region_id, size_mm, basis)


def run_axis(unit: Unit, node_id: str) -> Axis:
    """The axis of the run holding the node named ``node_id``: the axis its
    size or thickness is measured along. Raises :class:`EditError` naming
    ``node_id`` when it names the root or nothing in ``unit``."""
    found = _locate(unit.root, node_id)
    if found is None:
        raise EditError(node_id, f"no item with id {node_id!r} inside the unit")
    return found[0].axis


def _board_and_region_before(unit: Unit, board_id: str) -> tuple[Division, int]:
    """The run holding ``board_id`` and the index of the region immediately
    before it. Raises :class:`EditError` naming ``board_id`` when it names
    no board, or a board with no region immediately before it."""
    found = _locate(unit.root, board_id)
    if found is None or not isinstance(found[0].items[found[1]], Board):
        raise EditError(board_id, f"no board with id {board_id!r}")
    parent, index = found
    if index == 0 or isinstance(parent.items[index - 1], Board):
        raise EditError(
            board_id,
            "This board has no opening below or left of it for a drag to resize.",
        )
    return parent, index - 1


def region_before(unit: Unit, board_id: str) -> str:
    """The id of the region a drag of ``board_id`` resizes: the one
    immediately before it in its run. Raises :class:`EditError` on the same
    terms as :func:`move_board`'s board checks."""
    parent, index = _board_and_region_before(unit, board_id)
    return parent.items[index].id


def move_board(unit: Unit, board_id: str, low_face_mm: float, catalog: Catalog) -> Unit:
    """``unit`` with the board named ``board_id`` dragged so its low face
    along its run's axis sits at ``low_face_mm`` (a unit-frame coordinate).

    Only the region immediately before the board changes: it is fixed at
    the clear size that puts the board there, restated in the basis that
    region already had (``Basis.CLEAR`` when it was ``Weighted`` or
    ``Fill``), so a drag never changes what a size measures. The board lands
    exactly at ``low_face_mm`` only when nothing before that region is
    driven; otherwise the solve shares the changed slack among those
    earlier siblings too. Raises :class:`EditError` naming ``board_id`` when
    it names no board, or a board with no region immediately before it, and
    naming that region when the drag would leave it no positive size.
    """
    parent, index = _board_and_region_before(unit, board_id)
    region = parent.items[index]
    spaces = solve(unit, catalog)
    region_low_mm = spaces[region.id].origin_mm(_axis_index(parent.axis))
    clear_mm = low_face_mm - region_low_mm
    if clear_mm <= 0:
        raise EditError(
            region.id,
            "The board cannot move past the far side of the opening it resizes.",
        )
    basis = region.rule.basis if isinstance(region.rule, Fixed) else Basis.CLEAR
    size_mm = _size_in_basis_mm(unit, parent, index, clear_mm, basis, catalog)
    return set_size(unit, region.id, size_mm, basis)


@dataclasses.dataclass(frozen=True)
class Measurement:
    """A region's size as the editor shows it."""

    # What the region's size measures: its Fixed rule's basis, or
    # Basis.CLEAR for a Weighted or Fill region, which is what a typed size
    # or a drag would fix it in.
    basis: Basis
    # Whether the region's rule is Fixed; False means it shares slack.
    fixed: bool
    clear_mm: float
    # clear_mm plus the next board's catalog thickness, the number a
    # Basis.WITH_NEXT rule stores; None when no board follows the region.
    spacing_mm: float | None

    @property
    def size_mm(self) -> float:
        """The size in :attr:`basis`: the number a field shows for it."""
        if self.basis is Basis.WITH_NEXT and self.spacing_mm is not None:
            return self.spacing_mm
        return self.clear_mm


def measure(
    unit: Unit, region_id: str, spaces: Mapping[str, Space], catalog: Catalog
) -> Measurement:
    """The :class:`Measurement` of the region named ``region_id``, read from
    ``spaces`` (``unit`` solved against ``catalog``). Raises
    :class:`EditError` when ``region_id`` names the root, a board, or
    nothing, the regions :func:`set_size` refuses."""
    parent, index = _locate_region(unit, region_id)
    region = parent.items[index]
    clear_mm = spaces[region_id].extent_mm(_axis_index(parent.axis))
    spacing_mm: float | None = None
    if index + 1 < len(parent.items) and isinstance(parent.items[index + 1], Board):
        spacing_mm = _size_in_basis_mm(
            unit, parent, index, clear_mm, Basis.WITH_NEXT, catalog
        )
    fixed = isinstance(region.rule, Fixed)
    basis = region.rule.basis if isinstance(region.rule, Fixed) else Basis.CLEAR
    return Measurement(
        basis=basis, fixed=fixed, clear_mm=clear_mm, spacing_mm=spacing_mm
    )
