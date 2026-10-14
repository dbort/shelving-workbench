"""The undo steps of one editing session: each edit its own step in
FreeCAD's undo stack, and every Undo and Redo read back into the session.

``Std_Undo`` and ``Std_Redo`` reach the document from their shortcuts, the
Edit menu and the toolbar, during a task dialog too, and a panel can
intercept none of them, so the session follows FreeCAD's stack instead of
owning it. That stack names its steps and nothing more, and past
``MaxUndoSize`` each commit drops its oldest step, so positions read from
``UndoCount`` drift. :class:`EditHistory` keeps its own copy of the stack,
updated from the document's signals, to tell the session's steps from
the rest: no Undo during the session reaches what came before it.

Imports no Qt: the caller passes the deferral FreeCAD's signals need.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import FreeCAD

FLOOR_MESSAGE = "Nothing older to undo in this edit."
# The session's first step, which marks where it began.
SESSION_STEP = "Edit Shelving Unit"

Schedule = Callable[[Callable[[], None]], None]


class HistoryOwner(Protocol):
    """What :class:`EditHistory` needs from the session whose steps it
    follows."""

    def mark_start(self) -> None:
        """Record a change that leaves the document as it is: the content
        of the session's first step."""
        ...

    def reload(self) -> None:
        """Read the session's state back from the document after an Undo
        or Redo."""
        ...

    def probe_name(self) -> str | None: ...

    def step_interrupted(self) -> None:
        """FreeCAD closed the open step itself, as an Undo during a drag
        does."""
        ...

    def changed(self, message: str | None) -> None:
        """An Undo or Redo was read back; ``message``, if any, is for the
        user."""
        ...


class _GuiDocument(Protocol):
    # True while FreeCAD's Gui runs an Undo or Redo in this document.
    Transacting: bool


_Kind = Literal["before", "start", "edit", "other"]


@dataclass
class _Entry:
    """One step of FreeCAD's undo or redo stack, as this history sees it."""

    # before: from before the session. start: the session's first step.
    # edit: one of the session's edits. other: one the session did not make.
    kind: _Kind


class EditHistory:
    """The document transactions of one editing session over ``doc``.

    ``schedule`` runs a callable once FreeCAD has finished the signal being
    handled; the read-back after an Undo or Redo runs through it, or
    through :meth:`settle`.
    """

    def __init__(
        self, doc: FreeCAD.Document, owner: HistoryOwner, schedule: Schedule
    ) -> None:
        self._doc = doc
        self._owner = owner
        self._schedule = schedule
        self._undo = [_Entry("before") for _ in range(doc.UndoCount)]
        self._redo = [_Entry("before") for _ in range(doc.RedoCount)]
        # The edit step's name, between begin and end, and whether its
        # transaction is open: it opens only once the edit writes, so a
        # click, or a refused edit, leaves the history untouched.
        self._step_name: str | None = None
        self._step_opened = False
        self._ending = False
        # Whether the session's first step is being written, and whether it
        # has been: it waits for the first write, since its commit empties
        # the Redo list.
        self._starting = False
        self._started = False
        # Steps from before the session that an Undo took back before the
        # first edit, which the read-back redoes.
        self._undone_before = 0
        # An Undo or Redo ended a step whose transaction was open but held
        # nothing, leaving FreeCAD's pending transaction to close.
        self._step_dropped = False
        # FreeCAD's pending transaction this history opened, as
        # getActiveTransaction gives it: an open with no change leaves it
        # pending until a later change, whoever makes it.
        self._pending: tuple[str, int] | None = None
        self._lingering: tuple[str, int] | None = None
        # The objects the transaction now recording has touched, and whose
        # step it is, decided when it opened.
        self._recording: set[str] | None = None
        self._recording_kind: _Kind = "other"
        self._own_moves = False
        self._gui_list_filled = False
        self._settle_queued = False
        self._finished = False
        # Whether any step changed the probe object.
        self.probe_recorded = False
        FreeCAD.addDocumentObserver(self)

    @property
    def finished(self) -> bool:
        return self._finished

    @property
    def step_open(self) -> bool:
        return self._step_name is not None

    def begin(self, name: str) -> None:
        """Start the step named ``name`` that one edit fills, closed by
        :meth:`end`; its transaction opens at :meth:`write_ahead`."""
        self.settle()
        self._step_name = name
        self._step_opened = False

    def write_ahead(self) -> None:
        """Open the current step's transaction, if it is not yet open, just
        before the edit writes. Before the session's first write, commits
        its first step, named :data:`SESSION_STEP`, which changes nothing:
        an Undo of it is the floor. Does nothing outside a step."""
        if self._step_name is None or self._step_opened:
            return
        if not self._started:
            self._started = True
            self._starting = True
            try:
                self._open(SESSION_STEP)
                self._owner.mark_start()
            finally:
                self._starting = False
            self._doc.commitTransaction()
            self._close_pending()
        self._step_opened = True
        self._open(self._step_name)

    def end(self, keep: bool) -> None:
        """Commit the step when ``keep``, else abort it, so a refused edit
        leaves no step. Does nothing when FreeCAD already closed it."""
        if self._step_name is None:
            return
        opened = self._step_opened
        self._step_name = None
        self._step_opened = False
        if not opened:
            return
        self._ending = True
        try:
            if keep:
                self._doc.commitTransaction()
            else:
                self._doc.abortTransaction()
        finally:
            self._ending = False
            self._close_pending()

    def finish(self) -> None:
        """Stop following the document, leaving every step where it is."""
        if self._finished:
            return
        self._close_lingering()
        self.settle()
        self.end(keep=True)
        self._empty_gui_list()
        FreeCAD.removeDocumentObserver(self)
        self._finished = True

    def settle(self) -> None:
        """Read the latest Undo or Redo back into the session, if one has
        not been yet. An Undo of the session's first step, or of a step from
        before the session, is redone at once, and the owner hears
        :data:`FLOOR_MESSAGE`."""
        if not self._settle_queued or self._finished:
            return
        self._settle_queued = False
        if self._step_dropped:
            self._step_dropped = False
            self._close_pending()
        self._sync()
        self._empty_gui_list()
        message: str | None = None
        start = next((e for e in self._redo if e.kind == "start"), None)
        if start is not None or self._undone_before:
            with self._moving():
                while start in self._redo and self._doc.RedoCount:
                    self._doc.redo()
                    self._sync()
                for _ in range(self._undone_before):
                    if self._doc.RedoCount:
                        self._doc.redo()
                self._undone_before = 0
                self._sync()
            message = FLOOR_MESSAGE
        self._owner.reload()
        self._owner.changed(message)

    # FreeCAD's document observer

    def slotOpenTransaction(self, doc: FreeCAD.Document, _name: str) -> None:
        if doc is self._doc:
            self._recording = set()
            # Decided now: inside a Gui command FreeCAD holds the commit
            # back until the command returns.
            if self._starting:
                self._recording_kind = "start"
            elif self._step_name is not None:
                self._recording_kind = "edit"
            else:
                self._recording_kind = "other"

    def slotAbortTransaction(self, doc: FreeCAD.Document) -> None:
        if doc is self._doc:
            self._recording = None

    def slotChangedObject(self, obj: FreeCAD.DocumentObject, _prop: str) -> None:
        self._touch(obj)

    def slotCreatedObject(self, obj: FreeCAD.DocumentObject) -> None:
        self._touch(obj)

    def slotDeletedObject(self, obj: FreeCAD.DocumentObject) -> None:
        self._touch(obj)

    def slotCommitTransaction(self, doc: FreeCAD.Document) -> None:
        if doc is not self._doc:
            return
        touched = self._recording or set()
        self._recording = None
        kind, self._recording_kind = self._recording_kind, "other"
        if kind == "edit" and self._step_name is not None and not self._ending:
            # An Undo during a drag commits the drag's open step first.
            self._step_name = None
            self._step_opened = False
            self._owner.step_interrupted()
        if self._owner.probe_name() in touched:
            self.probe_recorded = True
        self._undo.append(_Entry(kind))
        self._redo.clear()
        self._sync()
        if kind == "other" and not self._own_moves:
            self._queue_settle()

    def slotUndoDocument(self, doc: FreeCAD.Document) -> None:
        if doc is not self._doc:
            return
        if self._undo:
            undone = self._undo.pop()
            self._redo.append(undone)
            if undone.kind == "before" and not self._own_moves:
                self._undone_before += 1
        if self._gui_transacting():
            self._gui_list_filled = True
        self._moved()

    def slotRedoDocument(self, doc: FreeCAD.Document) -> None:
        if doc is not self._doc:
            return
        if self._redo:
            redone = self._redo.pop()
            self._undo.append(redone)
            # The Gui Redo workaround's own moves come in pairs that leave
            # the count as it was.
            if redone.kind == "before" and self._undone_before and not self._own_moves:
                self._undone_before -= 1
        if self._gui_transacting():
            # A Gui Redo walks and empties the list a Gui Undo fills.
            self._gui_list_filled = False
        self._moved()

    def _moved(self) -> None:
        if self._own_moves:
            return
        if self._step_name is not None:
            # A drag that has written nothing yet: FreeCAD undoes past its
            # step, and the drag is over.
            self._step_dropped = self._step_opened
            self._step_name = None
            self._step_opened = False
            self._owner.step_interrupted()
        self._queue_settle()

    # Internals

    def _touch(self, obj: FreeCAD.DocumentObject) -> None:
        if self._recording is not None and obj.Document is self._doc:
            self._recording.add(obj.Name)

    def _queue_settle(self) -> None:
        if not self._settle_queued:
            self._settle_queued = True
            # FreeCAD signals from inside its own undo loop, which the
            # toolbar's drop-down list runs once per step.
            self._schedule(self.settle)

    def _sync(self) -> None:
        """Drop from the bottom of each copy what FreeCAD dropped from its
        stack."""
        while len(self._undo) > self._doc.UndoCount:
            self._undo.pop(0)
        while len(self._redo) > self._doc.RedoCount:
            self._redo.pop(0)

    def _open(self, name: str) -> None:
        self._close_lingering()
        before = cast("tuple[str, int] | None", FreeCAD.getActiveTransaction())
        self._doc.openTransaction(name)
        active = cast("tuple[str, int] | None", FreeCAD.getActiveTransaction())
        # A Gui command running this edit may hold its own application
        # transaction already; that one is FreeCAD's to close.
        self._pending = active if active != before else None

    def _close_pending(self) -> None:
        """Close the transaction this history opened when no change filled
        it, so the next change, perhaps not the session's, is not recorded
        under its name."""
        active = cast("tuple[str, int] | None", FreeCAD.getActiveTransaction())
        if self._pending is not None and active == self._pending:
            # While a Gui command runs, FreeCAD ignores this close, but would
            # honor an abort at once, discarding the step just committed.
            FreeCAD.closeActiveTransaction(False)
            if FreeCAD.getActiveTransaction() == self._pending:
                self._lingering = self._pending
                self._schedule(self._close_lingering)
        self._pending = None

    def _close_lingering(self) -> None:
        """Close a transaction a Gui command kept FreeCAD from closing, once
        the command has returned."""
        if self._lingering is not None:
            if FreeCAD.getActiveTransaction() == self._lingering:
                FreeCAD.closeActiveTransaction(False)
            self._lingering = None

    @contextmanager
    def _moving(self) -> Generator[None]:
        self._own_moves = True
        try:
            yield
        finally:
            self._own_moves = False

    def _gui_transacting(self) -> bool:
        if not FreeCAD.GuiUp:
            return False
        import FreeCADGui

        gui_doc = FreeCADGui.getDocument(self._doc.Name)
        return gui_doc is not None and cast("_GuiDocument", gui_doc).Transacting

    def _empty_gui_list(self) -> None:
        """Empty the list of view providers FreeCAD's Gui Undo fills, while
        every one in it is still alive.

        ``Gui::Document::undo`` records each view provider it recreates in
        ``_redoViewProviders``, and only ``Gui::Document::redo`` walks the
        list and clears it (FreeCAD 1.1 and main). An object an Undo brought
        back and a later Undo removed again keeps its view provider only
        while that step stays in the history; every new edit drops the Redo
        list, which frees it, and the next Gui Redo in the document reads
        freed memory and can crash FreeCAD. A Gui Redo here, with its step
        taken back at the App level, which records no view providers,
        leaves the list empty and the document where it was."""
        if not self._gui_list_filled or not FreeCAD.GuiUp:
            return
        import FreeCADGui

        with self._moving():
            if self._doc.RedoCount:
                FreeCADGui.runCommand("Std_Redo")
                self._doc.undo()
            elif self._doc.UndoCount:
                FreeCADGui.runCommand("Std_Undo")
                FreeCADGui.runCommand("Std_Redo")
        self._gui_list_filled = False
        self._sync()
