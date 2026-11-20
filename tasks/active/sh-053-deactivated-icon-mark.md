---
id: sh-053
title: "A corner X marks a deactivated constraint's icon"
---

# sh-053: A corner X marks a deactivated constraint's icon

## Summary
Fixes bug-024. In Edit Unit's 3D view, a selected Equal or Even spacing
icon turns entirely into the selection color, so you can't tell whether
the constraint is on or off. Turning one off with its checkbox in the
constraint list selects the row, so the change doesn't show until you
deselect. After this task, a deactivated constraint's icon keeps the
active red and carries an X in its corner. Selecting an icon still
recolors it in the selection color, X included, so on or off shows in
every state.

## Must Have
- [ ] An icon is drawn in `ConstrainedIcoColor` when unselected and in
  `SelectionColor` when selected, whether its constraint is active or
  deactivated.
- [ ] A deactivated constraint's icon is the active icon of the same kind
  and selection plus a corner X in the same color. A view test asserts
  that every pixel where the two images differ lies in the glyph's
  top-right corner region, and that each of those pixels is the glyph
  color blended over the tile.
- [ ] An active constraint's icon carries no X, selected or not.
- [ ] A test plans an overlay with a deactivated constraint selected and
  gets icons that report both selected and not active. Today the single
  `IconState` value `"selected"` hides activation.
- [ ] A view test selects a constraint's row, unchecks its box, and gets
  an icon that is still in the selection color and now carries the X.
  Checking the box again removes the X, and the row stays selected
  throughout.
- [ ] `grep -rn DeactivatedConstrDimColor freecad/ tests/` finds nothing.
  `Style` has no `deactivated_rgb` field.
- [ ] The constraint list is unchanged: a deactivated row's icon is still
  grayed in Qt's disabled mode, and pressing a row's checkbox still
  selects the row.
- [ ] README's **Deactivated constraint** entry, the notification shown
  when Edit Unit opens with deactivated constraints
  (`_DEACTIVATED_AT_OPEN` in `freecad/Shelving/editor/session.py`), and
  `docs/scope-and-design.md` describe a deactivated icon in the view by
  its corner X. None of them call it gray or grayed.
- [ ] The `bug-024` entry is deleted from `.claude/docs/bug-log.md`.
- [ ] The manual QA case **The constraint list: rows, redundancy marks and
  deactivated rows** (`editor.constraint_list`) has a step for toggling a
  selected row's checkbox, and no step in `30-editor.toml` expects a gray
  icon in the 3D view.
- [ ] `pixi run tests` passes, with `pyrefly check` clean over the changed
  code.

## Advice
- The user chose the X to replace the gray, drawn in the glyph's own
  color. The user rejected an outline ring in the selection color and
  showing the X only on a selected icon. Do not keep gray as a second
  signal, and do not add a preference for the X's color.
- Follow FreeCAD's own tools: this departs from the Sketcher's
  `constrColor`, which grays a deactivated icon with
  `DeactivatedConstrDimColor`. The Sketcher has the same defect: its
  selection color hides a selected constraint's deactivated state. Keeping
  the Sketcher's recolor on selection and carrying activation in the
  glyph's shape fixes that and changes the icon's color rules as little as
  possible. Record this departure in `docs/scope-and-design.md` next to
  the icon paragraph.
- Draw the X into the glyph image before the source-in fill in
  `constraint_icon_image` (`freecad/Shelving/editor/overlay.py`). The
  existing recolor then gives it the glyph's color, and the image cache
  key has to include activation. Put it in the top-right corner of the
  glyph square, where both `Constraint_Equal.svg` and
  `Constraint_EvenSpacing.svg` leave the most room. It must stay legible
  at the default `ConstraintSymbolSize` and at a device pixel ratio of 2,
  and must not hide which kind the glyph is. The manual QA step judges
  this.
- Split activation from selection in the plan: `ConstraintIcon`
  (`freecad/Shelving/editor/elevation.py`) carries both independently, in
  place of the three-valued `IconState`. Color depends on selection only,
  and the X on activation only.
- Leave the constraint list alone. Its unchecked box and Qt's
  disabled-mode icon already show "off" under a row's selection
  highlight. A press on the checkbox selecting the row is Qt's default and
  the Sketcher's list behavior. The user kept it.
- Unlocked dimensions and a blue selection color can still look alike.
  The user accepted that. Do not add an outline or recolor to work around
  it.
- `.claude/docs/freecad-notes.md`'s note on `renderConstrIcon` and
  `constrColor` records FreeCAD's behavior. Leave it unchanged.
- Users never read the log: this task adds no messages. The notification
  text it rewords stays a Notification Area popup.
- Shell stays simple: no shell is involved.

## Plan
- [ ] **Step 1** (`freecad/Shelving/editor/elevation.py`,
  `tests/test_editor_elevation.py`): `ConstraintIcon` carries `active:
  bool` and `selected: bool`, and `IconState` is removed along with the
  comment above it. Update the tests at lines 546 and 580 to assert both
  fields, including a selected deactivated constraint.
- [ ] **Step 2** (`freecad/Shelving/editor/overlay.py`,
  `freecad/Shelving/editor/view_editor.py`): `Style` drops
  `deactivated_rgb` and its `DeactivatedConstrDimColor` read.
  `icon_state_rgb` becomes a selection-only color choice.
  `constraint_icon_image` takes an `active` flag and draws the corner X
  for a deactivated icon. `_row_image` keys its cache on kind, color,
  activation, tile and size. Update the docstrings and comments at
  `overlay.py` lines 115-134 and 153-169 that describe the gray.
- [ ] **Step 3** (`tests/freecad_view/test_constraints.py`): the
  `icon_colors` fixture sets only `ConstrainedIcoColor` and the selection
  color. Rework `test_active_deactivated_and_selected_icons_take_their_colors`
  to cover the four combinations of selected and active, using
  `_glyph_mismatches` for the glyph and a check that the X pixels are
  confined to the corner region. Add the test that toggles a selected
  row's checkbox and checks the X appears and disappears while the icon
  stays in the selection color.
- [ ] **Step 4** (`README.md`, `docs/scope-and-design.md`,
  `freecad/Shelving/editor/session.py`): replace "drawn grayed" for view
  icons with the corner X in README line 123, scope-and-design line 105,
  and `_DEACTIVATED_AT_OPEN`. Keep that text free of counts and articles
  keyed to numbers, so it stays one string to translate. In
  scope-and-design line 254, reword the tiles' rationale, since there is
  no gray icon left to wash out, and add the Sketcher departure. Line 269,
  about the list's grayed icon, stays.
- [ ] **Step 5** (`freecad/Shelving/qa/cases/30-editor.toml`): in
  `editor.constraints`, the `reopen`, `activate`, `undo` and `delete`
  steps describe the even spacing's icons by their X, with "Click a gray
  icon." becoming "Click an icon marked with an X." In
  `editor.constraint_list`, `deactivate` expects the view's even spacing
  icons to gain the X and stay red. A new step after it selects the Even
  spacing row, checks its box, then unchecks it. It expects the icons to
  stay in the selection color while the X disappears and returns, the X to
  be easy to see at a glance on the HiDPI screen, and each glyph's kind to
  be recognizable.
- [ ] **Step 6** (`.claude/docs/bug-log.md`): delete the `bug-024` entry
  in the fixing commit, leaving `next_id` as is.

## Review log
