"""Refusals in one shape across the workbench's commands: what failed, which
objects are responsible, and what to do next.

The suggested next step is data in :data:`SUGGESTIONS`, keyed by the same
reason codes :class:`~freecad.Shelving.core.scan.ScanError` and
:class:`~freecad.Shelving.core.solver.LayoutSolveError` carry, so a reason
reads the same whichever command reports it. The editor's own refused edits
go through :func:`report_error` alone, with no suggestion or selection.
"""

from collections.abc import Callable, Iterable, Mapping
from typing import Literal, cast

import FreeCAD

from freecad.Shelving.core.layout import Board, Division, Region, Unit
from freecad.Shelving.core.scan import ScanErrorReason
from freecad.Shelving.core.solver import LayoutSolveError, SolveErrorReason

CommandRefusalReason = Literal[
    "no_unit_selected",
    "not_one_container",
    "no_3d_view",
    "task_panel_open",
    "unexpected",
]

RefusalReason = ScanErrorReason | SolveErrorReason | CommandRefusalReason

# freecad-stubs declares PrintTranslatedUserError with one argument, but
# FreeCAD 1.0 and 1.1 accept (notifier, message), and the notifier is what
# labels the popup in the Notification Area.
_print_user_error = cast(
    "Callable[[str, str], None]", FreeCAD.Console.PrintTranslatedUserError
)

# A solver reason surfaces from a command only when Edit Unit opens a unit
# that does not solve. A rescan takes every size from the boards, so this
# needs a unit the scan reads but cannot solve; each solver suggestion still
# leads back to a state the editor can open.
SUGGESTIONS: Mapping[RefusalReason, str] = {
    "no_boxes": (
        "Put the unit's boards inside the container, or select the container "
        "that holds them."
    ),
    "nonpositive_extent": (
        "Give the part a real size in every direction, or move it out of the "
        "unit's container so the unit is read without it."
    ),
    "no_thin_axis": (
        "A board must be thinner in one direction than in the other two. "
        "Simplify the part to a plain board, or move it out of the unit's "
        "container, into a group of its own, so the unit is read without it."
    ),
    "collapses_at_snap": (
        "The part is smaller than the snap tolerance in the elevation. Make "
        "it larger, or move it out of the unit's container."
    ),
    "overlap": (
        "Move or shrink one of the boards so they only touch, or delete it if "
        "it is a duplicate."
    ),
    "not_a_tree": (
        "These boards interlock, so no straight cut separates them. Lengthen "
        "or shorten one so it runs the full width or height of its opening."
    ),
    "partly_enclosed": (
        "Close the gap in the unit's outline with a board, or move the boards "
        "so the opening is fully enclosed or fully open."
    ),
    "crosses_bay": (
        "Trim the board so it stops at the boards around the opening it sits in."
    ),
    "no_elevation": (
        "Every part reads as a back or front panel. Add the unit's sides, top "
        "and bottom as boards inside the container."
    ),
    "no_enclosed_bay": (
        "Move the sides, top and bottom so they meet, closing the gap in the "
        "unit's outer frame."
    ),
    "overflow": (
        "The boards were moved by hand so the unit's stored sizes no longer "
        "fit between them. Undo that move, then change the sizes in Edit Unit, "
        "which moves the boards around them."
    ),
    "no_slack_absorber": (
        "These sizes were stored before the boards were moved by hand. Undo "
        "that move so Edit Unit opens, then change a size or leave one "
        "opening free there."
    ),
    "nonpositive_opening": (
        "The boards were moved by hand so an opening has no room left. Undo "
        "that move, then change the sizes in Edit Unit."
    ),
    "unresolvable_basis": (
        "The boards were changed by hand so a spacing no longer has a board "
        "after it. Undo that change, then edit the unit in Edit Unit."
    ),
    "pinned_mismatch": (
        "This board keeps the size it was drawn at, and the layout needs a "
        "different one. Undo the hand edit that changed the unit, or resize "
        "the board by hand to fit."
    ),
    "no_unit_selected": (
        "Select one unit's container in the tree, or parts that all belong to "
        "the same unit, then run Edit Unit again."
    ),
    "not_one_container": (
        "Select one App::Part, App::LinkGroup or group holding the boards, "
        "grouping loose boards into one first."
    ),
    "no_3d_view": (
        "Open a 3D view of the document with View > Create new view, then run "
        "Edit Unit again."
    ),
    "task_panel_open": (
        "Close the task panel already open in the Tasks tab with OK or "
        "Cancel, then run the command again."
    ),
    "unexpected": (
        "Nothing in the document was changed. This is a workbench fault: "
        "report it with the text above."
    ),
}


def report_error(message: str) -> None:
    """Show ``message`` as a Shelving error in FreeCAD's Notification Area,
    which pops it up briefly and keeps it in the Report view."""
    _print_user_error("Shelving", message + "\n")


def report_refusal(summary: str, objects: Iterable[str], suggestion: str) -> None:
    """Report ``summary``, the objects ``objects`` names and ``suggestion``
    through :func:`report_error` as one message, a line each in that order,
    then select in the 3D view each named object the active document holds,
    replacing the selection.

    With no objects named, the message has no objects line and the selection
    is left alone. A name the document does not hold is shown as given and
    not selected. Selection is skipped without a GUI.
    """
    names = tuple(objects)
    doc = FreeCAD.ActiveDocument
    lines = [f"REFUSED: {summary}"]
    if names:
        lines.append("  Objects: " + ", ".join(_describe(doc, name) for name in names))
    lines.append(f"  Next: {suggestion}")
    report_error("\n".join(lines))
    if names and FreeCAD.GuiUp:
        _select(doc, names)


def _describe(doc: FreeCAD.Document | None, name: str) -> str:
    """``name`` as the tree shows it: the object's label, followed by its
    name when the two differ, since a refusal's summary quotes names."""
    obj = doc.getObject(name) if doc is not None else None
    if obj is None or obj.Label == name:
        return name
    return f"{obj.Label} ({name})"


def _select(doc: FreeCAD.Document | None, names: Iterable[str]) -> None:
    import FreeCADGui as Gui

    Gui.Selection.clearSelection()
    if doc is None:
        return
    for name in names:
        obj = doc.getObject(name)
        if obj is not None:
            Gui.Selection.addSelection(obj)


def solve_error_objects(unit: Unit, err: LayoutSolveError) -> tuple[str, ...]:
    """The boards a user would move to resolve ``err``, as document object
    names: the board ``err`` names, every board in the row or column it
    names, or the boards either side of the opening it names. Empty when
    ``err.node_id`` is not part of ``unit``."""
    if isinstance(unit.root, Division) and unit.root.id == err.node_id:
        return _boards_of(unit.root)
    return _find_objects(unit.root, err.node_id) or ()


def _boards_of(division: Division) -> tuple[str, ...]:
    return tuple(item.id for item in division.items if isinstance(item, Board))


def _find_objects(region: Region, node_id: str) -> tuple[str, ...] | None:
    """:func:`solve_error_objects`'s answer for ``node_id`` within
    ``region``'s subtree, or ``None`` when the subtree does not hold it."""
    if not isinstance(region, Division):
        return None
    for index, item in enumerate(region.items):
        if item.id != node_id:
            continue
        if isinstance(item, Board):
            return (item.id,)
        if isinstance(item, Division):
            return _boards_of(item)
        neighbors = (region.items[index - 1 : index], region.items[index + 1 :][:1])
        return tuple(
            near.id for side in neighbors for near in side if isinstance(near, Board)
        )
    for item in region.items:
        if not isinstance(item, Board):
            found = _find_objects(item, node_id)
            if found is not None:
                return found
    return None
