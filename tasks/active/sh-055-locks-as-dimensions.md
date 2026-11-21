---
id: sh-055
title: "Locks drawn as dimensions, made with Lock Width and Lock Height"
blocked_by: [sh-053, sh-054]
---

# sh-055: Locks drawn as dimensions, made with Lock Width and Lock Height

## Summary
Draws dimensions the way the Sketcher does. A lock is a red driving
dimension and the padlocks are gone. An opening with no lock shows no
dimension unless it's selected or carries an Equal or Even spacing. Then
it shows a blue reference dimension with its value in parentheses. Two
new toolbar commands, Lock Width and Lock Height, lock the size you mean
on each selected opening. They work like the Sketcher's horizontal and
vertical distance constraints, so locking a bay's width locks the column
that holds it. A click on a dimension selects it and a double-click
types a size.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `grep -rni padlock freecad tests README.md docs/scope-and-design.md`
      prints nothing.
- [ ] Elevation plan (`tests/test_editor_elevation.py`), on sh-050's unit:
      654 mm tall of 18 mm boards, fixed point `min`, split by two
      dividers into three columns L, M, R, with left A1 300, shelf s1,
      A2 300; middle B1 200, shelf t1, B2 400; right C1 250, shelf u1,
      C2 350 (bottom to top):
      - with no Lock, constraint or selection, the overlay has no
        dimension;
      - with A1 locked, A1's dimension is planned driving; with that Lock
        deactivated, deactivated; with it selected, selected;
      - with A1 selected and unlocked, A1's and L's dimensions are planned
        reference, and no other;
      - with an Equal on A1 and B1, A1's and B1's dimensions are planned
        reference, each followed by its Equal icon at the row's first
        slot.
- [ ] 3D view (`tests/freecad_view/`):
      - a driving dimension takes `ConstrainedDimColor`, a deactivated one
        `DeactivatedConstrDimColor`, a reference one
        `NonDrivingConstrDimColor`, and a dimension whose Lock is selected
        `SelectionColor`;
      - a reference dimension's text is its formatted size in parentheses,
        and a driving one's is the formatted size alone;
      - a click on a driving dimension's text tile selects its Lock alone,
        a Ctrl-click adds it to the selected constraints, and Delete then
        removes it;
      - a click on a reference dimension's text tile selects its region;
      - a double-click on a dimension's text tile opens its size field,
        and typing 250 into A1's field gives A1 an active Lock at 250;
      - a shelf held only by Locks shows no drag arrow and nothing in its
        place, and outlines the regions holding it;
      - no icon overlaps another icon or a dimension's text tile in device
        pixels.
- [ ] GUI (`tests/freecad_gui/`): `Shelving_LockWidth` and
      `Shelving_LockHeight` sit on the edit toolbar beside Constrain Equal
      and in the Shelving menu, and `IsActive` is false outside an edit.
      On the unit above:
      - A1 selected, Lock Width locks L and Lock Height locks A1;
      - A1 and A2 selected, Lock Width makes one Lock, on L;
      - each is one undo step that moves no board;
      - a selected board, or no selection, is refused through
        `report_error` with text saying to select openings;
      - on a unit with no divider, a bay selected, Lock Width is refused
        through `report_error` with text naming the panel's Width field.
- [ ] GUI (`tests/freecad_gui/test_constraint_list.py`): a Lock row shows
      the icon of the command that makes its axis's Lock, and its text
      names Lock Width or Lock Height.
- [ ] `README.md`'s glossary has entries **Lock Width and Lock Height**
      and **Reference dimension**.
- [ ] `freecad/Shelving/qa/cases/30-editor.toml` has a case with id
      `editor.dimensions` and none with id `editor.padlocks`.

## Advice
- **Dimensions follow the Sketcher** (user decision): a Lock is drawn as
  its dimension and has no icon. A region's dimension is drawn when it
  has a Lock (driving, or deactivated), when it is selected, or when it
  carries an Equal or Even spacing, active or deactivated (reference).
  Nothing else draws a dimension. Colors are the Sketcher's
  `ConstrainedDimColor`, `DeactivatedConstrDimColor` and
  `NonDrivingConstrDimColor`, and `SelectionColor` only for a dimension
  whose Lock is selected. Selecting a region, or the reference dimension
  that selects it, recolors nothing, as selecting Sketcher geometry leaves
  its dimensions' colors alone.
- **Reference text in parentheses** (user decision), as the Sketcher
  writes a reference dimension's value. Keep it one localizable format
  string.
- **Selected opening, both axes** (user decision): a selected opening
  draws its own reference dimension and the reference dimension of the
  region owning its size on the other elevation axis, unless that one is
  already drawn or is the unit's own size. It shows what Lock Width and
  Lock Height would lock and gives both sizes a click target.
- **Direction stays visible** (user decision): a constrained region draws
  its dimension, so an Equal or Even spacing icon always sits on a line
  and arrowheads that say which way it holds. Icons keep their place in
  the row after the text, starting at the first slot now that no padlock
  leads it. Every region has one size, along its parent's run, so a bay
  constrained in width and in height means two regions with two
  perpendicular dimensions, which the existing layout already keeps
  apart.
- **Lock Width and Lock Height** (user decision, the Sketcher's
  Constrain Horizontal and Vertical Distance): each selected opening
  resolves to the nearest region, itself or an ancestor, whose parent
  runs along the elevation's horizontal or vertical axis. Picks that
  resolve to one region make one Lock. A region already holding an active
  Lock is left alone, and one holding a deactivated Lock has it turned on
  (sh-054's one-Lock invariant). If any pick is a board or has no region
  on that axis, refuse the whole command through `report_error`, as
  `Std_Delete` refuses all when one is refused. A redundant result is
  accepted with the existing warning and outline. Each command is one
  undo step that moves nothing. Lock at the current size and open no
  field (user decision). Draw the icons in the Sketcher's style of
  `Constraint_HorizontalDistance` and `Constraint_VerticalDistance` under
  `freecad/Shelving/resources/`, as `Constraint_Equal.svg` is drawn,
  because the Sketcher's own icons do not exist until `SketcherGui` loads
  (`.claude/docs/freecad-notes.md`).
- **Clicks** (user decision, Sketcher): a click on a driving or
  deactivated dimension's text tile selects its Lock as a constraint, and
  Ctrl-click adds it, as an icon click does. A click on a reference
  dimension's tile selects its region, and Ctrl-click adds it to the
  selected openings. A double-click on any dimension's tile opens its
  size field, and typing into a reference dimension adds a Lock (sh-054's
  `set_size`). The press filter must take both presses of a double-click
  so FreeCAD's selection never sees them; verify in the view test.
- **Held boards** (user decision): a board any constraint holds, Locks
  included, shows no arrow and no padlock and outlines the regions
  holding it. Delete `held_padlock`, `HeldPadlock`, `unlock_holders`, the
  padlock glyph and `PadlockIcon`, and the slot constant that reserved the
  padlock's place, along with their callers and tests.
- **Deactivated Lock is gray** (user decision), as the Sketcher draws a
  deactivated dimension. sh-053 removes `DeactivatedConstrDimColor` from
  icons and replaces gray with a corner X; this task brings that color
  back for dimensions only, so it is blocked on sh-053 to keep the two
  rules from colliding. A selected deactivated dimension takes the
  selection color, hiding its state, as sh-053 accepted for dimensions.
- **Out of scope** (user decisions): Equal and Even spacing choosing
  their axis like Lock Width, and coloring fully constrained boards in
  the Sketcher's fully constrained color, are both on the roadmap's Later
  list.
- **Typed Python:** the label's role is a `Literal["driving",
  "deactivated", "reference"]` beside a `selected: bool`, replacing
  `LabelColor`.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher's driving, reference and
  deactivated dimension colors, its parenthesized reference values, its
  click-to-select and double-click-to-edit on a dimension, and its
  separate horizontal and vertical distance constraints.
- **Users never read the log:** both commands' refusals go through
  `report_error`.
- **Manual QA:** `editor.dimensions` replaces `editor.padlocks`, for what
  no test judges: at default zoom and on a HiDPI screen, dimensions
  appearing and disappearing with selection reads as calm rather than
  jumpy, a gray deactivated dimension is plainly distinct from a blue
  reference one, the parentheses read plainly, a double-click opens the
  field reliably, and Lock Width on a bay visibly locks its column. Start
  from an existing setup action; add none.
- **Rows keep their places** (user decision, 2026-11-20): a region's
  dimension outside the unit takes the row it would have with every
  dimension drawn, so one appearing or disappearing moves no other. A gap
  can show only where nested rows both reach an edge.
- **A Lock through the depth** (user decision, 2026-11-20: handle it in
  the least complex way): a scan locks a void in a run along the depth
  axis when that run holds a compartment, as in a unit stepped front to
  back. The view draws no dimension for it, no command makes it, and its
  list row reads "Lock" with an empty icon tile.
- **The unit's own size** (implementer reading of the Must Have,
  2026-11-20): a size is the unit's own when no enclosing region's run
  lies along that axis, or when the region found is alone among boards in
  a run spanning the unit, as a column between the two sides is. That is
  what makes Lock Width on a bay with no divider refuse, and it also keeps
  a selected column from drawing the interior's height.

## Plan
- [x] **Step 1** (`editor/elevation.py`, `tests/test_editor_elevation.py`):
      the dimension visibility rule, the label role and selection, the
      other-axis owner of a selected opening, the axis resolution for Lock
      Width and Lock Height as a pure function, and icon slots without the
      padlock.
- [x] **Step 2** (`editor/session.py`, `tests/freecad/test_editor_session.py`,
      `tests/freecad/test_constraint_session.py`): `lock_axis(axis)` over
      the selection with its refusals, one undo step; remove
      `unlock_holders`.
- [x] **Step 3** (`editor/overlay.py`, `editor/view_editor.py`,
      `tests/freecad_view/editor.py`, `test_editor_drawing.py`,
      `test_editor_input.py`, `test_constraints.py`,
      `test_constraint_list.py`; delete `test_padlocks.py` and move what
      still applies into a `test_dimensions.py`): colors and parenthesized
      text, click and double-click on text tiles, removal of the padlocks
      and the held padlock.
- [x] **Step 4** (`commands/lock_width.py`, `commands/lock_height.py`,
      `resources/`, `init_gui.py`, `editor/constraint_list.py`,
      `tests/freecad_gui/`): the two commands on the edit toolbar and in
      the menu, their icons, and Lock rows showing them.
- [x] **Step 5** (`README.md`, `docs/scope-and-design.md`,
      `.claude/docs/freecad-notes.md`, `freecad/Shelving/qa/cases/30-editor.toml`):
      glossary entries for the commands and reference dimensions, and the
      Size rule, Even spacing and Constraint list entries without padlocks;
      the Editing section's padlock paragraph rewritten for dimensions and
      the departure list updated; the background-color note drops
      "padlocks"; `editor.padlocks` replaced by `editor.dimensions`, and
      the padlock and lock-color steps of `editor.hidpi`,
      `editor.stock_selection`, `editor.constraints` and
      `editor.constraint_list` rewritten for dimensions and the commands.

## Review log
