"""The elevation editor's session: the document, its undo steps, and the
edits, behind one small API the panel drives.

Every accepted edit writes straight through
:func:`freecad.Shelving.container.write_container` as its own undo step,
so the live preview is the real boards: there is no separate preview model
to drift from the real write path. :mod:`freecad.Shelving.editor.history`
keeps those steps, reads each Undo and Redo back into the session, and
folds the session into one step at OK.

Every ``isinstance`` check and structural match here is against
``freecad.Shelving.core.*`` types imported by their fully qualified name.
Two importable copies of the core classes is a shipped bug: ``isinstance``
silently failed to match a ``Board`` against itself and a divider vanished.

Imports no Qt: the scene and the panel read this session's state, this
session never reads theirs.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Literal, Protocol, cast

import FreeCAD

from freecad.Shelving import properties
from freecad.Shelving.container import (
    read_container,
    renamed_board_ids,
    write_container,
)
from freecad.Shelving.core.edit import (
    EditError,
    Measurement,
    held_by,
    lock,
    measure,
    merge_at,
    move_board,
    region_before,
    require_movable,
    run_axis,
    set_basis,
    set_size,
    set_unit_size,
    split_region,
    unlock,
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
from freecad.Shelving.core.record import rules_from_json, with_stored_rules
from freecad.Shelving.core.scan import elevation_axes, scan
from freecad.Shelving.core.solver import LayoutSolveError, describe_solve_error, solve
from freecad.Shelving.debug_log import Stopwatch
from freecad.Shelving.editor.history import EditHistory, Schedule

SplitDirection = Literal["horizontal", "vertical"]


class _Labeled(Protocol):
    Label: str


class _Placed(Protocol):
    Placement: FreeCAD.Placement


# The Length property on the session's probe object that the panel's
# dimension field binds to (.claude/docs/freecad-notes.md, "GUI-only widget
# access").
PROBE_PROPERTY = "Dimension"

UnitDimension = Literal["width", "depth", "height"]

# The probe property each of the unit's dimension fields binds to, so an
# expression typed into one field never shows up in another.
UNIT_PROBE_PROPERTIES: Mapping[UnitDimension, str] = {
    "width": "UnitWidth",
    "depth": "UnitDepth",
    "height": "UnitHeight",
}

_PANEL_REASON = (
    "thin through the unit's depth, so it reads as a back or front panel, "
    "which the layout does not place"
)
_UNPLACED_REASON = "not part of the layout"


@dataclasses.dataclass(frozen=True)
class EditFailure:
    """A rejected session edit, returned in place of raising. The edit that
    produced it changed nothing: the document and the session's unit are as
    they were before the call."""

    # Plain words for the user; names no internal id.
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


class UnsolvableUnit(Exception):
    """:class:`Session` construction's refusal when the container scans but
    its boards do not solve as they stand."""

    def __init__(self, error: LayoutSolveError, unit: Unit) -> None:
        super().__init__(str(error))
        self.error = error
        # The unit as read: region ids are minted fresh on every scan, so
        # only this copy holds the region error.node_id names.
        self.unit = unit


@dataclasses.dataclass(frozen=True)
class LeftAlone:
    """An object in the container that this workbench did not write and
    will not change or delete unless told to."""

    name: str
    label: str
    # Why the layout does not use it, in words for the panel.
    reason: str


def _read_unit(container: FreeCAD.DocumentObject) -> tuple[Unit, Mapping[str, str]]:
    """``container`` read fresh and scanned, with its stored rules and unit
    id reapplied, and the reason each part the scan did not place in the
    tree was set aside, keyed by ``Name``.

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


@dataclasses.dataclass(frozen=True)
class SessionState:
    """What a :class:`Session` holds between its edits: everything an Undo
    or Redo puts back."""

    unit: Unit
    spaces: Mapping[str, Space]
    left_alone: tuple[LeftAlone, ...]
    set_aside_reasons: Mapping[str, str]
    # The left-alone objects the session has deleted so far.
    deleted: frozenset[str]


class Session:
    """One elevation-editing session against a selected container."""

    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        """Read and solve ``container``. Raises ``ScanError`` when it does
        not scan and :class:`UnsolvableUnit` when it does not solve."""
        watch = Stopwatch("session")
        self.container = container
        # unit and spaces are the current, already-solved state, replaced
        # wholesale by every accepted edit.
        self.unit, self._set_aside_reasons = _read_unit(container)
        watch.lap("read unit")
        try:
            self.spaces: Mapping[str, Space] = solve(self.unit)
        except LayoutSolveError as err:
            raise UnsolvableUnit(err, self.unit) from err
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
        self._probe_name = ""
        # The board being dragged and the pointer's offset from its low
        # face along its run's axis, between begin_drag and end_drag.
        self._drag: tuple[str, Axis, float] | None = None
        self._deleted: frozenset[str] = frozenset()
        # The stock of each board the session created, keyed by its object
        # name: OK undoes the session and writes its final unit again, and a
        # recreated board's stock_from source may be gone by then.
        self._stock: dict[str, properties.Stock] = {}
        self._history: EditHistory[SessionState] | None = None
        # Runs after an Undo or Redo has been read back, with what to tell
        # the user, if anything.
        self.on_change: Callable[[EditFailure | None], None] | None = None

    def open(self, schedule: Schedule | None = None) -> None:
        """Start this session's undo history with a first step that creates
        the probe object. Call once, before any edit. ``schedule`` defers the
        read-back after an Undo or Redo until FreeCAD has finished it; with
        none, :meth:`settle` does the read-back.

        A document created by ``FreeCAD.newDocument`` (as every
        ``freecadcmd`` script and this workbench's own smoke does) starts
        with ``UndoMode`` off, unlike a document created through the GUI:
        transactions are silent no-ops against it (verified), so ``cancel``
        would leave every edit in place. Setting it here makes cancel work
        regardless of how the document was created.
        """
        self.container.Document.UndoMode = 1
        self._history = EditHistory(
            self.container.Document, self, schedule or (lambda _settle: None)
        )
        self._history.start(self._create_probe)

    def _create_probe(self) -> None:
        probe = cast(
            "FreeCAD.DocumentObject",
            self.container.Document.addObject("App::VarSet", "ShelvingDimensionProbe"),
        )
        for name in (PROBE_PROPERTY, *UNIT_PROBE_PROPERTIES.values()):
            probe.addProperty("App::PropertyLength", name, "Shelving")
        cast("_Labeled", probe).Label = "Shelving dimension (temporary)"
        self.probe = probe
        self._probe_name = probe.Name

    def settle(self) -> None:
        """Read a pending Undo or Redo back into this session now."""
        if self._history is not None:
            self._history.settle()

    def commit(self) -> str | None:
        """End this session, keeping its unit as one undo step and removing
        the probe object. Returns a message for the user when a change made
        elsewhere in the document kept the session from folding into one
        step."""
        message = self._finish(keep=True)
        return message

    def cancel(self) -> str | None:
        """End this session, putting the document back as the session found
        it, the probe object's creation included. Returns a message for the
        user when a change made elsewhere in the document kept the session's
        steps from being undone, and the starting unit was written over
        them instead."""
        return self._finish(keep=False)

    def _finish(self, keep: bool) -> str | None:
        self._drag = None
        history = self._history
        if history is None:
            return None
        message = history.finish(keep)
        self.probe = None
        return message

    @property
    def dragging(self) -> bool:
        """Whether a drag begun with :meth:`begin_drag` is still going: an
        Undo during it ends it."""
        return self._drag is not None

    # What EditHistory needs; see HistoryOwner.

    def capture(self) -> SessionState:
        return SessionState(
            self.unit,
            self.spaces,
            self.left_alone,
            self._set_aside_reasons,
            self._deleted,
        )

    def restore(self, state: SessionState) -> None:
        self.unit = state.unit
        self.spaces = state.spaces
        self.left_alone = state.left_alone
        self._set_aside_reasons = state.set_aside_reasons
        self._deleted = state.deleted
        if self.selected_id is not None and (
            _find_node(state.unit.root, self.selected_id) is None
        ):
            self.selected_id = None

    def write(self, state: SessionState, *, probe: bool) -> Mapping[str, str]:
        doc = self.container.Document
        if probe and self.probe is None:
            self._create_probe()
        if not probe and self.probe is not None:
            # An undone creation leaves the object's wrapper without a Name.
            if doc.getObject(self._probe_name) is not None:
                doc.removeObject(self._probe_name)
            self.probe = None
        for name in state.deleted:
            if doc.getObject(name) is not None:
                doc.removeObject(name)
        result = write_container(self.container, state.unit)
        for old_id, new_id in result.id_renames.items():
            stock = self._stock.get(old_id)
            target = doc.getObject(new_id)
            if stock is not None and target is not None:
                properties.write_stock(stock, target)
                self._stock[new_id] = stock
        return result.id_renames

    def renamed(self, state: SessionState, renames: Mapping[str, str]) -> SessionState:
        if not renames:
            return state
        root = renamed_board_ids(state.unit.root, renames)
        return dataclasses.replace(
            state,
            unit=dataclasses.replace(state.unit, root=root),
            spaces=_renamed_spaces(state.spaces, renames),
        )

    def rescan(self) -> SessionState | None:
        try:
            unit, reasons = _read_unit(self.container)
            spaces = solve(unit)
        except Exception:  # noqa: BLE001 - the session keeps its last state
            return None
        doc = self.container.Document
        left_alone = tuple(
            LeftAlone(
                name=name,
                label=obj.Label if obj is not None else name,
                reason=reasons.get(name, _UNPLACED_REASON),
            )
            for name in sorted(reasons)
            if not properties.has_board_properties(obj := doc.getObject(name))
        )
        return SessionState(unit, spaces, left_alone, reasons, self._deleted)

    def owns(self, name: str) -> bool:
        if name == self.container.Name:
            return True
        group = cast("FreeCAD.DocumentObjectGroup", self.container).Group
        if any(obj.Name == name for obj in group):
            return True
        return _find_node(self.unit.root, name) is not None or any(
            entry.name == name for entry in self.left_alone
        )

    def probe_name(self) -> str | None:
        return self._probe_name if self.probe is not None else None

    def nudge(self) -> None:
        container = cast("_Placed", self.container)
        container.Placement = container.Placement

    def step_interrupted(self) -> None:
        self._drag = None

    def changed(self, message: str | None) -> None:
        if self.on_change is not None:
            self.on_change(EditFailure(message, None) if message else None)

    def _step(
        self, name: str, edit: Callable[[], EditFailure | None]
    ) -> EditFailure | None:
        """Run ``edit`` as one undo step named ``name``; a refusal, or an
        exception, leaves none."""
        history = self._history
        if history is None or history.finished:
            return edit()
        history.begin(name)
        failure: EditFailure | None = EditFailure("the edit did not finish", None)
        try:
            failure = edit()
        finally:
            history.end(keep=failure is None)
        return failure

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
        name when the board's neighbors do not permit a merge."""
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
            spaces: Mapping[str, Space] = solve(candidate)
            # write_container solves again before writing any board, so a
            # LayoutSolveError from either call means nothing was written.
            result = write_container(self.container, candidate)
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
            doc = self.container.Document
            for name in result.id_renames.values():
                created = doc.getObject(name)
                if created is not None:
                    self._stock[name] = properties.read_stock(created)
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
                f"unit {self.unit.id!r} has no depth_axis to orient its elevation"
            )
        return elevation_axes(depth_axis)

    def _unit_axis(self, dimension: UnitDimension) -> Axis:
        """The model axis ``dimension`` names: width and height are the
        elevation's horizontal and vertical axes, depth is the depth axis.
        Raises ``ValueError`` on the same terms as :meth:`_elevation_axes`."""
        horizontal, vertical = self._elevation_axes()
        if dimension == "width":
            return horizontal
        if dimension == "height":
            return vertical
        return next(axis for axis in Axis if axis not in (horizontal, vertical))

    def unit_dimension_mm(self, dimension: UnitDimension) -> float:
        """The unit's outer size along ``dimension``, as scanned or last set:
        a part the scan set aside, such as a back panel, does not count."""
        size_mm = self.unit.size_mm
        return (size_mm.x_mm, size_mm.y_mm, size_mm.z_mm)[
            self._unit_axis(dimension).component_index
        ]

    def resize(self, dimension: UnitDimension, size_mm: float) -> EditFailure | None:
        """Set the unit's outer size along ``dimension``, keeping its minimum
        corner where it is and the selection as it was. Returns ``None`` on
        success or an :class:`EditFailure` on refusal, which changes
        nothing."""
        components = [
            self.unit.size_mm.x_mm,
            self.unit.size_mm.y_mm,
            self.unit.size_mm.z_mm,
        ]
        components[self._unit_axis(dimension).component_index] = size_mm
        try:
            candidate = set_unit_size(self.unit, Vec3(*components))
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._step(
            "Resize Unit", lambda: self._apply(candidate, select=self.selected_id)
        )

    def split(self, direction: SplitDirection) -> EditFailure | None:
        """Split the selected ``Bay`` in two with a board that copies its stock
        from :func:`~freecad.Shelving.core.stock.source_board`'s choice.

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
            candidate = split_region(self.unit, self.selected_id, axis)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        name = "Add Divider" if direction == "horizontal" else "Add Shelf"
        return self._step(name, lambda: self._apply(candidate))

    def merge(self) -> EditFailure | None:
        """Remove the selected ``Board`` and merge its neighboring regions.
        Returns ``None`` on success, which clears the selection, or an
        :class:`EditFailure` on refusal, which changes nothing."""
        if self.selected_id is None:
            return EditFailure("select a board to merge", None)
        try:
            candidate = merge_at(self.unit, self.selected_id)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._step("Delete Board", lambda: self._apply(candidate))

    def clear_probe_expression(self) -> None:
        """Remove any expression a dimension field's f(x) dialog bound to
        the probe. The edit already holds the resolved number, and while
        the expression stays its field is read-only; for the region size
        field, that means read-only for every region."""
        if self.probe is not None:
            for name in (PROBE_PROPERTY, *UNIT_PROBE_PROPERTIES.values()):
                self.probe.setExpression(name, None)

    def selected_measurement(self) -> Measurement | None:
        """The selected region's :class:`~freecad.Shelving.core.edit.Measurement`,
        or ``None`` when the selection is nothing, a board, or the whole
        unit: nothing a size applies to."""
        if self.selected_id is None:
            return None
        try:
            return measure(self.unit, self.selected_id, self.spaces)
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
            basis = measure(self.unit, region_id, self.spaces).basis
            candidate = set_size(self.unit, region_id, size_mm, basis)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._step("Set Size", lambda: self._apply(candidate, select=region_id))

    def set_basis(self, basis: Basis) -> EditFailure | None:
        """Change what the selected region's size measures, moving nothing.
        The selection is kept. Returns ``None`` on success or an
        :class:`EditFailure` on refusal, which changes nothing."""
        if self.selected_id is None:
            return EditFailure("select a region to measure", None)
        region_id = self.selected_id
        try:
            candidate = set_basis(self.unit, region_id, basis)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return EditFailure(describe_solve_error(err), err.node_id)
        return self._step(
            "Change What a Size Measures",
            lambda: self._apply(candidate, select=region_id),
        )

    def set_locks(self, region_ids: Sequence[str], locked: bool) -> EditFailure | None:
        """Lock each of ``region_ids`` when ``locked``, else unlock each, as
        one write that moves nothing and keeps the selection. Returns an
        :class:`EditFailure` on refusal, such as locking a run's last
        unlocked region, leaving the session and document untouched."""
        candidate = self.unit
        try:
            for region_id in region_ids:
                candidate = (lock if locked else unlock)(candidate, region_id)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return EditFailure(describe_solve_error(err), err.node_id)
        name = "Lock Openings" if locked else "Unlock Openings"
        return self._step(name, lambda: self._apply(candidate, select=self.selected_id))

    def held_by(self, board_id: str) -> tuple[str, ...] | None:
        """:func:`~freecad.Shelving.core.edit.held_by` for this session's
        unit: the locked regions to unlock so a drag may move ``board_id``,
        empty when it may move, ``None`` when no unlock would free it."""
        return held_by(self.unit, board_id)

    def begin_drag(self, board_id: str, grab_mm: Vec3) -> EditFailure | None:
        """Start dragging ``board_id``, grabbed at the unit-frame point
        ``grab_mm``; each :meth:`drag_to` keeps that point under the pointer.
        Leaves the selection alone, so a press that never moves still
        selects the board. Returns an :class:`EditFailure`, starting no
        drag, when a drag may not move the board: a locked region holds it,
        or no unlock would free it."""
        try:
            require_movable(self.unit, board_id)
            axis = run_axis(self.unit, board_id)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        low_mm = self.spaces[board_id].origin_mm(axis.component_index)
        self._drag = (
            board_id,
            axis,
            grab_mm.component_mm(axis.component_index) - low_mm,
        )
        # Every move of the drag fills this one step; end_drag closes it.
        if self._history is not None and not self._history.finished:
            self._history.begin("Move Board")
        return None

    def drag_to(self, pointer_mm: Vec3) -> EditFailure | None:
        """Move the dragged board so its grab point follows ``pointer_mm``
        along its run's axis, re-solving and writing the boards, and select
        the region before it. Boards joined to it through locked regions
        move with it, and only the first unlocked region on each side
        changes size. Returns an :class:`EditFailure`, leaving the last good
        state, when this step is refused or would not solve, or no drag is in
        progress."""
        if self._drag is None:
            return EditFailure("no board is being dragged", None)
        board_id, axis, grab_offset_mm = self._drag
        low_face_mm = pointer_mm.component_mm(axis.component_index) - grab_offset_mm
        try:
            region_id = region_before(self.unit, board_id)
            candidate = move_board(self.unit, board_id, low_face_mm)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._apply(candidate, select=region_id)

    def end_drag(self) -> None:
        """End the drag, closing its undo step; a drag that moved nothing
        leaves none."""
        self._drag = None
        if self._history is not None and self._history.step_open:
            self._history.end(keep=True)

    def delete_untagged(self, names: Collection[str]) -> EditFailure | None:
        """Delete the listed :attr:`left_alone` objects as one undo step, so
        Undo and :meth:`cancel` restore them. Refuses, deleting nothing,
        when any name is not currently listed."""
        listed = {entry.name for entry in self.left_alone}
        unknown = sorted(set(names) - listed)
        if unknown:
            return EditFailure(
                f"not an object this unit leaves alone: {', '.join(unknown)}",
                unknown[0],
            )
        doc = self.container.Document

        def delete() -> EditFailure | None:
            for name in names:
                doc.removeObject(name)
            self.left_alone = tuple(e for e in self.left_alone if e.name not in names)
            self._deleted = self._deleted | frozenset(names)
            return None

        return self._step("Delete Objects", delete)
