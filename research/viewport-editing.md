# Elevation editing in the 3D viewport

Research notes, not a design decision. They live on the
`research/viewport-editing` branch and are meant to be folded into a task
plan or deleted once a direction is chosen.

## Question

The elevation editor draws the unit in a `QGraphicsView` inside the task
panel. On a laptop the panel is small, so the user scrolls the panel and
pans the little view by hand. Can the editor move into FreeCAD's main 3D
view instead, so zoom, pan and orbit are FreeCAD's own navigation, and
stay in Python?

Decisions already made in the interview (2026-10-12):

- **Orbiting stays editable.** Overlays are anchored to the unit's front
  plane in 3D, and picking and dragging keep working at any camera angle.
- **Edit surface: research both** the real solids with an overlay, and a
  Sketcher-like scene of our own.
- **A slim task panel stays** for controls with no place on the drawing:
  the unit's width, depth and height, the size basis, and the list of
  objects this workbench did not create.
- **Desk research first.** Spikes and screenshots only where they buy
  confidence that the source cannot.

Everything below was checked against the FreeCAD 1.1.0 source tag and the
FreeCAD 1.1.3 and pivy 0.6.11 builds in this repo's pixi environment, unless
marked otherwise. Source paths are relative to FreeCAD's `src/`.

## What "like the Sketcher" means

The Sketcher does not open a separate view. Editing a sketch puts its view
provider into edit mode in the same 3D view: the camera turns normal to the
sketch, other objects are optionally hidden or cut by a section plane, and
the view provider's own scene graph and event handler take over. The old
camera comes back when editing ends. Its On-View Parameters
(`Gui/EditableDatumLabel.cpp`) are a `SoDatumLabel` drawn in the scene
plus a real `Gui::QuantitySpinBox` widget floated over the view at the
label's projected position, moved by a sensor on the camera.

PartDesign's patterns show a live preview of the transformed copies in the
3D view (`Mod/PartDesign/Gui/ViewProviderTransformed.cpp`) while the
parameters stay in the task panel. In 1.1, Pad, Pocket, Fillet, Chamfer,
Revolution, Helix, Hole and Thickness also show on-view gizmos: arrows
bound to a task-panel field, built from `Gui/Inventor/Draggers/Gizmo.h`.

So "the Sketcher way" and "the PartDesign way" are the same pattern at two
strengths: a task panel plus scene-graph content in the ordinary 3D view,
with FreeCAD's navigation untouched.

## What FreeCAD 1.1 offers Python

| Need | Python route | Precedent | Confidence |
|---|---|---|---|
| Add overlay geometry to the view | `view.getSceneGraph()` and pivy `insertChild`/`removeChild` | Draft trackers (`draftguitools/gui_trackers.py`) | High |
| Receive mouse and key events | `view.addEventCallbackPivy(type, cb)` | Draft Edit (`gui_edit.py`) | High |
| Screen to 3D | `view.getPointOnFocalPlane`, `view.projectPointToLine` (a ray) | Draft snapper | High |
| 3D to screen | `view.getPointOnViewport(Vector)` | used by `EditableDatumLabel` in C++ | High, but see HiDPI risk |
| Pick real solids | `view.getObjectInfo((x, y))`, pivy `SoRayPickAction` on our subgraph | Draft Edit ray pick | High |
| Native selection as the picker | `Gui.Selection.addSelectionGate`, selection observers | Assembly joints, CAM | High |
| Turn native click selection off | `selectionEnabled` field on the root `SoFCUnifiedSelection` node, through pivy | none found in Python | Medium |
| Camera to the front, then back | `view.setCameraType("Orthographic")`, `setCameraOrientation`, `getCamera`/`setCamera` | Sketcher (C++), Draft working plane | High |
| Own right-click menu | `view.setPopupMenuEnabled(False)` plus a Qt menu | | Medium |
| FreeCAD-styled dimension text | `coin.SoType.fromName("SoDatumLabel").createInstance()` | Draft `archDimTracker` | High |
| FreeCAD-styled drag arrows | `SoLinearDragger`, a registered Coin type, or plain `SoTranslate1Dragger` | Assembly exploded view uses `addDraggerCallback` | Medium |
| A typed size field on the view | `Gui::QuantitySpinBox` from `Gui.UiLoader`, parented to the view's MDI widget and moved on a camera `SoNodeSensor` | `EditableDatumLabel` does exactly this in C++ | Medium |
| A second 3D view of the same document | `Gui.ActiveDocument.createView("Gui::View3DInventor")` | `Std_ViewCreate` | High |
| `setupEditingRoot` and friends | exposed on `view.getViewer()` | | Not usable: see below |

The gizmo classes themselves (`LinearGizmo`, `GizmoContainer`'s C++ API)
and `EditableDatumLabel` have no Python bindings. Their Coin node types
(`SoLinearDragger`, `SoDatumLabel`, `GizmoContainer`) are registered at
startup (`Gui/SoFCDB.cpp`), so Python can create the nodes but must wire
them to fields itself. The wiring is a few hundred lines of C++ in
FreeCAD; a Python equivalent for our needs is smaller, because we need
only linear sizes.

## The container cannot enter edit mode, and that is acceptable

FreeCAD's edit mode (`Gui.ActiveDocument.setEdit`) belongs to a view
provider. The unit's container is an `App::Part` or a link group, whose
C++ view providers answer the default edit mode with the transform
dragger (`Gui/ViewProviderDragger.cpp`). Python cannot override that
without giving the container a proxy or an extension, which would put
workbench state into the document and break the rule that everything
opens intact without the workbench. A C++ workbench would hit the same
wall: real edit mode needs a custom document object type.

What edit mode would add, and what to do instead:

- **Event delivery.** None lost. An edit view provider receives events
  through the same `SoEventCallback` node that `addEventCallbackPivy`
  registers on (`View3DInventorViewer::setEditingViewProvider`), so a
  Python callback sees the same events in the same order as the
  Sketcher does.
- **`viewer->isEditing()`.** Navigation styles read this flag. It is what
  lets Gesture navigation treat a left-drag as a sketch drag rather than
  an orbit, and it suppresses some click-to-select handling. Python
  cannot set it. The workaround is the dragger rule in the next section.
- **`setupEditingRoot`.** Python can call it, but it returns early when no
  view provider is in edit (`View3DInventorViewer::setupEditingRoot`).
  Inserting into the scene graph root, as Draft does, needs no edit mode.

The edit session is therefore Draft-shaped: a command opens the task
dialog, saves the camera, adds an overlay subgraph and event callbacks,
and the dialog's accept and reject remove them and restore the camera.

## Event routing decides the interaction design

A mouse event in the 3D view goes through three stages:

1. **The navigation style** (`Gui/Navigation/*.cpp`) sees it first and may
   consume it for zoom, pan or orbit.
2. **The selection node** `SoFCUnifiedSelection` is the scene graph root.
   On a left release it picks and selects before traversing its children
   (`Gui/Selection/SoFCUnifiedSelection.cpp`), and it marks the event
   handled when it selected something.
3. **Event callbacks** sit in its first child, so ours run after both.

Three consequences:

- **Anything dragged must be a Coin dragger.** Gesture navigation, a
  common choice and the one most likely on a laptop trackpad, hands a
  left press to the scene only when an `SoDragger` is under the cursor
  (`GestureNavigationStyle.cpp`, the `isDraggerUnderCursor` test).
  Outside edit mode a left-drag on plain geometry becomes an orbit.
  OpenSCAD navigation has the same test. So a board is moved by
  grabbing a dragger: a gizmo arrow on the selected board, or an
  `SoTranslate1Dragger` whose translator part is the board's own overlay
  face, so the board itself is the handle. Draft's Edit tool sidesteps
  this by using click, move, click instead of a drag; that is a fallback
  if draggers disappoint.
- **Clicks must not also select solids.** Either turn
  `selectionEnabled` off for the session, or keep native selection on and
  use it, gated to the unit's boards, as the board picker (option A
  below). Both need a spike.
- **Keys.** Escape and Delete reach FreeCAD's own handling before or
  alongside ours. How Escape interacts with an open task dialog and a
  focused floating spin box needs a spike.

A Qt event filter on `view.graphicsView().viewport()` sees raw Qt events
before navigation, and would be the escape hatch if a navigation style
still steals an interaction. It bypasses Coin's picking, so it is a last
resort.

## Candidate designs

All candidates share the Draft-shaped session above, the slim task panel,
and the existing `Session` API, which already rewrites the solids on every
edit, drag steps included, so the 3D model reflows live today. None needs
a change to the core.

### A. Overlay on the real solids

The camera turns to the unit's front, orthographic, framed on the unit.
The real `Part::Box` panels stay visible; other objects are dimmed. Our
subgraph adds, on the front plane of the unit, translucent bay and void
faces, selection outlines, and dimensions as `SoDatumLabel` nodes.

- **Picking.** Boards by picking the real solids (`getObjectInfo` gives
  the object `Name`, and the session already maps names to node ids), so a
  board can be clicked on its edge, its side or its front at any camera
  angle. Bays and voids by a ray (`projectPointToLine`) intersected with
  the front plane, then the existing elevation hit-test logic.
- **For:** the user edits the thing itself, and orbiting shows real
  depths and the effect of each edit. Native preselection highlighting
  can come for free if native selection is the picker.
- **Against:** the overlay has to sit on the front faces without
  z-fighting and without showing through solids when the camera looks
  from behind. The overlay is rebuilt from the session after each edit,
  in step with FreeCAD's recompute.

### B. Own elevation scene, Sketcher-like

The unit's solids are hidden or ghosted, and our subgraph draws the
elevation as flat geometry on the front plane, as the current
`QGraphicsScene` does, with boards drawn at their thickness.

- **For:** the closest translation of today's editor. Every pick is ours,
  so native selection simply stays off. Drawing order is fully ours, so
  occlusion questions go away.
- **Against:** orbiting shows a flat drawing tilting in space, which adds
  little. Hiding the solids changes their `Visibility`, which is saved in
  the document; it must be restored on every exit path, including
  cancel and an exception mid-session. The Sketcher does the same and restores it.

### C. A dedicated 3D view tab, combined with A or B

`Gui.ActiveDocument.createView("Gui::View3DInventor")` opens a second 3D
view of the same document as an MDI tab, with its own camera and native
navigation. The session puts its overlay and callbacks on that view only
and closes it on exit.

- **For:** the user's main camera is never touched; on a large screen the
  two views can be tiled. Selection can be disabled in the edit view alone.
- **Against:** on a laptop a tab hides the main view, so it buys little
  over A or B in place, and it adds window-management code (the user can
  close the tab mid-session).

### D. Baseline: today's view, bigger

Move the current `QGraphicsView` out of the task panel into its own MDI
tab (`Gui.getMainWindow().addWindow`, or a `QMdiSubWindow`). This is the
cheapest fix to the scrolling, but navigation stays ours, not FreeCAD's,
which is the thing this research wants to avoid. It is listed so the cost
of A to C has something to compare against.

### Recommendation

A, with B's drawing as its fallback for bays and voids. A and B differ
mainly in whether boards are picked as real solids or as our own faces,
and the overlay code is the same either way: the bay faces, dimensions and
draggers that B needs are a subset of what A draws. Build A's spike so
board picking can be switched between the two, and decide from use. C is
an option to revisit for large screens, not the first build.

## Mapping today's editor onto the viewport

| Today | In the viewport |
|---|---|
| Click a region or board | Click it in the view (solid pick or ray against the front plane) |
| Drag a board | Grab the board's dragger; it calls `begin_drag`/`drag_to`/`end_drag` |
| Size field and basis menu | Click a dimension: a `QuantitySpinBox` opens on it, as in Sketcher's On-View Parameters. Basis stays in the slim panel or goes in a right-click menu |
| Add Divider, Add Shelf, Delete | Right-click menu on the selection, plus the same buttons in the slim panel; Delete key |
| Readout line | A `SoDatumLabel` or text near the selection, or the slim panel |
| Unit width, depth, height | Slim panel (decided); datum labels on the outer edges later |
| Untagged objects list | Slim panel; it shows only when such objects exist |

The size field keeps FreeCAD's expression language because it is the
same widget the panel uses today.

## Python or C++

C++ would not make a significantly more usable editor. What it would buy:

- Direct use of `EditableDatumLabel` and the `LinearGizmo` classes instead
  of a Python equivalent of their wiring.
- A custom navigation style, or edit mode through a custom object type.
  The first is unnecessary because the editor keeps FreeCAD's navigation;
  the second is ruled out by the document-stays-native rule, in either
  language.
- Speed in mouse-move handlers. Draft's Python trackers show Python is
  fast enough for this, and the dominant cost in a drag is the solid
  rewrite and recompute that happens today anyway.

What it would cost: a compiled module per platform and per FreeCAD minor
release, since FreeCAD has no stable C++ ABI. The Addon Manager installs
source repositories, so a C++ workbench means shipping binaries outside
it or upstreaming the code into FreeCAD. This distribution claim comes
from general knowledge of the Addon Manager and was not checked in source
this pass.

Every capability the designs above need has a Python route. Stay in
Python.

## Risks, and where the spike left them

Each risk was first ranked by desk research. The spike below then ran under
Xvfb on the dev VM (`.claude/docs/xvfb-gui-testing.md`), driven by
`research/spikes/drive_viewport_spike.py`, which sends real Qt mouse and
key events into the 3D view. "Retired" means the driver showed it working;
"open" means only a person at a real screen can settle it.

| # | Risk | Status |
|---|---|---|
| 1 | Board drag through a dragger works in each navigation style, outside edit mode | Retired for CAD, Gesture, Touchpad and OpenSCAD, and on the user's Mac trackpad with Touchpad navigation. OpenInventor works with Ctrl held, which is how that style selects anyway |
| 2 | Clicks reach our callback; native selection can be switched off from pivy, or gated to the unit | Retired for both picking modes. `getObjectInfo` names the board through the container (`SubName` `Board001.Face3`) |
| 3 | The floating `QuantitySpinBox` lands on its label on a HiDPI screen and keeps focus; Return and Escape leave the task dialog open | Retired on the user's Retina Mac: the field opened on its label, took typing at once, and applied on Return. `getSize` reports device pixels (2880 by 1122 for a 1440 by 561 widget at ratio 2), as the placement math assumes. The f(x) formula button is untested |
| 4 | The overlay neither z-fights with board faces nor shows through solids when orbited | Retired by moving the overlay to whichever face the camera sees. From behind, the user found the arrows blocked by boards, and the dimension text showing through the solids even depth-tested (`SoDatumLabel` draws its text without a depth test). On the back face neither happens; the driver drags an arrow from behind |
| 5 | Drag stays smooth | On the user's Mac: solve and write 8.5 ms a step on average, 40 ms at worst, redraw under 2 ms, over drags of 60 to 150 steps on a default unit. Large units open |
| 6 | Hiding other objects and restoring them leaves `Visibility` and the undo stack untouched | Retired, also on the user's own document: 13 objects hidden and restored on both OK and Cancel, undo names unchanged |
| 7 | The overlay follows a moved, rotated container | Retired at 0 and 30 degrees: 0.0000 mm between each board's solid and its overlay. Nested containers untested |
| 8 | Bay and void hit-testing from a 3D ray | Retired |
| 9 | Camera save, front framing, restore | Retired: restored exactly, apart from the near and far planes Coin recomputes on every render |
| 10 | Dimension text is legible | Size retired: sized as the Sketcher sizes it (28 pt on the user's Retina Mac), the user found it bigger. Contrast and overlap reworked since: Sketcher colors, bay dimensions at thirds, outer dimensions outside their region. The user's eye decides |

## The spike

**Spike: Edit Unit in 3D View** sits on its own "Shelving Spikes" toolbar.
It is the Edit Unit panel with its elevation view hidden, so the panel is
the slim panel this research settled on, plus an editor in the active 3D
view (`freecad/Shelving/spikes/`). It logs to
`/tmp/shelving-viewport-spike.log`, appending, with a line at each open.

- The camera turns to the unit's front, orthographic, framed on it, and is
  restored on OK or Cancel.
- Bays and voids are translucent faces on the front plane; dimensions are
  FreeCAD's own `SoDatumLabel`, as in the Sketcher.
- A click picks a board by its real solid, otherwise the region under the
  pointer on the front plane. A click within 24 px of a dimension's text
  opens a size field there; Return applies, Escape closes it.
- A selected inner board shows an arrow dragger along its run.
- Delete merges the selected board.
- Panel switches: who picks (ours, with FreeCAD's selection off, or
  FreeCAD's, limited to the unit's boards), overlay drawn over the solids,
  hide other objects, back to the front view, and a note box that writes a
  line into the log.

### Findings the spike added

- **CAD navigation delays a quick second press.** A left press sooner than
  the double-click interval after the previous one is held back and
  replayed at the release (`NavigationStyle::processClickEvent`). Grabbing
  a dragger right after the click that selected its board therefore does
  nothing. A design that shows the dragger on hover, or on the same press,
  would avoid it.
- **`SoDatumLabel.norm` is in document coordinates.** The node compares it
  with the camera direction to decide which way text reads; a local-frame
  normal mirrors the text.
- **The quantity field cannot be reparented directly.** `setParent` on the
  `Gui::QuantitySpinBox` that `_DimensionField` builds destroys it at once.
  Adding it to a layout in a frame parented to the view works, as the
  panel's rows do.
- **The floating field must consume Escape.** Unconsumed, Escape reaches
  the task dialog and cancels the whole edit.
- **A refused size was reported twice:** Return applied it, then the
  focus-out at closing finished the same edit again. The spike guards it;
  the real editor needs the same guard.
- **A dragged board stays selected.** `Session.drag_to` selects the
  region before the board, which suits the panel's size field; in the
  viewport that hid the arrow after every drag. The user wants the arrow
  to stay until something else is selected, so the spike reselects the
  board after each step.
- **Dimension labels compete with boards for clicks.** In a small view a
  label sits on top of the shelf it measures past, and the label wins.
  Label placement and hit priority need design.
- **OpenInventor navigation** consumes the press of the first Ctrl+click,
  so only its release arrives.
- **Dimension placement.** At the middle of their regions a bay's width
  and height cross at their text, and a click there opened the one drawn
  first. The spike now draws a bay's line two thirds across with its text
  a third along, so the two never meet, and lets the label drawn last win
  a tie. Thirds alone still let a region that holds others put its
  dimension on a child's line. Such a dimension goes outside the unit,
  like a chain dimension on a drawing, when only boards lie between its
  region and that side of the unit; a row already taken there pushes it
  one row further out. Otherwise it stays inside its own region, a sixth
  across: just outside the region it lay over a neighbor's boards and
  dimensions. Dragging labels as in the Sketcher is wanted later, not now.
- **The overlay draws in a fixed order.** Coin defers translucent shapes
  and sorts them by distance from the camera, and `SoDatumLabel` always
  counts itself translucent, so a fill could land over a dimension and dim
  it depending on the view. An `SoTransparencyType` of `BLEND` draws the
  overlay in scene order instead: fills, then outlines, then dimensions,
  with the fills writing no depth (`SoDepthBuffer`) because the label
  draws its lines in the face's own plane, behind the fills.
- **Dimension colors follow the Sketcher:** `ConstrainedDimColor` (red)
  for a fixed size, which drives, `NonDrivingConstrDimColor` (blue) for a
  region sharing the leftover space, which only reports, and
  `SelectionColor` for the selection, all read from FreeCAD's View
  preferences.
- **The overlay follows the camera to the back face.** A camera sensor
  watches which side of the unit the camera is on and redraws the overlay
  on the face it sees, with the same axes and negative z. Text stays
  readable because the label's `norm` stays the front face's normal and
  the node flips the text itself.
- **FreeCAD's picking can select whole boards.** A click on a board's
  face, edge or vertex arrives as that sub-element; the spike replaces it
  with the whole board, which FreeCAD then highlights entirely, and a
  click on an opening clears FreeCAD's selection. Hover preselection still
  highlights only the face under the pointer. In this mode a dimension
  label drawn over a board cannot be clicked, because FreeCAD's selection
  takes the click first.
- **A selection shows as an outline only.** Filling a selected opening in
  the selection color hid its dimensions, which use that color too, so
  only their arrowheads showed.
- **The arrow sits beside the dimension it changes:** just past the line
  of the opening before the board, so a view zoomed in on a tall or narrow
  opening shows both. Coin's stock `SoTranslate1Dragger` is pale grey and
  hard to see; FreeCAD's own arrow (see the requests) would fix that too.
- **FreeCAD's Delete command takes the delete key from a selected
  board.** Under FreeCAD's picking a board sits in FreeCAD's selection, so
  Delete (Backspace on a Mac) fires `Std_Delete`. That removes the board's
  object from the document behind the session and records its own undo
  entry inside the edit. The spike claims both keys with a
  `ShortcutOverride` event filter whenever focus is in the 3D view; the
  key then arrives as a plain key press at the Coin key callback, which
  merges the board. With focus in the tree, `Std_Delete` still runs, so the
  real editor must also guard the board objects or rescan after a
  deletion.
- **The overlay follows the unit's size.** A new depth from the panel
  moves the back face; the overlay recomputes both faces on every redraw
  instead of once at open.
- **FreeCAD imports a module once per process,** so a test session after
  a pull runs the old code until FreeCAD restarts. The fifth laptop
  session did, and reported a fixed bug as still present. The log's open
  lines now say whether any of the workbench's files changed since FreeCAD
  loaded them.
- **Escape in the 3D view is harmless.** With no field open it reaches the
  spike's key callback and the task dialog stays open.
- **Dimension text must be sized as the Sketcher sizes it.** `SoDatumLabel`
  takes points and renders in device pixels. The Sketcher reads the View
  preference `EditSketcherFontSize` (default: the application font's pixel
  size), multiplies by the device pixel ratio and converts at the screen's
  logical DPI (`EditModeCoinManager`, FreeCAD 1.1). A fixed size reads half
  as large on a Retina Mac.
- **Destroying a dragger that has been dragged crashes FreeCAD on macOS.**
  The first drag makes Coin's `SoDragger::getViewVolume` create an
  `SoCallbackAction` with callbacks for two node types, which leaves null
  entries in its per-type lists. Coin before 4.0.4 calls `deleteAll()` on
  those entries when the action is deleted (coin3d/coin#556, fixed in
  4.0.4). The macOS FreeCAD 1.1 bundle ships Coin 4.0.3, and its clang
  build drops the null check, so it segfaults at address `0x10` (seen on
  the user's Mac). Linux builds do not crash, so neither Xvfb nor a pivy
  repro on Coin 4.0.3 here could reproduce it. The spike keeps one dragger
  for the whole session, moves and hides it instead of rebuilding it, and
  on Coin before 4.0.4 never lets it be destroyed, leaking one small
  dragger per session. The real editor needs the same rule.
- **Undo during an edit must be FreeCAD's own Undo, one step per edit.**
  Std_Undo reaches the document from its shortcut, the Edit menu, the
  toolbar and its drop-down list; it is always enabled, task dialog or
  not, and a Python panel can intercept none of those routes. With the
  main editor's one transaction open, Undo commits that transaction and
  undoes it whole, then undoes whatever came before: on the user's Mac,
  two presses removed the session's edits and then the unit itself, with
  the panel still open over a stale session. The spike instead makes each
  edit its own transaction (a drag is one), and a document observer's
  `slotUndoDocument` and `slotRedoDocument` read the unit back from the
  document after every Undo or Redo; the scan reproduces the session's
  unit, so selection and dimensions carry on. The session's first step
  holds only the probe object's creation, so an Undo past the first edit
  removes nothing the user made; the observer redoes it at once and shows
  "Nothing left to undo in this edit". OK undoes the session's steps and
  writes the final unit back as one "Edit Shelving Unit" step, so the
  history after OK matches the main editor's. Cancel undoes them and
  clears the Redo list, which takes a transaction that records a change
  and is then aborted: opening one, or setting `Label` to itself, clears
  nothing. Verified under Xvfb through `Std_Undo` and `Std_Redo`. One
  cost: OK and Cancel also undo any step the user made elsewhere in
  FreeCAD during the session, such as a property edit on another object.

### Requests for the real task

From the user's notes during the second laptop session. None needs the
spike unless it carries a risk the spike can retire.

- **Legible dimensions** at any zoom (risk 10 above), and later, labels
  the user can drag aside as in the Sketcher.
- **FreeCAD's picking, whole boards:** the user prefers FreeCAD's click
  picking, provided a click anywhere on a board selects the whole board
  and a click on an opening deselects it. Not yet certain; the spike now
  does both for trial.
- **Arrows clear of dimension lines:** offset the drag arrow so it does
  not sit on the dimension it changes.
- **Typed moves and a step size,** styled as close to FreeCAD's own
  transform and gizmo arrows as possible: select a movable board, type the
  distance to move it, and set the drag increment. FreeCAD's
  `SoLinearDragger` has `translationIncrement` and `label` fields for
  exactly this and can be created from Python, but its C++ gizmo wiring
  cannot. Whether that node behaves when driven from Python is the one
  request worth a spike.
- **Drag a middle opening:** dragging a bay between two shelves moves both
  shelves together, keeping its size; only those shelves, never a
  neighboring divider. A new core edit.
- **Open spaces edited in the view:** selecting, or double-clicking, an
  opening offers its width and height as on-view fields instead of the
  panel's size field.
- **Unit size in the view:** dragging an outer board resizes the unit, and
  the overall dimensions are clickable fields like the others.
- **Delete removes the selected board,** under either picking mode.
  What deleting an outer board does is undecided: refuse it with a
  message, or remove that side of the carcass.
- **Later:** select several parallel sibling boards and redistribute them
  at a common spacing.
- **Undo and Redo inside the edit,** stepping through the edits made
  since the panel opened (finding above).
- **Add boards from the view:** with an opening selected, buttons over it
  add a shelf or a divider, and the board appears where it would go while
  the pointer is over its button. Qt buttons floating at the opening's
  center, as the spike has them, suit the user; adding selects the new
  board, so its arrow is ready to move it. These buttons and the delete
  key replace the panel's Add Divider, Add Shelf and Delete buttons, which
  the spike hides.
- **A drag moves only the dragged board.** `core.edit.move_board` fixes
  the opening before the board and leaves every opening that shares
  leftover space to absorb the change, so with two shelves in a column,
  dragging the upper one 50 mm moved the lower one 34 mm and landed the
  dragged one 34 mm short of the pointer. The user expects the openings on
  either side to change and nothing else to move. The spike's
  `move_board_locally` also fixes the opening after the board, unless it
  is the last opening in the run still sharing space, in which case it
  takes up the move unaided. The main editor's drag has the same
  behavior, and the real task changes the core edit and its tests.
- **The mouse wheel must not change a field it merely passes over.** Today
  scrolling the panel with the pointer over a size field changes the size,
  and the unit fields apply every wheel step at once. FreeCAD behaves this
  way by default: its `WheelEventFilter` (ignore the wheel on combo boxes
  and unfocused spin boxes) is opt-in through the hidden parameter
  `BaseApp/Preferences/General/ComboBoxWheelEventFilter`, read at startup.
  The panel can install the same filter on its own fields. This affects
  the panel on `main` too.

### Testing on your laptop

Restart FreeCAD after pulling new spike code, and check that the log's
open lines include `code: current`. Open a real unit, select it, and run
the spike. Use "Log note" to mark
what you were doing; the log is what comes back here, so screenshots are
needed only for something that looks wrong.

1. Navigate the way you normally do: zoom, pan and orbit while editing,
   with your usual navigation style and trackpad.
2. Click a dimension and type a size right away. Does the field sit on the
   text and keep the keyboard? Try Return, Escape, and the f(x) formula
   button.
3. Select a divider or shelf and drag its arrow. Is it smooth on your
   largest unit? Try grabbing the arrow right after selecting the board.
4. Compare the two picking modes. Is FreeCAD's hover highlight on boards
   worth having?
5. Orbit around to the back with "Draw overlay over the solids" on and
   off. Which reads better?
6. Tick "Hide other objects", then Cancel. Are your objects visible again,
   and is the undo history clean?
7. Press Escape in the 3D view with no field open. What happens?
8. Is the panel now short enough that it never scrolls?
9. Make a few edits, then press Cmd-Z and Shift-Cmd-Z, and try the Edit
   menu's Undo too. Does each step back one edit? Keep pressing Cmd-Z past
   the first edit. After OK, does one Cmd-Z take back the whole session?
10. Select an opening and use the two buttons over it. Is the preview
    clear, and do the buttons get in the way?

Copy `/tmp/shelving-viewport-spike.log` into the VM afterward.

## Suggested next steps

Laptop sessions have settled the whole list. The f(x) button works; the
panel still scrolls with the Python console open, which the user accepts
because the spike's own controls go away.

1. Recheck the dimension layout and colors, FreeCAD picking with whole
   boards, and orbiting behind the unit.
2. Optionally, spike FreeCAD's `SoLinearDragger` in place of
   `SoTranslate1Dragger` to retire the typed-move and step-size request.
3. Plan design A with `/new-task`, carrying the findings and requests
   above into its `## Advice`.
4. Before this branch merges, delete `freecad/Shelving/spikes/`, the
   toolbar lines in `init_gui.py`, the spike line in
   `.claude/docs/code-map.md`, and `research/spikes/`.

## Sources

FreeCAD 1.1.0 source:

- `Gui/View3DPy.cpp`, `Gui/View3DViewerPy.cpp`: the Python view API.
- `Gui/View3DInventorViewer.cpp`: scene graph layout, `setupEditingRoot`,
  `setEditingViewProvider`, `getPointOnViewport`, `toQPoint`.
- `Gui/Selection/SoFCUnifiedSelection.cpp`: `handleEvent`.
- `Gui/Navigation/GestureNavigationStyle.cpp`,
  `Gui/Navigation/CADNavigationStyle.cpp`,
  `Gui/Navigation/NavigationStyle.cpp` (`isDraggerUnderCursor`).
- `Gui/EditableDatumLabel.cpp`, `Gui/SoDatumLabel.h`.
- `Gui/Inventor/Draggers/Gizmo.h`, `SoLinearDragger.h`, `Gui/SoFCDB.cpp`.
- `Gui/ViewProviderPart.h`, `Gui/ViewProviderDragger.cpp`.
- `Mod/PartDesign/Gui/ViewProviderTransformed.cpp`.

FreeCAD 1.1.3 installed Python: `Mod/Draft/draftguitools/gui_edit.py` and
`gui_trackers.py`, `Mod/Assembly/CommandCreateView.py`.
