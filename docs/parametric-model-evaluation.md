# Parametric model evaluation

An evaluation of two ways for the workbench to compute a shelving unit's
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

Two versions of the alternative are worth separating, because they differ
by an order of magnitude in scope.

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

Prefer version B, gated on the spike below. The override-ownership rule is
the single factor that decides whether B is pleasant or a trap, and it can
be tested in a day without touching the roadmap.

## Spike goals

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

## How the roadmap changes if the spike passes

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
