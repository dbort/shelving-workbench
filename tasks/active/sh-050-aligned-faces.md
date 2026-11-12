---
id: sh-050
title: "Aligned faces, picked by a board's face edges"
blocked_by: [sh-049]
---

# sh-050: Aligned faces, picked by a board's face edges

## Summary
Adds the last M18 constraint. Aligned faces keeps a face of one board
level with a face of another, top with top or top with bottom, for
example, so a shelf in one column stays in line with a shelf in the next
as the unit is resized or either shelf is dragged. A face is picked by
clicking just outside the board's long edge. A highlight shows the edge
while the pointer is there, as the Sketcher preselects an edge. Picking
an edge also selects its board, so the rest of the editor treats it as an
ordinary board selection. Center planes cannot be aligned.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] Core suite, on a unit 654 mm tall of 18 mm boards, fixed point
      `min`, split by two dividers into three columns: left A1 300, shelf
      s1, A2 300; middle B1 200, shelf t1, B2 400; right C1 250, shelf u1,
      C2 350 (bottom to top):
      - aligning s1's top face with t1's top face gives A1 250, A2 350,
        B1 250, B2 350, with the right column unchanged;
      - aligning s1's top face with t1's bottom face instead gives A1 241
        and B1 259;
      - picks of s1 top, t1 top and u1 top, in that order, make exactly two
        constraints, s1 with t1 and t1 with u1, and give A1, B1 and C1 250;
      - after the first alignment, dragging s1's low face to 318 leaves it
        within 0.001 mm of 318 and t1's low face within 0.001 mm of it;
      - with A1 locked at 300 and B1 locked at 200, aligning s1's top with
        t1's top is refused with a conflict naming A1, B1 and the Aligned;
      - a pick of a board by its body, two faces of one board, or s1's top
        with a divider's face is refused before solving;
      - deleting s1, or merging A1 with A2, removes every Aligned naming
        s1 in the same edit;
      - after the first alignment, locking B1 makes `held_by` of s1 name
        the Aligned.
- [ ] The constraint record writes an Aligned as `{"kind": "aligned",
      "active": <bool>, "faces": [{"board": <board key>, "face": "low" |
      "high"}, {...}]}`, two entries in pick order, with board keys as
      sh-048's Even spacing ends use them, and reads it back. An entry
      with another face string, or not exactly two faces, is dropped and
      nothing is raised.
- [ ] Headless (`tests/freecad/`), opening a container in `Session`:
      - an Aligned whose faces now differ by more than the joint clearance
        comes in deactivated and is written back with `"active": false`
        by the next edit; one off by less comes in active, opening moves
        no board, and the next edit makes the faces coplanar;
      - an Aligned naming a board deleted by hand is dropped, and the open
        notification reports it;
      - creating an Aligned is one undo step, and Undo removes it and
        restores the boards.
- [ ] GUI (`tests/freecad_gui/`): `Shelving_ConstrainAligned` sits on
      sh-048's edit toolbar and in the Shelving menu, `IsActive` is false
      outside an edit, and a selection it cannot use is refused through
      `report_error` with text saying to pick board edges.
- [ ] GUI (`tests/freecad_gui/test_constraint_list.py`): an Aligned row
      shows the Sketcher icon the view uses and text naming the kind and
      both faces in pick order from Top, Bottom, Left and Right. With it
      selected, the "Opening size measures" combo is disabled.
- [ ] 3D view (`tests/freecad_view/test_aligned_faces.py`):
      - a click PickRadius − 1 px outside s1's top face, over A2, selects
        s1 with face `high`, and FreeCAD's selection holds s1 whole; a
        click at A2's center selects A2; a click on s1's body selects s1
        with no face;
      - with PickRadius set to 1000, a click at A2's center still selects
        A2;
      - hovering inside the band draws s1's top edge in the View
        preference `HighlightColor`, and moving out removes it;
      - Ctrl-click in t1's top band after picking s1's top face gives an
        ordered selection of s1 top then t1 top;
      - an Aligned along the height axis draws
        `:/icons/constraints/Constraint_Horizontal.svg` at each of its two
        boards, and one along the width axis draws
        `:/icons/constraints/Constraint_Vertical.svg`. No icon overlaps
        another icon, a dimension's text, or a padlock in device pixels;
      - a selected Aligned outlines its two boards in the selection color.
- [ ] `README.md`'s glossary has an entry **Aligned faces**.
- [ ] `freecad/Shelving/qa/cases/30-editor.toml` has a case with id
      `editor.aligned_faces`.

## Advice
- **Blocked on sh-049:** this needs sh-048's constraint machinery
  (record, toolbar, icons, constraint selection, drops on delete, open
  reconciliation) and sh-049's list, which gains Aligned rows.
- **The relation:** one face, low or high, of each of two boards whose
  faces are perpendicular to the same model axis, width or height, stays
  coplanar. Any combination of low and high. No center planes (user
  decision). Linear in the boards' low faces, so it is one more engine
  relation (sh-045). It carries no basis.
- **Edge picks** (user decision): a press in the band just outside a
  board's long face, within FreeCAD's View preference `PickRadius` beyond
  the face, selects that board exactly as a click on it does (drag arrow,
  Delete, stock), and the session's ordered selection also records the
  face. The band runs along the face's length only, lies over openings or
  outside the unit, is capped at a third of the opening's drawn size so
  the opening keeps a clickable middle, and loses to a board under the
  pointer. Only boards in a run along the width or height axis have
  bands. A click on a board's body selects it with no face. Ctrl-click
  in a band adds that board with that face. On a board already selected,
  it removes the board when the face matches, and switches the face when
  it differs. Compute bands in `editor/elevation.py` so layout tests need
  no view; hit-test them in the press filter after icons and dimension
  text, before openings.
- **Hover** (user decision, Sketcher preselects an edge): while the
  pointer is in a band, the overlay draws that face's edge as a line in
  FreeCAD's preselection color, `HighlightColor` in the View preferences.
  FreeCAD's own preselection of the board's body is untouched.
- **Command:** `Shelving_ConstrainAligned`, one thin module under
  `commands/`, on sh-048's edit toolbar and in the Shelving menu. N face
  picks make N-1 Aligned constraints chained in selection order, as Equal
  does (user decision). Refuse through `report_error`, saying to pick
  board edges, when a pick has no face, two picks share a board, or picks
  lie on different axes. Everything else, same-row boards and carcass
  boards included, goes to the solver, which refuses only an
  unsatisfiable layout through the existing conflict path. Each creation
  is one undo step. A redundant one is accepted and flagged as sh-047 and
  sh-049 do.
- **Icons** (user decision): Sketcher's Horizontal constraint between two
  points puts them at one height, so `Constraint_Horizontal` marks an
  Aligned along the height axis and `Constraint_Vertical` one along the
  width axis. Recolor them as sh-048 recolors Equal. Draw one at each
  board, in the band side of its aligned face, clear of other icons,
  dimension text and padlocks, planned in `editor/elevation.py`.
- **Selection and holding:** a selected Aligned outlines its two boards
  in the selection color, and an Aligned holding a board outlines its
  boards with the holding outline, since it relates boards, not openings.
- **Deletes drop silently:** deleting a board, directly or through a
  merge, drops every Aligned naming it in the same undo step, as sh-048
  drops constraints on a deleted board.
- **Across sessions:** as sh-048 treats Equal. An active Aligned whose
  faces differ by more than `DEFAULT_CLEARANCE_MM` at open comes in
  deactivated; one within it comes in active and the next edit makes it
  exact; one naming a board key that matches nothing is dropped. All of
  it goes into sh-048's one open notification.
- **Constraint list** (user decision): an Aligned row shows the kind and
  both faces in pick order, worded from fixed face names: on the height
  axis low is Bottom and high is Top, on the width axis low is Left and
  high is Right, as seen from the unit's front. No size, and the basis
  combo is disabled for it. Keep the wording free of count-keyed grammar.
- **Typed Python:** the face is a `Literal["low", "high"]`, a face pick a
  frozen dataclass of board id and face, the record entry a `TypedDict`.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher's edge picking with
  preselection, its Horizontal and Vertical constraints between two
  points, its pick radius preference, and its silent drop of a constraint
  whose geometry is deleted.
- **Users never read the log:** refusals and the open report go through
  the Notification Area.
- **Manual QA:** one case, `editor.aligned_faces`, for what no test
  judges: the band is easy to hit and the hover line easy to see at
  default zoom and on a HiDPI screen, and M18's whole scenario.
  Start from the `large_unit` action, space three shelves of the left
  column evenly, align the right column's middle shelf top to top with
  one of them, grow the unit and drag a shelf to see both relations hold;
  close, move one shelf by hand, reopen, and see that relation greyed and
  removable with nothing moved. Add no setup action.
- **Out of scope:** aligning center planes, aligning faces along the depth
  axis, and alignment across units (named values, Later).

## Plan
- [ ] **Step 1** (`core/layout.py`, `core/solver.py`, `core/edit.py`,
      their tests): the `Aligned` constraint with its two face picks;
      its engine relation; creation chained with its refusals; the drops
      on board deletion and merge; `held_by` naming it.
- [ ] **Step 2** (`core/record.py`, `core/tests/test_record.py`): the
      Aligned record entry and the open reconciliation for it.
- [ ] **Step 3** (`container.py`, `unit_ops.py`, `tests/freecad/`): read
      and write Aligned; resize and rescan honor the active ones.
- [ ] **Step 4** (`editor/elevation.py`, `tests/test_editor_elevation.py`):
      the face bands and their hit-test, and the Aligned icons' positions.
- [ ] **Step 5** (`editor/session.py`, `tests/freecad/test_editor_session.py`):
      face picks in the ordered selection, the creation, and the open
      report.
- [ ] **Step 6** (`editor/overlay.py`, `editor/view_editor.py`,
      `editor/constraint_list.py`, `tests/freecad_view/test_aligned_faces.py`,
      `tests/freecad_gui/test_constraint_list.py`): band clicks and the
      hover line, the icons and their outlines, and the Aligned row.
- [ ] **Step 7** (`commands/constrain_aligned.py`, `init_gui.py`,
      `refusals.py`, `tests/freecad_gui/`): the command on the edit
      toolbar and in the menu.
- [ ] **Step 8** (`README.md`, `docs/scope-and-design.md`,
      `freecad/Shelving/qa/cases/30-editor.toml`): the glossary entry, the
      Editing section on face picks and Aligned, and the
      `editor.aligned_faces` case.

## Review log
