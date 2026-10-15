# Roadmap

The open milestones of [`scope-and-design.md`](scope-and-design.md). Each
ends with a concrete way to see it working in FreeCAD, and each becomes one
or more `sh-XXX` tasks. A milestone is removed from this file once its last
task ships.

## M10: v1 polish

**Status:** Tasks sh-022, sh-035, sh-023

- [x] sh-022: one refusal shape, and Edit Unit as the one way in
- [ ] sh-035: Relabel Unit (blocked on sh-022)
- [ ] sh-023: the preferences page

A board takes a readable label and its source board's color when it is
written, and an update rewrites neither, so a rename or a recolor survives
every resize. A command restores the label on request.

Every refusal has one shape: a summary, the objects responsible, and a
suggested next step, with the objects selected in the 3D view. The
suggestion is data beside each reason, because a refusal a user cannot act
on reads as a bug. With that in place, Edit Unit says everything about a
hand-built unit that the separate scan command did, so that command is
removed and Edit Unit is the one way in.

The preferences page holds the starter unit's three dimensions and the snap
and joint-clearance tolerances. Real geometry has coincident edges
disagreeing by up to 0.09 mm, and someone whose model is worse needs a way
forward that is not editing the source.

The user guide leads with scanning geometry you already have, documents
what each refusal means, and states the three limits a user will meet. It
and the release have no task until M14 ships, so the guide describes the
editor users will keep.

*Verify in FreeCAD:* install from the GitHub repository through the Addon
Manager on a clean profile, model a real unit, move it into a second
document with an ordinary placement, confirm an over-constrained input
produces a clear error and no stale geometry, and walk the user guide's
steps exactly as written.

## M14: Editing in the 3D view

**Status:** Tasks sh-037, sh-038, sh-039, sh-040, sh-041

- [x] sh-037: 3D-view tests under Xvfb
- [x] sh-038: locked openings, and a drag that moves only what it drags
- [x] sh-039: Undo and Redo inside an edit (blocked on sh-037)
- [ ] sh-040: Edit Unit works in the 3D view (blocked on sh-037, sh-038
  and sh-039)
- [ ] sh-041: padlocks lock and unlock openings in the view (blocked on
  sh-040)

The editor moves out of the task panel into FreeCAD's own 3D view, so zoom,
pan and orbit are FreeCAD's navigation. The camera turns to face the unit
as the Sketcher's does, and the unit's real boards are what the user picks
and drags. Openings are drawn over the boards with dimensions in the
Sketcher's style; clicking a dimension types a size on the spot, buttons
over a selected opening add a shelf or a divider, and an arrow drags the
selected board. A slim task panel keeps the unit's size and the controls
with no place on the drawing.

An opening is locked at its size or unlocked to share what is left. A drag
moves only the dragged board, together with any board joined to it through
locked openings, and a padlock on each dimension locks or unlocks it. Undo
and Redo step through the edits inside a session, one edit each, and the
edits stay as their own steps after the panel closes.

*Verify in FreeCAD:* open a unit with Edit Unit, watch the camera turn to
it, orbit behind it and back, lock the opening between two shelves and drag
one of them, add a shelf from the view, undo and redo a few edits with
Cmd-Z, click Close, and undo the last edit with one Cmd-Z.

## M11: Back panels

**Status:** Planned

Backs and fronts as boards in the depth axis rather than parts set aside
during scanning, with their treatments (rabbeted, overlay, captured) and a
back material.

*Verify in FreeCAD:* add a back to an existing unit; it appears, tracks
size changes, and scans back as the same treatment.

## M12: Framing: `StudWall`

**Status:** Planned

A second consumer of the same core: bottom plate, double top plate, and
studs at on-center spacing with a remainder stud. Brings the repeat rule,
where a member count is computed from a pitch, and with it a second
identity scheme, because members with no durable identity still have to be
matched on reflow. The pitch is recovered from stored properties, never
from geometry.

*Verify in FreeCAD:* create a wall, change its length and stud spacing,
and watch the studs redistribute with a correct remainder.

## M13: Framing: openings

**Status:** Planned

An opening subdivides a bay and expands to king, jack, cripple, header,
and sill members, with parametric header depth and rough-opening
clearances.

*Verify in FreeCAD:* place a window and a door opening in a wall, move one
and change its size, and confirm the cripples and jacks follow.

## Later

**Status:** Planned

Each of these is its own task when it comes up.

- **Named values shared between units.** A rule names a value in an
  ordinary `VarSet` instead of holding a literal. One mechanism then covers
  cross-unit alignment, driving a unit from its surroundings (a `VarSet`
  property carries an expression), and exposing values outward. Only the
  handful of driving values become expressions; every derived dimension
  stays in the solver. Resolve a named value in the same pass that resolves
  a `WITH_NEXT` basis to a clear size.
- **Live units**: an opt-in per-unit driver that reflows on recompute
  rather than on command. A live unit is not hand-editable, and the choice
  between the two should be explicit.
- **Assemblies on more than one plane**: a corner, a T of runs, an aisle.
  Seen from above each is itself a straight-cut subdivision, so the region
  tree extends to it one level up; the model already lets a division name
  any axis. Cutting first decides which run passes the corner, and sibling
  runs share heights for free. Shelves in separate runs still line up only
  through shared named values. The cost is in the editor, which needs a
  plan view beside the per-run elevation.
- **Panels that are not boxes**, starting with a notched panel such as one
  clearing a breaker box. Options: refuse it; adopt it by its bounding box
  as pinned, which works on existing geometry today; model it as a
  rectilinear profile extruded through a thickness, derived from its
  largest face, which covers an edge notch, an L-shaped top and a stepped
  end; or have the user's own `Part::Cut` consume a box this workbench
  owns. None covers a stopped pocket, a miter, or anything not
  axis-aligned.
- **Physical materials** that reference FreeCAD's own material system, so a
  stock entry names a substance. Stock and substance are separate lists: a
  thickness belongs to the sheet you bought, a density to the material.
  Mass is the first payoff, since per-board volume is already computed.
- **A support check.** A board floating clear of its neighbors is a valid
  arrangement of straight cuts and is accepted today; whether a design is
  buildable is a separate question that nothing asks yet.
- **Spacing constraints** beyond a lock per opening: a group of shelves
  kept evenly spaced, so moving one moves them all, and shelves on either
  side of a divider kept level, by their centers or by their top or bottom
  faces when their thicknesses differ. These tie together openings the
  solver sizes branch by branch, so design them with named values shared
  between units. Evenly spaced groups also give a way to even out a row's
  unlocked openings after drags, which nothing offers yet.
- **Typed moves and a drag step** in the 3D view: type how far to move the
  selected board, and set the drag increment, in the style of FreeCAD's
  own transform arrows. FreeCAD's `SoLinearDragger` has the fields for it
  but no Python wiring, so it needs a spike first.
- **Sizes typed on the drawing:** the unit's overall dimensions and an
  opening's width and height as fields in the 3D view, and dimension
  labels dragged aside as in the Sketcher.
- **Deleting a carcass board**, refused today: whether it should instead
  remove that side of the carcass.
- **Flipping a unit's facing in the editor.** A unit opened for the first
  time may face the wrong way; the editor should offer turning it around to
  the other side.
- **A "generate bug report" command** that absorbs Export Boxes: the boxes
  JSON plus whatever else a report needs, in one file to attach.
- **Parametric joinery** with promote-to-Body, the cut-list spreadsheet,
  the TechDraw elevation, and assembly joints.
