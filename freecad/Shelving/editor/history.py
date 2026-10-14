"""The undo steps of one editing session: each edit its own step in
FreeCAD's undo stack, and every Undo and Redo read back into the session.

``Std_Undo`` and ``Std_Redo`` reach the document from their shortcuts, the
Edit menu and the toolbar, during a task dialog too, and a panel can
intercept none of them, so the session follows the document as
Sketcher's edit mode does: an Undo goes wherever FreeCAD's history takes
it, and the session reads the result back.

Imports no Qt: the caller passes the deferral FreeCAD's signals need.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Protocol, cast

import FreeCAD

Schedule = Callable[[Callable[[], None]], None]


class HistoryOwner(Protocol):
    """What :class:`EditHistory` needs from the session whose steps it
    follows."""

    def reload(self) -> None:
        """Read the session's state back from the document after an Undo,
        a Redo, or a step the session did not make."""
        ...

    def probe_name(self) -> str | None: ...

    def step_interrupted(self) -> None:
        """An Undo or Redo ended the open step, as one during a drag does."""
        ...


class _GuiDocument(Protocol):
    # True while FreeCAD's Gui runs an Undo or Redo in this document.
    Transacting: bool


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
        # The open edit step's name, between begin and end.
        self._step_name: str | None = None
        self._ending = False
        # An Undo or Redo ended a step whose transaction held nothing yet,
        # leaving FreeCAD's pending transaction to close.
        self._step_dropped = False
        # FreeCAD's pending transaction this history opened, as
        # getActiveTransaction gives it: an open with no change leaves it
        # pending until a later change, whoever makes it.
        self._pending: tuple[str, int] | None = None
        # The objects the transaction now recording has touched.
        self._recording: set[str] | None = None
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
        """Open the step named ``name`` that one edit fills, closed by
        :meth:`end`."""
        self.settle()
        self._step_name = name
        self._open(name)

    def end(self, keep: bool) -> None:
        """Commit the open step when ``keep``, else abort it, so a refused
        edit leaves no step; a step nothing wrote into leaves none either.
        Does nothing when an Undo or Redo already ended it."""
        if self._step_name is None:
            return
        self._ending = True
        try:
            if keep:
                self._doc.commitTransaction()
            else:
                self._doc.abortTransaction()
        finally:
            self._ending = False
            self._step_name = None
            self._close_pending()

    def finish(self) -> None:
        """Stop following the document, leaving every step where it is."""
        if self._finished:
            return
        self.settle()
        self.end(keep=True)
        self._empty_gui_list()
        FreeCAD.removeDocumentObserver(self)
        self._finished = True

    def settle(self) -> None:
        """Read the latest Undo, Redo, or step the session did not make back
        into the session, if it has not been yet."""
        if not self._settle_queued or self._finished:
            return
        self._settle_queued = False
        if self._step_dropped:
            self._step_dropped = False
            self._close_pending()
        self._empty_gui_list()
        self._owner.reload()

    # FreeCAD's document observer

    def slotOpenTransaction(self, doc: FreeCAD.Document, _name: str) -> None:
        if doc is self._doc:
            self._recording = set()

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
        if self._owner.probe_name() in touched:
            self.probe_recorded = True
        if self._step_name is not None and not self._ending:
            # An Undo during a drag commits the drag's open step first.
            self._end_interrupted()
        elif self._step_name is None and not self._own_moves:
            # A step the session did not make.
            self._queue_settle()

    def slotUndoDocument(self, doc: FreeCAD.Document) -> None:
        if doc is self._doc:
            if self._gui_transacting():
                self._gui_list_filled = True
            self._moved()

    def slotRedoDocument(self, doc: FreeCAD.Document) -> None:
        if doc is self._doc:
            if self._gui_transacting():
                # A Gui Redo walks and empties the list a Gui Undo fills.
                self._gui_list_filled = False
            self._moved()

    # Internals

    def _moved(self) -> None:
        if self._own_moves:
            return
        if self._step_name is not None:
            # A drag that has written nothing yet: FreeCAD undoes past its
            # step, and the drag is over.
            self._step_dropped = True
            self._end_interrupted()
        self._queue_settle()

    def _end_interrupted(self) -> None:
        self._step_name = None
        self._owner.step_interrupted()

    def _touch(self, obj: FreeCAD.DocumentObject) -> None:
        if self._recording is not None and obj.Document is self._doc:
            self._recording.add(obj.Name)

    def _queue_settle(self) -> None:
        if not self._settle_queued:
            self._settle_queued = True
            # FreeCAD signals from inside its own undo loop, which the
            # toolbar's drop-down list runs once per step.
            self._schedule(self.settle)

    def _open(self, name: str) -> None:
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
            FreeCAD.closeActiveTransaction(False)
        self._pending = None

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
            redo_count = self._doc.RedoCount
            if redo_count:
                FreeCADGui.runCommand("Std_Redo")
                # Only a Redo that ran is taken back.
                if self._doc.RedoCount < redo_count:
                    self._doc.undo()
            elif self._doc.UndoCount:
                FreeCADGui.runCommand("Std_Undo")
                if self._doc.RedoCount:
                    FreeCADGui.runCommand("Std_Redo")
        self._gui_list_filled = False
