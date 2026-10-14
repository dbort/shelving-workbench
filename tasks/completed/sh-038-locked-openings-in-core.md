---
id: sh-038
title: "Locked openings, and a drag that moves only what it drags"
---

# sh-038: Locked openings, and a drag that moves only what it drags

## Summary
An opening is locked at its size or unlocked to share what is left, and the
core gains locking and unlocking that move nothing. A drag then moves only
the dragged board, together with any board joined to it through locked
openings, instead of shifting every shelf that shares leftover space; a
board with only locks between it and the end of its row is held. A rescan
keeps each opening's lock and basis but takes its size from the geometry,
which fixes a hand-moved shelf snapping back (bug-007). No new controls:
sh-041 adds the padlocks. Milestone M14.

## Must Have
- [x] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [x] `core.edit` treats a region with a `Fixed` rule as locked and one
      with `Weighted` or `Fill` as unlocked; the rule record's schema is
      unchanged.
- [x] A core edit locks or unlocks a region and moves nothing: on any
      unit, `solve` gives every node the same space before and after.
      Locking gives `Fixed` at the region's solved clear size; unlocking
      gives the `Weighted` share that holds its solved size, or `Fill`
      when it is the run's only unlocked region. Locking or unlocking a
      region already in that state returns the unit unchanged.
- [x] Locking the last unlocked region in a run raises `EditError` naming
      it, with the message "One opening in each row stays unlocked, to
      take up changes to the unit's size." `set_size` and `set_basis`,
      which lock, refuse the same way when they would lock a run's last
      unlocked region. A run that already has no unlocked region (from an
      older record) is not refused anything it was allowed before.
- [x] A core query gives, for a board, the locked regions to unlock so a
      drag may move it: on each side where only boards and locked regions
      lie between it and the end of its run, the locked region nearest
      the board. It is empty when a drag may move the board, and `None`
      when a side holds no region at all (a carcass board).
- [x] `move_board(unit, board_id, low_face_mm)` puts the board's low face
      at `low_face_mm`, moves every board joined to it through locked
      regions by the same distance, and resizes only the first unlocked
      region on each side, which stay unlocked; every other region keeps
      its solved size. It raises `EditError` naming the board when the
      query above gives `None`, naming the nearest holding region when it
      gives a non-empty tuple, and naming the region the move would leave
      no positive size. Asserted in the core suite on a column of three
      200 mm bays between 20 mm boards (680 mm tall):
      - the lowest shelf moved 50 mm up gives bays of 250, 150 and 200 mm,
        all unlocked, and the unit then made 90 mm taller gives 287.5,
        172.5 and 230 mm;
      - with the middle bay locked, the lowest shelf moved 30 mm up gives
        230, 200 and 170 mm, and the upper shelf moves 30 mm too;
      - with the lower two bays locked, the query gives the lower bay for
        the lowest shelf and the middle bay for the upper shelf, and
        `move_board` on either raises naming those;
      - the query gives `None` for the top and bottom boards.
- [x] Splitting a locked bay gives two locked halves, and merging gives a
      locked region only when both merged regions were locked, as today.
- [x] A rescan takes sizes from geometry and lock state and basis from the
      stored record (bug-007). Asserted in the core suite on scanned units
      with stored records:
      - a stored unlocked region whose scanned size changed keeps the
        scanned rule;
      - a stored `Fixed(250, CLEAR)` region scanned at 260 mm becomes
        `Fixed(260, CLEAR)`; a stored `Fixed` with `Basis.WITH_NEXT` keeps
        that basis, its size restated so `solve` reproduces the geometry;
      - a stored unlocked region the scan fixed (a void) becomes unlocked
        at the share that holds its scanned size;
      - a region with no stored entry keeps the scanned rule.
- [x] Headless (`tests/freecad/`): add a shelf through `Session`, commit,
      move the shelf 60 mm down by setting its `Placement`, and
      `unit_ops.rescan_unit` leaves it where it was moved (bug-007's
      reproduction).
- [x] `Session` gains a lock/unlock of several regions as one write,
      returning `EditFailure` on refusal with the document untouched, and
      exposes the board query; `begin_drag` returns an `EditFailure` and
      starts no drag for a held board or one the query gives `None` for.
      Asserted headless.
- [x] `bug-007` is deleted from `.claude/docs/bug-log.md`.
- [x] The README glossary's "Size rule" and "The drag rule" entries
      describe locked and unlocked openings and the drag above, in user
      vocabulary; `tests/test_readme_glossary.py` passes.

## Advice

DECISIONS (user, 2026-10-13, in the viewport-editing research):
- **Vocabulary.** The user thinks of a fixed opening as locked and one
  sharing leftover space as unlocked. Weights never appear in the
  interface.
- **Locking and unlocking never move anything.** Unlocking reweights so
  the opening holds its current size until the unit or a neighbor
  changes.
- **The last unlocked opening in a row cannot be locked**, so a change to
  the unit's size always has somewhere to go.
- **Typing a size locks the opening** (today's `set_size`), and the
  unlocked openings in its row absorb the difference.
- **A lock keeps its size through a drag by moving with it.** With two
  shelves around one locked opening, either shelf drags and the other
  follows. A drag never locks or unlocks anything.
- **Held:** only when, on some side, nothing but boards and locked
  openings lie between the board and the end of its row. The query names
  the nearest locked opening on each such side because unlocking those
  frees the board; sh-041's padlock does exactly that.
- **Splitting a locked bay keeps both halves locked** (today's behavior).
- **Geometry wins on a rescan** (bug-007): hand edits are always taken
  up; the record contributes only what geometry cannot say, the lock and
  the basis.
- **The current editor need not keep working well.** sh-040 replaces it.
  Update its GUI tests to the new rules, or delete those that only
  assert the old drag rule.

CONSTRAINTS:
- Reweighting keeps the run's total weight: with `u` the size one unit
  of weight gets in the run, each resized region's weight becomes its new
  size over `u`. `_other_driven_anchor` in `core/edit.py` already finds a
  run's `u`; reuse it rather than adding a second helper.
- A run's unlocked regions all share one `u`, but the scan's
  `_recover_rules` mixes nothing: `Fill` for an equal run, size-valued
  `Weighted` otherwise. Keep any rule the bug-007 merge produces
  consistent with that, so a run never mixes `Fill` with size-valued
  weights (that moves boards).
- `Basis.WITH_NEXT` sizes are restated through `_size_in_basis_mm`, as
  `move_board` does today, never by hand.
- `region_before` stays: sh-040 places the drag arrow beside that region's
  dimension. `Session.drag_to` keeps selecting as it does; sh-040 changes
  what a viewport drag selects.
- The spike's version of the drag and query is the reference:
  `06d20ab:freecad/Shelving/spikes/local_move.py` on branch
  `research/viewport-editing` (keep that branch until sh-041 ships). Its
  checks in `06d20ab:research/spikes/drive_viewport_spike.py` under "A
  locked opening carries the boards beside it" show the intended
  behavior.

USERS OF THE CHANGED NAMES (grep before changing):
- `move_board`, `region_before`: `freecad/Shelving/core/edit.py`,
  `freecad/Shelving/editor/session.py`,
  `freecad/Shelving/core/tests/test_edit.py` (the `set_size / set_basis /
  move_board` section), `freecad/Shelving/core/tests/test_scanned_units.py`
  (around its `move_board` call).
- `with_stored_rules`: `freecad/Shelving/core/record.py`,
  `freecad/Shelving/unit_ops.py` (`_rescanned_unit`),
  `freecad/Shelving/editor/session.py` (`_read_unit`),
  `freecad/Shelving/core/tests/test_record.py` (the `with_stored_rules`
  and round-trip tests); the record module's docstring describes what the
  record is for and needs the new precedence.
- Drags through the session: `tests/freecad/test_editor_session.py`
  (around `begin_drag`), `tests/freecad_gui/test_panel.py` (the drag tests
  asserting `Fixed` rules after a drag, including
  `test_a_drag_keeps_the_basis`).
- Prose: `README.md` glossary, `docs/scope-and-design.md` (the rules
  paragraph and "Geometry cannot say two things"), and the `drag` step of
  `editor.dimensions` in `freecad/Shelving/qa/cases/30-editor.toml`, which
  drags a shelf held by the locked lower bay and must now expect the
  refusal.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: precise types, `pyrefly check` clean; the query returns
  `tuple[str, ...] | None`, never a bare `tuple`.
- Shell stays simple: no shell.
- Users never read the log: every refusal is an `EditError` or
  `EditFailure` the editor already reports through the Notification Area.

## Plan
- [x] **Step 1** (`freecad/Shelving/core/edit.py`, `freecad/Shelving/core/tests/test_edit.py`): Lock and unlock edits, the last-unlocked refusal in them and in `set_size` and `set_basis`, the held-by query, and `move_board`'s new rule, with the Must Have core tests; update or replace the tests asserting the old drag rule.
- [x] **Step 2** (`freecad/Shelving/core/record.py`, `freecad/Shelving/core/tests/test_record.py`, `freecad/Shelving/core/tests/test_scanned_units.py`): The rescan precedence: lock and basis from the record, size from geometry, with the bug-007 core tests.
- [x] **Step 3** (`freecad/Shelving/editor/session.py`, `tests/freecad/test_editor_session.py`, `tests/freecad/test_write.py`): Session lock/unlock and query, `begin_drag`'s refusal, and the headless bug-007 reproduction.
- [x] **Step 4** (`tests/freecad_gui/test_panel.py`): Bring the panel's drag tests to the new rule, or delete those that only asserted the old one.
- [x] **Step 5** (`README.md`, `docs/scope-and-design.md`, `freecad/Shelving/qa/cases/30-editor.toml`, `.claude/docs/bug-log.md`): Glossary and design prose for locked openings and the drag; the QA drag step's expectation; delete bug-007.

## Review log

### Round 1: REJECTED
- **F1: The QA `drag` step expects a state the panel cannot show** (`freecad/Shelving/qa/cases/30-editor.toml:94`): after a refused drag the shelf is selected, so Size is blank and the basis combo disabled; the `expression` step then sizes nothing. The panel test does not assert the selection after the refused drag.
- **F2: The record hand-copies the WITH_NEXT restatement** (`freecad/Shelving/core/record.py:295`): call one shared helper from `edit` and `record`.
- **F3: `Session.__init__` lets a raw `LayoutSolveError` escape for a unit with a record** (`freecad/Shelving/editor/session.py:184`): `with_stored_rules` now solves inside `_read_unit`, outside the `try` that wraps `UnsolvableUnit`; docstrings of `unit_size_mm`, `UnsolvableUnit` and `Session.__init__` are stale.
- **F4: A held board's refusal reaches the user nowhere** (`freecad/Shelving/editor/panel.py:668`): report it, for example once on the first drag motion, and update the stale comment.
- N1: The overflow, no_slack_absorber and nonpositive_opening suggestions blame stored sizes.
- N2: `test_move_board_refuses_a_board_with_no_region_before_it` is misnamed.
- N3: No test for a drag past the opening above.
- N4: The void merge is tested only on a hand-built unit.

### Round 2: APPROVED
- N1: The record merge's WITH_NEXT fallback (`record.py:286`) has no test; only a hand-edited or corrupt record reaches it.
- N2: No test that a plain click on a held board stays quiet; the `startDragDistance` gate keeps it quiet by reading.
- N3: Dragging a carcass board now pops up "This board has no opening on each side to move."; neither the QA case nor the Advice mentions it.
- N4: Round 1's N1 (suggestion texts blame stored sizes) and N4 (void merge tested on a hand-built unit) stand.
