---
id: sh-057
title: "Fully constrained boards in color, and degrees of freedom in the panel"
blocked_by: [sh-055]
---

# sh-057: Fully constrained boards in color, and degrees of freedom in the panel

## Summary
Shows how constrained a unit is, the way the Sketcher shows it for a
sketch. Each board whose position is fixed gets an outline in the
Sketcher's fully constrained color. Carcass boards are always outlined,
since the unit's size places them. The Edit Unit panel says "Fully
constrained", or how many degrees of freedom are left, and updates after
every edit.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] Core suite, on sh-046's column of 18 mm boards with fixed point
      `min`: bottom, A 300, shelf s1, B 300, shelf s2, C 300, top (972 mm
      tall):
      - with no Lock or constraint, the degrees of freedom are 2, and
        only the carcass boards count as fully constrained;
      - with A locked: 1, with s1 counted and s2 not;
      - with A and B locked: 0, with every board counted;
      - with an Equal on A and B and another on B and C, and no Lock: 0;
      - with A locked and its Lock deactivated: 2.
- [ ] Elevation plan (`tests/test_editor_elevation.py`): every board
      counted as fully constrained has an outline with role
      `"constrained"`, unless it is selected, when it keeps the
      `"selected"` outline. No other board has one.
- [ ] 3D view (`tests/freecad_view/`): a `"constrained"` outline is
      drawn in the View preference `FullyConstraintElementColor`, read
      with the Sketcher's default, and selecting the board replaces it
      with the selection color. The board's own `ShapeAppearance` is
      unchanged throughout the edit.
- [ ] GUI (`tests/freecad_gui/test_panel.py`): the panel's constraint
      status reads "Fully constrained" for the A-and-B-locked unit and
      "Degrees of freedom: 2" for the unconstrained one. It updates after
      an edit, after Undo inside the edit, and after a constraint is
      turned off in the list.
- [ ] `README.md`'s glossary has an entry **Fully constrained**.

## Advice
- **What counts** (user decision): a board is fully constrained when
  `held_by` gives `None`, because boards alone hold it, as for every
  carcass board, or a held result that is not free. That is the test
  that already hides a board's drag arrow. Carcass boards always count,
  because the unit's size always places them: its fields drive it, or
  the locks fix it as a reference.
- **Degrees of freedom:** the number of independent interior board
  positions the active Locks and constraints leave free, summed over
  the elevation's two axes, with the unit's outer faces held. Take it
  from the engine's freedom query (`core/axis_solver.py`), the same query
  `held_by` and the reference axis use, so the three never disagree. Zero
  means fully constrained.
- **Drawing** (user decision): an overlay outline of the board's
  elevation rectangle in `FullyConstraintElementColor`, as the Sketcher
  colors a fully constrained edge, and never a change to the user's
  object. Precedence on a board is selected, then holding (sh-050's
  Aligned outlines its boards), then constrained. Verify the preference's
  name and default in FreeCAD 1.1's Sketcher source and record them in
  `.claude/docs/freecad-notes.md`.
- **Panel status** (user decision, the Sketcher's solver messages): one
  line in the Constraints group, above the list: "Fully constrained", or
  "Degrees of freedom: N". The second form keeps the count out of the
  grammar so it stays one translatable string. Redundancy and conflicts
  are reported as they are now, so the line shows neither.
- **Performance:** the panel's refresh already runs a solve per
  dimension (sh-047 N4). Compute the count and the per-board result from
  one freedom query per axis per refresh, not one query per board.
- **Typed Python:** add `"constrained"` to `OutlineRole`; the count is a
  plain `int` from a function with a typed contract.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher's per-element fully
  constrained color and its "Fully constrained sketch" and degrees of
  freedom messages.
- **Users never read the log:** the status is in the panel.
- **Manual QA:** one case, `editor.fully_constrained`, for what no test
  judges: on the default light theme and on a dark preference pack, at
  default zoom and on a HiDPI screen, the constrained outline is plainly
  distinct from the selection and holding outlines and from an
  opening's region outline. Start from the `large_unit` action, lock
  openings until a column turns fully constrained, then select one of
  its shelves. Add no setup action.

## Plan
- [x] **Step 1** (`core/axis_solver.py`, `core/solver.py`, `core/edit.py`,
      their tests): the degrees-of-freedom count and the per-board fully
      constrained set, from one freedom query per axis.
- [x] **Step 2** (`editor/elevation.py`, `tests/test_editor_elevation.py`):
      the `"constrained"` outline role and its precedence.
- [x] **Step 3** (`editor/overlay.py`, `editor/view_editor.py`,
      `tests/freecad_view/test_editor_drawing.py`): the color read from
      the View preferences and the outline drawn in it.
- [x] **Step 4** (`editor/session.py`, `editor/panel.py`,
      `editor/constraint_list.py`, `tests/freecad_gui/test_panel.py`): the
      status line and its refreshes.
- [x] **Step 5** (`README.md`, `docs/scope-and-design.md`,
      `.claude/docs/freecad-notes.md`,
      `freecad/Shelving/qa/cases/30-editor.toml`): the glossary entry, the
      Editing section, the preference note, and the
      `editor.fully_constrained` case.

## Review log

### Round 1: REJECTED
- **F1: The degrees-of-freedom count includes seams, which disagrees with the Advice and the docs and has no test** (`freecad/Shelving/core/solver.py:786`, `README.md:205`, `docs/scope-and-design.md:389`): `axis_freedom` returns the solve's `degrees_of_freedom`, which counts every engine position, a seam where two regions meet with no board between them included. The Advice counts "independent interior board positions", and the README and scope-and-design say the same. On a unit of bottom, plinth `Void`, `Bay`, top with no constraints, `constraint_status` gives 1 with every board fully constrained, so the panel reports a freedom nothing visible shows. Count only freedom that reaches board positions, or get a user decision to keep seams and correct the docs; either way add a core test pinning the plinth-seam case.
- **N1: One `freedom()` projection per board** (`freecad/Shelving/core/solver.py:786`): the Advice says one freedom query per axis, not one per board; the code makes one solve per axis and one projection per board, and the `constraint_status` docstring says "one solve". Say which reading applies.
- **N2: The holding-over-constrained precedence has no test** (`freecad/Shelving/editor/elevation.py:702`): unreachable for boards on `main` today; sh-050 should add the test when boards can hold.
- **N3: No Smoke set entry in `## Advice`** (`tasks/active/sh-057-fully-constrained-boards.md:79`): the plan predates the obligation; no smoke mark changed, which looks right, but a one-line entry would meet the never-skipped-silently rule.
- **N4: Line wrap in scope-and-design** (`docs/scope-and-design.md:390`): one line runs past the paragraph's wrap width; re-wrap it.
