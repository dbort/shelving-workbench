---
id: sh-012
title: "ShelvingUnit container + Create Unit command (M3, part 2)"
current_agent: user
current_phase: user_signoff
review_rejections: 1
blocked_by: [sh-011]
---

# sh-012: ShelvingUnit container + Create Unit command (M3, part 2)

## Summary
Add the `ShelvingUnit` scripted object with promoted `Width` / `Height` /
`Depth` / `DefaultMaterial` properties and a hidden `Layout` JSON string, plus a
"Create Unit" toolbar command that seeds a single-`Leaf` unit. On recompute,
`execute` parses `Layout` into a `Carcass`, overrides the four scalars from the
properties, calls `shelving_core.expand` against the in-code default catalog,
rewrites `Layout` from the reconciled carcass when it changed, and reconciles
child `Plank` objects by node id (create / update / remove). Extends the headless
harness with the end-to-end reflow and over-constraint assertions. Part 2 of 2
for milestone M3; builds on sh-011.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [ ] User sign-off

## Sign-off defect — planks do not render in the FreeCAD GUI
Found by the user in manual testing on macOS. `review_rejections` stays at 1;
this is a sign-off demotion, not a review-loop round.

**Symptom.** After **Create Unit**: the tree shows `ShelvingUnit` /
`ShelvingUnitDriver` / four `Plank` objects, each `ViewObject.Visibility == True`
with a real `Shape` (correct bounding boxes), but nothing draws in 3D,
`ViewObject.isVisible()` is `False`, and spacebar does not toggle it.

**Root cause (isolated at the console).** In this FreeCAD 1.0.0 build a
`Part::FeaturePython` with a set `Shape` and no ViewProvider proxy does not
render: bare or with the `Plank` proxy, `isVisible()` is stuck `False`, and
`ViewObject.show()` / `touch()` + `recompute()` do not change it. A plain
`Part::Feature` and a `Part::Box` in the same document render fine. Independent
of whether the plank is created inside `execute` or at top level. sh-011's
"a headless `Part::FeaturePython` needs no `ViewProvider`, and the GUI supplies
a default" is false for this build; the merged `Plank` object has never
actually displayed.

**Fix directive.**
- Give `Plank` a `ViewProvider` that renders its solid and is selectable /
  visibility-toggleable. Scope is "it draws"; colour-by-material stays M6.
  Try the minimal proxy first (`attach` storing `vobj.Object`,
  `getDisplayModes -> []`, `getDefaultDisplayMode -> "Flat Lines"`, no-op
  `updateData` / `onChanged`, `dumps` / `loads -> None`), which lets the C++
  `PartGui::ViewProviderPython` base keep drawing the `Shape`. If that still
  does not render in the GUI, force the C++ Part view provider at creation
  (`Document.addObject(..., viewType=...)`).
- Attach it only in a GUI: `add_plank` (or a GUI-only helper it calls) sets the
  VP proxy when `obj.ViewObject is not None`. Under `freecadcmd`
  `obj.ViewObject` is `None`, so this is a no-op there. Keep every `FreeCADGui`
  import out of the headless path; `shelving_core/tests/test_no_freecad.py` and
  the two `freecadcmd` smokes must stay green.
- Check whether the `ShelvingUnitDriver` (`App::FeaturePython`, no shape) needs
  a VP to avoid a broken tree entry; the `ShelvingUnit` `App::Part` already
  renders (C++ VP), leave it.
- `docs/manual-qa.md` case 2's "the 3D view shows a closed box …" is the
  acceptance check. `freecadcmd` has no `ViewObject`, so `pixi run tests`
  cannot assert rendering. Ship the fix plus a short console macro
  (`doc = App.ActiveDocument; assert all(o.ViewObject.isVisible() for o in ...
  if o.TypeId == "Part::FeaturePython")`) for the user to run once in the GUI,
  and note in `manual-qa.md` how to run it.
- No `shelving_core/` change. No colour / grain / catalog scope creep.

### Implementation notes
- `objects/shelving_unit.py` imports the layout / solver / expand / materials
  surface from the top-level `shelving_core.*` rather than
  `freecad.shelving.vendor.shelving_core.*`: the byte-identical vendored
  `expand.py` / `solver.py` bind their classes from `shelving_core` (bare name),
  so a carcass built from the vendored `layout` module fails every
  `isinstance(bay, Split)` check inside `expand` and drops all dividers with no
  error. `plank.py` / `labels.py` keep the vendored import (standalone helpers
  only). Logged in `.claude/docs/friction-log.md`; a departure from the
  "import from the vendored path" line in `## Frontier Advice`.
- The driver's `execute` recomputes each touched or created plank child
  directly (`obj.recompute()`), because a plank added mid recompute is not in
  the document's current work list and would otherwise stay shapeless until the
  next recompute.
- Step 7's `docs/manual-qa.md` `## M3` GUI cases cannot run headless; they are
  pending human sign-off.
- Review round 1 fixes (all in `tools/freecad_object_smoke.py` plus a docs note
  and one `execute` wrap): F1 — `_in_error_state` now rests on `"Invalid" in
  driver.State or not driver.isValid()`, the real signal a raised proxy
  `execute` leaves under `freecadcmd` (`State == ['Touched', 'Invalid']`,
  `isValid()` false, recompute does not re-raise); recorded in
  `docs/freecadcmd-notes.md` § "A proxy `execute` that raises marks the object
  `Invalid`". F2 — `_check_unit_end_to_end` now collapses the 6-plank relayout
  back to a single `Leaf` before the over-constraint step and asserts the count
  returns to 4, the two shelf `NodeId`s and their objects are gone from the
  document, and the four shell planks kept their `Name`s. N4 — `Carcass.from_json`
  in `execute` gets the same `RuntimeError` translation as `expand`. N5 / N6 —
  comments added for the `driver.Width = 900` reset and the cross-identity
  vendored-import block.
- Sign-off addition (user-directed, not a review finding): `docs/manual-qa.md`
  gains a "Loading the workbench from this checkout" top-level section with the
  `Mod` symlink steps for Linux and macOS. The M3 prerequisite line points at
  it. Docs only.
- Sign-off defect fix (planks did not render): `PlankViewProvider` added to
  `objects/plank.py`, a minimal proxy (`attach` stores `vobj.Object`,
  `getDisplayModes -> []`, `getDefaultDisplayMode -> "Flat Lines"`, no-op
  `updateData` / `onChanged`, `getIcon` / `dumps` / `loads -> None`) that lets
  the C++ `PartGui::ViewProviderPython` base draw the `Shape`. The class imports
  no `FreeCADGui` symbol (FreeCAD injects `vobj`), so `plank.py` stays safe on
  the headless import path. `add_plank` binds it only when `obj.ViewObject is not
  None`; under `freecadcmd` that is `None`, so the headless path is byte-for-byte
  unchanged and both smokes stay green. `objects/feature_types.py` gains a
  `ViewObjectHost` Protocol and a `ViewObject` field on `PlankFeature` so the
  guard type-checks. The `ShelvingUnitDriver` is left without a VP: the sign-off
  report confirms it already shows correctly in the tree and it carries no
  `Shape`, so there is nothing for a VP to fix. `pixi run tests` cannot assert
  rendering (`freecadcmd` has no `ViewObject`); `docs/manual-qa.md` case 2 gains
  a Python-console macro that asserts every `Part::FeaturePython` child reports
  `ViewObject.isVisible()`, to be run once in the GUI for sign-off.

## Must Have

### Container pattern — `App::Part` plus a driver child
sh-011's probe settled this. `docs/freecadcmd-notes.md` § "`App::Part` does not
call a Python `Proxy.execute`" records that a bare `App::Part` under FreeCAD 1.0
cannot hold a `Proxy` at all and never dispatches `execute` on recompute.

- [x] The unit is an `App::Part` (kept for `Placement` / `App::Link` / Assembly
  compatibility) that contains one `App::FeaturePython` driver child, named
  `ShelvingUnitDriver`. The driver carries the promoted properties, `Layout`,
  and `execute`, and parents `Plank` objects into the `App::Part`.
- [x] "The unit object" in the Must Have items below means this driver: it owns
  the properties and `execute`. "The container" or "the `App::Part`" means the
  parent that holds the `Placement` and the plank children.
- [x] `docs/architecture.md`'s `### `ShelvingUnit` container` section still puts
  the properties and `execute` on the `App::Part` itself; it is amended to the
  driver-child split (see Docs below).

### `freecad/shelving/objects/shelving_unit.py` (new)
- [x] `class ShelvingUnit`: the `Proxy` for the unit object.
- [x] `make_shelving_unit(doc: FreeCAD.Document) -> FreeCAD.DocumentObject`:
  factory used by both the command and the functional smoke (so the smoke needs
  no GUI). It creates the `App::Part` and its `ShelvingUnitDriver` child,
  attaches the driver proxy, adds the properties, seeds the starter layout
  (below), sets the promoted properties to match, and returns the `App::Part`
  (the driver is reachable as its child).
- [x] Promoted properties, group `"Shelving"`:
  - `Width`, `Height`, `Depth` — `App::PropertyLength`. Read `.Value` for
    millimetres in `execute`.
  - `DefaultMaterial` — `App::PropertyEnumeration`, enum list =
    `freecad.shelving.default_catalog.DEFAULT_CATALOG_IDS`.
  - `Layout` — `App::PropertyString`, hidden. The full serialised `Carcass`
    JSON (`Carcass.to_json()`), the hand-edit surface for tree structure.
- [x] Starter layout (what `make_shelving_unit` seeds): a `Carcass` with
  `width_mm=900.0`, `height_mm=1800.0`, `depth_mm=300.0`,
  `default_material=DEFAULT_MATERIAL_ID`, `root=Leaf()`. Serialise into `Layout`;
  set `Width`/`Height`/`Depth` to the same millimetres and `DefaultMaterial` to
  `"ply18"`.
- [x] `ShelvingUnit.execute(self, obj)` algorithm, in this order:
  1. `carcass = Carcass.from_json(obj.Layout)`.
  2. Rebuild `carcass` with `width_mm=obj.Width.Value`, `height_mm=obj.Height.Value`,
     `depth_mm=obj.Depth.Value`, `default_material=MaterialId(obj.DefaultMaterial)`,
     keeping `carcass.id` and `carcass.root` unchanged (the property values win
     over the JSON's four scalars).
  3. `specs = expand(carcass, DEFAULT_CATALOG)` — called before any child is
     touched. On `LayoutSolveError`, `KeyError`, or `ValueError`, raise
     `RuntimeError(str(err))` (or a message wrapping it) and mutate nothing: no
     child add/update/remove, no `Layout` write. FreeCAD then marks the unit
     touched-with-error and shows no fresh geometry.
  4. `new_layout = <reconciled carcass>.to_json()`; if `new_layout != obj.Layout`,
     set `obj.Layout = new_layout` (the dirty guard: an unconditional write
     re-touches the object and loops the recompute).
  5. Reconcile children (below).
- [x] Child reconciliation:
  - Index existing plank children by `NodeId`: planks the driver created,
    parented in the `App::Part`. "Plank child" = a child with a `NodeId`
    property, so the driver itself is never one.
  - Walk `specs` in list order. For a spec whose `node_id` matches an existing
    plank: set `SizeMM`, `CornerMM`, `Material`, `Role`; `touch()` it. For a new
    `node_id`: `add_plank(doc)`, set `NodeId`, the geometry properties,
    `Role`, `Material`, and `Label = generated_label(role, ordinal_for_role)`;
    parent it into the `App::Part`.
  - `ordinal_for_role`: 1-based count of planks of that role encountered so far
    in `specs` order (shell roles pass 1 and `generated_label` ignores it).
  - After the walk, remove every plank child whose `NodeId` is not in the new
    spec id set: `doc.removeObject(child.Name)`.
  - `Label` is set only at creation. Later executes never write `Label`, so a
    user rename sticks and a plank that changes role keeps its old generated
    name until it is removed and re-created.
- [x] `dumps` / `loads` return `None` / accept with no stored data (state lives
  on properties), matching `Plank`.
- [~] Import `Carcass`, `Leaf`, `MaterialId`; `expand`, `PlankRole`,
  `LayoutSolveError` — taken from the **top-level** `shelving_core.*`, not the
  vendored path this bullet names, so they share class identity with the
  `isinstance` checks inside `expand` / `solve` (see `### Implementation notes`
  and the friction log). `Vec3` is unused by this module and not imported.
  `DEFAULT_CATALOG` etc. from `freecad.shelving.default_catalog`; `add_plank` /
  `generated_label` from `freecad.shelving.objects.*`; `PlankFeature` and the
  new `ShelvingUnitFeature` (below) from
  `freecad.shelving.objects.feature_types`.

### `freecad/shelving/objects/feature_types.py` (extend)
- [x] Add a `ShelvingUnitFeature` `Protocol` for the driver's scripted-object
  surface, following the existing `PlankFeature` shape (names and types match
  the `addProperty` calls in `ShelvingUnit.__init__`): `Proxy: object`, `Width`
  / `Height` / `Depth` (the FreeCAD quantity type exposing `.Value: float`),
  `DefaultMaterial: str`, `Layout: str`, `addProperty`, `touch`, the child-list
  / `addObject` used to parent planks, and any state the smoke reads (`State` /
  `isValid`).
- [x] `shelving_unit.py` casts `doc.addObject("App::FeaturePython", ...)` to
  `ShelvingUnitFeature` and `add_plank(doc)` and any existing plank children to
  `PlankFeature` before touching their scripted properties, the same way
  `tools/freecad_object_smoke.py` already casts. `mypy --strict` over
  `freecad/shelving/` stays green with no new blanket `type: ignore`.
- [x] Update the module docstring: it currently says `PlankFeature` alone
  supplies the typed view.

### `freecad/shelving/commands/create_unit.py` (new)
- [x] `freecad/shelving/commands/__init__.py` plus `create_unit.py`.
- [x] `class CreateUnitCommand`: `GetResources` returns `MenuText = "Create Unit"`,
  a `ToolTip`, and `Pixmap` = the existing `resources/shelving.svg` path.
  `IsActive` returns `bool(FreeCAD.ActiveDocument)`. `Activated` wraps
  `openTransaction("Create Shelving Unit")` /
  `make_shelving_unit(FreeCAD.ActiveDocument)` / `ActiveDocument.recompute()` /
  `commitTransaction`.
- [x] `Gui.addCommand("Shelving_CreateUnit", CreateUnitCommand())`, guarded so
  the module imports cleanly headless (no top-level `FreeCADGui` attribute
  access that fails under the `freecadcmd` stub).

### `freecad/shelving/init_gui.py`
- [x] `Initialize` registers the command into a `"Shelving"` toolbar and a
  `"Shelving"` menu (`self.appendToolbar` / `self.appendMenu` with
  `["Shelving_CreateUnit"]`). Import the command module inside `Initialize`
  (deferred), so a headless `import freecad.shelving.init_gui` still does not
  touch GUI-only code. The `Gui = None` collapse from sh-011 stays intact.

### `tools/freecad_object_smoke.py` (extend) — end-to-end checks
- [x] Add a section, keeping sh-011's object-layer checks, that:
  - `make_shelving_unit(doc)`, `doc.recompute()`; assert exactly 4 plank
    children (children carrying a `NodeId`, so the `ShelvingUnitDriver` is
    excluded); their `Role` set is `{bottom, top, left_side, right_side}`; the
    union of their `Shape.BoundBox` is `(0,0,0)`-`(900,300,1800)` within `1e-6`.
  - assert each shell plank's `SizeMM` / `CornerMM` against the carcass lap rule
    with `t = DEFAULT_CATALOG["ply18"].thickness_mm` (bottom `900 x 300 x t` at
    `(0,0,0)`; top at `(0,0,1800 - t)`; left `t x 300 x (1800 - 2t)` at
    `(0,0,t)`; right at `(900 - t, 0, t)`).
  - set `unit.Width = 1000`, `doc.recompute()`; assert the bbox X extent is
    `1000`, the right-side plank `CornerMM.x == 1000 - t`, and
    `json.loads(unit.Layout)["carcass"]["width_mm"] == 1000`.
  - set `unit.Layout` to a `Carcass` with one `HORIZONTAL` split of two
    `Fixed` shelves (built in the script via `Carcass(...).to_json()`, reusing
    `unit`'s current `id` so shell node ids are stable), `doc.recompute()`;
    assert 6 plank children, two with `Role == "shelf"`, each shelf
    `SizeMM ≈ (900 - 2t, 300, t)`.
  - over-constraint: set `unit.Layout` to a split whose `Fixed` sizes exceed the
    interior span, `doc.recompute()`; assert the unit is in an error state
    (`"Error" in unit.State` or `unit.isValid() is False` or the recompute
    raised), the plank-child count is unchanged from the previous good state (no
    stale extra planks), and `unit.Layout` still holds the previous good JSON
    (not rewritten).
  - keep the final `print("shelving object layer OK")` marker (rename the marker
    only if `tools/run-tests.sh` is updated to match).

### `docs/manual-qa.md` (new) — human-run test-case catalog
- [x] Create `docs/manual-qa.md`: a living catalog of manual QA checks a human
  runs in the FreeCAD GUI, since some behavior (property-editor reflow, toolbar
  wiring, tree presentation) has no headless assertion yet. Human-facing prose,
  swept by `doc-hygiene`.
- [x] Structure: a short intro stating the doc's purpose and that each case
  should migrate into an automated `pixi run tests` check whenever a headless
  path becomes possible (cross-reference `tools/freecad_object_smoke.py`); then
  cases grouped by milestone / feature. Each case is a numbered set of steps
  with an explicit expected result, written so someone who did not build the
  feature can follow it.
- [x] Seed it with an `## M3 — `ShelvingUnit`` group covering: activate the
  Shelving workbench and confirm the toolbar/menu show "Create Unit"; run
  "Create Unit" and confirm one unit with four planks named `Bottom` / `Top` /
  `Left Side` / `Right Side`; change `Width`, then `Height`, then `Depth` in the
  property editor and confirm the planks reflow each time; change
  `DefaultMaterial` and confirm the shell planks re-thickness; hand-edit
  `Layout` to add a `HORIZONTAL` two-shelf split and confirm two `Shelf n`
  planks appear; rename a plank's `Label`, trigger a recompute, and confirm the
  rename sticks; set an over-constrained `Layout` and confirm the unit shows a
  recompute error with no stale geometry.

### Docs
- [x] Amend `docs/architecture.md` `### `ShelvingUnit` container` to describe the
  `App::Part` + `ShelvingUnitDriver` child split: the driver owns the promoted
  properties, `Layout`, and `execute`; the `App::Part` keeps the single
  `Placement` and the plank children. Note why (FreeCAD 1.0 does not run
  `Proxy.execute` on a recomputing `App::Part`; cross-reference the
  `docs/freecadcmd-notes.md` section). No other restyling.
- [x] `docs/architecture.md` `## Testing and CI`: change "From M2 the
  `freecadcmd` step runs full smoke tests" to "As of M3 …" and trim the example
  list to what M3 actually asserts (create a unit, recompute, assert plank count
  and bounding boxes; edit a property, recompute, assert the reflow). The
  catalog-thickness-reflow example stays described as arriving with M4.

### Verification
- [x] `pixi run tests` green end to end, including the extended
  `freecadcmd` object-layer smoke.
- [ ] Manual: run the `## M3` cases in the new `docs/manual-qa.md` in the FreeCAD
  GUI and record the outcome in this task file for sign-off.

### Scope guard
- [x] No layout editor / `QGraphicsView` / task panel (M5). No catalog document
  object, "manage catalog" command, or per-plank `Material` override that drives
  reflow (M4) — `Material` stays read-only reporting. No `ViewProvider` /
  colour-by-material / generated `Label` restyling beyond the create-time
  default (M6). No preferences page (M6). No `Grain`. No back panel / back role.
  No per-node depth override. No change to `shelving_core/` or the vendored copy;
  no `vendor-core.sh` re-run. No second branch — resume on `sh-012`.

## Frontier Advice

DEPENDS ON sh-011 (`blocked_by: [sh-011]`): by the time this runs,
`freecad/shelving/objects/geometry.py` (`plank_shape`), `objects/labels.py`
(`generated_label`), `objects/plank.py` (`Plank`, `add_plank`),
`objects/feature_types.py` (`PlankFeature`), and
`freecad/shelving/default_catalog.py` (`DEFAULT_CATALOG`, `DEFAULT_MATERIAL_ID`,
`DEFAULT_CATALOG_IDS`) all exist; `freecad/shelving/` is under `mypy --strict`
via `freecad-stubs`; `tools/freecad_object_smoke.py` and its second
`tools/run-tests.sh` block exist; and `docs/freecadcmd-notes.md` records that a
bare `App::Part` takes no `Proxy` and never runs `execute`, so the container
needs an `App::FeaturePython` driver child. This task adds the container, the
command, the toolbar wiring, and the end-to-end assertions on top. Do not
re-touch the sh-011 modules except to wire them together.

CONTAINER PATTERN IS SETTLED: the `docs/freecadcmd-notes.md` finding rules out a
bare `App::Part` proxy, so the container is the `App::Part` plus a
`ShelvingUnitDriver` `App::FeaturePython` child. Do not re-litigate it or try to
attach a `Proxy` to the `App::Part` directly. `make_shelving_unit` builds both
objects; `execute` and the reconciliation run on the driver.

HEADLESS CONVENTIONS (`docs/freecadcmd-notes.md`): the smoke keeps the
`sys.path` + `extend_path` shim and the printed-marker success signal.
`create_unit.py` and the `Initialize` toolbar wiring must not break a headless
`import freecad.shelving.init_gui` — defer the command import into `Initialize`
and guard `Gui.addCommand`. The functional smoke calls `make_shelving_unit`
directly; it never invokes the GUI command (there is no `Gui` under
`freecadcmd`).

`execute` DIRTY GUARD IS LOAD-BEARING: writing `obj.Layout` unconditionally
inside `execute` re-touches the object and FreeCAD recomputes again, looping.
Only assign when the serialised string actually differs. Likewise do not write
the promoted properties from inside `execute` (they are the inputs).

ERROR PATH: call `expand` before mutating any child. On failure re-raise as
`RuntimeError` and leave every child and `Layout` exactly as they were, so the
previous good geometry stays on screen and FreeCAD's own error state is the only
signal. Do not delete children "to be safe" — a half-cleared unit is the stale
state the design forbids.

RECONCILIATION MATCHES sh-010's node_id CONTRACT: shell planks carry
`f"{carcass.id}:{role.value}"` (stable as long as `Layout` round-trips
`carcass.id`); divider planks carry `Divider.id`. `expand` already emits
`BOTTOM, TOP, LEFT_SIDE, RIGHT_SIDE` then dividers in pre-order. Preserve that
order when assigning `ordinal_for_role`.

STANDING OBLIGATIONS (`CLAUDE.md`):
- **Typed Python**: `freecad/shelving/` is under `mypy --strict` (set up in
  sh-011). Scripted-object property surfaces are declared as a `Protocol` in
  `objects/feature_types.py` and `cast` onto each `doc.addObject(...)` return,
  the way `PlankFeature` already is; add `ShelvingUnitFeature` there for the
  driver rather than scattering `Any`. A scoped `# type: ignore[code]` is
  allowed only at a real stub gap. `App::PropertyEnumeration` round-trips as
  `str`; `App::PropertyLength` exposes `.Value` as `float`.
- **Units in the name**: `SizeMM` / `CornerMM` stay as sh-011 defined them;
  length locals suffixed `_mm`. EXPLICIT OPT-OUT for the promoted properties:
  `Width`, `Height`, `Depth` keep those exact names with no `_mm` suffix,
  because they are FreeCAD `App::PropertyLength` quantity properties surfaced in
  the property editor under the FreeCAD unit schema, and `docs/architecture.md`
  specifies them by those names ("promoted scalars: `Width`, `Height`, `Depth`,
  `DefaultMaterial`"). `execute` reads `.Value` into `width_mm` / `height_mm` /
  `depth_mm` locals, which do carry the suffix.
- **Shell stays simple**: no new bash logic; `tools/run-tests.sh` at most gets
  its existing second-block marker string adjusted if the smoke's marker is
  renamed.

NO `from __future__ import annotations` (repo-wide convention, see sh-003).

CORE IS FROZEN INPUT: import everything layout/solver/expand/materials from
`freecad.shelving.vendor.shelving_core.*`. No `shelving_core/` edit, no
`tools/vendor-core.sh` run.

Friction log: record any workaround per `CLAUDE.md` in
`.claude/docs/friction-log.md` in this session, especially anything about
`App::Part` recompute ordering or child parenting that the
`docs/freecadcmd-notes.md` finding did not already cover.

## Execution Plan

- [x] **Step 1** (`docs/freecadcmd-notes.md` — read only): Read the `App::Part` /
  `Proxy.execute` section for the exact behavior the driver-child container
  works around.

- [x] **Step 2** (`freecad/shelving/objects/feature_types.py`,
  `freecad/shelving/objects/shelving_unit.py`): Add the `ShelvingUnitFeature`
  Protocol to `feature_types.py` and update its module docstring. Then the
  `ShelvingUnit` proxy and `make_shelving_unit` factory (the `App::Part` plus a
  `ShelvingUnitDriver` child): the promoted properties, the seeded
  single-`Leaf` starter layout, the five-step `execute` (dirty guard,
  pre-mutation `expand`), and the child reconciliation (index by `NodeId`,
  create/update/remove, create-time `Label` only), with `PlankFeature` /
  `ShelvingUnitFeature` casts on the `addObject` returns. Empty `dumps`/`loads`.

- [x] **Step 3** (`freecad/shelving/commands/__init__.py`,
  `freecad/shelving/commands/create_unit.py`): `CreateUnitCommand` with
  `GetResources` / `IsActive` / `Activated` per Must Have, and a headless-safe
  `Gui.addCommand`.

- [x] **Step 4** (`freecad/shelving/init_gui.py`): Wire `Shelving_CreateUnit`
  into a `"Shelving"` toolbar and menu in `Initialize`, with the command import
  deferred into `Initialize`. Keep the headless `Gui = None` path working. Run
  `mypy` and a headless `freecadcmd -c "import freecad.shelving.init_gui"` sanity
  check.

- [x] **Step 5** (`tools/freecad_object_smoke.py`): Add the end-to-end section —
  create, recompute, 4-plank + bbox assertions; lap-rule size checks; `Width`
  reflow + `Layout` rewrite; a `HORIZONTAL` two-`Fixed`-shelf relayout to 6
  planks; the over-constraint error-state check. Keep sh-011's checks and the
  marker. Run via `freecadcmd`.

- [x] **Step 6** (`docs/manual-qa.md`): Create the manual QA catalog per Must
  Have, seeded with the `## M3 — `ShelvingUnit`` case group.

- [x] **Step 7** (`docs/architecture.md`): Amend the `### `ShelvingUnit`
  container` section for the `App::Part` + `ShelvingUnitDriver` split. Update the
  `## Testing and CI` "From M2" wording to "As of M3" and trim the example list
  to M3's actual assertions. Run `pixi run tests` and confirm the whole chain is
  green; run the `docs/manual-qa.md` `## M3` cases in the GUI and record the
  outcome in this file for sign-off.
