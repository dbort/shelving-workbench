# sh-003 Review — Round 1

**Verdict:** REJECTED

Both verification tiers pass on `sh-003` (`./test.sh --fast` in `.venv`,
Python 3.14: 49 passed; `pixi run full`, Python 3.12: 49 passed, workflow
lint OK, FreeCAD smoke OK). The solver math is correct: the nested
`HORIZONTAL`-then-`VERTICAL` sample re-derives by hand to exactly the rects
asserted in `test_solver.py:142-150` (interior 864x1764 at (18,18); `a`
400 tall; `d0` at z=418; `inner` 1346 tall at z=436; three 276-wide
children at x=18/312/606 with 18-wide dividers at x=294/588). Dependency
hygiene, the scope guard, the `from __future__` prohibition, the JSON
Schema, and the vendored copy all check out. Two findings block approval.

## Blocking findings

- **F1: `solve` inlines the placement geometry instead of calling a
  standalone `_place` helper** (`shelving_core/solver.py:168-232`): the
  Must Have requires `solve` to be "a thin orchestrator: it calls small,
  individually testable helpers and does not inline the geometry. At
  minimum: `_interior_rect(carcass) -> Rect`, `distribute(...)`, a
  `_place(bay, rect, out)` recursion, and `_effective_thicknesses(...)".
  `_interior_rect`, `_effective_thicknesses`, and `distribute` are
  module-level and individually testable, but `_place` is a nested `def`
  inside `solve` (`solver.py:172`) with signature `(bay, rect)`, closing
  over `out` and `carcass`. The consequence is the one the Must Have was
  written to prevent: all ~60 lines of cursor-walking, child-rect, and
  divider-rect geometry live in `solve`'s body, and no test can exercise
  the recursion against a hand-built `Rect` without going through a whole
  `Carcass`. Lift it to a module-level `_place(bay, rect, out,
  default_thickness_mm)` (or equivalent explicit-parameter form; the
  `carcass.default_thickness_mm` capture is the only other closed-over
  value) so `solve` becomes the inset-plus-recurse orchestrator the plan
  specifies, and add at least one test that calls `_place` directly with a
  literal parent `Rect` and asserts the child and divider rects it records
  — mirroring how `distribute` is already tested directly with literal
  numbers (`test_solver.py:83-98`).

- **F2: `tools/layout_demo.py` has no automated coverage** (`tools/layout_demo.py:1-110`,
  `pixi.toml:26`, `README.md:10-13`): the Must Have's "`python
  tools/layout_demo.py` exits 0" is currently verifiable only by running
  the script by hand. I did run it (and `pixi run demo`) — both exit 0 and
  print a correct tree, with the root `[Weighted(1), Fixed(500)]` split
  yielding a 1246 mm top bay as expected — but that check leaves no trace
  and nothing re-runs it. Neither tier touches the demo: `test.sh`'s
  `run_fast` is `ruff`/`mypy`/`vendor-core --check`/`pytest shelving_core
  tests`, and `[tool.mypy] files = ["shelving_core"]` excludes `tools/`, so
  the only thing guarding a documented entry point wired into `README.md`
  and a `pixi` task is lint. A refactor of `solve`, of the `sys.path`
  bootstrap, or of any name the demo imports breaks `pixi run demo`
  silently. This repo already has the pattern for exactly this:
  `tests/test_harness_cli.py` subprocess-tests `test.sh`'s CLI contract,
  and its module docstring states the rationale ("Those behaviors are
  load-bearing, so they get real coverage here instead of being re-derived
  by hand each review round"). Add a fast-tier test in `tests/` that runs
  `[sys.executable, "tools/layout_demo.py"]` from the repo root as a
  subprocess, asserts `returncode == 0`, and asserts something about the
  output beyond emptiness (e.g. the `Carcass 900 x 1800 x 300 mm` header
  line and that the expected number of `leaf` / `divider` / `split` lines
  appear). It needs no live infrastructure, so it belongs in the fast tier,
  not `--full`.

## Non-blocking notes

- **N1: an all-`Fixed` overflowing split reports `no_slack_absorber`, not
  `overflow`** (`shelving_core/solver.py:112-125`): the `if not driven:` /
  `elif slack_mm < -EPS_MM:` ordering means a split whose fixed sizes
  exceed the span and which has no driven rule raises
  `reason="no_slack_absorber"` even though the failure is an overflow. The
  Must Have states the overflow condition unqualified ("or when `slack <
  -EPS_MM`") and the `no_slack_absorber` condition as "no `Weighted`/`Fill`
  rules and `abs(slack) > EPS_MM`", so both match and the plan does not
  state precedence; either ordering is defensible, but the current one
  reports the less informative reason. No test pins the behavior in either
  direction. Pick the precedence deliberately and add a test for the
  all-`Fixed`-overflow case.

- **N2: `Any` in `test_schema.py` lacks a why-comment at the boundary**
  (`shelving_core/tests/test_schema.py:10,28,80-134`): CLAUDE.md's Typed
  Python obligation permits `Any` at a genuine type-erasing boundary
  (parsed external JSON, an untyped third-party API) "and then with a
  comment saying why", and the task's Frontier Advice narrows the permitted
  `Any`/`object` to `from_dict`'s input. The uses here do sit on that
  boundary (parsed JSON that the corruption helpers subscript through
  several levels, plus untyped `jsonschema`), and the comment at line 81-82
  explains the mutable-`dict`-over-`CarcassDoc` choice, but it does not say
  why `Any` rather than `object`. Add one line at `_schema()` (line 28)
  naming the boundary, or narrow `_schema()` to `Mapping[str, object]`
  since it is only handed to `jsonschema`.

- **N3: `docs/architecture.md` now contradicts itself on N-ary splits**
  (`docs/architecture.md:30,71`): the "### The split-tree" rewrite is
  correct, but the v1-delivers bullet still says a bay "is divided
  horizontally or vertically into two child bays" and the Decisions of
  record table still says "Recursive binary split-tree". The task scoped
  the edit to three `###` subsections and said "No other restyling", so
  leaving these is compliant with the letter of the plan; flagging so a
  human can decide whether to fold the two-line fix into this task or open
  a follow-up.

- **N4: `tools/layout_demo.py` is not type-checked** (`pyproject.toml:31`):
  `[tool.mypy] files = ["shelving_core"]`, so the demo's annotations
  (including the `match`-exhaustive `_rule_label`) are never verified. Not
  required by the Must Have; worth considering alongside F2 if the demo
  gains a test.

- **N5: `sys.path` bootstrap differs slightly from its stated model**
  (`tools/layout_demo.py:20`): the pattern matches `tools/freecad_smoke.py`
  as intended and is acceptable, but the smoke script guards with `if
  _REPO_ROOT not in sys.path:` before inserting. Matching that guard keeps
  the two copies identical, which matters given the friction-log entry
  predicting more repo-root scripts will copy this stanza.
