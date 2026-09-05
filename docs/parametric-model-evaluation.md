# Plain-planks evaluation

An evaluation of the plain-planks approach, written before deciding whether
to replace the design of record with it. Nothing here is a decision of
record; [`architecture.md`](architecture.md) stays authoritative until a
task rewrites it. "Plain-planks" is a working name for the approach and is
to be revisited before it names any Python module or type.

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

- **Recognise** takes a container the user chooses, classifies the
  axis-aligned boxes inside it into planks, reads the lap order at each
  joint from which member runs through, infers the bays from the enclosed
  voids, and builds a split-tree. Anything outside a strict envelope is
  refused with a diagnosis that names the offending object.
- **Edit** is the 2.5D editor operating on the recognised tree.
- **Apply** writes the tree back as plain boxes into the same container:
  existing planks updated by identity, new ones created, removed ones
  deleted.

The design of record computes every number in Python and writes it onto
`Part::FeaturePython` planks that only this workbench understands. Under
plain-planks the same core does the same arithmetic, but its input comes
from geometry and its output is geometry.

## What Woodworking establishes

Read from a local clone of the repository. These are facts about the
substrate the approach builds on, and constraints on the recognise
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
  front of the back panel. Recognise must tolerate a small clearance at a
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
  opening the editor is a supported path, because recognise starts from
  whatever is there.
- **Recognition is pure geometry.** It lives in `shelving_core` taking
  `(size, corner)` boxes and returning a tree or a structured refusal,
  with the round-trip property that recognising `expand`'s output
  reproduces the tree as the oracle test.
- **`StudWall` recognises the same way**: plates and a row of studs are a
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
  not identify a catalog entry. Recognise reads the stored property when
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
  Reconstructing it by position on every recognise would lose labels and
  per-plank overrides.

## Decisions

Made in the planning interview on 2026-09-04. Each is provisional until
the spike confirms it is workable.

| Question | Decision |
|---|---|
| Unit scope | One container the user chooses (`App::Part`, `App::LinkGroup`, or a plain group). Every box inside it is a plank of one unit; apply writes into the same container; the container gives the unit its `Placement` |
| Plank types | `Part::Box` only, identity rotation, for the first envelope. `Pad` and rotated placements are later |
| Outline | Rectilinear, one plane. Represented as the bounding rectangle's split-tree with leaves that may be marked *outside*: no planks, no opening. The shell follows the boundary between inside and outside |
| Non-tree layouts | A pinwheel or any partition that is not a tree is refused, naming the planks that form the cycle |
| Clearance at a joint | A gap up to a tolerance (default 3 mm) is a joint; the gap is stored per plank end and apply reproduces it. Larger gaps refuse |
| Per-plank depth | Recognise records each plank's depth and Y offset as per-node overrides; apply reproduces them; unit depth is the default for new planks |
| Back and front panels | Y-thin planks are set aside from the bay partition and reported; back-panel semantics arrive with M7 |
| Rule recovery | Stored rule metadata on a box is authoritative. Without it, sibling openings equal within tolerance become `fill` and the rest become `fixed` |
| Identity and metadata | Dynamic properties on the plain box: node id, role, rule, material, clearances. They persist without the workbench installed |
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

Recognise therefore works on a cell grid: every plank edge coordinate is
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

Throwaway code under `spikes/plain_planks/`, not a task and not shipped.
Nothing imports it. `ruff check .` covers it because it sweeps the tree,
but `pixi run tests` does not run its tests or type-check it; run those
with `pixi run -- python -m pytest spikes` and `pixi run -- mypy --strict
spikes`.

### Core spike: recognise from boxes, no FreeCAD

`recognise.py` takes a list of axis-aligned boxes and returns a cut tree
or a `RecogniseError` naming the objects. `test_recognise.py` covers:

1. **Round trip.** For sample trees (a single leaf, three `fill` shelves,
   a vertical split with a nested horizontal one, mixed thicknesses),
   `expand` to boxes, recognise, convert back to a `Carcass`, `expand`
   again, and assert the plank set matches to 1e-6 mm.
2. **Woodworking cabinet.** The `magicStart` F0 shape (floor, sides, top,
   back, front, one shelf inset 1 mm each side and shallower than the
   sides) recognises as one bay split by one shelf, with the back and
   front set aside and the clearances recorded.
3. **Stair-step.** Three columns of decreasing height with a continuous
   floor and left side, step tops, and risers recognise into a tree with
   outside leaves, and the lap order matches the geometry.
4. **Refusals.** A pinwheel, an overlap, a gap wider than the clearance, a
   square-section plank, and a shell with a leak each refuse and name the
   objects.
5. **Rule recovery.** Equal siblings become `fill`; a differing sibling
   stays `fixed`; resizing the recognised carcass redistributes only the
   `fill` openings.

### FreeCAD spike: plain boxes in a document

A `freecadcmd` script, written after the core spike passes, covering:

6. **Dynamic properties on plain boxes.** Add node id, role, rule, and
   material string properties to a `Part::Box`, save, reload headless
   without the workbench on `sys.path`, and assert the properties and the
   shape survive with no warnings.
7. **Export from a container.** Walk an `App::Part` and an
   `App::LinkGroup`, read each box's global placement, refuse a rotated
   box, and produce the input the core recogniser takes.
8. **Apply by identity.** Recognise a unit, split a bay in the tree,
   apply, and assert the untouched boxes are the same document objects,
   the new plank is new, and a removed plank is deleted.
9. **Scale.** Recognise a forty-plank unit and time it.

### GUI checks

With FreeCAD 1.0 and Woodworking installed:

10. Run `spikes/plain_planks/export_boxes.py` as a macro on a `magicStart`
    cabinet and on the stair-step unit, modelled as plain boxes. The
    exported JSON is the recogniser's real-world input.
11. After apply exists: run Woodworking's `getDimensions` on an applied
    unit and check the cut list; resize one plank with `magicResizer` and
    confirm recognise still accepts the unit.

## Core spike results

Run on 2026-09-04 against `spikes/plain_planks/recognise.py`; fifteen
tests pass, `ruff` and `mypy --strict` are clean, and `pixi run tests`
stays green. **Recognition is tractable.** The recogniser is about 500
lines and every planned case works.

What the spike settled:

1. **Round trip holds.** For a single leaf, four `fill` shelves, a nested
   vertical-then-horizontal tree with mixed materials, and unequal fixed
   shelves, recognising `expand`'s boxes and expanding the recovered
   carcass reproduces every plank to 1e-6 mm and the same tree shape. It
   also holds at 3 x 4, 6 x 10, and 8 x 14 grids.
2. **The Woodworking cabinet recognises.** The `magicStart` F0 shape
   yields floor and top as the outer cuts, the two sides inside them, and
   the shelf with its 1 mm clearance recorded at each end. Back and front
   are set aside as Y-thin panels.
3. **The stair-step recognises.** Three columns of decreasing height give
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
- **A shelf that runs through the sides has no home in today's
  `Carcass`.** Recognise handles it (it is simply an outer cut with three
  or more members), but `expand` always makes the top and bottom
  continuous, so the converter refuses it. This is the per-joint lap
  override the schema reserves, and the general model needs it.
- **Unit depth comes from the elevation members, not the bounding box.**
  A Woodworking cabinet's 400 mm depth is an 18 mm front panel plus a
  382 mm carcass. Recognise reports the members' depth and the front
  offset separately, and both are needed to write the unit back.

Performance is a non-issue: recognising 115 planks takes 1.7 ms, and the
cost grows roughly with plank count times grid cells.

| Planks | Recognise | Convert |
|---|---|---|
| 15 | 0.2 ms | 0.08 ms |
| 35 | 0.3 ms | 0.15 ms |
| 63 | 0.7 ms | 0.26 ms |
| 115 | 1.7 ms | 0.47 ms |

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
  this project is the part that does not fit that vision. The core's
  second consumer, `StudWall`, is outside woodworking entirely.
- **Interop needs no merge.** Emitted boxes follow Woodworking's
  conventions, so its cut list, dowel, edge-banding, and export tools work
  on a unit unchanged, and recognise works on panels made with its tools.

## If adopted: reset in place, not a fresh repository

Adopting plain-planks invalidates the object layer and most of the design
of record, and a repository that describes a superseded design as current
steers implementers (human or agent) toward its shapes. The remedy is a
deliberate reset in this repository, not a new one.

What survives unchanged: the core (`layout`, `solver`, `expand`,
`materials`, and their tests) is the apply path and the oracle for
recognise; the check harness, pixi environment, CI, action-pin verifier,
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

## How the roadmap changes if adopted

- The `Plank` `Part::FeaturePython` proxy and the driver's per-recompute
  `execute` are replaced by plain `Part::Box` objects carrying dynamic
  properties and by the recognise / edit / apply commands. The container
  and its `Placement` stay; `App::LinkGroup` is accepted alongside
  `App::Part`.
- `shelving_core` gains recognition (boxes to tree, or a structured
  refusal) with its round-trip test against `expand`, the outside leaf in
  the schema, per-plank depth and clearance overrides, and a shell rule in
  `expand` that follows the inside/outside boundary.
- M4 (catalog) keeps its shape; material identity is a stored property
  on each box.
- M5 (editor) becomes the centre of the product: it is the only place the
  tree exists, so it opens from a recognised container, not only from a
  unit the workbench created.
- M8 and M9 (`StudWall`, openings) gain recognise rules for studs and
  headers; the on-centre spacing rule is recovered from stored properties,
  never from geometry.
- The "3D edits" and "Source of truth" decisions in `architecture.md`
  change: direct edits round-trip through recognise, and the boxes are the
  source of truth with the tree as a transient editing view.
