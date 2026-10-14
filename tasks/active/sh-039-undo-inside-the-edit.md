---
id: sh-039
title: "Undo and Redo inside an edit"
blocked_by: [sh-037]
---

# sh-039: Undo and Redo inside an edit

## Summary
Cmd-Z and Redo, from any of FreeCAD's routes, step through the edits made
since Edit Unit opened, one edit at a time, and the panel follows. OK still
leaves one "Edit Shelving Unit" step in FreeCAD's history and Cancel still
restores the unit, however long the session ran and even when FreeCAD's
20-step history limit is reached. Today one Cmd-Z reverts the whole session
and a second reverts what came before it, under an open panel (bug-015).
Milestone M14.

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
- [ ] `Std_Undo` past the session's first edit leaves the document as the
      session opened it and shows "Nothing older to undo in this edit."
      through the panel or the Notification Area; `Std_Redo` then redoes
      the first edit.
- [ ] OK leaves FreeCAD's undo names as they were before the session plus
      one "Edit Shelving Unit" on top, an empty Redo list, and the
      session's final unit in the document; one `Std_Undo` after OK gives
      back the document as it was before the session. OK with no edits
      adds no step.
- [ ] Cancel leaves every board's name, placement and size, the object
      count, and the undo names as they were before the session, and an
      empty Redo list.
- [ ] A shelf added beside a board whose color and material were set
      keeps that color and material through an Undo and Redo of a later
      edit, and after OK.
- [ ] With FreeCAD's history at 20 steps (the `MaxUndoSize` default) and
      ten unrelated steps already in it, a session of 30 edits:
      - every `Std_Undo` from the top steps back exactly one edit, never
        more, down to the oldest edit still held one at a time;
      - `Std_Undo` below that changes nothing and shows "Nothing older to
        undo in this edit.";
      - Cancel then restores the document as before the session, and OK
        leaves exactly one "Edit Shelving Unit" step above the history
        that remains from before the session.
- [ ] A step the session did not make (a property change on an object
      outside the unit, in its own transaction, during the session) is
      never undone by the session: after Cancel the unit is as before the
      session and the foreign change is still in place; after OK the
      session's final unit and the foreign change are both in place; in
      both cases a Notification Area message says the edit could not be
      folded into one step.
- [ ] FreeCAD's Gui Redo use-after-free (below) cannot be reached through
      the editor: a test runs the sequence that crashes plain FreeCAD
      (create, delete, undo, undo, a new edit, undo, redo, all inside a
      session through `Std_Undo` and `Std_Redo`) in a FreeCAD GUI process
      started with `MALLOC_PERTURB_=165` and
      `GLIBC_TUNABLES=glibc.malloc.tcache_count=0`, and the process exits
      cleanly.
- [ ] `editor.one-session`'s "Run Edit, Undo once" step is gone from
      `freecad/Shelving/qa/cases/30-editor.toml`, replaced by the view-tier
      tests above.
- [ ] `bug-015` is deleted from `.claude/docs/bug-log.md`.

## Advice

DECISIONS (user, 2026-10-13):
- **One Cmd-Z at the top of the stack always undoes exactly one edit.**
  Nothing may make a single Undo take back several edits.
- **The history limit folds only the oldest steps.** Near the limit, the
  session's oldest steps are folded into one, and every newer step stays
  its own step under its own name. The fold is the session's floor, like
  its start: Undo there shows "Nothing older to undo in this edit." and
  changes nothing. Cancel still restores everything. Fold enough at once
  (for instance the older half) that folding is rare.
- **Steps the session did not make are detected, never undone, and
  reported.** Rewinding stops at such a step. Cancel restores the unit by
  writing the session's starting unit as a new step when a foreign step
  blocks the rewind; OK folds only the session steps above the newest
  foreign step. Either way the user is told, in the Notification Area,
  that the edit could not be folded into one step.
- **The current panel need not survive long.** Wire Undo into today's
  panel (sh-040 replaces it), enough for the Must Haves; do not polish it.

FINDINGS from the viewport spike (branch `research/viewport-editing` at
`06d20ab`, keep it until sh-041 ships;
`06d20ab:freecad/Shelving/spikes/edit_history.py` is the reference
implementation, and `06d20ab:research/viewport-editing.md` § "Findings the
spike added" has the full account):
- `Std_Undo` and `Std_Redo` reach the document from their shortcuts, the
  Edit menu, the toolbar and its drop-down list, all enabled during a task
  dialog, and a Python panel can intercept none of them. They send
  "Undo"/"Redo" to the active view, so they do nothing without a 3D view:
  test them in the view tier.
- A document observer's `slotUndoDocument` and `slotRedoDocument` fire
  inside FreeCAD's undo loop, once per step for the drop-down list; defer
  the session's update with `QTimer.singleShot(0, ...)`. The Gui
  document's `Transacting` flag tells a Gui Undo or Redo from an
  App-level one.
- The session's first step holds only the dimension probe's creation, so
  an Undo past the first edit removes nothing the user made; redo it at
  once and show the floor message.
- Clearing the Redo list after Cancel takes a transaction that records a
  change and is then aborted: setting the container's `Placement` to
  itself works; opening one, or setting `Label` to itself, clears
  nothing.
- **Gui Redo use-after-free (FreeCAD 1.1 and main):**
  `Gui::Document::undo` records each view provider it recreates in
  `_redoViewProviders`, and only `Gui::Document::redo` walks and clears
  that list. An object an Undo brought back and a later Undo removed
  again keeps a listed view provider only while that step stays in the
  history; OK, Cancel, a fold, and every new edit after an Undo drop it,
  and the next Gui Redo in the document crashes in `handleChildren3D`.
  Workaround: after each Gui Undo, run `Std_Redo` (which empties the list
  while its entries are alive) and take that step back with the App-level
  `doc.undo()`, which records no view providers; with nothing to redo,
  `Std_Undo` then `Std_Redo`. A draft upstream issue is at
  `3622341:research/spikes/freecad-issue-redo-crash.md`; keep the
  workaround version-agnostic.
- **Reading the unit back by rescanning loses `Board.stock_from`**, so the
  spike's rewrite at OK recreated added boards in default grey. Keep the
  session's own unit after each of its steps and restore from that list
  on Undo and Redo instead of rescanning; the same list is what lets the
  fold rewrite newer steps one by one. Rescan only after a foreign step
  that touched the container's objects.
- **FreeCAD's history limit:** the Gui document sets it from
  `BaseApp/Preferences/Document/MaxUndoSize` (default 20) when it is
  created, and Python cannot change it on an open document. Past the
  limit each commit drops the oldest step, so `UndoCount` stops growing:
  track the session's own steps, never positions derived from
  `UndoCount`. Steps from before the session drop first, which is
  FreeCAD's normal behavior and fine.
- The spike drove all of this through `SpikePanel`
  (`06d20ab:freecad/Shelving/spikes/viewport_panel.py`) and checks it in
  the driver's "Undo and Redo as Cmd-Z and the Edit menu run them"
  section.

CONSTRAINTS:
- `Session` owns the document's transactions (`.claude/docs/code-map.md`
  says it owns "its one transaction"; update that). Keep the history
  logic in the editor layer, testable without the panel; the panel only
  reacts to a "the unit changed" notification and shows the message.
- An Undo arriving mid-drag must not corrupt the session: finish or
  abandon the drag first.
- FreeCAD.app runs Python 3.11 while pixi runs 3.12: nothing 3.12-only;
  take `override` from `freecad.Shelving.compat` (branch
  `fix-py311-override`, which the user merges before this work starts).

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: protocols for the FreeCAD and Gui document attributes
  used (`Transacting`, `UndoNames`), no bare containers; `pyrefly check`
  clean.
- Shell stays simple: the crash test starts its subprocess from Python.
- Users never read the log: the floor message and the could-not-fold
  message reach the user in the panel or the Notification Area.

## Plan
- [x] **Step 1** (`freecad/Shelving/editor/`): A history object owning the session's transactions: one per edit, its own step list with the unit after each, the read-back on Undo and Redo, the floor, the fold near the limit, foreign-step detection, and OK and Cancel; `Session` routes every edit through it.
- [x] **Step 2** (`freecad/Shelving/editor/`): The Gui Redo workaround and the Redo-clearing transaction.
- [x] **Step 3** (`freecad/Shelving/editor/panel.py`, `freecad/Shelving/commands/edit_unit.py`): The panel refreshes after an Undo or Redo and shows the floor and could-not-fold messages; OK and Cancel go through the history.
- [x] **Step 4** (`tests/freecad/`, `tests/freecad_view/`): Headless tests for the step list, fold and floor; view-tier tests for every Must Have that runs `Std_Undo` or `Std_Redo`, and the crash-sequence subprocess test.
- [x] **Step 5** (`freecad/Shelving/qa/cases/30-editor.toml`, `.claude/docs/code-map.md`, `.claude/docs/bug-log.md`): Remove the replaced QA step, update the code map, delete bug-015.

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
