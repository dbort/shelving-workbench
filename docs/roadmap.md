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
  over `freecad/shelving/`, and a headless functional-test harness
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

**Status:** Planned

Replace the carcass with the region tree: a region is an open bay, a void,
or a division into an ordered run of planks and sub-regions. `solve` and
`expand` work on it, reusing the existing slack distribution unchanged,
because a plank contributes a fixed thickness and a region contributes its
rule. The shell stops being a rule and becomes the outermost planks of the
outermost divisions, which is what lets a stepped outline, a through
shelf, and two planks face to face be ordinary.

The FreeCAD object layer goes in the same task. The `Plank` scripted
object, the `ShelvingUnit` driver, the create-unit command, and the object
smoke are all built on the carcass and none of them survive the new
design, so porting them would be work done twice.

`spikes/plain_planks/general_model.py` is the worked design; copy from it
rather than moving it, so the spike keeps running as the fallback for the
two milestones during which the workbench has no commands.

*Verify:* the core suite, including an equivalence check that a closed box
built from ordinary items expands to what the carcass model expanded to,
plank for plank; the demo script prints a plank table for a stepped unit;
`freecadcmd` still loads the workbench.

## M5 — Scanning, no FreeCAD

**Status:** Planned

Read a layout from geometry: axis-aligned boxes in, a region tree or a
refusal naming the objects out. Detects the elevation plane, cuts at every
line no plank crosses, treats gaps narrower than the joint clearance as
joints rather than compartments, and separates space enclosed by planks
from space open to the outside. Carries what it cannot read rather than
dropping it: a missing panel does not fail the scan, it makes enclosed
bays read as open instead.

`spikes/plain_planks/scan.py` and its fixtures are the worked design; copy
from them, again leaving the spike intact.

*Verify:* the core suite over real exported units, a stepped unit, two
abutting units whose side panels meet, and a generated Woodworking
cabinet, plus the refusal cases.

## M6 — Read a container

**Status:** Planned

The FreeCAD half of scanning: walk a container the user selects, stopping
at parts rather than descending into a solid's construction, deduplicating
objects a selection reaches by more than one path, and reading each box in
the container's own frame. A **Scan** command reports what it found,
including anything it could not read.

`spikes/` is deleted here, in this task. The workbench can now do what the
spike was standing in for, so the fallback has no remaining job. The
container walk comes from `export_boxes.py` and the Scan report replaces
`report.py`. One piece has no planned replacement: `inspect_object.py`
reports whether a part is a plain box, a box minus rectangular cutouts, or
something else, which is what a user wants when a scan refuses on a part
it cannot read. This task decides whether that folds into the Scan refusal
path or keeps a home under `tools/`.

*Verify in FreeCAD:* select a container of boxes and run Scan; a unit it
understands reports its compartments, and one it does not names the
objects and says why. A headless check scans a document built in the test;
`spikes/` is gone and nothing references it.

## M7 — Write a container

**Status:** Planned

Apply a layout back to a container as plain `Part::Box` objects, matched
by the object's own name so a rename, a colour, or a downstream reference
survives. Stores what geometry cannot carry: a plank's material and the
rule beside it, provenance for telling a copy from an original, and on the
container the unit's identity, plane, facing, and compartment rules. A
**Create Unit** command builds a starter unit through the same path.

*Verify in FreeCAD:* create a unit and get plain boxes; scan it back and
get the same layout; change a dimension and watch it reflow; save, reopen
with the workbench uninstalled, and find the document intact.

## M8 — Material catalog

**Status:** Planned

The catalog as a document object, seeded from the in-code default, with a
command to edit it and a per-plank material override. Editing an entry
reflows every plank that references it.

*Verify in FreeCAD:* change a stock thickness, reflow, and see every plank
using it change while the unit's outside dimensions hold.

## M9 — The elevation editor

**Status:** Planned

The modal task panel: an elevation rendered from the scanned layout, pick
a compartment, split it, delete a divider to merge. Then dimensions: type
an exact size with fractional-inch input, drag a divider, and choose
whether a size measures the clear opening or the spacing across a shelf.
Dragging changes the number and never what it measures. OK and Cancel wrap
one transaction, and the 3D follows as you go.

*Verify in FreeCAD:* build a three-shelf bookcase entirely through the
editor, set one opening exactly and watch the rest redistribute, switch a
dimension to shelf spacing and change the stock thickness to see the
shelves hold, then undo the whole session in one step.

## M10 — v1 polish

**Status:** Planned

Colour by material, generated labels that stay correct when a unit's
facing is unknown, error surfacing for an over-constrained layout, a
preferences page, finalised `package.xml`, and user documentation.

*Verify in FreeCAD:* install from the GitHub repository through the Addon
Manager on a clean profile, model a real unit, move it into a second
document with an ordinary placement, and confirm an over-constrained input
produces a clear error and no stale geometry.

## M11 — Back panels

**Status:** Planned

Backs and fronts as planks in the depth axis rather than parts set aside
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
- **Panels that are not boxes**, beginning with whether a plank is better
  modelled as a rectilinear profile extruded through a thickness.
- **A support check**, since a plank floating clear of its neighbours is a
  valid arrangement of straight cuts and is currently accepted.
- **Parametric joinery** with promote-to-Body, the cut-list spreadsheet,
  the TechDraw elevation, and assembly joints.
