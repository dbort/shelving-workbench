---
id: sh-040
title: "Edit Unit works in the 3D view"
blocked_by: [sh-037, sh-038, sh-039]
---

# sh-040: Edit Unit works in the 3D view

## Summary
Edit Unit stops drawing the unit in a small picture inside the task panel
and works in FreeCAD's own 3D view instead, so zoom, pan and orbit are
FreeCAD's navigation and the user picks and drags the unit's real boards.
The camera turns to face the unit as the Sketcher's does; openings and
Sketcher-style dimensions are drawn over the boards; clicking a dimension
types a size on the spot, buttons over a selected opening add a shelf or a
divider, an arrow drags the selected board, and Delete removes it. The task
panel shrinks to the unit's size, the size basis and the list of objects
left alone. This retires the panel's elevation, and with it bug-004 and
bug-009. Milestone M14.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] `freecad/Shelving/editor/scene.py` and `tests/test_editor_scene.py`
      no longer exist, and the task panel holds no `QGraphicsView`.
- [ ] The panel holds exactly: the Unit group (width, depth, height), the
      selected opening's basis menu, the list of objects left alone (shown
      only when it is not empty, with its Delete Selected button), and a
      "Hide other objects" checkbox, unticked when the panel opens. No
      size field, Add Divider, Add Shelf or Delete button remains.
- [ ] Every panel spin box and combo box ignores a wheel event unless it
      has focus: a `QWheelEvent` sent to an unfocused field leaves its
      value and the document unchanged.
- [ ] In the view tier (sh-037), Edit Unit adds one overlay node to the
      active view's scene graph and every exit (Close, an Undo that removes
      the unit, an exception while the editor is built) removes it,
      restores FreeCAD's selection settings and the visibility of every
      object, and leaves each edit as its own undo step, as sh-039
      specifies.
- [ ] Opening turns the camera with `view.setCameraOrientation` to face
      the unit's front, orthographic, for a container at its default
      placement and for one moved and turned 30 degrees about Z, and
      every board's front corners then project inside the view. On close
      the camera is restored when the
      `Mod/Sketcher/General/RestoreCamera` preference is true (its
      default) and left where it is when false.
- [ ] Each bay and void is a translucent face on the unit's front face:
      for both placements above, every face's corners lie within 0.01 mm
      of its solved region's front face in document coordinates. With the
      camera behind the unit the overlay is drawn on the back face, and
      back in front on the front face.
- [ ] One `SoDatumLabel` per region in each run that lies in the
      elevation plane, reading the region's size as its basis measures
      it, colored with the View preferences `ConstrainedDimColor` when the
      region is locked, `NonDrivingConstrDimColor` when unlocked, and
      `SelectionColor` when selected, and sized as the Sketcher sizes its
      dimensions (`EditSketcherFontSize`, the device pixel ratio and the
      screen's logical DPI). Its `norm` is the unit front face's normal in
      document coordinates on either face.
- [ ] Picking is FreeCAD's selection, gated to the unit's boards: a click
      on any face, edge or vertex of a board selects the whole board in
      FreeCAD (no sub-element names) and in the session; a click on an
      opening selects that opening and clears FreeCAD's selection; a
      click on an object outside the unit selects nothing. On
      `tests/freecad/fixtures/woodworking_magic_start_default.FCStd`, whose
      back panel lies behind every opening, a click on each opening selects
      that opening, and hovering an opening shows no forbidden cursor.
- [ ] A click on a dimension's text, including one drawn over a board,
      opens a quantity field there showing the region's size; typing a
      size and pressing Return applies it as one edit and closes the
      field, a refused size is reported exactly once, Escape closes the
      field without closing the task dialog, and the field follows the
      label when the camera moves.
- [ ] A selected board that sh-038's query says may move shows one arrow
      along its run, beside the dimension of the region before it;
      dragging the arrow moves the board under sh-038's rule as one undo
      step, and the board and its arrow stay selected afterward. A held
      board and a carcass board show no arrow. Drags and clicks pass under
      the CAD, Gesture, Touchpad and OpenSCAD navigation styles, and
      under OpenInventor with Ctrl held.
- [ ] The editor creates one dragger per session and, on Coin before
      4.0.4, never destroys it.
- [ ] A selected bay shows two buttons at its center, Add shelf and Add
      divider; with the pointer over one, the board it would add is drawn
      where the split would put it; clicking adds that board as one edit
      and selects it, showing its arrow. Neither button shows unless the
      selection is a bay.
- [ ] With focus in the 3D view, Delete and Backspace delete the selected
      inner board as one edit and `Std_Delete` does not run; on a carcass
      board they report a refusal in the Notification Area and change
      nothing. Deleting a board's object from the tree view during the edit
      leaves the overlay and panel showing the rescanned unit, and one Undo
      restores the board.
- [ ] Ticking "Hide other objects" hides every visible object outside the
      unit; unticking and Close restore exactly the objects it hid,
      and FreeCAD's undo names are unchanged by either.
- [ ] `freecad/Shelving/qa/cases/30-editor.toml` covers the new editor
      with only what no test asserts: navigation and dragging on a real
      trackpad, the field landing on its label and the dimension text's
      legibility on a HiDPI screen, the f(x) dialog from the floating
      field, the camera's turn and return, and drag smoothness on a large
      unit.
- [ ] `bug-004` and `bug-009` are deleted from
      `.claude/docs/bug-log.md`; `README.md`, `docs/scope-and-design.md`,
      `.claude/docs/code-map.md` and `freecad/Shelving/editor/__init__.py`
      describe the editor in the 3D view.
- [ ] The panel's size fields bind no temporary object: after a session
      that used an f(x) expression, Close adds no undo step and leaves no
      object behind, and `Std_Undo` after Close steps back exactly one
      edit.

## Advice

FROM sh-039 (2026-10-13): the editor's edits stay as their own undo steps,
Undo and Redo go wherever FreeCAD's history takes them with the editor
rescanning after each, and the panel's only button is Close, as in
Sketcher's edit mode. FreeCAD's f(x) dialog records its binding as a step
of its own, so a field bound to sh-039's temporary probe object leaves a
"Remove Shelving Dimension" step at Close; bind the slim panel's size
fields to properties of a real object, as FreeCAD's own task panels do, so
there is no temporary object.

DECISIONS (user, 2026-10-12 and 2026-10-13, in the viewport-editing
research; `06d20ab:research/viewport-editing.md` on branch
`research/viewport-editing` has the whole account, and that branch stays
until sh-041 ships):
- **Design A:** an overlay on the real solids in the active 3D view,
  FreeCAD's navigation untouched, a slim task panel. Python only; the
  container cannot enter FreeCAD's edit mode without putting workbench
  state in the document, so the session is Draft-shaped: the command opens
  the task dialog, saves the camera, adds an overlay subgraph and event
  callbacks, and Close removes them.
- **FreeCAD's picking, whole boards.** The spike's switch to its own
  picker goes away.
- **The camera turns as the Sketcher's does:** `view.setCameraOrientation`
  is the call `ViewProviderSketch::setEditViewer` makes, rotating about
  the focal point and animating when `UseNavigationAnimations` is on. Then
  fit the unit; a jump there is acceptable if FreeCAD's fit cannot
  animate. Pull the camera back first if the front face would land in
  front of it, as the Sketcher does. On close, restore only when
  `Mod/Sketcher/General/RestoreCamera` is set; the user wants the return
  animated where possible (the Sketcher's own return jumps, through
  TempoVis `setCamera`).
- **Slim panel** as the Must Have lists. Unit sizes stay in the panel;
  typing them on the drawing is later work.
- **"Hide other objects"** is a panel checkbox, off by default.
- **In-view add buttons** replace the panel's: Qt buttons floating at the
  opening's center, as in the spike, suit the user; adding selects the
  new board so its arrow is ready.
- **A drag keeps the board selected**, and its arrow stays until
  something else is selected. `Session.drag_to` selects the region before
  the board for the old panel's size field; change that.
- **Deleting a carcass board is refused** for now. What it should do is a
  later decision (`docs/roadmap.md` § Later).
- **Not in this task:** padlocks and the held board's padlock (sh-041);
  typed moves and a step size, opening and unit sizes typed on the
  drawing, labels dragged aside, a full-height divider over a selected
  `Division` (bug-005).

FINDINGS from the spike, each one a constraint
(`06d20ab:freecad/Shelving/spikes/viewport_editor.py`,
`viewport_panel.py` and `command.py` are the reference;
`06d20ab:research/spikes/drive_viewport_spike.py` drove it):
- **Draw in one elevation frame:** x along the elevation's horizontal,
  y along its vertical, z toward the camera, origin at the unit's minimum
  corner on the face the camera sees. `SoDatumLabel` lays text out in its
  local XY plane only, which forces that frame, and it makes bay picking a
  ray meeting z = 0 (`view.projectPointToLine`).
- **`SoDatumLabel.norm` is in document coordinates**; a local-frame
  normal mirrors the text. Keep the front face's normal on both faces and
  the node flips the text itself.
- **Draw order:** Coin defers translucent shapes and `SoDatumLabel`
  counts as translucent, so use an `SoTransparencyType` of `BLEND` and
  draw fills, then outlines, then dimensions, with fills writing no depth
  (`SoDepthBuffer`), since labels draw their lines in the face's plane.
- **Selection shows as an outline only:** a fill in the selection color
  hides the selected dimensions, which use that color too.
- **Overlay on the face the camera sees:** a camera `SoNodeSensor` decides
  the side; the sensor fires mid-render, so switch sides from a
  `QTimer.singleShot(0, ...)`. Recompute both faces on every redraw: a
  depth change from the panel moves the back face.
- **Never change the scene graph inside a Coin callback;** defer every
  rebuild a Coin callback triggers with `QTimer.singleShot(0, ...)`, and
  keep the dragger under its own holder that a rebuild during a drag
  leaves alone.
- **Destroying a dragged dragger crashes FreeCAD on macOS** (Coin before
  4.0.4, coin3d/coin#556; FreeCAD 1.1's macOS bundle ships 4.0.3). Keep one
  dragger per session, move and show or hide it, and on Coin before 4.0.4
  keep it referenced for the life of the process.
- **Anything dragged must be a Coin dragger:** Gesture and OpenSCAD
  navigation hand a left press to the scene only over an `SoDragger`. An
  `SoTranslate1Dragger` works; Coin's default one is pale grey and hard
  to see, so give it a visible color. Place it just past the dimension
  line of the region before the board, so a zoomed view shows both.
- **CAD navigation delays a quick second press** past the double-click
  interval, so grabbing the arrow right after the click that selected the
  board does nothing. Showing the arrow on hover, or acting on the same
  press, would avoid it; at least do not make it worse.
- **Clicks on labels over boards:** with FreeCAD's picking on,
  `SoFCUnifiedSelection` takes a click on a board before any event
  callback, so a label drawn over a board cannot be clicked through a
  Coin callback. Hit-test label text first, for instance from a Qt event
  filter on `view.graphicsView().viewport()`, which sees events before
  navigation, consuming only clicks within the label radius (the spike
  used 24 device pixels).
- **Clicks on openings with something behind them never reach a Coin
  callback.** With FreeCAD's picking on, `SoFCUnifiedSelection` consumes
  the left release whenever its ray hits any object, even one the gate
  refuses: on the user's magicStart unit every opening click hit the back
  panel (`Back`), the press reached the spike but the release never did,
  and no opening could be selected. The refusal is also what showed the
  forbidden cursor over openings. Neither `TempoVis.setUnpickable` nor
  `ViewObject.Selectable = False` on the back panel helped: a link
  group's children are drawn and picked through the link's own nodes.
  Verified under Xvfb on that unit: a Qt event filter on
  `view.graphicsView().viewport()` sees the press and release first, and
  on a click whose deferred check finds no board selected, picking the
  region under the pointer with the front-plane ray selects each opening.
  Handle opening clicks there, with the label clicks below. The cursor
  still needs a fix: for instance a gate that admits the unit's own
  set-aside parts while an observer turns such a pick into the opening
  under the pointer, or another way to keep FreeCAD from refusing over an
  opening; the probe is in the session's scratchpad only, so re-derive it.
- **Gating selection:** `FreeCADGui.Selection.addSelectionGate` limited
  to the unit's boards, an observer that replaces a sub-element pick with
  the whole board (deferred: it runs inside FreeCAD's selection change),
  and a click on an opening clears FreeCAD's selection. Hover
  preselection still highlights only the face under the pointer; accepted.
  `getObjectInfo` names a board through the container (`SubName`
  `Board001.Face3`).
- **The floating field:** `Gui::QuantitySpinBox` from the UI loader, as
  the panel's `_DimensionField` builds it. `setParent` on it destroys it at
  once; add it to the layout of a frame parented to the view's parent
  widget. It must consume Escape, or Escape cancels the task dialog. Return
  applies, then the close's focus-out would apply the same edit again:
  guard it so a refusal reports once. Place it with
  `view.getPointOnViewport`, which is device pixels with y up; divide by
  `devicePixelRatioF()`.
- **Dimension text sized as the Sketcher's:** `SoDatumLabel.size` takes
  points but renders device pixels; the Sketcher multiplies
  `EditSketcherFontSize` (default: the application font's pixel size) by
  the device pixel ratio and converts at the screen's logical DPI
  (`EditModeCoinManager`). A fixed size reads half as large on Retina.
- **Dimension placement:** a bay's line two thirds across it with its
  text a third along, so its width and height never cross; a region that
  holds others puts its dimension outside the unit when only boards lie
  between it and that side, one row further out per row already taken,
  and otherwise a sixth across inside itself. On a tie the label drawn
  last wins a click.
- **Delete:** under FreeCAD's picking a selected board is in FreeCAD's
  selection, so Delete or Backspace (a Mac's delete key) fires
  `Std_Delete`, which removes the object behind the session. Claim both
  keys with a `ShortcutOverride` filter while focus is in the 3D view;
  they then arrive at the Coin key callback. With focus in the tree,
  `Std_Delete` still runs; sh-039's rescan after a step made elsewhere
  covers it.
- **Escape in the 3D view** with no field open is harmless; keep it so.
- **Hiding other objects** and restoring them leaves `Visibility` and the
  undo stack untouched when done through the view objects, as the spike
  did on the user's own document.
- **OpenInventor navigation** consumes the press of the first Ctrl+click.
- **Drag cost** on the user's Mac: solve and write about 10 ms a step,
  redraw under 3 ms; nothing to optimize unless the large-unit QA case
  says so.

CONSTRAINTS:
- `freecad/Shelving/editor/` keeps its layering: drawing and frame math
  that need no document stay testable without FreeCAD's GUI; `session.py`
  owns the document; the panel and the view editor are Qt and Coin
  shells over the session. Name the modules for what they hold.
- pivy ships no types: one `Any` alias for Coin nodes, commented, is the
  boundary; everything else is typed.
- FreeCAD.app runs Python 3.11 while pixi runs 3.12: nothing 3.12-only;
  `override` from `freecad.Shelving.compat`.
- `freecad/Shelving/commands/edit_unit.py` hooks bug-011's first-paint
  timing to `panel.view`; move that hook to what the user first sees now.
- The QA wizard contract applies to the rewritten cases
  (`.claude/docs/qa-wizard.md`): closed-data TOML, one action per line,
  setup actions only through public API.

USERS OF WHAT GOES (grep before deleting): `editor/scene.py` is imported
by `freecad/Shelving/editor/panel.py` and `tests/test_editor_scene.py`,
and named in `freecad/Shelving/editor/__init__.py`,
`.claude/docs/code-map.md` and bug-009's entry; `panel.view` is used by
`freecad/Shelving/commands/edit_unit.py` and `tests/freecad_gui/test_panel.py`
(the drag, click and minimum-height tests); the panel's size field and
Add/Delete buttons are exercised throughout `tests/freecad_gui/test_panel.py`
and `tests/freecad_gui/test_refusals.py`; `README.md`'s opening paragraph
describes editing the elevation.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: as above; `pyrefly check` clean.
- Shell stays simple: no shell.
- Users never read the log: every refusal (a refused size, a carcass
  board's delete, a failed split) reaches the user through the
  Notification Area, as the editor's refusals do today; the spike's log
  file does not come along.

## Plan
- [x] **Step 1** (`freecad/Shelving/editor/`): The elevation frame and the overlay drawing (faces, outlines, dimensions, back face, colors, sizes), with tests that need no GUI for the frame math and placement.
- [x] **Step 2** (`freecad/Shelving/editor/`, `freecad/Shelving/commands/edit_unit.py`): The view editor's lifecycle: camera turn, fit and restore, overlay and callbacks added and removed on every exit, selection gate and whole-board picking, opening picks, hide-others.
- [x] **Step 3** (`freecad/Shelving/editor/`, `freecad/Shelving/editor/session.py`): The floating size field over labels, the drag arrow with sh-038's rule and the board kept selected, the add buttons with their preview, and Delete.
- [x] **Step 4** (`freecad/Shelving/editor/panel.py`, `freecad/Shelving/editor/scene.py`, `tests/test_editor_scene.py`, `tests/freecad_gui/`): The slim panel with the wheel filter; delete the scene and the elevation, and bring the offscreen GUI tests to the slim panel.
- [x] **Step 5** (`tests/freecad_view/`): View-tier tests for every Must Have, parametrized over navigation styles where they click or drag.
- [x] **Step 6** (`freecad/Shelving/qa/cases/30-editor.toml`, `freecad/Shelving/qa/actions.py`, `README.md`, `docs/scope-and-design.md`, `.claude/docs/code-map.md`, `freecad/Shelving/editor/__init__.py`, `.claude/docs/bug-log.md`): The manual cases for what only a person can judge; the docs; delete bug-004 and bug-009.

## Review log

### Round 1: REJECTED
- **F1: Binding the size fields to the container's `Placement.Base.x/y/z` breaks Edit Unit on supported containers** (`freecad/Shelving/editor/panel.py:39`, `freecad/Shelving/editor/view_editor.py:65`, `freecad/Shelving/editor/fields.py:210`): an `App::DocumentObjectGroup` container has no `Placement`, so binding raises while the panel builds and Edit Unit refuses as unexpected; a user expression on the container's `Placement.Base.x` makes the Width field and every floating field read-only. Bind to a property every accepted container has and that cannot already hold a user expression; test a plain-group container and a placement expression for the panel fields and the floating field.
- **N1: freecad-notes still describes the probe object** (`.claude/docs/freecad-notes.md:172`).
- **N2: Unit suffixes missing on a few new quantities** (`freecad/Shelving/editor/view_editor.py:159`, `:675`, `:697`; `tests/freecad_view/test_editor_input.py:122`).
- **N3: A late camera restore can jump the next session's camera** (`freecad/Shelving/editor/view_editor.py:1089`): a pending restore poll can override a new session's turn and fit on the same view.
- **N4: The default of the RestoreCamera preference is not exercised** (`tests/freecad_view/test_editor_drawing.py:215`).

### Round 2: REJECTED
- **F1: The size fields' properties get saved into the user's file** (`freecad/Shelving/editor/session.py:81`, `:250-252`): `Transient` keeps only the value out of the file; a save during the edit writes all four `ShelvingField*` declarations into `Document.xml`, putting workbench state in the user's document. Add them with the `Prop_NoPersist` attribute (32) instead, test a save during the session, and correct the comment.
- **N1: `Session.close` raises once the container object is destroyed** (`freecad/Shelving/editor/session.py:268-270`): `hasattr` does not catch FreeCAD's `ReferenceError`, so `EditUnitPanel._end` (`freecad/Shelving/editor/panel.py:374`) raises before `closeDialog()` on the lost-unit path, and from the form's `destroyed` slot after the document closed.
- **N2: The container test's parameter could be a `Literal`** (`tests/freecad_view/test_editor_input.py:731`).

### Round 3: APPROVED
- All three round 2 findings are fixed: the size fields' properties carry `Prop_NoPersist` and a save during the session writes none of them; `Session.close` survives a destroyed container; the view test's `kind` is a `Literal`. Nothing new blocks.

### Round 4: APPROVED
- Reviewed the QA fixes in abe363d: the overlay's bounding box reaches the dimensions, so a square-on camera no longer clips their lines and text (confirmed by the user on FreeCAD 1.1.4 for macOS); the camera restore survives its document closing; an unexpected Edit Unit refusal logs its traceback. Both new view tests fail without their fixes.
- **N1: The unreproduced "QGraphicsView already deleted" refusal is recorded only in conversation** (`freecad/Shelving/commands/edit_unit.py:147`): give it a bug-log entry so the next QA run captures the Report view.
- **N2: Ambiguous referent in the new docstring** (`freecad/Shelving/editor/overlay.py:214`): name `SoDatumLabel`.

### Round 5: REJECTED
- **F1: `pixi run tests` is red: the new test fails, and its failure cascades** (`tests/freecad_view/test_editor_drawing.py:535`, `freecad/Shelving/editor/view_editor.py:469`): the test's `ViewDriver` keeps the closed view's `graphicsView()` wrapper; when FreeCAD puts the next view at the same address, `view.graphicsView()` returns that wrapper and `viewer.destroyed.connect(...)` raises "Signal source has been deleted", failing this and later tests. Make the test deterministic, and make `_open` cope with a stale wrapper held elsewhere or record in Advice why that is out of scope.
- **N1: The `alive` callable passed to the camera restore never turns false** (`freecad/Shelving/editor/view_editor.py:598`, `:1153-1167`).
- **N2: FreeCAD has its own auto-close for a Python task dialog's document** (`freecad/Shelving/editor/panel.py:350-357`): Assembly's `setAutoCloseOnDeletedDocument(True)` and `setDocumentName`; use it for the document case or say in Advice why one signal covers both.
- **N3: `_view_closed` closes whatever dialog is active, even after the panel has already ended** (`freecad/Shelving/editor/panel.py:350`).
- **N4: `_DeleteKeys` still keeps the viewer wrapper** (`freecad/Shelving/editor/view_editor.py:254`).
