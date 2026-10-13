"""Spike: a board drag that moves only that board.

``core.edit.move_board`` fixes the opening before the board and lets the
solve share the change among every opening in the run that shares
leftover space, so dragging one shelf moves the shelves around it too. The
user expects the opening on each side of the board to change and nothing
else to move.
"""

from __future__ import annotations

from freecad.Shelving.core.edit import (
    EditError,
    _axis_index,
    _board_and_region_before,
    _size_in_basis_mm,
    move_board,
    region_before,
    set_size,
)
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Basis, Board, Fixed, Unit
from freecad.Shelving.core.solver import solve
from freecad.Shelving.editor.session import EditFailure, Session


def move_board_locally(unit: Unit, board_id: str, low_face_mm: float) -> Unit:
    """``unit`` with ``board_id``'s low face at ``low_face_mm`` along its run,
    the openings before and after it resized, and every other node where it
    was. The opening after keeps its rule when it is the run's only opening
    left sharing space, which then takes up exactly the move; otherwise it
    is fixed at its new size in the basis it had. Raises :class:`EditError`
    on :func:`move_board`'s terms, and naming the opening after when the
    move would leave it no positive size."""
    moved = move_board(unit, board_id, low_face_mm)
    parent, before_index = _board_and_region_before(unit, board_id)
    after_index = before_index + 2
    if after_index >= len(parent.items):
        return moved
    after = parent.items[after_index]
    if isinstance(after, Board):
        return moved
    axis_index = _axis_index(parent.axis)
    spaces = solve(unit)
    shift_mm = low_face_mm - spaces[board_id].origin_mm(axis_index)
    clear_mm = spaces[after.id].extent_mm(axis_index) - shift_mm
    if clear_mm <= 0:
        raise EditError(
            after.id,
            "The board cannot move past the far side of the opening after it.",
        )
    others_share = any(
        not isinstance(item, Board) and not isinstance(item.rule, Fixed)
        for index, item in enumerate(parent.items)
        if index not in (before_index, after_index)
    )
    if not isinstance(after.rule, Fixed) and not others_share:
        return moved
    basis = after.rule.basis if isinstance(after.rule, Fixed) else Basis.CLEAR
    size_mm = _size_in_basis_mm(parent, after_index, clear_mm, basis)
    return set_size(moved, after.id, size_mm, basis)


def drag_to_locally(session: Session, pointer_mm: Vec3) -> EditFailure | None:
    """:meth:`Session.drag_to` with :func:`move_board_locally` in place of
    ``move_board``."""
    drag = session._drag
    if drag is None:
        return EditFailure("no board is being dragged", None)
    board_id, axis, grab_offset_mm = drag
    low_face_mm = pointer_mm.component_mm(axis.component_index) - grab_offset_mm
    try:
        region_id = region_before(session.unit, board_id)
        candidate = move_board_locally(session.unit, board_id, low_face_mm)
    except EditError as err:
        return EditFailure(str(err), err.node_id)
    return session._apply(candidate, select=region_id)
