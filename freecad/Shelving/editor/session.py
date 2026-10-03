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
from collections.abc import Collection, Mapping
from typing import Literal, Protocol, cast

import FreeCAD

from freecad.Shelving import properties
from freecad.Shelving.catalog import ensure_catalog, read_usable_catalog
from freecad.Shelving.container import (
    read_container,
    renamed_board_ids,
    write_container,
)
from freecad.Shelving.core.edit import (
    EditError,
    Measurement,
    measure,
    merge_at,
    move_board,
    region_before,
    run_axis,
    set_basis,
    set_size,
    split_region,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Region,
    Unit,
)
from freecad.Shelving.core.materials import Catalog, MaterialId
from freecad.Shelving.core.record import rules_from_json, with_stored_rules
from freecad.Shelving.core.scan import elevation_axes, scan
from freecad.Shelving.core.solver import LayoutSolveError, describe_solve_error, solve
from freecad.Shelving.debug_log import Stopwatch

SplitDirection = Literal["horizontal", "vertical"]


class _Labelled(Protocol):
    Label: str


# The Length property on the session's probe object that the panel's
# dimension field binds to (.claude/docs/freecad-notes.md, "GUI-only widget
# access").
PROBE_PROPERTY = "Dimension"

_PANEL_REASON = (
    "thin through the unit's depth, so it reads as a back or front panel, "
    "which the layout does not place"
)
_UNPLACED_REASON = "not part of the layout"


@dataclasses.dataclass(frozen=True)
class EditFailure:
    """A rejected session edit."""

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


def _renamed_spaces(
    spaces: Mapping[str, Space], renames: Mapping[str, str]
) -> Mapping[str, Space]:
    """``spaces`` with every key present in ``renames`` replaced by its
    mapped value; every other key is untouched. Keeps a session's solved
    spaces keyed the same way as ``self.unit``'s board ids after
    :func:`~freecad.Shelving.container.renamed_board_ids` adopts a
    freshly-created board's real ``Name``."""
    if not renames:
        return spaces
    return {renames.get(node_id, node_id): space for node_id, space in spaces.items()}


@dataclasses.dataclass(frozen=True)
class LeftAlone:
    """An object in the container that this workbench did not write and
    will not change or delete unless told to."""

    name: str
    label: str
    # Why the layout does not use it, in words for the panel.
    reason: str


def _read_unit(
    container: FreeCAD.DocumentObject, catalog: Catalog
) -> tuple[Unit, Mapping[str, str]]:
    """``container`` read fresh, scanned against ``catalog``, with its stored
    rules and unit id reapplied, and the reason each part the scan did not
    place in the tree was set aside, keyed by ``Name``.

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
    reasons = {entry.name: entry.reason for entry in scan_result.skipped}
    reasons.update((panel.name, _PANEL_REASON) for panel in scan_result.panels)
    return unit, reasons


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
        self.unit, self._set_aside_reasons = _read_unit(container, self.catalog)
        watch.lap("read unit")
        self.spaces: Mapping[str, Space] = solve(self.unit, self.catalog)
        watch.lap("solve")
        # A region or board id. A split or merge clears it, since the id it
        # just edited no longer names anything the caller can act on.
        self.selected_id: str | None = None
        # Untagged objects the layout does not place: what a write leaves
        # alone. Before the first write that is every set-aside part
        # carrying no board properties, since write_container deletes a
        # tagged one; after it, exactly what the write reported.
        doc = container.Document
        self.left_alone: tuple[LeftAlone, ...] = tuple(
            self._left_alone(name)
            for name in sorted(self._set_aside_reasons)
            if not properties.has_board_properties(doc.getObject(name))
        )
        # The object the panel's dimension field binds to, so it can resolve
        # an expression naming a VarSet; exists only between open() and the
        # end of the transaction.
        self.probe: FreeCAD.DocumentObject | None = None
        # The board being dragged and the pointer's offset from its low
        # face along its run's axis, between begin_drag and end_drag.
        self._drag: tuple[str, Axis, float] | None = None

    def open(self) -> None:
        """Start this session's one transaction. Call once, before any edit.

        A document created by ``FreeCAD.newDocument`` (as every
        ``freecadcmd`` script and this workbench's own smoke does) starts
        with ``UndoMode`` off, unlike a document created through the GUI:
        ``openTransaction``/``abortTransaction`` are silent no-ops against
        it (verified), so ``cancel`` would leave every edit in
        place. Setting it here makes cancel work regardless of how the
        document was created.
        """
        doc = self.container.Document
        doc.UndoMode = 1
        doc.openTransaction("Edit Shelving Unit")  # type: ignore[no-untyped-call]
        # Created inside the transaction, so the abort in cancel() removes it
        # and commit() only has to remove it before committing.
        probe = cast(
            "FreeCAD.DocumentObject",
            doc.addObject("App::VarSet", "ShelvingDimensionProbe"),
        )
        probe.addProperty("App::PropertyLength", PROBE_PROPERTY, "Shelving")
        cast("_Labelled", probe).Label = "Shelving dimension (temporary)"
        self.probe = probe

    def commit(self) -> None:
        """End this session's transaction, keeping every edit made and
        removing the probe object."""
        doc = self.container.Document
        if self.probe is not None:
            doc.removeObject(self.probe.Name)
            self.probe = None
        doc.commitTransaction()  # type: ignore[no-untyped-call]

    def cancel(self) -> None:
        """End this session's transaction, reverting every edit made,
        including the probe object's creation."""
        self.probe = None
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

    def _left_alone(self, name: str) -> LeftAlone:
        obj = self.container.Document.getObject(name)
        return LeftAlone(
            name=name,
            label=obj.Label if obj is not None else name,
            reason=self._set_aside_reasons.get(name, _UNPLACED_REASON),
        )

    def _apply(self, candidate: Unit, select: str | None = None) -> EditFailure | None:
        """Adopt ``candidate`` as this session's state and write it to the
        document, selecting ``select``, or return an :class:`EditFailure`
        when it fails to solve, leaving the session and document untouched."""
        try:
            spaces: Mapping[str, Space] = solve(candidate, self.catalog)
            # write_container solves again before writing any board, so a
            # LayoutSolveError from either call means nothing was written.
            result = write_container(self.container, candidate, self.catalog)
        except LayoutSolveError as err:
            return EditFailure(describe_solve_error(err), err.node_id)
        if result.id_renames:
            # A board split created carries a fresh new_id(), not yet a
            # document object Name; without adopting the real Name here,
            # the next _apply's write_container call would fail to match
            # this board by Name and delete and recreate it instead
            # (bug-008).
            candidate = dataclasses.replace(
                candidate, root=renamed_board_ids(candidate.root, result.id_renames)
            )
            spaces = _renamed_spaces(spaces, result.id_renames)
        self.unit = candidate
        self.spaces = spaces
        self.selected_id = select
        self.left_alone = tuple(self._left_alone(name) for name in result.left_alone)
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

    def clear_probe_expression(self) -> None:
        """Remove any expression the dimension field's f(x) dialog bound to
        the probe. The rule already holds the resolved number, and while
        the expression stays the field is read-only for every region."""
        if self.probe is not None:
            self.probe.setExpression(PROBE_PROPERTY, None)

    def selected_measurement(self) -> Measurement | None:
        """The selected region's :class:`~freecad.Shelving.core.edit.Measurement`,
        or ``None`` when the selection is nothing, a board, or the whole
        unit: nothing a size applies to."""
        if self.selected_id is None:
            return None
        try:
            return measure(self.unit, self.selected_id, self.spaces, self.catalog)
        except EditError:
            return None

    def set_size(self, size_mm: float) -> EditFailure | None:
        """Fix the selected region at ``size_mm``, a value FreeCAD's own
        quantity widget already resolved, in the basis the region already
        measures in. The selection is kept. Returns ``None`` on success or
        an :class:`EditFailure` on refusal, which changes nothing."""
        if self.selected_id is None:
            return EditFailure("select a region to size", None)
        region_id = self.selected_id
        try:
            basis = measure(self.unit, region_id, self.spaces, self.catalog).basis
            candidate = set_size(self.unit, region_id, size_mm, basis)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._apply(candidate, select=region_id)

    def set_basis(self, basis: Basis) -> EditFailure | None:
        """Change what the selected region's size measures, moving nothing.
        The selection is kept. Returns ``None`` on success or an
        :class:`EditFailure` on refusal, which changes nothing."""
        if self.selected_id is None:
            return EditFailure("select a region to measure", None)
        region_id = self.selected_id
        try:
            candidate = set_basis(self.unit, region_id, basis, self.catalog)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return EditFailure(describe_solve_error(err), err.node_id)
        return self._apply(candidate, select=region_id)

    def begin_drag(self, board_id: str, grab_mm: Vec3) -> EditFailure | None:
        """Start dragging ``board_id``, grabbed at the unit-frame point
        ``grab_mm``; each :meth:`drag_to` keeps that point under the pointer.
        Leaves the selection alone, so a press that never moves still
        selects the board. Returns an :class:`EditFailure`, starting no
        drag, when the board has no region before it."""
        try:
            region_before(self.unit, board_id)
            axis = run_axis(self.unit, board_id)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        low_mm = self.spaces[board_id].origin_mm(axis.component_index)
        self._drag = (
            board_id,
            axis,
            grab_mm.component_mm(axis.component_index) - low_mm,
        )
        return None

    def drag_to(self, pointer_mm: Vec3) -> EditFailure | None:
        """Move the dragged board so its grab point follows ``pointer_mm``
        along its run's axis, re-solving and writing the boards, and select
        the region before it: only that region's number changes, never its
        basis. Returns an :class:`EditFailure`, leaving the last good state,
        when this step would not solve or no drag is in progress."""
        if self._drag is None:
            return EditFailure("no board is being dragged", None)
        board_id, axis, grab_offset_mm = self._drag
        low_face_mm = pointer_mm.component_mm(axis.component_index) - grab_offset_mm
        try:
            region_id = region_before(self.unit, board_id)
            candidate = move_board(self.unit, board_id, low_face_mm, self.catalog)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._apply(candidate, select=region_id)

    def end_drag(self) -> None:
        self._drag = None

    def remove_untagged(self, names: Collection[str]) -> EditFailure | None:
        """Delete the listed :attr:`left_alone` objects inside this
        session's transaction, so :meth:`cancel` restores them. Refuses,
        deleting nothing, when any name is not currently listed."""
        listed = {entry.name for entry in self.left_alone}
        unknown = sorted(set(names) - listed)
        if unknown:
            return EditFailure(
                f"not an object this unit leaves alone: {', '.join(unknown)}",
                unknown[0],
            )
        doc = self.container.Document
        for name in names:
            doc.removeObject(name)
        self.left_alone = tuple(e for e in self.left_alone if e.name not in names)
        return None
