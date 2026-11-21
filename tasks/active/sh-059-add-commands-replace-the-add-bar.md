---
id: sh-059
title: "Add Shelf and Add Divider become editor commands"
---

# sh-059: Add Shelf and Add Divider become editor commands

## Summary
Removes the floating Add shelf / Add divider buttons from the middle of a
selected opening, where they covered the opening's dimensions (bug-026).
Add Shelf and Add Divider become commands on the toolbar Edit Unit
shows and in the Shelving menu, next to Lock Width. While Edit Unit is open,
all six editor commands also appear in the 3D view's right-click menu,
as Sketcher's tools do. A command run on several selected bays splits
each of them. The six command modules collapse into one, and the task
leaves less Python than it found.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `git diff --numstat main...sh-059 -- '*.py' | awk '{a+=$1; d+=$2} END {exit !(d > a)}'`
      exits 0: the branch removes more Python lines than it adds.
- [ ] `grep -rnE "AddBar|add_bar|split_preview|_board_icon|_hover_add|_preview_direction|_place_add_bar" freecad tests`
      prints nothing.
- [ ] `freecad/Shelving/commands/edit_commands.py` exists, and none of
      `lock_width.py`, `lock_height.py`, `constrain_equal.py`,
      `constrain_even_spacing.py` exists under `freecad/Shelving/commands/`.
- [ ] GUI test: the edit toolbar's actions are, in order,
      `Shelving_AddShelf`, `Shelving_AddDivider`, `Shelving_LockWidth`,
      `Shelving_LockHeight`, `Shelving_ConstrainEqual`,
      `Shelving_ConstrainEvenSpacing`. The Shelving menu lists the same
      six, and all six are inactive outside an edit.
- [ ] GUI test: with two bays selected, `Shelving_AddShelf` adds one
      shelf across each bay as a single undo step named `Add Shelf`, and
      the selection afterward is exactly the two new boards.
      `Shelving_AddDivider` does the same with `Add Divider`.
- [ ] GUI test: run with nothing selected, or with a selection that
      includes a board or a bay too small to split, either command leaves
      the unit and the document's undo names unchanged and reports exactly
      one Notification Area error.
- [ ] GUI test: while Edit Unit is open, the editor's workbench
      manipulator puts the six commands, in toolbar order, into the context
      menu for recipient `"View"` in a workbench other than Shelving. After
      Close, no Shelving manipulator is installed.
- [ ] View test: selecting a bay shows no new visible widget over the 3D
      view; the visible children of the viewer's parent widget are the same
      before and after the click.
- [ ] A test of adding a shelf to a selected bay through
      `Shelving_AddShelf` carries a `smoke` mark naming that path.
- [ ] `freecad/Shelving/qa/cases/30-editor.toml`: `editor.undo` adds its
      shelves and divider from the toolbar, with one of those additions made
      from the right-click menu. The `select` step of `editor.dimensions`
      expects both dimensions readable, with nothing drawn over them.
- [ ] The `bug-026` entry is gone from `.claude/docs/bug-log.md`.

## Advice
- The bar goes because no FreeCAD tool puts buttons over the geometry.
  Sketcher, PartDesign, Draft and Assembly put edit actions on toolbars and
  menus, and Sketcher 1.x's edit mode also lists its tools in the 3D view's
  right-click menu. Lock Width already follows that pattern in this repo,
  so the add commands copy it exactly. They do not gray out during an
  edit; an unusable selection is refused through `report_error`, with a
  message saying what to select (Users never read the log).
- No hover preview: no FreeCAD command previews its result, and a split
  always lands mid-bay with a one-step Undo. Delete the preview path
  entirely: `split_preview`, `ViewEditor.preview`, `_update_preview`,
  `drawing_node`'s `preview` parameter, and `_PREVIEW_TRANSPARENCY`
  wherever nothing else uses them.
- The user asked for a net removal of code. Beyond the bar, take every
  simplification the change opens up. Merge the four command modules into
  one table-driven module. Define the six command ids once; today
  `init_gui.CONSTRAINT_COMMANDS` and `panel.CONSTRAINT_TOOLBAR_COMMANDS`
  duplicate them, and a test asserts the two match. Drop helpers only the
  bar used, such as `_bind` and `_ICON_PX`. Keep `_move_to`, which the
  floating size field still uses.
- Layering (`.claude/docs/code-map.md`): `editor/` must not import
  `commands/`, and `import freecad.Shelving.init_gui` must stay headless,
  with no Qt or Coin at import. Put the one id tuple where all three
  readers (`init_gui`, the toolbar, the manipulator) can import it under
  those rules.
- A split over several bays is all or nothing: apply `split_region` to
  each selected bay in turn on one candidate, as one `_step` named `Add
  Shelf` or `Add Divider` (the names the undo QA case already uses). Any
  refusal changes nothing and names the offending node. Selecting the new
  boards afterward keeps today's single-bay behavior: one new board shows
  its drag arrow at once.
- Right-click menu: use FreeCAD's `WorkbenchManipulator`
  (`FreeCADGui.addWorkbenchManipulator`, `modifyContextMenu`). The editor
  runs in whatever workbench is active, and a manipulator applies to all
  of them, which `Workbench.ContextMenu` does not. Install it when the
  panel shows its toolbar and remove it in `_end`. Add items only for
  recipient `"View"`: the six commands, then a separator, ahead of
  FreeCAD's own view entries. Confirm FreeCAD 1.1's return-value contract
  for `modifyContextMenu` against its source or a live run, and record it
  in `.claude/docs/freecad-notes.md`.
- Right-click must not change the editor's selection. `_ViewportClicks`
  already passes non-left buttons through; keep it that way, so a user can
  select bays, then right-click to add.
- The toolbar now holds more than constraints. Rename `ConstraintToolBar`,
  `CONSTRAINT_TOOLBAR_NAME` and the toolbar title to an edit-toolbar name.
  Add Shelf and Add Divider come first, then a separator, then the four
  constraint commands.
- Icons: two SVGs in `freecad/Shelving/resources/`, an opening with a
  board across it (horizontal for the shelf, vertical for the divider),
  drawn in the style of the existing `Constraint_*.svg` files. They
  replace the QPainter-drawn `_board_icon`.
- No default shortcuts, the same as the other editor commands; users bind
  them in Tools > Customize.
- Ordering: sh-056 is `blocked_by` this task and adds its four
  axis-specific commands as rows in the merged module.
- Typed Python: the table uses a `NamedTuple` or a frozen dataclass whose
  action field is a precise type, such as a `Literal` or a
  `Callable[[EditUnitPanel], None]`, never `Any`. Shell: no shell is
  involved.
- Smoke set: adding a board is a main user path whose entry point moves,
  so the command-driven add test takes a `smoke` mark. The removed bar
  test carried none, so no mark is lost.

## Plan
- [ ] **Step 1** (`editor/session.py`, `tests/freecad/test_editor_session.py`):
      `split(direction)` splits every selected bay as one undo step, all or
      nothing, and refuses an empty selection or any non-bay. Single-bay
      callers (`qa/actions.py`, `tests/freecad/test_edit_history.py`,
      `tests/freecad/test_stock_session.py`,
      `tests/freecad_gui/test_constraint_commands.py`'s fixture) behave as
      before. Drop or rewrite `can_split` if nothing outside the removed
      bar still needs it (`tests/freecad/test_stock_session.py`,
      `tests/freecad/test_editor_session.py`). Update the
      `can_split` fixture text in `tests/test_readme_glossary.py` only if
      that test needs a live identifier.
- [ ] **Step 2** (`commands/edit_commands.py`, `init_gui.py`,
      `editor/panel.py`, `resources/`, `.claude/docs/code-map.md`):
      one module registers `Shelving_AddShelf`, `Shelving_AddDivider` and
      the four existing commands from a table, and the four old modules are
      deleted. The panel gains an add method that runs the split, reports a
      refusal, and selects the new boards in the session and in FreeCAD.
      The renamed edit toolbar and the Shelving menu read the single id
      tuple. Add the two SVG icons. The code-map's `commands/` line
      describes the merged module.
- [ ] **Step 3** (`editor/panel.py` or a sibling editor module,
      `.claude/docs/freecad-notes.md`): the context-menu manipulator,
      installed and removed with the edit toolbar.
- [ ] **Step 4** (`editor/view_editor.py`, `editor/overlay.py`,
      `editor/elevation.py`): delete `AddBar`, `_bind`, `_board_icon`, the
      bar's construction, placement and icon redraw, `_add_board`,
      `_hover_add`, the preview state and drawing, and `split_preview`.
- [ ] **Step 5** (tests): rename `tests/freecad_gui/test_constraint_commands.py`
      to `test_edit_commands.py` and cover the Must Haves' toolbar, menu,
      multi-bay, refusal and manipulator cases, with the smoke mark.
      `tests/freecad_view/editor.py`'s `add_board` helper runs the command
      instead of clicking the bar, which keeps its many callers unchanged.
      Delete the bar test in `tests/freecad_view/test_editor_input.py` and
      add the no-widget-over-the-view test. Drop the bar assertions in
      `tests/freecad_view/test_dimensions.py` (icon sizes) and
      `tests/freecad_view/test_multi_selection.py`. Drop
      `test_split_preview_is_where_the_new_board_goes` in
      `tests/test_editor_elevation.py`.
- [ ] **Step 6** (`README.md`, `docs/scope-and-design.md`,
      `freecad/Shelving/qa/cases/30-editor.toml`,
      `.claude/docs/bug-log.md`): add a glossary entry for Add Shelf and
      Add Divider covering where they sit and the multi-bay behavior. Say
      in the Lock Width entry that the editor commands are also in the
      view's right-click menu. Replace scope-and-design's "buttons over a
      selected opening" sentence. Make the QA case edits the Must Haves
      name, then delete `bug-026`.

## Review log
