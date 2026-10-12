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
| 1 | Board drag through a dragger works in each navigation style, outside edit mode | Retired for CAD, Gesture, Touchpad and OpenSCAD. OpenInventor works with Ctrl held, which is how that style selects anyway |
| 2 | Clicks reach our callback; native selection can be switched off from pivy, or gated to the unit | Retired for both picking modes. `getObjectInfo` names the board through the container (`SubName` `Board001.Face3`) |
| 3 | The floating `QuantitySpinBox` lands on its label on a HiDPI screen and keeps focus; Return and Escape leave the task dialog open | Return and Escape retired. Position on HiDPI and focus behavior open: Xvfb has a pixel ratio of 1 and no window manager |
| 4 | The overlay neither z-fights with board faces nor shows through solids when orbited | Renders correctly from the front, depth-tested and on top. From behind open: the eye judges it faster than a script |
| 5 | Drag stays smooth | Solve and write about 12 ms a step, panel and overlay redraw about 3 ms, on a six-board unit. Large units and real frame rates open |
| 6 | Hiding other objects and restoring them leaves `Visibility` and the undo stack untouched | Retired: undo names unchanged, visibility restored |
| 7 | The overlay follows a moved, rotated container | Retired at 0 and 30 degrees: 0.0000 mm between each board's solid and its overlay. Nested containers untested |
| 8 | Bay and void hit-testing from a 3D ray | Retired |
| 9 | Camera save, front framing, restore | Retired: restored exactly, apart from the near and far planes Coin recomputes on every render |

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
- **Dimension labels compete with boards for clicks.** In a small view a
  label sits on top of the shelf it measures past, and the label wins.
  Label placement and hit priority need design.
- **OpenInventor navigation** consumes the press of the first Ctrl+click,
  so only its release arrives.

### Testing on your laptop

Open a real unit, select it, and run the spike. Use "Log note" to mark
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

Copy `/tmp/shelving-viewport-spike.log` into the VM afterward.

## Suggested next steps

1. Run the laptop test above and bring the log back.
2. Fold the answers into this document, then plan design A with
   `/new-task`, carrying the findings above into its `## Advice`.
3. Before this branch merges, delete `freecad/Shelving/spikes/`, the
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
