"""Spike: locked and unlocked openings, and a board drag that moves only
that board.

An opening with a ``Fixed`` rule is locked; one sharing the leftover space
is unlocked. ``core.edit.move_board`` fixes the opening before the board and
lets the solve share the change among every unlocked opening in the run,
so dragging one shelf moves the shelves around it too, and it locks an
opening the user never asked to lock. Here a lock holds the board next to
it in place, and a drag reweights the two unlocked openings beside the
board so the size one unit of weight gets in the run, and with it every
other opening, stays as it was.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from freecad.Shelving.core.edit import (
    EditError,
    _axis_index,
    _locate,
    _locate_region,
    _with_rule,
    set_size,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Basis,
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
from freecad.Shelving.core.solver import LayoutSolveError, describe_solve_error, solve
from freecad.Shelving.editor.session import EditFailure, Session

_LAST_UNLOCKED = (
    "One opening in each row stays unlocked, to take up changes to the unit's size."
)


def is_locked(item: Item) -> bool:
    """Whether ``item`` is an opening with a fixed size; a board never is."""
    return not isinstance(item, Board) and isinstance(item.rule, Fixed)


def _weight(rule: SizeRule) -> float:
    return rule.weight if isinstance(rule, Weighted) else 1.0


def _share_mm(
    parent: Division, spaces: dict[str, Space], skip: int | None = None
) -> float | None:
    """The size one unit of weight gets in ``parent``'s run, read from its
    first unlocked region other than the one at ``skip``; ``None`` when there
    is none."""
    axis_index = _axis_index(parent.axis)
    for index, item in enumerate(parent.items):
        if index == skip or isinstance(item, Board) or is_locked(item):
            continue
        return spaces[item.id].extent_mm(axis_index) / _weight(item.rule)
    return None


def lock(unit: Unit, region_id: str) -> Unit:
    """``unit`` with ``region_id`` fixed at its solved clear size, so nothing
    moves. Raises :class:`EditError` naming ``region_id`` when it is the last
    unlocked opening in its run, or on ``set_size``'s terms."""
    parent, index = _locate_region(unit, region_id)
    region = parent.items[index]
    if is_locked(region):
        return unit
    others_unlocked = any(
        not isinstance(item, Board) and not is_locked(item)
        for i, item in enumerate(parent.items)
        if i != index
    )
    if not others_unlocked:
        raise EditError(region_id, _LAST_UNLOCKED)
    size_mm = solve(unit)[region_id].extent_mm(_axis_index(parent.axis))
    return set_size(unit, region_id, size_mm, Basis.CLEAR)


def unlock(unit: Unit, region_id: str) -> Unit:
    """``unit`` with ``region_id`` sharing the leftover space at the weight
    that holds its solved size, so nothing moves. Raises :class:`EditError`
    on ``_locate_region``'s terms."""
    parent, index = _locate_region(unit, region_id)
    region = parent.items[index]
    if not is_locked(region):
        return unit
    spaces = solve(unit)
    size_mm = spaces[region_id].extent_mm(_axis_index(parent.axis))
    share_mm = _share_mm(parent, spaces, skip=index)
    rule: SizeRule = Weighted(size_mm / share_mm) if share_mm else Fill()
    return dataclasses.replace(unit, root=_with_rule(unit.root, region_id, rule))


def _neighbors(unit: Unit, board_id: str) -> tuple[Division, Region, Region] | None:
    """The run holding ``board_id`` and the regions on either side of it, or
    ``None`` when it is not a board with a region on each side."""
    found = _locate(unit.root, board_id)
    if found is None:
        return None
    parent, index = found
    if (
        not isinstance(parent.items[index], Board)
        or not 0 < index < len(parent.items) - 1
    ):
        return None
    before = parent.items[index - 1]
    after = parent.items[index + 1]
    if isinstance(before, Board) or isinstance(after, Board):
        return None
    return parent, before, after


def holders(unit: Unit, board_id: str) -> tuple[str, ...] | None:
    """The locked openings holding ``board_id`` in place, empty when a drag
    may move it, or ``None`` when it has no opening on each side to drag
    between."""
    found = _neighbors(unit, board_id)
    if found is None:
        return None
    _parent, before, after = found
    return tuple(region.id for region in (before, after) if is_locked(region))


def move_board_locally(unit: Unit, board_id: str, low_face_mm: float) -> Unit:
    """``unit`` with ``board_id``'s low face at ``low_face_mm`` along its run
    and only the two openings beside it resized, both still unlocked.
    Raises :class:`EditError` naming the board when it has no opening on
    each side, naming a locked opening holding it, or naming the opening
    the move would leave no positive size."""
    found = _neighbors(unit, board_id)
    if found is None:
        raise EditError(
            board_id, "This board has no opening on each side to move between."
        )
    parent, before, after = found
    for region in (before, after):
        if is_locked(region):
            raise EditError(region.id, "A locked opening holds this board in place.")
    axis_index = _axis_index(parent.axis)
    spaces = solve(unit)
    shift_mm = low_face_mm - spaces[board_id].origin_mm(axis_index)
    before_mm = spaces[before.id].extent_mm(axis_index) + shift_mm
    after_mm = spaces[after.id].extent_mm(axis_index) - shift_mm
    for region, size_mm in ((before, before_mm), (after, after_mm)):
        if size_mm <= 0:
            raise EditError(
                region.id, "The board cannot move past the far side of this opening."
            )
    # Both neighbors are unlocked, so the run has a share.
    share_mm = _share_mm(parent, spaces) or 1.0
    root = _with_rule(unit.root, before.id, Weighted(before_mm / share_mm))
    root = _with_rule(root, after.id, Weighted(after_mm / share_mm))
    return dataclasses.replace(unit, root=root)


def drag_to_locally(session: Session, pointer_mm: Vec3) -> EditFailure | None:
    """:meth:`Session.drag_to` with :func:`move_board_locally` in place of
    ``move_board``."""
    drag = session._drag
    if drag is None:
        return EditFailure("no board is being dragged", None)
    board_id, axis, grab_offset_mm = drag
    low_face_mm = pointer_mm.component_mm(axis.component_index) - grab_offset_mm
    try:
        candidate = move_board_locally(session.unit, board_id, low_face_mm)
    except EditError as err:
        return EditFailure(str(err), err.node_id)
    return session._apply(candidate, select=board_id)


def set_locks(
    session: Session, region_ids: Sequence[str], locked: bool
) -> EditFailure | None:
    """Lock or unlock each of ``region_ids`` in one write, keeping the
    selection. Nothing moves; a refusal leaves the session as it was."""
    candidate = session.unit
    try:
        for region_id in region_ids:
            candidate = (lock if locked else unlock)(candidate, region_id)
    except EditError as err:
        return EditFailure(str(err), err.node_id)
    except LayoutSolveError as err:
        return EditFailure(describe_solve_error(err), err.node_id)
    return session._apply(candidate, select=session.selected_id)
