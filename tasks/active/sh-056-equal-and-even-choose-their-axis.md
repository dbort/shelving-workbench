---
id: sh-056
title: "Equal and Even spacing choose their axis"
blocked_by: [sh-055]
---

# sh-056: Equal and Even spacing choose their axis

## Summary
Replaces Constrain Equal and Constrain Even Spacing with four commands:
Equal Width, Equal Height, Even Width and Even Height. Each works out
the size you mean from the openings you pick, as Lock Width and Lock
Height do. To make two columns the same width, select one bay in each
and run Equal Width; today you'd have to select the columns themselves.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `grep -rnE "Shelving_ConstrainEqual\b|Shelving_ConstrainEvenSpacing\b|constrain_equal\b|constrain_even_spacing\b" freecad tests README.md docs`
      prints nothing.
- [ ] Core suite, on a unit 972 mm wide and 654 mm tall of 18 mm boards,
      fixed point `min`, split by two dividers into columns L 300, M 200,
      R 400 (left to right), each split by one shelf: left A1 300, A2 300;
      middle B1 200, B2 400; right C1 250, C2 350 (bottom to top):
      - Equal Width on A1 then B1 makes one Equal on L and M, leaves L and
        M within 0.001 mm of each other, and leaves every bay's height
        unchanged;
      - Equal Height on A1 then B1 makes one Equal on A1 and B1;
      - Equal Width on A1, B1 and C1 makes exactly two Equals, L with M
        and M with R;
      - Equal Width on A1 and A2, which both resolve to L, is refused;
      - Even Width on A1 and C1 makes one Even spacing over the root's
        run from L to R, giving L, M and R within 0.001 mm of each other;
      - Even Height on A1 and A2 makes one Even spacing in the left
        column's run;
      - Even Height on the two dividers is refused, because they lie in
        a run along the width axis;
      - on a unit with no divider, Equal Width or Even Width on bays is
        refused.
- [ ] GUI (`tests/freecad_gui/test_constraint_commands.py`):
      `Shelving_ConstrainEqualWidth`, `Shelving_ConstrainEqualHeight`,
      `Shelving_ConstrainEvenWidth` and `Shelving_ConstrainEvenHeight` sit
      on the edit toolbar and in the Shelving menu, each with its own icon,
      and `IsActive` is false outside an edit. Every refusal goes through
      `report_error`, with text naming what to select.
- [ ] GUI (`tests/freecad_gui/test_constraint_list.py`): an Equal row's
      text names Equal Width or Equal Height, and an Even spacing row's
      Even Width or Even Height, by its regions' axis.
- [ ] A unit whose record holds Equals and Even spacings made before this
      task opens with them unchanged: `rules_to_json` output is identical
      before and after opening it.
- [ ] `README.md`'s glossary entries **Equal** and **Even spacing** name
      the four commands and do not contain "Constrain Equal" or
      "Constrain Even Spacing".

## Advice
- **Four commands** (user decision): the axis comes from the command and
  never from the selection, as Lock Width and Lock Height (sh-055) take
  theirs. Reuse sh-055's resolution function: each opening pick resolves
  to the nearest region, itself or an ancestor, whose parent runs along
  the command's axis. Remove `Shelving_ConstrainEqual` and
  `Shelving_ConstrainEvenSpacing` together with their modules.
- **Equal:** resolved picks are deduplicated in selection order, and N
  distinct regions make N-1 Equals chained in that order, as now. Fewer
  than two distinct regions, a board pick, or a pick with no region on
  the axis is refused. The axis check `add_equal` makes stays as a guard.
- **Even spacing:** opening picks resolve as for Equal, then follow
  `add_even_spacing`'s existing rules for openings. Board picks keep its
  rules for boards, plus one more: the boards' run must lie along the
  command's axis. A mixed selection is refused as it is now.
- **The model and record do not change.** A constraint's regions already
  imply its axis, so stored constraints read back as they are, and the
  view's icons stay the axis-free Equal and Even spacing glyphs, since the
  dimension line they sit on shows the direction (sh-055).
- **Icons:** the four toolbar icons are the Equal and Even spacing glyphs
  under `freecad/Shelving/resources/`, each with a small horizontal or
  vertical double arrow added, drawn in the same style. The list rows use
  them too. The 3D view's icons are unchanged.
- **Typed Python:** the axis argument is the editor's existing elevation
  axis type, not a string.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher's separate horizontal and
  vertical tools, as sh-055 already follows for Lock.
- **Users never read the log:** refusals go through `report_error`.
- **Manual QA:** extend `editor.constraints` with one step: in the
  `large_unit` action's unit, select one bay in each of two columns, run
  Equal Width, and see the columns come to one width, the icons sitting
  on the columns' dimensions. No test judges that the icons and the
  toolbar read plainly as width or height; this step does. Add no setup
  action.

## Plan
- [ ] **Step 1** (`core/edit.py`, `core/tests/test_edit.py`,
      `core/tests/test_constraints.py`): axis-taking forms of `add_equal`
      and `add_even_spacing` that resolve picks through sh-055's
      function, with the refusals above.
- [ ] **Step 2** (`editor/session.py`, `editor/panel.py`,
      `tests/freecad/test_constraint_session.py`): `constrain_equal` and
      `constrain_even_spacing` take the axis; `ConstraintCommand` names
      the four commands.
- [ ] **Step 3** (`commands/`, `init_gui.py`, `resources/`,
      `editor/constraint_list.py`, `editor/overlay.py`,
      `tests/freecad_gui/test_constraint_commands.py`,
      `tests/freecad_gui/test_constraint_list.py`): the four command
      modules replace `constrain_equal.py` and `constrain_even_spacing.py`;
      their icons; list rows named and iconed by axis.
- [ ] **Step 4** (`README.md`, `docs/scope-and-design.md`,
      `freecad/Shelving/qa/cases/30-editor.toml`): the glossary and the
      constraints paragraph name the four commands and the resolution;
      every QA step that runs Constrain Equal or Constrain Even Spacing
      names the matching new command, and `editor.constraints` gains the
      Equal Width step.

## Review log
