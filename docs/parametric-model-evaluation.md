# Parametric model evaluation

An evaluation of three ways for the workbench to hold and compute a shelving unit's
geometry, written before deciding whether to change the roadmap. Nothing
here is a decision of record; [`architecture.md`](architecture.md) stays
authoritative until a task updates it.

## The question

The design of record computes every number in Python: `ShelvingUnitDriver`
deserialises the split-tree, `shelving_core.solve` distributes space,
`shelving_core.expand` emits `PlankSpec`s, and `execute` writes sizes and
corners onto the plank children as plain values. FreeCAD sees only the
promoted `Width` / `Height` / `Depth` / `DefaultMaterial` on the driver and
the resulting solids. Everything between those is opaque to the document.

The alternative is to make the numbers first-class FreeCAD properties
joined by expressions, so that a user can bind a unit to the scene ("this
unit is the alcove width less 10 mm"), bind the scene to the unit ("the
countertop is the unit's top plank length"), and override any intermediate
value ("this opening is 300 mm, the rest share what is left") in the
property editor, the way any other parametric FreeCAD object works.

Three versions are worth separating. The first two keep a workbench-owned
model and differ in who does the arithmetic; the third drops the owned
model and treats plain FreeCAD solids as the source of truth.

### Version A: bindable inputs, readable outputs

Keep the Python solver. Promote every *driving* value to a writable
property on the driver (each `fixed` split rule's size, plus the existing
four scalars), and expose every *solved* value as a read-only property
(each opening's clear size on the driver; length, width, and thickness on
each plank). Expressions can drive the inputs and reference the outputs.
Intermediates are visible but not overridable, because the solver, not the
expression engine, computes them.

This is a small change to the current plan: one milestone that adds
per-node properties to the driver and per-plank reporting properties, and
a rule for the layout editor to treat expression-bound openings as locked.

### Version B: the expression generator

Every number in the model is an expression. Python owns the tree and the
object lifecycle; FreeCAD's expression engine owns evaluation.

The solver's arithmetic is closed-form, so this is possible. For one split
with parent span `S`, divider thicknesses `t_i`, fixed openings `f_j`, and
weights `w_k`, each driven opening is

    (S - sum(t_i) - sum(f_j)) * w_k / sum(w_k)

and positions are running sums of openings and thicknesses. Every term is a
property somewhere: `S` is the parent's solved opening, `t_i` is a catalog
entry's thickness, `f_j` is a user-set length, `w_k` is a user-set float.
The expression language has no loops, but the tree is known at generation
time, so each sum is written out term by term. Three `fill` shelves in a
bay generate expressions of the shape

    Opening_a  = (Bay3_Opening - 2 * Catalog.ply18_Thickness) * 1 / 3
    Shelf1_Z   = Bay3_Z + Opening_a

Each plank carries expressions for its own size and corner, and
`Plank.execute` builds a box from its own properties. The driver's
`execute` runs only on topology changes, to create and delete planks by
UUID and to (re)generate expressions; every other recompute flows through
the dependency graph without Python involvement beyond box construction.

### Version C: recognise plain solids, edit, write back

Source of truth is the set of plain solids themselves, in the manner of the
Woodworking workbench (`dprojects/Woodworking`). The workbench keeps no
model between edits. Three commands replace the driver:

- **Recognise** takes a selection (or a container) of axis-aligned boxes,
  classifies them into shell and interior planks, reads the lap order from
  which member runs through at each joint, infers the bays from the voids,
  and builds a split-tree. Anything outside a strict envelope is refused
  with a diagnosis that names the offending object.
- **Edit** is the 2.5D editor operating on the recognised tree.
- **Apply** writes the tree back as plain boxes: existing planks updated by
  identity, new ones created, removed ones deleted. With version B's
  generator, it also emits expressions so the result stays self-consistent
  when a parameter changes.

What Woodworking proves about the substrate, from its `MagicPanels` API
doc: panels are `Part::Box`, `PartDesign::Pad`, `Part::Cut`, `App::Link`,
and clones; sizes come from `Length` / `Width` / `Height` or from vertices
and the bounding box; orientation is a six-way axis classification from
geometry (`getDirection` returns `XY`, `YX`, `XZ`, and so on); its move and
resize tools write plain values, not expressions; and `magicGlue` is a
`SubShapeBinder` helper for sketches, not a panel-to-panel parametric
link. Woodworking never infers structure from an arrangement. Version C
builds on the substrate it proves and adds the recognition it lacks.

## What version B gains

- **Every intermediate is live and overridable.** Replacing
  `... * 1 / 3` with `300 mm` in the property editor is exactly the
  driving/driven distinction the solver models, expressed the way FreeCAD
  users already understand it. No custom UI is needed to express "this
  opening is fixed".
- **Binding works at every level in both directions**, not only at the
  levels the workbench chose to promote.
- **The catalog milestone (M4) collapses.** Once a catalog entry's
  thickness is a property, "edit a thickness and every dependent plank
  reflows" is the dependency graph doing its job.
- **The `App::Part` execute problem shrinks.** Planks depend on the driver
  and the catalog through expressions, so a dimension change never needs
  the reconcile pass; only a topology change does.
- **Undo, units, and recompute ordering are native.** Expression edits are
  already transactional, unit-aware, and ordered by the graph.

## What version B costs

- **Topology stays in Python regardless.** The number of children, the
  split orientation, the lap order, and which planks exist are structural.
  Expressions cannot create objects. Either version is a hybrid; the
  difference is who does the arithmetic.
- **Ownership of user overrides is the hard problem.** The generator runs
  on every topology change. If the user replaced a generated expression on
  an opening, a later split of an ancestor must not clobber it, and the
  override must be re-targeted if the property it referenced was
  regenerated. FreeCAD keeps no "user edited this" marker, so the driver
  has to record each expression it wrote and treat any mismatch as an
  override to preserve. This is the `Label` regeneration rule applied to
  roughly six expressions per plank plus one or two per opening; a
  twenty-plank unit carries around 150 user-touchable expressions.
- **Over-constraint becomes silent.** Expressions evaluate a negative
  opening without complaint. The "hard error, no stale geometry" decision
  survives only if a Python validation pass remains in the loop; the
  cheapest place is a check in the driver's `execute` that recomputes the
  solve in Python and raises, which means the Python solver does not go
  away.
- **Testability moves.** `shelving_core` stops being the thing that
  computes and becomes an oracle. That is workable, and a strong test
  shape: a `freecadcmd` test asserts the generated expressions evaluate to
  what `shelving_core.solve` returns for the same tree. But every geometric
  rule then has an implementation in two languages, and the vendored core
  no longer earns its place by being the only source of numbers.
- **The property panel gets noisy.** Grouping and hiding help; naming has
  to be UUID-stable because expressions reference properties by name and
  properties cannot be renamed.
- **The layout editor (M5) reads and writes differently.** It reads solved
  values back from properties, writes literal lengths when the user drags or
  types, and must treat an expression-bound opening as locked rather than
  overwrite the binding.

## What version C gains

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
- **Recognition is pure geometry.** It lives in `shelving_core` as an
  `infer` module taking `(size, corner)` boxes and returning a tree or a
  structured refusal, with the round-trip property `infer(expand(t))`
  reproduces `t` as the oracle test.
- **`StudWall` recognises the same way**: plates and a row of studs are a
  one-level tree.

## What version C costs

- **The tree is not unique.** Two continuous dividers crossing have no
  tree at all; four segments meeting at a point are ambiguous between H
  then V and V then H. Lap order resolves most cases (the continuous
  member belongs to the outer split), and strictness handles the rest:
  refuse, and name the plank that makes the arrangement unrecognisable.
- **Rules are lost.** Geometry cannot distinguish a 300 mm `fixed`
  opening from a `fill` that happened to solve to 300 mm. Three ways to
  recover them, in increasing cost:
  1. treat every opening as `fixed` on recognise, so nothing redistributes
     until the user changes a rule in the editor;
  2. store rule kind, node UUID, role, and material id as dynamic
     properties on the plain box (`addProperty` works on any
     `DocumentObject`, persists in the file, and needs no proxy to load);
  3. read rules from the expressions the generator wrote: a literal length
     is `fixed`, a share formula is `fill` or weighted. This is where
     version B's generator becomes version C's persistence.
  Option 2 is the sensible floor; option 3 falls out if B is adopted.
- **Expressions fight plain-value tools.** If apply emits expressions, a
  Woodworking resize writes a value that the next recompute overwrites.
  Either apply writes plain values only and the editor is the sole reflow
  mechanism, or bound planks are edited through the workbench's tools or
  the parameter object and other tools are for unbound planks.
- **Material is not inferable** beyond thickness, and thickness alone does
  not identify a catalog entry. Recognise reads the stored property when
  present and otherwise asks, or leaves the material unset.
- **Refusal is the user experience.** Every unsupported arrangement (a
  rotated plank, a gap at a joint, an overlap, a shelf that spans two bays,
  a non-box) must produce a diagnosis that points at geometry. A silent
  no-op or a generic error makes the tool feel broken.
- **Consistency is not maintained between edits.** A user can leave the
  boxes in any state; the model is only known to be consistent right
  after apply. This is the Woodworking model and its users accept it, but
  it is a different promise from the current design's "the 3D is always a
  projection of the model".
- **Identity across edits** must be stored (option 2 above) or
  reconstructed by position on every recognise. Stored is cheap and
  reliable; reconstruction is where labels and per-plank overrides would
  get lost.

## How the roadmap changes if version C is adopted

- The `Plank` `Part::FeaturePython` proxy and the driver's per-recompute
  `execute` are replaced by plain `Part::Box` objects carrying dynamic
  properties (`NodeId`, `Role`, `Rule`, `Material`) and by the recognise /
  edit / apply commands. The `App::Part` container and its `Placement`
  stay.
- `shelving_core` gains `infer.py` (boxes to tree, or a structured
  refusal) and its round-trip test against `expand`.
- M4 (catalog) is unchanged in shape; with B it also collapses as
  described above.
- M5 (editor) becomes the centre of the product: it is the only place the
  tree exists, so it must be able to open from a recognised selection,
  not only from a unit the workbench created.
- M8 and M9 (`StudWall`, openings) gain recognise rules for studs and
  headers; the on-centre spacing rule is recovered from stored properties
  or expressions, never from geometry.
- The "3D edits" and "Source of truth" decisions in `architecture.md`
  change: direct edits round-trip through recognise, and the boxes are the
  source of truth with the tree as a transient editing view.

## Spike goals for version C

A throwaway `freecadcmd` script, separate from the version B spike.

1. **Round trip.** For each sample tree in the core tests, `expand` it to
   boxes, feed the boxes to `infer`, and assert the tree comes back with
   identical topology, sizes, and lap order (rules excluded). This is a
   pure `shelving_core` test and should be written first.
2. **Ambiguity envelope.** Feed `infer` a 2 x 2 grid with a continuous
   vertical divider and segmented shelves (should resolve to V then H), the
   mirror case (H then V), and four segments meeting at a point (should
   refuse with a diagnosis naming the joint). Record the refusal messages
   and judge whether they would tell a user what to fix.
3. **Malformed input.** Feed a rotated plank, a 1 mm gap at a joint, an
   overlap, a shelf spanning two bays, and a cylinder. Each must refuse and
   name the object.
4. **Dynamic properties on plain boxes.** Add `NodeId`, `Role`, `Rule`,
   and `Material` string properties to a `Part::Box`, save, reload headless
   without the workbench on `sys.path`, and assert the properties and the
   shape survive with no warnings.
5. **Apply by identity.** Recognise a unit, split a bay in the tree, apply,
   and assert the untouched boxes are the same document objects (same
   `Name`), the new plank is a new object, and a removed plank is deleted.
6. **External edit then recognise.** Resize one shelf's `Length` by hand
   (the Woodworking path), recognise, and assert the tree reflects the new
   size and the lap order is unchanged. Then move the shelf 5 mm so it no
   longer meets its neighbours and assert recognise refuses.
7. **Expressions versus plain-value tools.** Apply with expressions (from
   the B spike), then set a plank's `Length` to a literal, recompute, and
   record which value wins. This decides the "expressions fight tools"
   cost above.
8. **Scale.** Recognise a forty-plank unit and time it. Recognition is
   pairwise face matching at worst, so this is expected to be trivial, but
   the number belongs in the record.

## Separate workbench, or features inside Woodworking?

If version C is adopted, the output is plain solids of the kind Woodworking
already operates on, which raises the question of contributing the work
upstream instead of shipping a workbench. The answer is a separate
workbench whose output follows Woodworking's conventions.

- **Governance.** Woodworking describes itself as "my environment for
  woodworking" and is 99% single-author (504 of 509 commits at the time of
  writing), with six external pull requests in its history, all small. Its
  pull-request terms require changes to be "consistent with the current
  vision for the add-on and not introduce drastic changes to interface or
  user experience", and state that contributed code "will be improved or
  removed by others". The repository has no CI, no type checking, and a
  single sample directory under `Tests`. A modal split-tree editor is a
  drastic interface change, and this repository's checks (pure core,
  pytest, `mypy --strict`, headless `freecadcmd` smoke) would not survive
  there.
- **Different kind of tool.** Woodworking is a toolbox of stateless
  operations on the current selection. Version C keeps a model, transient
  or not: a tree with driving and driven rules, over-constraint semantics,
  and identity and rule metadata stored on the boxes. The editor is the
  product. The nearest overlap, `magicStart`, is a one-shot wizard that
  emits a cabinet from dimensions; the delta that justifies this project is
  the part that does not fit that vision. The core's second consumer,
  `StudWall`, is outside woodworking entirely.
- **Interop needs no merge.** If the emitted boxes follow Woodworking's
  conventions (axis-aligned `Part::Box`, thickness along one axis,
  `Length` / `Width` / `Height` carrying their usual meaning), then its cut
  list (`getDimensions`), dowel, edge-banding, and export tools work on a
  unit unchanged, and recognise works on panels made with its tools. Two
  workbenches over one substrate is the normal FreeCAD arrangement.

Consequences for version C: Woodworking's box conventions become an
explicit design constraint, and the spike gains a goal:

9. **Woodworking consumes the output.** With the Woodworking workbench
   installed, run `getDimensions` on an applied unit and check the cut
   list is correct; run `magicResizer` on one plank and confirm recognise
   still accepts the unit (spike goal 6 covers the manual form of this).

## If version C is adopted: reset in place, not a fresh repository

Adopting version C invalidates the object layer and most of the design of
record, and a repository that describes a superseded design as current
steers implementers (human or agent) toward its shapes. The remedy is a
deliberate reset in this repository, not a new one.

What survives unchanged: the core (`layout`, `solver`, `expand`,
`materials`, and their tests) is version C's apply path and the oracle
for recognise; the check harness, pixi environment, CI, action-pin
verifier, workflow lint, vendoring script, pipeline and skills,
`package.xml`, workbench registration, and the `freecadcmd` notes are all
still true. A fresh repository re-derives these and gains nothing, and
"reference the old repository" copies the old shapes without the tests
that constrain them.

What misleads: `freecad/shelving/objects/` (the `Plank` proxy, the driver
and its reconcile, the feature-type protocols), the object smoke test, and
above all the prose in `architecture.md` and `roadmap.md`, which
implementers read first and treat as the contract.

The reset, done as one task after the core round-trip spike passes:

1. Rewrite `architecture.md` as the version C design of record, as a new
   document rather than an edit, with one line stating that anything in
   history before the reset commit is superseded.
2. Delete the dead object layer and its smoke test in the same change.
   Nothing is kept "for reference" or marked deprecated; git history is
   the reference.
3. Re-milestone `roadmap.md`. Completed task files stay in
   `tasks/completed/` untouched.
4. Update the agent memory index in the same session.

A fresh repository is the right call only if the tree itself goes away
(so the core has no consumer) or the project's identity changes (a name
covering framing as well as shelving). Version C keeps the tree as the
editor's model, and a rename can happen in place, so neither applies.

## How B and C compose

B answers "how does the model stay consistent when a parameter changes";
C answers "what is the model, and who else may touch it". They are
independent axes:

| | Python solver writes values | Expressions written by generator |
|---|---|---|
| **Workbench-owned objects** | Design of record (M3 as built) | Version B |
| **Plain solids, recognised** | Version C, plain (editor is the only reflow) | Version C + B (recognise reads rules from expressions) |

The bottom-right cell is the most FreeCAD-native and the most work. The
bottom-left cell is the smallest step that captures C's interop and
adoption gains, and it leaves the door open to the bottom-right later
because apply already owns the write-back. If C is adopted at all, start
bottom-left with dynamic properties for identity and rules, and add the
generator when the B spike has settled the override-ownership rule.

## What version A costs relative to B

- Intermediates are visible but not overridable; "fix this opening" still
  needs a UI gesture (editor or property flip) rather than an expression
  edit.
- M4 keeps its reflow plumbing in Python.
- A future promote-to-Body path gets no help from the graph.

Version A is the safer increment. Version B is the one where a shelving
unit behaves like any other parametric FreeCAD object instead of a black
box with four knobs.

## Recommendation

Prefer version B, gated on the spike below, for the consistency axis. On
the ownership axis, version C's round-trip test (its spike goal 1) is a
pure-Python day of work and decides whether recognition is tractable at
all; run it alongside the B spike before choosing a cell in the table
above. The override-ownership rule for B and the ambiguity envelope for C
are the two facts that decide the roadmap.

## Spike goals for version B

A throwaway `freecadcmd` script (not a task; no pipeline) that answers the
following. Each goal has a concrete pass condition so the outcome is a
list of facts, not an impression.

1. **Generation works end to end.** From a two-level tree (root split into
   two bays, one bay split into three `fill` openings), generate driver
   properties, plank objects, and expressions, recompute, and assert every
   plank's size and corner matches `shelving_core.expand` for the same
   tree and catalog to within 1e-6 mm.
2. **Inbound binding.** Bind the driver's `Width` to a property on an
   unrelated object, change that property, recompute, assert planks
   follow. Confirms the dependency graph crosses the `App::Part` boundary
   as expected.
3. **Outbound binding.** Bind an unrelated object's property to a plank's
   solved length, change the unit's width, recompute, assert the unrelated
   object follows.
4. **Override survives regeneration.** Replace one generated opening
   expression with a literal, then split a different bay (a topology
   change that reruns the generator). Assert the literal is still in place
   and every other expression is regenerated. This needs the
   generated-expression record and the mismatch rule; the spike should
   implement the simplest version and report how much code it took.
5. **Override re-targeting.** Replace a generated expression with one that
   references a sibling opening, then remove that sibling's split. Record
   what FreeCAD does with the dangling reference (error state, silent
   zero, or exception) and whether the driver can detect it before
   recompute.
6. **Over-constraint.** Set two fixed openings whose sum exceeds the
   parent span. Record what the expression engine produces (negative
   length, error, clamp) and confirm a Python check in the driver's
   `execute` can raise before any plank recomputes with a bad value.
7. **Catalog thickness as a property.** Put one catalog entry's thickness
   on a document object and reference it from the generated expressions.
   Change it, recompute, assert every plank using it changes. Confirms M4
   collapses.
8. **Recompute order and cycles.** Confirm that, after a topology change,
   the driver's `execute` runs before the planks' (creating planks and
   setting expressions mid-recompute has been fragile elsewhere; see
   [`freecadcmd-notes.md`](freecadcmd-notes.md)). Deliberately create a
   cycle between two openings and record how FreeCAD reports it.
9. **Save and reload.** Save the document, reload it headless, recompute,
   and assert nothing changed. Expressions on `Part::FeaturePython`
   properties must round-trip.
10. **Scale.** Generate a unit with roughly forty planks, time a full
    recompute after a `Width` change, and count the expressions. The number
    is a data point for the property-panel-noise cost, and the time is a
    data point for the M5 live-preview concern.

## How the roadmap changes if the version B spike passes

- **M4 (material catalog)** shrinks to the catalog object with thickness
  as a property; the reflow plumbing disappears.
- A new **M4.5 (expression generator)** replaces the driver's per-recompute
  reconcile with topology-only reconcile plus expression generation, adds
  the generated-expression record and override rule, and adds the
  oracle-equivalence test.
- **M5 (layout editor)** reads solved values from properties, writes
  literal lengths, and locks expression-bound openings. It ships after
  M4.5 so there is one write path.
- **`architecture.md`** changes its "Source of truth" and "Parameter
  storage" decisions: the tree remains the source of truth for topology
  and rule *kinds*; numeric values live on properties, with the tree JSON
  holding only what the generator needs to re-emit them.
- **`shelving_core`** keeps `layout`, `solve`, and `expand` as the
  reference implementation and gains an `emit` module that produces the
  expression text, so expression generation is unit-testable without
  FreeCAD.

If the spike fails on goal 4 or 5 (override ownership cannot be made
reliable) the fallback is version A, which needs none of the above beyond
one added milestone.
