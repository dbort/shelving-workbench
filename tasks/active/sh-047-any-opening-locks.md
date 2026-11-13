---
id: sh-047
title: "Any opening locks, with reference sizes and constraint feedback"
blocked_by: [sh-046]
---

# sh-047: Any opening locks, with reference sizes and constraint feedback

## Summary
Retires the rule that one opening in each run stays unlocked, so every
opening shows a padlock and any of them can lock. When the locks fix an
axis completely, the unit's size along it becomes a read-only reference, as
a Sketcher reference dimension is, and it follows the other edits. A
redundant lock is accepted with a warning. A refused edit now outlines the
locks and openings responsible, and so does that warning. This completes
M18's first task: the solver, with locks as its only constraint.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `grep -rnwE "_LAST_UNLOCKED|_refuse_last_unlocked|lockable" freecad tests`
      prints nothing.
- [ ] Core suite, on a column of 18 mm boards with fixed point `min`:
      bottom, bay A 300, shelf, bay B 300, top (654 mm tall):
      - locking A, then B, is accepted, and the height then reads as fixed
        by A and B;
      - `set_unit_size` to another height then raises the conflict naming
        A and B, while changing the width or depth is accepted;
      - typing 350 into A then gives a 704 mm unit whose bottom stays put
        and whose B stays 300;
      - `held_by` of the shelf is `(A, B)` with both locked.
- [ ] Core suite: when one column's locks already fix a unit's height,
      locking the last unlocked opening of a second column is accepted.
      The redundancy query reports the new lock, and the locks it
      duplicates include the first column's. A lock that only turns the
      height into a reference is not reported redundant.
- [ ] Headless (`tests/freecad/`): locking a redundant opening through
      `Session` applies the lock and reports a warning naming the locks it
      duplicates. A refused conflict returns an `EditFailure` that carries
      the responsible region ids, and leaves the document untouched.
      A unit whose record already holds a redundant lock opens in
      `Session` with no warning.
- [ ] Every opening's dimension carries a padlock:
      `tests/freecad_view/test_padlocks.py` asserts a padlock on a run's
      only opening.
- [ ] GUI (`tests/freecad_gui/test_panel.py`): with both openings of the
      single-shelf column locked, the Height field is read-only and Width
      and Depth are editable; unlocking either opening makes Height
      editable again.
- [ ] 3D view (`tests/freecad_view/`): after a refused edit, the regions
      its `EditFailure` names carry the holding outline. The outline clears
      on the next edit or selection change. A redundant lock's duplicated
      locks are outlined the same way.
- [ ] `README.md`'s glossary entries **Size rule** and **The drag rule**
      do not contain "One opening in each row stays unlocked", and
      `docs/scope-and-design.md` does not contain "alone in its run shows
      no padlock".

## Advice
- **The one-unlocked-opening rule retires.** Any opening may lock, and
  every opening's dimension shows a padlock. Delete `_LAST_UNLOCKED`,
  `_refuse_last_unlocked` and `DimensionLabel.lockable`.
- **Reference axis:** on an axis the locks determine, the unit's size is a
  reference, as in the Sketcher. `core/solver.py` exposes whether an axis
  is determined and by which locks, through the engine's freedom query.
  `set_unit_size` changing it raises the conflict naming the locks that
  fix it, and the panel's field for it is read-only. Every other edit
  (typed size, thickness, split, merge) lets it follow, with the fixed
  point's side holding (user decision). Depth is never divided, so its
  field stays editable. `unit_ops.resize_unit` raises the same conflict.
- **Redundant lock:** accepted with a Notification Area warning, and the
  locks it duplicates are outlined as for a refusal (user decision:
  Sketcher accepts and flags). M18's constraint list (task 3) will mark
  these locks persistently. A lock that only turns the unit's size into a
  reference is not redundant. Redundancy already present when Edit Unit
  opens is tolerated without a message; M18 task 2 owns how constraints
  behave across sessions.
- **Conflict outline:** `EditFailure` gains the region ids of sh-046's
  conflict error: its locks, plus any opening held at its minimum. The
  view draws them with the existing holding outline until the next edit
  or selection change (user chose message plus outline).
- **`held_by`** needs no change: sh-046 derives it from freedom, and it
  gives both sides once both are locked.
- **Typed Python:** region id collections are `tuple[str, ...]` or
  `frozenset[str]`; no bare `list` in signatures.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher's reference dimensions,
  its redundancy warning and its highlighting of the constraints
  involved.
- **Users never read the log:** the redundancy warning and each refusal
  reach the user through the Notification Area and the outline.
- **No new manual QA case:** a test asserts every outcome here. The
  existing `editor.padlocks` case names no lone-opening exception and
  stays true; keep it true.
- **Out of scope:** Equal, and a lock made redundant by one, belong to
  sh-048.

## Plan
- [x] **Step 1** (`core/solver.py`, `core/edit.py`, their tests): the
      determined-axis query and the redundancy query, each with the lock
      ids involved; `set_unit_size` refuses on a reference axis; delete
      the one-unlocked rule.
- [x] **Step 2** (`unit_ops.py`, `refusals.py`,
      `tests/freecad/test_refusals.py`, `tests/freecad_gui/test_refusals.py`):
      `resize_unit` raises the conflict on a reference axis; add a
      Notification Area warning beside `report_error`.
- [x] **Step 3** (`editor/session.py`, `editor/elevation.py`,
      `editor/overlay.py`, `editor/view_editor.py`, `editor/panel.py`,
      `editor/fields.py`; tests in `tests/freecad/test_editor_session.py`,
      `tests/test_editor_elevation.py`, `tests/freecad_gui/test_panel.py`,
      `tests/freecad_view/test_padlocks.py`,
      `tests/freecad_view/test_editor_drawing.py`):
      - `EditFailure` carries the responsible region ids;
      - the session reports a redundant lock as a warning and exposes
        whether each unit axis is a reference;
      - `DimensionLabel.lockable` goes, and every opening gets a padlock;
      - the overlay outlines the regions of a refusal or warning until the
        next edit or selection change;
      - the panel makes a reference axis's size field read-only.
- [x] **Step 4** (`README.md`, `docs/scope-and-design.md`): the glossary's Size rule and The drag
      rule say any opening locks and describe the reference axis; the
      Editing section's padlock paragraph loses the lone-opening
      exception.

## Review log

### Round 1: REJECTED
- **F1: The drag rule glossary entry makes a false claim about nested rows** (`README.md:102-104`): "locking every opening of a row holds all its boards and makes the unit's size along it a reference" holds only for a row spanning the whole unit; a fully locked row nested beside an unlocked column leaves the width free (`size_fixed_by` returns `None`). Use the Size rule's condition, or keep only "holds all its boards".
- **N1: The "opens with no warning" test cannot see a warning raised during open** (`tests/freecad/test_editor_session.py:873`): `on_warning` is attached after `open()` and `resize` never warns; lock another region on the reopened unit and assert no new warning, exercising the before/after comparison against recorded redundancy.
- **N2: Awkward README sentence** (`README.md:88-89`): "that refused it" says the openings refused the edit.
- **N3: `Style.outline_rgb` docstring describes its callers** (`freecad/Shelving/editor/overlay.py:186-187`): the sentence about refused edits and redundant locks duplicates `plan_overlay`'s docstring.
- **N4: Extra solves on every refresh** (`freecad/Shelving/editor/panel.py:582`): `_refresh` runs `size_fixed_by` per dimension after every edit attempt, drag steps included; fine now, worth remembering if drag latency grows.

### Round 2: APPROVED
- **N1: Extra solves on every refresh, still open** (`freecad/Shelving/editor/panel.py:582`): `_refresh` runs `size_fixed_by` once per dimension after every edit attempt, drag steps included; fine now, revisit if drag latency grows.
