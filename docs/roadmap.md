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
and the release have no task yet.

*Verify in FreeCAD:* install from the GitHub repository through the Addon
Manager on a clean profile, model a real unit, move it into a second
document with an ordinary placement, confirm an over-constrained input
produces a clear error and no stale geometry, and walk the user guide's
steps exactly as written.

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

## M16: Starting from a silhouette or a volume

**Status:** Planned

New ways to begin a unit besides Create Unit's starter box: from a
silhouette, such as a sketch of its outline on a wall's plane, or from a
volume it has to fill. A unit started from a silhouette keeps that plane
as its fixed side in depth.

*Verify in FreeCAD:* start a unit from a sketched outline on a wall, change
its depth, and see it stay on the wall.

## M17: Adding a back

**Status:** Planned

A command adds a back to a unit that has none, or replaces one, with its
treatment (overlay, captured, rabbeted) and a back material, and removes
one. The back it makes follows the unit's boards on every edit, as a back
the unit already has does.

*Verify in FreeCAD:* add a back to an existing unit; it appears, tracks
size changes, and scans back as the same treatment.

## M18: Constraints

**Status:** Planned

Relations between the openings and boards of one unit, in the Sketcher's
manner: openings kept the same size, a run of openings kept evenly spaced
whatever the spacing becomes, and board faces in different subtrees kept
coplanar. Alignment across units belongs to named values (Later).

Tasks, in order:

1. The solver, with locks as its only constraint. It ships alone, so the
   change to resize behavior can be tried before any new constraint.
2. Equal and Even spacing, with the commands, the icons, selecting
   several openings, and the handling of constraints across sessions.
3. The constraint list in the task panel.
4. Aligned faces, with picking a board's edges.

**The solver.** A lock becomes one kind of constraint, a dimension in the
Sketcher's terms; Equal, Even spacing and Aligned faces are geometric
ones. Every constraint is linear along one model axis, so each axis is one
small system: every run fills its span, every opening stays at least 5 mm,
and the constraints hold. Within what they allow, boards move as little
as possible from where they are, as the Sketcher's solver moves geometry.
A drag is a target its board approaches until an opening reaches its
minimum. A unit resize goes to the openings beside the outer boards that
move, and pushes into the next opening once one reaches its minimum. That
replaces proportional shares, and the hidden weights behind unlocked
openings retire.

The minimum opening is one named value, the one a drag stops at today
(`MIN_DRAG_GAP_MM`). The solver takes it as an input rather than holding
its own, and every check against it reads that one value, so it can become
a preference later. A preference is global and has no document for an
expression to refer to, so it is a plain number. It has to stay above the
joint clearance plus the snap tolerance, or a minimum opening vanishes on
the next read, so the preference reader checks it against both as it
checks the snap against the clearance.

The solver is a self-contained module in `core/` behind an opaque
interface. A caller passes named positions on one axis with their current
values, the relations among them, lower bounds and drag targets. It gets
back the solved positions and the freedom left, or the constraints in
conflict and, separately, the redundant ones. An edit, a typed size or a
new constraint that over-constrains the layout is refused through the
editor's existing refusal, naming the constraints in conflict, since an
unsolvable layout has no boxes to write. A fully constrained axis is
allowed: its size field turns read-only, like a Sketcher reference
dimension, and changing it is refused with the constraints that fix it
named. That retires the editor's rule of keeping one unlocked opening in
every run.

**The constraints.**

- **Equal**: two or more openings, in any runs along the same axis, keep
  one size. Typing a size into one locks it and the rest follow, as a
  Sketcher dimension on one of several equal lines sizes them all; locking
  a second is redundant and refused.
- **Even spacing**: every opening between two boards of one run keeps one
  size, so a shelf added or removed inside the span joins or leaves the
  group.
- **Aligned faces**: two boards' low faces, high faces or center planes on
  one model axis stay coplanar, in any combination.

Equal and Even spacing carry a basis, as a lock does: the clear opening,
or the spacing through the next board.

**Making and removing them.** Constrain Equal, Constrain Even Spacing and
Constrain Aligned are commands on a toolbar active only during an edit,
as the Sketcher's constraint toolbar is, each acting on the selection.
The add-to-selection click that adds a board adds an opening too. For
Aligned faces, a click just outside a board's long face picks that face's
edge, as the Sketcher constrains edges, and Center is an option of the
command. Each constraint is an icon beside its geometry, drawn the way the
fixed-point cross is, selected by a click and removed with Delete.
Wherever the Sketcher has the same thing, the editor uses the Sketcher's
own: its constraint icons, which load as Qt resources such as
`:/icons/constraints/Constraint_EqualLength.svg` once `SketcherGui` is
imported, and its color preferences, as the editor already reads
`ConstrainedIcoColor`. Even spacing has no Sketcher counterpart, so its
icon is drawn in the same style.
Deleting a board removes its constraints in the same undo step without a
message, and a split drops an Equal on the opening it cuts the same way:
the Sketcher's Split and Trim drop an Equal on the line they cut. The
constraint list, a later task, gives each constraint a row with an active
checkbox and a delete button, and one button removes every deactivated
constraint.

**Across sessions.** Geometry still wins. The container's rule record
becomes the constraint record, version 2: each lock with its basis, and
each constraint with an active flag. A version 1 record reads with its
locks kept and its weights dropped. When Edit Unit opens, a lock takes the
size its boards now have, as today. A relation the boards no longer
satisfy within the joint clearance, because something moved by hand,
comes in deactivated: drawn in the Sketcher's `DeactivatedConstrDimColor`,
enforced only once the user reactivates it, which moves the boards as its
own undo step, and removable with Delete without reactivating it, as the
Sketcher allows. A constraint naming a board that is gone, deleted or
replaced by a copy with a new `Name`, is dropped. An Even spacing group is
dropped only when an end board goes, and an Equal whose opening a
hand-added shelf split is dropped too. One Notification Area message at
open says what was deactivated or dropped. A copied unit loses its
constraints as it loses its locks today (bug-021).

*Verify in FreeCAD:* in a two-column bookcase, space three shelves of the
left column evenly and align the right column's middle shelf top to top
with one of them. Grow the unit and drag a shelf, and see both relations
hold. Close, move one shelf by hand, open Edit Unit again, and see that
relation greyed and removable with nothing moved.

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
