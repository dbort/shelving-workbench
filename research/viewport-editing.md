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

## Risks, ranked, and how to retire each

Most open questions are about event routing and focus, which a screenshot
cannot show. A macro the user runs on their own machine, which prints what
happened as text, retires them more cheaply than screenshots parsed here.
Screenshots help in two places only, marked below, and the user judging
them by eye beats sending them back.

| # | Risk | Confidence now | Retire with |
|---|---|---|---|
| 1 | Board drag through a dragger works in Gesture, CAD, OpenInventor and Touchpad navigation, outside edit mode | Medium | Macro: a dragger on a box, tried in each style, printing callback events |
| 2 | Clicks on overlay faces and solids reach our callback, and native selection can be switched off through the `selectionEnabled` field from pivy, or gated to the unit | Medium | Same macro |
| 3 | A floating `QuantitySpinBox` positions correctly on a HiDPI laptop (`getPointOnViewport` returns device pixels with y up; `toQPoint` in C++ flips and divides by the pixel ratio), takes focus, and Enter and Escape do not close the task dialog | Medium-low | Macro, run on the laptop |
| 4 | The overlay on the front plane neither z-fights with the board faces nor shows through solids when orbited | Medium | Macro plus the user's eye; a screenshot only if it looks wrong |
| 5 | Overlay rebuild plus the existing per-step solid rewrite stays smooth in a drag on a large unit | Medium | Macro with the existing `Stopwatch` timings printed |
| 6 | Hiding or dimming other objects and restoring them leaves `Visibility` and the undo stack untouched | Medium | Macro, checking `Visibility` and undo names after cancel |
| 7 | The overlay follows a container with a non-identity or nested `Placement` | High | Unit test on the geometry, no GUI |
| 8 | Bay and void hit-testing from a 3D ray | High | Unit test, no GUI |
| 9 | Camera save, front framing on the unit, restore | High | Folded into the first macro |

Items 1 to 3 decide whether the viewport editor is viable at all and
belong in one spike macro. Items 4 to 6 belong in a second one if the
first passes.

This VM cannot run any of these: offscreen Qt cannot create FreeCAD's
OpenGL view ("QOpenGLWidget is not supported on this platform"). An Xvfb
plus Mesa display from conda-forge might let an agent run the macros for
crashes and API errors, though not for feel or HiDPI behavior; it is worth
trying only if spikes become frequent.

## Suggested next steps

1. Spike macro 1 under `research/spikes/`, run by the user in FreeCAD 1.1
   on the laptop: open a unit, turn the camera to its front, draw one bay
   face and one board dragger, a clickable `SoDatumLabel` that opens a
   floating `QuantitySpinBox`, and log each event as text. Covers risks 1
   to 3 and 9.
2. If it passes, spike macro 2 for risks 4 to 6 on a real unit with the
   live `Session`.
3. Then a `/new-task` plan for design A, with the spike findings in its
   `## Advice`.

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
