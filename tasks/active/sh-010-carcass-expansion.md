---
id: sh-010
title: "Carcass expansion: PlankSpec list (M2, part 2)"
current_agent: user
current_phase: user_signoff
review_rejections: 0
blocked_by: [sh-009]
---

# sh-010: Carcass expansion: PlankSpec list (M2, part 2)

## Summary
Add `shelving_core.expand`: walk a solved `Carcass` split-tree and emit one
`PlankSpec` (role, size, placement, material) per physical plank — the two
sides, top, bottom, and every divider — applying the default carcass lap rule
(top and bottom run continuous full width x depth; the sides and every divider
are captured) and the front-bottom-left coordinate convention. The demo script
gains a plank table and a total-volume line; the README gains a glossary of the
carcass and woodworking vocabulary. Part 2 of 2 for milestone M2; builds on
sh-009's catalog-driven solver.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [ ] User sign-off

## Must Have

### `shelving_core/expand.py` (new)
- [x] `@dataclass(frozen=True) Vec3` with `x_mm: float`, `y_mm: float`, `z_mm: float`.
- [x] `class PlankRole(enum.StrEnum)` with members `LEFT_SIDE = "left_side"`, `RIGHT_SIDE = "right_side"`, `TOP = "top"`, `BOTTOM = "bottom"`, `SHELF = "shelf"`, `DIVIDER = "divider"`.
- [x] `@dataclass(frozen=True) PlankSpec` with `node_id: str`, `role: PlankRole`, `size: Vec3`, `placement: Vec3`, `material: MaterialId`. No grain field.
- [x] `expand(carcass: Carcass, catalog: Catalog) -> list[PlankSpec]`: calls `solve(carcass, catalog)` internally, then emits, in this exact order: `BOTTOM`, `TOP`, `LEFT_SIDE`, `RIGHT_SIDE`, then one plank per `Divider` walking the tree in pre-order (each child visited, then the divider that follows it, recursing into `Split` children).
- [x] Shell-plank geometry (local frame: origin front-bottom-left, `+X` right, `+Y` back/depth, `+Z` up; `placement` is the plank's minimum corner). Let `width_mm`, `height_mm`, `depth_mm` be the carcass outer dimensions and `thickness_mm = catalog[carcass.default_material].thickness_mm`. BOTTOM `size Vec3(width_mm, depth_mm, thickness_mm)` at `Vec3(0, 0, 0)`; TOP `size Vec3(width_mm, depth_mm, thickness_mm)` at `Vec3(0, 0, height_mm - thickness_mm)`; LEFT_SIDE `size Vec3(thickness_mm, depth_mm, height_mm - 2*thickness_mm)` at `Vec3(0, 0, thickness_mm)`; RIGHT_SIDE `size Vec3(thickness_mm, depth_mm, height_mm - 2*thickness_mm)` at `Vec3(width_mm - thickness_mm, 0, thickness_mm)`. (Top and bottom run continuous full width x full depth; the two sides are captured between them.)
- [x] Divider geometry: for `Divider` `d` in `Split` `s`, `rect = layout[d.id]`; `role` is `PlankRole.SHELF` when `s.orientation is Orientation.HORIZONTAL` else `PlankRole.DIVIDER`; `size Vec3(rect.width_mm, carcass.depth_mm, rect.height_mm)`; `placement Vec3(rect.x_mm, 0.0, rect.z_mm)`; `material` is `d.material` when set else `carcass.default_material` (looked up via `catalog[...]` so an unknown id raises `KeyError`); `node_id` is `d.id`.
- [x] Shell-plank `node_id` is `f"{carcass.id}:{role.value}"` (e.g. `"<uuid>:left_side"`), stable across repeated `expand` calls on the same `Carcass`.
- [x] Public helper `total_volume_mm3(specs: Sequence[PlankSpec]) -> float` returning `sum(s.size.x_mm * s.size.y_mm * s.size.z_mm for s in specs)`. Used by the demo and the tests. (Name carries `_mm3` per the repo's units-in-the-name rule.)
- [x] `LayoutSolveError` from `solve` propagates through `expand` unchanged. `Divider.lap` is not read (still reserved).
- [x] No FreeCAD import; imports only from `shelving_core.layout`, `.materials`, `.solver`.

### Tests — new
- [x] `shelving_core/tests/test_expand.py`: (a) a bare single-`Leaf` carcass -> exactly 4 planks, each role/size/placement asserted with `pytest.approx(abs=1e-6)`, plus `total_volume_mm3`; (b) a one-`HORIZONTAL`-split carcass -> a 5th plank, `role == SHELF`, `size == (width_mm - 2*thickness_mm, depth_mm, thickness_mm)`, placement from the solver; (c) a one-`VERTICAL`-split carcass -> `role == DIVIDER`, `size == (thickness_mm, depth_mm, height_mm - 2*thickness_mm)`; (d) a `Divider(material=<12mm id>)` override in a catalog whose default is 18mm -> that plank's `material` is the override id and its thickness dimension is 12, and a sibling leaf opening is wider than in the no-override case (the shell keeps resolving to the 18 mm default, so the thinner divider frees interior span); (e) shell `node_id`s equal `f"{carcass.id}:<role>"` and are identical across two `expand` calls; (f) a nested sample (mirroring the demo tree) -> plank count `== 4 + divider count` and `total_volume_mm3` equals an independent recomputation; (g) `default_material` missing from the catalog raises `KeyError`; an over-constrained carcass raises `LayoutSolveError` through `expand`.

### Demo
- [x] `tools/layout_demo.py`: after the existing solved-rect tree dump, call `expand(carcass, catalog)` and print a plank table — one row per plank with role, size as `x x y x z mm`, placement as `(x, y, z)`, and material name — then a final line `Total plank volume: <n> mm^3` from `total_volume_mm3(specs)` (integer-formatted millimetres cubed, no litres). The sample already has one divider with a `material=` override (added in sh-009); the table shows it. `python tools/layout_demo.py` exits 0; `--svg PATH` still works.
- [x] `tests/test_layout_demo.py`: add assertions that the plank-table section has `4 + <divider count>` rows for the sample and that a `Total plank volume:` line is printed. The header and tree-line assertions are unchanged from sh-009.

### Docs
- [x] `README.md`: add a `## Glossary` section (after `## Tests`, or wherever reads best) defining the core and woodworking vocabulary this milestone introduces, each term paired with how it is represented in the code. Cover at least: carcass; bay / leaf / split; divider (and shelf vs vertical divider); plank; joint; butt joint; lap order, and "continuous" (runs through) vs "captured" (stops against a neighbour's face); the default carcass rule (top and bottom continuous full width x depth, sides and dividers captured); catalog / material entry / `MaterialId`; `PlankSpec` and `PlankRole`; the local coordinate convention (origin front-bottom-left, +X right, +Y depth, +Z up; `placement` is a plank's minimum corner); `Vec3`; `expand` and the spacing solver. Name the actual classes / fields / modules (`Carcass.default_material`, `Divider.material`, `shelving_core.expand`, ...). Prose follows the repo's file-content writing style (identifier-first where it fits, state current behaviour as settled, no em-dash asides, no filler); it is swept by `doc-hygiene` at sign-off.
- [x] `docs/architecture.md`: in "### v1 delivers", rewrite the butt-joint bullet so the top and bottom run full width and depth and the two sides (and every shelf/divider) are captured; note the per-joint lap-order override is reserved in the schema and not yet honored. In "### Carcass expansion", update the default carcass rule to "top and bottom continuous, sides and dividers captured", state the per-joint override is reserved (M2 always applies the default), and change the `PlankSpec` tuple to `(node_id, role, size, placement, material_ref)` with `size`/`placement` as `Vec3` and grain deferred to a later milestone. No other restyling. (The split-tree / spacing-solver / "## Material catalog" / "Material model" edits were sh-009's.)

### Verification
- [x] `tools/vendor-core.sh` re-run and the refreshed `freecad/shelving/vendor/shelving_core/` committed (now carrying `expand.py`); the vendor-drift check in `pixi run tests` passes.
- [x] `pixi run tests` is green end to end (ruff lint + format, `mypy --strict`, pytest over `shelving_core` and `tests`, repo-consistency checks, workflow lint, headless `freecadcmd` import smoke).

### Scope guard
- [x] No back panel, no back role, no back material. No grain type, field, or logic anywhere in `shelving_core`. No per-node depth override (no `depth_mm` field). No FreeCAD import in `shelving_core/`. No reverse solve. No per-joint lap-order logic — `Divider.lap` (added in sh-009) stays unread. No bay-level (`Leaf`/`Split`) material field. No change to `shelving_core/materials.py`, `layout.py`, `solver.py`, or their schemas beyond what sh-009 already delivered — `expand` sits on top of them. `expand` produces plain data only — no `Part` / solid construction.

## Frontier Advice

DEPENDS ON sh-009 (hard blocker, `blocked_by: [sh-009]`): by the time this runs,
`shelving_core.materials` exists (`MaterialId`, `MaterialEntry`, `Catalog`),
`solve` already takes `(carcass, catalog)` and resolves thickness from the
catalog, `Carcass` already has an `id` field, and `Divider` already has the
reserved `material` / `lap` fields. This task adds `expand.py` and its wiring on
top; it does not re-touch those modules or their schemas.

CRITICAL: `shelving_core` stays runtime-dependency-free and never imports
`FreeCAD`/`FreeCADGui` (`shelving_core/tests/test_no_freecad.py` scans the whole
package, vendored copy included). `expand.py` imports with no side effects.

MODULE DEPENDENCY DIRECTION: `expand` imports from `shelving_core.layout`,
`.materials`, and `.solver`. Nothing imports from `expand`. No import from
`expand` back into any of those.

STANDING OBLIGATIONS (`CLAUDE.md`):
- **Typed Python** applies and is satisfied: frozen dataclasses (`Vec3`,
  `PlankSpec`), `StrEnum` (`PlankRole`), `Sequence` parameter on
  `total_volume_mm3`, no new `Any`/`object` (nothing here parses external JSON).
  `mypy --strict` over `expand.py` and `test_expand.py` must pass.
- **Shell stays simple**: no shell logic added; nothing to opt out of.

NAMING: follow `CLAUDE.md` § Project conventions (units in the name). Here that
means `Vec3` fields `x_mm` / `y_mm` / `z_mm`, every length local suffixed `_mm`,
and the volume helper named `total_volume_mm3`.

NO `from __future__ import annotations` (consistent with sh-003).
`Vec3`/`PlankSpec`/`PlankRole` need no forward refs; `expand`'s tree recursion
dispatches on `isinstance`, not annotations.

COORDINATE CONVENTION (local carcass frame, matches `docs/architecture.md`):
origin at the front-bottom-left corner; `+X` right (width), `+Y` away from the
viewer (depth), `+Z` up (height). A `PlankSpec.placement` is the plank's minimum
corner in that frame, the point you would pass to `Part.makeBox` before
translating. `size` is the plank's extent along each axis. All lengths are float
millimetres; no rounding, no `Decimal`.

CARCASS LAP RULE (exact). `thickness_mm` =
`catalog[carcass.default_material].thickness_mm`; `width_mm` / `height_mm` /
`depth_mm` = the carcass outer dimensions.
- BOTTOM: size `(width_mm, depth_mm, thickness_mm)`, placement `(0, 0, 0)`.
- TOP: size `(width_mm, depth_mm, thickness_mm)`, placement
  `(0, 0, height_mm - thickness_mm)`.
- LEFT_SIDE: size `(thickness_mm, depth_mm, height_mm - 2*thickness_mm)`,
  placement `(0, 0, thickness_mm)`.
- RIGHT_SIDE: size `(thickness_mm, depth_mm, height_mm - 2*thickness_mm)`,
  placement `(width_mm - thickness_mm, 0, thickness_mm)`.
- Each divider is its solved `Rect` extruded through the full depth: size
  `(rect.width_mm, depth_mm, rect.height_mm)`, placement
  `(rect.x_mm, 0, rect.z_mm)`.
Interior divider sizes/placements come straight from `solve`; do not recompute
them in `expand`. The `_interior_rect` inset already accounts for `thickness_mm`
on all four sides, so a shelf's solved width is `width_mm - 2*thickness_mm` and a
vertical divider's solved height is `height_mm - 2*thickness_mm` without any
extra arithmetic here.

SHELL-PLANK IDENTITY: shell-plank `node_id` is the literal string
`f"{carcass.id}:{role.value}"`. Deterministic and stable across `expand` calls,
never `uuid4()` per call. Divider `node_id` is the `Divider.id` from the tree.

ERROR BEHAVIOUR: a `MaterialId` not in the catalog -> `KeyError` from
`Catalog.__getitem__` (message `f"no material {mid!r} in catalog"`), propagating
out of `expand`. An unsatisfiable layout -> `LayoutSolveError` unchanged,
propagating out of `expand`. Do not catch or wrap either.

DEMO: keep it argparse-driven (`--svg PATH` optional). Add only the `expand`
call, the plank table, and the `Total plank volume: <n> mm^3` line — the in-code
`Catalog` and the header text were done in sh-009. `tests/test_layout_demo.py`
runs it as a subprocess and asserts exit 0, the header line, the tree line
counts (unchanged), the plank-row count (`4 + divider count`), and the presence
of the total-volume line.

VENDORING: after adding `expand.py`, run `bash tools/vendor-core.sh` and commit
`freecad/shelving/vendor/shelving_core/`. `pixi run tests` runs the drift check.

DOC EDITS are scoped to the bullets in Must Have "Docs"; do not restyle
surrounding prose, and do not re-edit the sections sh-009 already covered.

Friction log: record any workaround per `CLAUDE.md` in
`.claude/docs/friction-log.md` in this session.

## Execution Plan

- [x] **Step 1** (`shelving_core/expand.py`): New module. `Vec3`, `PlankRole`, `PlankSpec`, `total_volume_mm3`, and `expand(carcass, catalog)` per CARCASS LAP RULE, SHELL-PLANK IDENTITY, and the divider geometry / ordering in Must Have. Calls `solve(carcass, catalog)` internally. Imports only from `shelving_core.layout`, `.materials`, `.solver`. No FreeCAD import.

- [x] **Step 2** (`shelving_core/tests/test_expand.py`): Write the suite per Must Have "Tests — new" (cases a–g). Use `pytest.approx(abs=1e-6)` for every geometric assertion.

- [x] **Step 3** (`tools/layout_demo.py`, `tests/test_layout_demo.py`): Add the `expand(carcass, catalog)` call, the plank table, and the `Total plank volume: <n> mm^3` line. Update `tests/test_layout_demo.py` with the plank-row-count and total-volume-line assertions. Run `python tools/layout_demo.py`; confirm exit 0 and a readable table.

- [x] **Step 4** (`README.md`, `docs/architecture.md`): Add the `README.md` `## Glossary` section per Must Have "Docs". Apply the two scoped `docs/architecture.md` edits: the butt-joint bullet in "### v1 delivers" and the "### Carcass expansion" rule + `PlankSpec` tuple + grain-deferred note. Nothing else.

- [x] **Step 5** (`freecad/shelving/vendor/shelving_core/`): Run `bash tools/vendor-core.sh`, commit the refreshed vendored copy (now including `expand.py`). Run `pixi run tests` and confirm the whole chain is green.
