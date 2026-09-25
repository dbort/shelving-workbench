"""The elevation editor's session: the document, the transaction, and the
edits, behind one small API the panel drives.

Every accepted edit writes straight through
:func:`freecad.Shelving.container.write_container` inside the one
transaction :meth:`Session.open` starts, so the live preview is the real
boards: there is no separate preview model to drift from the real write
path.

Every ``isinstance`` check and structural match here is against
``freecad.Shelving.core.*`` types imported by their fully qualified name.
Two importable copies of the core classes is a shipped bug: ``isinstance``
silently failed to match a ``Board`` against itself and a divider vanished.

Imports no Qt: the scene and the panel read this session's state, this
session never reads theirs.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Literal

import FreeCAD

from freecad.Shelving.catalog import ensure_catalog, read_usable_catalog
from freecad.Shelving.container import read_container, write_container
from freecad.Shelving.core.edit import EditError, merge_at, split_region
from freecad.Shelving.core.geometry import Space
from freecad.Shelving.core.layout import Axis, Bay, Board, Division, Region, Unit
from freecad.Shelving.core.materials import Catalog, MaterialId
from freecad.Shelving.core.record import rules_from_json, with_stored_rules
from freecad.Shelving.core.scan import elevation_axes, scan
from freecad.Shelving.core.solver import LayoutSolveError, solve
from freecad.Shelving.debug_log import Stopwatch

SplitDirection = Literal["horizontal", "vertical"]


@dataclasses.dataclass(frozen=True)
class EditFailure:
    """A rejected :meth:`Session.split` or :meth:`Session.merge` call."""

    message: str
    # Whatever EditError or LayoutSolveError named: the region or board the
    # caller asked to edit, or the node a re-solve refused at. None only when
    # nothing was selected to act on.
    node_id: str | None


def _find_node(region: Region, node_id: str) -> Region | Board | None:
    """The ``Region`` or ``Board`` in ``region``'s subtree (``region``
    included) whose id is ``node_id``, or ``None`` when nothing matches."""
    if region.id == node_id:
        return region
    if not isinstance(region, Division):
        return None
    for item in region.items:
        if isinstance(item, Board):
            if item.id == node_id:
                return item
        else:
            found = _find_node(item, node_id)
            if found is not None:
                return found
    return None


def _read_unit(container: FreeCAD.DocumentObject, catalog: Catalog) -> Unit:
    """``container`` read fresh, scanned against ``catalog``, with its stored
    rules and unit id reapplied.

    Mirrors :func:`freecad.Shelving.unit_ops._rescanned_unit`; kept as its
    own copy here rather than imported, the way every other small
    FreeCAD-layer read helper in this codebase stays local to its own
    module rather than reaching into another module's private name.
    """
    watch = Stopwatch("session read")
    boxes, skipped, record = read_container(container)
    watch.lap(f"read_container ({len(boxes)} boxes, {len(skipped)} skipped)")
    scan_result = scan(
        boxes,
        catalog,
        skipped=skipped,
        depth_axis=record.depth_axis,
        front_at_min=record.front_at_min,
    )
    watch.lap("scan")
    unit = scan_result.unit
    if record.rules_json is not None:
        unit = with_stored_rules(unit, rules_from_json(record.rules_json))
    if record.unit_id is not None:
        unit = dataclasses.replace(unit, id=record.unit_id)
    watch.lap("stored rules")
    return unit


class Session:
    """One elevation-editing session against a selected container."""

    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        watch = Stopwatch("session")
        self.container = container
        self.catalog, self._skipped_catalog_entries = read_usable_catalog(
            ensure_catalog(container.Document)
        )
        watch.lap("catalog")
        # unit and spaces are the current, already-solved state, replaced
        # wholesale by every accepted edit.
        self.unit = _read_unit(container, self.catalog)
        watch.lap("read unit")
        self.spaces: Mapping[str, Space] = solve(self.unit, self.catalog)
        watch.lap("solve")
        # A region or board id. Every accepted edit clears it, since the id
        # it just edited no longer names anything the caller can act on.
        self.selected_id: str | None = None

    def open(self) -> None:
        """Start this session's one transaction. Call once, before any edit.

        A document created by ``FreeCAD.newDocument`` (as every
        ``freecadcmd`` script and this workbench's own smoke does) starts
        with ``UndoMode`` off, unlike a document created through the GUI:
        ``openTransaction``/``abortTransaction`` are silent no-ops against
        it, verified directly, so ``cancel`` would leave every edit in
        place. Setting it here makes cancel work regardless of how the
        document was created.
        """
        self.container.Document.UndoMode = 1
        self.container.Document.openTransaction(  # type: ignore[no-untyped-call]
            "Edit Shelving Unit"
        )

    def commit(self) -> None:
        """End this session's transaction, keeping every edit made."""
        self.container.Document.commitTransaction()  # type: ignore[no-untyped-call]

    def cancel(self) -> None:
        """End this session's transaction, reverting every edit made."""
        self.container.Document.abortTransaction()  # type: ignore[no-untyped-call]

    def select(self, node_id: str | None) -> None:
        self.selected_id = node_id

    def can_split(self) -> bool:
        """Whether the current selection is a ``Bay``: the only region
        :meth:`split` acts on."""
        if self.selected_id is None:
            return False
        node = _find_node(self.unit.root, self.selected_id)
        return isinstance(node, Bay)

    def can_merge(self) -> bool:
        """Whether the current selection is a ``Board``: the only kind of
        node :meth:`merge` acts on. ``True`` does not promise :meth:`merge`
        succeeds: :func:`~freecad.Shelving.core.edit.merge_at` refuses by
        name when the board's neighbours do not permit a merge."""
        if self.selected_id is None:
            return False
        node = _find_node(self.unit.root, self.selected_id)
        return isinstance(node, Board)

    def _apply(self, candidate: Unit) -> EditFailure | None:
        """Adopt ``candidate`` as this session's state and write it to the
        document, clearing the selection, or return an :class:`EditFailure`
        when it fails to solve, leaving the session and document untouched."""
        try:
            spaces = solve(candidate, self.catalog)
            # write_container solves again before writing any board, so a
            # LayoutSolveError from either call means nothing was written.
            write_container(self.container, candidate, self.catalog)
        except LayoutSolveError as err:
            return EditFailure(str(err), err.node_id)
        self.unit = candidate
        self.spaces = spaces
        self.selected_id = None
        return None

    def _elevation_axes(self) -> tuple[Axis, Axis]:
        """The ``(horizontal, vertical)`` elevation axes of
        ``self.unit.depth_axis``. Raises ``ValueError`` naming ``self.unit.id``
        when it is ``None``; a scanned container always resolves a depth
        axis (see :mod:`freecad.Shelving.core.scan`), so this is an
        invariant check, not a user-facing refusal."""
        depth_axis = self.unit.depth_axis
        if depth_axis is None:
            raise ValueError(
                f"unit {self.unit.id!r} has no depth_axis to split by direction"
            )
        return elevation_axes(depth_axis)

    def split(
        self, direction: SplitDirection, material: MaterialId | None = None
    ) -> EditFailure | None:
        """Split the selected ``Bay`` in two, ``material`` defaulting to the
        unit's own.

        ``direction`` names an elevation axis, not a model axis:
        "horizontal" divides the bay left and right behind a vertical
        divider, "vertical" stacks it top and bottom behind a horizontal
        shelf, whichever model axis the unit's depth runs along. Returns
        ``None`` on success, which clears the selection, or an
        :class:`EditFailure` on refusal, which changes nothing."""
        if self.selected_id is None:
            return EditFailure("select a bay to split", None)
        horizontal, vertical = self._elevation_axes()
        axis = horizontal if direction == "horizontal" else vertical
        try:
            candidate = split_region(
                self.unit, self.selected_id, axis, self.catalog, material
            )
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._apply(candidate)

    def merge(self) -> EditFailure | None:
        """Remove the selected ``Board`` and merge its neighbouring regions.
        Returns ``None`` on success, which clears the selection, or an
        :class:`EditFailure` on refusal, which changes nothing."""
        if self.selected_id is None:
            return EditFailure("select a board to merge", None)
        try:
            candidate = merge_at(self.unit, self.selected_id, self.catalog)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._apply(candidate)
