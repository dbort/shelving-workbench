---
id: sh-012
title: "ShelvingUnit container + Create Unit command (M3, part 2)"
current_agent: implementer
current_phase: implementation
review_rejections: 0
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
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have

### Container pattern — read the probe finding first
- [ ] Open `docs/freecadcmd-notes.md` and read the `App::Part` / `Proxy.execute`
  section sh-011 wrote. It states whether FreeCAD 1.0 under `freecadcmd` runs a
  Python `Proxy.execute` on a recomputing `App::Part`.
- [ ] **If yes (Pattern A):** the `ShelvingUnit` proxy is attached directly to a
  `doc.addObject("App::Part", ...)`; the promoted properties and `execute` live
  on that `App::Part`. This matches `docs/architecture.md` as written; no doc
  amendment.
- [ ] **If no (Pattern B):** the unit is an `App::Part` (kept for `Placement` /
  `App::Link` / Assembly compatibility) that contains one
  `App::FeaturePython` driver child, named `ShelvingUnitDriver`, which carries
  the promoted properties, `Layout`, and `execute`; the driver parents `Plank`
  objects into the `App::Part`. Amend `docs/architecture.md` (see Docs below).
- [ ] Every other Must-Have item below is written against "the unit object" —
  the `App::Part` in Pattern A, the driver in Pattern B. The choice changes only
  which object owns the properties and `execute`, not the algorithm.

### `freecad/shelving/objects/shelving_unit.py` (new)
- [ ] `class ShelvingUnit`: the `Proxy` for the unit object.
- [ ] `make_shelving_unit(doc: FreeCAD.Document) -> FreeCAD.DocumentObject`:
  factory used by both the command and the functional smoke (so the smoke needs
  no GUI). It creates the object(s) per the chosen pattern, attaches the proxy,
  adds the properties, seeds the starter layout (below), sets the promoted
  properties to match, and returns the unit object (the `App::Part` in both
  patterns; in Pattern B the driver is reachable as its child).
- [ ] Promoted properties, group `"Shelving"`:
  - `Width`, `Height`, `Depth` — `App::PropertyLength`. Read `.Value` for
    millimetres in `execute`.
  - `DefaultMaterial` — `App::PropertyEnumeration`, enum list =
    `freecad.shelving.default_catalog.DEFAULT_CATALOG_IDS`.
  - `Layout` — `App::PropertyString`, hidden. The full serialised `Carcass`
    JSON (`Carcass.to_json()`), the hand-edit surface for tree structure.
- [ ] Starter layout (what `make_shelving_unit` seeds): a `Carcass` with
  `width_mm=900.0`, `height_mm=1800.0`, `depth_mm=300.0`,
  `default_material=DEFAULT_MATERIAL_ID`, `root=Leaf()`. Serialise into `Layout`;
  set `Width`/`Height`/`Depth` to the same millimetres and `DefaultMaterial` to
  `"ply18"`.
- [ ] `ShelvingUnit.execute(self, obj)` algorithm, in this order:
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
- [ ] Child reconciliation:
  - Index existing plank children by `NodeId` (children of the `App::Part` in
    Pattern A; children the driver created, parented in the `App::Part`, in
    Pattern B). "Plank child" = a child with a `NodeId` property.
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
- [ ] `dumps` / `loads` return `None` / accept with no stored data (state lives
  on properties), matching `Plank`.
- [ ] Import `Carcass`, `Leaf`, `MaterialId` from
  `freecad.shelving.vendor.shelving_core.layout` / `.materials`; `expand`,
  `PlankRole`, `Vec3` from `.expand`; `LayoutSolveError` from `.solver`.
  `DEFAULT_CATALOG` etc. from `freecad.shelving.default_catalog`; `add_plank` /
  `generated_label` from `freecad.shelving.objects.*`.

### `freecad/shelving/commands/create_unit.py` (new)
- [ ] `freecad/shelving/commands/__init__.py` plus `create_unit.py`.
- [ ] `class CreateUnitCommand`: `GetResources` returns `MenuText = "Create Unit"`,
  a `ToolTip`, and `Pixmap` = the existing `resources/shelving.svg` path.
  `IsActive` returns `bool(FreeCAD.ActiveDocument)`. `Activated` wraps
  `openTransaction("Create Shelving Unit")` /
  `make_shelving_unit(FreeCAD.ActiveDocument)` / `ActiveDocument.recompute()` /
  `commitTransaction`.
- [ ] `Gui.addCommand("Shelving_CreateUnit", CreateUnitCommand())`, guarded so
  the module imports cleanly headless (no top-level `FreeCADGui` attribute
  access that fails under the `freecadcmd` stub).

### `freecad/shelving/init_gui.py`
- [ ] `Initialize` registers the command into a `"Shelving"` toolbar and a
  `"Shelving"` menu (`self.appendToolbar` / `self.appendMenu` with
  `["Shelving_CreateUnit"]`). Import the command module inside `Initialize`
  (deferred), so a headless `import freecad.shelving.init_gui` still does not
  touch GUI-only code. The `Gui = None` collapse from sh-011 stays intact.

### `tools/freecad_object_smoke.py` (extend) — end-to-end checks
- [ ] Add a section, keeping sh-011's checks and the `App::Part` probe, that:
  - `make_shelving_unit(doc)`, `doc.recompute()`; assert exactly 4 plank
    children; their `Role` set is `{bottom, top, left_side, right_side}`; the
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
- [ ] Create `docs/manual-qa.md`: a living catalog of manual QA checks a human
  runs in the FreeCAD GUI, since some behavior (property-editor reflow, toolbar
  wiring, tree presentation) has no headless assertion yet. Human-facing prose,
  swept by `doc-hygiene`.
- [ ] Structure: a short intro stating the doc's purpose and that each case
  should migrate into an automated `pixi run tests` check whenever a headless
  path becomes possible (cross-reference `tools/freecad_object_smoke.py`); then
  cases grouped by milestone / feature. Each case is a numbered set of steps
  with an explicit expected result, written so someone who did not build the
  feature can follow it.
- [ ] Seed it with an `## M3 — `ShelvingUnit`` group covering: activate the
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
- [ ] Pattern B only: amend `docs/architecture.md` `### `ShelvingUnit` container`
  to describe the `App::Part` + `ShelvingUnitDriver` child split — the driver
  owns the promoted properties, `Layout`, and `execute`; the `App::Part` keeps
  the single `Placement` and the plank children. Note why (FreeCAD 1.0 does not
  run `Proxy.execute` on a recomputing `App::Part`; cross-reference the
  `docs/freecadcmd-notes.md` section). No other restyling.
- [ ] `docs/architecture.md` `## Testing and CI`: change "From M2 the
  `freecadcmd` step runs full smoke tests" to "As of M3 …" and trim the example
  list to what M3 actually asserts (create a unit, recompute, assert plank count
  and bounding boxes; edit a property, recompute, assert the reflow). The
  catalog-thickness-reflow example stays described as arriving with M4.

### Verification
- [ ] `pixi run tests` green end to end, including the extended
  `freecadcmd` object-layer smoke.
- [ ] Manual: run the `## M3` cases in the new `docs/manual-qa.md` in the FreeCAD
  GUI and record the outcome in this task file for sign-off.

### Scope guard
- [ ] No layout editor / `QGraphicsView` / task panel (M5). No catalog document
  object, "manage catalog" command, or per-plank `Material` override that drives
  reflow (M4) — `Material` stays read-only reporting. No `ViewProvider` /
  colour-by-material / generated `Label` restyling beyond the create-time
  default (M6). No preferences page (M6). No `Grain`. No back panel / back role.
  No per-node depth override. No change to `shelving_core/` or the vendored copy;
  no `vendor-core.sh` re-run. No second branch — resume on `sh-012`.

## Frontier Advice

DEPENDS ON sh-011 (`blocked_by: [sh-011]`): by the time this runs,
`freecad/shelving/objects/geometry.py` (`plank_shape`), `objects/labels.py`
(`generated_label`), `objects/plank.py` (`Plank`, `add_plank`), and
`freecad/shelving/default_catalog.py` (`DEFAULT_CATALOG`, `DEFAULT_MATERIAL_ID`,
`DEFAULT_CATALOG_IDS`) all exist; `freecad/shelving/` is under `mypy --strict`
via `freecad-stubs`; `tools/freecad_object_smoke.py` and its second
`tools/run-tests.sh` block exist; and `docs/freecadcmd-notes.md` records the
`App::Part` / `Proxy.execute` finding. This task adds the container, the command,
the toolbar wiring, and the end-to-end assertions on top. Do not re-touch the
sh-011 modules except to wire them together.

CONTAINER PATTERN IS DECIDED BY DATA, NOT PREFERENCE: read the
`docs/freecadcmd-notes.md` section and follow Pattern A or B as it dictates. Do
not spend a rejection cycle re-litigating it. The `make_shelving_unit` factory
is the seam that absorbs the difference; keep `execute` and reconciliation
pattern-agnostic.

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
  sh-011). New modules are fully typed against `freecad-stubs`; a scoped
  `# type: ignore[code]` or a commented `Any` is allowed only at a real stub
  gap. `App::PropertyEnumeration` round-trips as `str`; `App::PropertyLength`
  exposes `.Value` as `float` — annotate accordingly.
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
`App::Part` recompute ordering or child parenting that the probe did not already
cover.

## Execution Plan

- [ ] **Step 1** (`docs/freecadcmd-notes.md` — read only): Read the `App::Part` /
  `Proxy.execute` section from sh-011 and fix Pattern A or B for the rest of the
  task.

- [ ] **Step 2** (`freecad/shelving/objects/shelving_unit.py`): `ShelvingUnit`
  proxy and `make_shelving_unit` factory per the chosen pattern: the promoted
  properties, the seeded single-`Leaf` starter layout, the five-step `execute`
  (with the dirty guard and the pre-mutation `expand`), and the child
  reconciliation (index by `NodeId`, create/update/remove, create-time `Label`
  only). Empty `dumps`/`loads`.

- [ ] **Step 3** (`freecad/shelving/commands/__init__.py`,
  `freecad/shelving/commands/create_unit.py`): `CreateUnitCommand` with
  `GetResources` / `IsActive` / `Activated` per Must Have, and a headless-safe
  `Gui.addCommand`.

- [ ] **Step 4** (`freecad/shelving/init_gui.py`): Wire `Shelving_CreateUnit`
  into a `"Shelving"` toolbar and menu in `Initialize`, with the command import
  deferred into `Initialize`. Keep the headless `Gui = None` path working. Run
  `mypy` and a headless `freecadcmd -c "import freecad.shelving.init_gui"` sanity
  check.

- [ ] **Step 5** (`tools/freecad_object_smoke.py`): Add the end-to-end section —
  create, recompute, 4-plank + bbox assertions; lap-rule size checks; `Width`
  reflow + `Layout` rewrite; a `HORIZONTAL` two-`Fixed`-shelf relayout to 6
  planks; the over-constraint error-state check. Keep sh-011's checks, the probe,
  and the marker. Run via `freecadcmd`.

- [ ] **Step 6** (`docs/manual-qa.md`): Create the manual QA catalog per Must
  Have, seeded with the `## M3 — `ShelvingUnit`` case group.

- [ ] **Step 7** (`docs/architecture.md`): Pattern B only — amend the
  `ShelvingUnit` container section for the driver-child split. Both patterns —
  update the `## Testing and CI` "From M2" wording to "As of M3" and trim the
  example list to M3's actual assertions. Run `pixi run tests` and confirm the
  whole chain is green; run the `docs/manual-qa.md` `## M3` cases in the GUI and
  record the outcome in this file for sign-off.
