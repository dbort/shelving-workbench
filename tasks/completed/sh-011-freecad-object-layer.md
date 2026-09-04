---
id: sh-011
title: "FreeCAD object layer: Plank, box helper, test harness (M3, part 1)"
current_agent: user
current_phase: done
review_rejections: 1
---

# sh-011: FreeCAD object layer: Plank, box helper, test harness (M3, part 1)

## Summary
Stand up the FreeCAD side of the workbench below the `ShelvingUnit` container: an
isolable helper that turns a plank's size and corner into a `Part` solid, a
`Plank` `Part::FeaturePython` scripted object with generated `Label` and
read-only size reporting, an in-code default material catalog, and a headless
functional-test harness wired into `pixi run tests`. Adds `freecad-stubs` as a
type-check-only dependency and brings `freecad/shelving/` (minus the vendored
core) under `mypy --strict`. Records in `docs/freecadcmd-notes.md` that FreeCAD
1.0 does not call `Proxy.execute` on a recomputing `App::Part`, which sets
sh-012's container shape. Part 1 of 2 for milestone M3.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [x] User sign-off

## Sign-off addendum (user-directed, not a review rejection)
The branch reached `user_signoff` and cleared review plus the doc-hygiene pass.
During manual sign-off the user asked for the changes below; `review_rejections`
stays at 1. Some depart from the approved Must Have wording, which is left as the
record of what review saw.

Round A:
- The `freecad-stubs` comment in `pixi.toml` drops the before/after framing about
  mypy having been off.
- The scripted-object property Protocol moves into its own module,
  `freecad/shelving/objects/feature_types.py` (`PlankFeature`), which `plank.py`
  and `tools/freecad_object_smoke.py` both import. This clears the friction-log
  entry about `_PlankFeature` being reached by a cross-module private import and
  `_ProxyHolder` being re-declared in the smoke.

Round B:
- `freecad/shelving/catalog.py` is renamed to `default_catalog.py`.
- `plank_shape`'s parameters lose the `_mm` suffix (`size`, `origin`): the `Vec3`
  type already carries `_mm` on its fields. The `SizeMM` / `CornerMM` FreeCAD
  property names keep the marker: they hold a bare `FreeCAD.Vector`, which is not
  unit-tagged.
- The `App::Part` / `Proxy.execute` probe is removed from
  `tools/freecad_object_smoke.py` (the file keeps its label / catalog /
  `plank_shape` / recompute functional checks). sh-012's container decision is
  locked, and the finding is recorded in `docs/freecadcmd-notes.md`, which is
  rewritten to stand on its own without the probe.
- The friction-log entry that read "`App::Part` rejects a `Proxy` assignment, so
  the sh-011 probe pseudocode crashes as written" was removed at the user's
  request. The behavioral fact it captured now lives in
  `docs/freecadcmd-notes.md`, in the "App::Part does not call a Python
  Proxy.execute" section; the probe pseudocode it flagged is itself gone with the
  probe.
- `add_plank` in `freecad/shelving/objects/plank.py` gains a comment explaining
  why `Plank(obj)` is called for its constructor side effect and binds nothing:
  the proxy registers itself on the object.
- `README.md`'s `freecadcmd` test bullet is trimmed to the high-level summary.
- A friction-log entry records that `[tool.mypy] files` still enumerates each
  `tools/` / `tests/` script; collapsing to directories is deferred.

## Must Have

### `freecad/shelving/objects/geometry.py` (new)
- [x] `plank_shape(size_mm: Vec3, origin_mm: Vec3) -> Part.Shape`: the single
  place plank geometry is constructed. `Vec3` imported from
  `freecad.shelving.vendor.shelving_core.expand`. Body is
  `Part.makeBox(size_mm.x_mm, size_mm.y_mm, size_mm.z_mm, FreeCAD.Vector(origin_mm.x_mm, origin_mm.y_mm, origin_mm.z_mm))`.
- [x] Raises `ValueError` when any of `size_mm.x_mm / y_mm / z_mm <= 0` (message
  naming the offending axis and value).
- [x] Module docstring states the isolation rationale: this is the seam a later
  milestone feeds into a PartDesign Body base feature, so no other module calls
  `Part.makeBox` for a plank.
- [x] Imports `FreeCAD` and `Part` at module top. No import from
  `freecad.shelving.objects.plank` or any sibling that would cycle.

### `freecad/shelving/objects/labels.py` (new)
- [x] `generated_label(role: PlankRole, ordinal_for_role: int) -> str`. `PlankRole`
  imported from `freecad.shelving.vendor.shelving_core.expand`. Mapping:
  `BOTTOM -> "Bottom"`, `TOP -> "Top"`, `LEFT_SIDE -> "Left Side"`,
  `RIGHT_SIDE -> "Right Side"`, `SHELF -> f"Shelf {ordinal_for_role}"`,
  `DIVIDER -> f"Divider {ordinal_for_role}"`. Shell roles ignore
  `ordinal_for_role`.
- [x] `match` over `PlankRole` with no catch-all `case _` fallthrough that hides
  a new enum member (every member handled explicitly).
- [x] Imports nothing from `FreeCAD` / `Part` (kept import-light on purpose; the
  functional smoke exercises it without a running FreeCAD document).

### `freecad/shelving/objects/plank.py` (new)
- [x] `class Plank`: the `Proxy` for a `Part::FeaturePython` solid, one per
  `PlankSpec`.
- [x] `add_plank(doc: FreeCAD.Document, name: str = "Plank") -> FreeCAD.DocumentObject`:
  factory that does `doc.addObject("Part::FeaturePython", name)`, attaches
  `Plank(obj)`, and returns the object. Used by the container in sh-012 and by
  the functional smoke, so neither needs the GUI.
- [x] `Plank.__init__(self, obj)` adds these properties, all in the `"Shelving"`
  property group:
  - `NodeId` `App::PropertyString` — hidden, read-only after first set. The
    reconciliation match key: the owning `Divider.id` for a divider plank, the
    literal `f"{carcass.id}:{role.value}"` for a shell plank.
  - `Role` `App::PropertyString` — read-only. The `PlankRole` value string.
  - `Material` `App::PropertyString` — read-only. The `MaterialId` string from
    the spec (per-plank override that drives reflow is M4; here it is reporting
    only).
  - `SizeMM` `App::PropertyVector` — hidden. The plank extent
    `(x_mm, y_mm, z_mm)`.
  - `CornerMM` `App::PropertyVector` — hidden. The plank minimum corner in the
    carcass local frame.
  - `Dimensions` `App::PropertyString` — read-only. Recomputed each `execute`
    from `SizeMM` as `f"{x:g} x {y:g} x {z:g} mm"`.
- [x] `Plank.execute(self, obj)`: `obj.Shape = plank_shape(vec3(obj.SizeMM), vec3(obj.CornerMM))`
  where `vec3` adapts a `FreeCAD.Vector` to the core `Vec3`; then set
  `obj.Dimensions`. `obj.Placement` is left at identity in M3 (the unit's
  `App::Part.Placement` moves the whole assembly; per-plank `Placement`
  positioning is a later-milestone change the `plank_shape` seam isolates).
- [x] `Plank.__getstate__` / `__setstate__` (or the FreeCAD 1.0
  `dumps`/`loads`) return `None` / accept the proxy with no stored data — all
  state is on the object's properties.
- [x] No GUI import. `ViewProvider` is not added here (colour-by-material is M6;
  a headless `Part::FeaturePython` needs none, and GUI gives it a default).

### `freecad/shelving/catalog.py` (new)
- [x] `DEFAULT_CATALOG: Catalog` built from
  `freecad.shelving.vendor.shelving_core.materials` with at least these entries,
  in this order: `ply18` ("18 mm birch plywood", 18.0, "plywood", nominal
  `3/4"`); `ply12` ("12 mm birch plywood", 12.0, "plywood", nominal `1/2"`);
  `mdf19` ("19 mm MDF", 19.0, "mdf", nominal `3/4"`); `hardwood20` ("20 mm hard
  maple", 20.0, "solid wood").
- [x] `DEFAULT_MATERIAL_ID: MaterialId` = `ply18`.
- [x] `DEFAULT_CATALOG_IDS: list[str]` = the ids above in catalog order (sh-012
  feeds this to the `DefaultMaterial` enumeration property).
- [x] Module docstring notes this is a stopgap: M4 replaces the source of the
  catalog with the document-level catalog object and the "manage catalog"
  command.
- [x] Standard-library plus vendored-core imports only; no `FreeCAD` import.

### `freecad/shelving/init_gui.py` (bring under strict typing)
- [x] Fully annotate the module so `mypy --strict` passes over it (it enters the
  gate with the rest of `freecad/shelving/`). Behavior is unchanged: the
  `Gui = None` collapse for headless `freecadcmd`, the resource dir, the
  workbench class. No toolbar or command wiring yet (that is sh-012).

### Type-check tooling
- [x] Add `freecad-stubs` to `pixi.toml` `[pypi-dependencies]` (type-check only;
  it ships no runtime code). Regenerate the lock cleanly:
  `rm pixi.lock && pixi lock` so the editable self-install entry stays
  repo-relative and `tools/check_lock_paths.py` keeps passing. Commit the
  refreshed `pixi.lock`. The lock must resolve for both `linux-64` and
  `linux-aarch64`.
- [x] `pyproject.toml` `[tool.mypy]`: drop `exclude = ["freecad/"]`; add
  `"freecad/shelving/"` to `files`; add
  `exclude = ["^freecad/shelving/vendor/"]`. Add an override so the vendored
  copy is not analyzed twice under two module names:
  ```toml
  [[tool.mypy.overrides]]
  module = "freecad.shelving.vendor.*"
  follow_imports = "skip"
  ```
- [x] `mypy` (the bare `pixi run tests` invocation) passes with the new
  `freecad/shelving/` modules typed against `freecad-stubs`. Where a stub
  genuinely lacks a symbol, a narrowly-scoped `# type: ignore[code]` or a
  commented `Any` is acceptable per `CLAUDE.md` (untyped-boundary rule); no
  blanket `ignore_errors`.

### `tools/freecad_object_smoke.py` (new) — the functional harness
- [x] Runs under `freecadcmd tools/freecad_object_smoke.py`. Follows every
  headless convention in `docs/freecadcmd-notes.md`: the `sys.path` insert plus
  `freecad.__path__ = extend_path(...)` shim before importing `freecad.shelving`;
  a printed marker line as the only success signal (exit status is discarded).
- [x] Checks, with plain `assert` and a final `print("shelving object layer OK")`:
  - `generated_label` returns the exact strings above for every `PlankRole`,
    including `Shelf 2` / `Divider 3` for ordinals.
  - `DEFAULT_CATALOG` has the four entries in order; `DEFAULT_CATALOG["ply18"].thickness_mm == 18.0`;
    `DEFAULT_MATERIAL_ID == "ply18"`; `DEFAULT_CATALOG_IDS` matches.
  - `plank_shape(Vec3(700, 300, 18), Vec3(10, 0, 5))` yields a solid whose
    `BoundBox` is `(10,0,5)`-`(710,300,23)` within `1e-6`;
    `plank_shape(Vec3(0, 1, 1), Vec3(0,0,0))` raises `ValueError`.
  - create an in-memory document, `add_plank(doc)`, set `SizeMM = Vector(700,300,18)`,
    `CornerMM = Vector(10,0,5)`, `doc.recompute()`, assert the object's
    `Shape.BoundBox` matches the same box and `obj.Dimensions == "700 x 300 x 18 mm"`.
- [x] The `App::Part` / `Proxy.execute` probe (see PROBE below), as a permanent
  section of this script: it attaches a trivial `Proxy` with an `execute` that
  records a call onto a bare `doc.addObject("App::Part", ...)`, recomputes, and
  `assert`s the observed outcome against a hard-coded `EXPECTED_APART_EXECUTE`
  bool with a comment pointing at the new `docs/freecadcmd-notes.md` section. It
  also `print`s `APART_PROXY_EXECUTE: yes|no`. A future FreeCAD bump that flips
  the behavior then fails `pixi run tests` loudly.

### `tools/run-tests.sh`
- [x] After the existing `freecad_smoke.py` block, add one more linear block:
  capture `freecadcmd tools/freecad_object_smoke.py 2>&1`, print it, and
  `grep -q "shelving object layer OK"` or exit non-zero. Same shape as the
  existing smoke block; no loops, parsing, or logic beyond that (Shell-stays-
  simple obligation).

### Docs
- [x] `docs/freecadcmd-notes.md`: add a `## ` section recording the probe
  finding: whether FreeCAD 1.0 under `freecadcmd` calls `Proxy.execute` on a
  recomputing `App::Part`, the exact observed behavior, and one line on what it
  means for the `ShelvingUnit` container (drives sh-012's choice between
  `App::Part`-owns-`execute` and an `App::FeaturePython` driver child). Written
  from what the probe actually prints, not assumed.
- [x] `README.md` `## Tests`: extend the `freecadcmd` bullet to mention the new
  object-layer functional check alongside the import smoke.

### Verification
- [x] `pixi run tests` green end to end: `check_lock_paths`, ruff lint + format,
  `mypy --strict` (now including `freecad/shelving/`), `shellcheck`, the vendor
  drift check, pytest over `shelving_core` and `tests`, the workflow lint, the
  `freecadcmd` import smoke, and the new `freecadcmd` object-layer smoke.

### Scope guard
- [x] No `ShelvingUnit`, no container object, no `Layout` property, no `expand`
  call, no child reconciliation — all sh-012. No "Create Unit" command, no
  toolbar or menu wiring in `init_gui.py`. No `ViewProvider` / colour-by-
  material (M6). No layout editor (M5). No catalog document object / "manage
  catalog" command / per-plank material override reflow (M4). No `Grain`
  property. No back panel / back role. No preferences page (M6). No per-node
  depth. No change to `shelving_core/` or the vendored copy; no `vendor-core.sh`
  re-run (nothing in core changes).

## Frontier Advice

MILESTONE CONTEXT: M3 delivers the FreeCAD `ShelvingUnit`. This task (part 1) is
everything below the container: the plank object, the geometry seam, the default
catalog, the typing plumbing, and the headless functional harness. sh-012 (part
2, `blocked_by: [sh-011]`) adds the container and the "Create Unit" command on
top. Keep the split clean: nothing here reads `Layout` or calls `expand`.

HEADLESS CONVENTIONS ARE NON-NEGOTIABLE (`docs/freecadcmd-notes.md`): every new
`freecadcmd` script does the `sys.path` insert + `freecad.__path__ = extend_path(freecad.__path__, "freecad")`
refresh before `import freecad.shelving`; reports success only via a printed
marker line that `tools/run-tests.sh` greps (the process exit status is
discarded); and guards any `FreeCADGui` use behind `hasattr(Gui, "Workbench")`,
not just `except ImportError`.

CORE IS FROZEN INPUT: `shelving_core` and `freecad/shelving/vendor/shelving_core/`
are read-only here. Import `Vec3`, `PlankRole`, `PlankSpec`, `Catalog`,
`MaterialEntry`, `MaterialId` from the vendored path
(`freecad.shelving.vendor.shelving_core.*`), never from a top-level
`shelving_core` import inside `freecad/shelving/`. No `tools/vendor-core.sh` run
is needed because no core file changes.

STANDING OBLIGATIONS (`CLAUDE.md`):
- **Typed Python** now covers `freecad/shelving/`. `freecad-stubs` supplies the
  `FreeCAD` / `App` / `Part` / `FreeCADGui` stubs; the conda-forge FreeCAD ships
  none, which is why the gate was previously off. `mypy --strict` must pass.
  Permitted escape hatches, each with an inline reason: a scoped
  `# type: ignore[code]` where a stub omits a real symbol, and `Any` at a
  genuine FreeCAD-boundary erasure. Not permitted: `ignore_errors`, a blanket
  per-module `ignore_missing_imports` for FreeCAD, or leaving `freecad/shelving/`
  out of `files`.
- **Shell stays simple**: the only `tools/run-tests.sh` change is one more
  capture-print-grep block mirroring the existing smoke block. No new logic in
  bash; all assertions live in the Python smoke script.

NAMING (`CLAUDE.md` units-in-the-name): `SizeMM` / `CornerMM` vector properties,
`plank_shape(size_mm, origin_mm)`, every length local suffixed `_mm`. The
`Vec3` fields are already `x_mm` / `y_mm` / `z_mm`. FreeCAD property *names* that
this task does not introduce (none here) are out of frame; sh-012 handles the
`Width` / `Height` / `Depth` convention question.

NO `from __future__ import annotations` (repo-wide convention, see sh-003).

`freecad-stubs` RISK: if pixi cannot resolve it for `linux-aarch64`, do not
force it. Fall back to a hand-written minimal stub package under `typings/`
covering only the FreeCAD symbols this task touches, add `mypy_path = "typings"`
to `[tool.mypy]`, and log the swap in `.claude/docs/friction-log.md`. Either way
`tools/check_lock_paths.py` must stay green: regenerate the lock with
`rm pixi.lock && pixi lock`, never an incremental `pixi add` that writes an
absolute self-path.

PROBE (`App::Part` + `Proxy.execute`): the open question is whether FreeCAD 1.0,
under `freecadcmd`, invokes a Python `Proxy.execute` when an `App::Part` is
recomputed. Build the probe as: `part = doc.addObject("App::Part", "Probe")`,
`part.Proxy = _Recorder()` where `_Recorder.execute` sets a module-or-instance
flag, `part.touch()`, `doc.recompute()`, then read the flag. Run it, observe the
real result, then: (a) hard-code `EXPECTED_APART_EXECUTE` in the smoke to the
observed value with an `assert` and a comment, and (b) write the
`docs/freecadcmd-notes.md` section from the observation. sh-012's plan is
written to branch on that recorded finding, so it must be unambiguous and
committed on this branch.

MYPY DUPLICATE-MODULE HAZARD: the same core files are reachable as `shelving_core`
(already in `files`) and as `freecad.shelving.vendor.shelving_core`. Without the
`follow_imports = "skip"` override for `freecad.shelving.vendor.*`, mypy errors
with "duplicate module named 'shelving_core'". Add the override; do not solve it
by removing `shelving_core` from `files` or by renaming anything in the vendored
copy (that would break the drift check).

PLANK STATE MODEL: all persistent state is on the `Part::FeaturePython`
properties, so the `Proxy` serialises to nothing. Under FreeCAD 1.0 that is
`dumps(self) -> None` / `loads(self, state) -> None` (older `__getstate__` /
`__setstate__` names also still work); pick one pair, keep it minimal, and do
not stash Python objects on the proxy instance that would not survive a
save/reload.

Friction log: record any workaround per `CLAUDE.md` in
`.claude/docs/friction-log.md` in this session (a missing tool, a stub gap, a
FreeCAD API that behaved off-spec, a doc reverse-engineered).

## Execution Plan

- [x] **Step 1** (`pixi.toml`, `pixi.lock`, `pyproject.toml`): Add `freecad-stubs`
  to `[pypi-dependencies]`. `rm pixi.lock && pixi lock`; confirm the self-install
  entry is repo-relative and both platforms resolve. In `[tool.mypy]` drop the
  `freecad/` exclude, add `freecad/shelving/` to `files`, add the
  `^freecad/shelving/vendor/` exclude and the `follow_imports = "skip"` override
  for `freecad.shelving.vendor.*`. Run `python tools/check_lock_paths.py` and
  `mypy` (expect mypy to now fail only on the not-yet-typed `init_gui.py`, fixed
  in Step 5).

- [x] **Step 2** (`freecad/shelving/objects/__init__.py`,
  `freecad/shelving/objects/geometry.py`): New `objects` package. `plank_shape`
  per Must Have, with the `ValueError` guards and the isolation-rationale
  docstring. Imports `FreeCAD`, `Part`, and `Vec3` from the vendored core.

- [x] **Step 3** (`freecad/shelving/objects/labels.py`, `freecad/shelving/catalog.py`):
  `generated_label` with an exhaustive `match` over `PlankRole`. `DEFAULT_CATALOG`
  / `DEFAULT_MATERIAL_ID` / `DEFAULT_CATALOG_IDS` from the vendored `materials`
  module, with the M4-stopgap docstring. Neither module imports `FreeCAD`.

- [x] **Step 4** (`freecad/shelving/objects/plank.py`): `Plank` proxy and
  `add_plank` factory per Must Have: the six `"Shelving"`-group properties with
  the stated hidden/read-only flags, `execute` calling `plank_shape` and setting
  `Dimensions`, and the empty `dumps`/`loads`. No GUI import, no `ViewProvider`.

- [x] **Step 5** (`freecad/shelving/init_gui.py`): Add full type annotations so
  `mypy --strict` passes; behavior unchanged (headless `Gui = None` collapse,
  workbench class, no command wiring). Run `mypy`; it must now be green over all
  of `freecad/shelving/` except the vendored copy.

- [x] **Step 6** (`tools/freecad_object_smoke.py`): The functional harness per
  Must Have: the headless path shim, the `generated_label` / catalog /
  `plank_shape` / `Plank`-recompute assertions, the `App::Part` probe section
  with `EXPECTED_APART_EXECUTE`, and the `print("shelving object layer OK")`
  marker. Run it via `freecadcmd` directly and read the `APART_PROXY_EXECUTE`
  line.

- [x] **Step 7** (`tools/run-tests.sh`): Add the second capture-print-grep block
  for `tools/freecad_object_smoke.py` (marker `shelving object layer OK`),
  mirroring the existing smoke block.

- [x] **Step 8** (`docs/freecadcmd-notes.md`, `README.md`): Write the
  `App::Part` / `Proxy.execute` section from the observed probe result and its
  one-line consequence for sh-012. Extend the `README.md` `## Tests` `freecadcmd`
  bullet. Run `pixi run tests` and confirm the whole chain is green.
