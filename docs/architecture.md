# Shelving Workbench Architecture

A FreeCAD 1.0 workbench for parametric shelving. A unit is designed as a
flat front elevation (a "2.5D" view: 2D layout plus a depth value per
element), and expands into individually editable 3D plank solids that live
in the Part, Draft, and Woodworking workflows. Editing the elevation
reflows the 3D. The layout engine is written so a stud-framed wall with
openings is the same problem with different expansion rules.

This document is the design of record. The implementation roadmap at the
end breaks it into milestones, each of which produces something testable
in FreeCAD.

The GitHub repository is `shelving-workbench`. "shelving" is the short
name used for the Python package, the vendored core, and the FreeCAD
workbench identifier.

## Scope

### v1 delivers

- A `ShelvingUnit` parametric object: a single self-contained carcass
  (one "box").
- Butt-joint construction only. Sides run full height and depth; top,
  bottom, shelves, and dividers are captured between the sides. The lap
  order of any individual joint (which member runs continuous, which is
  captured) is an overridable per-joint attribute; the carcass rule is
  only the default.
- A recursive split layout: any bay is either a leaf or is divided
  horizontally or vertically into two child bays.
- A modal task-panel elevation editor with: split a bay H or V, drag a
  split, type an exact opening dimension (fractional-inch input
  accepted). Delete removes a split and merges its bays.
- A document-level material catalog. The only required field per stock
  entry is actual thickness. Editing an entry reflows every plank that
  references it.
- Per-plank 3D solids, individually selectable and taggable, each
  carrying a material reference, a grain-direction value, and a
  human-readable `Label`.
- Placement of a finished unit into a larger document by ordinary
  `Placement` edits.

### Deferred, but the design leaves room

Sequenced roughly in this order:

1. **Back panels** (rabbeted / overlay / captured, with a back material).
2. **Framing walls**: a `StudWall` object reusing the layout engine
   (plates, studs at on-center spacing with a remainder stud), then
   openings that subdivide a bay into king / jack / cripple / header /
   sill members.
3. Parametric joinery (dado / rabbet / groove per joint) and promotion of
   planks to PartDesign Bodies so joinery is real feature history.
4. A cut-list Spreadsheet and a dimensioned TechDraw elevation.
5. Multi-box units (a bank of carcasses in one unit) and assembly joints.

### Explicitly out of scope for the foreseeable term

Fabrication concerns are not part of the model. Kerf, saw and sheet
optimisation, cost rollups, hardware, fasteners, edge banding, line
boring, doors, drawers, and face frames are all downstream of the "ideal
form" the workbench produces.

## Decisions of record

| Area | Decision |
|---|---|
| Component type | Python workbench, Addon-Manager-installable; core deliverable is a set of scripted objects |
| Source of truth | The parametric model (split-tree + params + material refs) is the only source of truth; 3D is a pure projection, regenerated on every change |
| 3D edits | Downstream features that reference a generated plank survive regeneration as long as that plank still exists; direct edits to plank geometry do not round-trip |
| Layout model | Recursive binary split-tree; a bay is a leaf or is split H/V at a rule-driven position |
| Split rule | Each split stores a rule (fixed size / weight / fill), not an absolute coordinate. A fixed rule's number is the clear opening on its reference side. Absolute positions are derived and cached |
| Constraint priority | Each span is driving or driven; the solver holds driving values and distributes slack to driven ones. Default: exterior dimensions drive, interior openings are driven |
| Over-constraint | Hard error. The unit produces no shape and enters the standard FreeCAD error state until the input is corrected. The editor validates input to make this a backstop, not the normal path |
| Granularity | One `App::Part` container per unit, holding one `Part::FeaturePython` solid per physical plank |
| Plank identity | Every split-tree node carries a persistent UUID. Child objects match by UUID across regeneration: updated in place, added, or removed. `Label` is a generated readable default, user-overridable, never used for matching |
| Plank representation | `Part::FeaturePython` solid rebuilt from the tree; base geometry kept isolable so a later "promote to PartDesign Body" path is clean |
| Container | `App::Part`, for `App::Link` and built-in Assembly compatibility and a single rigid-body `Placement` |
| Assembly | v1 uses plain `Placement`. The container stays compatible with the FreeCAD 1.0 built-in Assembly workbench |
| Material model | Document-level catalog object. Required field: actual thickness. All other fields optional. Planks reference stock by UUID; unit has a default, any node may override |
| Parameter storage | Full split-tree serialised to a hidden `App::PropertyString` (JSON) on the container. Common knobs (overall W/H/D, default material) also promoted to first-class properties |
| 2.5D editor | Modal task panel, `QGraphicsView` elevation, live 3D preview, OK/Cancel wrapping one document transaction |
| Coordinates | Front elevation on the XZ plane (X right, Z up); depth runs +Y away from the viewer. Unit origin at the front-bottom-left corner. One depth for the whole unit in v1; per-bay depth override reserved in the schema |
| Units | Millimetres internally. Display follows the FreeCAD unit schema. The dimension field parses fractional-inch input (`3/4`, `12 1/2"`) |
| Platform | FreeCAD 1.0 or later, PySide6, Python 3.11 or later. FreeCAD 0.21 is not supported |
| Repo | GitHub `shelving-workbench`. Monorepo; `shelving_core/` is pure Python with no FreeCAD imports; the workbench vendors it |
| License | MIT |

## Core library (`shelving_core`)

Pure Python, no FreeCAD imports, unit-tested with pytest. The workbench
vendors a copy. This boundary is what keeps the engine testable without a
GUI, and it is enforced: `shelving_core` importing anything from
`FreeCAD` or `FreeCADGui` is a test failure.

### The split-tree

A `Unit` holds outer dimensions, a default material reference, a depth,
and a root `Bay`. A `Bay` is either:

- a **leaf**: an open compartment, optionally with a material or depth
  override; or
- a **split**: an orientation (horizontal or vertical), a divider node
  (its own material/thickness, inherited from the unit default unless
  overridden), a `SplitRule`, and two child `Bay`s.

Every node carries a UUID assigned at creation and preserved across all
edits. Serialisation is a JSON object mirroring this structure, stored on
the container. A small schema version field allows later migration.

### The spacing solver

Given a parent span and a list of sibling openings, each with a
`SplitRule`, the solver assigns each opening a concrete size:

- **fixed**: the opening takes its stated clear size on its reference
  side. Driving.
- **weighted**: the opening takes a share of leftover space proportional
  to its weight. Driven.
- **fill**: weight-1 shorthand. Driven.

Divider thickness (from the divider's material) is subtracted from the
parent span before leftover space is distributed. If the fixed openings
plus divider thicknesses exceed the parent span, the solve fails with a
structured error naming the offending bay; the FreeCAD layer turns this
into a recompute error.

Rules are never edited through an explicit control in v1. A freshly split
bay's two children are both `fill`. Typing a dimension on an opening or
dragging its split converts that opening to `fixed` at the resulting
size; its sibling keeps whatever rule it had and absorbs the slack.

### Carcass expansion

`expand(unit, catalog) -> list[PlankSpec]` walks the tree and emits one
`PlankSpec` per physical plank: the two outer sides, top, bottom, every
divider, and (later) the back. A `PlankSpec` is `(uuid, role, size as a
3-tuple, placement, material_ref, grain)` in the unit's local frame.

The default carcass rule (sides continuous, everything else captured
between them) sets each joint's default lap order. A per-joint override
flips which member runs through. Expansion reads the effective lap order
per joint to decide each plank's length and position.

Expansion has no FreeCAD dependency: it produces plain data. The FreeCAD
layer turns each `PlankSpec` into a solid.

## FreeCAD layer (`freecad/shelving`)

### Workbench

Registers menus, a toolbar, and a preferences page (default catalog,
default depth, default material). Activating it exposes the commands:
create unit, edit layout, manage catalog.

### `ShelvingUnit` container

An `App::Part` with a Python proxy. Properties:

- promoted scalars: `Width`, `Height`, `Depth`, `DefaultMaterial`;
- `Layout`: hidden `App::PropertyString` holding the split-tree JSON;
- standard `Placement` (inherited from `App::Part`).

`execute` deserialises `Layout`, runs `shelving_core.expand` against the
document's catalog, then reconciles children: for each `PlankSpec`, find
the child `Part::FeaturePython` whose stored UUID matches and update its
shape and metadata in place; create children for new UUIDs; delete
children whose UUID is gone. A structured solver error is re-raised so
FreeCAD marks the object as touched-with-error and shows no stale shape.

### Plank objects

One `Part::FeaturePython` per `PlankSpec`, parented into the container.
Properties: `NodeId` (the UUID, hidden), `Material`, `Grain`, and
read-only reporting of finished size. `execute` builds a box from the
spec. The box is built from an isolable helper so a future milestone can
feed it into a PartDesign Body base feature without reworking the object.

`Label` defaults to a generated name (`Left Side`, `Top`, `Shelf 2`,
`Divider 1`), regenerated only for still-unnamed planks so user renames
stick.

### 2.5D layout editor

A task panel opened by "Edit Layout" on a selected unit. A `QGraphicsView`
renders the front elevation from the current tree. Interactions:

- click a bay to select it; buttons or context menu to split it H or V;
- drag a split line: the dragged opening becomes `fixed` at the dragged
  size, a live dimension readout follows the cursor, the 3D updates on
  each drag step;
- select an opening, type an exact size (parsed through the FreeCAD unit
  system, fractional inch accepted): that opening becomes `fixed`;
- Delete on a selected divider removes the split and merges its bays.

The panel opens one `openTransaction`; OK commits it, Cancel aborts it, so
undo granularity is one editing session. Live preview writes to the real
objects inside that transaction rather than to a separate preview model.

### Appearance

A ViewProvider colours each plank by its material's optional appearance
field, falling back to a default. No custom 3D widgets in v1.

### Assembly compatibility

The container being an `App::Part` with a single `Placement` is enough for
v1 (move the unit in a room document) and for the FreeCAD 1.0 built-in
Assembly workbench later (insert via `App::Link`, add joints). No
assembly-specific code ships in v1.

## Material catalog

A document-level object (Python proxy over a plain data table, so the same
structure is what `shelving_core` consumes). Each entry: `id` (UUID),
`name`, `thickness` (required), and optional `nominal_label`,
`sheet_size`, `grain_default`, `appearance`. The workbench ships a small
default catalog seeded into a document on first unit creation. Editing an
entry touches every `ShelvingUnit` that references it, triggering reflow.

## Repository layout

```
shelving_core/            pure Python, no FreeCAD imports
  layout.py                 split-tree types + JSON (de)serialisation
  solver.py                 spacing solver
  expand.py                 carcass expansion -> PlankSpec list
  materials.py              catalog data model
  tests/                    pytest
freecad/shelving/         the workbench
  init_gui.py               workbench registration
  commands/                 create unit, edit layout, manage catalog
  objects/                  ShelvingUnit, Plank, MaterialCatalog proxies
  view/                     ViewProviders, the QGraphicsView editor
  vendor/shelving_core/   vendored copy of the core
  tests/                    freecadcmd smoke tests
package.xml                 Addon Manager metadata
LICENSE                     MIT
test.sh                     --fast / --full entry points
```

## Testing and CI

CI runs from the first milestone and covers both layers:

- **Fast tier** (`./test.sh --fast`): ruff, a type check, and pytest over
  `shelving_core`. No FreeCAD. Runs on every push.
- **Full tier** (`./test.sh --full`): a FreeCAD 1.0 environment (AppImage
  or conda) running `freecadcmd` smoke tests: create a unit, recompute,
  assert plank count and bounding boxes; edit a property, recompute,
  assert the reflow; edit a catalog thickness, recompute, assert
  dependent planks changed.

The core carries the load. Every geometric rule (solver distribution,
lap-order effects, over-constraint failure, serialisation round-trips) is
a core pytest. The FreeCAD tier checks that the adapter wires the core to
real objects and that reconciliation adds, updates, and removes the right
children.

## Open questions and risks

- **Promote-to-Body ordering.** Feeding a scripted base solid into a
  PartDesign Body (via `SubShapeBinder` or a scripted base feature)
  without recompute-order surprises is unproven here. v1 avoids it; the
  isolable box helper is the hedge.
- **Editor performance.** `QGraphicsView` redraw and full-model recompute
  on every drag step needs a check on a large unit; a debounce or a
  cheaper preview path may be needed.
- **FreeCAD 1.0 API drift.** Minor releases occasionally move scripted
  object and ViewProvider details. The full CI tier is the early-warning
  system.
- **Child recompute order.** `App::Part` children recompute needs to be
  ordered so planks rebuild after the container writes their specs;
  verify rather than assume.

## Implementation roadmap

The milestone breakdown and its live status live in
[`roadmap.md`](roadmap.md). Each milestone is self-contained and ends with
a concrete way to see it working in FreeCAD; milestones become `sh-XXX`
tasks through the normal pipeline.
