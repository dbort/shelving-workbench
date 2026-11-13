---
id: sh-048
title: "Equal and Even spacing constraints"
blocked_by: [sh-047]
---

# sh-048: Equal and Even spacing constraints

## Summary
Adds the first two geometric constraints to the editor. Equal keeps two
openings, in any runs along one axis, the same size. Even spacing keeps
every opening between two ends of one run the same size, so a shelf added
inside the span joins the group. They are made from a toolbar that appears
only during an edit, drawn as Sketcher-style icons beside their openings,
and removed with Delete. They are kept across sessions with an active flag:
one the boards no longer satisfy comes in deactivated, and one whose
boards are gone is dropped, with one notification saying so.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] Core suite, on sh-046's column of 18 mm boards with fixed point `min`:
      bottom, A 300, shelf s1, B 300, shelf s2, C 300, top (972 mm tall):
      - Equal on A and B, then typing 400 into C, gives A 250, B 250, C 400;
        without the Equal, the same typing gives A 300, B 200 (control);
      - Equal on A, B and C, selected in that order, makes exactly two
        constraints: A with B, and B with C;
      - after typing 200 into A and unlocking it (A 200, B 400, C 300),
        Even spacing on the openings A and C gives A, B and C 300 each, and
        splitting C along the run then gives four openings of 220.5 mm;
        deleting the new shelf gives three of 300 again, with the group kept;
      - Even spacing on s1 and s2, with only B between them, is refused;
      - an Even spacing with boards as its ends is removed when an end
        board is deleted, and kept when an inner board is deleted;
      - deleting s1 removes an Equal on A or B; splitting A along the run
        removes an Equal on A; splitting A across the run keeps it;
      - A locked at 300 and C locked at 200, an Equal on A and C is refused
        with a conflict naming A, C and the Equal;
      - with an Equal on A and B and A locked, locking B is accepted and
        reported redundant, the duplicated ids including A's lock and the
        Equal;
      - an Equal on an opening of a vertical run and one of a horizontal
        run is refused;
      - with Even spacing on A, B and C, `held_by` (or what replaces it)
        names that Even spacing for s1 and offers no unlock.
- [ ] `rules_to_json` emits `{"schema_version": 2, "locks": {...},
      "constraints": [...]}`, the locks exactly as sh-046 emits them. Each
      constraint entry has `"kind"` (`"equal"` or `"even_spacing"`),
      `"basis"` (`"clear"`), `"active"` (a bool), and the rescan-stable keys
      of its openings or of its run and ends. `rules_from_json` on a
      version 1 record, or on any other shape, gives no locks and no
      constraints, and raises nothing.
- [ ] Headless (`tests/freecad/`), opening a container in `Session`:
      - an Equal whose openings now differ by more than the joint clearance
        comes in deactivated. A following edit leaves those openings'
        difference as it was, and the written record has `"active": false`;
      - one off by less than the clearance comes in active, opening moves
        no board, and the next edit makes the two equal;
      - a stored deactivated Equal whose openings are equal again stays
        deactivated;
      - an Equal whose bounding board was deleted by hand, or whose opening
        a hand-added shelf split along its axis, is dropped. An Even
        spacing whose end board was deleted by hand is dropped, and one
        whose inner board was deleted is kept;
      - the session reports what was deactivated and dropped. Exactly one
        Notification Area message is posted at open when anything was, and
        none when nothing was or after an undo or redo inside the edit.
- [ ] Headless: Delete with one or several constraints selected, active or
      deactivated, removes them as one undo step that moves no board, and
      Undo brings them back.
- [ ] GUI (`tests/freecad_gui/`): the commands `Shelving_ConstrainEqual`
      and `Shelving_ConstrainEvenSpacing` sit on a toolbar that is visible
      in the main window exactly while an edit is open, in any workbench.
      Both are in the Shelving menu, and `IsActive` is false outside an
      edit. A selection either command cannot use is refused through the
      Notification Area with text saying what to select.
- [ ] 3D view (`tests/freecad_view/`):
      - Ctrl-click on an opening adds it to the selection, and the session
        keeps the selection order;
      - an Equal draws one icon at each of its two openings, and an Even
        spacing draws one at every opening of its group. No icon overlaps
        another icon, a dimension's text, or a padlock in device pixels;
      - the Equal and Even spacing icons are rendered from the
        workbench's own SVGs under `freecad/Shelving/resources/`;
      - a click on an icon selects its constraint alone, Ctrl-click on
        another icon adds it, and a click on a board or opening drops the
        constraint selection;
      - a selected constraint's openings carry the selection outline;
      - with distinct values set for `ConstrainedIcoColor`,
        `DeactivatedConstrDimColor` and `SelectionColor`, an active,
        a deactivated and a selected icon are each drawn in their color;
      - every constraint icon and every padlock sits on a rounded tile of
        the 3D view's background color, read from the View preferences:
        the plain color, or a gradient's middle;
      - selecting s1 inside an Even spacing group shows no drag arrow, and
        the group's openings carry the holding outline.
- [ ] `README.md`'s glossary has entries **Equal**, **Even spacing** and
      **Deactivated constraint**.
- [ ] `freecad/Shelving/qa/cases/30-editor.toml` has a case with id
      `editor.constraints`.
- [ ] `.claude/docs/freecad-notes.md` says whether
      `:/icons/constraints/Constraint_EqualLength.svg` exists before
      `SketcherGui` is imported, on FreeCAD 1.1. No workbench code imports
      `SketcherGui`.

## Advice
- **Blocked on sh-047:** this needs the engine's general linear relations
  (sh-045), the solved layout and locks-only record (sh-046), and the
  redundancy reporting and conflict outline (sh-047).
- **Equal is pairwise** (user decision, Sketcher precedent): N selected
  openings make N-1 constraints chained in selection order, each between
  two openings. Any two openings whose runs lie along the same model axis
  qualify, in any subtrees. An opening is any region the editor draws a
  size dimension for: bay, void or division (user decision). The relation
  is their sizes in the constraint's basis being equal.
- **Even spacing** (user decision): select two boards of one run, or two or
  more openings of one run. With openings, the group runs from the first
  opening to the last, and each end is the board bounding it or the run's
  own end, so selecting a column's top and bottom bays spaces the whole
  column, whose carcass bottom and top are not in its run. The group is
  every opening of the run between its ends, read at each solve, so a
  split inside the span joins and a delete leaves. Creation with fewer
  than two openings between the ends is refused. It is kept while its ends
  exist, even if later deletes leave it one opening.
- **Basis is clear only** (user decision). The type and the record carry a
  basis so the constraint list (task 3) can offer spacing without a record
  change.
- **Commands:** refuse a selection they cannot use through `report_error`,
  saying what to select (user decision, Sketcher keeps its constraint
  commands active and explains a wrong selection). Selection first only;
  Sketcher's continuous mode is out of scope. Each creation is its own
  undo step. A conflicting new constraint is refused through the existing
  conflict path. A redundant one, or a lock made redundant by a
  constraint, is accepted with sh-047's warning and outline (user decision,
  consistent with sh-047).
- **Toolbar** (user decision, Sketcher precedent): the editor shows it when
  the edit opens and removes or hides it at close, whatever the active
  workbench, as Sketcher's edit-mode toolbars are. The commands also go in
  the Shelving menu, greyed outside an edit. One thin module per command
  under `commands/` (code map).
- **Selection** (user decision): the add-to-selection click that adds a
  board adds an opening too, and the session keeps an ordered selection of
  boards and openings. Constraints are selected separately: a click on an
  icon selects that constraint alone, Ctrl-click adds more, and a click on
  a board or opening drops them, so the selection never mixes the two and
  Delete never means both merge and remove. Delete with constraints
  selected removes them all as one step. A selected constraint outlines
  its openings in the selection color. FreeCAD's selection never holds an
  opening or a constraint.
- **Icons** (user decision): Sketcher's in-view icons are drawn at each
  constrained geometry, so an Equal draws its icon at both openings and
  an Even spacing at each of its openings, beside the dimension text and
  clear of the padlock. Several icons on one opening sit in a row. Draw
  them as the fixed-point cross is drawn (`PointMarker`, an image at device
  pixel size), and hit-test them in the press filter ahead of the
  dimension text. Plan their positions in `editor/elevation.py` so the
  layout tests need no view. Equal and Even spacing each get the
  workbench's own SVG in Sketcher's constraint icon style, in
  `freecad/Shelving/resources/`, recolored as Sketcher's own constraint
  icon drawing recolors it (read its source). Colors from
  the View preferences: `ConstrainedIcoColor` active,
  `DeactivatedConstrDimColor` deactivated, `SelectionColor` selected.
- **Sketcher resources:** whether they load before `SketcherGui` is
  imported is checked by Plan step 1 and recorded in
  `.claude/docs/freecad-notes.md`.
- **The workbench draws its own Equal icon** (user decision, 2026-11-13):
  the Even spacing icon already copies Sketcher's style and must be kept
  in step with it, so Equal is drawn the same way rather than borrowed.
  That removes the `SketcherGui` import Sketcher's own icon needed.
- **Deletes and splits drop silently**, in the same undo step: deleting a
  board drops every Equal on an opening beside it, since that opening
  merges away, and every Even spacing with it as an end. A split along an
  Equal's axis drops the Equal on the opening it cuts, as the Sketcher's
  Split and Trim drop an Equal on the line they cut. A split across the
  axis keeps it (user decision), since that opening's size and record key
  are unchanged. The same rules decide what is dropped at open.
- **A board held by a constraint** (user decision): no drag arrow, and the
  constraints holding it outline their openings with the holding outline.
  The held padlock stays for a board held by locks alone, since only locks
  release with one click. Extend sh-046's `held_by` result to name
  constraints beside locks.
- **Record version 2** (user decision): locks as sh-046 stores them, plus
  a constraint list. Each Equal names its two openings by record key, and
  each Even spacing names its run's key (a sentinel for the root run) and
  its two ends, a board id or a run-end sentinel, so all of it survives a
  rescan as locks do. A version 1 record reads as no record (user
  decision, as sh-046 treated the old shape).
- **At open:** geometry wins. An active constraint whose openings differ
  by more than the joint clearance (`DEFAULT_CLEARANCE_MM`) comes in
  deactivated. A deactivated one is drawn, stored, never passed to the
  solver, and removable with Delete; reactivating is the constraint
  list's (task 3). A stored deactivated constraint stays deactivated even
  when satisfied (user decision: the flag is the user's state). One within
  the clearance comes in active, and opening moves nothing; the next edit
  makes it exact inside that edit's undo step (user decision). A
  constraint naming a key that matches nothing is dropped. Redundancy
  present at open is tolerated without a message (sh-047). The open
  report is computed in `core/` and worded in the editor. It is posted
  once at open, never on the session's reloads after undo or redo.
  Opening writes nothing, so until an edit writes the record the next
  open reports the same again.
- **Outside the editor:** `unit_ops`' resize and rescan read the record's
  constraints and solve with the active ones, as they honor locks.
- **UI text stays localizable:** the open notification and refusals use no
  a/an or plural grammar keyed to a count.
- **Typed Python:** constraint and selection types are frozen dataclasses
  and `NewType` ids, collections are `tuple[...]` or `frozenset[...]`, and
  the record documents are `TypedDict`s.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher throughout, as cited above:
  pairwise Equal, an edit-only constraint toolbar, icons at each geometry
  recolored from preferences, deactivated constraints, and silent drops on
  split and delete.
- **Users never read the log:** refusals, the redundancy warning and the
  open report reach the user through the Notification Area and the
  outlines.
- **Manual QA:** one case, `editor.constraints`, for what no test judges:
  the icons read as Sketcher's at a glance and stay sharp on a HiDPI
  screen, the Even spacing icon sits in the same family, and M18's
  scenario without Aligned faces. Start from the
  `large_unit` action, space one column's openings evenly, and make an
  Equal across to another column. Grow the unit, drag a shelf, and see
  both relations hold. Close, move one shelf by hand, reopen, and see
  that relation greyed and removable, with nothing moved. Add no setup
  action.
- **A selection never mixes boards and openings** (user decision,
  2026-11-12): a click on a board, Ctrl or not, replaces a selection of
  openings; Ctrl-click on an opening toggles it in a selection of openings,
  and with boards selected keeps them and adds nothing. No command takes a
  mix, and under Inventor navigation Ctrl-click is the only way to select a
  board, so it must be able to replace an opening.
- **Icons and padlocks sit on tiles of the view background** (user
  decision, 2026-11-13): under a dark theme the opening fill blends to a
  mid gray that a deactivated icon's gray all but matches. A rounded tile
  in the 3D view's background color puts every constraint icon and
  padlock back on the background the theme picks those colors against,
  as SolidWorks and Fusion set sketch relation glyphs on tiles. No
  FreeCAD tool draws one; the Sketcher's icons sit on bare background.
- **Out of scope:** Aligned faces (task 4), the constraint list and
  reactivation (task 3), a spacing basis in the UI, keyboard shortcuts for
  the commands, and bug-021 (a copy loses its constraints as it loses its
  locks).

## Plan
- [x] **Step 1** (`tests/freecad_view/`, `.claude/docs/freecad-notes.md`):
      find whether Sketcher's constraint icon resources exist before
      `SketcherGui` is imported, record it, and keep the check as a test
      of whatever the editor relies on.
- [x] **Step 2** (`core/layout.py`, `core/tests/test_layout.py`): `Equal`
      and `EvenSpacing` with id, basis and active flag. `Unit` carries
      them, and an Even spacing resolves its openings from the tree.
- [x] **Step 3** (`core/solver.py`, `core/tests/test_solver.py`): active
      constraints become engine relations. Conflict, redundancy and
      freedom results carry constraint ids beside region ids.
- [x] **Step 4** (`core/edit.py`, `core/tests/test_edit.py`): creating
      Equal (chained) and Even spacing with their refusals, removing
      constraints, the drops in `split_region`, `merge_at` and board
      deletion, and `held_by` naming constraints.
- [x] **Step 5** (`core/record.py`, `core/scan.py` if needed,
      `core/tests/test_record.py`): the version 2 record, version 1 and
      malformed read as none, and the open reconciliation (deactivate,
      drop) returning a report.
- [x] **Step 6** (`container.py`, `unit_ops.py`, `tests/freecad/test_write.py`,
      `tests/freecad/`): read and write constraints; resize and rescan
      honor active ones.
- [x] **Step 7** (`editor/session.py`, `tests/freecad/test_editor_session.py`,
      `tests/freecad/test_edit_history.py`): the ordered item selection,
      the constraint selection, the two creations, Delete of constraints,
      and the open report, posted once.
- [x] **Step 8** (`editor/elevation.py`, `tests/test_editor_elevation.py`):
      icon positions per opening, clear of text, padlocks and each other,
      and hit-testing; the selection and holding outlines for
      constraints.
- [x] **Step 9** (`editor/overlay.py`, `editor/view_editor.py`,
      `editor/panel.py`, `tests/freecad_view/test_constraints.py`,
      `tests/freecad_view/test_multi_selection.py`): draw and recolor the
      icons, Ctrl-click on openings, icon clicks, Delete routing, the held
      board's outline, and the panel's state with several openings or a
      constraint selected.
- [x] **Step 10** (`commands/constrain_equal.py`,
      `commands/constrain_even_spacing.py`, `init_gui.py`,
      `resources/`, `refusals.py`, `tests/freecad_gui/`): the commands, the
      edit-only toolbar, the menu entries, the Even spacing SVG, and the
      open notification.
- [x] **Step 11** (`README.md`, `docs/scope-and-design.md`,
      `.claude/docs/code-map.md`, `freecad/Shelving/qa/cases/30-editor.toml`):
      the three glossary entries; "What is stored" names the constraint
      record; the code map's `resources/` entry covers the new icon; the
      `editor.constraints` case.

## Review log

### Round 1: REJECTED
- **F1: The icon color test never sets `SelectionColor`** (`tests/freecad_view/test_constraints.py:352`, `tests/freecad_view/test_constraints.py:392`): the Must Have asks for distinct values set for `ConstrainedIcoColor`, `DeactivatedConstrDimColor` and `SelectionColor`; the fixture sets only the first two and compares the selected icon with `editor.style.selected_rgb`, the code's own reading, so a wrong parameter name in `view_style` (`freecad/Shelving/editor/overlay.py:119`) would pass. Meet it without writing FreeCAD's parameter (e.g. patch the editor's color read for `"SelectionColor"`), or record a user decision in `## Advice`.
- **N1: Even spacing refusals that do not say what to select** (`freecad/Shelving/core/edit.py:1058`, `freecad/Shelving/core/edit.py:1048`): reword the one-opening and opening-beside-an-opening refusals as "Select ...".
- **N2: Unit suffixes in the elevation layout test** (`tests/test_editor_elevation.py:570`): `x_px, y_px = label.text_at_mm` holds millimeters; `half_w`, `half_h`, `half` lack suffixes.
- **N3: Odd line wraps in changed docstrings** (`freecad/Shelving/core/edit.py:23`, `freecad/Shelving/editor/view_editor.py:1449`): reflow both.
- **N4: Delete of constraints can move boards** (`freecad/Shelving/editor/session.py`, `_apply`): every edit settles, so a Delete makes another active constraint left within the clearance exact; pin the intended behavior with a test or a sentence in Advice.

### Round 2: APPROVED
- **N1: N4's test docstring claims something it does not check** (`tests/freecad/test_constraint_session.py:358`): it says the deleted even spacing "moves nothing of its own" and cites "the Advice", but the test asserts only that A equals B and the Equal remains. Drop the clause and the pointer, or assert it.

### Round 3: REJECTED
- **F1: Nothing tests the new Must Have "No workbench code imports `SketcherGui`"** (`tasks/active/sh-048-equal-and-even-spacing.md:99`): only a grep confirms it, and `test_both_icons_are_the_workbenchs_own_svgs` pins the icon paths alone, so a reintroduced `import SketcherGui` passes every suite. Add a cheap core-level test that parses every `.py` under `freecad/Shelving/` with `ast` and asserts no `Import`/`ImportFrom` names `SketcherGui`.
- **N1: Round 2's N1 is still open** (`tests/freecad/test_constraint_session.py:358`): the docstring still says the deleted constraint "moves nothing of its own" and cites "the Advice", asserting neither, and now reads oddly beside bug-023. Drop the clause and the pointer, or point to bug-023.
- **N2: Stale Advice bullet** (`tasks/active/sh-048-equal-and-even-spacing.md:159`): "Sketcher resources: unverified ... Check first" reads as open though Plan step 1 answered it in `freecad-notes.md`. Optional: say the answer is recorded there.

### Round 4: REJECTED
- **F1: The tile Must Have's held padlock and rounded padlock corners are untested** (`tests/freecad_view/test_constraints.py:249`, `freecad/Shelving/editor/view_editor.py:304`): the test checks one pixel of each visible opening padlock in `editor.padlocks`, never `editor.board_padlock`, and never that a padlock's corners are rounded, so losing either passes every suite. Check `board_padlock`'s face for the patched tile color (`tests/freecad_view/test_padlocks.py` already shows it), and that a corner pixel of a padlock's `grab()` differs from the tile color.
- **N1: Hard-to-parse `background_rgb` docstring** (`freecad/Shelving/editor/overlay.py:80`): chained appositives; split into short sentences naming `UseBackgroundColorMid`, `BackgroundColor2` and `BackgroundColor3`.
- **N2: Short line wraps left by the edits** (`docs/scope-and-design.md:98`, `freecad/Shelving/qa/cases/30-editor.toml:551`): reflow both paragraphs.
- **N3: Defaults when the gradient keys are unset** (`freecad/Shelving/editor/overlay.py:83`): a missing `Simple` reads as true and a missing `Gradient` as false; FreeCAD may read `Gradient` with a default of true and not read `Simple`. Low risk, since every bundled preference pack sets them; comment if deliberate.

### Round 5: APPROVED
- **N1: Missing noun in the new notes section** (`.claude/docs/freecad-notes.md:291`): "writes the FreeCAD Light pack's plain (247, 247, 247)" needs "plain color".
- **N2: `Style.tile_rgb` default is out of step with the new background defaults** (`freecad/Shelving/editor/overlay.py:125`): the dataclass default is still FreeCAD Light's (247, 247, 247), unlike `_BACKGROUND_DEFAULT` and the gradient-middle default; `view_style` always sets it, so nothing draws with it. Optional: say why in the field's comment, or drop the default.
