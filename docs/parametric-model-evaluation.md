# Scan, edit, apply: an evaluation

An evaluation of the plain-planks approach. It carries the evidence and the
reasoning behind [`scope-and-design.md`](scope-and-design.md), which is the
design of record; nothing here is a decision of record on its own. The
approach was adopted, so the sections below that weigh whether to adopt it
and what would follow are the record of that decision rather than an open
question; `roadmap.md` carries what is left to do. The
approach has no name and needs none: the operations are **scan**, **edit**,
and **apply**, and the modules are named for what they do. A label for the
philosophy would only appear in prose, and would go stale as the approach
moved.

Two earlier alternatives, promoting the solver's driving values to
properties and generating every number as a FreeCAD expression, were
evaluated and dropped in favour of this one; they are in this file's git
history. The one idea from them worth keeping is that a unit's rules could
later be persisted as expressions on the boxes rather than as properties;
nothing below depends on it.

## The approach

The plain solids are the source of truth. The workbench keeps no model
between edits, in the manner of the Woodworking workbench
(`dprojects/Woodworking`). Three commands replace the current driver
object:

- **Scan** takes a container the user chooses, classifies the
  axis-aligned boxes inside it into planks, reads the lap order at each
  joint from which member runs through, infers the bays from the enclosed
  voids, and builds a split-tree. Anything outside a strict envelope is
  refused with a diagnosis that names the offending object.
- **Edit** is the 2.5D editor operating on the scanned tree.
- **Apply** writes the tree back as plain boxes into the same container:
  existing planks updated by identity, new ones created, removed ones
  deleted.

The design of record computes every number in Python and writes it onto
`Part::FeaturePython` planks that only this workbench understands. Under
plain-planks the same core does the same arithmetic, but its input comes
from geometry and its output is geometry.

## What Woodworking establishes

Read from a local clone of the repository. These are facts about the
substrate the approach builds on, and constraints on the scan
envelope.

- Panels are `Part::Box`, `PartDesign::Pad`, `Part::Cut`, `App::Link`,
  and clones; sizes come from `Length` / `Width` / `Height` or from
  vertices and the bounding box.
- Axis convention matches this project's: `Length` along X (width),
  `Width` along Y (depth), `Height` along Z, front face at low Y.
  Orientation is a six-way classification of which dimension is thinnest
  (`getDirection`).
- Its furniture generator (`magicStart`) emits `Part::Box` objects named
  `Floor`, `Left`, `Right`, `Back`, `Top`, `Front`, `Shelf`, and puts them
  in an `App::LinkGroup`. Its container helpers also handle `App::Part`,
  `PartDesign::Body`, and `Part::Cut`.
- A generated shelf is inset 1 mm from each side (`gShelfOffsetSides`)
  and is shallower than the sides: it sits behind the front panel and in
  front of the back panel. Scan must tolerate a small clearance at a
  joint and planks of differing depth, or it refuses every Woodworking
  cabinet.
- Back and front panels are thin along Y. They project onto the whole
  elevation and are not part of the bay partition.
- Move and resize tools write plain values, never expressions.
  `magicGlue` is a `SubShapeBinder` helper for sketches, not a
  panel-to-panel parametric link. Woodworking never infers structure from
  an arrangement.
- The cut list (`getDimensions`) reads `Length` / `Width` / `Height` from
  boxes and groups by container label, so plain boxes in a container are
  all it needs.

## Gains

- **Documents outlive the workbench.** A `Part::Box` is native; a
  `Part::FeaturePython` whose proxy module is missing loads as a frozen
  shape with a warning. Every other Part, Draft, and Woodworking tool
  works on the output unchanged.
- **Adoption of existing geometry.** The editor works on shelving the user
  already modelled, or imported, as long as it fits the envelope.
- **Lap order is read from geometry** rather than reserved in the schema.
- **Direct plank edits round-trip.** This reverses the "3D edits" decision
  of record: resizing a plank with Woodworking's `magicResizer` and then
  opening the editor is a supported path, because scan starts from
  whatever is there.
- **Scanning is pure geometry.** It lives in `shelving_core` taking
  `(size, corner)` boxes and returning a tree or a structured refusal,
  with the round-trip property that scanning `expand`'s output
  reproduces the tree as the oracle test.
- **`StudWall` scans the same way**: plates and a row of studs are a
  one-level tree.

## Costs

- **The tree is not unique for every arrangement.** Four segments meeting
  at a point are ambiguous, and a pinwheel (each divider stopping against
  the next) has no tree at all. Lap order resolves the first: the member
  that runs through belongs to the outer split. The second is refused.
- **Rules are lost from geometry.** Geometry cannot distinguish a 300 mm
  `fixed` opening from a `fill` that happened to solve to 300 mm.
  Recovery is by stored metadata when present and by heuristic otherwise
  (see Decisions).
- **Material is not inferable** beyond thickness, and thickness alone does
  not identify a catalog entry. Scan reads the stored property when
  present and otherwise leaves the material unset.
- **Refusal is the user experience.** Every unsupported arrangement (a
  rotated plank, a gap wider than the clearance tolerance, an overlap, a
  shelf that spans two bays, a non-box) must produce a diagnosis that
  points at geometry. A silent no-op or a generic error makes the tool
  feel broken.
- **Consistency is not maintained between edits.** A user can leave the
  boxes in any state; the model is only known to be consistent right
  after apply. Woodworking users accept this, but it is a different
  promise from "the 3D is always a projection of the model".
- **Identity across edits** is stored on the boxes as dynamic properties.
  Reconstructing it by position on every scan would lose labels and
  per-plank overrides.

## Decisions

Made in the planning interview on 2026-09-04. The spike results below
confirm or amend each of them.

| Question | Decision |
|---|---|
| Unit scope | One container the user chooses (`App::Part`, `App::LinkGroup`, or a plain group). Every box inside it is a plank of one unit; apply writes into the same container; the container gives the unit its `Placement` |
| Plank types | `Part::Box` only, identity rotation, for the first envelope. `Pad` and rotated placements are later |
| Elevation plane | Detected, not assumed: depth is the shallowest bounding-box axis, vertical is Z unless Z is the depth. Stored on the unit, overridable |
| Facing | Which end of the depth axis is the front. Stored on the unit and authoritative. Two hints give a first guess, a back or front panel and an inset front, and both fire rarely, so unknown is the normal outcome |
| Outline | Rectilinear, one plane. The bounding rectangle's tree carries `Void` regions that hold no planks and are not bays; the outline is whatever they leave |
| Shell | Not a rule and not a field. A split is an ordered run of planks and sub-regions, so the shell is its outermost planks. `Carcass` does not survive |
| Split axis | A split names an axis (X, Y, or Z), not an orientation within an assumed elevation plane. Near-term scanning and editing stay single-plane, but the model never needs changing to hold a second one |
| Depth | A region's extent along the depth axis, not a field on the unit. A plank fills its region's cross-section with an inset per face, which is the same parameter as a joint clearance |
| Measurement basis | A fixed size is a clear opening by default, or inclusive of the adjacent plank, which is a shelf spacing. Stored with the rule, since the two place the panels identically and geometry cannot tell them apart. Resolved to a clear size before distribution, in the same pass that resolves a named value |
| Panel shape | Rectangular boxes only. An L-shaped, mitred, notched, or scribed panel has no representation and is a future path, not a near-term goal |
| Non-tree layouts | A pinwheel or any partition that is not a tree is refused, naming the planks that form the cycle |
| Clearance at a joint | A gap up to a tolerance (default 3 mm) is a joint; the gap is stored per plank end and apply reproduces it. Larger gaps refuse |
| Per-plank depth | Scan records each plank's depth and Y offset as per-node overrides; apply reproduces them; unit depth is the default for new planks |
| Back and front panels | Y-thin planks are set aside from the bay partition and reported; back-panel semantics arrive with M11 |
| Rule recovery | Stored rule metadata on a box is authoritative. Without it, sibling openings equal within tolerance become `fill` and the rest become `fixed` |
| Plank identity | The FreeCAD `Name`. Never stored by us, so it cannot be copied and a duplicate is a distinct entity by construction |
| Provenance | Two stored fields, the `Name` and the document `Uid` at the time the plank was tagged. They classify what a mismatch means: a changed `Name` is a copy, a changed `Uid` is a relocation |
| Stored metadata | Only what geometry cannot carry: **material** and the **rule** of the region beside the plank. Role and clearance are derived, so a copy carries fewer wrong fields |
| Region rules | A record on the container, keyed by plank `Name`. Not a source of truth for geometry; a missing or stale entry falls back to the equal-siblings heuristic |
| Reflow | Inert by default: scan, edit, apply are commands. An optional per-unit driver for automatic reflow comes later, and a live unit is not hand-editable |
| Repeat rules | Deferred to `StudWall` (M12), where a computed member count is the point. Its children are positional, so it introduces a second identity scheme |
| Draft arrays | Skipped loudly for now. Expanding one into its element placements is easy but adds a type to the envelope |
| Apply | Plain values. Expressions among planks are a later option, not part of the approach |

### The outline model

"Guillotine" describes a partition of a rectangle made by repeated
edge-to-edge straight cuts, each running the full span of the region it
cuts. The split-tree is exactly that: every `Split` divides its whole bay
across. A pinwheel cannot be made by full-span cuts, so it has no tree.

A stair-step outline is guillotine: cut vertically at each step edge,
then cut the top off each column. So the tree stays the model, extended
by an *outside* leaf. The bounding rectangle is the carcass; a leaf
marked outside has no planks and no opening. A plank that borders an
outside leaf, or the bounding rectangle's edge, is a shell plank; a plank
between two open bays is a divider. Lap order at every joint is the tree
order: the plank that runs the full span of a region is the one cut
first and runs through; planks in the strips it creates are captured
against it. That makes lap order unambiguous and free.

Scan therefore works on a cell grid: every plank edge coordinate is
a grid line, a flood fill from the bounding rectangle's edge through
uncovered cells marks the outside, and the recursion at each region looks
for planks whose line across the region meets only the plank itself,
outside cells, or a clearance gap. In a region with no planks, all-inside
is an open bay, all-outside is an outside leaf, and mixed is a refusal
(the outline is not guillotine). A unit with no open bay at all is
refused too: that is what a leak in the shell looks like, since the flood
fill reaches the interior. Feet under a floor, a top that steps, and a
Woodworking cabinet with inset shelves all fall out of the same rule.

The closed rectangular carcass is the special case where the root's two
horizontal cuts are the bottom and the top with nothing beyond them, and
the strip between them has the two sides as its vertical cuts. The
current `Carcass` keeps its shell implicit, so the spike converts that
case back to today's model to prove the round trip; the general case
needs the outside leaf in the schema and a shell rule in `expand` that
follows the inside/outside boundary.

## Spike plan

Throwaway code, not a task and not shipped: a standalone package outside
`shelving_core`, checked by its own ad hoc `pytest` and `mypy --strict`
invocations rather than by `pixi run tests`. sh-016 ported what it proved
into the shipped scanner and deleted it.

### Core spike: scan from boxes, no FreeCAD

`scan.py` takes a list of axis-aligned boxes and returns a cut tree
or a `ScanError` naming the objects. `test_scan.py` covers:

1. **Round trip.** For sample trees (a single leaf, three `fill` shelves,
   a vertical split with a nested horizontal one, mixed thicknesses),
   `expand` to boxes, scan, convert back to a `Carcass`, `expand`
   again, and assert the plank set matches to 1e-6 mm.
2. **Woodworking cabinet.** The `magicStart` F0 shape (floor, sides, top,
   back, front, one shelf inset 1 mm each side and shallower than the
   sides) scans as one bay split by one shelf, with the back and
   front set aside and the clearances recorded.
3. **Stair-step.** Three columns of decreasing height with a continuous
   floor and left side, step tops, and risers scan into a tree with
   outside leaves, and the lap order matches the geometry.
4. **Refusals.** A pinwheel, an overlap, a gap wider than the clearance, a
   square-section plank, and a shell with a leak each refuse and name the
   objects.
5. **Rule recovery.** Equal siblings become `fill`; a differing sibling
   stays `fixed`; resizing the scanned carcass redistributes only the
   `fill` openings.

### FreeCAD spike: plain boxes in a document

A `freecadcmd` script, written after the core spike passes, covering:

6. **Dynamic properties on plain boxes.** Add node id, role, rule, and
   material string properties to a `Part::Box`, save, reload headless
   without the workbench on `sys.path`, and assert the properties and the
   shape survive with no warnings.
7. **Export from a container.** Walk an `App::Part` and an
   `App::LinkGroup`, read each box's global placement, refuse a rotated
   box, and produce the input the core scanner takes.
8. **Apply by identity.** Scan a unit, split a bay in the tree,
   apply, and assert the untouched boxes are the same document objects,
   the new plank is new, and a removed plank is deleted.
9. **Scale.** Scan a forty-plank unit and time it.

### GUI checks

Outstanding; they need a human at FreeCAD 1.0 with Woodworking installed.

10. Done. A stair-step unit from a live project was exported and now
    scans; see the results below. It found the plane assumption, the
    snap tolerance, and the thickness corruption.
11. Outstanding. Run Woodworking's `getDimensions` on a unit the spike's
    apply wrote, and check the cut list is correct.
12. Done. A saved `magicStart` document was read directly. It scans,
    and it found that the tool ships two opposite lap orders and that the
    facing rule mishandled a proud overlay back.

## Spike results

### Core: scan from boxes

Run on 2026-09-04 against the spike's scanner; fifteen
tests pass, `ruff` and `mypy --strict` are clean, and `pixi run tests`
stays green. **Scanning is tractable.** The scanner is about 500
lines and every planned case works.

What the spike settled:

1. **Round trip holds.** For a single leaf, four `fill` shelves, a nested
   vertical-then-horizontal tree with mixed materials, and unequal fixed
   shelves, scanning `expand`'s boxes and expanding the recovered
   carcass reproduces every plank to 1e-6 mm and the same tree shape. It
   also holds at 3 x 4, 6 x 10, and 8 x 14 grids.
2. **The Woodworking cabinet scans.** The `magicStart` F0 shape
   yields floor and top as the outer cuts, the two sides inside them, and
   the shelf with its 1 mm clearance recorded at each end. Back and front
   are set aside as Y-thin panels.
3. **The stair-step scans.** Three columns of decreasing height give
   a floor cut, then four uprights, then a per-column top with an
   `Outside` region above the two short columns. Lap order falls out of
   the tree order with no extra rule.
4. **Refusals name the objects.** A pinwheel refuses with all four planks
   named, an overlap names both planks, a shelf floating beyond the
   clearance names itself, a square-section post names itself, and a
   shell with a gap refuses as "no enclosed bay".
5. **Rule recovery works.** Equal siblings become `fill` and redistribute
   correctly when the recovered carcass is made taller; unequal siblings
   stay `fixed`.

Three findings that change the plan:

- **A full-height divider is a sibling of the sides.** The solver insets
  the carcass by one thickness, so a root-level vertical divider spans
  exactly the same region as the left and right sides and appears as a
  third full-span cut beside them. The converter has to read the outer
  two cuts as the shell and the rest as the root split's dividers. This
  is an artefact of `Carcass` keeping its shell implicit; the general
  model with an explicit shell and outside leaves does not have it.
- **A shelf that runs through the sides has no home in today's `Carcass`.**
  Scan handles it (it is an outer cut with three or more members), but
  `expand` always makes the top and bottom continuous, so the converter
  refuses it. This is the per-joint lap override the schema reserves, and
  the general model needs it.
- **Unit depth comes from the elevation members, not the bounding box.**
  A Woodworking cabinet's 400 mm depth is an 18 mm front panel plus a
  382 mm carcass. Scan reports the members' depth and the front
  offset separately, and both are needed to write the unit back.

Performance is a non-issue: scanning 115 planks takes 1.7 ms, and the
cost grows roughly with plank count times grid cells.

| Planks | Scan | Convert |
|---|---|---|
| 15 | 0.2 ms | 0.08 ms |
| 35 | 0.3 ms | 0.15 ms |
| 63 | 0.7 ms | 0.26 ms |
| 115 | 1.7 ms | 0.47 ms |

### FreeCAD: plain boxes in a document

Run with the spike's `freecadcmd` script, which printed
`plain-planks freecad spike OK` on success. All four goals pass.

- **Dynamic properties survive a reload (goal 6).** Four
  `App::PropertyString` properties added to a plain `Part::Box` come back
  intact after a save, close, and reopen, with the shape valid. The saved
  `Document.xml` contains no `Proxy`, `FeaturePython`, or `PythonObject`
  entry, so the file needs nothing of ours installed to load. **This is
  the linchpin of the approach and it holds.**
- **The container walk feeds the scanner (goal 7).** Both `App::Part`
  and `App::LinkGroup` export cleanly, and moving the container leaves
  the scanned tree unchanged while shifting the exported corners,
  because the walk composes container placements and the tree is measured
  against its own bounding rectangle. `getGlobalPlacement` is not usable
  here: a `LinkGroup` is not a geo-feature group, so the chain is composed
  by hand.
- **Apply matches by identity (goal 8).** Adding a shelf to a scanned
  tree updates the six existing boxes in place, creates exactly one, and
  deletes none; removing it deletes exactly that one. Every shell plank
  keeps its original document object. The result scans again, so the
  edit cycle closes.
- **Cost is negligible (goal 9).** A 45-plank unit exports in 0.3 ms and
  scans in 0.6 ms; apply plus a full document recompute is 9 ms.
  FreeCAD's own recompute dominates, and it is still far below an
  interactive threshold.

### Real geometry: a stair-step unit from a live project

The user exported a stair-step component built in the FreeCAD GUI with
Woodworking tools and fed it to the scanner. It is kept as
`shelving_core/tests/fixtures/real_stair_step.boxes.json` and asserted by
`test_real_stair_step_whole_tree`.

**It scans, and the tree matches the geometry.** A top running the
full width, three uprights under it (a short left side, a middle divider,
and a right side that runs down past everything as a leg), a shelf in the
left step, two shelves plus a divider in the right step, and the open
space below each step read as `Outside`. Nothing about the layout needed
a new rule: it is guillotine, and lap order fell out of the tree order.

Getting there took two fixes, both of which the synthetic tests had no way
to provoke:

- **The elevation plane cannot be assumed.** The unit is modelled on the
  YZ plane with X as depth, because that is how it sits in the room. The
  spike had X-across and Y-deep hardcoded, so it read the unit end-on and
  refused with a bogus overlap. Scanning now detects the plane, taking
  the depth axis to be the shallowest bounding-box extent, with an
  explicit override. The `Plank` record is in elevation coordinates
  (across, up, through) rather than XYZ, and a plank is classified as an
  upright, a shelf, or a panel by which of those it is thin along. **Any
  design that assumes a fixed plane is wrong**, and the same applies to
  the editor and to apply.
- **The snap tolerance was an order of magnitude too tight.** Edges that
  the model means to be coincident differ by up to 0.09 mm, and four such
  edges spread wider than the 0.05 mm tolerance the spike started with.
  Worse, snapping greedily against the previous kept value let a run of
  small steps chain. The tolerance is now 0.5 mm and clustering measures
  from each cluster's own first member, so a chain cannot form.

Two further findings came out of the same run:

- **Snapping must not touch a plank's measured size.** Moving an edge to
  a cluster midpoint changed each plank's thickness by up to half the
  tolerance, which turned two real stock thicknesses into seven. Since
  thickness is what identifies a plank's material, the grid now owns the
  topology alone and every plank keeps its measured extents.
- **Per-plank depth is the normal case, not an edge case.** This unit
  mixes 215.9 mm and 292.1 mm planks (8.5 and 11.5 inch), back-aligned
  rather than front-aligned. The unit has no back or front panel at all,
  so the "set aside the Y-thin panels" rule did no work here.

#### Facing is not in the geometry

Reporting that unit back to the user described its left side as the right
one. The correction exposed a gap that no test would have caught, because
the scanner and the tests were both consistently wrong.

The depth *axis* is detectable, but its *sign* is not: nothing in a set of
boxes says which of the two faces a person stands at. The same elevation
read from the other side is mirrored, so every left and right swaps. This
changes no size, no topology, and no lap order, which is why it is easy to
miss and why it survives every structural test. It changes only what a
plank is called and which way the editor draws.

Two hints exist, and **both fire rarely**:

- **A plank thin through the depth.** One lying proud of the other members
  is a door or a face, so that end is the front; one lying within them is
  a back, so the front is the far end. This needs the unit to have a back
  or a front, which open shelving does not.
- **An inset front.** The rear of a unit is almost always flush, since it
  goes against a wall, while the front may be inset for looks. So the end
  the members sit flush with is the back. This needs the plank depths to
  *differ*: a unit whose planks are all one depth is symmetric through the
  depth axis and says nothing.

Across the spike's ten fixtures, a panel settled two, the inset settled
one, and seven were undetermined. Every synthetic unit is undetermined,
because uniform depth is the ordinary case. **Unknown is the normal
outcome, and the hints are a first guess, not a mechanism.**

The inset hint was nearly implemented backwards. The first reading of the
real unit assumed shelves are flush at the front and shallower at the
back; the convention is the reverse, and the unit's shallow planks are
flush at the rear and inset three inches at the front. Read the wrong way
round it would have produced a confident mirror image.

Consequences for the design:

- **Facing is a stored property of the unit, not a derived value.** It
  belongs on the container beside the plane, set once and remembered. A
  stored value is authoritative and is never second-guessed by a hint.
- **Unknown is a first-class state.** The spike carries `front_at_min` as
  an explicit `None`, and the derived left-right sign returns `None` with
  it, so any code needing a left or a right must handle not knowing.
- **A guess must be labelled as one.** Scanning records which evidence
  settled the facing, and the report prints the reasoning when it guessed.
- **The editor needs a "view from the other side" control**, and it is the
  natural place to set the property the first time. Since unknown is the
  normal outcome, the editor has to open on an arbitrary but stable
  orientation and make flipping it one click.
- **Generated labels must not say left or right until facing is known.**
  Today's `generated_label` would produce a confidently mirrored name.

The unit also confirms two decisions already recorded: it is stepped at
the bottom rather than the top, which the outside leaf handles without
change, and it carries two stock thicknesses, which the closed-rectangle
converter would reject but the general model must not.

### Real geometry: two units side by side, loosely grouped

A second export, of two adjacent units from the same project whose side
panels meet, kept as
`shelving_core/tests/fixtures/real_two_units.boxes.json`. It
was taken from a selection rather than a tidy container, which is what
makes it useful.

Four findings, in order of how much they change the plan.

**Two abutting units are refused, and the reason is structural.** Each
unit scans on its own. Together they refuse with "no plank runs the
full span of the region". The scanner only cuts a region where a single
plank spans it, and at the junction there is no such plank: the two units'
top boards are separate pieces that together span the width and neither of
which spans alone, and the seam between the units is two side panels face
to face rather than one shared panel.

The fix is a better rule, not a special case. A guillotine cut is any
coordinate that no plank *crosses*, and cutting at a plank's two faces is
the special case where the resulting slab holds one plank. Under that rule
the junction is a clean cut, nothing crosses it, and the top slab
becomes a region holding two planks side by side, which the general model
already expresses. It also removes an asymmetry in the current code, where
a plank ends a region but cannot begin one. The cost is ambiguity: many
coordinates are clean, so scanning would need a canonical choice of
axis and cut set.

**A dropped panel produces a wrong tree, not a refusal.** This export
contains the notched breaker-panel part, and the walk dropped it, listing
only its sketch and pad as skipped. The unit still scanned. Comparing the
tree against the same unit with the panel adopted by its bounding box,
three regions that are enclosed bays were reported as `outside`, and the
unit's left end was read as open. Nothing complained. This is the
silent-drop failure predicted earlier, now demonstrated: the output is
plausible, self-consistent, and wrong.

It also settles the question it was meant to test. Adopting the panel
opaquely by its bounding box makes the tree correct, so the cheapest
option for a plank-like part does work on real geometry.

**The seam cannot be classified by shape.** Two side panels face to face
is geometrically identical to a framed wall's double top plate, which is
one unit, not two. So whether an assembly is one unit or several is not
recoverable from geometry, and the container the user scans has to be
the answer. Surfacing back-to-back parallel planks as a question is
reasonable; deciding it automatically is not.

**The walk double-counted.** Eleven planks were exported twice, byte for
byte, because a selection can reach the same object by more than one path.
Export has to deduplicate by document object.

### Real geometry: a Woodworking cabinet from the tool itself

A cabinet generated by `magicStart` and saved, read straight from the
document rather than reconstructed from Woodworking's source, kept as
`shelving_core/tests/fixtures/real_magicstart_f1.boxes.json`. Six
`Part::Box` objects in an `App::LinkGroup`, exported and scanned with no
intervention.

**It scans correctly**, including a 100 mm plinth gap below the floor
that reads as `Outside` rather than a bay, and the 1 mm shelf clearance at
each side.

**Its lap order is the opposite of the reconstructed fixture.** The
`createF1` variant runs the sides the full height and captures the floor
and top between them; `createF0`, which the earlier synthetic fixture
copies, runs the floor and top full width and captures the sides. Both
come out of the same tool. There is no house lap order to assume, which is
why reading it from geometry, and letting the tree's nesting carry it, is
the right call.

**Facing was inferred backwards, and the fix matters.** The cabinet's 3 mm
back sits *proud* behind the carcass rather than set within it, and the
rule read a proud panel as a door. It put the front at the wrong end and
mirrored the elevation, the same class of error a human caught earlier by
eye. Corrected: a proud panel of stock thickness is a door, and a proud
panel much thinner than the stock is an overlay back, and the two point
opposite ways. Both real and synthetic cabinets now infer correctly, and a
test flips the back's thickness to confirm the two cases diverge.

That is the second time the facing heuristic has been wrong on the first
real example it met. The rule stands: facing is stored, a heuristic only
seeds it, and a guess is labelled as one.

### The carcass is a specialisation, not a primitive

Scanning produces a tree of regions and full-span cuts. `Carcass`
produces four shell planks by rule: a top and a bottom running the full
width, two sides captured between them. Those are not the same shape, and
the difference is measurable. Of four fixtures, scanning handles all
four and the conversion to `Carcass` refuses two:

| unit | scans | converts to `Carcass` |
|---|---|---|
| closed bookcase | yes | yes |
| `magicStart` F0 cabinet | yes | yes |
| synthetic stair-step | yes | no |
| real stair-step unit | yes | no |

Both refusals are the same message: not a closed rectangle. The shell rule
is the constraint, not the scanning.

The spike's general model prototypes the tree without it. A
split is an ordered list of *items* along its axis, each either a `Plank`
or a `Sub` region carrying a size rule. There is no shell field and no
shell rule: the shell is the outermost planks of the outermost splits.
sh-013 shipped this shape as `shelving_core.layout`'s region model.

```
Unit    = size, depth, default material, face, root Region
Region  = Bay | Void | Divide
Divide  = orientation + ordered [Item]
Item    = Plank(material?, front inset, depth?) | Sub(Region, rule)
```

Ten tests establish what it buys:

- **It reproduces the carcass exactly.** A `closed_box` helper builds the
  carcass shape from ordinary items, and its expansion matches
  `shelving_core.expand` plank for plank for one, two, and four openings,
  and for a nested split with a divider in a second material. So nothing
  is lost.
- **A stepped outline is ordinary.** Three columns of falling height are
  three sub-regions each ending in a `Void` that takes the leftover
  height. The tops come out at 600, 900, and 1200 mm with no shell rule
  involved, and a `Void` emits no plank and is not a bay.
- **Two planks can sit face to face.** A framed wall's double top plate is
  two adjacent `Plank` items. M12 needs this and the carcass model cannot
  say it.
- **A shelf can run through the sides.** Lap order is the order the splits
  nest, so a through-shelf is a plank higher up the tree. The carcass
  reserves this as a per-joint override that expansion never honours, and
  can only produce two full-width planks.
- **A per-plank inset keeps the rear flush**, which is the real unit's
  shape and the convention it follows.
- **The solver did not change.** `shelving_core.solver.distribute` is
  reused unaltered: a plank contributes `Fixed(thickness)` and a region
  contributes its own rule, so the arithmetic never needed to know which
  was which. A unit too short for its own top and bottom now fails as an
  ordinary overflow rather than a special case.

What it costs:

- **Building a plain bookcase is more verbose**, which the `closed_box`
  constructor answers.
- **Roles stop being a closed enum.** A stepped unit has three tops and
  none of them is *the* top, so `PlankRole` cannot name them.
  A role becomes a free-form string or a derived position, and generated
  labels have to follow.
- **More trees describe the same geometry**, so scanning has to pick a
  canonical one and apply has to match by stored id rather than by shape.

The conclusion is that `Carcass` should not survive the reset. Keeping it
would mean carrying a second model for the shapes it can express, and
every real unit seen so far that is not a plain box falls outside it.

### The bugs real geometry found, and the rule that replaced one

Four defects surfaced only against real documents, and the last one was
not a defect so much as a rule that was too narrow.

- **The walk descended into a `PartDesign::Body`.** A body exposes its
  feature history through `Group`, so its sketch and its pad were treated
  as planks and its solid was never looked at. It now descends only into
  `App::Part`, `App::LinkGroup`, and plain groups. A body or a boolean is
  one part, and its children are its construction, not its contents.
- **The walk double-counted.** A selection can reach one object by more
  than one path, which put eleven planks into a real export twice over. It
  now tracks what it has yielded, and the parser collapses identical
  duplicates while refusing two different boxes claiming one `Name`.
- **Skips were silent.** They now carry a reason and reach the report,
  which says the tree cannot be trusted and exits non-zero.
- **The plank-span rule refused two abutting units.** Replaced by the
  general guillotine rule: a cut is any line no plank *crosses*, rather
  than a line some one plank spans. Cutting at a plank's own faces is then
  the case where the slab holds one plank.

The new rule needed two conditions to stay useful. A cut line must be a
face of a plank **in that region**, or a neighbouring unit's shelf heights
slice this one's empty space into a dozen meaningless slabs. And lines
closer together than the clearance are one joint rather than a
compartment, with the face of a plank the cut separates winning, or a
shelf held a millimetre off each side turns its two joint gaps into two
one millimetre bays.

`CutSplit` became `Divide` with a single ordered item list, matching the
general model, so a shell plank at a region edge is the first item rather
than a `None` strip.

All three real fixtures now scan. The two abutting units come out with
**both** seams visible: the units' two top boards side by side, and their
two side panels face to face, neither pair having a member that spans
alone.

One behaviour changed rather than improved. A plank floating clear of both
neighbours is no longer refused, because `[gap, plank, gap]` is a legal
partition and the general rule cannot say otherwise. Whether a plank
reaches its neighbours is a question about the thing being buildable, not
about the layout being a tree. Nothing asks it yet, and something should.

### Verdict

Every spike goal passes, real project geometry scans correctly, and
nothing turned up that blocks the approach. The open questions are not
about feasibility:

1. **The name.** "Plain-planks" is a placeholder and should be settled
   before it reaches a module or type name.
2. **The general model**, prototyped above and no longer in doubt:
   `Carcass` goes, the shell becomes ordinary planks in the tree, and
   `Void` regions carry the outline. Writing that into `shelving_core`,
   with scanning producing it directly, is the bulk of the real work.
3. **Where the plane and the facing live.** Scanning detects the plane
   and sometimes the facing, but a `Carcass` has no field for either, and
   the editor, apply, and every generated label need both. They belong in
   the model next to the `Void` region, with facing stored rather than
   inferred.
4. **How much of the arrangement to model now.** Splits should name an
   axis rather than an orientation within an assumed plane, so a second
   elevation plane never forces a model change; scanning and the editor
   stay single-plane. See Future paths.

## Separate workbench, or features inside Woodworking?

The output is plain solids of the kind Woodworking already operates on,
which raises the question of contributing the work upstream. The answer
is a separate workbench whose output follows Woodworking's conventions.

- **Governance.** Woodworking describes itself as "my environment for
  woodworking" and is 99% single-author (504 of 509 commits at the time
  of writing), with six external pull requests in its history, all
  small. Its pull-request terms require changes to be "consistent with
  the current vision for the add-on and not introduce drastic changes to
  interface or user experience", and state that contributed code "will be
  improved or removed by others". The repository has no CI, no type
  checking, and a single sample directory under `Tests`. A modal
  split-tree editor is a drastic interface change, and this repository's
  checks would not survive there.
- **Different kind of tool.** Woodworking is a toolbox of stateless
  operations on the current selection. Plain-planks keeps a model,
  transient or not: a tree with driving and driven rules, over-constraint
  semantics, and identity and rule metadata stored on the boxes. The
  editor is the product. The nearest overlap, `magicStart`, is a one-shot
  wizard that emits a cabinet from dimensions; the delta that justifies
  this project is the part that does not fit that vision. The core's second
  consumer, `StudWall`, is outside woodworking.
- **Interop needs no merge.** Emitted boxes follow Woodworking's
  conventions, so its cut list, dowel, edge-banding, and export tools work
  on a unit unchanged, and scan works on panels made with its tools.

## If adopted: reset in place, not a fresh repository

Adopting plain-planks invalidates the object layer and most of the design
of record, and a repository that describes a superseded design as current
steers implementers (human or agent) toward its shapes. The remedy is a
reset in this repository, not a new one.

What survives unchanged: the core (`layout`, `solver`, `expand`,
`materials`, and their tests) is the apply path and the oracle for
scan; the check harness, pixi environment, CI, action-pin verifier,
workflow lint, vendoring script, pipeline and skills, `package.xml`,
workbench registration, and the `freecadcmd` notes are all still true. A
fresh repository re-derives these and gains nothing, and "reference the
old repository" copies the old shapes without the tests that constrain
them.

What misleads: `freecad/shelving/objects/` (the `Plank` proxy, the driver
and its reconcile, the feature-type protocols), the object smoke test, and
above all the prose in `architecture.md` and `roadmap.md`, which
implementers read first and treat as the contract.

The reset, done as one task after the core spike passes:

1. Rewrite `architecture.md` as the plain-planks design of record, as a
   new document rather than an edit, with one line stating that anything
   in history before the reset commit is superseded.
2. Delete the dead object layer and its smoke test in the same change.
   Nothing is kept "for reference" or marked deprecated; git history is
   the reference.
3. Re-milestone `roadmap.md`. Completed task files stay in
   `tasks/completed/` untouched.
4. Update the agent memory index in the same session.

A fresh repository is the right call only if the tree itself goes away
(so the core has no consumer) or the project's identity changes (a name
covering framing as well as shelving). Plain-planks keeps the tree as the
editor's model, and a rename can happen in place, so neither applies.

## Copies, identity, and parameters

Two questions raised after the spike, both of which turn on the same
thing: every stored field is a field a copy can get wrong.

### A copied plank

Copying a plank to make another shelf is a normal gesture, and FreeCAD
copies every property with it. A stored node id would therefore be
duplicated, and nothing would say which box was the original. The worst
case, a copy moved into a different unit, would leave that unit holding a
plank claiming to belong to another.

Measured against FreeCAD 1.0:

| | result |
|---|---|
| `doc.Uid` | exists, a UUID |
| copy within a document | `Name` changes |
| copy into a fresh document | `Name` preserved, `Uid` differs |
| copy where the name collides | `Name` changes |
| Save As | `Uid` unchanged, so two files share one |

So identity should not be stored at all. The `Name` is unique per
document, persisted, stable across saves and across moves between
containers, and a copy always gets a fresh one, which makes duplicate
identity impossible rather than merely detectable. Two provenance fields,
the `Name` and document `Uid` at tagging time, then classify a mismatch: a
changed `Name` is a copy, and a preserved `Name` in a different document is
a relocation. The Save As caveat is benign, since both files are
self-consistent and merging them forces a rename that the first check
catches.

Three signatures then mean the same thing, and the resolution is what the
user wanted anyway: **drop the stale record and adopt the box by
geometry**, so a copied shelf becomes a new shelf. They are a plank whose
recorded slot is taken, one whose recorded parent is not in this
container, and one whose geometry does not match the slot it claims.

Cutting the stored fields to material and rule matters for the same
reason. Role and clearance are derivable, so storing them only creates
fields a copy can carry wrongly.

### Parameters

The shared driving value proposed for cross-unit alignment **is** a
parameter, and a `VarSet` is its natural home. If a rule can name a value
instead of holding a literal, one mechanism covers three things:

- **cross-unit alignment**, where several regions name one level or pitch;
- **external driving**, since a `VarSet` property carries an expression, so
  `shelf_pitch = Room.Height / 5` needs no code from us;
- **exposure outward**, since other objects read the `VarSet`, or read the
  plank boxes, whose `Length`, `Width` and `Height` are ordinary
  properties.

That answers the question this whole evaluation opened with, and far more
cheaply than the expression generator that was evaluated and dropped,
because only the handful of named driving values are expressions. Every
derived dimension stays in the solver where it is testable. The generator's
fatal cost was owning roughly a hundred and fifty user-editable
expressions per unit; this owns perhaps five.

The tension is when reflow happens. Scan, edit and apply are commands,
while parameters imply the model follows on its own. Inert by default with
an opt-in per-unit driver resolves it, at the price of making live and
hand-editable mutually exclusive, which should be an explicit choice.

### What follows for the near term

Three seams, all small, and all of which pay for themselves on a single
unit before any of the above is built.

- **One function resolves a rule to a size.** A rule that is sometimes a
  reference is both the alignment mechanism and the parameter mechanism,
  so this is the single place either lands. Do not reserve an unimplemented
  reference variant in the schema; the reserved lap-order field is already
  a cautionary example here.
- **One function applies a tree to a container.** Coupling means writing
  more than one container in a transaction.
- **A stable unit id on the container**, so a relationship can name units
  durably.

## Future paths, not near-term

Recorded so the near-term model does not foreclose them. None of this is
scheduled, and none of it should shape the first release beyond the one
model decision noted above.

### Assemblies on more than one plane

Shelving set into the corner of a room, a T-shaped arrangement with a run
projecting into the room, a U of three runs, or a library aisle of two
runs facing each other. Each needs more than one elevation plane, which
is the one assumption the single-plane model still makes.

The encouraging part is that this is one more dimension rather than a new
idea. **Seen from above, all of those arrangements are themselves
guillotine subdivisions.** A corner is a rectangle with a void bitten out
of it: cut the back strip full width, then cut what remains into the side
run and the void. A T cuts the crossbar off and then cuts the rest into
void, stem, void. An aisle is two strips with the walkway as the void
between them. The arrangement of runs is the same operation as the
arrangement of shelves, one level up, so the model generalises to a tree
whose splits may run along any of the three axes.

What it would buy beyond the arrangements themselves:

- Plane detection stops being load-bearing. Scanning would look for
  full-span cuts along any axis instead of guessing which axis is the
  depth, and a wrong guess would mis-draw rather than mis-scan.
- Corner ownership becomes explicit. One run runs through and the other
  butts into it, and which cut comes first is that choice. The tree would
  record a real construction decision instead of leaving it implicit in
  coordinates.
- Dimensional coupling comes free. The side run's length follows from the
  back run's depth, because the cut that separates them sets both, and
  their heights match because they are siblings. Keeping the runs as
  separate units instead is what costs a constraint mechanism.

What it would not solve:

- **Cross-branch alignment**, the most substantial gap. Two runs are
  separate subtrees, so their shelves line up only if their rules happen
  to yield identical numbers. A library aisle wants them locked together.
  That needs a mechanism the tree does not have, either a named rule
  shared by several splits or a constraint layer above it.
- **A pinwheel in plan**, four runs each stopping against the next, is not
  guillotine and would be refused, as it is in elevation.
- **Anything not axis-aligned**, including a 45 degree corner cabinet.

The cost is almost entirely in the editor, which is why the split above
puts the model change in early and leaves the rest out. A single front
elevation stops describing the object, so editing needs a plan view for
the arrangement plus elevation editing per run. Scanning in three
dimensions is the same voxel-grid flood fill with one more axis and cell
counts that stay trivial.

### Panels that are not boxes

A revision of a real plan has a plank with a rectangle cut out along one
edge, for access to a breaker panel, modelled as an `App::Part` holding a
`PartDesign::Body` whose `Pad` extrudes a notched sketch. For layout it
behaves like a plank: it spans a region, it has a thickness, it sits at a
position. The notch is fabrication detail, not layout.

The spike's solid inspector answers the question that decides
how such a part can be handled: subtract the solid from its own bounding
box and ask whether what is left decomposes into boxes. A part that passes
is a plank plus rectangular cutouts. One that fails has to be carried
opaquely or refused. sh-016 folded this classifier into
`freecad/shelving/container.py`'s skip-reason reporting.

Run on the real part, it passes cleanly. The solid is axis-aligned, and
the difference from its bounding box is exactly one box:

| | mm | inches |
|---|---|---|
| enclosing box | 292.1 x 18.2626 x 1480.3374 | 11.5 deep, 0.719 thick |
| notch | 196.85 x 18.2626 x 355.6 | 7.75 x 14 |
| material left behind the notch | 95.25 | 3.75 |
| notch above the panel foot | 558.8 | 22 |

Two things about the notch shape matter more than its size. It **spans the
full thickness**, so it is a hole in the profile rather than a pocket. And
it is **open at one edge** rather than enclosed, which is what lets the
panel slide into place around whatever it clears instead of having to drop
over it. So the shape is a rectilinear profile extruded through a
thickness, which is what the `Pad` already is.

That narrows the third option usefully. Deriving a general cutout list
from a solid is hard, but deriving a **rectilinear profile** from a
plank-shaped solid is a 2D problem on one face, and it is the same
guillotine-flavoured question the scanner already answers in the
elevation.

The part comes from a superseded revision of the same plan, where it
mirrored the longest leg of the stair-step unit, which is why its
enclosing box matches `panelZX008` exactly. The stair-step model that is
current is plain boxes throughout, so the fixture is faithful to it.

That history is the useful part. One revision of one plan turned a plain
panel into a notched extrusion, and the design is otherwise ordinary
shelving. A plank-like part that is not a box is what happens when a design
meets a real room, not an exotic case to guard against.

Four ways to handle a part like that:

| option | scanning | apply | works on existing geometry |
|---|---|---|---|
| Refuse it | names the object | n/a | no |
| Adopt it opaquely | bounding box, marked pinned | may move it, never resize it | yes |
| Model cutouts natively | plank plus rectangular cutouts | emits a box minus boxes | only if cutouts are derived |
| Modify downstream | reads through to our tagged box | rewrites the box, the user's cut re-applies | no, needs a rebuild |

Adopting opaquely is the one that works on a model that already exists,
and it is cheap because it reuses machinery already there: a pinned
plank's length **drives** its region instead of being driven by it, which
is the solver's existing distinction, and two pinned planks that disagree
are an ordinary over-constraint. The cost is that the unit can no longer
be resized in the direction that plank spans.

Modifying downstream is the most parametric and is already the intent of
the "3D edits" decision in `architecture.md`: the workbench owns a plain
box and the user's cut consumes it and re-applies on every regeneration.
It needs scanning to look through a `Part::Cut` to the tagged box
inside, and it needs the user to build it that way.

Deriving cutouts from arbitrary solids is still the option not to reach
for, but the real part suggests a narrower version that is worth
considering: treat a plank as a **rectilinear profile extruded through a
thickness**, and derive that profile from the solid's largest face. A
plain plank is the degenerate case with a rectangular profile. This stays
a 2D problem, keeps every plank a single extrusion, and covers an edge
notch, an L-shaped top, and a stepped end with one mechanism. It does not
cover a pocket that stops partway through, a mitre, or anything not
axis-aligned.

Whatever is chosen, every plank is still a rectangular box for layout
purposes, and these have no representation at all:

- an L-shaped or notched top cut from one sheet;
- a mitred corner where two tops meet on a 45 degree cut;
- a shelf notched around a post;
- a panel scribed to a wall, which is normal in a room that is not square;
- a 45 degree corner cabinet.

Some of these are fabrication rather than design, and the architecture
already places fabrication outside the model. A mitred corner is
arguably one: the panel is a rectangle and the mitre is a cut applied to
it. An L-shaped top is not, because its outline is the design.

The near-term requirement is only that such a panel is never silently
dropped.

## How the roadmap changes if adopted

- The `Plank` `Part::FeaturePython` proxy and the driver's per-recompute
  `execute` are replaced by plain `Part::Box` objects carrying dynamic
  properties and by the scan / edit / apply commands. The container
  and its `Placement` stay; `App::LinkGroup` is accepted alongside
  `App::Part`.
- `shelving_core` gains scanning (boxes to tree, or a structured
  refusal) with its round-trip test against `expand`, and the spike's general
  region tree in place of `Carcass`: `Void`
  regions for the outline, planks as ordinary items, and no shell rule.
- **The model carries an axis per split from the start**, so a second
  elevation plane needs no change to it later. Concretely: a split names
  X, Y, or Z rather than an orientation within an assumed plane; depth is
  a region's extent rather than a field on the unit; and a plank fills its
  region's cross-section with a per-face inset, which is the same
  parameter that expresses a joint clearance. This is not speculative
  work. It deletes the unit-level depth field, folds the separate
  clearance and depth-inset parameters into one, and stops backs and
  fronts being set aside from the partition, all of which the single-plane
  case needs anyway. See the future path below for what it buys later.
- Scanning cuts a region at **any coordinate no plank crosses**, not
  only where a single plank spans it. Two abutting units are the case that
  forces this: their tops are separate boards that together span the
  width, and their seam is two panels face to face. Cutting at a plank's
  faces becomes the special case where the slab holds one plank.
- Scanning and the editor stay **single-plane** near-term. A
  multi-plane container is refused, naming the planks that do not lie in
  the chosen plane. Plane detection therefore stays load-bearing for
  scanning and keeps its known fragility; the axis-per-split model
  demotes it to a presentation hint only once scanning itself goes
  multi-plane.
- Scanning works in the **container's local frame**. The export macro
  currently composes container placements into global coordinates, so a
  unit rotated in a room would present as rotated boxes and be refused.
- Objects the export skips, meaning anything that is not a `Part::Box`,
  are **reported rather than dropped**. Today the macro records them
  under `skipped`, and both the scanner and the report ignore that key,
  so a non-box panel disappears without complaint and the unit scans
  as though it were never there. A missing panel changes nothing
  structurally, so nothing else catches it.
- Export must **deduplicate by document object**. A selection can reach
  the same object by more than one path, and eleven planks in a real
  export came through twice, byte for byte.
- The container walk must **stop at a part, not descend into its
  history**. A `PartDesign::Body` exposes its features through `Group`, so
  the walk currently treats a body's sketch and pad as separate leaves and
  skips both, never looking at the body's own solid. Containers to descend
  into are `App::Part`, `App::LinkGroup`, and plain groups; a body or a
  boolean is one part and its children are its construction, not its
  contents.
- M8 (catalog) keeps its shape; material identity is a stored property
  on each box.
- M9 (editor) becomes the centre of the product: it is the only place the
  tree exists, so it opens from a scanned container, not only from a
  unit the workbench created.
- M12 and M13 (`StudWall`, openings) gain scan rules for studs and
  headers; the on-centre spacing rule is recovered from stored properties,
  never from geometry.
- The "3D edits" and "Source of truth" decisions in `architecture.md`
  change: direct edits round-trip through scan, and the boxes are the
  source of truth with the tree as a transient editing view.
