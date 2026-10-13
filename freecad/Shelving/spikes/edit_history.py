"""Spike: Undo and Redo inside an editing session, through FreeCAD's own.

Std_Undo reaches the document from its shortcut, the Edit menu, the toolbar
and its drop-down list, none of which a task panel can intercept, and with
the session's one transaction still open it commits that transaction and
undoes it whole. So each edit here is its own transaction, and the session
reads the unit back from the document after every Undo or Redo. OK then
replaces the session's steps with one, keeping the main editor's one
history step per session.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Protocol, cast

import FreeCAD
from PySide6 import QtCore

from freecad.Shelving import properties
from freecad.Shelving.core.solver import LayoutSolveError, describe_solve_error, solve
from freecad.Shelving.editor.session import (
    EditFailure,
    Session,
    _find_node,
    _read_unit,
)
from freecad.Shelving.spikes.spike_log import log

_PAST_START = "Nothing left to undo in this edit"


class _Placed(Protocol):
    Placement: FreeCAD.Placement


class EditHistory:
    """The document transactions of one editing session over ``session``,
    which must have just been opened. ``on_change`` runs after every Undo or
    Redo has been read back into the session, with the refusal to show, if
    any."""

    def __init__(
        self, session: Session, on_change: Callable[[EditFailure | None], None]
    ) -> None:
        self._session = session
        self._on_change = on_change
        self._doc = session.container.Document
        # Session.open's transaction holds only the probe's creation.
        # Committed, it is the step an Undo past this session's first edit
        # removes, which takes back nothing the user made and which the
        # observer at once redoes.
        self._doc.commitTransaction()
        self._start_count = self._doc.UndoCount
        probe = session.probe
        self._probe_name = probe.Name if probe is not None else None
        self._own_moves = False
        self._read_back_queued = False
        self._finished = False
        FreeCAD.addDocumentObserver(self)
        log(f"history: start at undo count {self._start_count}")

    @contextmanager
    def step(self, name: str) -> Iterator[None]:
        """One history step named ``name`` around an edit. An edit that
        refuses writes nothing, and FreeCAD drops an empty transaction."""
        self.begin(name)
        try:
            yield
        except BaseException:
            self._doc.abortTransaction()
            raise
        self.end()

    def begin(self, name: str) -> None:
        """Open the step a drag fills, for :meth:`end` to close."""
        self._doc.openTransaction(name)

    def end(self) -> None:
        self._doc.commitTransaction()
        log(f"history: undo names {self._doc.UndoNames}")

    def finish(self, keep: bool) -> None:
        """Undo every step of the session, then write its final unit back as
        one step named as the main editor's when ``keep`` and anything
        changed, or clear the Redo list otherwise, so Redo cannot replay a
        cancelled edit. Undoing a step the user made in another part of
        FreeCAD during the session drops it as well."""
        if self._finished:
            return
        self._finished = True
        FreeCAD.removeDocumentObserver(self)
        doc = self._doc
        session = self._session
        final = session.unit
        changed = doc.UndoCount > self._start_count
        steps = doc.UndoCount - self._start_count + 1
        log(f"history: finish keep={keep}, undoing {steps} of {doc.UndoNames}")
        self._own_moves = True
        try:
            for _ in range(steps):
                doc.undo()
        finally:
            self._own_moves = False
        session.probe = None
        if keep and changed:
            doc.openTransaction("Edit Shelving Unit")
            # The unit solved when the session reached it, so this writes.
            failure = session._apply(final)
            doc.commitTransaction()
            if failure is not None:
                log(f"history: final write refused: {failure.message}")
        else:
            container = cast("_Placed", session.container)
            # FreeCAD clears the Redo list once a transaction records any
            # change, even one it then aborts. Setting Label to itself
            # records nothing.
            doc.openTransaction("Clear redo")
            container.Placement = container.Placement
            doc.abortTransaction()
        log(f"history: finished, undo names {doc.UndoNames}, redo {doc.RedoNames}")

    # FreeCAD's document observer

    def slotUndoDocument(self, doc: FreeCAD.Document) -> None:
        self._moved(doc, "undo")

    def slotRedoDocument(self, doc: FreeCAD.Document) -> None:
        self._moved(doc, "redo")

    def _moved(self, doc: FreeCAD.Document, kind: str) -> None:
        if doc is not self._doc or self._own_moves or self._finished:
            return
        log(f"history: {kind} to undo count {doc.UndoCount}")
        if not self._read_back_queued:
            self._read_back_queued = True
            # FreeCAD signals from inside its own undo loop, which the
            # drop-down list runs once per step.
            QtCore.QTimer.singleShot(0, self._read_back)

    def _read_back(self) -> None:
        self._read_back_queued = False
        if self._finished:
            return
        doc = self._doc
        failure: EditFailure | None = None
        if doc.UndoCount < self._start_count:
            self._own_moves = True
            try:
                while doc.UndoCount < self._start_count and doc.RedoCount:
                    doc.redo()
            finally:
                self._own_moves = False
            failure = EditFailure(_PAST_START, None)
            log(f"history: undo went past the session; redone to {doc.UndoCount}")
        session = self._session
        container = session.container
        if self._probe_name is not None:
            session.probe = doc.getObject(self._probe_name)
        try:
            unit, reasons = _read_unit(container)
            spaces = solve(unit)
        except LayoutSolveError as err:
            log(f"history: read back does not solve: {err}")
            self._on_change(EditFailure(describe_solve_error(err), err.node_id))
            return
        session.unit = unit
        session.spaces = spaces
        session._set_aside_reasons = reasons
        session.left_alone = tuple(
            session._left_alone(name)
            for name in sorted(reasons)
            if not properties.has_board_properties(doc.getObject(name))
        )
        selected = session.selected_id
        if selected is not None and _find_node(unit.root, selected) is None:
            session.selected_id = None
        log(f"history: read back at undo count {doc.UndoCount}")
        self._on_change(failure)
