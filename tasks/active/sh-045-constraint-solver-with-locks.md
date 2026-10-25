---
id: sh-045
title: "The constraint solver, with locks as its only constraint"
---

# sh-045: The constraint solver, with locks as its only constraint

## Summary
Replaces proportional slack sharing with a small constraint solver, in the
Sketcher's manner: boards move as little as possible from where they are,
within the locks and a 5 mm minimum opening. A unit resize changes the
openings beside the edges that move and pushes inward once one reaches
5 mm. A drag pushes the boards ahead of it, and typing a size moves the
boards either side of that opening. Every opening can be locked. An axis
the locks fix completely turns its unit size into a read-only reference
that follows the other edits. An edit that over-constrains is refused with
the locks responsible outlined, and a redundant lock is accepted with a
warning. The hidden weights go, and the rule record stays at version 1 but
holds only locks. First task of milestone M18. It ships alone, so the new
resize behavior can be tried before any new constraint exists.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `freecad/Shelving/core/axis_solver.py` exists, imports only the
      standard library (nothing from `freecad.Shelving`), and defines no
      `Protocol`, ABC, or backend choice. Its own suite
      (`freecad/Shelving/core/tests/test_axis_solver.py`) asserts:
      - consistent relations, no targets: every position comes back within
        1e-9 mm of its current value;
      - `x1 - x0 = 10` and `x1 - x0 = 12` together: a conflict naming both;
      - a consistent relation that the others already imply: solved, and
        reported redundant;
      - lower bounds that the relations cannot meet: a conflict naming
        those bounds and relations;
      - the freedom query names the relations that fix a determined
        difference of positions, and reports a free one as free;
      - a weighted target with no active bound lands within 0.001 mm.
- [ ] `grep -rnwE "Weighted|Fill|distribute|_place|_driven_weight|_other_driven_anchor|_LAST_UNLOCKED|_refuse_last_unlocked|_recover_rules|no_slack_absorber" freecad tests`
      prints nothing.
- [ ] `grep -rn "MIN_DRAG_GAP_MM =" freecad` prints exactly one line, in
      `core/edit.py`. `core/axis_solver.py` and `core/solver.py` never name
      it and take the minimum opening as a parameter.
- [ ] Core suite, on a column of 18 mm boards with fixed point `min`:
      bottom, bay A 300, shelf, bay B 300, top (654 mm tall):
      - growing it to 754 mm gives A 300, B 400, and the shelf unmoved;
      - shrinking it to 254 mm gives B 5 and A 195;
      - shrinking it to 60 mm is refused, the conflict naming A's and B's
        minimums;
      - with fixed point `center`, growing it to 754 mm gives A 350, B 350,
        and the shelf unmoved;
      - typing 4 mm into A is refused; typing 5 mm is accepted (bug-019);
      - locking A, then B, is accepted; the height then reads as fixed by
        A and B, `set_unit_size` to another height raises the conflict
        naming A and B, and typing 350 into A gives a 704 mm unit whose
        bottom stays put and whose B stays 300;
      - `held_by` of the shelf is `(A,)` with A locked, `(A, B)` with both
        locked, `()` with neither locked; for the top or bottom board it is
        `None`.
- [ ] Core suite, on a column of 18 mm boards with fixed point `min`:
      bottom, A 300, shelf s1, B 300, shelf s2, C 300, top (972 mm tall):
      - typing 340 into B gives A 280, B 340, C 280;
      - dragging s1's low face to 718 gives A 700, B 5, C 195, with s1's
        low face within 0.001 mm of 718;
      - dragging s1's low face to 2000 stops it at 908: A 890, B 5, C 5;
      - with B locked, dragging s1 50 mm up gives A 350, B 300, C 250, and
        s2 moves 50 mm too.
- [ ] Core suite: when one column's locks already fix a unit's height,
      locking the last unlocked opening of a second column is accepted.
      The redundancy query reports the new lock, and the locks it
      duplicates include the first column's.
- [ ] Core suite: a scan gives every region its measured size and locks
      only what it locks today: a void beside a bay or division, and an
      axis-wrap division. A unit read and solved with no edit keeps every
      board within 1e-6 mm.
- [ ] `rules_to_json` emits exactly
      `{"schema_version": 1, "locks": {<key>: {"basis": "clear" | "with_next"}}}`,
      with one entry per locked region and none for an unlocked one.
      `rules_from_json` on a record in any other shape, including the old
      `"rules"` shape, gives no locks and raises nothing. Headless
      (`tests/freecad/`): a container carrying an old-shape record opens
      in `Session`, with every opening unlocked.
- [ ] Headless: locking a redundant opening through `Session` applies the
      lock and reports a warning naming the locks it duplicates. A
      refused conflict returns an `EditFailure` that carries the
      responsible region ids, and leaves the document untouched.
- [ ] Every opening's dimension carries a padlock: `DimensionLabel` has no
      `lockable` field, and `tests/freecad_view/test_padlocks.py` asserts a
      padlock on a run's only opening.
- [ ] GUI (`tests/freecad_gui/test_panel.py`): with both openings of the
      single-shelf column locked, the Height field is read-only and Width
      and Depth are editable; unlocking either opening makes Height
      editable again.
- [ ] 3D view (`tests/freecad_view/`): after a refused edit, the regions
      its `EditFailure` names carry the holding outline. The outline clears
      on the next edit or selection change. A redundant lock's duplicated
      locks are outlined the same way.
- [ ] `README.md`'s glossary entries **Size rule** and **The drag rule**
      contain neither "weighted share" nor "One opening in each row
      stays unlocked", and `docs/scope-and-design.md` no longer contains
      "alone in its run shows no padlock".
- [ ] `bug-019` is deleted from `.claude/docs/bug-log.md`.

## Advice
- **Tree carries current geometry.** Every non-root region stores its
  current clear size along its run, and a lock is a basis on the region
  (`None` when unlocked). `Weighted` and `Fill` are deleted. A board's
  extent override stays a fixed size. Reason: the solve minimizes motion
  from where the boards are now, so the tree must hold that; the weights
  encoded the same sizes as hidden shares.
- **Every edit solves its own result.** Each edit in `core/edit.py`
  returns a unit whose stored sizes the engine has already solved, and
  `solve(unit)` in `core/solver.py` only lays out the stored geometry and
  checks it (pinned boards, sizes that fit). Reason: the pre-edit geometry
  is the reference for minimal motion, and only the edit holds both it
  and the change. Reword the module docstrings that say edits never
  re-solve.
- **The engine** (`core/axis_solver.py`): one model axis per call, opaque,
  pure Python, standard library only, with no `Protocol` or swappable
  backend (user decision). Inputs: named positions with current values;
  relations, each a general linear equality with an id; lower bounds on a
  difference of positions, each with an id; weighted targets. General
  linear, because task 2's Equal and Even spacing are not differences.
  Output: either the solved positions, a freedom query and the redundant
  relation ids; or the conflicting relation and bound ids and the
  redundant ones. Method: bounded least squares with an active set,
  minimizing the sum of each board's squared low-face motion (weight 1),
  plus each target weighted heavily enough to land within 0.001 mm.
  Consistent redundant equalities must solve, not fail: a fully locked
  axis and documents that already hold redundant locks both produce them.
  No numpy: systems are tens of positions, and the core suite stays free
  of dependencies.
- **System builder** (`core/solver.py`): positions are each board's low
  face on runs along the axis plus the unit's two outer faces. Every
  region edge is expressed through those. Relations: each board's
  thickness (or extent override), each lock in its basis, and the fixed
  point (min face, midpoint or max face) always. The unit's size counts as
  a relation only when the other relations leave it free. Lower bounds:
  every region (bay, void, division) at least `min(minimum, current
  size)`, so an opening already narrower is not pushed open. The minimum
  is a parameter that `core/edit.py` fills from `MIN_DRAG_GAP_MM`. The
  solver cannot import it, because `edit` imports `solver`, and the
  roadmap keeps one named value that a preference can replace later. The
  preference itself is sh-023's.
- **Resize:** on a free axis, the openings beside the moving outer faces
  take up the change and push inward once one reaches its minimum. That
  falls out of minimal motion.
- **Reference axis:** on an axis the locks determine, the unit's size is a
  reference, as in the Sketcher. `set_unit_size` changing it raises the
  conflict naming the locks that fix it, and the panel's field for it is
  read-only. Every other edit (typed size, thickness, split, merge) lets
  it follow, with the fixed point's side holding (user decision). Depth
  is never divided, so its field stays editable.
- **Drag:** the dragged board's low face is a weighted target. The outer
  faces hold, and every other board keeps its motion term, so once an
  opening reaches its minimum the drag pushes the boards ahead of it
  (user decision, Sketcher precedent: dragged geometry reaches the
  pointer when any solution allows it, and other geometry moves only as
  the constraints force). A drag never locks or unlocks anything.
- **Typed size** locks the opening at that size. When both bounding
  boards are free, each moves half the change (user decision). A typed
  size below `MIN_DRAG_GAP_MM` is refused in `set_size` whatever the
  opening's current size, because the scanner drops anything narrower on
  the next read (bug-019).
- **The one-unlocked-opening rule retires.** Any opening may lock, and
  every opening's dimension shows a padlock.
- **`held_by`** comes from the engine's freedom query with the outer faces
  held. It returns `()` when a drag may move the board. Otherwise it
  returns the fewest locks whose unlocking frees the board, the one
  nearest the board on each blocked side, low side first. It returns
  `None` when no unlock frees it, as for a carcass board. `require_movable`,
  `arrow_for` and the held padlock keep their meaning on top of it.
- **Conflict:** refused through the editor's existing path,
  `EditFailure` then `report_error`. `EditFailure` gains the region ids
  the conflict names: its locks, plus any opening held at its minimum.
  The view draws them with the existing holding outline until the next
  edit or selection change (user decision). The Sketcher accepts a
  conflicting constraint and leaves the sketch in error; this editor
  refuses, because an unsolvable layout has no boxes to write (roadmap).
- **Redundant lock:** accepted with a Notification Area warning, and the
  locks it duplicates are outlined as for a refusal (user decision:
  Sketcher accepts and flags). Task 3's constraint list will mark these
  locks persistently. A lock that only turns the unit's size into a
  reference is not redundant. Redundancy already present when Edit Unit
  opens is tolerated without a message; task 2 owns how constraints
  behave across sessions.
- **Scan** gives regions their measured sizes and recovers no lock except
  the two it sets today: a void beside a bay or division, so a plinth gap
  holds still, and an axis-wrap division at its slot.
- **Record** stays `schema_version` 1 with a rewritten shape (user
  decision: no version 2, no backward compatibility). It stores only
  locks and their basis, no size, since a lock takes its scanned size on
  read as it does today. A record in any other shape reads as no record:
  `scope-and-design.md` already says a missing or stale record falls back
  to inference, and raising would make every existing unit unopenable.
  The `ShelvingRules` property keeps its name.
- **Typed Python:** positions are a `NewType` over `str`; relations,
  bounds, targets and results are frozen dataclasses; signatures use no
  bare `dict` or `list`.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher, as cited for drag,
  reference dimension, redundancy and conflict above.
- **Users never read the log:** refusals and the redundancy warning reach
  the user through the Notification Area and the outline.
- **Speed:** every pointer move during a drag runs a solve. The
  `large_unit` fixture, four columns of six openings, must keep up with
  the pointer, which manual QA case `editor.large-unit` checks. Add no
  timing assertion, because it would be flaky.
- **No new manual QA case:** a test asserts every outcome here. The
  existing `editor.navigation`, `editor.large-unit` and `editor.padlocks`
  expectations stay true; keep them true.
- **Out of scope:** the roadmap's "locking a second Equal is redundant and
  refused" belongs to task 2; bug-021 (a copy loses its locks) stays open.

## Plan
- [ ] **Step 1** (`core/axis_solver.py`, `core/tests/test_axis_solver.py`):
      the engine and its suite, per the Must Have.
- [ ] **Step 2** (`core/layout.py`, `core/tests/test_layout.py`): regions
      carry their current clear size and an optional lock basis; delete
      `Weighted` and `Fill`.
- [ ] **Step 3** (`core/solver.py`, `core/tests/test_solver.py`): `solve`
      lays out stored geometry and checks it. A per-axis system builder
      and an apply-back turn a unit, plus an edit's change (outer size,
      lock, thickness, drag target) and the minimum opening, into engine
      calls and a solved unit. It also exposes the queries `core/edit.py`
      needs: whether an axis is determined and by which locks, a board's
      freedom with its fixing locks, and the redundant locks with what
      each duplicates. Delete `distribute`, `_place` and `_driven_weight`.
      Reduce `SolveErrorReason` to the reasons that can still occur, add
      a conflict error carrying the responsible region ids, and update
      `describe_solve_error`.
- [ ] **Step 4** (`core/edit.py`, `core/tests/test_edit.py`): every edit
      returns a solved unit. Rework `set_unit_size` (reference axis
      refusal), `set_size` (minimum refusal), `set_basis`, `lock`,
      `unlock`, `move_board` (target, push), `set_thickness`,
      `split_region` and `merge_at` (sizes in place of weights),
      `held_by` and `require_movable` (from freedom), and `measure`.
      Delete `_LAST_UNLOCKED`, `_refuse_last_unlocked`, `_driven_weight`
      and `_other_driven_anchor`. `MIN_DRAG_GAP_MM` stays here as the one
      definition.
- [ ] **Step 5** (`core/scan.py`, `core/tests/test_scan.py`,
      `core/tests/test_scanned_units.py`): measured sizes, no
      `_recover_rules`, and the void and axis-wrap locks kept.
- [ ] **Step 6** (`core/record.py`, `core/tests/test_record.py`): the
      rewritten version 1 shape, a malformed record read as none, and
      `with_stored_rules` applying locks at scanned sizes. Update the
      module docstring and `unit_ops.unit_size_mm`'s "ValueError when
      malformed" clause.
- [ ] **Step 7** (`core/expand.py`, `core/stock.py`, `core/backs.py`,
      `unit_ops.py`, `container.py`, `core/tests/test_stock.py`,
      `core/tests/test_expand.py`, `core/tests/test_backs.py`): build and
      write units with sizes. `unit_ops._default_unit` gives its bays
      concrete sizes, and `resize_unit` raises the conflict on a
      reference axis.
- [ ] **Step 8** (`refusals.py`, `tests/freecad/test_refusals.py`,
      `tests/freecad_gui/test_refusals.py`): `SUGGESTIONS` matches the
      reduced reasons; add a Notification Area warning beside
      `report_error`.
- [ ] **Step 9** (`editor/session.py`, `editor/elevation.py`,
      `editor/overlay.py`, `editor/view_editor.py`, `editor/panel.py`,
      `editor/fields.py`; tests in `tests/freecad/test_editor_session.py`,
      `tests/freecad/test_edit_history.py`, `tests/freecad/test_write.py`,
      `tests/freecad/test_backs.py`, `tests/test_editor_elevation.py`,
      `tests/freecad_gui/test_panel.py`, `tests/freecad_view/test_padlocks.py`,
      `tests/freecad_view/test_editor_drawing.py`,
      `tests/freecad_view/test_editor_input.py`,
      `tests/freecad_view/test_scan_and_write.py`):
      - `EditFailure` carries the responsible region ids;
      - the session reports a redundant lock as a warning and exposes
        whether each unit axis is a reference;
      - `DimensionLabel.lockable` goes;
      - the overlay outlines the regions of a refusal or warning until the
        next edit or selection change;
      - the panel makes a reference axis's size field read-only.
- [ ] **Step 10** (`README.md`, `docs/scope-and-design.md`,
      `.claude/docs/bug-log.md`):
      - rewrite the glossary entries Size rule and The drag rule:
        minimal motion, push at 5 mm, any opening locks, reference axis;
      - in `scope-and-design.md`, fix the opening paragraph's "shelves
        redistribute", the Editing section's padlock paragraph (no lone
        exception, no "shares behind unlocked openings"), and "What is
        stored" (a record of locks);
      - delete bug-019.

## Review log
