---
id: sh-049
title: "The constraint list in the task panel"
blocked_by: [sh-048]
---

# sh-049: The constraint list in the task panel

## Summary
Adds a Constraints group to the Edit Unit panel listing every lock and
every Equal and Even spacing, each with its icon, kind and size. A
checkbox turns a constraint on or off, so a constraint that came in
deactivated can be enforced again. Each row has a delete button, and one
button deletes every deactivated constraint. Rows that duplicate each
other are marked redundant for as long as they do. Selecting a row selects
its constraint or opening in the 3D view, and the reverse. The panel's
basis choice also applies to a selected Equal or Even spacing, so it can
measure spacing through the next board.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] Core suite, on sh-046's column of 18 mm boards with fixed point `min`:
      bottom, A 300, shelf s1, B 300, shelf s2, C 300, top (972 mm tall):
      - with A locked, B locked and an Equal on A and B, the redundant set
        is exactly A's lock, B's lock and the Equal; after unlocking B it
        is empty;
      - with A and B locked and nothing else, the redundant set is empty
        (locks that only make the height a reference are not redundant);
      - a deactivated constraint is never in the redundant set;
      - deactivating an active Equal on A and B moves no board, and typing
        400 into A then gives A 400, B 200, C 300, as with no Equal;
      - with a deactivated Equal on A 280, B 300, C 320, reactivating it
        gives A 290, B 290, C 320;
      - with A locked at 300, C locked at 200 and a deactivated Equal on A
        and C, reactivating the Equal raises the conflict naming A, C and
        the Equal, and the unit is unchanged;
      - deleting every deactivated constraint removes exactly those,
        keeping active ones and every lock, and moves no board;
      - with s2 36 mm thick (column 990 mm tall), setting an Equal on A and
        B to the spacing basis gives A + 18 = B + 36 within 1e-6 mm.
- [ ] `rules_to_json` writes `"basis": "with_next"` for a constraint in the
      spacing basis, and `rules_from_json` reads it back; an unknown basis
      string drops that constraint and raises nothing.
- [ ] Headless (`tests/freecad/`), through `Session` on the same column:
      - deactivating, activating, deleting a constraint, deleting the
        deactivated constraints, and changing a constraint's basis are
        each one undo step with a distinct name, and Undo restores the
        previous record and board placements;
      - a refused reactivation returns an `EditFailure` carrying the
        conflict's ids and leaves the document untouched;
      - a reactivation that is redundant is accepted with sh-047's warning;
      - deleting a lock's row unlocks that opening as the padlock does,
        under the same undo step name.
- [ ] GUI (`tests/freecad_gui/test_constraint_list.py`):
      - a group titled "Constraints" sits directly after the Unit group and
        shows with no rows on a unit with no locks or constraints;
      - rows list locks first, in tree order, then constraints in creation
        order. Each row shows its kind's icon (the view's closed padlock,
        Sketcher's `Constraint_EqualLength`, the workbench's Even spacing
        SVG) and text containing its kind name and FreeCAD's `UserString`
        for its size; a deactivated row shows no size and its icon in
        Qt's disabled mode;
      - a constraint row has a checkbox, checked exactly when the
        constraint is active; a lock row has none. Unchecking deactivates
        and checking activates, through the session; a refused activation
        leaves the box unchecked and posts the refusal through
        `report_error`;
      - every row has a delete button, and pressing it removes that row's
        constraint, or unlocks that row's opening;
      - the "Delete Deactivated" button is enabled exactly when some
        constraint is deactivated, and pressing it removes every
        deactivated constraint as one undo step;
      - a row in the redundant set carries a warning icon and a tooltip
        saying it is redundant; other rows carry neither, and the marks
        update after every edit, Undo and Redo;
      - after Undo of a deactivation, that row's box is checked again;
      - the "Opening size measures" combo is enabled with exactly one
        Equal or Even spacing selected, shows its basis, and changing it
        changes the constraint's basis; the spacing choice is disabled
        when any opening the constraint names has no board after it.
- [ ] 3D view (`tests/freecad_view/test_constraint_list.py`):
      - clicking a constraint row selects that constraint in the view, and
        Ctrl-clicking another constraint row adds it;
      - clicking a lock row selects its opening and drops any constraint
        selection;
      - clicking an icon in the view selects its row alone, and selecting a
        locked opening in the view selects its lock row; selecting a board
        clears the list's selection.
- [ ] `README.md`'s glossary has entries **Constraint list** and
      **Redundant constraint**.
- [ ] `freecad/Shelving/qa/cases/30-editor.toml` has a case with id
      `editor.constraint_list`.

## Advice
- **Blocked on sh-048:** this needs its Equal and Even spacing, their
  active flag and basis in the record, the constraint selection and its
  Delete, and sh-047's conflict ids and redundancy warning.
- **Rows** (user decision, Sketcher lists its dimensions beside its
  geometric constraints): one per lock and one per Equal or Even spacing,
  active or deactivated. Locks first in tree order, then constraints in
  creation order (user decision). Text is the kind's name and the current
  size in its basis, in the user's unit system; a deactivated row shows
  the kind alone, because its openings may differ. An active row within
  the joint clearance at open shows its first opening's size. Keep the
  text free of count-keyed grammar (UI text stays localizable). Icons:
  the view's closed padlock (`_padlock_icon` in `editor/view_editor.py`;
  make it public if the panel needs it), Sketcher's `Constraint_EqualLength`
  as sh-048 loads it, and the Even spacing SVG sh-048 adds. A deactivated
  row's icon is the normal icon rendered in `QIcon.Mode.Disabled`, as
  Sketcher's list greys a deactivated constraint's icon.
- **Controls** (user decision): an active checkbox
  on each constraint row, a delete button on every row, and one "Delete
  Deactivated" button. No right-click menu and no Delete-key handling in
  the list; the view's Delete still removes selected constraints (sh-048).
  A lock has no active flag, so its row has no checkbox, and its delete
  button unlocks the opening through `Session.set_lock`. The delete button
  uses FreeCAD's own delete icon with tooltip "Delete".
- **Activation:** deactivating keeps the constraint, stops passing it to
  the solver, writes `"active": false`, and moves no board. Activating
  re-solves with it as its own undo step, moving boards to
  satisfy it. A conflict is refused through the existing conflict path: message
  plus sh-047's outline, the constraint stays deactivated. A redundant
  activation is accepted with sh-047's warning. Delete Deactivated is one
  undo step that moves no board. Undo step names: "Activate Constraint",
  "Deactivate Constraint", "Delete Constraint", "Delete Deactivated
  Constraints".
- **Redundancy marks** (user decision, in the rows; Sketcher's message
  panel cites constraint numbers this editor has no use for): a lock or
  active constraint is redundant when removing it alone leaves the axis's
  freedom unchanged, so every member of an overlapping group is marked and
  the user picks which to remove. A lock that only turns a unit size into
  a reference adds freedom-fixing rank and is not redundant (sh-047). Add
  the query to `core/solver.py` over the engine's rank (sh-045) and
  recompute it on every refresh, including after Undo and Redo. The
  tooltip is one fixed sentence; it does not list the duplicates.
  Redundancy present at open is marked silently: still no message (sh-047).
- **Selection** (user decision, two-way, as Sketcher's list and view
  select together): a constraint row maps to that constraint, a lock row
  to its opening. List clicks follow the view's rules: Ctrl-click adds,
  and picking an opening drops the constraint selection and the reverse
  (sh-048 never mixes them). The list follows every view selection
  change; a board selection clears it. Guard the two directions against
  re-entering each other with `blockSignals`, as `_refresh` already does
  for its combos.
- **Basis** (user decision): the existing "Opening size measures" combo
  serves a lone selected Equal or Even spacing as well as a lone opening.
  For a constraint, changing the basis re-solves, unlike a lock's basis
  change, which moves nothing, because the relation itself changes. It is
  one undo step under the existing "Change What a Size Measures" name, and
  a conflict is refused as above. Offer the spacing choice only when every
  opening the constraint names has a board after it, the same test a
  lone opening's combo uses (`Measurement.spacing_mm is not None`).
- **Placement** (user decision): a "Constraints" group directly after the
  Unit group, always shown. Build it in a new `editor/constraint_list.py`
  so `panel.py` stays a thin shell; the session supplies a typed row
  snapshot and the actions, and the widget holds no layout logic.
- **Typed Python:** the row snapshot is a frozen dataclass with `Literal`
  kinds and sh-048's `NewType` ids; collections are `tuple[...]` or
  `frozenset[...]`.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** Sketcher's constraint list: dimensions
  and geometric constraints in one list, a kind icon, the value in the
  row text, a greyed icon when deactivated, and selection shared with the
  view. Departures, each a user decision: the checkbox means active
  (Sketcher's means visible in its virtual space, which this editor
  lacks); a delete button per row and a Delete Deactivated button (opening
  a unit can deactivate several constraints at once, which Sketcher never
  does); redundancy marked on the rows instead of a messages box.
- **Users never read the log:** refusals and the redundancy warning go
  through the Notification Area; redundancy marks are in the list.
- **Manual QA:** one case, `editor.constraint_list`, for what no test
  judges: the rows fit the task panel at its default width without
  horizontal scrolling, a deactivated row reads as off at a glance, the
  warning and delete icons are recognizable, and all of it stays sharp on
  a HiDPI screen. Start from the `large_unit` action, lock two openings in
  one column and make an Equal between them (a redundant group), make an
  Even spacing elsewhere, then deactivate and delete rows. Add no setup
  action.
- **Out of scope:** renaming constraints, a filter, editing a lock's size
  from its row (Sketcher's double-click edit), Aligned faces (task 4), and
  a Delete key inside the list.

## Plan
- [ ] **Step 1** (`core/solver.py`, `core/edit.py`, their tests): the
      redundant-set query; activate, deactivate, delete-deactivated and
      constraint-basis edits, with conflicts raised as sh-047's.
- [ ] **Step 2** (`core/record.py`, `core/tests/test_record.py`): the
      spacing basis on constraints round-trips; an unknown basis drops
      the constraint.
- [ ] **Step 3** (`editor/session.py`, `tests/freecad/test_editor_session.py`,
      `tests/freecad/test_edit_history.py`): the row snapshot in list order
      with redundancy; the four constraint actions as undo steps; selecting
      by row; `selected_measurement` and `set_basis` covering a lone
      selected constraint.
- [ ] **Step 4** (`editor/constraint_list.py`, `editor/panel.py`,
      `editor/view_editor.py`, `tests/freecad_gui/test_constraint_list.py`,
      `tests/freecad_view/test_constraint_list.py`): the Constraints
      group, its rows and buttons, refresh after every edit and history
      move, and two-way selection with the view.
- [ ] **Step 5** (`README.md`, `docs/scope-and-design.md`,
      `.claude/docs/code-map.md`, `freecad/Shelving/qa/cases/30-editor.toml`):
      the two glossary entries; the Editing section describes the list;
      the code map names `constraint_list.py`; the `editor.constraint_list`
      case.

## Review log
