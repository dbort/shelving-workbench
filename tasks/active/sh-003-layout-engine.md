---
id: sh-003
title: "Layout engine: Carcass split-tree, JSON Schema, spacing solver (M1)"
current_agent: reviewer
current_phase: review
review_rejections: 0
---

# sh-003: Layout engine: Carcass split-tree, JSON Schema, spacing solver (M1)

## Summary
Build the pure-Python heart of the Shelving Workbench: an N-ary recursive
split-tree data model for a `Carcass` (the shelving box), with JSON
round-tripping backed by a published JSON Schema, and a spacing solver that
turns a tree plus the carcass outer dimensions into a concrete 2D rectangle for
every bay and divider, distributing slack by fixed / weighted / fill rules and
raising a structured error when a layout cannot be satisfied. No FreeCAD, no
materials, no 3D; those arrive in M2 and M3.

## Status
- [x] Planning
- [x] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have

### Data model (`shelving_core/layout.py`)
- [x] Defines: `Orientation` (`enum.StrEnum` with members `HORIZONTAL = "horizontal"` and `VERTICAL = "vertical"`); rule classes `Fixed` (field `size_mm: float`), `Weighted` (field `weight: float`), `Fill` (no fields); node classes `Leaf` (field `id: str`), `Divider` (fields `id: str`, `thickness_mm: float | None`), `Split` (fields `id: str`, `orientation: Orientation`, `children: list["Bay"]`, `rules: list[SplitRule]`, `dividers: list[Divider]`); `Carcass` (fields `width_mm: float`, `height_mm: float`, `depth_mm: float`, `default_thickness_mm: float`, `root: Bay`). Type aliases `Bay = Leaf | Split` and `SplitRule = Fixed | Weighted | Fill`. Module constant `SCHEMA_VERSION: int = 1`. Function `new_id() -> str` returning `str(uuid.uuid4())`; every node `id` field defaults to `field(default_factory=new_id)`.
- [x] Every length-valued field and parameter carries an `_mm` suffix and is a plain `float`. `Weighted.weight` is dimensionless and stays `weight` (no suffix). No `Millimeters` type, no units field.
- [x] Tree nodes (`Leaf`, `Split`, `Divider`, `Carcass`) are mutable dataclasses; rule classes may be frozen or not.
- [x] `Split.__post_init__` validates: `len(children) == len(rules)` and `len(children) >= 2` and `len(dividers) == len(children) - 1`; any violation raises `ValueError` naming the offending count.
- [x] Construction validation, each raising `ValueError`: `Carcass.width_mm`, `.height_mm`, `.depth_mm` all `> 0`; `Carcass.default_thickness_mm >= 0`; `Fixed.size_mm > 0`; `Weighted.weight > 0`; `Divider.thickness_mm` is `None` or `>= 0`.
- [x] `Carcass.to_dict(self) -> CarcassDoc` and `Carcass.from_dict(cls, data: Mapping[str, object]) -> Carcass` (classmethod) round-trip any tree, preserving every node `id`, every rule (type and value), and every divider `thickness_mm` (including `None`) exactly. `Carcass.to_json(self) -> str` and `Carcass.from_json(cls, s: str) -> Carcass` (classmethod) are `json.dumps` / `json.loads` wrappers over those. No module-level `dumps`/`loads`/`to_dict`/`from_dict` functions.
- [x] `CarcassDoc` and the nested doc shapes (`CarcassBody`, `LeafDoc`, `SplitDoc`, `BayDoc` union, `FixedRuleDoc` / `WeightedRuleDoc` / `FillRuleDoc` / `RuleDoc` union, `DividerDoc`) are `typing.TypedDict`s (with `Literal` tags for `kind` / `type` / `orientation` and `schema_version`). `to_dict`'s return type is `CarcassDoc`.
- [x] `from_dict` takes `Mapping[str, object]` (arbitrary parsed JSON is the sanctioned type-erasing boundary, commented as such), narrows with `isinstance` / `match`, reconstructs through the real constructors so their validation runs, and reads ids from the data without regenerating them. It raises `ValueError` on: a `schema_version` key absent or `!= 1`; a bay object whose `kind` is not `"leaf"` or `"split"`; a rule object whose `type` is not `"fixed"` / `"weighted"` / `"fill"`; a structurally wrong shape (missing required key, wrong JSON type for a value).
- [x] The top-level doc is `{"schema_version": 1, "carcass": {...}}`. A carcass body is `{"width_mm", "height_mm", "depth_mm", "default_thickness_mm", "root"}`. Bay objects carry `"kind": "leaf" | "split"` and `"id"`; a split adds `"orientation": "horizontal" | "vertical"`, `"children"`, `"rules"`, `"dividers"`. Rule objects: `{"type": "fixed", "size_mm": <n>}` / `{"type": "weighted", "weight": <n>}` / `{"type": "fill"}`. Divider objects: `{"id": <s>, "thickness_mm": <n> | null}`.

### JSON Schema (`shelving_core/layout.schema.json`)
- [x] A JSON Schema (`"$schema": "https://json-schema.org/draft/2020-12/schema"`, with a stable `"$id"`) describing the exact top-level doc above, shipped inside the package so the vendored copy and external tools both carry it. Recursive `$defs` for `bay` (`oneOf` leaf / split), `rule` (`oneOf` the three), and `divider`. `schema_version` is `{"const": 1}`. `additionalProperties: false` on every object. Numeric constraints match the constructors (`size_mm` exclusiveMinimum 0, `weight` exclusiveMinimum 0, `thickness_mm` minimum 0 or null, carcass dims exclusiveMinimum 0, `default_thickness_mm` minimum 0).
- [x] `from_dict` does NOT import `jsonschema` or validate against the schema file at runtime; the dataclass constructors are the runtime guard. The schema is the published interop contract, kept honest by `test_schema.py` (below).
- [x] `pyproject.toml` `[project.optional-dependencies] dev` gains `jsonschema` (used only by tests). No new `shelving_core` runtime dependency.
- [x] `tools/vendor-core.sh` continues to copy `layout.schema.json` into the vendored tree (it lives under `shelving_core/`, so the existing `rsync` already includes it; the vendor-drift check must still pass).

### Solver (`shelving_core/solver.py`)
- [x] Defines: `Rect` (frozen dataclass, fields `x_mm: float`, `z_mm: float`, `width_mm: float`, `height_mm: float`); `SolvedLayout` (frozen dataclass wrapping `rect_by_id: Mapping[str, Rect]`, with `__getitem__` so `layout[node_id]` returns the `Rect`); module constant `EPS_MM: float = 1e-6`; `SolveErrorReason = Literal["overflow", "no_slack_absorber", "nonpositive_opening"]`; exception `LayoutSolveError(Exception)` with attributes `node_id: str`, `reason: SolveErrorReason`, `detail: Mapping[str, float]`.
- [x] `solve(carcass: Carcass) -> SolvedLayout` is a thin orchestrator: it calls small, individually testable helpers and does not inline the geometry. At minimum: `_interior_rect(carcass) -> Rect` (carcass inset), `distribute(...)` (below), a `_place(bay, rect, out)` recursion, and `_effective_thicknesses(split, default_thickness_mm) -> list[float]`.
- [x] `distribute(axis_span_mm: float, rules: Sequence[SplitRule], divider_thicknesses_mm: Sequence[float], *, node_id: str) -> list[float]` is a pure function with no dependency on `Rect`, the tree, or `Carcass`. It returns one opening size per rule. It raises `LayoutSolveError(reason="overflow", node_id=node_id, ...)` when `sum(divider_thicknesses_mm) > axis_span_mm + EPS_MM` or when `slack < -EPS_MM`, and `LayoutSolveError(reason="no_slack_absorber", node_id=node_id, ...)` when there are no `Weighted`/`Fill` rules and `abs(slack) > EPS_MM`. It does NOT check for nonpositive openings; `_place` does that against the child bay id.
- [x] Distribution math: effective divider thickness is `divider.thickness_mm` if not `None` else `carcass.default_thickness_mm`; `available_mm = axis_span_mm - sum(divider_thicknesses_mm)`; `fixed_sum_mm = sum(r.size_mm for Fixed rules)`; driven rules are `Weighted` and `Fill`, `Fill` counting as weight `1.0`; `slack_mm = available_mm - fixed_sum_mm`; each driven opening gets `weight / total_weight * slack_mm`, each fixed opening gets its `size_mm`. Float millimetres, no rounding, no `Decimal`.
- [x] `_interior_rect` insets the exterior by `default_thickness_mm` on all four sides: `Rect(x_mm=t, z_mm=t, width_mm=width_mm - 2*t, height_mm=height_mm - 2*t)`. If the inset width or height is `<= EPS_MM`, raise `LayoutSolveError(node_id=<root bay id>, reason="overflow", detail=...)`.
- [x] `_place` records a `Rect` in `rect_by_id` for every `Leaf` id, every `Split` id, and every `Divider` id. A `HORIZONTAL` split distributes its rect's `height_mm` along Z; a `VERTICAL` split distributes its rect's `width_mm` along X. Children are laid out in list order from the low edge (child 0 at minimum `z_mm` for `HORIZONTAL`, minimum `x_mm` for `VERTICAL`); each divider fills the gap between consecutive children, spanning the full cross-axis extent of the parent rect. After `distribute` returns, any resolved opening `<= EPS_MM` raises `LayoutSolveError(reason="nonpositive_opening", node_id=<that child bay's id>, detail={"size_mm": size})`.
- [x] `LayoutSolveError.node_id` is: the offending `Split`'s id for `"overflow"` and `"no_slack_absorber"` (or the root bay id for the carcass-inset case); the child bay's id for `"nonpositive_opening"`.

### Tests (`shelving_core/tests/`)
- [x] `test_layout.py`: one assertion per construction-validation `ValueError` (`Split` count invariants, all `Carcass`/`Fixed`/`Weighted`/`Divider` value guards); a JSON round-trip of a nested tree that includes at least one split with `>= 3` children, asserting id preservation and structural equality (`from_dict(c.to_dict()) == c` given dataclass `__eq__`); `from_dict` rejecting a bad `schema_version`, an unknown `kind`, an unknown rule `type`, and a structurally malformed doc.
- [x] `test_solver.py`: an even `Fill`/`Fill`/`Fill` split (3 equal openings, exercising N-ary); a `Fixed` + `Fill` split (fill absorbs slack); a `Weighted(2)` / `Weighted(1)` split (2:1 slack ratio); `distribute` tested directly with plain numbers for the fixed/weighted/fill and both error cases; a nested `HORIZONTAL`-then-`VERTICAL` case with every resulting `Rect` asserted via `pytest.approx(abs=1e-6)`; the carcass inset (all four sides reduced by `default_thickness_mm`); and one test per `LayoutSolveError` reason asserting `.reason` and `.node_id`.
- [x] `test_schema.py`: meta-validates that `layout.schema.json` is itself a valid Draft 2020-12 schema; for several sample `Carcass` trees (nested, and one with a `>= 3`-child split) asserts `to_dict(c)` validates against the schema; a corpus of hand-written invalid docs (bad `schema_version`, unknown `kind`, unknown rule `type`, missing required key, wrong value type, negative `size_mm`) each fail schema validation.
- [x] `./test.sh --fast` exits 0 (it runs `pytest shelving_core tests`); `./test.sh --full` / `pixi run full` still green.
- [x] `mypy --strict` reports no errors over `shelving_core` (including the new modules and the `TypedDict`s); `ruff check .` and `ruff format --check .` report nothing.

### Demo and docs
- [x] `tools/layout_demo.py` builds a sample nested `Carcass` (at least two split levels; a mix of `Fixed`, `Weighted`, and `Fill` rules; at least one `>= 3`-child split), calls `solve`, and prints an indented tree: each node's short id, kind, solved `Rect`, and (for split children) the rule. `python tools/layout_demo.py` exits 0. It is not part of the `shelving_core` package (repo-root `tools/`, like `tests/`).
- [x] `pixi.toml` gains a `[tasks]` entry `demo` whose body is exactly `python tools/layout_demo.py`. The existing `fast` / `full` / `lint-workflows` tasks are untouched.
- [x] `README.md` mentions `pixi run demo` (or `python tools/layout_demo.py`) as the way to eyeball a solved layout.
- [x] `docs/architecture.md` "### The split-tree" section: rewritten for N-ary splits (an orientation, an ordered list of two or more child `Bay`s, one `SplitRule` per child, one fewer `Divider` than children); the core type renamed from `Unit` to `Carcass` wherever that subsection refers to the data model (leave the FreeCAD `ShelvingUnit` object references alone); a sentence stating `Carcass` carries `default_thickness_mm`, used both for the carcass panels and as the divider default, until M2 introduces materials; a note that lengths use `_mm`-suffixed float fields. Rename `Unit` to `Carcass` in the "### The spacing solver" and "### Carcass expansion" subsections too where they name the core type. No other restyling.

### Scope guard
- [x] No `materials` module, no `expand` function, no `PlankSpec`, no catalog, no per-`Leaf` material or depth-override fields, no reverse solve (carcass dimensions are always given), no FreeCAD import anywhere in `shelving_core/`.

## Frontier Advice

CRITICAL: `shelving_core` stays runtime-dependency-free (standard library only:
`dataclasses`, `enum`, `uuid`, `json`, `typing`). `jsonschema` is a TEST-only
dependency in the `dev` extra; production code (`layout.py`, `solver.py`) never
imports it. `shelving_core` must never import `FreeCAD` / `FreeCADGui`
(`shelving_core/tests/test_no_freecad.py` already scans the whole package). New
modules import with no side effects.

STANDING OBLIGATIONS (`CLAUDE.md`): **Typed Python** applies and is satisfied by
this plan (precise dataclasses, `Literal` tags, `TypedDict` doc shapes,
`Mapping`/`Sequence` params). The only permitted `object`/`Any` is
`from_dict`'s `Mapping[str, object]` input, since parsed external JSON is a
genuine type-erasing boundary; put a one-line comment there saying so. No other
standing obligation is active.

PEP 749 / `from __future__ import annotations`: do NOT add it. The single
recursive annotation is `Split.children: list["Bay"]` (string forward
reference); `Bay` and `SplitRule` aliases are declared after the node classes.
Every other annotation uses a real, already-defined type. `dataclass` does not
evaluate annotation strings at class-creation time, so `list["Bay"]` is safe.

TYPE SHAPES (exact):
- `class Orientation(enum.StrEnum): HORIZONTAL = "horizontal"; VERTICAL = "vertical"`.
- `@dataclass class Fixed: size_mm: float` + `__post_init__` guard `> 0`.
  `@dataclass class Weighted: weight: float` guard `> 0`. `@dataclass class
  Fill:` empty. `SplitRule = Fixed | Weighted | Fill`.
- `@dataclass class Leaf: id: str = field(default_factory=new_id)`.
- `@dataclass class Divider: thickness_mm: float | None = None; id: str =
  field(default_factory=new_id)` guard `thickness_mm is None or thickness_mm >= 0`.
- `@dataclass class Split: orientation: Orientation; children: list["Bay"];
  rules: list[SplitRule]; dividers: list[Divider]; id: str =
  field(default_factory=new_id)` + the `__post_init__` length invariants.
- `Bay = Leaf | Split`.
- `@dataclass class Carcass: width_mm: float; height_mm: float; depth_mm: float;
  default_thickness_mm: float; root: Bay` + the value guards.
- `SCHEMA_VERSION: int = 1`.

`match` on the `Bay` and `SplitRule` unions in `to_dict`, `from_dict`, and
`_place`. In `from_dict`, `match` on the narrowed `kind` / `type` string after
`isinstance` shape checks; unknown values fall through to `raise ValueError`.

JSON (exact, `Carcass.to_dict()` output):
```json
{
  "schema_version": 1,
  "carcass": {
    "width_mm": 900.0, "height_mm": 1800.0, "depth_mm": 300.0,
    "default_thickness_mm": 18.0,
    "root": {
      "kind": "split", "id": "<uuid>", "orientation": "horizontal",
      "children": [
        {"kind": "leaf", "id": "<uuid>"},
        {"kind": "split", "id": "<uuid>", "orientation": "vertical",
         "children": [
           {"kind": "leaf", "id": "<uuid>"},
           {"kind": "leaf", "id": "<uuid>"},
           {"kind": "leaf", "id": "<uuid>"}
         ],
         "rules": [{"type": "fill"}, {"type": "fill"}, {"type": "fill"}],
         "dividers": [{"id": "<uuid>", "thickness_mm": null},
                      {"id": "<uuid>", "thickness_mm": null}]}
      ],
      "rules": [{"type": "fixed", "size_mm": 400.0}, {"type": "fill"}],
      "dividers": [{"id": "<uuid>", "thickness_mm": null}]
    }
  }
}
```

SOLVER ALGORITHM:
1. `_interior_rect(carcass)`: `t = carcass.default_thickness_mm`;
   `Rect(x_mm=t, z_mm=t, width_mm=carcass.width_mm - 2*t,
   height_mm=carcass.height_mm - 2*t)`. If `width_mm <= EPS_MM` or
   `height_mm <= EPS_MM` -> `LayoutSolveError(node_id=carcass.root.id,
   reason="overflow", detail={"width_mm": w, "height_mm": h, "thickness_mm": t})`.
2. `_place(bay, rect, out)`:
   - `Leaf`: `out[bay.id] = rect`; return.
   - `Split`: `out[bay.id] = rect`. `axis_span_mm = rect.height_mm` if
     `HORIZONTAL` else `rect.width_mm`. `ts = _effective_thicknesses(bay,
     carcass.default_thickness_mm)`. `sizes = distribute(axis_span_mm,
     bay.rules, ts, node_id=bay.id)`. For each `size, child` pair: if
     `size <= EPS_MM` -> `LayoutSolveError(reason="nonpositive_opening",
     node_id=child.id, detail={"size_mm": size})`. Then walk the axis from the
     low edge: place child 0 in `[low, low+sizes[0]]` (full cross-axis extent),
     then divider 0 of thickness `ts[0]` in the next slot (its `Rect` recorded
     in `out`), then child 1, etc. Recurse `_place` into each child with its
     computed `Rect`.
3. `solve` returns `SolvedLayout(rect_by_id=out)` (wrap the dict so it is
   read-only from outside; internal build uses a plain `dict[str, Rect]`).

`EPS_MM = 1e-6`. Float millimetres throughout. No `round`, `Decimal`, or
quantisation.

DISTRIBUTE (pure, no tree/Rect/Carcass): per the Must Have. Test it directly
with literal numbers: `distribute(1000.0, [Fixed(400.0), Fill()], [18.0],
node_id="x")` -> `[400.0, 582.0]`; `distribute(300.0, [Fill(), Fill(),
Fill()], [18.0, 18.0], node_id="x")` -> `[88.0, 88.0, 88.0]`;
`distribute(100.0, [Fixed(200.0), Fill()], [0.0], node_id="x")` raises
`reason="overflow"`; `distribute(100.0, [Fixed(30.0), Fixed(40.0)], [0.0],
node_id="x")` raises `reason="no_slack_absorber"`.

DEMO: `tools/layout_demo.py`, `python tools/layout_demo.py` from repo root, no
argparse. Build one `Carcass` in code, `solve` it, walk the tree printing
`f"{indent}{node.id[:8]} {kind} rect=({r.x_mm:.1f},{r.z_mm:.1f},{r.width_mm:.1f},{r.height_mm:.1f})"`
plus the rule for split children. Exit 0. Add `demo = "python
tools/layout_demo.py"` under `[tasks]` in `pixi.toml`.

TESTS live in `shelving_core/tests/` (they test `shelving_core`, are
FreeCAD-free, part of the package contract, unlike the repo-root `tests/`
harness-CLI suite). `./test.sh --fast` already runs `pytest shelving_core
tests`. For the nested `test_solver.py` case pick round numbers (exterior
900x1800, `default_thickness_mm` 18, a `HORIZONTAL` split `[Fixed(400.0),
Fill()]`, the `Fill` child a `VERTICAL` `[Fill(), Fill(), Fill()]`) and assert
every `Rect` with `pytest.approx(abs=1e-6)`. `test_schema.py` uses
`jsonschema` (dev extra) for validation and meta-validation.

ARCHITECTURE DOC: scoped edit of `docs/architecture.md` per the Must Have.
Rename the core data type `Unit` -> `Carcass` in the "### The split-tree", "###
The spacing solver", and "### Carcass expansion" subsections; leave every
`ShelvingUnit` (the FreeCAD scripted object) reference untouched. N-ary
rewrite + the `default_thickness_mm` sentence + the `_mm` convention note. No
other prose restyled.

Friction log: record any workaround per `CLAUDE.md`.

## Execution Plan

- [x] **Step 1** (`shelving_core/layout.py`, `shelving_core/layout.schema.json`): Implement the data model per TYPE SHAPES: `Orientation` (`StrEnum`), `Fixed`/`Weighted`/`Fill`, `Leaf`/`Divider`/`Split`/`Carcass`, `Bay` / `SplitRule` aliases, `new_id`, `SCHEMA_VERSION`, all `__post_init__` validation. Then the `TypedDict` doc shapes and `Carcass.to_dict` / `from_dict` (classmethod, `Mapping[str, object]` input, `match`-based narrowing, real-constructor reconstruction, `ValueError` on bad `schema_version` / `kind` / `type` / shape) / `to_json` / `from_json`. Author `layout.schema.json` (Draft 2020-12) to match the exact doc shape with `additionalProperties: false` and the numeric bounds. No `from __future__ import annotations`; `list["Bay"]` is the only forward ref.

- [x] **Step 2** (`shelving_core/solver.py`): Implement `Rect` (frozen), `SolvedLayout` (frozen, read-only `rect_by_id` + `__getitem__`), `EPS_MM`, `SolveErrorReason`, `LayoutSolveError`, the `distribute` pure function, the `_interior_rect` / `_effective_thicknesses` / `_place` helpers, and the `solve` orchestrator, per SOLVER ALGORITHM and DISTRIBUTE. Imports from `shelving_core.layout` only.

- [x] **Step 3** (`pyproject.toml`): Add `jsonschema` to `[project.optional-dependencies] dev`. No other dependency changes.

- [x] **Step 4** (`shelving_core/tests/test_layout.py`): Tests per the Must Have "Tests" bullet for `test_layout.py`, including a `>= 3`-child split in the round-trip case.

- [x] **Step 5** (`shelving_core/tests/test_solver.py`): Tests per the Must Have "Tests" bullet for `test_solver.py`: the 3-way even `Fill` split, fixed+fill, weighted 2:1, direct `distribute` tests (values from DISTRIBUTE), the nested `Rect` case via `pytest.approx(abs=1e-6)`, the carcass inset, and one test per `LayoutSolveError` reason asserting `.reason` and `.node_id`.

- [x] **Step 6** (`shelving_core/tests/test_schema.py`): Meta-validate `layout.schema.json`; assert `to_dict` output for sample trees (nested, `>= 3`-child) validates against it; assert a corpus of invalid docs each fail validation. Uses `jsonschema`.

- [x] **Step 7** (`tools/layout_demo.py`, `pixi.toml`, `README.md`): Write the demo per DEMO. Add the `demo` `[tasks]` entry to `pixi.toml`. Add the `pixi run demo` line to `README.md`. Run `python tools/layout_demo.py`; confirm exit 0 and a readable tree dump. Run `bash tools/vendor-core.sh` and commit the refreshed vendored copy (now including `layout.py`, `solver.py`, `layout.schema.json`).

- [x] **Step 8** (`docs/architecture.md`): Apply the ARCHITECTURE DOC edit: N-ary rewrite of the split-tree subsection, `Unit` -> `Carcass` rename in the three named subsections, the `default_thickness_mm` sentence, the `_mm` convention note. Nothing else changes.
