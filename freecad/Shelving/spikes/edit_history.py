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
from dataclasses import dataclass
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
from PySide6 import QtCore

from freecad.Shelving import properties
from freecad.Shelving.core.layout import Board, Division, Region
from freecad.Shelving.core.solver import LayoutSolveError, describe_solve_error, solve
from freecad.Shelving.editor.session import (
    EditFailure,
    Session,
    _find_node,
    _read_unit,
)
from freecad.Shelving.spikes.spike_log import log

_PAST_START = "Nothing left to undo in this edit"


class _GuiDocument(Protocol):
    # True while FreeCAD's Gui runs an Undo or Redo in this document.
    Transacting: bool


class _Placed(Protocol):
    Placement: FreeCAD.Placement


@dataclass(frozen=True)
class _Stock:
    """What :func:`properties.copy_stock` copies, held after its object is
    gone."""

    material: properties.FreeCADMaterial | None
    # The Grain property's type, group and value.
    grain: tuple[str, str, list[str]] | None
    appearance: list[FreeCAD.Material] | None

    @staticmethod
    def read(obj: FreeCAD.DocumentObject) -> _Stock:
        material = (
            cast("properties._MaterialObject", obj).ShapeMaterial
            if hasattr(obj, "ShapeMaterial")
            else None
        )
        grain_value = properties.read_grain(obj)
        grain = (
            (
                obj.getTypeIdOfProperty(properties.GRAIN_PROP),
                obj.getGroupOfProperty(properties.GRAIN_PROP),
                grain_value,
            )
            if grain_value is not None
            else None
        )
        view = properties._appearance_view(obj)
        appearance = list(view.ShapeAppearance) if view is not None else None
        return _Stock(material, grain, appearance)

    def write(self, obj: FreeCAD.DocumentObject) -> None:
        if self.material is not None and hasattr(obj, "ShapeMaterial"):
            cast("properties._MaterialObject", obj).ShapeMaterial = self.material
        if self.grain is not None:
            type_id, group, value = self.grain
            if not hasattr(obj, properties.GRAIN_PROP):
                obj.addProperty(type_id, properties.GRAIN_PROP, group)
            cast("properties._GrainObject", obj).Grain = value
        view = properties._appearance_view(obj)
        if self.appearance is not None and view is not None:
            view.ShapeAppearance = self.appearance


def _boards(region: Region) -> Iterator[Board]:
    if isinstance(region, Division):
        for item in region.items:
            if isinstance(item, Board):
                yield item
            else:
                yield from _boards(item)


def _board_ids(region: Region) -> set[str]:
    return {board.id for board in _boards(region)}


def _paired_board_ids(before: Region, after: Region) -> Iterator[tuple[str, str]]:
    """Each board's id in ``before`` with its id in ``after``, the same tree
    once a write has renamed the boards it created."""
    for old, new in zip(_boards(before), _boards(after), strict=True):
        yield old.id, new.id


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
        self._start_boards = _board_ids(session.unit.root)
        probe = session.probe
        self._probe_name = probe.Name if probe is not None else None
        self._own_moves = False
        # Whether a Gui Undo since the last Gui Redo left view providers in
        # FreeCAD's list (see _empty_gui_list).
        self._gui_list_filled = False
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
        # The undo below deletes every board the session added, and the
        # write recreates it with no source to copy its stock from: a read
        # back after an Undo or Redo leaves no Board.stock_from, since the
        # document does not record it.
        added_stock = {
            board_id: _Stock.read(obj)
            for board_id in _board_ids(final.root) - self._start_boards
            if (obj := doc.getObject(board_id)) is not None
        }
        self._empty_gui_list()
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
            if failure is None:
                for old_id, new_id in _paired_board_ids(final.root, session.unit.root):
                    stock = added_stock.get(old_id)
                    target = doc.getObject(new_id)
                    if stock is not None and target is not None:
                        stock.write(target)
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

    def _empty_gui_list(self) -> None:
        """Empty the list of view providers FreeCAD's Gui Undo fills, while
        every one in it is still alive.

        Gui::Document::undo records each view provider it recreates in
        _redoViewProviders, and only Gui::Document::redo walks the list and
        clears it (FreeCAD 1.1 and main). An object an Undo brought back and
        a later undo removed again keeps its view provider only while that
        step stays in the history; finish and every new edit drop the Redo
        list, which frees it, and the next Gui Redo in the document then
        reads freed memory and can crash FreeCAD (seen under Xvfb). A Gui
        Redo here, with its step taken back at the App level, which records
        nothing, leaves the list empty and the document where it was."""
        if not self._gui_list_filled:
            return
        doc = self._doc
        self._own_moves = True
        try:
            if doc.RedoCount:
                FreeCADGui.runCommand("Std_Redo")
                doc.undo()
            elif doc.UndoCount:
                FreeCADGui.runCommand("Std_Undo")
                FreeCADGui.runCommand("Std_Redo")
        finally:
            self._own_moves = False
        self._gui_list_filled = False
        log("history: emptied FreeCAD's Gui redo list")

    # FreeCAD's document observer

    def slotUndoDocument(self, doc: FreeCAD.Document) -> None:
        self._moved(doc, "undo")

    def slotRedoDocument(self, doc: FreeCAD.Document) -> None:
        self._moved(doc, "redo")

    def _moved(self, doc: FreeCAD.Document, kind: str) -> None:
        if doc is not self._doc or self._own_moves or self._finished:
            return
        if cast("_GuiDocument", FreeCADGui.getDocument(doc.Name)).Transacting:
            # A Gui Redo walks and empties the list a Gui Undo fills.
            self._gui_list_filled = kind == "undo"
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
        self._empty_gui_list()
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
