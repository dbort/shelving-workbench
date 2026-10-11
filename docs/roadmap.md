# Roadmap

The open milestones of [`scope-and-design.md`](scope-and-design.md). Each
ends with a concrete way to see it working in FreeCAD, and each becomes one
or more `sh-XXX` tasks. A milestone is removed from this file once its last
task ships.

## M10: v1 polish

**Status:** Tasks sh-022, sh-035, sh-023, sh-024

- [ ] sh-022: refusals, and removing Scan Unit
- [ ] sh-035: Relabel Unit (blocked on sh-022)
- [ ] sh-023: the preferences page
- [ ] sh-024: user documentation and the release (blocked on sh-022,
  sh-035 and sh-023)

A board takes a readable label and its source board's color when it is
written, and an update rewrites neither, so a rename or a recolor survives
every resize. A command restores the label on request.

Every refusal has one shape: a summary, the objects responsible, and a
suggested next step, with the objects selected in the 3D view. The
suggestion is data beside each reason, because a refusal a user cannot act
on reads as a bug. With that in place, Edit Unit says everything about a
hand-built unit that Scan Unit did, so Scan Unit is removed and Edit Unit is
the one way in.

The preferences page holds the starter unit's three dimensions and the snap
and joint-clearance tolerances. Real geometry has coincident edges
disagreeing by up to 0.09 mm, and someone whose model is worse needs a way
forward that is not editing the source.

The user guide leads with scanning geometry you already have, documents
what each refusal means, and states the three limits a user will meet.

*Verify in FreeCAD:* install from the GitHub repository through the Addon
Manager on a clean profile, model a real unit, move it into a second
document with an ordinary placement, confirm an over-constrained input
produces a clear error and no stale geometry, and walk the user guide's
steps exactly as written.

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
- **Flipping a unit's facing in the editor.** A unit opened for the first
  time may face the wrong way; the editor should offer turning it around to
  the other side.
- **A "generate bug report" command** that absorbs Export Boxes: the boxes
  JSON plus whatever else a report needs, in one file to attach.
- **Parametric joinery** with promote-to-Body, the cut-list spreadsheet,
  the TechDraw elevation, and assembly joints.
