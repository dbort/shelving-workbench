---
id: sh-060
title: "One Even Spacing command"
---

# sh-060: One Even Spacing command

## Summary
Replaces Even Width and Even Height with a single Even Spacing command
that reads the direction from what you pick. Picks inside one column
space that column's heights; picks across columns space the columns'
widths; two boards space the row or column they sit in. The constraint
list still names each row Even Width or Even Height. Equal and Lock keep
their width and height commands, since a bay in each of two columns
could mean either size for them.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `grep -rnE "Shelving_ConstrainEvenWidth\b|Shelving_ConstrainEvenHeight\b|\beven_axis\b|add_even_spacing_along" freecad tests README.md docs`
      prints nothing.
- [ ] Core suite (`core/tests/test_constraints.py`), with `add_even_spacing`
      on sh-056's three-column unit (`_three_columns`: columns L 300,
      M 200, R 400 in the root run between `left` and `right`, each split
      by one shelf into bays A1/A2, B1/B2, C1/C2):
      - A1 and C1 make one Even spacing on the root run from `left` to
        `right`, leaving L, M and R within 0.001 mm of each other;
      - A1 and A2 make one Even spacing on run L;
      - A1, A2 and C1 make one Even spacing on the root run, L standing
        once for A1 and A2;
      - `left` and `d2` make one Even spacing on the root run with ends
        `left` and `d2`;
      - the shelves of L and M (two boards of different runs), a single
        bay, the same bay picked twice, and A1 with `d1` (mixed) are each
        refused with an `EditError`;
      - on the nested unit `test_even_width_in_a_nested_run_keeps_its_ends`
        builds (M's top bay B2 split side by side into P and Q), P and Q
        make one Even spacing on their own run, and P with C1 makes one
        on the root run over M and R, M standing for P;
      - on `_column()` (no divider), bays A and C make one Even spacing
        on the column's run;
      - two regions split from one bay along the unit's depth axis are
        refused with an `EditError`.
- [ ] GUI (`tests/freecad_gui/test_edit_commands.py`):
      `Shelving_ConstrainEvenSpacing` sits on the edit toolbar, in the
      Shelving menu and in the 3D view's right-click menu with
      `Constraint_EvenSpacing.svg` as its icon, `IsActive` is false
      outside an edit, and neither `Shelving_ConstrainEvenWidth` nor
      `Shelving_ConstrainEvenHeight` is in `FreeCADGui.listCommands()`.
      Run on the columns unit, bays A1 and C1 make one undo step named
      "Even Width" over L, M and R; A1 and A2 one named "Even Height"
      over A1 and A2. A refused selection goes through `report_error`
      with text containing "Select".
- [ ] `tests/freecad_view/test_editor_input.py`: the right-click menu
      lists Add Shelf, Add Divider, a separator, Lock Width, Lock Height,
      Equal Width, Equal Height, Even Spacing, a separator, then Fit All.
- [ ] `README.md`: the **Even spacing** glossary entry names the Even
      Spacing command and says how picks give width or height; no line
      calls Even Width or Even Height a command.

## Advice
- **Only Even merges** (user decision): Equal Width, Equal Height, Lock
  Width and Lock Height stay as they are. A bay in each of two columns is
  a valid Equal Width (the columns) and a valid Equal Height (the bays),
  so the selection cannot give Equal's axis; it always gives Even's.
- **Axis rule: where the picks part ways** (user decision): for openings,
  the run is the innermost one holding every pick, and each pick stands
  for its region in that run, itself or the ancestor that is a child of
  that run. That run's axis is the direction. Two distinct picks always
  sit in different children of exactly one run, so the rule never has
  two answers and needs no tie-break. It replaces sh-056's per-pick
  `region_along` resolution for Even: a sub-bay inside column M picked
  with a bay of column R spaces M and R, which Even Width refused. Picks
  that collapse to one region, a lone pick, and a mixed board and
  opening selection are refused. Boards keep today's rule: two boards of
  one run, whose axis gives the direction. Once the run and its picked
  regions are known, `add_even_spacing`'s existing end rules, group-size
  refusal and held-span solve (sh-056) apply unchanged.
- **Depth runs refused:** no command makes a constraint through the depth
  (`docs/scope-and-design.md`), so a run along the unit's depth axis is
  refused with a message saying to pick openings side by side or one
  above another. Use the existing `_elevation` helper's notion of the
  depth axis.
- **Core shape:** generalize `add_even_spacing(unit, node_ids)` to the rule
  above and delete `add_even_spacing_along` and the now-unused
  `_SELECT_TO_SPACE`/`_UNIT_SIZE_TO_SPACE` maps. One axis-free refusal
  message replaces them, naming what to select for either direction
  (no a/an or plural keyed to a count: UI text stays localizable).
- **Name and icon** (user decision): menu text "Even Spacing", command id
  `Shelving_ConstrainEvenSpacing`, icon `Constraint_EvenSpacing.svg`
  (the axis-free glyph the 3D view already shows,
  `ICON_SOURCES["even_spacing"]` in `editor/elevation.py`). Tooltip says
  the picks choose the direction. `Constraint_EvenWidth.svg` and
  `Constraint_EvenHeight.svg` stay: the constraint list's rows use them.
- **Undo step and list row by axis:** the undo step is named "Even Width"
  or "Even Height" (`_EVEN_STEPS`) from the new constraint's axis
  (`constraint_axis`), matching its list row, so the Edit menu says which
  direction was spaced. The list rows, their icons and `RowKind` do not
  change.
- **The model and record do not change.** A stored Even spacing names its
  run, which already implies its axis.
- **Typed Python:** `ConstraintCommand` becomes
  `Literal["equal_width", "equal_height", "even_spacing"]`;
  `Session.even_spacing() -> EditFailure | None` replaces `even_axis`.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher's Constrain
  horizontal/vertical (`Sketcher_ConstrainHorVer`, FreeCAD 1.0) is one
  tool that picks horizontal or vertical from the selection, beside the
  separate Horizontal and Vertical tools; Even Spacing follows it. Equal
  stays split, as the Sketcher has no combined tool where the selection
  cannot decide.
- **Users never read the log:** refusals go through `report_error`.
- **Smoke set:** no `smoke` mark changes. Neither Even command carried
  one; the Equal Width mark still covers the constraint-command path, and
  the toolbar test keeps checking the buttons.
- **Manual QA:** update `30-editor.toml`'s steps that click Even Height on
  the toolbar to click Even Spacing, and the toolbar-look step's expected
  text: the Even Spacing button shows three evenly spaced uprights with no
  arrow, and reads on a dark toolbar. Even Height rows in the list keep
  their names. No new case or setup action.

## Plan
- [x] **Step 1** (`freecad/Shelving/core/edit.py`,
      `freecad/Shelving/core/tests/test_constraints.py`): `add_even_spacing`
      takes the axis from the picks as above; `add_even_spacing_along` and
      its message maps go. Rewrite the tests that call
      `add_even_spacing_along` (sh-056's Even Width/Height tests,
      `test_even_spacing_along_takes_boards_only_on_its_axis`,
      `test_even_spacing_along_refuses_a_mixed_selection`, the Even half of
      `test_width_commands_on_a_unit_with_no_divider_are_refused`) onto
      `add_even_spacing`; `test_even_spacing_refuses_a_mixed_or_scattered_selection`'s
      sub-bay-and-B case now succeeds and becomes a positive test. Add the
      Must Have cases.
- [x] **Step 2** (`freecad/Shelving/editor/session.py`,
      `freecad/Shelving/editor/panel.py`,
      `tests/freecad/test_constraint_session.py`,
      `tests/freecad_gui/test_constraint_list.py`): `Session.even_spacing`
      names its undo step by axis; `EDIT_COMMANDS` lists
      `Shelving_ConstrainEvenSpacing` in place of the two; `panel.constrain`
      dispatches `"even_spacing"`. In `test_constraint_session.py`,
      `test_width_commands_on_bays_of_one_column_are_refused` keeps only
      Equal Width and the one-column Even case becomes Even Height success;
      `test_even_height_spaces_the_column_and_refuses_one_opening` calls
      `even_spacing`.
- [x] **Step 3** (`freecad/Shelving/commands/edit_commands.py`,
      `freecad/Shelving/editor/elevation.py`,
      `tests/freecad_gui/test_edit_commands.py`,
      `tests/freecad_view/test_editor_input.py`,
      `tests/freecad_view/test_constraint_list.py`,
      `tests/freecad_view/test_constraints.py`,
      `tests/freecad_view/test_dimensions.py`): one Even Spacing row
      replaces the two in `_SPECS`; the module docstring and the
      `AXIS_ICON_SOURCES` comment say the axis icons serve Even's list
      rows. GUI and view tests call `"even_spacing"`; the board-refusal
      cases for Even become the different-runs refusal.
- [x] **Step 4** (`README.md`, `docs/scope-and-design.md`,
      `freecad/Shelving/qa/cases/30-editor.toml`): glossary entries
      (the command list under the lock entry, **Even spacing**) and the
      constraints paragraph describe Even Spacing and the axis rule; the
      constraint-list paragraph no longer says every row is named for the
      command making it (Even rows are named by axis); QA steps per
      Advice.

## Review log

### Round 1: APPROVED
- **N1: Test name still calls Even Width a command** (`tests/freecad_gui/test_constraint_list.py:323`): `test_width_rows_name_and_draw_the_width_commands` now checks an Even Width row, and no command by that name exists anymore; a name like `..._draw_the_width_icons` would fit.
- **N2: Unreflowed paragraph lines** (`docs/scope-and-design.md:124`, `docs/scope-and-design.md:360`): the edited constraints paragraph has a line of about 100 characters and the constraint-list paragraph a short one; rewrap both to match the surrounding text.
