---
id: sh-009
title: "Material catalog + solver rework (M2, part 1)"
current_agent: implementer
current_phase: planning
review_rejections: 0
---

# sh-009: Material catalog + solver rework (M2, part 1)

## Summary
Add `shelving_core.materials`, a catalog data model (id / name / actual
thickness / material type, plus an optional nominal-thickness label) with JSON
round-trip and a published schema. Then move panel thickness off the numeric
`Carcass.default_thickness_mm` / `Divider.thickness_mm` fields onto catalog
references, threading the catalog through the M1 spacing solver. The existing
tests, the demo's material wiring, the SVG title, and the layout schema move
with it. This is part 1 of 2 for milestone M2; `shelving_core.expand` and
`PlankSpec` are sh-010.

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
- [ ] `Divider`: drop `thickness_mm`; add `material: MaterialId | None = None` and `lap: Literal["captured", "through"] | None = None` (reserved for a future per-joint lap-order override — no code reads it in M2; sh-010 keeps ignoring it). `id` stays. `__post_init__` drops the thickness guard and raises `ValueError` when `lap` is neither `None`, `"captured"`, nor `"through"`.
- [ ] `Carcass.to_dict` emits `id` and `default_material` in the carcass body, no `default_thickness_mm`. `Divider` doc emits `id`, `material` (string or `null`), `lap` (string or `null`), no `thickness_mm`. `from_dict` reads `id`/`default_material` (required) and, per divider, optional `material`/`lap` (absent -> `None`). `SCHEMA_VERSION` stays `1` (no persisted carcasses exist yet, so no migration path is owed).
- [ ] `CarcassBody` TypedDict: `id: str`, `default_material: str`, no `default_thickness_mm`. `DividerDoc`: `id: str`, `material: str | None`, `lap: Literal["captured", "through"] | None`, no `thickness_mm`.
- [ ] `layout.py` imports `MaterialId` from `shelving_core.materials`. No import cycle (verify `materials.py` imports nothing from `layout`).
- [ ] `layout.schema.json`: carcass `required` becomes `["id", "width_mm", "height_mm", "depth_mm", "default_material", "root"]`; `id` and `default_material` are `{"type": "string", "minLength": 1}`; `default_thickness_mm` removed. Divider `required` is `["id"]`; add `"material": {"type": ["string", "null"]}` and `"lap": {"enum": ["captured", "through", null]}`; remove `thickness_mm`. `additionalProperties: false` retained.

### `shelving_core/solver.py` (rework)
- [ ] `solve(carcass: Carcass, catalog: Catalog) -> SolvedLayout`. Imports `Catalog` from `shelving_core.materials`.
- [ ] `solve` resolves `default_thickness_mm = catalog[carcass.default_material].thickness_mm` once (the local keeps the name the existing `_place` parameter already uses) and threads it plus `catalog` into `_interior_rect(carcass, default_thickness_mm)` and `_place(bay, rect, out, catalog, default_thickness_mm)`. Rename `_effective_thicknesses` to `_effective_thicknesses_mm` (repo rule: a name for a `float` / `list[float]` dimensioned value carries the `_mm` suffix); its new signature is `_effective_thicknesses_mm(split, catalog, default_thickness_mm) -> list[float]`, returning per divider `catalog[d.material].thickness_mm` when `d.material is not None` else `default_thickness_mm`.
- [ ] `distribute(...)` is unchanged: same signature, still a pure function over `Sequence[SplitRule]` and `Sequence[float]`, no `Catalog` parameter.
- [ ] `LayoutSolveError` and its reasons are unchanged. A `default_material` or `Divider.material` absent from the catalog surfaces as the `KeyError` from `Catalog.__getitem__` (documented in the `solve` docstring), not a `LayoutSolveError`.

### `shelving_core/svg.py`
- [ ] `to_svg` signature is unchanged (`carcass`, `layout`, keyword options). The title string drops the `default thickness ... mm` clause; it becomes `f"Carcass {carcass.width_mm:g} x {carcass.height_mm:g} x {carcass.depth_mm:g} mm"`. No other change; `to_svg` still reads only the carcass and the solved layout.

### Tests — reworked
- [ ] `test_layout.py`: every `Carcass(...)` uses `default_material=<MaterialId>` (no `default_thickness_mm`); every `Divider(...)` uses `material=`/`lap=` or the defaults (no `thickness_mm`). Drop the `default_thickness_mm` and `Divider.thickness_mm` value-guard tests; add tests for the empty-`default_material` guard, the `lap` value guard, and a JSON round-trip preserving `carcass.id`, `default_material`, per-divider `material` (including `None`) and `lap`.
- [ ] `test_solver.py`: introduce a small catalog helper (e.g. entries at the exact thicknesses the cases need); every `solve(...)` call passes a `Catalog`; `Divider` thickness cases become `Divider(material=<id at that thickness>)`. `distribute` direct-call tests are untouched (still literal numbers). The nested-`Rect` case and the carcass-inset case keep their `pytest.approx(abs=1e-6)` assertions with thicknesses now sourced from the catalog.
- [ ] `test_schema.py`: sample `Carcass` docs carry `id`/`default_material` and dividers carry `material`/`lap` instead of `thickness_mm`; the invalid-doc corpus is updated (a doc still carrying `default_thickness_mm` or a divider `thickness_mm` must now fail because `additionalProperties: false`).
- [ ] `test_svg.py`: title-string assertions updated to the thickness-free title; `Carcass` construction updated to `default_material` + a catalog for the `solve` call.
- [ ] `tests/test_layout_demo.py`: header assertion updated to the new trailing text (`default material <name>` instead of `default thickness <n> mm`); the solved-rect tree line counts are unchanged. No plank-table assertion yet — that arrives with sh-010.

### Tests — new
- [ ] `shelving_core/tests/test_materials.py`: `MaterialEntry` construction guards; `Catalog.__getitem__` `KeyError` message; `get`/`__contains__`/`__iter__`; multi-entry JSON round-trip preserving order and every field including `nominal_thickness=None`; `from_dict` rejecting bad `schema_version`, a duplicate `id`, a missing required key, and a wrong value type.
- [ ] `shelving_core/tests/test_materials_schema.py`: meta-validate `materials.schema.json` as a Draft 2020-12 schema; assert `to_dict()` for a couple of sample catalogs validates; a corpus of invalid docs (bad `schema_version`, missing required key, `thickness_mm <= 0`, an unexpected extra key) each fail validation. Uses `jsonschema` (already in the `dev` extra).

### Demo
- [ ] `tools/layout_demo.py`: build a small in-code `Catalog` (a default ~18 mm plywood entry plus a second ~12 mm entry) and set `carcass.default_material`; give one divider in the sample tree `material=<12mm id>` so the override is exercised. Call `solve(carcass, catalog)` (still no `expand`). The solved-rect tree dump stays; its header line keeps `Carcass 900 x 1800 x 300 mm` and the trailing `default thickness <n> mm` text becomes `default material <name>`. `python tools/layout_demo.py` exits 0; `--svg PATH` still works via `to_svg(carcass, layout)`.

### Docs
- [ ] `docs/architecture.md`: in "### The split-tree", replace the `default_thickness_mm` sentence with one describing `Carcass.default_material` (a catalog id whose thickness applies to the shell panels and to any `Divider` with no `material`), and note every node including the `Carcass` carries a UUID. In "### The spacing solver", note `solve` now takes the catalog. In "## Material catalog", update the per-entry field list to `id` / `name` / `thickness_mm` / `material_type` (all required) plus optional `nominal_thickness`; drop `nominal_label` / `sheet_size` / `grain_default` / `appearance` (note they arrive with the milestones that consume them). Update the "Material model" decisions-of-record row to name both required fields. No other restyling. (The butt-joint bullet and the "### Carcass expansion" section are sh-010's to edit.)

### Verification
- [ ] `tools/vendor-core.sh` re-run and the refreshed `freecad/shelving/vendor/shelving_core/` committed (now carrying `materials.py` and `materials.schema.json`, plus the reworked `layout.py` / `solver.py` / `layout.schema.json`); the vendor-drift check in `pixi run tests` passes.
- [ ] `pixi run tests` is green end to end (ruff lint + format, `mypy --strict`, pytest over `shelving_core` and `tests`, repo-consistency checks, workflow lint, headless `freecadcmd` import smoke).

### Scope guard
- [ ] No `shelving_core/expand.py`, no `PlankSpec` / `PlankRole` / `Vec3`, no plank-list output, no lap-rule geometry, no plank table, no README glossary — all of that is sh-010. No back panel / back role / back material. No grain type, field, or logic anywhere. No per-node depth override (no `depth_mm` field). No FreeCAD import in `shelving_core/`. No reverse solve. `Divider.lap` is stored and round-tripped but never read. No bay-level (`Leaf`/`Split`) material field.

## Frontier Advice

CRITICAL: `shelving_core` stays runtime-dependency-free (standard library only).
`jsonschema` is TEST-only and already present in the `dev` extra and
`pixi.toml`; do not add dependencies. `shelving_core` must never import
`FreeCAD`/`FreeCADGui` (`shelving_core/tests/test_no_freecad.py` scans the whole
package, vendored copy included). New modules import with no side effects.

MODULE DEPENDENCY DIRECTION (do not violate): `materials` imports nothing from
`shelving_core`. `layout` imports `MaterialId` from `materials`. `solver`
imports from `layout` and `materials`. Any import from `materials` back into
`layout`/`solver` is a cycle and a bug. (`expand`, added in sh-010, will sit on
top of all three.)

STANDING OBLIGATIONS (`CLAUDE.md`):
- **Typed Python** applies and is satisfied by this plan: `NewType`
  (`MaterialId`), frozen dataclasses (`MaterialEntry`, `Catalog`), `Literal`
  tags in the doc `TypedDict`s and on `Divider.lap`, `Mapping`/`Sequence`
  parameters. The ONLY permitted `object` is `Catalog.from_dict`'s
  `Mapping[str, object]` input — parsed external JSON, a genuine type-erasing
  boundary — with a one-line comment saying so, exactly as `layout.py` already
  does. `mypy --strict` over the changed code must pass.
- **Shell stays simple**: no shell logic is added; `tools/vendor-core.sh` is
  unchanged (its existing `rsync` of `shelving_core/` already picks up the new
  files). Nothing to opt out of.

NAMING: follow `CLAUDE.md` § Project conventions (units in the name).
Concretely here: rename `_effective_thicknesses` -> `_effective_thicknesses_mm`,
and suffix every new length local / parameter with `_mm`. `nominal_thickness`
keeps no suffix — it is a `str` label, not a millimetre value.

NO `from __future__ import annotations` (consistent with sh-003). String forward
refs only where `layout.py` already uses them (`-> "Carcass"`, and now `->
"Catalog"` in `materials.py`).

SOLVER REWORK IS MECHANICAL: keep `distribute` byte-for-byte (signature and
body). Thread `catalog` + a resolved `default_thickness_mm: float` through
`solve` -> `_interior_rect` / `_place` / `_effective_thicknesses_mm` (renamed
from `_effective_thicknesses`). `_effective_thicknesses_mm` resolves each
`Divider`: `catalog[d.material].thickness_mm` if `d.material` is not `None`,
else `default_thickness_mm`. Everything else in `solver.py` is untouched. The
`_interior_rect` inset (by `default_thickness_mm` on all four sides, origin at
`(default_thickness_mm, default_thickness_mm)`) is correct unchanged: only the
thickness source moves to the catalog.

`Carcass.id`: add `id: str = field(default_factory=new_id)` (reuse
`layout.new_id`). It is unused in this task; it is added here so sh-010's
expansion has a stable per-unit identity for the four shell planks without a
second `layout.py` / `layout.schema.json` change. Round-trip it in
`to_dict`/`from_dict` and the schema.

EXPECTED TEST BLAST RADIUS (all under this task): `test_layout.py`,
`test_solver.py`, `test_schema.py`, `test_svg.py`, `tests/test_layout_demo.py`
all reference `default_thickness_mm` / `Divider(thickness_mm=...)` /
`solve(carcass)` and must be updated to `default_material` + a `Catalog` +
`solve(carcass, catalog)`. Build a tiny reusable catalog helper in the solver
test module rather than repeating entry construction. `svg.py` (the title
line) is the only non-test line outside the new module that reads
`default_thickness_mm`; the fix is to drop that clause from the title, not to
thread the catalog into `to_svg`.

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
propagating out of `solve`. An unsatisfiable layout -> `LayoutSolveError`
unchanged.

VENDORING: after the `shelving_core/` changes, run `bash tools/vendor-core.sh`
and commit `freecad/shelving/vendor/shelving_core/`. `pixi run tests` runs the
drift check, so re-run the vendor script whenever `shelving_core/` changes
again during rework.

DOC EDITS are scoped to the bullets in Must Have "Docs"; do not restyle
surrounding prose, and leave the butt-joint bullet and the "### Carcass
expansion" section for sh-010.

Friction log: record any workaround per `CLAUDE.md` in
`.claude/docs/friction-log.md` in this session.

## Execution Plan

- [ ] **Step 1** (`shelving_core/materials.py`, `shelving_core/materials.schema.json`): Implement `MaterialId`, `MATERIALS_SCHEMA_VERSION`, `MaterialEntry` (+ `__post_init__` guards), `Catalog` (`__getitem__`/`get`/`__contains__`/`__iter__`), the `MaterialEntryDoc`/`CatalogDoc` TypedDicts, and `to_dict`/`from_dict`/`to_json`/`from_json` per CATALOG DOC FORMAT. Author `materials.schema.json` (Draft 2020-12) to match, with `additionalProperties: false` and `thickness_mm` `exclusiveMinimum: 0`. Imports: standard library only; nothing from `shelving_core`.

- [ ] **Step 2** (`shelving_core/layout.py`, `shelving_core/layout.schema.json`): Import `MaterialId` from `.materials`. `Carcass`: drop `default_thickness_mm`, add `default_material: MaterialId` and trailing `id: str = field(default_factory=new_id)`, update `__post_init__`, `to_dict`/`from_dict`, `CarcassBody`. `Divider`: drop `thickness_mm`, add `material: MaterialId | None = None` and `lap: Literal["captured","through"] | None = None`, update `__post_init__`, `to_dict`/`from_dict`, `DividerDoc`. Update `layout.schema.json` per Must Have. Keep `SCHEMA_VERSION = 1`.

- [ ] **Step 3** (`shelving_core/solver.py`): `solve(carcass, catalog)`. Resolve `default_thickness_mm` from the catalog; thread `catalog` + `default_thickness_mm` through `_interior_rect`, `_place`, and `_effective_thicknesses_mm` (renamed from `_effective_thicknesses` for the `_mm` convention; divider material -> thickness, else `default_thickness_mm`). Leave `distribute` and all other logic byte-identical. Import `Catalog` from `.materials`.

- [ ] **Step 4** (`shelving_core/svg.py`, `shelving_core/tests/test_layout.py`, `shelving_core/tests/test_solver.py`, `shelving_core/tests/test_schema.py`, `shelving_core/tests/test_svg.py`): Drop the `default thickness` clause from the `to_svg` title. Update the four test modules to `default_material` + `Catalog` + `solve(carcass, catalog)` + `Divider(material=/lap=)`, adjust JSON/schema expectations, update/drop the removed value-guard tests, and add the new `default_material` / `lap` guard tests and the extended round-trip assertions per Must Have "Tests — reworked".

- [ ] **Step 5** (`shelving_core/tests/test_materials.py`, `shelving_core/tests/test_materials_schema.py`): Write the two new suites per Must Have "Tests — new". `test_materials_schema.py` uses `jsonschema`.

- [ ] **Step 6** (`tools/layout_demo.py`, `tests/test_layout_demo.py`): Add the in-code `Catalog` (two entries, one divider overriding to the 12 mm entry), switch the `solve` call to pass the catalog, replace the header's `default thickness <n> mm` text with `default material <name>`. Update the `tests/test_layout_demo.py` header assertion. Run `python tools/layout_demo.py`; confirm exit 0.

- [ ] **Step 7** (`docs/architecture.md`): Apply the scoped edits in Must Have "Docs": the split-tree `default_material` sentence + Carcass-UUID note, the solver-takes-catalog note, the "## Material catalog" field list, the "Material model" decisions row. Nothing else.

- [ ] **Step 8** (`freecad/shelving/vendor/shelving_core/`): Run `bash tools/vendor-core.sh`, commit the refreshed vendored copy (now including `materials.py`, `materials.schema.json`). Run `pixi run tests` and confirm the whole chain is green.
