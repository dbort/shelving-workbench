---
id: sh-009
title: "Carcass expansion + material catalog (M2)"
current_agent: implementer
current_phase: planning
review_rejections: 0
---

# sh-009: Carcass expansion + material catalog (M2)

## Summary
Add the two remaining pure-Python core modules: `shelving_core.materials`, a
catalog data model (id / name / actual thickness / material type, plus an
optional nominal-thickness label) with JSON round-trip and a published schema,
and `shelving_core.expand`, which solves a `Carcass` split-tree and emits one
`PlankSpec` (role, size, placement, material) per physical plank: the two sides,
top, bottom, and every divider. Material now drives panel thickness, so the M1
solver is reworked to take the catalog; the demo script gains a plank table and
a total-volume line, and the README gains a glossary of the carcass and
woodworking vocabulary. No FreeCAD, no 3D solids, no back panel.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have

### `shelving_core/materials.py`
- [ ] `MaterialId = NewType("MaterialId", str)`. `MATERIALS_SCHEMA_VERSION: int = 1`.
- [ ] `@dataclass(frozen=True) MaterialEntry` with fields `id: MaterialId`, `name: str`, `thickness_mm: float`, `material_type: str`, `nominal_thickness: str | None = None`. `__post_init__` raises `ValueError` on: empty `id`, empty `name`, empty `material_type`, `thickness_mm <= 0`.
- [ ] `@dataclass(frozen=True) Catalog` wrapping `entries: Mapping[MaterialId, MaterialEntry]`. `__getitem__(self, mid: MaterialId) -> MaterialEntry` raises `KeyError(f"no material {mid!r} in catalog")` when absent (chained `from None`). `get(self, mid) -> MaterialEntry | None`, `__contains__`, `__iter__` (yields `MaterialEntry` values in insertion order).
- [ ] `Catalog.to_dict(self) -> CatalogDoc` / `from_dict(cls, data: Mapping[str, object]) -> Catalog` (classmethod) / `to_json` / `from_json` (classmethod), mirroring the `layout.py` pattern exactly: `to_json`/`from_json` are `json.dumps`/`json.loads` wrappers; no module-level `dumps`/`loads`/`to_dict`/`from_dict` functions.
- [ ] Doc shape (`TypedDict`s): `MaterialEntryDoc` (`id: str`, `name: str`, `thickness_mm: float`, `material_type: str`, `nominal_thickness: str | None` — key always present, value may be `null`); `CatalogDoc` (`schema_version: Literal[1]`, `materials: list[MaterialEntryDoc]`). The doc is `{"schema_version": 1, "materials": [ {entry}, ... ]}`, order-preserving.
- [ ] `from_dict` takes `Mapping[str, object]` (parsed external JSON, the sanctioned type-erasing boundary — one-line comment), narrows with `isinstance`, reconstructs through the real `MaterialEntry`/`Catalog` constructors, and builds `entries` keyed by each entry's `id`. It raises `ValueError` on: `schema_version` absent or `!= 1`; `materials` not a list; an entry that is not an object; a missing required key; a wrong JSON type for a value; two entries sharing an `id`.
- [ ] No runtime dependency added: standard library only (`json`, `dataclasses`, `typing`, `collections.abc`). No import from `shelving_core.layout` or any other `shelving_core` module (keeps `layout` -> `materials` one-directional).

### `shelving_core/materials.schema.json`
- [ ] JSON Schema (`"$schema": "https://json-schema.org/draft/2020-12/schema"`, stable `"$id"`) for the exact doc above. `schema_version` is `{"const": 1}`. `materials` is an array of entry objects; entry `required: ["id", "name", "thickness_mm", "material_type"]`; `thickness_mm` `{"type": "number", "exclusiveMinimum": 0}`; `nominal_thickness` `{"type": ["string", "null"]}`; `additionalProperties: false` on every object. Shipped inside the package next to `layout.schema.json`.

### `shelving_core/layout.py` + `layout.schema.json` (rework)
- [ ] `Carcass`: drop `default_thickness_mm`; add `default_material: MaterialId` (no default) and `id: str = field(default_factory=new_id)` as the last field. `__post_init__` keeps the `width_mm`/`height_mm`/`depth_mm > 0` guards, drops the `default_thickness_mm` guard, and raises `ValueError` on an empty `default_material`.
- [ ] `Divider`: drop `thickness_mm`; add `material: MaterialId | None = None` and `lap: Literal["captured", "through"] | None = None` (reserved for a future per-joint lap-order override — no code reads it in M2). `id` stays. `__post_init__` drops the thickness guard and raises `ValueError` when `lap` is neither `None`, `"captured"`, nor `"through"`.
- [ ] `Carcass.to_dict` emits `id` and `default_material` in the carcass body, no `default_thickness_mm`. `Divider` doc emits `id`, `material` (string or `null`), `lap` (string or `null`), no `thickness_mm`. `from_dict` reads `id`/`default_material` (required) and, per divider, optional `material`/`lap` (absent -> `None`). `SCHEMA_VERSION` stays `1` (no persisted carcasses exist yet, so no migration path is owed).
- [ ] `CarcassBody` TypedDict: `id: str`, `default_material: str`, no `default_thickness_mm`. `DividerDoc`: `id: str`, `material: str | None`, `lap: Literal["captured", "through"] | None`, no `thickness_mm`.
- [ ] `layout.py` imports `MaterialId` from `shelving_core.materials`. No import cycle (verify `materials.py` imports nothing from `layout`).
- [ ] `layout.schema.json`: carcass `required` becomes `["id", "width_mm", "height_mm", "depth_mm", "default_material", "root"]`; `id` and `default_material` are `{"type": "string", "minLength": 1}`; `default_thickness_mm` removed. Divider `required` is `["id"]`; add `"material": {"type": ["string", "null"]}` and `"lap": {"enum": ["captured", "through", null]}`; remove `thickness_mm`. `additionalProperties: false` retained.

### `shelving_core/solver.py` (rework)
- [ ] `solve(carcass: Carcass, catalog: Catalog) -> SolvedLayout`. Imports `Catalog` from `shelving_core.materials`.
- [ ] `solve` resolves `default_t = catalog[carcass.default_material].thickness_mm` once and threads it plus `catalog` into `_interior_rect(carcass, default_t)` and `_place(bay, rect, out, catalog, default_t)`. `_effective_thicknesses(split, catalog, default_t) -> list[float]` returns, per divider, `catalog[d.material].thickness_mm` when `d.material is not None` else `default_t`.
- [ ] `distribute(...)` is unchanged: same signature, still a pure function over `Sequence[SplitRule]` and `Sequence[float]`, no `Catalog` parameter.
- [ ] `LayoutSolveError` and its reasons are unchanged. A `default_material` or `Divider.material` absent from the catalog surfaces as the `KeyError` from `Catalog.__getitem__` (documented in the `solve` docstring), not a `LayoutSolveError`.

### `shelving_core/expand.py` (new)
- [ ] `@dataclass(frozen=True) Vec3` with `x_mm: float`, `y_mm: float`, `z_mm: float`.
- [ ] `class PlankRole(enum.StrEnum)` with members `LEFT_SIDE = "left_side"`, `RIGHT_SIDE = "right_side"`, `TOP = "top"`, `BOTTOM = "bottom"`, `SHELF = "shelf"`, `DIVIDER = "divider"`.
- [ ] `@dataclass(frozen=True) PlankSpec` with `node_id: str`, `role: PlankRole`, `size: Vec3`, `placement: Vec3`, `material: MaterialId`. No grain field.
- [ ] `expand(carcass: Carcass, catalog: Catalog) -> list[PlankSpec]`: calls `solve(carcass, catalog)` internally, then emits, in this exact order: `BOTTOM`, `TOP`, `LEFT_SIDE`, `RIGHT_SIDE`, then one plank per `Divider` walking the tree in pre-order (each child visited, then the divider that follows it, recursing into `Split` children).
- [ ] Shell-plank geometry (local frame: origin front-bottom-left, `+X` right, `+Y` back/depth, `+Z` up; `placement` is the plank's min corner; `W,H,D = carcass.width_mm, height_mm, depth_mm`; `t = catalog[carcass.default_material].thickness_mm`): BOTTOM `size Vec3(W, D, t)` at `Vec3(0, 0, 0)`; TOP `size Vec3(W, D, t)` at `Vec3(0, 0, H - t)`; LEFT_SIDE `size Vec3(t, D, H - 2*t)` at `Vec3(0, 0, t)`; RIGHT_SIDE `size Vec3(t, D, H - 2*t)` at `Vec3(W - t, 0, t)`. (Top and bottom run continuous full width x full depth; the two sides are captured between them.)
- [ ] Divider geometry: for `Divider` `d` in `Split` `s`, `rect = layout[d.id]`; `role` is `PlankRole.SHELF` when `s.orientation is Orientation.HORIZONTAL` else `PlankRole.DIVIDER`; `size Vec3(rect.width_mm, D, rect.height_mm)`; `placement Vec3(rect.x_mm, 0.0, rect.z_mm)`; `material` is `d.material` when set else `carcass.default_material` (looked up via `catalog[...]` so an unknown id raises `KeyError`); `node_id` is `d.id`.
- [ ] Shell-plank `node_id` is `f"{carcass.id}:{role.value}"` (e.g. `"<uuid>:left_side"`), stable across repeated `expand` calls on the same `Carcass`.
- [ ] Public helper `total_volume(specs: Sequence[PlankSpec]) -> float` returning `sum(s.size.x_mm * s.size.y_mm * s.size.z_mm for s in specs)`. Used by the demo and the tests.
- [ ] `LayoutSolveError` from `solve` propagates through `expand` unchanged.
- [ ] No FreeCAD import; imports only from `shelving_core.layout`, `.materials`, `.solver`.

### `shelving_core/svg.py`
- [ ] `to_svg` signature is unchanged (`carcass`, `layout`, keyword options). The title string drops the `default thickness ... mm` clause; it becomes `f"Carcass {carcass.width_mm:g} x {carcass.height_mm:g} x {carcass.depth_mm:g} mm"`. No other change; `to_svg` still reads only the carcass and the solved layout.

### Tests — reworked
- [ ] `test_layout.py`: every `Carcass(...)` uses `default_material=<MaterialId>` (no `default_thickness_mm`); every `Divider(...)` uses `material=`/`lap=` or the defaults (no `thickness_mm`). Drop the `default_thickness_mm` and `Divider.thickness_mm` value-guard tests; add tests for the empty-`default_material` guard, the `lap` value guard, and a JSON round-trip preserving `carcass.id`, `default_material`, per-divider `material` (including `None`) and `lap`.
- [ ] `test_solver.py`: introduce a small catalog helper (e.g. entries at the exact thicknesses the cases need); every `solve(...)` call passes a `Catalog`; `Divider` thickness cases become `Divider(material=<id at that thickness>)`. `distribute` direct-call tests are untouched (still literal numbers). The nested-`Rect` case and the carcass-inset case keep their `pytest.approx(abs=1e-6)` assertions with thicknesses now sourced from the catalog.
- [ ] `test_schema.py`: sample `Carcass` docs carry `id`/`default_material` and dividers carry `material`/`lap` instead of `thickness_mm`; the invalid-doc corpus is updated (a doc still carrying `default_thickness_mm` or a divider `thickness_mm` must now fail because `additionalProperties: false`).
- [ ] `test_svg.py`: title-string assertions updated to the thickness-free title; `Carcass` construction updated to `default_material` + a catalog for the `solve` call.
- [ ] `tests/test_layout_demo.py`: header assertion still holds; add assertions that the plank-table section has `4 + <divider count>` rows for the sample and that a `Total plank volume:` line is printed.

### Tests — new
- [ ] `shelving_core/tests/test_materials.py`: `MaterialEntry` construction guards; `Catalog.__getitem__` `KeyError` message; `get`/`__contains__`/`__iter__`; multi-entry JSON round-trip preserving order and every field including `nominal_thickness=None`; `from_dict` rejecting bad `schema_version`, a duplicate `id`, a missing required key, and a wrong value type.
- [ ] `shelving_core/tests/test_materials_schema.py`: meta-validate `materials.schema.json` as a Draft 2020-12 schema; assert `to_dict()` for a couple of sample catalogs validates; a corpus of invalid docs (bad `schema_version`, missing required key, `thickness_mm <= 0`, an unexpected extra key) each fail validation. Uses `jsonschema` (already in the `dev` extra).
- [ ] `shelving_core/tests/test_expand.py`: (a) a bare single-`Leaf` carcass -> exactly 4 planks, each role/size/placement asserted with `pytest.approx(abs=1e-6)`, plus `total_volume`; (b) a one-`HORIZONTAL`-split carcass -> a 5th plank, `role == SHELF`, `size == (W-2t, D, t)`, placement from the solver; (c) a one-`VERTICAL`-split carcass -> `role == DIVIDER`, `size == (t, D, H-2t)`; (d) a `Divider(material=<12mm id>)` override in a catalog whose default is 18mm -> that plank's `material` is the override id and its thickness dimension is 12, and a sibling leaf opening is smaller than in the no-override case; (e) shell `node_id`s equal `f"{carcass.id}:<role>"` and are identical across two `expand` calls; (f) a nested sample (mirroring the demo tree) -> plank count `== 4 + divider count` and `total_volume` equals an independent recomputation; (g) `default_material` missing from the catalog raises `KeyError`; an over-constrained carcass raises `LayoutSolveError` through `expand`.

### Demo
- [ ] `tools/layout_demo.py`: build a small in-code `Catalog` (a default ~18 mm plywood entry plus a second ~12 mm entry) and set `carcass.default_material`; give one divider in the sample tree `material=<12mm id>` so the override shows in the table. Call `solve(carcass, catalog)` and `expand(carcass, catalog)`. Keep the existing solved-rect tree dump (its header line stays `Carcass 900 x 1800 x 300 mm ...`, with the trailing `default thickness` text replaced by `default material <name>`). Then print a plank table: one row per plank with role, size as `x x y x z mm`, placement as `(x, y, z)`, and material name; then a final line `Total plank volume: <n> mm^3`. `python tools/layout_demo.py` exits 0. `--svg PATH` still works via `to_svg(carcass, layout)`.

### Docs
- [ ] `README.md`: add a `## Glossary` section (after `## Tests`, or wherever reads best) defining the core and woodworking vocabulary this milestone introduces, each term paired with how it is represented in the code. Cover at least: carcass; bay / leaf / split; divider (and shelf vs vertical divider); plank; joint; butt joint; lap order, and "continuous" (runs through) vs "captured" (stops against a neighbour's face); the default carcass rule (top and bottom continuous full width x depth, sides and dividers captured); catalog / material entry / `MaterialId`; `PlankSpec` and `PlankRole`; the local coordinate convention (origin front-bottom-left, +X right, +Y depth, +Z up; `placement` is a plank's minimum corner); `Vec3`; `expand` and the spacing solver. Name the actual classes / fields / modules (`Carcass.default_material`, `Divider.material`, `shelving_core.expand`, ...). Prose follows the repo's file-content writing style (identifier-first where it fits, state current behaviour as settled, no em-dash asides, no filler); it is swept by `doc-hygiene` at sign-off.
- [ ] `docs/architecture.md`: in "### v1 delivers", rewrite the butt-joint bullet so the top and bottom run full width and depth and the two sides (and every shelf/divider) are captured; note the per-joint lap-order override is reserved in the schema and not yet honored. In "### The split-tree", replace the `default_thickness_mm` sentence with one describing `Carcass.default_material` (a catalog id whose thickness applies to the shell panels and to any `Divider` with no `material`), and note every node including the `Carcass` carries a UUID. In "### The spacing solver", note `solve` now takes the catalog. In "### Carcass expansion", update the default carcass rule to "top and bottom continuous, sides and dividers captured", state the per-joint override is reserved (M2 always applies the default), and change the `PlankSpec` tuple to `(node_id, role, size, placement, material_ref)` with `size`/`placement` as `Vec3` and grain deferred to a later milestone. In "## Material catalog", update the per-entry field list to `id` / `name` / `thickness_mm` / `material_type` (all required) plus optional `nominal_thickness`; drop `nominal_label` / `sheet_size` / `grain_default` / `appearance` (note they arrive with the milestones that consume them). Update the "Material model" decisions-of-record row to name both required fields. No other restyling.
- [ ] `docs/roadmap.md`: M2 **Status** line becomes `Task sh-009`.

### Verification
- [ ] `tools/vendor-core.sh` re-run and the refreshed `freecad/shelving/vendor/shelving_core/` committed (now carrying `expand.py`, `materials.py`, `materials.schema.json`); the vendor-drift check in `pixi run tests` passes.
- [ ] `pixi run tests` is green end to end (ruff lint + format, `mypy --strict`, pytest over `shelving_core` and `tests`, repo-consistency checks, workflow lint, headless `freecadcmd` import smoke).

### Scope guard
- [ ] No back panel, no back role, no back material. No grain type, field, or logic anywhere in `shelving_core`. No per-node depth override (no `depth_mm` field). No FreeCAD import in `shelving_core/`. No reverse solve. No per-joint lap-order logic beyond storing the reserved `Divider.lap` field. No bay-level (`Leaf`/`Split`) material field. `expand` produces plain data only — no `Part` / solid construction.

## Frontier Advice

CRITICAL: `shelving_core` stays runtime-dependency-free (standard library only).
`jsonschema` is TEST-only and already present in the `dev` extra and
`pixi.toml`; do not add dependencies. `shelving_core` must never import
`FreeCAD`/`FreeCADGui` (`shelving_core/tests/test_no_freecad.py` scans the whole
package, vendored copy included). New modules import with no side effects.

MODULE DEPENDENCY DIRECTION (do not violate): `materials` imports nothing from
`shelving_core`. `layout` imports `MaterialId` from `materials`. `solver`
imports from `layout` and `materials`. `expand` imports from `layout`,
`materials`, `solver`. Any import from `materials` back into `layout`/`solver`
is a cycle and a bug.

STANDING OBLIGATIONS (`CLAUDE.md`):
- **Typed Python** applies and is satisfied by this plan: `NewType`
  (`MaterialId`), frozen dataclasses (`MaterialEntry`, `Catalog`, `Vec3`,
  `PlankSpec`), `StrEnum` (`PlankRole`), `Literal` tags in the doc `TypedDict`s
  and on `Divider.lap`, `Mapping`/`Sequence` parameters. The ONLY permitted
  `object` is `Catalog.from_dict`'s `Mapping[str, object]` input — parsed
  external JSON, a genuine type-erasing boundary — with a one-line comment
  saying so, exactly as `layout.py` already does. `mypy --strict` over the
  changed code must pass.
- **Shell stays simple**: no shell logic is added; `tools/vendor-core.sh` is
  unchanged (its existing `rsync` of `shelving_core/` already picks up the new
  files). Nothing to opt out of.

NO `from __future__ import annotations` (consistent with sh-003). String forward
refs only where `layout.py` already uses them (`-> "Carcass"`, and now `->
"Catalog"` in `materials.py`). `Vec3`/`PlankSpec`/`PlankRole` need no forward
refs. `expand`'s tree recursion dispatches on `isinstance`, not annotations.

COORDINATE CONVENTION (local carcass frame, matches `docs/architecture.md`):
origin at the front-bottom-left corner; `+X` right (width), `+Y` away from the
viewer (depth), `+Z` up (height). A `PlankSpec.placement` is the plank's minimum
corner in that frame — the point you would pass to `Part.makeBox` before
translating. `size` is the plank's extent along each axis. All lengths are float
millimetres; no rounding, no `Decimal`.

CARCASS LAP RULE (exact; `t` = default material thickness, `W/H/D` = carcass
width/height/depth):
- BOTTOM: size `(W, D, t)`, placement `(0, 0, 0)`.
- TOP: size `(W, D, t)`, placement `(0, 0, H - t)`.
- LEFT_SIDE: size `(t, D, H - 2*t)`, placement `(0, 0, t)`.
- RIGHT_SIDE: size `(t, D, H - 2*t)`, placement `(W - t, 0, t)`.
- Each divider is its solved `Rect` extruded through the full depth: size
  `(rect.width_mm, D, rect.height_mm)`, placement `(rect.x_mm, 0, rect.z_mm)`.
The M1 solver's `_interior_rect` (inset by `t` on all four sides, origin at
`(t, t)`) is geometrically correct for this rule unchanged — only its thickness
*source* moves to the catalog. Interior divider sizes/placements come straight
from `solve`; do not recompute them in `expand`.

SHELL-PLANK IDENTITY: `Carcass` gains `id: str = field(default_factory=new_id)`
(reuse `layout.new_id`). Shell-plank `node_id` is the literal string
`f"{carcass.id}:{role.value}"`. This must be deterministic and stable across
`expand` calls — no `uuid4()` per call.

SOLVER REWORK IS MECHANICAL: keep `distribute` byte-for-byte (signature and
body). Thread `catalog` + a resolved `default_t: float` through `solve` ->
`_interior_rect` / `_place` / `_effective_thicknesses`. `_effective_thicknesses`
resolves each `Divider`: `catalog[d.material].thickness_mm` if `d.material` is
not `None`, else `default_t`. Everything else in `solver.py` is untouched.

EXPECTED TEST BLAST RADIUS (all under this task): `test_layout.py`,
`test_solver.py`, `test_schema.py`, `test_svg.py`, `tests/test_layout_demo.py`
all reference `default_thickness_mm` / `Divider(thickness_mm=...)` /
`solve(carcass)` and must be updated to `default_material` + a `Catalog` +
`solve(carcass, catalog)`. Build a tiny reusable catalog helper in the solver
test module rather than repeating entry construction. `svg.py:~233` is the only
non-test line outside the new modules that reads `default_thickness_mm`; the fix
is to drop that clause from the title, not to thread the catalog into `to_svg`.

CATALOG DOC FORMAT (`Catalog.to_dict()` output, exact):
```json
{
  "schema_version": 1,
  "materials": [
    {"id": "ply18", "name": "18 mm birch ply", "thickness_mm": 18.0,
     "material_type": "plywood", "nominal_thickness": "3/4\""},
    {"id": "mdf12", "name": "12 mm MDF", "thickness_mm": 12.0,
     "material_type": "mdf", "nominal_thickness": null}
  ]
}
```
`from_dict` keys `entries` by each entry's `id`; a repeated `id` is a
`ValueError`. `material_type` is a free-form string (`"plywood"`, `"solid
wood"`, `"mdf"`, ...), not an enum. `nominal_thickness` is a human label for the
nominal/callout thickness (`"3/4\""`, `"18 mm"`), always emitted (as `null` when
unset).

ERROR BEHAVIOUR: a `MaterialId` not in the catalog -> `KeyError` from
`Catalog.__getitem__` (with the `f"no material {mid!r} in catalog"` message),
propagating out of `solve`/`expand`. An unsatisfiable layout -> `LayoutSolveError`
unchanged, propagating out of `expand`. Do not catch or wrap either in `expand`.

DEMO: keep it argparse-driven exactly as today (`--svg PATH` optional). Add the
in-code `Catalog`, the plank table, and the `Total plank volume: <n> mm^3` line
(integer-formatted millimetres cubed, no litres). `tests/test_layout_demo.py`
runs it as a subprocess and asserts exit 0, the header line, the tree line
counts (unchanged), the plank-row count (`4 + divider count`), and the presence
of the total-volume line.

VENDORING: after the `shelving_core/` changes, run `bash tools/vendor-core.sh`
and commit `freecad/shelving/vendor/shelving_core/`. `pixi run tests` runs the
drift check, so re-run the vendor script whenever `shelving_core/` changes
again during rework.

DOC EDITS are scoped to the bullets in Must Have "Docs"; do not restyle
surrounding prose. `docs/roadmap.md` M2 status -> `Task sh-009` in the same
change.

Friction log: record any workaround per `CLAUDE.md` in
`.claude/docs/friction-log.md` in this session.

## Execution Plan

- [ ] **Step 1** (`shelving_core/materials.py`, `shelving_core/materials.schema.json`): Implement `MaterialId`, `MATERIALS_SCHEMA_VERSION`, `MaterialEntry` (+ `__post_init__` guards), `Catalog` (`__getitem__`/`get`/`__contains__`/`__iter__`), the `MaterialEntryDoc`/`CatalogDoc` TypedDicts, and `to_dict`/`from_dict`/`to_json`/`from_json` per CATALOG DOC FORMAT. Author `materials.schema.json` (Draft 2020-12) to match, with `additionalProperties: false` and `thickness_mm` `exclusiveMinimum: 0`. Imports: standard library only; nothing from `shelving_core`.

- [ ] **Step 2** (`shelving_core/layout.py`, `shelving_core/layout.schema.json`): Import `MaterialId` from `.materials`. `Carcass`: drop `default_thickness_mm`, add `default_material: MaterialId` and trailing `id: str = field(default_factory=new_id)`, update `__post_init__` and `to_dict`/`from_dict` and `CarcassBody`. `Divider`: drop `thickness_mm`, add `material: MaterialId | None = None` and `lap: Literal["captured","through"] | None = None`, update `__post_init__`, `to_dict`/`from_dict`, `DividerDoc`. Update `layout.schema.json` per Must Have. Keep `SCHEMA_VERSION = 1`.

- [ ] **Step 3** (`shelving_core/solver.py`): `solve(carcass, catalog)`. Resolve `default_t` from the catalog; thread `catalog` + `default_t` through `_interior_rect`, `_place`, `_effective_thicknesses` (divider material -> thickness, else `default_t`). Leave `distribute` and all other logic byte-identical. Import `Catalog` from `.materials`.

- [ ] **Step 4** (`shelving_core/expand.py`): New module. `Vec3`, `PlankRole`, `PlankSpec`, `total_volume`, and `expand(carcass, catalog)` per CARCASS LAP RULE, SHELL-PLANK IDENTITY, and the divider geometry / ordering in Must Have. Calls `solve(carcass, catalog)` internally. No FreeCAD import.

- [ ] **Step 5** (`shelving_core/svg.py`, `shelving_core/tests/test_layout.py`, `shelving_core/tests/test_solver.py`, `shelving_core/tests/test_schema.py`, `shelving_core/tests/test_svg.py`): Drop the `default thickness` clause from the `to_svg` title. Update the four test modules to `default_material` + `Catalog` + `solve(carcass, catalog)` + `Divider(material=/lap=)`, adjust JSON/schema expectations, and update/drop the removed value-guard tests as listed in Must Have "Tests — reworked". Add the new `default_material` / `lap` guard tests and the extended round-trip assertions.

- [ ] **Step 6** (`shelving_core/tests/test_materials.py`, `shelving_core/tests/test_materials_schema.py`, `shelving_core/tests/test_expand.py`): Write the new suites per Must Have "Tests — new". Use `pytest.approx(abs=1e-6)` for every geometric assertion. `test_materials_schema.py` uses `jsonschema`.

- [ ] **Step 7** (`tools/layout_demo.py`, `tests/test_layout_demo.py`): Add the in-code `Catalog` (two entries, one divider overriding to the 12 mm entry), switch to `solve`/`expand` with the catalog, replace the header's `default thickness` text with `default material <name>`, print the plank table and the `Total plank volume: <n> mm^3` line. Update `tests/test_layout_demo.py` per Must Have. Run `python tools/layout_demo.py`; confirm exit 0 and a readable table.

- [ ] **Step 8** (`README.md`, `docs/architecture.md`, `docs/roadmap.md`): Add the `README.md` `## Glossary` section per Must Have "Docs". Apply the scoped `docs/architecture.md` edits: the butt-joint bullet, the split-tree `default_material` sentence + Carcass-UUID note, the solver-takes-catalog note, the "### Carcass expansion" rule + `PlankSpec` tuple + grain-deferred note, the "## Material catalog" field list, the "Material model" decisions row. Set the `docs/roadmap.md` M2 status line.

- [ ] **Step 9** (`freecad/shelving/vendor/shelving_core/`): Run `bash tools/vendor-core.sh`, commit the refreshed vendored copy (now including `expand.py`, `materials.py`, `materials.schema.json`). Run `pixi run tests` and confirm the whole chain is green.
