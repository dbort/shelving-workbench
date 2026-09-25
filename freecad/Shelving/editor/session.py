"""The elevation editor's session: the document, the transaction, and the
edits, behind one small API the panel drives.

Constructed from a selected container, a :class:`Session` reads it once
(:func:`freecad.Shelving.core.scan.scan`, with its stored rules reapplied),
keeps the resulting :class:`~freecad.Shelving.core.layout.Unit` and the
document's catalog, and solves it once for the elevation to draw. Every
accepted edit rebuilds the tree through
:mod:`freecad.Shelving.core.edit`, re-solves it, and writes it straight
through sh-018's :func:`freecad.Shelving.container.write_container`, inside
the one transaction :meth:`Session.open` starts: there is no separate
preview model to keep in sync with the real write path (see this repo's
sh-020 Frontier Advice, "live preview writes real boards").

A rejected edit, whether :mod:`freecad.Shelving.core.edit` refuses it as
structurally impossible or the rebuilt tree fails to solve, changes nothing:
:meth:`Session.split` and :meth:`Session.merge` re-solve the candidate tree
and let :func:`~freecad.Shelving.container.write_container` run its own
internal solve before writing anything, so a failure at either point never
reaches the document. Every FreeCAD ``isinstance`` / structural match in
this module is against ``freecad.Shelving.core.*`` types, imported fully
qualified and consistently, per this repo's sh-020 Frontier Advice on why
two importable copies of the same core classes is a real, previously-shipped
bug (a divider vanishing because ``isinstance`` silently failed to match a
``Board`` against itself).

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

SplitDirection = Literal["horizontal", "vertical"]


@dataclasses.dataclass(frozen=True)
class EditFailure:
    """A rejected :meth:`Session.split` or :meth:`Session.merge` call.

    ``node_id`` is whatever :class:`~freecad.Shelving.core.edit.EditError` or
    :class:`~freecad.Shelving.core.solver.LayoutSolveError` named: the region
    or board the caller asked to edit, or the node a re-solve refused at.
    ``None`` means no node was named at all, which only happens when nothing
    was selected to act on in the first place.
    """

    message: str
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
    boxes, skipped, record = read_container(container)
    scan_result = scan(
        boxes,
        catalog,
        skipped=skipped,
        depth_axis=record.depth_axis,
        front_at_min=record.front_at_min,
    )
    unit = scan_result.unit
    if record.rules_json is not None:
        unit = with_stored_rules(unit, rules_from_json(record.rules_json))
    if record.unit_id is not None:
        unit = dataclasses.replace(unit, id=record.unit_id)
    return unit


class Session:
    """One elevation-editing session against a selected container.

    ``unit`` and ``spaces`` are the current, already-solved state: read at
    construction, replaced wholesale after every edit
    :meth:`split`/:meth:`merge` accepts. ``selected_id`` is a region id or a
    board id, or ``None`` when nothing is selected; :meth:`select` is the
    only way it changes, including back to ``None``, which every accepted
    edit does itself since the id it just edited no longer names anything
    the caller can act on.
    """

    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        self.container = container
        self.catalog, self._skipped_catalog_entries = read_usable_catalog(
            ensure_catalog(container.Document)
        )
        self.unit = _read_unit(container, self.catalog)
        self.spaces: Mapping[str, Space] = solve(self.unit, self.catalog)
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
        node :meth:`merge` acts on. Whether that board's neighbours actually
        permit a merge is only known once :meth:`merge` tries, since that is
        exactly what :func:`~freecad.Shelving.core.edit.merge_at` itself
        refuses by name when it does not hold."""
        if self.selected_id is None:
            return False
        node = _find_node(self.unit.root, self.selected_id)
        return isinstance(node, Board)

    def _apply(self, candidate: Unit) -> EditFailure | None:
        """Re-solve ``candidate`` and write it through sh-018's write path;
        on success, adopt it as this session's new state and clear the
        selection. On failure, this session's ``unit``/``spaces`` are
        untouched: :func:`~freecad.Shelving.container.write_container` runs
        its own internal solve before writing any board, so a
        :class:`~freecad.Shelving.core.solver.LayoutSolveError` here means
        nothing reached the document."""
        try:
            spaces = solve(candidate, self.catalog)
            write_container(self.container, candidate, self.catalog)
        except LayoutSolveError as err:
            return EditFailure(str(err), err.node_id)
        self.unit = candidate
        self.spaces = spaces
        self.selected_id = None
        return None

    def _elevation_axes(self) -> tuple[Axis, Axis]:
        """This session's own ``(horizontal, vertical)`` elevation axes,
        resolved from ``self.unit.depth_axis``. Raises ``ValueError`` naming
        ``self.unit.id`` when it is ``None``, the same guard
        :func:`freecad.Shelving.editor.scene.build_scene` already applies to
        the very same unit before this method could ever run: a session is
        always built from a scanned container, which always resolves a
        depth axis (see :mod:`freecad.Shelving.core.scan`), so this is an
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
        """Split the selected ``Bay`` into two, ``material`` defaulting to
        the unit's own. ``direction`` chooses which of the elevation's two
        axes (:func:`freecad.Shelving.core.scan.elevation_axes` of
        ``self.unit.depth_axis``) the split runs along rather than naming a
        model axis directly: "horizontal" divides the bay left and right
        behind a vertical divider board, "vertical" stacks it top and bottom
        behind a horizontal shelf, in both cases regardless of which model
        axis (X, Y, or Z) the unit's depth actually runs along. Returns
        ``None`` on success, an :class:`EditFailure` on refusal, changing
        nothing either way but the selection on success."""
        if self.selected_id is None:
            return EditFailure("select a bay to split", None)
        horizontal, vertical = self._elevation_axes()
        axis = horizontal if direction == "horizontal" else vertical
        try:
            candidate = split_region(self.unit, self.selected_id, axis, material)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._apply(candidate)

    def merge(self) -> EditFailure | None:
        """Remove the selected ``Board`` and merge its neighbouring regions.
        Returns ``None`` on success, an :class:`EditFailure` on refusal,
        changing nothing either way but the selection on success."""
        if self.selected_id is None:
            return EditFailure("select a board to merge", None)
        try:
            candidate = merge_at(self.unit, self.selected_id)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._apply(candidate)
