---
id: sh-039
title: "Undo and Redo inside an edit"
blocked_by: [sh-037]
---

# sh-039: Undo and Redo inside an edit

## Summary
Cmd-Z and Redo, from any of FreeCAD's routes, step through the edits made
since Edit Unit opened, one edit at a time, and the panel follows. Each
edit stays its own undo step after the panel closes, as Sketcher's and
Draft's edits do, and the panel has one button, Close. Today one Cmd-Z
reverts the whole session and a second reverts what came before it, under
an open panel (bug-015). Milestone M14.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] Each edit made through `Session` is one FreeCAD transaction named
      for it, and a refused edit leaves none: a split, a merge, a typed
      size, a basis change, a unit resize, a whole drag from `begin_drag`
      to `end_drag` however many steps it took, a lock or unlock
      (sh-038), and deleting a left-alone object.
- [ ] In the view tier (sh-037), with Edit Unit open on a unit after
      several edits, each `Std_Undo` steps back exactly one edit and each
      `Std_Redo` forward one: after every step the document's boards and
      the session's unit (every solved space) equal the state that edit
      produced, the panel shows that state, and a selected node that
      still exists stays selected.
- [ ] `Std_Undo` past the session's first edit undoes the steps before the
      session as FreeCAD always does, and the panel follows; when an Undo
      removes the unit or leaves it unreadable (Create Unit undone), the
      panel closes, and `Std_Redo` then works as it does without a panel.
- [ ] The panel's only button is Close. Close leaves each edit as its own
      undo step, removes the probe object without adding a step, and
      leaves the Redo list as it was; `Std_Undo` after Close steps back
      exactly one edit. A session that made no edit, or only clicks and
      refused edits, leaves the undo and Redo lists as it found them.
- [ ] A shelf added beside a board whose color and material were set
      keeps that color and material through an Undo and Redo of a later
      edit, and after Close.
- [ ] An Undo during a drag ends the drag, and the session then matches
      the document.
- [ ] FreeCAD's Gui Redo use-after-free (below) cannot be reached through
      the editor: a test runs the sequence that crashes plain FreeCAD
      (create, delete, undo, undo, a new edit, undo, redo, all inside a
      session through `Std_Undo` and `Std_Redo`) in a FreeCAD GUI process
      started with `MALLOC_PERTURB_=165` and
      `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`, and the process exits
      cleanly.
- [ ] `editor.one-session`'s "Run Edit, Undo once" step is gone from
      `freecad/Shelving/qa/cases/30-editor.toml`, and every QA step that
      clicked Cancel clicks Close with its expectation to match.
- [ ] `bug-015` is deleted from `.claude/docs/bug-log.md`.

## Advice

DECISIONS (user, 2026-10-13):
- **One Cmd-Z at the top of the stack always undoes exactly one edit.**
  Nothing may make a single Undo take back several edits.
- **Edits stay as their own steps after the panel closes**, as Sketcher's
  and Draft's do: no folding into one step, so FreeCAD's history limit
  needs no handling of its own, and nothing is ever undone and written
  again.
- **Close only, no Cancel**, as Sketcher's edit mode: the user takes edits
  back with Cmd-Z. sh-040 and sh-031 plan around Cancel and need
  re-planning against Close.
- **No floor, as Sketcher:** Undo and Redo during a session go wherever
  FreeCAD's history takes them, and the panel follows by rescanning; when
  the unit is gone or no longer reads, the panel closes, as Sketcher's
  edit mode ends when its sketch is undone. Follow FreeCAD's own tools
  rather than inventing behavior they lack (`CLAUDE.md`, standing
  obligations).
- **The current panel need not survive long.** Wire Undo into today's
  panel (sh-040 replaces it), enough for the Must Haves; do not polish it.

FINDINGS from the viewport spike (branch `research/viewport-editing` at
`06d20ab`, keep it until sh-041 ships;
`06d20ab:freecad/Shelving/spikes/edit_history.py` is the reference
implementation, and `06d20ab:research/viewport-editing.md` § "Findings the
spike added" has the full account), and from this task's first build:
- `Std_Undo` and `Std_Redo` reach the document from their shortcuts, the
  Edit menu, the toolbar and its drop-down list, all enabled during a task
  dialog while focus is in the 3D view, and a Python panel can intercept
  none of them. They send "Undo"/"Redo" to the active view, so they do
  nothing without a 3D view: test them in the view tier.
- A document observer's `slotUndoDocument` and `slotRedoDocument` fire
  inside FreeCAD's undo loop, once per step for the drop-down list; defer
  the session's update with `QTimer.singleShot(0, ...)`. The Gui
  document's `Transacting` flag tells a Gui Undo or Redo from an
  App-level one.
- **The probe object cannot live in a step that stays in the history**:
  removing it at Close would take a step of its own, which the first
  Cmd-Z after Close would spend bringing it back. Create and remove it
  outside any transaction. Should any step record a change to the probe,
  remove it in a step of its own at Close instead, so no step in the
  history names a destroyed object.
- **Gui Redo use-after-free (FreeCAD 1.1 and main):**
  `Gui::Document::undo` records each view provider it recreates in
  `_redoViewProviders`, and only `Gui::Document::redo` walks and clears
  that list. An object an Undo brought back and a later Undo removed
  again keeps a listed view provider only while that step stays in the
  history; every new edit after an Undo drops it, and the next Gui Redo
  in the document crashes in `handleChildren3D`. Workaround: after each
  Gui Undo, run `Std_Redo` (which empties the list while its entries are
  alive) and take that step back with the App-level `doc.undo()`, which
  records no view providers; with nothing to redo, `Std_Undo` then
  `Std_Redo`. A draft upstream issue is at
  `3622341:research/spikes/freecad-issue-redo-crash.md`; keep the
  workaround version-agnostic.
- **Read back by rescanning.** After an Undo or Redo the document holds
  exactly the state the step left, and no board is ever recreated from the
  unit, so a rescan loses nothing that matters. A rescan mints fresh region
  ids: carry the selection over to the region with the same solved space.
- **FreeCAD's transaction quirks** (`.claude/docs/freecad-notes.md`,
  "Transactions and the undo stack"): an empty transaction leaves its name
  pending for the next change; a Gui command defers closing the
  application transaction, so Edit Unit declares `CmdType: NoTransaction`.

CONSTRAINTS:
- `Session` owns the document's transactions (`.claude/docs/code-map.md`
  says it owns "its one transaction"; update that). Keep the history
  logic in the editor layer, testable without the panel; the panel only
  reacts to a "the unit changed" notification and shows the message.
- An Undo arriving mid-drag must not corrupt the session: finish or
  abandon the drag first.
- FreeCAD.app runs Python 3.11 while pixi runs 3.12: nothing 3.12-only;
  take `override` from `freecad.Shelving.compat`.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: protocols for the FreeCAD and Gui document attributes
  used (`Transacting`, `UndoNames`), no bare containers; `pyrefly check`
  clean.
- Shell stays simple: the crash test starts its subprocess from Python.
- Users never read the log: the panel closing when its unit is undone is
  itself visible, as Sketcher's edit mode ending is.

## Plan
- [ ] **Step 1** (`freecad/Shelving/editor/history.py`, `freecad/Shelving/editor/session.py`): A history that follows the document's signals: one step per edit, the read-back by rescanning, the panel closing when the unit is gone, the Gui Redo workaround, and Close; `Session.close` replaces `commit` and `cancel`.
- [x] **Step 2** (`freecad/Shelving/editor/panel.py`, `freecad/Shelving/commands/edit_unit.py`, `freecad/Shelving/qa/actions.py`, `freecad/Shelving/properties.py`): The panel's one Close button; callers of `commit` and `cancel` close instead; drop the stock records the rewrite needed.
- [x] **Step 3** (`tests/freecad/`, `tests/freecad_gui/`, `tests/freecad_view/`): Bring the tests to Close; headless and view-tier tests for the Must Haves; the crash-sequence subprocess test.
- [x] **Step 4** (`freecad/Shelving/qa/cases/30-editor.toml`, `.claude/docs/code-map.md`, `.claude/docs/bug-log.md`, `.claude/docs/freecad-notes.md`): Close in the QA cases, the code map, bug-015, the notes.

## Review log

### Round 1: REJECTED
- **F1: OK drops the stock of a recreated board that gets its old name back** (`freecad/Shelving/editor/session.py:367`): `Session.write` reapplies stored stock only to boards in `result.id_renames`, which lists a board only when its new name differs; a board recreated under its old name falls back on `stock_from`, whose source may be gone. Apply stored stock to every board the write created, and test the sequence (bottom Wood, add Board, add Board001 above it, add Board002 below it, merge Board, OK).
- **F2: Nothing tests that color survives** (`tests/freecad/test_edit_history.py:282`): the stock test checks only `ShapeMaterial`, headless, so `ShapeAppearance` through Undo, Redo and OK is untested.
- N1: The crash test missed a disabled workaround in one of four runs; repeat the sequence in the child.
- N2: The OK-at-the-limit test skips the ten unrelated steps and does not compare the history below `SESSION_STEP`.
- N3: The view tier checks the could-not-fold message only for Cancel.
- N4: Only `set_size` is tested as a refused edit leaving no step.
- N5: Style nits in `Session.commit`, the `Grain` docstring, `CmdType`'s type, and the `EditUnitPanel` docstring.

### Round 2: APPROVED
- No new findings. Round 1's F1 and F2 are fixed with tests that fail without the fixes; N1 to N5 are addressed.

### Round 3: REJECTED
Reviewed the design the user chose after Round 2.
- **F1: A session that made no edit wipes the Redo list it found** (`freecad/Shelving/editor/history.py:338`): the start step's commit at open clears Redo, and Close undoing it cannot bring earlier entries back. Test with a non-empty Redo list before open.
- **F2: The panel tells users Cancel restores deleted objects** (`freecad/Shelving/editor/panel.py:641`).
- **F3: Docs and tests still describe the dropped design**: `session.py`'s module docstring and `delete_untagged` docstring, a comment and a test name in `tests/freecad/test_editor_session.py`, and M14 in `docs/roadmap.md`.
- **F4: An Undo during a drag that has not yet changed the document does not end the drag** (`freecad/Shelving/editor/history.py:460`): no commit signal fires, so the drag goes on; end it on the Undo or Redo signal and test it.
- N1: No test that a selected board stays selected across an Undo.
- N2: The `editor.dimensions` undo step assumes the f(x) binding records no step of its own.
- N3: sh-040 and sh-031 still plan around Cancel.

### Round 4: REJECTED
- **F1: A Gui `Std_Undo` before the session's first edit undoes a step from before the session, with no floor message** (`freecad/Shelving/editor/history.py:270`): the Gui Redo workaround's own moves change the count of pre-session steps undone, so `settle` finds nothing to redo. Test it through `Std_Undo` in the view tier.
- **F2: A click on a board with no edit empties Redo and leaves an "Edit Shelving Unit" step** (`freecad/Shelving/editor/session.py:600`): `begin_drag` on every press commits the start step. Test a no-move drag before any edit with a non-empty Redo list.
- N1: The fix for an Undo before a drag moves is tested only at the App level.
- N2: Round 3's N2 rests on the manual QA run.

### Round 5: REJECTED
- **F1: An Undo reaching below the session's start in one read-back comes back with the first edit redone** (`freecad/Shelving/editor/history.py:211`): after the start step and the earlier steps are redone, the count of pre-session steps undone is still set, so the second loop redoes the session's own undone edits too. Redo by the count only when no start step is in the Redo list, zero it either way, and test several Undos read back at once.
- N1: Should `write_container`'s solve refuse after `_apply`'s passed, the first refused edit would already have committed the start step.
- N2: Round 4's N1 and Round 3's N2 stand.
