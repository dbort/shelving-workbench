# Shelving Workbench Roadmap

The milestone breakdown of [`scope-and-design.md`](scope-and-design.md).
Each milestone is self-contained and ends with a concrete way to see it
working in FreeCAD. Milestones become `sh-XXX` tasks through the normal
pipeline.

M0 to M3 are history. They were delivered against an earlier design in
which the workbench owned its plank objects and drove them from a
serialised split-tree, described in [`architecture.md`](architecture.md).
The layout engine and the material catalog from that work carry forward;
the object layer does not. M4 onwards rebuild on the current design, in
which plain solids are the model and the workbench reads and writes
them.

## Status legend

Every milestone carries a **Status** line. A milestone delivered by one
task uses:

- **Planned** — no task exists yet.
- **Task sh-XXX** — a task file exists and is moving through the pipeline.
  Keep the id in sync; add `(blocked on sh-YYY)` when relevant.
- **Done sh-XXX** — the task merged to `main`. Record the id that
  delivered it.

Set **Task sh-XXX** in the same change that creates the task file. The
flip to **Done sh-XXX** is made by `approve-task` when the branch merges
to `main`, never by the task's own implementation or review steps.

### Milestones split across several tasks

A milestone too large for one task lists each delivering task in a
checklist directly under its **Status** line, and the **Status** line
becomes a rollup:

- **Planned** — no task file exists yet.
- **Tasks sh-XXX, sh-YYY, …** — at least one task file exists; the line
  names every task in the split, in dependency order.
- **Done sh-XXX, sh-YYY, …** — every task in the split has merged to
  `main`.

The checklist carries one line per task, `- [ ] sh-XXX — <what it
delivers>`, with `(blocked on sh-YYY)` appended where a dependency
applies:

    **Status:** Tasks sh-009, sh-010

    - [x] sh-009 — material catalog + solver rework
    - [ ] sh-010 — carcass expansion (blocked on sh-009)

`new-task` writes this block when it creates a task file for the
milestone: it adds the checklist, converting a single-task milestone if
needed, and keeps the **Status** id list in sync. `approve-task` ticks a
task's box when its branch merges and flips the rollup to **Done …** as
it ticks the last box. The human-gate rule is unchanged: no agent ticks a
box or edits the **Status** line outside `approve-task`, or `new-task` at
task creation.

## M0 — Scaffold

**Status:** Done sh-001

Monorepo skeleton, MIT `LICENSE`, `package.xml`, the `pixi run tests`
check harness wired up, and a GitHub Actions job that runs it in a
FreeCAD 1.0 environment and imports the (empty) workbench.

*Verify:* CI is green; `freecadcmd` loads the workbench with no errors.

## M1 — Layout engine, no FreeCAD

**Status:** Done sh-003

`shelving_core.layout` and `shelving_core.solver`: split-tree types,
JSON round-trip, the spacing solver with fixed / weighted / fill,
driving/driven slack distribution, and the structured over-constraint
error.

*Verify:* pytest, plus a short script that prints computed opening sizes
for a sample layout so the distribution is eyeballable.

## M2 — Carcass expansion, no FreeCAD

**Status:** Done sh-009, sh-010

- [x] sh-009 — material catalog (`shelving_core.materials`) and reworking the
  spacing solver to resolve panel thickness from the catalog
- [x] sh-010 — carcass expansion (`shelving_core.expand`): the `PlankSpec`
  list, the lap rule, the coordinate convention

`shelving_core.expand` and `shelving_core.materials`: catalog data
model, expansion to a `PlankSpec` list, per-joint lap order, coordinate
convention, per-node material overrides (per-node depth override deferred
past M2).

*Verify:* pytest asserting plank sizes, placements, and total volume for
sample units; the print script gains a plank table.

## M3 — `ShelvingUnit` in FreeCAD

**Status:** Done sh-011, sh-012

- [x] sh-011 — FreeCAD object layer: the isolable plank box helper, the
  `Plank` `Part::FeaturePython`, generated `Label`s, the in-code default
  catalog, the `freecad-stubs` type-check dependency plus `mypy --strict`
  over `freecad/Shelving/`, and a headless functional-test harness
- [x] sh-012 — the `ShelvingUnit` `App::Part` container, the "create unit"
  command and toolbar, `execute` calling core expansion and reconciling
  child planks by UUID (blocked on sh-011)

Workbench skeleton, the "create unit" command, the `App::Part` container
with promoted scalars and the `Layout` JSON property, `execute` calling
core expansion and reconciling child `Part::FeaturePython` planks by
UUID. No custom editor: the layout is edited by hand-editing the JSON
property or from the Python console.

M4 removes this object layer.

*Verify in FreeCAD:* create a unit from the toolbar; change `Width`,
`Height`, `Depth`, and `DefaultMaterial` in the property editor and watch
planks reflow; a headless FreeCAD test in `pixi run tests` asserts plank
count and bounding box.

## M4 — The region model, no FreeCAD

**Status:** Done sh-013

Replace the carcass with the region model: a region is a bay, a void, or a
division of an ordered run of boards and sub-regions along one axis.
`solve` and `expand` work on it, reusing the existing slack distribution
unchanged, because a board contributes a fixed thickness and a region
contributes its rule. The shell stops being a rule and becomes the
outermost boards of the outermost divisions, which is what lets a stepped
outline, a through shelf, and two boards face to face be ordinary.

Regions carry a 3D extent and a division names an axis, so the unit-wide
depth and the special-cased front inset collapse into one per-face inset on
a board.

The FreeCAD object layer goes in the same task, and so does the SVG
elevation renderer. The scripted plank, the driver, the create-unit
command, the object smoke, and the renderer are all built on the carcass
and none of them survive, so porting them would be work done twice. M5
rebuilds the renderer on the region model.

`spikes/plain_planks/general_model.py` was the worked design, copied from
rather than moved, so the spike kept running as the fallback for the two
milestones during which the workbench had no commands. `spikes/` was
deleted in M6, once the workbench could do what it had stood in for.

*Verify:* the core suite, including a check that a closed box built from
ordinary items expands to the geometry the carcass model produced, board
for board, against hard-coded values; the demo script prints a board table
for a stepped unit; `freecadcmd` still loads the workbench.

## M5 — Scanning and the elevation renderer, no FreeCAD

**Status:** Done sh-014, sh-015

- [x] sh-014 — scanning: geometry to a region model, or a refusal
- [x] sh-015 — the elevation renderer, rebuilt on the region model (blocked
  on sh-014)

Read a layout from geometry: axis-aligned boxes in, a region tree or a
refusal naming the objects out. Detects the elevation plane, cuts at every
line no board crosses, treats gaps narrower than the joint clearance as
joints rather than compartments, and separates space enclosed by boards
from space open to the outside. Carries what it cannot read rather than
dropping it: a missing panel does not fail the scan, it makes enclosed
bays read as open instead.

`spikes/plain_planks/scan.py` and its fixtures were the worked design,
copied from rather than moved, again leaving the spike intact until M6
deleted it.

Then the elevation renderer that M4 removed, rebuilt on the region model
and drawing bays, boards and voids. It lands here rather than with the
model so its first subject is a scanned real file rather than a synthetic
sample, which is a far better check of what scanning made of a stepped
outline or two abutting units.

*Verify:* the core suite over real exported units, a stepped unit, two
abutting units whose side panels meet, and a generated Woodworking
cabinet, plus the refusal cases; `pixi run demo` writes an SVG elevation of
a scanned fixture.

## M6 — Read a container

**Status:** Done sh-016

The FreeCAD half of scanning: walk a container the user selects, stopping
at parts rather than descending into a solid's construction, deduplicating
objects a selection reaches by more than one path, and reading each box in
the container's own frame. A **Scan** command reports what it found,
including anything it could not read.

Reading is in the container's own frame, so a unit moved or rotated in a
room reads the same as one at the origin, and sizes come from each part's
bounding box rather than its length, width and height properties, so a
board rotated a quarter turn still reads. A part the walk cannot read is
reported with the reason in geometric terms, a box minus two rectangular
cutouts or not axis-aligned, never dropped. Reading one as a board needs a
flag that lets its size drive its region, which lands with M7 alongside the
stored metadata that marks it.

An **Export boxes** command writes the same records to JSON, which is how a
unit that refuses gets captured without sharing a whole document.

`spikes/` is deleted here. The workbench can now do what the spike was
standing in for, so the fallback has no remaining job: the container walk
comes from `export_boxes.py`, the report from `report.py`, and
`inspect_object.py`'s solid classifier folds into the reason a part was
skipped.

*Verify in FreeCAD:* select a container of boxes and run Scan; a unit it
understands reports its compartments, and one it does not names the
objects, says why, and selects them in the 3D view. A headless check reads
and scans a document built in the test; `spikes/` is gone and nothing
references it.

## M7 — Write a container

**Status:** Done sh-017, sh-018

- [x] sh-017 — pinned parts and the stored rule record
- [x] sh-018 — writing a container, and the create and resize commands
  (blocked on sh-016 and sh-017)

Apply a layout back to a container as plain `Part::Box` objects, matched
by the object's own name so a rename, a colour, or a downstream reference
survives, and deleting only objects this workbench tagged, so a part it
did not write is never removed.

Brings the pinned board, a part the workbench cannot regenerate such as a
notched panel. The solver verifies its extent rather than deriving it and
raises when a layout would need a different one, so resizing a unit across
a fixed panel fails, which is true. Apply moves such a part but never
rewrites it.

Stores what geometry cannot carry, then reads it back, so a rescan
recovers the intent it was given rather than re-guessing it: a board's
material, provenance for telling a copy from an original, and on the
container the unit's identity, depth axis, facing, and the per-region
rules. The rules are keyed by the boards bounding each region, because a
region's own id is fresh on every scan.

**Create Unit** seeds a starter unit and **Resize Unit** takes new outer
dimensions, both through the same write path. Resize rescans every time
rather than caching a model, so a board moved by hand between operations
is taken up rather than overwritten. The unit's size stays geometry rather
than becoming a container property: a property nothing recomputes would be
a second source of truth that lies, and making one honest needs the
live-unit driver under *Later*.

*Verify in FreeCAD:* create a unit and get plain boxes; scan it back and
get the same layout; resize it and watch it reflow while labels and
colours hold; move a board by hand and rescan to take the edit up; put an
unrelated box in the container and confirm apply leaves it and says so;
save, reopen with the workbench uninstalled, and find the document
intact.

## M8 — Material catalog

**Status:** Done sh-019

The catalog moves out of code and into the document: a group of `VarSet`
entries, one per stock item, each editable in the property editor. No
proxy and no edit dialog, so a document whose owner never installed this
workbench still shows its materials, and editing one is the property
editor rather than a panel duplicating it. Seeded from the in-code default
the first time anything needs it, so a fresh document needs no setup.

A material id is the stable key rather than an object name, so renaming an
entry does not orphan the boards using it, and a duplicate id is an error
naming both entries.

**Reflow All** rescans and rewrites every tagged unit in the document,
which is what carries a changed thickness to the boards. A rescan picks the
change up because a board stores its material and scanning prefers that to
matching by thickness; without that precedence every existing board would
match no entry and the rescan would refuse.

*Verify in FreeCAD:* change a stock thickness, run Reflow All, and see
every board using it change while each unit's outside dimensions hold.

## M9 — The elevation editor

**Status:** Tasks sh-020, sh-021

- [ ] sh-020 — the panel, the scene, selection, split and merge
- [ ] sh-021 — dimensions, dragging, the measurement basis, and the
  untagged-object choice (blocked on sh-020)

The modal task panel: an elevation rendered from the scanned layout, pick
a compartment, split it, delete a divider to merge. Then dimensions: type
an exact size with fractional-inch input, drag a divider, and choose
whether a size measures the clear opening or the spacing across a shelf.
Dragging changes the number and never what it measures. OK and Cancel wrap
one transaction, and the 3D follows as you go.

The panel is also where apply's untagged objects get a choice. M7 leaves
anything this workbench did not write exactly where it is and reports it;
a panel has somewhere to put the question, so the editor can offer to
remove indicated boards or ignore them, with the reason stated.

Built in three layers so most of it is testable. Editing operations are
tree functions in the core, a unit in and a unit out, covered by the fast
suite. The Qt scene renders and hit-tests, covered by an offscreen
`QApplication`, which works under `freecadcmd` along with simulated clicks.
Only the task-panel shell needs a human, because `FreeCADGui.Control` does
not exist headlessly.

The dimension field is FreeCAD's own quantity input, so it accepts what
every other length field accepts, including an expression naming a
variable, and this workbench inspects nothing a user types. The field is an
expression language rather than a number, so any pattern check over it
produces false refusals, and a false refusal has no workaround.

*Verify in FreeCAD:* build a three-shelf bookcase entirely through the
editor, set one opening exactly and watch the rest redistribute, switch a
dimension to shelf spacing and change the stock thickness to see the
shelves hold, then undo the whole session in one step.

## M10 — v1 polish

**Status:** Tasks sh-022, sh-023, sh-024

- [ ] sh-022 — appearance and error surfacing (blocked on sh-021)
- [ ] sh-023 — the preferences page (blocked on sh-021)
- [ ] sh-024 — user documentation and the release (blocked on sh-022 and
  sh-023)

The workbench states an opinion when it creates something and never again.
A board takes its material's colour and a readable label when it is
written, and an update rewrites neither, so a rename or a recolour
survives every resize. Two commands take that opinion back on request.
Colour maps deterministically from the material id, so the same stock is
the same colour in every unit.

Every refusal takes one shape: a summary, the objects responsible, and a
suggested next step, with the objects selected in the 3D view. A refusal a
user cannot act on reads as a bug, so the suggestion is data beside each
reason rather than prose scattered through the commands.

The preferences page holds six values and no more: the starter unit's four,
and the snap and joint-clearance tolerances. The tolerances are there
because real geometry has coincident edges disagreeing by up to 0.09 mm,
and someone whose model is worse needs a way forward that is not editing
the source.

Then the user guide, which leads with scanning geometry you already have
rather than with creating a unit, documents what each refusal means, and
states the three limits a user will meet. `architecture.md` is deleted
here: its supersession banner has done its job.

*Verify in FreeCAD:* install from the GitHub repository through the Addon
Manager on a clean profile, model a real unit, move it into a second
document with an ordinary placement, confirm an over-constrained input
produces a clear error and no stale geometry, and walk the user guide's
steps exactly as written.

## M11 — Back panels

**Status:** Planned

Backs and fronts as boards in the depth axis rather than parts set aside
during scanning, with the treatments that go with them: rabbeted, overlay,
and captured, and a back material.

*Verify in FreeCAD:* add a back to an existing unit; it appears, tracks
size changes, and scans back as the same treatment.

## M12 — Framing: `StudWall`

**Status:** Planned

A second consumer of the same core: bottom plate, double top plate, and
studs at on-centre spacing with a remainder stud. Brings the repeat rule,
where a member count is computed from a pitch rather than spelled out, and
with it the question of how members that have no durable identity are
matched on reflow.

*Verify in FreeCAD:* create a wall, change its length and stud spacing,
and watch the studs redistribute with a correct remainder.

## M13 — Framing: openings

**Status:** Planned

An opening subdivides a bay and expands to king, jack, cripple, header,
and sill members, with parametric header depth and rough-opening
clearances.

*Verify in FreeCAD:* place a window and a door opening in a wall, move one
and change its size, and confirm the cripples and jacks follow.

## Later

**Status:** Planned

Each of these is its own task when it comes up.

- **Named values shared between units**, so a shelf spacing set once
  applies everywhere, held in an ordinary variable set so it can carry an
  expression and be driven from elsewhere in the document.
- **Live units**, an opt-in driver per unit that reflows on recompute
  rather than on command, with the tradeoff that a live unit is not
  hand-editable.
- **Assemblies on more than one plane**: shelving in a corner, a T of
  runs, an aisle. Needs a plan view alongside the elevation editor, and
  needs the cross-unit alignment that named values start.
- **Physical materials**, referencing FreeCAD's own material system so a
  stock entry names a substance rather than describing one. Stock and
  substance are separate lists: a thickness belongs to the sheet you
  bought, a density to the material. The first real payoff is mass, since
  per-board volume is already computed, and colour by material would come
  with it. Stress analysis is much further off: the model is butt joints
  with no fasteners, so an analysis would be modelling a pile of loose
  boards.
- **Panels that are not boxes**, beginning with whether a board is better
  modelled as a rectilinear profile extruded through a thickness.
- **A support check**, since a board floating clear of its neighbours is a
  valid arrangement of straight cuts and is currently accepted.
- **Parametric joinery** with promote-to-Body, the cut-list spreadsheet,
  the TechDraw elevation, and assembly joints.
