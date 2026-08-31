---
id: sh-003
title: "Layout engine: split-tree, JSON, spacing solver (M1)"
current_agent: implementer
current_phase: planning
review_rejections: 0
---

# sh-003: Layout engine: split-tree, JSON, spacing solver (M1)

## Summary
Build the pure-Python heart of the Shelving Workbench: an N-ary recursive
split-tree data model with JSON round-tripping, and a spacing solver that turns
a tree plus a unit's outer dimensions into a concrete 2D rectangle for every
bay and divider, distributing slack by fixed / weighted / fill rules and raising
a structured error when a layout cannot be satisfied. No FreeCAD, no materials,
no 3D; those arrive in M2 and M3.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have

### Data model (`shelving_core/layout.py`)
- [ ] Defines: `Orientation` (an `enum.Enum` with `HORIZONTAL` and `VERTICAL`); rule classes `Fixed` (field `size: float`), `Weighted` (field `weight: float`), `Fill` (no fields); node classes `Leaf` (field `id: str` only), `Divider` (fields `id: str`, `thickness: float | None`), `Split` (fields `id: str`, `orientation: Orientation`, `children: list[Bay]`, `rules: list[SplitRule]`, `dividers: list[Divider]`); `Unit` (fields `width: float`, `height: float`, `depth: float`, `default_thickness: float`, `root: Bay`). Type aliases `Bay = Leaf | Split` and `SplitRule = Fixed | Weighted | Fill`. Module constant `SCHEMA_VERSION = 1`. Function `new_id() -> str` returning `str(uuid.uuid4())`; every node's `id` field defaults to `field(default_factory=new_id)`.
- [ ] Tree nodes (`Leaf`, `Split`, `Divider`, `Unit`) are mutable dataclasses; rule classes may be frozen or not.
- [ ] `Split` validates at construction (`__post_init__`): `len(children) == len(rules)` and `len(children) >= 2` and `len(dividers) == len(children) - 1`; any violation raises `ValueError`.
- [ ] Construction validation, each raising `ValueError`: `Unit.width`, `Unit.height`, `Unit.depth` all `> 0`; `Unit.default_thickness >= 0`; `Fixed.size > 0`; `Weighted.weight > 0`; `Divider.thickness` is `None` or `>= 0`.
- [ ] `to_dict(unit: Unit) -> dict` and `from_dict(data: dict) -> Unit` round-trip any tree, preserving every node `id`, every rule (type and value), and every divider thickness (including `None`) exactly. The emitted dict has top-level key `"schema_version"` equal to `1` and a `"unit"` sub-object. `dumps(unit) -> str` / `loads(s: str) -> Unit` are thin `json` wrappers over those.
- [ ] `from_dict` raises `ValueError` on: a `schema_version` other than `1`; an unknown bay `kind`; an unknown rule `type`.
- [ ] JSON shape is exactly: bay objects carry `"kind": "leaf" | "split"`; a split carries `"orientation": "horizontal" | "vertical"`, `"children"`, `"rules"`, `"dividers"`; rule objects are `{"type": "fixed", "size": <n>}` / `{"type": "weighted", "weight": <n>}` / `{"type": "fill"}`; divider objects are `{"id": <s>, "thickness": <n> | null}`.

### Solver (`shelving_core/solver.py`)
- [ ] Defines: `Rect` (frozen dataclass, fields `x: float`, `z: float`, `width: float`, `height: float`); `SolvedLayout` (frozen dataclass wrapping `rect_by_id: dict[str, Rect]`, with `__getitem__` so `layout[node_id]` returns the `Rect`); module constant `EPS = 1e-6`; exception `LayoutSolveError(Exception)` with attributes `node_id: str`, `reason: str` (one of `"overflow"`, `"no_slack_absorber"`, `"nonpositive_opening"`), `detail: dict[str, float]`; `solve(unit: Unit) -> SolvedLayout`.
- [ ] `solve` computes the root interior rect by insetting the exterior by `default_thickness` on all four sides: `Rect(x=default_thickness, z=default_thickness, width=width - 2*default_thickness, height=height - 2*default_thickness)`. If the inset width or height is `<= 0`, raise `LayoutSolveError(node_id=<root id>, reason="overflow", detail=...)`.
- [ ] `solve` places every node: `rect_by_id` has an entry for every `Leaf` id, every `Split` id, and every `Divider` id. A `HORIZONTAL` split distributes its rect's `height` (the Z axis); a `VERTICAL` split distributes its rect's `width` (the X axis). Children are laid out in list order from the low edge of the axis (child[0] at minimum z for `HORIZONTAL`, minimum x for `VERTICAL`); dividers occupy the gaps between consecutive children and span the full cross-axis extent of the parent rect.
- [ ] Distribution algorithm per split: effective divider thickness is `divider.thickness` if not `None` else `unit.default_thickness`; `available = axis_span - sum(effective divider thicknesses)`; `fixed_sum = sum(r.size for Fixed rules)`; driven rules are `Weighted` and `Fill`, with `Fill` counting as weight `1.0`; `slack = available - fixed_sum`. If there are no driven rules, require `abs(slack) <= EPS` or raise `reason="no_slack_absorber"`. Otherwise each driven opening gets `weight / total_weight * slack`; each fixed opening gets its `size`. If `slack < -EPS`, or `available < -EPS`, raise `reason="overflow"`. If any resolved opening is `<= EPS`, raise `reason="nonpositive_opening"` with `node_id` set to the offending child bay's id.
- [ ] `LayoutSolveError.node_id` for `"overflow"` and `"no_slack_absorber"` is the offending `Split`'s id (or the root id for the carcass-inset case); for `"nonpositive_opening"` it is the child bay's id.
- [ ] The solver works entirely in float millimetres and performs no rounding.

### Tests (`shelving_core/tests/`)
- [ ] `test_layout.py` covers: each construction-validation `ValueError`; a JSON round-trip of a >= 2-level nested tree asserting id preservation and structural equality; `from_dict` rejecting a bad `schema_version`, `kind`, and rule `type`.
- [ ] `test_solver.py` covers: an even `Fill`/`Fill` split (equal openings); a `Fixed` + `Fill` split (fill absorbs the slack); a `Weighted(2)` / `Weighted(1)` split (2:1 slack ratio); a nested split (HORIZONTAL then VERTICAL) with hand-computed expected `Rect`s asserted exactly (allowing `EPS`); the carcass inset (`default_thickness` removed on all four sides); and one test per `LayoutSolveError` reason asserting `.reason` and `.node_id`.
- [ ] `./test.sh --fast` exits 0 (it runs `pytest shelving_core tests`).
- [ ] `mypy` (strict) reports no errors over `shelving_core`; `ruff check .` and `ruff format --check .` report nothing.

### Demo and docs
- [ ] `tools/layout_demo.py` builds a sample nested `Unit` (at least two split levels, a mix of `Fixed`, `Weighted`, and `Fill` rules), calls `solve`, and prints an indented tree: each node's id, kind, and solved `Rect`. `python tools/layout_demo.py` exits 0. It is not part of the `shelving_core` package (repo-root `tools/`, like `tests/`).
- [ ] `pixi.toml` has a `[tasks]` entry `demo` whose body is `python tools/layout_demo.py`.
- [ ] `README.md` mentions `pixi run demo` (or `python tools/layout_demo.py`) as the way to eyeball a solved layout.
- [ ] `docs/architecture.md` "### The split-tree" section describes N-ary splits: an orientation, an ordered list of two or more child `Bay`s, one `SplitRule` per child, and one fewer `Divider` than children. It also states that `Unit` carries a `default_thickness` used both for the carcass panels and as the divider default until M2 introduces materials. No other section of that file is restyled.

### Scope guard
- [ ] No `materials` module, no `expand` function, no `PlankSpec`, no catalog, no per-`Leaf` material or depth-override fields, no FreeCAD import anywhere in `shelving_core/`.

## Frontier Advice

CRITICAL: pure Python, standard library only (`dataclasses`, `enum`, `uuid`,
`json`, `typing`). No third-party runtime deps. `shelving_core` must never
import `FreeCAD` or `FreeCADGui` (enforced by
`shelving_core/tests/test_no_freecad.py`, which already scans the whole
package). New modules must import with no side effects.

Put `from __future__ import annotations` at the top of both modules. Target
Python 3.11+; `X | Y` unions and `match` statements are available. Use `match`
on the `Bay` and `SplitRule` unions in the solver and in `to_dict`/`from_dict`.

TYPE SHAPES (exact):
- `class Orientation(enum.Enum): HORIZONTAL = "horizontal"; VERTICAL = "vertical"`.
- `@dataclass class Fixed: size: float` (+ `__post_init__` guard `> 0`).
  `@dataclass class Weighted: weight: float` (guard `> 0`). `@dataclass class
  Fill:` (empty). `SplitRule = Fixed | Weighted | Fill`.
- `@dataclass class Leaf: id: str = field(default_factory=new_id)`.
- `@dataclass class Divider: thickness: float | None = None; id: str =
  field(default_factory=new_id)` (guard `thickness is None or thickness >= 0`).
- `@dataclass class Split: orientation: Orientation; children: list[Bay];
  rules: list[SplitRule]; dividers: list[Divider]; id: str =
  field(default_factory=new_id)` with the `__post_init__` length invariants.
- `Bay = Leaf | Split`.
- `@dataclass class Unit: width: float; height: float; depth: float;
  default_thickness: float; root: Bay` (guards as listed in Must Have).
- `SCHEMA_VERSION = 1`.

JSON (exact, `to_dict` output):
```json
{
  "schema_version": 1,
  "unit": {
    "width": 900.0, "height": 1800.0, "depth": 300.0, "default_thickness": 18.0,
    "root": {
      "kind": "split", "id": "<uuid>", "orientation": "horizontal",
      "children": [
        {"kind": "leaf", "id": "<uuid>"},
        {"kind": "split", "id": "<uuid>", "orientation": "vertical",
         "children": [{"kind": "leaf", "id": "<uuid>"}, {"kind": "leaf", "id": "<uuid>"}],
         "rules": [{"type": "fill"}, {"type": "fill"}],
         "dividers": [{"id": "<uuid>", "thickness": null}]}
      ],
      "rules": [{"type": "fixed", "size": 400.0}, {"type": "fill"}],
      "dividers": [{"id": "<uuid>", "thickness": null}]
    }
  }
}
```
`from_dict` reconstructs via the real constructors (so their validation runs).
Read ids from the JSON; never regenerate them on load. A `schema_version` key
absent or `!= 1` -> `ValueError`. A bay dict whose `"kind"` is neither `"leaf"`
nor `"split"` -> `ValueError`. A rule dict whose `"type"` is not one of the
three -> `ValueError`.

SOLVER ALGORITHM:
1. Root interior rect = exterior inset by `default_thickness` on all four
   sides. Inset width or height `<= 0` -> `LayoutSolveError(node_id=root.id,
   reason="overflow", detail={"width": w, "height": h, "thickness": t})`.
2. Recurse `place(bay, rect)`:
   - `Leaf`: `rect_by_id[bay.id] = rect`; return.
   - `Split`: `rect_by_id[bay.id] = rect`. `axis_span` = `rect.height` if
     `HORIZONTAL` else `rect.width`. `t_i` = effective divider thickness list.
     `available = axis_span - sum(t_i)`. `fixed_sum` = sum of `Fixed.size` over
     rules. `driven` = indices whose rule is `Weighted` or `Fill`;
     `weight_i` = `rule.weight` for `Weighted`, `1.0` for `Fill`;
     `total_weight = sum(weight_i for i in driven)`. `slack = available -
     fixed_sum`.
     - `available < -EPS` -> `reason="overflow"`, `node_id=split.id`.
     - `driven` empty: `abs(slack) > EPS` -> `reason="no_slack_absorber"`,
       `node_id=split.id`. Else each opening = its `Fixed.size`.
     - `driven` non-empty: `slack < -EPS` -> `reason="overflow"`. Else driven
       opening `i` = `weight_i / total_weight * slack`; fixed opening = its
       size.
     - Any resolved opening `<= EPS` -> `reason="nonpositive_opening"`,
       `node_id` = that child bay's id, `detail={"size": size}`.
   - Lay children along the axis from the low edge. For `HORIZONTAL`: child 0
     occupies `z in [rect.z, rect.z + size_0]`, full width; then a divider of
     thickness `t_0` at `z in [.., .. + t_0]`, full width; then child 1; etc.
     For `VERTICAL`: same along `x`, full height. Record each divider's `Rect`
     in `rect_by_id`. Recurse `place` into each child with its computed rect.
3. Return `SolvedLayout(rect_by_id)`.

`EPS = 1e-6`. Float millimetres throughout. No `round()`, no `Decimal`, no
quantisation anywhere in the solver.

DEMO: `tools/layout_demo.py`, runnable as `python tools/layout_demo.py` from
the repo root, no argument parsing. Build one sample `Unit` in code, `solve`
it, walk the tree printing `f"{indent}{node.id[:8]} {kind} rect=({x:.1f},
{z:.1f},{w:.1f},{h:.1f})"` plus the rule for split children. Exit 0. Add
`demo = "python tools/layout_demo.py"` under `[tasks]` in `pixi.toml`
(leave the existing `fast` / `full` / `lint-workflows` tasks untouched).

ARCHITECTURE DOC: edit only the "### The split-tree" subsection of
`docs/architecture.md`. Replace the "a split: an orientation ... and two child
`Bay`s" bullet with the N-ary description (ordered list of >= 2 child bays, one
`SplitRule` per child, one fewer `Divider` than children). Add one sentence
that `Unit` carries `default_thickness`, used for the carcass panels and as the
divider default, until M2's materials. Do not touch other sections, do not
restyle surrounding prose.

TESTS live in `shelving_core/tests/` (they test `shelving_core`, are
FreeCAD-free, and are part of the package's contract, unlike the repo-root
`tests/` harness-CLI suite). `./test.sh --fast` already runs
`pytest shelving_core tests`, so no `test.sh` change is needed. For the nested
`test_solver.py` case, pick round numbers (e.g. exterior 900x1800,
`default_thickness` 18, a `HORIZONTAL` split `[Fixed(400), Fill]`, the `Fill`
child a `VERTICAL` `[Fill, Fill]`) and assert every resulting `Rect` exactly
with `pytest.approx(..., abs=1e-6)`.

CLAUDE.md Standing task-planning obligations: the list has no active entries;
nothing to satisfy or opt out of.

Friction log: record any workaround per CLAUDE.md.

## Execution Plan

- [ ] **Step 1** (`shelving_core/layout.py`): Implement the full data model per the TYPE SHAPES block: `Orientation`, `Fixed`/`Weighted`/`Fill`, `Leaf`/`Divider`/`Split`/`Unit`, `Bay` and `SplitRule` aliases, `new_id`, `SCHEMA_VERSION`, and all `__post_init__` validation. Then `to_dict`, `from_dict`, `dumps`, `loads` per the JSON block, with `from_dict` going through the real constructors and raising `ValueError` on bad `schema_version` / `kind` / rule `type`. `from __future__ import annotations`; `match` on the unions in the (de)serialisers.

- [ ] **Step 2** (`shelving_core/solver.py`): Implement `Rect` (frozen), `SolvedLayout` (frozen, `rect_by_id` + `__getitem__`), `EPS`, `LayoutSolveError`, and `solve` per the SOLVER ALGORITHM block. Imports from `shelving_core.layout` only. No FreeCAD, no rounding.

- [ ] **Step 3** (`shelving_core/tests/test_layout.py`): Tests per the Must Have "Tests" bullet for `test_layout.py`: one assertion per construction-validation `ValueError`, a nested-tree JSON round-trip checking id preservation and structural equality, and `from_dict` rejection of bad `schema_version` / `kind` / rule `type`.

- [ ] **Step 4** (`shelving_core/tests/test_solver.py`): Tests per the Must Have "Tests" bullet for `test_solver.py`: even fill, fixed+fill slack, weighted 2:1, the nested HORIZONTAL-then-VERTICAL case with every `Rect` asserted via `pytest.approx(abs=1e-6)`, the carcass inset, and one test per `LayoutSolveError` reason (`overflow`, `no_slack_absorber`, `nonpositive_opening`) asserting `.reason` and `.node_id`.

- [ ] **Step 5** (`tools/layout_demo.py`, `pixi.toml`, `README.md`): Write the demo script per the DEMO block. Add `demo = "python tools/layout_demo.py"` to `pixi.toml` `[tasks]`. Add a line to `README.md` pointing at `pixi run demo`. Run `python tools/layout_demo.py` and confirm exit 0 with a readable tree dump.

- [ ] **Step 6** (`docs/architecture.md`): Apply the ARCHITECTURE DOC edit: rewrite the split-tree bullet to N-ary and add the `default_thickness` sentence. Nothing else in the file changes.
