"""The elevation editor's session: the document, its undo steps, and the
edits, behind one small API the panel drives.

Every accepted edit writes straight through
:func:`freecad.Shelving.container.write_container` as its own undo step,
so the live preview is the real boards: there is no separate preview model
to drift from the real write path. The steps stay after the panel closes;
:mod:`freecad.Shelving.editor.history` reads each Undo and Redo back into
the session.

Every ``isinstance`` check and structural match here is against
``freecad.Shelving.core.*`` types imported by their fully qualified name.
Two importable copies of the core classes is a shipped bug: ``isinstance``
silently failed to match a ``Board`` against itself and a divider vanished.

Imports no Qt: the panel and the view editor read this session's state,
this session never reads theirs.
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from typing import Concatenate, Literal, ParamSpec

import FreeCAD

from freecad.Shelving import properties, refusals
from freecad.Shelving.container import (
    read_container,
    renamed_board_ids,
    write_container,
)
from freecad.Shelving.core.backs import BackFitError, renamed_back_boards
from freecad.Shelving.core.edit import (
    ConstraintStatus,
    EditError,
    Held,
    Measurement,
    add_equal_along,
    add_even_spacing,
    constraint_status,
    held_by,
    lock,
    measure,
    merge_at,
    move_board,
    remove_boards,
    remove_constraints,
    remove_deactivated,
    require_movable,
    run_axis,
    set_basis,
    set_constraint_active,
    set_constraint_basis,
    set_size,
    set_thickness,
    set_unit_size,
    settle_constraints,
    split_region,
    unlock,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Constraint,
    ConstraintId,
    Division,
    Equal,
    FixedSide,
    Lock,
    Region,
    Unit,
    constraint_regions,
    region_along,
    region_lock,
    renamed_constraint_boards,
)
from freecad.Shelving.core.record import (
    OpenReport,
    parse_rules,
    region_keys,
    restore_rules,
)
from freecad.Shelving.core.scan import DEFAULT_CLEARANCE_MM, elevation_axes, scan
from freecad.Shelving.core.solver import (
    LayoutSolveError,
    constraint_axis,
    describe_solve_error,
    duplicated_constraint,
    measured_mm,
    redundant_rules,
    size_fixed_by,
    solve,
)
from freecad.Shelving.core.stock import BoardStock, Color, StockGroup, group_stocks
from freecad.Shelving.debug_log import Stopwatch
from freecad.Shelving.editor.elevation import (
    ElevationDirection,
    ElevationFrame,
    FixedChoice,
    elevation_frame,
    fixed_choices,
    run_direction,
)
from freecad.Shelving.editor.history import EditHistory, Schedule

SplitDirection = Literal["horizontal", "vertical"]

# The commands that edit the open unit, in the order the editor's toolbar,
# its right-click menu and the Shelving menu list them, with FreeCAD's
# "Separator" between the add and constraint commands. Here, free of Qt,
# so the headless workbench module can read it.
EDIT_COMMANDS = (
    "Shelving_AddShelf",
    "Shelving_AddDivider",
    "Separator",
    "Shelving_LockWidth",
    "Shelving_LockHeight",
    "Shelving_ConstrainEqualWidth",
    "Shelving_ConstrainEqualHeight",
    "Shelving_ConstrainEvenSpacing",
)


UnitDimension = Literal["width", "depth", "height"]

# A size field: one of the unit's, or the one that opens on an opening's
# dimension.
SizeField = Literal["width", "depth", "height", "opening"]

# FreeCAD's Prop_NoPersist property attribute; setPropertyStatus does not
# accept it by name.
_NO_PERSIST = 32

# The container property each size field binds to, so the field resolves
# names of document values and offers FreeCAD's f(x) dialog. The session
# adds them at open() and removes them at close(), hidden and outside any
# undo step, with FreeCAD's Prop_NoPersist, which keeps a save during the
# edit from writing them into the file (Transient would keep only their
# values out). Every container type can carry them, and none can already
# hold an expression of the user's. One each, so an expression typed into
# one field never shows up in another.
FIELD_PROPERTIES: Mapping[SizeField, str] = {
    "width": "ShelvingFieldWidth",
    "depth": "ShelvingFieldDepth",
    "height": "ShelvingFieldHeight",
    "opening": "ShelvingFieldOpening",
}

_PANEL_REASON = (
    "thin through the unit's depth, so it reads as a back or front panel, "
    "which the layout does not place"
)
_UNPLACED_REASON = "not part of the layout"
_BACK_REASON = "a back panel, so it follows the unit's boards as they move and resize"


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
    # The openings a refused re-solve holds at their minimum, in tree order.
    # Empty for every other refusal.
    region_ids: tuple[str, ...] = ()
    # The constraints a refused re-solve holds responsible, locks included,
    # in the unit's order; a constraint the refused edit was making is named
    # too.
    constraint_ids: tuple[ConstraintId, ...] = ()


@dataclasses.dataclass(frozen=True)
class EditWarning:
    """An accepted session edit that the user should hear something about."""

    # Plain words for the user; names no internal id.
    message: str
    # The regions the warning is about, in tree order.
    region_ids: tuple[str, ...]
    # The constraints the warning is about, locks included, in the unit's
    # order.
    constraint_ids: tuple[ConstraintId, ...] = ()


_REDUNDANT_LOCK = (
    "The outlined locks already fix this opening's size, so its own lock is redundant."
)
_REDUNDANT_CONSTRAINT = (
    "The outlined locks and constraints already fix these sizes, so the new "
    "constraint is redundant."
)
_REDUNDANT_ACTIVATED = (
    "The outlined locks and constraints already fix these sizes, so the "
    "constraint turned on is redundant."
)
_LOCK_STEPS: Mapping[ElevationDirection, str] = {
    "horizontal": "Lock Width",
    "vertical": "Lock Height",
}
_EQUAL_STEPS: Mapping[ElevationDirection, str] = {
    "horizontal": "Equal Width",
    "vertical": "Equal Height",
}
_EVEN_STEPS: Mapping[ElevationDirection, str] = {
    "horizontal": "Even Width",
    "vertical": "Even Height",
}
# Whole sentences per direction, so each translates on its own.
_SELECT_TO_SPLIT = "Select one or more open compartments to split."
_SELECT_TO_LOCK: Mapping[ElevationDirection, str] = {
    "horizontal": "Select one or more openings to lock their widths.",
    "vertical": "Select one or more openings to lock their heights.",
}
_UNIT_SIZE_TO_LOCK: Mapping[ElevationDirection, str] = {
    "horizontal": (
        "A selected opening's width is the unit's width. Set it in the panel's "
        "Width field."
    ),
    "vertical": (
        "A selected opening's height is the unit's height. Set it in the "
        "panel's Height field."
    ),
}
# Worded without a count, so the text reads the same for one constraint as
# for several and stays one string to translate.
_DEACTIVATED_AT_OPEN = (
    "Constraints the boards no longer meet were deactivated. Their icons "
    "carry an X in the corner. They hold nothing, and can be turned back on "
    "or deleted in the Constraints list."
)
_DROPPED_AT_OPEN = (
    "Constraints whose openings or boards are gone were removed from this unit."
)


def open_message(report: OpenReport) -> str | None:
    """The one notification :class:`Session` posts at open for ``report``;
    ``None`` when nothing was deactivated or dropped."""
    lines = []
    if report.deactivated:
        lines.append(_DEACTIVATED_AT_OPEN)
    if report.dropped:
        lines.append(_DROPPED_AT_OPEN)
    return "\n".join(lines) if lines else None


# What a constraint list row holds: a constraint on widths or on heights,
# named for the direction it holds, as the Lock and Equal commands are, or
# one on sizes through the depth, which no command makes but a scan's Lock
# or a stored Equal or Even spacing can hold.
RowKind = Literal[
    "lock_width",
    "lock_height",
    "lock",
    "equal_width",
    "equal_height",
    "equal",
    "even_width",
    "even_height",
    "even_spacing",
]
_RowConstraint = Literal["lock", "equal", "even_spacing"]
_AXIS_ROW_KINDS: Mapping[tuple[_RowConstraint, ElevationDirection], RowKind] = {
    ("lock", "horizontal"): "lock_width",
    ("lock", "vertical"): "lock_height",
    ("equal", "horizontal"): "equal_width",
    ("equal", "vertical"): "equal_height",
    ("even_spacing", "horizontal"): "even_width",
    ("even_spacing", "vertical"): "even_height",
}


@dataclasses.dataclass(frozen=True)
class ConstraintRow:
    """A constraint's row in the constraint list."""

    constraint_id: ConstraintId
    kind: RowKind
    active: bool
    # The first opening's size in the constraint's basis; None while the
    # constraint is deactivated, since it holds no size then.
    size_mm: float | None
    # Whether removing the constraint alone would leave the layout's freedom
    # as it is: redundant_rules in freecad.Shelving.core.solver. A
    # deactivated constraint never is.
    redundant: bool


def _row_kind(constraint: Constraint, unit: Unit, frame: ElevationFrame) -> RowKind:
    kind: _RowConstraint
    if isinstance(constraint, Lock):
        kind = "lock"
    elif isinstance(constraint, Equal):
        kind = "equal"
    else:
        kind = "even_spacing"
    regions = constraint_regions(unit, constraint)
    direction = None if not regions else run_direction(unit, frame, regions[0])
    return kind if direction is None else _AXIS_ROW_KINDS[kind, direction]


def _structure_key(region: Region) -> tuple[object, ...]:
    """What the redundant set and the constraint status depend on in
    ``region``'s subtree: ids, nesting and axes, leaving out every size, so
    a drag that only moves boards keeps the key."""
    if isinstance(region, Division):
        return (
            region.id,
            region.axis,
            tuple(
                item.id if isinstance(item, Board) else _structure_key(item)
                for item in region.items
            ),
        )
    return (region.id,)


def _solve_failure(err: LayoutSolveError) -> EditFailure:
    return EditFailure(
        describe_solve_error(err), err.node_id, err.region_ids, err.constraint_ids
    )


_P = ParamSpec("_P")


def _edit(
    method: Callable[Concatenate[Session, _P], EditFailure | None],
) -> Callable[Concatenate[Session, _P], EditFailure | None]:
    """Mark ``method`` as a session edit: it clears :attr:`Session.flagged`
    before it runs, and a refusal it returns flags the regions and
    constraints it names."""

    @functools.wraps(method)
    def run(self: Session, *args: _P.args, **kwargs: _P.kwargs) -> EditFailure | None:
        self.flagged = ()
        failure = method(self, *args, **kwargs)
        if failure is not None:
            self.flagged = (*failure.region_ids, *failure.constraint_ids)
        return failure

    return run


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


def _regions(region: Region) -> Iterator[Region]:
    """``region`` and every region below it, in tree order."""
    yield region
    if isinstance(region, Division):
        for item in region.items:
            if not isinstance(item, Board):
                yield from _regions(item)


def _duplicated_lock(
    unit: Unit, spaces: Mapping[str, Space], region_id: str
) -> tuple[ConstraintId, ...] | None:
    """:func:`~freecad.Shelving.core.solver.duplicated_constraint` for the
    active Lock on the region ``region_id``; ``None`` too when ``unit``
    holds no such Lock."""
    found = region_lock(unit, region_id)
    if found is None or not found.active:
        return None
    try:
        axis = run_axis(unit, region_id)
    except EditError:
        return None
    return duplicated_constraint(unit, spaces, found.id, axis)


def _boards(region: Region) -> Iterator[Board]:
    """Every board under ``region``, in pre-order."""
    if not isinstance(region, Division):
        return
    for item in region.items:
        if isinstance(item, Board):
            yield item
        else:
            yield from _boards(item)


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
class Untagged:
    """An object in the container that this workbench did not create and
    will not delete unless told to: one it leaves alone, or a back it moves
    with the boards."""

    name: str
    label: str
    # What the layout does with it, in words for the panel.
    reason: str


def _read_unit(
    container: FreeCAD.DocumentObject,
) -> tuple[Unit, Mapping[str, str], OpenReport]:
    """``container`` read fresh and scanned, with its stored constraints and
    unit id reapplied, the reason each part the scan did not place in the
    tree was set aside, keyed by ``Name``, and what reapplying the
    constraints deactivated and dropped.

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
    report = OpenReport()
    if record.rules_json is not None:
        unit, report = restore_rules(
            unit, parse_rules(record.rules_json), DEFAULT_CLEARANCE_MM
        )
    if record.unit_id is not None:
        unit = dataclasses.replace(unit, id=record.unit_id)
    unit = dataclasses.replace(unit, fixed_point=record.fixed_point)
    watch.lap("stored constraints")
    reasons = {entry.name: entry.reason for entry in scan_result.skipped}
    reasons.update((panel.name, _PANEL_REASON) for panel in scan_result.panels)
    reasons.update((back.name, _BACK_REASON) for back in unit.backs)
    return unit, reasons, report


class Session:
    """One elevation-editing session against a selected container."""

    def __init__(self, container: FreeCAD.DocumentObject) -> None:
        """Read and solve ``container``. Raises ``ScanError`` when it does
        not scan and :class:`UnsolvableUnit` when it does not solve."""
        watch = Stopwatch("session")
        self.container = container
        # unit and spaces are the current, already-solved state, replaced
        # wholesale by every accepted edit.
        self.unit, self._set_aside_reasons, report = _read_unit(container)
        # What reading the stored constraints deactivated and dropped, which
        # open() reports once. A reload after an Undo or Redo reports
        # nothing, and opening writes nothing, so the next open reports the
        # same again until an edit writes the record.
        self.open_report = report
        watch.lap("read unit")
        try:
            self.spaces: Mapping[str, Space] = solve(self.unit)
        except LayoutSolveError as err:
            raise UnsolvableUnit(err, self.unit) from err
        watch.lap("solve")
        # Boards and openings, in the order they were selected. A split or
        # merge clears it, since the id it just edited no longer names
        # anything the caller can act on.
        self._selection: tuple[str, ...] = ()
        # Constraints, in the order they were selected; empty whenever
        # _selection is not, so Delete never means both merge and remove.
        self._constraint_selection: tuple[ConstraintId, ...] = ()
        # Untagged objects the tree does not place: what a write leaves
        # alone, and the backs. Before the first write that is every
        # set-aside part that is one of the unit's backs or carries no board
        # properties, since write_container deletes any other tagged one and
        # never deletes a back; after it, exactly what the write reported.
        self.untagged: tuple[Untagged, ...] = self._unplaced(self._set_aside_reasons)
        # The board being dragged and the pointer's offset from its low
        # face along its run's axis, between begin_drag and end_drag.
        self._drag: tuple[str, Axis, float] | None = None
        self._history: EditHistory | None = None
        # Runs after an Undo, a Redo, or a step made elsewhere has been read
        # back.
        self.on_change: Callable[[], None] | None = None
        # Whether an Undo or Redo left no unit to read: the container gone,
        # or no longer scanning or solving. The panel closes then.
        self.lost = False
        # Receives each EditWarning an accepted edit raises.
        self.on_warning: Callable[[EditWarning], None] | None = None
        # The regions and constraints the last edit's refusal or warning
        # names, which the view outlines until the next edit, Undo, Redo or
        # selection change.
        self.flagged: tuple[str, ...] = ()
        # The last redundant set, keyed by what it depends on. A drag
        # refreshes the panel at every step, and the query solves once per
        # lock and constraint on each axis: measured at about 50 ms on a unit
        # of four columns of six openings with 8 locks and 5 constraints,
        # three frames at 60 Hz added to every step without the cache.
        self._redundant: tuple[tuple[object, ...], frozenset[ConstraintId]] | None = (
            None
        )
        # The last constraint status, keyed as the redundant set is: the
        # panel's status line and the view's outlines each read it at every
        # drag step.
        self._status: tuple[tuple[object, ...], ConstraintStatus] | None = None

    def open(self, schedule: Schedule | None = None) -> None:
        """Add the size fields' properties to the container and start
        following the document's undo history. Call once, before any edit.
        ``schedule`` defers the read-back after an Undo or Redo until
        FreeCAD has finished it; with none, :meth:`settle` does the
        read-back.

        A document created by ``FreeCAD.newDocument`` (as every
        ``freecadcmd`` script and this workbench's own smoke does) starts
        with ``UndoMode`` off, unlike a document created through the GUI,
        and records no step at all. Setting it here gives every document
        the same history.
        """
        doc = self.container.Document
        doc.UndoMode = 1
        for name in FIELD_PROPERTIES.values():
            if not hasattr(self.container, name):
                self.container.addProperty(
                    "App::PropertyLength", name, "Shelving", "", _NO_PERSIST
                )
                self.container.setPropertyStatus(name, "Hidden")
        self._history = EditHistory(doc, self, schedule or (lambda _settle: None))
        message = open_message(self.open_report)
        if message is not None:
            refusals.report_warning(message)

    def settle(self) -> None:
        """Read a pending Undo or Redo back into this session now. Every
        edit calls this first, so none is computed from the unit as it was
        before an Undo whose read-back has not run yet."""
        if self._history is not None:
            self._history.settle()

    def close(self) -> None:
        """End this session, leaving each of its edits as its own undo step
        and removing the size fields' properties. Safe to call twice."""
        self._drag = None
        if self._history is not None:
            self._history.finish()
        try:
            for name in FIELD_PROPERTIES.values():
                if hasattr(self.container, name):
                    self.container.removeProperty(name)
        except ReferenceError:
            # The container was destroyed, as removing it outside any undo
            # step or closing its document does, and its properties with it.
            pass

    @property
    def dragging(self) -> bool:
        """Whether a drag begun with :meth:`begin_drag` is still going: an
        Undo during it ends it."""
        return self._drag is not None

    # What EditHistory needs; see HistoryOwner.

    def reload(self) -> None:
        """Rescan the container, keeping each selected node that still exists
        selected, then tell :attr:`on_change`. Sets :attr:`lost` instead of
        rescanning when the container no longer reads."""
        try:
            unit, reasons, _report = _read_unit(self.container)
            spaces = solve(unit)
        except Exception:  # noqa: BLE001 - an Undo can leave anything behind
            self.lost = True
            self._drag = None
            if self.on_change is not None:
                self.on_change()
            return
        # A board keeps its id, its object's name, across a rescan; a
        # region is found again by the boards bounding it.
        old_keys = {region_id: key for key, region_id in region_keys(self.unit).items()}
        new_ids = region_keys(unit)
        selected: list[str] = []
        for node_id in self._selection:
            if node_id in spaces:
                selected.append(node_id)
                continue
            key = old_keys.get(node_id)
            found = None if key is None else new_ids.get(key)
            if found is not None:
                selected.append(found)
        self.unit = unit
        self.spaces = spaces
        self._set_aside_reasons = reasons
        self.untagged = self._unplaced(reasons)
        self._selection = tuple(selected)
        # A rescan mints fresh constraint ids, and the steps that change
        # constraints clear this selection anyway.
        self._constraint_selection = ()
        self.flagged = ()
        if self.on_change is not None:
            self.on_change()

    def step_interrupted(self) -> None:
        self._drag = None

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

    @property
    def selected_id(self) -> str | None:
        """The single selected region or board; ``None`` when nothing is
        selected and when several items are."""
        return self._selection[0] if len(self._selection) == 1 else None

    @property
    def selected_items(self) -> tuple[str, ...]:
        """Every selected board and opening, in the order they were
        selected."""
        return self._selection

    @property
    def selected_boards(self) -> tuple[str, ...]:
        """Every selected board, in the order they were selected."""
        boards = {board.id for board in _boards(self.unit.root)}
        return tuple(node_id for node_id in self._selection if node_id in boards)

    @property
    def selected_constraints(self) -> tuple[ConstraintId, ...]:
        """Every selected constraint, in the order they were selected; empty
        while any board or opening is selected."""
        return self._constraint_selection

    @property
    def constraints(self) -> tuple[Constraint, ...]:
        """The unit's constraints, active and deactivated, in the order they
        were made."""
        return self.unit.constraints

    def constraint_rows(self) -> tuple[ConstraintRow, ...]:
        """The constraint list's rows: every constraint, locks included,
        active or deactivated, in the order they were made."""
        redundant = self._redundant_rules()
        frame = elevation_frame(self.unit)
        rows: list[ConstraintRow] = []
        for constraint in self.unit.constraints:
            regions = constraint_regions(self.unit, constraint)
            size_mm = None
            if isinstance(constraint, Lock) and constraint.active:
                # As the opening's dimension shows it, so the two agree.
                size_mm = measure(self.unit, constraint.region_id, self.spaces).size_mm
            elif constraint.active and regions:
                size_mm = measured_mm(
                    self.unit, self.spaces, regions[0], constraint.basis
                )
            rows.append(
                ConstraintRow(
                    constraint_id=constraint.id,
                    kind=_row_kind(constraint, self.unit, frame),
                    active=constraint.active,
                    size_mm=size_mm,
                    redundant=constraint.id in redundant,
                )
            )
        return tuple(rows)

    def _freedom_key(self) -> tuple[object, ...]:
        return (
            _structure_key(self.unit.root),
            self.unit.constraints,
            self.unit.fixed_point,
        )

    def _redundant_rules(self) -> frozenset[ConstraintId]:
        key = self._freedom_key()
        if self._redundant is None or self._redundant[0] != key:
            self._redundant = (key, redundant_rules(self.unit, self.spaces))
        return self._redundant[1]

    def constraint_status(self) -> ConstraintStatus:
        """:func:`~freecad.Shelving.core.edit.constraint_status` for this
        session's unit: the degrees of freedom the panel reports and the
        fully constrained boards the view outlines."""
        key = self._freedom_key()
        if self._status is None or self._status[0] != key:
            self._status = (key, constraint_status(self.unit))
        return self._status[1]

    def constraint_regions(self, constraint_id: ConstraintId) -> tuple[str, ...]:
        """The openings the constraint ``constraint_id`` holds, empty when
        it names none of this unit's constraints."""
        for constraint in self.unit.constraints:
            if constraint.id == constraint_id:
                return constraint_regions(self.unit, constraint)
        return ()

    def select(self, node_id: str | None) -> None:
        """Make ``node_id`` the single selection, or clear it for ``None``."""
        self._set_selection(() if node_id is None else (node_id,))

    def select_boards(self, board_ids: Sequence[str]) -> None:
        """Select the boards ``board_ids`` names, each once; one board is a
        single selection, as :meth:`select` makes it."""
        self._set_selection(tuple(dict.fromkeys(board_ids)))

    def select_items(self, node_ids: Sequence[str]) -> None:
        """Select the boards and openings ``node_ids`` names, each once, in
        that order, dropping any constraint selection."""
        self._set_selection(tuple(dict.fromkeys(node_ids)))

    def select_constraints(self, constraint_ids: Sequence[ConstraintId]) -> None:
        """Select the constraints ``constraint_ids`` names, each once, in
        that order, dropping the board and opening selection. An id naming
        no constraint of the unit is left out."""
        known = {constraint.id for constraint in self.unit.constraints}
        selection = tuple(c for c in dict.fromkeys(constraint_ids) if c in known)
        if selection != self._constraint_selection or self._selection:
            self.flagged = ()
        self._selection = ()
        self._constraint_selection = selection

    def _set_selection(self, selection: tuple[str, ...]) -> None:
        if selection != self._selection or self._constraint_selection:
            self.flagged = ()
        self._selection = selection
        self._constraint_selection = ()

    def can_merge(self) -> bool:
        """Whether the current selection is a ``Board``: the only kind of
        node :meth:`merge` acts on. ``True`` does not promise :meth:`merge`
        succeeds: :func:`~freecad.Shelving.core.edit.merge_at` refuses by
        name when the board's neighbors do not permit a merge."""
        if self.selected_id is None:
            return False
        node = _find_node(self.unit.root, self.selected_id)
        return isinstance(node, Board)

    def _unplaced(self, reasons: Mapping[str, str]) -> tuple[Untagged, ...]:
        """Each part ``reasons`` names that is a back of ``self.unit`` or
        carries no board properties: what the next write keeps, since
        write_container deletes any other tagged one."""
        doc = self.container.Document
        backs = {back.name for back in self.unit.backs}
        return tuple(
            self._untagged(name)
            for name in sorted(reasons)
            if name in backs or not properties.has_board_properties(doc.getObject(name))
        )

    def _label(self, name: str) -> str:
        obj = self.container.Document.getObject(name)
        return obj.Label if obj is not None else name

    def _untagged(self, name: str) -> Untagged:
        return Untagged(
            name=name,
            label=self._label(name),
            reason=self._set_aside_reasons.get(name, _UNPLACED_REASON),
        )

    def _apply(self, candidate: Unit, select: Sequence[str] = ()) -> EditFailure | None:
        """Adopt ``candidate`` as this session's state and write it to the
        document, selecting ``select``, or return an :class:`EditFailure`
        when it fails to solve, leaving the session and document untouched.
        An active constraint ``candidate`` misses, as one the boards missed
        within the clearance at open, is met first, so every edit leaves
        the active constraints exact."""
        try:
            candidate = settle_constraints(candidate)
            spaces: Mapping[str, Space] = solve(candidate)
            # write_container solves again before writing any board, so a
            # LayoutSolveError from either call means nothing was written.
            result = write_container(self.container, candidate)
        except LayoutSolveError as err:
            return _solve_failure(err)
        except BackFitError as err:
            return EditFailure(
                f"{self._label(err.name)} follows the unit's boards, and this "
                "edit would leave it no width or height.",
                err.name,
            )
        if result.id_renames:
            # A board split created carries a fresh new_id(), not yet a
            # document object Name; without adopting the real Name here,
            # the next _apply's write_container call would fail to match
            # this board by Name and delete and recreate it instead
            # (bug-008).
            candidate = dataclasses.replace(
                candidate,
                root=renamed_board_ids(candidate.root, result.id_renames),
                backs=renamed_back_boards(candidate.backs, result.id_renames),
                constraints=renamed_constraint_boards(
                    candidate.constraints, result.id_renames
                ),
            )
            spaces = _renamed_spaces(spaces, result.id_renames)
        self.unit = candidate
        self.spaces = spaces
        self._selection = tuple(select)
        known = {constraint.id for constraint in candidate.constraints}
        self._constraint_selection = tuple(
            c for c in self._constraint_selection if c in known and not select
        )
        self.untagged = tuple(
            self._untagged(name) for name in sorted(result.left_alone + result.backs)
        )
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

    def _direction_axis(self, direction: ElevationDirection) -> Axis:
        """The model axis the elevation's ``direction`` lies along. Raises
        ``ValueError`` on the same terms as :meth:`_elevation_axes`."""
        horizontal, vertical = self._elevation_axes()
        return horizontal if direction == "horizontal" else vertical

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

    def size_fixed_by(
        self, dimension: UnitDimension
    ) -> tuple[ConstraintId, ...] | None:
        """The constraints, locks included, that determine the unit's size
        along ``dimension``, making it a reference that :meth:`resize`
        refuses to change; ``None`` when the size is free, as the depth
        always is."""
        return size_fixed_by(self.unit, self.spaces, self._unit_axis(dimension))

    def unit_dimension_mm(self, dimension: UnitDimension) -> float:
        """The unit's outer size along ``dimension``, as scanned or last set:
        a part the scan set aside, such as a back panel, does not count."""
        size_mm = self.unit.size_mm
        return (size_mm.x_mm, size_mm.y_mm, size_mm.z_mm)[
            self._unit_axis(dimension).component_index
        ]

    @_edit
    def resize(self, dimension: UnitDimension, size_mm: float) -> EditFailure | None:
        """Set the unit's outer size along ``dimension``, keeping its fixed
        point where it is and the selection as it was. Returns ``None`` on
        success or an :class:`EditFailure` on refusal, which changes
        nothing; a new size along a dimension :meth:`size_fixed_by` reports
        is refused, naming the locks that fix it."""
        self.settle()
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
        except LayoutSolveError as err:
            return _solve_failure(err)
        return self._step(
            "Resize Unit", lambda: self._apply(candidate, select=self._selection)
        )

    def fixed_choices(
        self, dimension: UnitDimension
    ) -> tuple[FixedChoice, FixedChoice, FixedChoice]:
        """:func:`~freecad.Shelving.editor.elevation.fixed_choices` for the
        model axis ``dimension`` names."""
        return fixed_choices(self.unit, self._unit_axis(dimension))

    def fixed_side(self, dimension: UnitDimension) -> FixedSide:
        """The side of the unit that stays put when its size along
        ``dimension`` changes."""
        return self.unit.fixed_point.side(self._unit_axis(dimension))

    @_edit
    def set_fixed_side(
        self, dimension: UnitDimension, side: FixedSide
    ) -> EditFailure | None:
        """Keep ``side`` put when the unit's size along ``dimension``
        changes, as one undo step that moves no board and keeps the
        selection. Adds no step when ``side`` is already the fixed one."""
        self.settle()
        axis = self._unit_axis(dimension)
        fixed = self.unit.fixed_point
        if fixed.side(axis) == side:
            return None
        candidate = dataclasses.replace(
            self.unit, fixed_point=fixed.with_side(axis, side)
        )
        return self._step(
            "Set Fixed Point", lambda: self._apply(candidate, select=self._selection)
        )

    @_edit
    def split(self, direction: SplitDirection) -> EditFailure | None:
        """Split every selected ``Bay`` in two at its middle, as one undo
        step, each with a board that copies its stock from
        :func:`~freecad.Shelving.core.stock.source_board`'s choice.

        ``direction`` names an elevation axis, not a model axis:
        "horizontal" divides a bay left and right behind a vertical
        divider, "vertical" stacks it top and bottom behind a horizontal
        shelf, whichever model axis the unit's depth runs along. Returns
        ``None`` on success, which clears the selection, or an
        :class:`EditFailure`, splitting none, when nothing is selected, any
        selected item is not a bay, or any bay is refused."""
        self.settle()
        selection = self._selection
        root = self.unit.root
        not_bay = next(
            (n for n in selection if not isinstance(_find_node(root, n), Bay)), None
        )
        if not selection or not_bay is not None:
            return EditFailure(_SELECT_TO_SPLIT, not_bay)
        horizontal, vertical = self._elevation_axes()
        axis = horizontal if direction == "horizontal" else vertical
        candidate = self.unit
        try:
            for bay_id in selection:
                candidate = split_region(candidate, bay_id, axis)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        name = "Add Divider" if direction == "horizontal" else "Add Shelf"
        return self._step(name, lambda: self._apply(candidate))

    @_edit
    def delete_boards(self) -> EditFailure | None:
        """Remove every selected board as :meth:`merge` removes one, as one
        undo step, clearing the selection. Returns an :class:`EditFailure`,
        removing none, when no board is selected or any one is refused."""
        self.settle()
        boards = self.selected_boards
        if not boards:
            return EditFailure("select the boards to delete", None)
        try:
            candidate = remove_boards(self.unit, boards)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        return self._step("Delete Boards", lambda: self._apply(candidate))

    def stock_groups(self) -> Sequence[StockGroup]:
        """The unit's boards grouped by stock, as
        :func:`~freecad.Shelving.core.stock.group_stocks` orders them, from
        their thickness, ``ShapeMaterial`` name and most common face color.
        Without a GUI no board's color is known, so only thickness and
        material tell groups apart. An object the layout leaves alone is in
        no group."""
        doc = self.container.Document
        records: list[BoardStock] = []
        for board in _boards(self.unit.root):
            obj = doc.getObject(board.id)
            records.append(
                BoardStock(
                    board_id=board.id,
                    thickness_mm=board.thickness_mm,
                    material=None
                    if obj is None
                    else properties.read_material_name(obj),
                    color=None if obj is None else properties.dominant_color(obj),
                )
            )
        return group_stocks(records)

    @_edit
    def swap_stock(
        self,
        thickness_mm: float | None = None,
        material_uuid: str | None = None,
        color: Color | None = None,
    ) -> EditFailure | None:
        """Give every selected board whichever of ``thickness_mm``, the
        library material ``material_uuid`` and ``color`` is set, as one undo
        step that keeps the selection.

        The thickness goes through
        :func:`~freecad.Shelving.core.edit.set_thickness` and the write path.
        The material becomes each board's ``ShapeMaterial``, and with a GUI
        every face is repainted in ``color``, or in the material's diffuse
        color when ``color`` is ``None``. Grain is never touched. Returns
        ``None``, adding no step, when none of the three is set; an
        :class:`EditFailure`, changing nothing, when no board is selected,
        the library holds no such material, or the thickness is refused or
        does not fit.
        """
        self.settle()
        if thickness_mm is None and material_uuid is None and color is None:
            return None
        boards = self.selected_boards
        if not boards:
            return EditFailure("select the boards whose stock to change", None)
        material = None
        if material_uuid is not None:
            material = properties.library_material(material_uuid)
            if material is None:
                return EditFailure(
                    "FreeCAD's material library has no such material", None
                )
        candidate: Unit | None = None
        if thickness_mm is not None:
            try:
                candidate = set_thickness(self.unit, boards, thickness_mm)
            except EditError as err:
                return EditFailure(str(err), err.node_id)
            except LayoutSolveError as err:
                return _solve_failure(err)
        paint_rgb = color
        if paint_rgb is None and material is not None:
            paint_rgb = properties.material_color(material)
        selection = self._selection
        doc = self.container.Document

        def swap() -> EditFailure | None:
            if candidate is not None:
                failure = self._apply(candidate, select=selection)
                if failure is not None:
                    return failure
            for board_id in boards:
                obj = doc.getObject(board_id)
                if obj is None:
                    continue
                if material is not None:
                    properties.write_material(obj, material)
                if paint_rgb is not None:
                    properties.paint(obj, paint_rgb)
            return None

        return self._step("Change Stock", swap)

    @_edit
    def merge(self) -> EditFailure | None:
        """Remove the selected ``Board`` and merge its neighboring regions.
        Returns ``None`` on success, which clears the selection, or an
        :class:`EditFailure` on refusal, which changes nothing."""
        self.settle()
        if self.selected_id is None:
            return EditFailure("select a board to merge", None)
        try:
            candidate = merge_at(self.unit, self.selected_id)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        return self._step("Delete Board", lambda: self._apply(candidate))

    def selected_measurement(self) -> Measurement | None:
        """The selected region's :class:`~freecad.Shelving.core.edit.Measurement`,
        or for a lone selected constraint its first opening's, in the
        constraint's basis and with ``spacing_mm`` ``None`` unless every
        opening it names has a board after it. ``None`` when the selection
        is nothing, a board, the whole unit, several constraints, or a
        constraint holding no opening: nothing a size applies to."""
        constraint = self._selected_constraint()
        if constraint is not None:
            return self._constraint_measurement(constraint)
        if self.selected_id is None:
            return None
        try:
            return measure(self.unit, self.selected_id, self.spaces)
        except EditError:
            return None

    def _selected_constraint(self) -> Constraint | None:
        """The one selected constraint; ``None`` for any other selection."""
        if len(self._constraint_selection) != 1:
            return None
        (selected,) = self._constraint_selection
        return next((c for c in self.unit.constraints if c.id == selected), None)

    def _constraint_measurement(self, constraint: Constraint) -> Measurement | None:
        regions = constraint_regions(self.unit, constraint)
        if not regions:
            return None
        measurements = [measure(self.unit, r, self.spaces) for r in regions]
        first = measurements[0]
        spaced = all(m.spacing_mm is not None for m in measurements)
        return dataclasses.replace(
            first,
            basis=constraint.basis,
            spacing_mm=first.spacing_mm if spaced else None,
        )

    @_edit
    def set_size(self, size_mm: float) -> EditFailure | None:
        """Fix the selected region at ``size_mm``, a value FreeCAD's own
        quantity widget already resolved, in the basis the region already
        measures in. The selection is kept. Returns ``None`` on success or
        an :class:`EditFailure` on refusal, which changes nothing."""
        self.settle()
        if self.selected_id is None:
            return EditFailure("select a region to size", None)
        region_id = self.selected_id
        try:
            basis = measure(self.unit, region_id, self.spaces).basis
            candidate = set_size(self.unit, region_id, size_mm, basis)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        return self._locking_step(
            "Set Size", candidate, [region_id], select=(region_id,)
        )

    @_edit
    def set_basis(self, basis: Basis) -> EditFailure | None:
        """Change what the selected region's size measures, moving nothing,
        or what a lone selected constraint's sizes measure, solving it again
        when it is active. One undo step that keeps the selection. Returns
        ``None`` on success or an :class:`EditFailure` on refusal, which
        changes nothing, a constraint's conflict included."""
        self.settle()
        constraint = self._selected_constraint()
        if constraint is not None:
            try:
                candidate = set_constraint_basis(self.unit, constraint.id, basis)
            except EditError as err:
                return EditFailure(str(err), err.node_id)
            except LayoutSolveError as err:
                return _solve_failure(err)
            if candidate is self.unit:
                return None
            return self._step(
                "Change What a Size Measures", lambda: self._apply(candidate)
            )
        if self.selected_id is None:
            return EditFailure("select a region to measure", None)
        region_id = self.selected_id
        try:
            candidate = set_basis(self.unit, region_id, basis)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._locking_step(
            "Change What a Size Measures", candidate, [region_id], select=(region_id,)
        )

    @_edit
    def set_lock(self, region_id: str, locked: bool) -> EditFailure | None:
        """When ``locked``, lock ``region_id``: turn its deactivated Lock on
        or add one. Otherwise delete its active Lock. One undo step that
        moves nothing and keeps the selection. Returns an
        :class:`EditFailure` on refusal, such as for an id that names no
        region, leaving the session and document untouched."""
        self.settle()
        name = "Lock Opening" if locked else "Unlock Opening"
        try:
            candidate = (lock if locked else unlock)(self.unit, region_id)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._locking_step(
            name, candidate, [region_id] if locked else [], select=self._selection
        )

    @_edit
    def lock_axis(self, direction: ElevationDirection) -> EditFailure | None:
        """Lock, at its current size, the region each selected opening's
        size along the elevation's ``direction`` belongs to, as
        :func:`~freecad.Shelving.core.layout.region_along` finds it:
        openings that resolve to one region make one Lock, a region whose
        Lock is active is left alone, and a deactivated Lock is turned on.
        One undo step that moves nothing and keeps the selection, adding no
        step when every region is already locked; a redundant Lock is kept
        with a warning through :attr:`on_warning`. Returns an
        :class:`EditFailure`, changing nothing, when nothing or a board is
        selected, or when any selected opening's size along ``direction``
        is the unit's own."""
        self.settle()
        selection = self._selection
        boards = {board.id for board in _boards(self.unit.root)}
        if not selection or any(node_id in boards for node_id in selection):
            first = next((n for n in selection if n in boards), None)
            return EditFailure(_SELECT_TO_LOCK[direction], first)
        axis = self._direction_axis(direction)
        targets: dict[str, None] = {}
        for node_id in selection:
            target = region_along(self.unit, node_id, axis)
            if target is None:
                return EditFailure(_UNIT_SIZE_TO_LOCK[direction], node_id)
            targets[target] = None
        candidate = self.unit
        for target in targets:
            candidate = lock(candidate, target)
        if candidate is self.unit:
            return None
        return self._locking_step(
            _LOCK_STEPS[direction], candidate, list(targets), select=selection
        )

    def _locking_step(
        self,
        name: str,
        candidate: Unit,
        locking: Sequence[str],
        select: Sequence[str],
    ) -> EditFailure | None:
        """Apply ``candidate`` as the undo step ``name``, selecting
        ``select``, then warn through :attr:`on_warning` and flag what it
        duplicates when the Lock on a region ``locking`` names is redundant
        after the step and was not before, as the Sketcher accepts and flags
        a redundant constraint."""
        before_unit, before_spaces = self.unit, self.spaces
        failure = self._step(name, lambda: self._apply(candidate, select=select))
        if failure is not None:
            return failure
        duplicated: dict[ConstraintId, None] = {}
        for region_id in locking:
            found = _duplicated_lock(self.unit, self.spaces, region_id)
            if found and not _duplicated_lock(before_unit, before_spaces, region_id):
                duplicated.update(dict.fromkeys(found))
        if duplicated:
            self._warn(_REDUNDANT_LOCK, duplicated)
        return None

    def _warn(self, message: str, ids: Collection[str]) -> None:
        """Flag ``ids``, regions and constraints, and send the warning
        ``message`` naming them through :attr:`on_warning`."""
        regions = _regions(self.unit.root)
        order = {node.id: index for index, node in enumerate(regions)}
        constraint_order = {c.id: index for index, c in enumerate(self.constraints)}
        warning = EditWarning(
            message,
            tuple(sorted((i for i in ids if i in order), key=order.__getitem__)),
            tuple(
                ConstraintId(i)
                for i in sorted(
                    (i for i in ids if i in constraint_order),
                    key=constraint_order.__getitem__,
                )
            ),
        )
        self.flagged = (*warning.region_ids, *warning.constraint_ids)
        if self.on_warning is not None:
            self.on_warning(warning)

    def held_by(self, board_id: str) -> Held | None:
        """:func:`~freecad.Shelving.core.edit.held_by` for this session's
        unit: the Locks to delete so a drag may move ``board_id`` and the
        other constraints that hold it whatever is unlocked, free when it
        may move, ``None`` when the boards alone hold it."""
        return held_by(self.unit, board_id)

    @_edit
    def equal_axis(self, direction: ElevationDirection) -> EditFailure | None:
        """Make equal the sizes along the elevation's ``direction`` of the
        selected openings, each pick resolved as
        :func:`~freecad.Shelving.core.edit.add_equal_along` resolves it and
        made equal to the next in selection order, as one undo step that
        clears the selection. A new constraint the locks and constraints
        already imply is kept, with a warning through :attr:`on_warning`
        that flags what it repeats. Returns an :class:`EditFailure`,
        changing nothing, for a selection ``add_equal_along`` refuses or
        one that conflicts."""
        self.settle()
        try:
            candidate = add_equal_along(
                self.unit, self._selection, self._direction_axis(direction)
            )
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        return self._constraining_step(_EQUAL_STEPS[direction], candidate)

    @_edit
    def even_spacing(self) -> EditFailure | None:
        """Space evenly the openings between the two selected boards, or
        those of the run the selected openings part ways in, as
        :func:`~freecad.Shelving.core.edit.add_even_spacing` resolves them,
        as one undo step that clears the selection, warning as
        :meth:`equal_axis` does. The step is named Even Width or Even
        Height for the direction the new spacing holds, matching its list
        row. Returns an :class:`EditFailure`, changing nothing, for a
        selection ``add_even_spacing`` refuses or one that conflicts."""
        self.settle()
        try:
            candidate = add_even_spacing(self.unit, self._selection)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        axis = constraint_axis(candidate, candidate.constraints[-1])
        direction: ElevationDirection = (
            "horizontal" if axis is self._direction_axis("horizontal") else "vertical"
        )
        return self._constraining_step(_EVEN_STEPS[direction], candidate)

    def _constraining_step(self, name: str, candidate: Unit) -> EditFailure | None:
        """Apply ``candidate``, which adds constraints, as the undo step
        ``name``, then warn about each new one that is redundant."""
        before = {constraint.id for constraint in self.unit.constraints}
        failure = self._step(name, lambda: self._apply(candidate))
        if failure is not None:
            return failure
        duplicated: dict[ConstraintId, None] = {}
        for constraint in self.unit.constraints:
            if constraint.id in before:
                continue
            axis = constraint_axis(self.unit, constraint)
            if axis is None:
                continue
            found = duplicated_constraint(self.unit, self.spaces, constraint.id, axis)
            if found:
                duplicated.update(dict.fromkeys(found))
                duplicated[constraint.id] = None
        if duplicated:
            self._warn(_REDUNDANT_CONSTRAINT, duplicated)
        return None

    @_edit
    def set_constraint_active(
        self, constraint_id: ConstraintId, active: bool
    ) -> EditFailure | None:
        """Activate or deactivate the constraint ``constraint_id`` as one
        undo step that keeps the selection; adds no step when it already is.
        Deactivating moves nothing; activating solves it in, and warns
        through :attr:`on_warning` when it is redundant. Returns an
        :class:`EditFailure`, changing nothing, for an unknown id or an
        activation that conflicts, naming the conflict's regions and
        constraints."""
        self.settle()
        try:
            candidate = set_constraint_active(self.unit, constraint_id, active)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        if candidate is self.unit:
            return None
        name = "Activate Constraint" if active else "Deactivate Constraint"
        failure = self._step(name, lambda: self._apply(candidate))
        if failure is not None or not active:
            return failure
        constraint = next(c for c in self.unit.constraints if c.id == constraint_id)
        axis = constraint_axis(self.unit, constraint)
        found = (
            None
            if axis is None
            else duplicated_constraint(self.unit, self.spaces, constraint_id, axis)
        )
        if found:
            self._warn(_REDUNDANT_ACTIVATED, (*found, constraint_id))
        return None

    @_edit
    def delete_constraint(self, constraint_id: ConstraintId) -> EditFailure | None:
        """Remove the constraint ``constraint_id``, active or deactivated, as
        one undo step that moves no board. Returns an :class:`EditFailure`,
        changing nothing, when it names no constraint of the unit."""
        self.settle()
        try:
            candidate = remove_constraints(self.unit, (constraint_id,))
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._step("Delete Constraint", lambda: self._apply(candidate))

    @_edit
    def delete_deactivated(self) -> EditFailure | None:
        """Remove every deactivated constraint as one undo step that moves no
        board. Returns an :class:`EditFailure`, adding no step, when none is
        deactivated."""
        self.settle()
        if all(constraint.active for constraint in self.unit.constraints):
            return EditFailure("no constraint is deactivated", None)
        candidate = remove_deactivated(self.unit)
        return self._step(
            "Delete Deactivated Constraints", lambda: self._apply(candidate)
        )

    @_edit
    def delete_constraints(self) -> EditFailure | None:
        """Remove every selected constraint, active or deactivated, as one
        undo step that moves no board and clears the selection. Returns an
        :class:`EditFailure`, removing none, when no constraint is
        selected."""
        self.settle()
        selected = self._constraint_selection
        if not selected:
            return EditFailure("select the constraints to delete", None)
        try:
            candidate = remove_constraints(self.unit, selected)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        return self._step("Delete Constraints", lambda: self._apply(candidate))

    @_edit
    def begin_drag(self, board_id: str, grab_mm: Vec3) -> EditFailure | None:
        """Start dragging ``board_id``, grabbed at the unit-frame point
        ``grab_mm``; each :meth:`drag_to` keeps that point under the pointer.
        Leaves the selection alone, so a press that never moves still
        selects the board. Returns an :class:`EditFailure`, starting no
        drag, when a drag may not move the board: a Lock holds it, or no
        unlock would free it."""
        self.settle()
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

    @_edit
    def drag_to(self, pointer_mm: Vec3) -> EditFailure | None:
        """Move the dragged board so its grab point follows ``pointer_mm``
        along its run's axis, re-solving and writing the boards, and select
        the board. Boards joined to it through locked regions move with it,
        and an opening it narrows to the minimum pushes the boards beyond.
        Returns an :class:`EditFailure`, leaving the last good state, when
        this move is refused or would not solve, or no drag is in
        progress."""
        if self._drag is None:
            return EditFailure("no board is being dragged", None)
        board_id, axis, grab_offset_mm = self._drag
        low_face_mm = pointer_mm.component_mm(axis.component_index) - grab_offset_mm
        try:
            candidate = move_board(self.unit, board_id, low_face_mm)
        except EditError as err:
            return EditFailure(str(err), err.node_id)
        except LayoutSolveError as err:
            return _solve_failure(err)
        return self._apply(candidate, select=(board_id,))

    def end_drag(self) -> None:
        """End the drag, closing its undo step; a drag that moved nothing
        leaves none."""
        self._drag = None
        if self._history is not None and self._history.step_open:
            self._history.end(keep=True)

    @_edit
    def delete_untagged(self, names: Collection[str]) -> EditFailure | None:
        """Delete the listed :attr:`untagged` objects as one undo step, so
        Undo restores them. Refuses, deleting nothing,
        when any name is not currently listed."""
        self.settle()
        listed = {entry.name for entry in self.untagged}
        unknown = sorted(set(names) - listed)
        if unknown:
            return EditFailure(
                "not listed among the objects this workbench did not create: "
                f"{', '.join(unknown)}",
                unknown[0],
            )
        doc = self.container.Document

        def delete() -> EditFailure | None:
            for name in names:
                doc.removeObject(name)
            self.untagged = tuple(e for e in self.untagged if e.name not in names)
            self.unit = dataclasses.replace(
                self.unit,
                backs=tuple(b for b in self.unit.backs if b.name not in names),
            )
            return None

        return self._step("Delete Objects", delete)
