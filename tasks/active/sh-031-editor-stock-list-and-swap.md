---
id: sh-031
title: "The editor's stock list and stock swap"
---

# sh-031: The editor's stock list and stock swap

## Summary
The Edit Unit panel lists the stocks the unit's boards are made of: each
distinct combination of thickness, FreeCAD material and color, with how many
boards use it. Clicking a stock selects its boards in the 3D view, and
Ctrl-click there or in the tree adds or removes single boards, as anywhere
in FreeCAD. "Change stock…" then changes the selected boards' thickness,
material or color together, each change one undo step, and Delete removes
every selected board at once.

## Must Have
- [x] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [x] A core edit sets the run-axis thickness of a given set of boards and
      returns the new `Unit`. It refuses an unknown id, a non-board id and a
      non-positive thickness. Core tests on one unit assert:
      - the unit's outside size is unchanged;
      - a locked `Basis.WITH_NEXT` region's next board keeps its position,
        and a locked `Basis.CLEAR` region's next board moves;
      - a thickness that cannot fit raises the solver's error.
- [x] A core edit removes a given set of boards as `merge_at` removes one,
      returning the new `Unit`. A board an earlier removal in the same edit
      already discarded is skipped; if any removal raises, the edit raises
      that `EditError` and returns nothing. Core tests cover two inner
      boards in one run, two in different runs, and a set holding an
      end-of-run board.
- [x] A pure core function groups (board id, thickness, material name or
      `None`, color or `None`) records into stocks, one per distinct
      (thickness, material, color), ordered by board count, most first,
      ties by first board in input order. Tested in the fast suite.
- [x] The session lists the unit's stock groups, each with its board ids.
      Left-alone objects are never in a group. Headless, where color is
      unknown, the grouping uses thickness and material only. Asserted on a
      copy of `tests/freecad/fixtures/woodworking_magic_start_default.FCStd`:
      one group holding the five layout boards, with the back board in none.
- [x] The session holds a multi-board selection alongside its single one:
      while two or more boards are selected, `Session.selected_id` is
      `None` and `can_split`, `can_merge` and `selected_measurement` answer
      as for no selection.
- [x] A session stock swap applies to the selected boards, as one undo
      step, any combination of: a thickness, a material from FreeCAD's
      library (by UUID, set as `ShapeMaterial`), and a color. It keeps the
      selection. Asserted headless on the Magic Start copy:
      - after a swap of the shelf to 12 mm and another material, the groups
        are one of four boards and one of the shelf;
      - a swap that cannot fit returns a failure and changes no board;
      - a swap with no field set returns `None` and adds no undo step;
      - one Undo restores every board's geometry and `ShapeMaterial`;
      - no swap changes a board's `Grain`.
- [x] In `tests/freecad_gui/`:
      - a material swap with no explicit color repaints the boards in the
        material's appearance diffuse color;
      - an explicit color wins over the material's;
      - after a swap every face of each board has the same color, so
        per-face colors are replaced.
- [x] In `tests/freecad_gui/`, the panel holds a "Stock" group below the
      Unit group, one row per stock group in the session's order, each row
      showing the thickness, the material name, a color swatch when color
      is known, and the board count as a bare number. Clicking a row puts
      exactly that group's boards in FreeCAD's selection and the session's.
      A row shows as selected exactly when the selection is its boards.
      "Change stock…" is enabled exactly when one or more boards are
      selected, and the basis control is disabled while two or more are.
- [x] In the view tier (`tests/freecad_view/`), under CAD navigation, on
      the Magic Start copy:
      - Ctrl-click on a board adds it to the selection, and Ctrl-click on
        a selected board removes it; the session's board set matches
        FreeCAD's selection after each;
      - selecting two boards in the tree view gives the session the same
        two;
      - Ctrl-click on an opening leaves a board selection unchanged;
      - a plain click on a board or opening returns to single selection;
      - clicking a dimension's text returns to single selection on its
        region;
      - while two or more boards are selected, no drag arrow and no add
        buttons show;
      - Delete with two inner boards selected removes both as one undo
        step, and one Undo restores both;
      - Delete with an inner board and a carcass board selected reports a
        refusal once in the Notification Area and changes nothing.
- [x] The "Change stock…" dialog has three optional fields: a thickness
      quantity field, FreeCAD's `MatGui::MaterialTreeWidget`, and a color.
      Each starts unset; accepting with none set changes nothing. A swap
      that cannot fit is reported in the Notification Area. Asserted in
      `tests/freecad_gui/`.
- [x] QA cases in `freecad/Shelving/qa/cases/` cover, with only what no
      test asserts:
      - selecting by stock row, by Ctrl-click in the view and in the tree,
        and how FreeCAD's highlight reads on several boards;
      - the material picker finding a material from the user's own library;
      - a material swap recoloring boards;
      - a thickness swap in which a spacing-based shelf holds and a
        clear-based one moves.
- [x] `README.md`'s glossary entry for a stock no longer says stock is never
      changed on an existing board and names the stock swap;
      `docs/scope-and-design.md`'s matching sentence says the same.

## Advice

DECISIONS (user, 2026-10-09, carried over):
- **A stock** is the triple (thickness, `ShapeMaterial` name, dominant
  color). A board's dominant color is its most common face color. The list
  is derived from the unit's boards every time, never stored. A new stock
  enters the list only by changing existing boards; there is no "add in
  stock X" gesture (user, 2026-10-17).
- **Do not bind double-click:** the user reserves it for a later "change
  the spacing of every sibling" gesture.
- **Single-item controls** act only with exactly one item selected: the
  drag arrow, the add buttons, the floating size field and the basis
  control. Delete is the exception below.
- **Materials** come from FreeCAD's material library through the
  `Materials` module (`Materials.MaterialManager().Materials`, keyed by
  UUID; verified on 1.1.3 with 200 materials including "Wood"), never from
  scanning folders. It includes the user's own library, where the user adds
  a material with FreeCAD's material editor and where Woodworking's
  `panelMaterial` looks.
- **Color:** picking a material repaints the boards in that material's
  appearance `DiffuseColor`, as Woodworking's `panelMaterial` does, unless
  the same swap also sets a color, which wins. Every face is repainted,
  replacing per-face colors.
- **Thickness:** the unit's outside size holds; a locked spacing keeps the
  board after it in place while a locked clear opening lets it move. A
  change that cannot fit is refused and changes nothing.
- **Scope:** this unit only, one undo step per swap. Left-alone objects are
  never listed or changed. **Grain** is never touched by a swap.

DECISIONS (user, 2026-10-17, re-plan after sh-040):
- **Selection mirrors FreeCAD's.** Whenever FreeCAD's selection holds only
  the unit's boards, the session's selection is those boards: one board is
  the single selection, several are the multi-selection. Ctrl-click in the
  view (whatever each navigation style's add-to-selection gesture is) and
  in the tree work because FreeCAD does them; the editor adds no modifier
  handling of its own. FreeCAD's highlight shows the selected boards, so the
  overlay draws no multi-selection outline. Today `ViewEditor._click`
  re-selects the clicked board alone after FreeCAD handles the click
  (`freecad/Shelving/editor/view_editor.py`), which would collapse every
  Ctrl-click: read FreeCAD's selection there instead. The selection
  observer needs `removeSelection` and `clearSelection` as well as
  `addSelection`, all deferred, since they run inside FreeCAD's selection
  change.
- **Selections are boards or one opening, never a mix.** Ctrl-click on an
  opening is ignored while boards are selected, as FreeCAD treats Ctrl-click
  on empty space.
- **Keep one "Change stock…" dialog** for thickness, material and color,
  one undo step, enabled with one or more boards selected; a swap is one
  act, buying a different sheet. Its material field is FreeCAD's
  `MatGui::MaterialTreeWidget`, created through the UI loader and wrapped
  with `MatGui.MaterialTreeWidget` as `Mod/CAM/Path/Main/Gui/Job.py` does
  (FEM's `task_material_common.py` is the other precedent). Thickness is a
  `Gui::QuantitySpinBox` as the panel's size fields build it; color is
  FreeCAD's `Gui::ColorButton`. Each field needs an unset state, for
  instance a checkbox beside it, since a blank field leaves its property
  unchanged.
- **Delete with several boards selected removes them all** as one undo
  step, as `Std_Delete` and the Sketcher do; if any one is refused (a
  carcass board), the whole delete is refused and reported once.
- The stock list stays in the panel; "Change stock…" sits under it.

DECISION (user, 2026-10-17, during /work): **an opening click reads its
modifier.** Under Inventor navigation FreeCAD selects only on Ctrl-click and
a plain click on empty space leaves its selection alone, so the strict rule
above would leave an Inventor user no click that reaches an opening once a
board is selected. A click on an opening carrying Ctrl (Command on a Mac),
FreeCAD's add-to-selection modifier, keeps a board selection; any other
click on an opening selects it, in every style, as sh-040 did. Boards still
follow FreeCAD's selection alone. Found while implementing: FreeCAD answers
a Ctrl-click on a board selected as a whole object by adding the clicked
element rather than removing the board, so the editor reads a board held
both whole and by an element as that board deselected.

SELECTION INTERFACE: keep `Session.selected_id` as the single selection and
add the board set beside it, `None` id during a multi-selection, so every
existing guard on `selected_id is None` stays correct. Its users:
`freecad/Shelving/editor/session.py`, `freecad/Shelving/editor/view_editor.py`,
`freecad/Shelving/editor/elevation.py`, `freecad/Shelving/qa/actions.py`,
`tests/freecad/test_editor_session.py`, `tests/freecad/test_edit_history.py`,
`tests/freecad_gui/test_panel.py`, `tests/freecad_gui/test_stock.py`, and in
`tests/freecad_view/`: `editor.py`, `test_editor_input.py`,
`test_editor_drawing.py`, `test_padlocks.py`, `test_undo_in_the_editor.py`.
`Session.reload` keeps a selected board that survives a rescan; keep that
for every board of a multi-selection.

LAYERING, as in sh-020 and sh-021:
- The thickness edit, the multi-board removal and the grouping key are
  decided in the core and tested in the fast suite.
- The session owns the document, its undo steps, `ShapeMaterial`, and the
  appearance through `ViewObject`.
- The panel, the dialog and the view editor only display and dispatch.

Color exists only with a GUI (`.claude/docs/freecad-notes.md`), so headless
grouping and swaps work on thickness and material alone, and every color
assertion belongs in `tests/freecad_gui/`.

UI TEXT: no a/an or plural grammar keyed to a number; a row shows its board
count as a bare number in its own column.

QA: the wizard contract applies (`.claude/docs/qa-wizard.md`): closed-data
TOML, one action per line, setup actions only through public API.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: no bare `Any`, no bare containers in signatures; the
  `Materials` and `MatGui` modules, `ShapeMaterial` and `ShapeAppearance`
  go through typed Protocols, since `freecad-stubs` may not cover them.
- Shell stays simple: this task adds no shell.
- Follow FreeCAD's own tools: selection is FreeCAD's, the material picker is
  the one FEM and CAM use, the color field is FreeCAD's color button, and
  multi-delete behaves as `Std_Delete`.
- Users never read the log: a swap that cannot fit and a refused
  multi-delete reach the user through the Notification Area, as the
  editor's other refusals do.

## Plan
- [x] **Step 1** (`freecad/Shelving/core/`): The thickness edit over a set of boards, the multi-board removal over `merge_at`, and the pure stock-grouping function, with core tests.
- [x] **Step 2** (`freecad/Shelving/editor/session.py`): The board set beside `selected_id`, kept through `reload`; the stock groups (reading `ShapeMaterial` and, with a GUI, the dominant face color); the stock swap (thickness through the core edit and the write path, `ShapeMaterial` from a library UUID, color repainting every face); deleting the selected boards as one step. Bring every `selected_id` user listed in Advice along.
- [x] **Step 3** (`freecad/Shelving/editor/view_editor.py`): Mirror FreeCAD's selection through the observer and `_click`, ignore Ctrl-click on an opening during a board selection, hide the arrow and add buttons during a multi-selection, and route Delete to the multi-board delete.
- [x] **Step 4** (`freecad/Shelving/editor/panel.py`, a new dialog module in `freecad/Shelving/editor/`): The Stock group and its rows, the basis control disabled during a multi-selection, and the "Change stock…" dialog with its three optional fields.
- [x] **Step 5** (`tests/freecad/`, `tests/freecad_gui/`, `tests/freecad_view/`): Tests for every Must Have at the tier it names.
- [x] **Step 6** (`freecad/Shelving/qa/cases/30-editor.toml`, `freecad/Shelving/qa/actions.py`, `README.md`, `docs/scope-and-design.md`, `.claude/docs/code-map.md`, `freecad/Shelving/editor/__init__.py`): The QA cases, the glossary and design-doc wording, and the new dialog module in the code map and the editor package docstring.

## Review log

### Round 1: REJECTED
- **F1: Clicking a stock row while the editor is open has no test** (`freecad/Shelving/editor/panel.py:344`): `select_stock` has two branches. `tests/freecad_gui/test_stock_panel.py` builds the panel with no 3D view, so its row-click tests cover only the fallback branch, where the panel calls `session.select_boards` and `select_in_freecad` itself. In real use the editor is always open, and a row click goes through `ViewEditor.select_boards`, after which FreeCAD's selection change triggers the deferred `_follow_freecad`, which may reorder the session's selection and re-runs `_on_change`. Add a view-tier test on Magic Start: emit `itemClicked` on a row, pump, and assert that the session's board set and FreeCAD's selection both hold exactly that group's boards, each held whole, and that the row still shows as selected.
- **F2: A QA instruction line holds two actions** (`freecad/Shelving/qa/cases/30-editor.toml:362`): "Check Thickness and type 12." is two actions; `.claude/docs/qa-wizard.md` § How a step reads requires one per line. Split it into "Check Thickness." and "Type 12.".
- **N1: The thickness tolerance comment doesn't match the code** (`freecad/Shelving/core/stock.py:168`): the comment says "closer than this", but `_THICKNESS_DIGITS` is a count of decimal places for rounding, and two values either side of a rounding boundary land in different groups. Reword it.
- **N2: Date tag in a docstring** (`freecad/Shelving/editor/view_editor.py:1213`): the `_click` docstring already gives its reason; drop "(user, 2026-10-17)", which the task file records.
- **N3: Unwrapped line in the code map** (`.claude/docs/code-map.md:22`): rewrap the edited bullet.
- **N4: Selections that include outside objects are not followed** (`freecad/Shelving/editor/view_editor.py:1160`): when FreeCAD's selection holds anything besides the unit's boards, `_follow_freecad` returns early, so the session keeps its old board set while FreeCAD highlights something else, and Delete with focus in the 3D view still acts on the session's boards. `main` already behaved this way for a single selection, and the Advice covers only selections of the unit's boards; not a regression, for a QA note or a later task.
