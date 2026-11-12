---
id: sh-046
title: "Lay units out with the constraint engine"
blocked_by: [sh-045]
---

# sh-046: Lay units out with the constraint engine

## Summary
Moves layout onto sh-045's engine, in the Sketcher's manner: boards move as
little as possible from where they are, within the locks and a 5 mm minimum
opening. A unit resize changes the openings beside the edges that move, and
pushes inward once one reaches 5 mm. A drag pushes the boards ahead of it.
Typing a size moves the boards on either side of that opening. An edit that
cannot be met is refused, and so is typing a size under 5 mm (bug-019). The
hidden weights go, and the rule record stays at version 1 but holds only
locks. The rule that one opening in each run stays unlocked still holds;
sh-047 retires it. This task ships alone so the new resize behavior can be
tried before any new constraint exists.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `grep -rnwE "Weighted|Fill|distribute|_place|_driven_weight|_other_driven_anchor|_recover_rules|no_slack_absorber" freecad tests`
      prints nothing.
- [ ] `grep -rn "MIN_DRAG_GAP_MM =" freecad` prints exactly one line, in
      `core/edit.py`. `core/axis_solver.py` and `core/solver.py` never name
      it and take the minimum opening as a parameter.
- [ ] Core suite, on a column of 18 mm boards with fixed point `min`:
      bottom, bay A 300, shelf, bay B 300, top (654 mm tall):
      - growing it to 754 mm gives A 300, B 400, and the shelf unmoved;
      - shrinking it to 254 mm gives B 5 and A 195;
      - shrinking it to 60 mm is refused, with a conflict naming A and B;
      - with fixed point `center`, growing it to 754 mm gives A 350, B 350,
        and the shelf unmoved;
      - typing 4 mm into A is refused; typing 5 mm is accepted (bug-019);
      - with A locked and fixed point `center`, growing it to 754 mm gives
        A 300 and B 400, and the shelf moves 50 mm down with the bottom;
      - `held_by` of the shelf is `(A,)` with A locked and `()` with
        neither locked; for the top or bottom board it is `None`.
- [ ] Core suite, on a column of 18 mm boards with fixed point `min`:
      bottom, A 300, shelf s1, B 300, shelf s2, C 300, top (972 mm tall):
      - typing 340 into B gives A 280, B 340, C 280;
      - dragging s1's low face to 718 gives A 700, B 5, C 195, with s1's
        low face within 0.001 mm of 718;
      - dragging s1's low face to 2000 stops it at 908: A 890, B 5, C 5;
      - with B locked, dragging s1 50 mm up gives A 350, B 300, C 250, and
        s2 moves 50 mm too.
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
- [ ] Headless: a refused conflict through `Session` returns an
      `EditFailure` and leaves the document untouched.
- [ ] `README.md`'s glossary entries **Size rule** and **The drag rule**
      do not contain "weighted share".
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
- **System builder** (`core/solver.py`): positions are each board's low
  face on runs along the axis plus the unit's two outer faces. Every
  region edge is expressed through those. Relations: each board's
  thickness (or extent override), each lock in its basis, and the fixed
  point (min face, midpoint or max face) always. The unit's size counts as
  a relation only when the other relations leave it free. Lower bounds:
  every region (bay, void, division) at least `min(minimum, current
  size)`, so an opening already narrower is not pushed open. The engine's
  motion term is one per board low face, weight 1. The minimum is a
  parameter that `core/edit.py` fills from `MIN_DRAG_GAP_MM`. The solver
  cannot import it, because `edit` imports `solver`, and the roadmap keeps
  one named value that a preference can replace later. The preference
  itself is sh-023's.
- **Engine interface** (added 2026-11-12, after sh-045 shipped): call
  `axis_solver.solve(current_mm, relations, bounds, targets)`, which
  returns `Solved` (`positions_mm`, `active_bounds`, `redundant`,
  `freedom(expression)`) or `Conflict` (`conflicting`, `redundant`).
  - **Ids:** constraint ids must be unique across relations and bounds
    (`ValueError` otherwise), so give a region's lock and its minimum
    bound distinct ids that map back to the region, such as
    `<region>:lock` and `<region>:min`.
  - **Size relation:** list structural relations first (thicknesses,
    fixed point), then locks, then the unit's size last. The engine flags
    the later member of a dependent group as redundant, so a consistent
    size implied by a fully locked run drops out and an inconsistent one
    conflicts. That gives the "counts only when free" rule above with no
    separate freedom query.
  - **`held_by`:** `freedom` counts tight bounds as fixing. A drag pushes
    through an opening held at its minimum, so query a solve passed no
    bounds: relations with the outer faces held. Keep only lock ids from
    `fixed_by`; it also names thickness and outer-face relations.
  - **Tests:** `Solved` carries a private basis and cannot be built by
    hand, so drive tests through real engine calls rather than fakes.
  - **Drags:** the default `TARGET_WEIGHT` lands a drag within about
    1e-4 mm for 40 positions moved 3 m. A 40-position solve takes about
    3 ms.
- **Resize:** the openings beside the moving outer faces take up the
  change and push inward once one reaches its minimum. That falls out of
  minimal motion.
- **Drag:** the dragged board's low face is a weighted target. The outer
  faces hold, and every other board keeps its motion term, so once an
  opening reaches its minimum the drag pushes the boards ahead of it, in
  nested runs too (user decision, Sketcher precedent: dragged geometry
  reaches the pointer when any solution allows it, and other geometry
  moves only as the constraints force). A drag never locks or unlocks
  anything.
- **Typed size** locks the opening at that size. When both bounding
  boards are free, each moves half the change (user decision). A typed
  size below `MIN_DRAG_GAP_MM` is refused in `set_size` whatever the
  opening's current size, because the scanner drops anything narrower on
  the next read (bug-019).
- **`held_by`** comes from the engine's freedom query with the outer faces
  held, because a drag can now push boards in other runs. It returns `()`
  when a drag may move the board. Otherwise it returns the fewest locks
  whose unlocking frees the board, the one nearest the board on each
  blocked side, low side first. It returns `None` when no unlock frees it,
  as for a carcass board. `require_movable`, `arrow_for` and the held
  padlock keep their meaning on top of it.
- **The one-unlocked-opening rule stays** (`_refuse_last_unlocked`,
  `DimensionLabel.lockable`). While every run keeps a free opening, no
  axis is determined and no lock is redundant, so the reference axis and
  the redundancy warning can wait for sh-047. A run the scan leaves fully
  locked, or a redundancy a document already holds, solves without a
  message: the engine accepts consistent redundancy.
- **Conflict:** `core/solver.py` raises a conflict `LayoutSolveError`
  carrying the region ids the engine names: its locks, plus any opening
  held at its minimum. The editor refuses through its existing path,
  `EditFailure` then `report_error`, and `describe_solve_error` words it.
  Outlining those regions is sh-047's. The Sketcher accepts a conflicting
  constraint and leaves the sketch in error; this editor refuses, because
  an unsolvable layout has no boxes to write (roadmap).
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
- **Typed Python:** signatures use no bare `dict` or `list`; reuse the
  engine's id `NewType`s at the boundary.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher, as cited for drag and
  conflict above.
- **Users never read the log:** a refusal reaches the user through the
  Notification Area, as every editor refusal does.
- **Speed:** every pointer move during a drag runs a solve. The
  `large_unit` fixture, four columns of six openings, must keep up with
  the pointer, which manual QA case `editor.large-unit` checks. Add no
  timing assertion, because it would be flaky.
- **No new manual QA case:** a test asserts every outcome here. The
  existing `editor.navigation`, `editor.large-unit` and `editor.padlocks`
  expectations stay true; keep them true.
- **Out of scope:** the reference axis, the redundancy warning, the
  conflict outline and retiring the one-unlocked rule (sh-047); bug-021
  (a copy loses its locks) stays open.

## Plan
- [ ] **Step 1** (`core/layout.py`, `core/tests/test_layout.py`): regions
      carry their current clear size and an optional lock basis; delete
      `Weighted` and `Fill`.
- [ ] **Step 2** (`core/solver.py`, `core/tests/test_solver.py`): `solve`
      lays out stored geometry and checks it. A per-axis system builder
      and an apply-back turn a unit, plus an edit's change (outer size,
      lock, thickness, drag target) and the minimum opening, into engine
      calls and a solved unit. It also exposes a board's freedom with its
      fixing locks, for `held_by`, from a solve without bounds (Advice:
      Engine interface). Delete `distribute`, `_place` and
      `_driven_weight`. Reduce `SolveErrorReason` to the reasons that can
      still occur, add the conflict error carrying region ids, and update
      `describe_solve_error`.
- [ ] **Step 3** (`core/edit.py`, `core/tests/test_edit.py`): every edit
      returns a solved unit. Rework `set_unit_size`, `set_size` (minimum
      refusal), `set_basis`, `lock`, `unlock`, `move_board` (target,
      push), `set_thickness`, `split_region` and `merge_at` (sizes in
      place of weights), `held_by` and `require_movable` (from freedom),
      and `measure`. Delete `_driven_weight` and `_other_driven_anchor`.
      `MIN_DRAG_GAP_MM` stays here as the one definition.
- [ ] **Step 4** (`core/scan.py`, `core/tests/test_scan.py`,
      `core/tests/test_scanned_units.py`): measured sizes, no
      `_recover_rules`, and the void and axis-wrap locks kept.
- [ ] **Step 5** (`core/record.py`, `core/tests/test_record.py`): the
      rewritten version 1 shape, a malformed record read as none, and
      `with_stored_rules` applying locks at scanned sizes. Update the
      module docstring and `unit_ops.unit_size_mm`'s "ValueError when
      malformed" clause.
- [ ] **Step 6** (`core/expand.py`, `core/stock.py`, `core/backs.py`,
      `unit_ops.py`, `container.py`, `core/tests/test_stock.py`,
      `core/tests/test_expand.py`, `core/tests/test_backs.py`): build and
      write units with sizes. `unit_ops._default_unit` gives its bays
      concrete sizes.
- [ ] **Step 7** (`refusals.py`, `tests/freecad/test_refusals.py`,
      `tests/freecad_gui/test_refusals.py`): `SUGGESTIONS` matches the
      reduced reasons, with one for a conflict.
- [ ] **Step 8** (`tests/freecad/test_editor_session.py`,
      `tests/freecad/test_edit_history.py`, `tests/freecad/test_write.py`,
      `tests/freecad/test_backs.py`, `tests/test_editor_elevation.py`,
      `tests/freecad_view/test_editor_input.py`,
      `tests/freecad_view/test_scan_and_write.py`, and the editor modules
      under `editor/` where they build or read rules): update every test
      that asserts proportional sharing to the minimal-motion outcome, and
      add the headless old-record and conflict tests from the Must Have.
- [ ] **Step 9** (`README.md`, `docs/scope-and-design.md`,
      `.claude/docs/bug-log.md`):
      - rewrite the glossary entries Size rule and The drag rule: minimal
        motion, push at 5 mm;
      - in `scope-and-design.md`, fix the opening paragraph's "shelves
        redistribute", the "shares behind unlocked openings" wording in
        the Editing section, and "What is stored" (a record of locks);
      - delete bug-019.

## Review log
