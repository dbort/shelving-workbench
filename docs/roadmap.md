# Shelving Workbench Roadmap

The milestone breakdown of [`architecture.md`](architecture.md). Each
milestone is self-contained and ends with a concrete way to see it working
in FreeCAD. Milestones become `sh-XXX` tasks through the normal pipeline.

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

**Status:** Tasks sh-009, sh-010

- [x] sh-009 — material catalog (`shelving_core.materials`) and reworking the
  spacing solver to resolve panel thickness from the catalog
- [ ] sh-010 — carcass expansion (`shelving_core.expand`): the `PlankSpec`
  list, the lap rule, the coordinate convention (blocked on sh-009)

`shelving_core.expand` and `shelving_core.materials`: catalog data
model, expansion to a `PlankSpec` list, per-joint lap order, coordinate
convention, per-node material overrides (per-node depth override deferred
past M2).

*Verify:* pytest asserting plank sizes, placements, and total volume for
sample units; the print script gains a plank table.

## M3 — `ShelvingUnit` in FreeCAD

**Status:** Planned

Workbench skeleton, the "create unit" command, the `App::Part` container
with promoted scalars and the `Layout` JSON property, `execute` calling
core expansion and reconciling child `Part::FeaturePython` planks by
UUID. No custom editor: the layout is edited by hand-editing the JSON
property or from the Python console.

*Verify in FreeCAD:* create a unit from the toolbar; change `Width`,
`Height`, `Depth`, and `DefaultMaterial` in the property editor and watch
planks reflow; a headless FreeCAD test in `pixi run tests` asserts plank
count and bounding box.

## M4 — Material catalog

**Status:** Planned

The catalog object, the default seeded catalog, the "manage catalog"
command, and the per-plank `Material` override. Editing a catalog entry
reflows dependent planks.

*Verify in FreeCAD:* change a stock thickness in the catalog, recompute,
see every plank using it change; a headless FreeCAD test in `pixi run tests`
asserts the reflow.

## M5 — The 2.5D editor

**Status:** Planned

The modal task panel: elevation render, select a bay, split H/V, drag a
split, type an exact dimension with fractional-inch parsing, Delete to
remove a split, OK/Cancel around one transaction, live 3D preview.

*Verify in FreeCAD:* build a three-shelf bookcase entirely through the
editor, adjust a middle opening, watch the rest redistribute, undo the
whole session in one step.

## M6 — v1 polish

**Status:** Planned

ViewProvider colour-by-material, generated `Label`s, error surfacing on
over-constraint, preferences page, finalised `package.xml`, user docs.

*Verify in FreeCAD:* install from the GitHub repo through the Addon
Manager on a clean profile; model a real unit; move it into a second
document with `Placement`; confirm an over-constrained input produces a
clear error and no stale geometry.

## M7 — Back panels

**Status:** Planned

Unit-level back treatment (rabbeted / overlay / captured) and a back
material, as an expansion-rule addition plus one new plank role.

*Verify in FreeCAD:* toggle the back treatment on an existing unit; the
back plank appears and tracks size changes.

## M8 — Framing: `StudWall`

**Status:** Planned

A second scripted object reusing `shelving_core`: bottom plate, double
top plate, studs at on-center spacing with a remainder stud, driving vs
driven spacing. Its own minimal task panel or property-driven for now.

*Verify in FreeCAD:* create a wall, change length and stud spacing, watch
studs redistribute with a correct remainder.

## M9 — Framing: openings

**Status:** Planned

An opening subdivides a bay and expands to king, jack, cripple, header,
and sill members with parametric header depth and rough-opening
clearances.

*Verify in FreeCAD:* place a window and a door opening in a wall; move an
opening and change its size; confirm cripples and jacks follow.

## Later

**Status:** Planned

Parametric joinery with promote-to-Body, the cut-list Spreadsheet, the
TechDraw elevation, multi-box units, and assembly joints, each as its own
task.
