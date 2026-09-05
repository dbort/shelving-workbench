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
| Elevation plane | Detected, not assumed: depth is the shallowest bounding-box axis, vertical is Z unless Z is the depth. Stored on the unit, overridable |
| Facing | Which end of the depth axis is the front. Inferred only from a back or a front panel, otherwise unknown and stored as an explicit choice. Never guessed from depth alignment |
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

Outstanding; they need a human at FreeCAD 1.0 with Woodworking installed.

10. Done. A stair-step unit from a live project was exported and now
    recognises; see the results below. It found the plane assumption, the
    snap tolerance, and the thickness corruption.
11. Outstanding. Run Woodworking's `getDimensions` on a unit the spike's
    apply wrote, and check the cut list is correct.
12. Outstanding. Export a `magicStart` cabinet from the GUI, to check the
    synthetic F0 fixture against a real one.

## Spike results

### Core: recognise from boxes

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

### FreeCAD: plain boxes in a document

Run with `freecadcmd spikes/plain_planks/freecad_spike.py`, which prints
`plain-planks freecad spike OK` on success. All four goals pass.

- **Dynamic properties survive a reload (goal 6).** Four
  `App::PropertyString` properties added to a plain `Part::Box` come back
  intact after a save, close, and reopen, with the shape valid. The saved
  `Document.xml` contains no `Proxy`, `FeaturePython`, or `PythonObject`
  entry, so the file needs nothing of ours installed to load. **This is
  the linchpin of the approach and it holds.**
- **The container walk feeds the recogniser (goal 7).** Both `App::Part`
  and `App::LinkGroup` export cleanly, and moving the container leaves
  the recognised tree unchanged while shifting the exported corners,
  because the walk composes container placements and the tree is measured
  against its own bounding rectangle. `getGlobalPlacement` is not usable
  here: a `LinkGroup` is not a geo-feature group, so the chain is composed
  by hand.
- **Apply matches by identity (goal 8).** Adding a shelf to a recognised
  tree updates the six existing boxes in place, creates exactly one, and
  deletes none; removing it deletes exactly that one. Every shell plank
  keeps its original document object. The result recognises again, so the
  edit cycle closes.
- **Cost is negligible (goal 9).** A 45-plank unit exports in 0.3 ms and
  recognises in 0.6 ms; apply plus a full document recompute is 9 ms.
  FreeCAD's own recompute dominates, and it is still far below an
  interactive threshold.

### Real geometry: a stair-step unit from a live project

The user exported a stair-step component built in the FreeCAD GUI with
Woodworking tools and fed it to the recogniser. It is kept as
`spikes/plain_planks/real_stair_step.boxes.json` and asserted by
`test_real_stair_step_unit_recognises`.

**It recognises, and the tree matches the geometry.** A top running the
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
  refused with a bogus overlap. Recognition now detects the plane, taking
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
the recogniser and the tests were both consistently wrong.

The depth *axis* is detectable, but its *sign* is not: nothing in a set of
boxes says which of the two faces a person stands at. The same elevation
read from the other side is mirrored, so every left and right swaps. This
changes no size, no topology, and no lap order, which is why it is easy to
miss and why it survives every structural test. It changes only what a
plank is called and which way the editor draws.

The tempting heuristic does not survive contact with the real unit. Its
shallow planks are flush with the **back** and set back three inches from
the **front**, the reverse of the usual "shelves flush at the front"
convention, so depth alignment is not evidence.

What is evidence, when it exists:

- a plank thin through the depth and lying **proud** of the other members
  is a door or a face frame, so that end is the front;
- one lying **within** the members is a back, so the front is the far end.

The `magicStart` cabinet has both and infers cleanly. Open shelving has
neither, which is the common case, and is simply undetermined.

Consequences for the design:

- **Facing is a stored property of the unit, not a derived value.** It
  belongs on the container beside the plane, set once and remembered.
- **Recognition must report it as unknown rather than guess.** The spike
  now carries `front_at_min` on the plane as an explicit `None` when
  undetermined, and `screen_right_sign` returns `None` with it, so any
  code that needs a left or a right has to handle not knowing.
- **The editor needs a "view from the other side" control**, and it is
  the natural place to set the property the first time.
- **Generated labels must not say left or right until facing is known.**
  Today's `generated_label` would produce a confidently mirrored name.

The unit also confirms two decisions already recorded: it is stepped at
the bottom rather than the top, which the outside leaf handles without
change, and it carries two stock thicknesses, which the closed-rectangle
converter would reject but the general model must not.

### Verdict

Every spike goal passes, real project geometry recognises correctly, and
nothing turned up that blocks the approach. The open questions are not
about feasibility:

1. **The name.** "Plain-planks" is a placeholder and should be settled
   before it reaches a module or type name.
2. **The general model.** The spike converts recognised trees back to
   today's implicit-shell `Carcass`, which is why a stepped outline and a
   through-shelf are refused at the conversion step even though recognise
   handles both. Adopting the approach means an explicit shell and the
   outside leaf in `shelving_core`, which is the bulk of the real work.
3. **Where the plane and the facing live.** Recognition detects the plane
   and sometimes the facing, but a `Carcass` has no field for either, and
   the editor, apply, and every generated label need both. They belong in
   the model next to the outside leaf, with facing stored rather than
   inferred.

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
