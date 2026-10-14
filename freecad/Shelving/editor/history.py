"""The undo history of one editing session: each edit its own step in
FreeCAD's undo stack, every Undo and Redo read back into the session, and
the whole session folded into one step at OK.

``Std_Undo`` and ``Std_Redo`` reach the document from their shortcuts, the
Edit menu and the toolbar, during a task dialog too, and a panel can
intercept none of them, so the session follows FreeCAD's stack instead of
owning it. That stack names its steps and nothing more, and past
``MaxUndoSize`` each commit drops its oldest step, so positions read from
``UndoCount`` drift. :class:`EditHistory` keeps its own copy of the stack,
updated from the document's signals, holding the session's state after
each of its own steps.

Imports no Qt: the caller passes the deferral FreeCAD's signals need.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Generic, Literal, Protocol, TypeVar, cast

import FreeCAD

FLOOR_MESSAGE = "Nothing older to undo in this edit."
NOT_FOLDED_MESSAGE = (
    "This edit could not be folded into one undo step, because another change "
    "was made in the document while it was open."
)
# The step OK leaves, and the session's first step while it runs.
SESSION_STEP = "Edit Shelving Unit"
# The step Cancel writes when another change blocks undoing the session.
CANCEL_STEP = "Cancel Shelving Edit"
_DEFAULT_MAX_STEPS = 20

S = TypeVar("S")

Schedule = Callable[[Callable[[], None]], None]


class HistoryOwner(Protocol[S]):
    """What :class:`EditHistory` needs from the session whose steps it
    keeps. ``S`` is the session's state: everything an Undo or Redo puts
    back without reading the document."""

    def capture(self) -> S:
        """The session's state as it stands."""
        ...

    def restore(self, state: S) -> None:
        """Adopt ``state`` without writing to the document, which already
        holds it."""
        ...

    def write(self, state: S, *, probe: bool) -> Mapping[str, str]:
        """Write ``state`` into the document, with the session's probe
        object present when ``probe`` and absent otherwise. Returns each
        board id the write renamed to its object's name."""
        ...

    def renamed(self, state: S, renames: Mapping[str, str]) -> S:
        """``state`` with board ids renamed per ``renames``."""
        ...

    def rescan(self) -> S | None:
        """The session's state read fresh from the document, or ``None``
        when it does not read."""
        ...

    def owns(self, name: str) -> bool:
        """Whether the object ``name`` is the unit's container or one of its
        objects."""
        ...

    def probe_name(self) -> str | None: ...

    def nudge(self) -> None:
        """Record a change that leaves the document as it is, so an aborted
        transaction around it clears FreeCAD's Redo list."""
        ...

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


_Kind = Literal["before", "own", "foreign", "probe"]


@dataclass
class _Entry(Generic[S]):
    """One step of FreeCAD's undo or redo stack, as this history sees it."""

    # before: a step from before the session. own: one of the session's.
    # foreign: one the session did not make. probe: one the session did not
    # make that touched only its probe object, such as an expression bound
    # through a field's f(x) dialog, which the session may undo freely.
    kind: _Kind
    name: str = ""
    # The session's state once this step is done; None for a step that
    # leaves it as the step below left it.
    state: S | None = None
    # The session's first step, which creates its probe object: OK and
    # Cancel undo down through it.
    start: bool = False
    # The oldest step Undo may take back is the one above this: the
    # session's first step, then the fold of its oldest steps.
    floor: bool = False
    # A foreign step that touched the unit's objects, read back by a
    # rescan the first time it is on top.
    rescan: bool = False
    touched: set[str] = field(default_factory=set)


class EditHistory(Generic[S]):
    """The document transactions of one editing session over ``doc``.

    Construct it before the session's first change, then call
    :meth:`start`. ``schedule`` runs a callable once FreeCAD has finished
    the signal being handled; the read-back after an Undo or Redo runs
    through it, or through :meth:`settle`.
    """

    def __init__(
        self, doc: FreeCAD.Document, owner: HistoryOwner[S], schedule: Schedule
    ) -> None:
        self._doc = doc
        self._owner = owner
        self._schedule = schedule
        self._undo: list[_Entry[S]] = [_Entry("before") for _ in range(doc.UndoCount)]
        self._redo: list[_Entry[S]] = [_Entry("before") for _ in range(doc.RedoCount)]
        self._start = owner.capture()
        # The open step's name, between begin and end.
        self._step_name: str | None = None
        self._ending = False
        # The entry a write of this history's own is about to commit.
        self._writing: _Entry[S] | None = None
        # FreeCAD's pending transaction this history opened, as
        # getActiveTransaction gives it: an open with no change leaves it
        # pending until a later change, whoever makes it.
        self._pending: tuple[str, int] | None = None
        self._lingering: tuple[str, int] | None = None
        self._recording: set[str] | None = None
        self._recording_writing: _Entry[S] | None = None
        self._recording_step: str | None = None
        self._own_moves = False
        self._gui_list_filled = False
        self._settle_queued = False
        self._finished = False
        # The step count past which FreeCAD drops a step, once seen.
        self._observed_limit: int | None = None
        FreeCAD.addDocumentObserver(self)

    @property
    def finished(self) -> bool:
        return self._finished

    def start(self, create_probe: Callable[[], None]) -> None:
        """Commit the session's first step, which holds only what
        ``create_probe`` makes: an Undo past the session's first edit
        removes nothing the user made, and is redone at once."""
        self._commit_own(
            _Entry("own", SESSION_STEP, self._start, start=True, floor=True),
            create_probe,
        )

    def begin(self, name: str) -> None:
        """Open the step named ``name`` that one edit fills, closed by
        :meth:`end`. Folds the session's oldest steps first when the
        commit would push one of its own steps off FreeCAD's stack."""
        self.settle()
        self._make_room()
        self._step_name = name
        self._open(name)

    def end(self, keep: bool) -> None:
        """Commit the open step when ``keep``, else abort it, so a refused
        edit leaves no step. Does nothing when FreeCAD already closed it."""
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

    @property
    def step_open(self) -> bool:
        return self._step_name is not None

    def finish(self, keep: bool) -> str | None:
        """End the session: undo its steps and, when ``keep`` and it changed
        anything, write its state back as one step named
        :data:`SESSION_STEP`; otherwise leave the document as the session
        found it, with an empty Redo list. A step the session did not make
        is never undone: undoing stops above the newest one, and the state
        is written above it, the session's starting state for a cancel.
        Returns :data:`NOT_FOLDED_MESSAGE` then, else ``None``."""
        if self._finished:
            return None
        self._close_lingering()
        self.settle()
        self.end(keep=True)
        self._empty_gui_list()
        self._sync()
        final = self._owner.capture()
        base, reaches_start = self._rewind_base()
        edited = any(e.kind == "own" and not e.start for e in self._undo[base:])
        self._rewind(len(self._undo) - base)
        if keep and (edited or not reaches_start):
            self._write(SESSION_STEP, final, probe=False, floor=False)
        elif not reaches_start:
            self._write(CANCEL_STEP, self._start, probe=False, floor=False)
        else:
            self._clear_redo()
        FreeCAD.removeDocumentObserver(self)
        self._finished = True
        return None if reaches_start else NOT_FOLDED_MESSAGE

    def settle(self) -> None:
        """Read the latest Undo or Redo back into the session, if one has
        not been yet. An Undo below the session's floor is redone at once,
        and the owner hears :data:`FLOOR_MESSAGE`."""
        if not self._settle_queued or self._finished:
            return
        self._settle_queued = False
        self._sync()
        self._empty_gui_list()
        message: str | None = None
        floor = next((e for e in self._redo if e.floor), None)
        if floor is not None:
            with self._moving():
                while floor in self._redo and self._doc.RedoCount:
                    self._doc.redo()
                    self._sync()
            message = FLOOR_MESSAGE
        top = self._undo[-1] if self._undo else None
        if top is not None and top.rescan and top.state is None:
            top.state = self._owner.rescan()
        state = self._current_state()
        if state is not None:
            self._owner.restore(state)
        self._owner.changed(message)

    # FreeCAD's document observer

    def slotOpenTransaction(self, doc: FreeCAD.Document, _name: str) -> None:
        if doc is self._doc:
            self._recording = set()
            # Whose step this is, decided now: inside a Gui command FreeCAD
            # holds the commit back until the command returns.
            self._recording_writing = self._writing
            self._recording_step = self._step_name

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
        writing, step = self._recording_writing, self._recording_step
        self._recording_writing, self._recording_step = None, None
        if writing is not None:
            entry: _Entry[S] = writing
        elif step is not None:
            entry = _Entry("own", step, self._owner.capture())
            if self._step_name is not None and not self._ending:
                self._step_name = None
                self._owner.step_interrupted()
        elif touched and touched <= {self._owner.probe_name()}:
            entry = _Entry("probe", touched=touched)
        else:
            rescan = any(self._owner.owns(name) for name in touched)
            entry = _Entry("foreign", rescan=rescan, touched=touched)
        before = len(self._undo)
        self._undo.append(entry)
        self._redo.clear()
        self._sync()
        if len(self._undo) <= before:
            self._observed_limit = self._doc.UndoCount
        if entry.kind == "foreign" and not self._own_moves:
            self._queue_settle()

    def slotUndoDocument(self, doc: FreeCAD.Document) -> None:
        if doc is not self._doc:
            return
        if self._undo:
            self._redo.append(self._undo.pop())
        if self._gui_transacting():
            self._gui_list_filled = True
        if not self._own_moves:
            self._queue_settle()

    def slotRedoDocument(self, doc: FreeCAD.Document) -> None:
        if doc is not self._doc:
            return
        if self._redo:
            self._undo.append(self._redo.pop())
        if self._gui_transacting():
            # A Gui Redo walks and empties the list a Gui Undo fills.
            self._gui_list_filled = False
        if not self._own_moves:
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

    def _commit_own(self, entry: _Entry[S], change: Callable[[], None]) -> None:
        self._open(entry.name)
        self._writing = entry
        try:
            change()
        except BaseException:
            self._writing = None
            self._doc.abortTransaction()
            self._close_pending()
            raise
        try:
            self._doc.commitTransaction()
        finally:
            self._writing = None
            self._close_pending()

    def _write(
        self, name: str, state: S, *, probe: bool, floor: bool
    ) -> Mapping[str, str]:
        entry: _Entry[S] = _Entry("own", name, state, floor=floor)
        renames: dict[str, str] = {}

        def change() -> None:
            renames.update(self._owner.write(state, probe=probe))
            entry.state = self._owner.renamed(state, renames)

        self._commit_own(entry, change)
        return renames

    def _clear_redo(self) -> None:
        if not self._doc.RedoCount:
            return
        # FreeCAD clears its Redo list once a transaction records any
        # change, even one it then aborts; opening one alone clears nothing.
        self._open("Clear redo")
        self._owner.nudge()
        self._doc.abortTransaction()
        self._close_pending()
        self._sync()

    @contextmanager
    def _moving(self) -> Iterator[None]:
        self._own_moves = True
        try:
            yield
        finally:
            self._own_moves = False

    def _rewind(self, steps: int) -> None:
        with self._moving():
            for _ in range(steps):
                self._doc.undo()
        self._sync()

    def _rewind_base(self) -> tuple[int, bool]:
        """The index in the undo copy of the lowest step OK or Cancel may
        undo, and whether undoing down to it reaches the session's start:
        its first step, unless a foreign step above it, or that step
        dropped from FreeCAD's stack, stops the rewind higher up."""
        start = next((i for i, e in enumerate(self._undo) if e.start), None)
        low = start if start is not None else 0
        foreign = [
            i for i in range(low, len(self._undo)) if self._undo[i].kind == "foreign"
        ]
        if foreign:
            return foreign[-1] + 1, False
        if start is None:
            own = [i for i, e in enumerate(self._undo) if e.kind in ("own", "probe")]
            return (own[0] if own else len(self._undo)), False
        return start, True

    def _current_state(self) -> S | None:
        for entry in reversed(self._undo):
            if entry.state is not None:
                return entry.state
        return None

    def _max_steps(self) -> int:
        param = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document")
        limit = param.GetInt("MaxUndoSize", _DEFAULT_MAX_STEPS)
        if self._observed_limit is not None:
            limit = min(limit, self._observed_limit)
        return limit

    def _make_room(self) -> None:
        """Fold the floor and the older half of the session's steps above it
        into one step, the new floor, when the next commit would drop one of
        the session's steps from FreeCAD's stack. Nothing is undone below
        the newest foreign step, nor the session's first step, which holds
        the probe object the panel's fields are bound to. FreeCAD drops a
        step from before the session, or a foreign one, as it always does."""
        self._sync()
        if len(self._undo) < self._max_steps() or not self._undo:
            return
        if self._undo[0].kind in ("before", "foreign"):
            return
        base = self._fold_base()
        entries = self._undo[base:]
        folded = len(entries) // 2
        if folded < 2:
            return
        states: list[S | None] = []
        state = self._current_state_below(base)
        for entry in entries:
            state = entry.state if entry.state is not None else state
            states.append(state)
        self._rewind(len(entries))
        for entry in self._undo:
            entry.floor = False
        renames: dict[str, str] = {}
        fold_state = states[folded - 1]
        if fold_state is not None:
            renames.update(
                self._write(
                    entries[folded - 1].name, fold_state, probe=True, floor=True
                )
            )
        for entry, entry_state in zip(entries[folded:], states[folded:], strict=True):
            if entry.kind != "own" or entry_state is None:
                continue
            written = self._write(
                entry.name,
                self._owner.renamed(entry_state, renames),
                probe=True,
                floor=False,
            )
            renames = _composed(renames, written)
        current = self._current_state()
        if current is not None:
            self._owner.restore(current)

    def _fold_base(self) -> int:
        """The index in the undo copy of the lowest step a fold may undo:
        the floor, or the step above it while the floor is the session's
        first step, and never at or below the newest foreign step."""
        floor = next((i for i, e in enumerate(self._undo) if e.floor), None)
        base = 0 if floor is None else floor + 1 if self._undo[floor].start else floor
        foreign = [i for i, e in enumerate(self._undo) if e.kind == "foreign"]
        if foreign and foreign[-1] >= base:
            base = foreign[-1] + 1
        while base < len(self._undo) and self._undo[base].kind == "before":
            base += 1
        return base

    def _current_state_below(self, index: int) -> S | None:
        for entry in reversed(self._undo[:index]):
            if entry.state is not None:
                return entry.state
        return self._start

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
        while that step stays in the history; OK, Cancel, a fold and every
        new edit drop the Redo list, which frees it, and the next Gui Redo
        in the document reads freed memory and can crash FreeCAD. A Gui
        Redo here, with its step taken back at the App level, which records
        no view providers, leaves the list empty and the document where it
        was."""
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


def _composed(first: Mapping[str, str], then: Mapping[str, str]) -> dict[str, str]:
    """Renames ``first`` followed by ``then``, as one mapping."""
    composed = {old: then.get(new, new) for old, new in first.items()}
    for old, new in then.items():
        composed.setdefault(old, new)
    return composed
