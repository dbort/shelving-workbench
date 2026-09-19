# sh-013 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green on the branch tip (114 passed; ruff, `mypy
--strict` over 29 files, vendor drift check, workflow lint, and the
`freecad_smoke.py` OK marker all pass), and every `## Must Have` line
checks out against the diff: the exports and the forbidden-identifier grep,
`geometry.Space`, `solve`/`expand` signatures and coverage, the hard-coded
carcass-equivalence values (they match `main`'s
`test_bare_leaf_emits_four_shell_planks` exactly), the stepped-unit,
adjacent-board, basis, and four error-reason tests, every required
deletion, the rebuilt demo test, the M3 removal from `docs/manual-qa.md`,
and the workbench import smoke. The findings below are about collateral the
plan's Must Have list does not cover.

## Blocking findings

- **F1: the branch leaves `spikes/plain_planks/` unimportable**
  (`spikes/plain_planks/general_model.py:30-33`,
  `spikes/plain_planks/scan.py:28-39`,
  `spikes/plain_planks/test_general_model.py:11-14`,
  `spikes/plain_planks/test_scan.py:12-21`,
  `spikes/plain_planks/freecad_spike.py:36-44`): all five modules import
  names this branch deletes — `PlankRole`, `PlankSpec` from
  `shelving_core.expand`; `Carcass`, `Divider`, `Leaf`, `Split`,
  `Orientation`, `SplitRule` from `shelving_core.layout`; `Rect` from
  `shelving_core.solver`. Evidence: the import lines above name each of
  them, and `grep -rn 'class Carcass\|class Rect\|PlankSpec\|PlankRole\|
  Orientation\|SplitRule' shelving_core/*.py` returns nothing, so the
  package now raises `ImportError` at import time. Nothing in the checks
  covers it (`tools/run-tests.sh:40` runs `pytest shelving_core tests`, and
  `pyproject.toml:36-41` keeps `spikes/` out of mypy's `files`), which is
  why this passed silently. The task's `## Frontier Advice` calls the spike
  CRITICAL, says "do NOT move or delete them", and gives the reason: it is
  "the only way to look at a layout while the workbench has no commands,
  and M6 deletes it". Files that cannot be imported do not satisfy that
  intent. Either port the spike's `shelving_core` imports onto the surface
  that survives (`Vec3`, `Fill`, `Fixed`, `new_id`, `EPS_MM`,
  `LayoutSolveError`, `distribute` are all still there; the carcass types
  are not, and `general_model.py` defines its own model anyway), or, if
  that is out of scope, stop and say so rather than shipping a dead
  package: record the conflict in the task file and hand it back for a
  scope decision. Whichever way it goes, the reason it went unnoticed is
  that no check imports `spikes/`; if the spike is meant to stay alive
  until M6, the fix needs a durable automated guard inside `pixi run tests`
  (an import or collection of `spikes/plain_planks/`), not a one-off manual
  `python -c 'import ...'`.

- **F2: `README.md` still describes the demo as a carcass demo**
  (`README.md:17-19`): "it builds a sample nested carcass, runs the spacing
  solver, and prints the resulting rectangle for every bay and divider".
  Step 10 rebuilt `tools/layout_demo.py` on the region model: it builds a
  stepped `Unit` of three columns (`tools/layout_demo.py:88-113`) and
  prints a `Space` per region plus a board table
  (`tools/layout_demo.py:157-186`). The sentence was true on `main` and
  this branch made it false, in the paragraph that introduces `pixi run
  demo` on the repo's front page, using three terms (carcass, divider,
  rectangle) the same branch deletes from the glossary below it. Step 2
  left the paragraph alone on purpose, correctly for that step, but step 10
  then invalidated it and nothing picked it back up.

## Non-blocking notes

- **N1: unit suffixes missing on two test locals**
  (`shelving_core/tests/test_expand.py:130`,
  `shelving_core/tests/test_expand.py:183`): `tops` is a list of millimetre
  heights and `expected` is a cubic-millimetre volume, so under `CLAUDE.md`
  § Project conventions (which covers locals explicitly) they read
  `tops_mm` and `expected_mm3`.

- **N2: reader-memory framing in the new glossary entry** (`README.md:69`):
  "the outermost boards of the outermost divisions are what a carcass used
  to name specially" states the current design by comparison to the deleted
  one, which `CLAUDE.md` § Writing style rules out ("no reader-memory
  framing ... 'used to'"). The point survives as a plain statement: there is
  no distinguished shell, the outermost boards of the outermost divisions
  are the shell.

- **N3: stale vocabulary in the moved `Vec3` docstring**
  (`shelving_core/geometry.py:19`): "A point or an extent in the carcass
  local frame" contradicts the module docstring four lines above it, which
  says "the unit's local frame". Step 3 did say to move the docstring
  verbatim, so this is the plan's wording carried forward rather than a new
  mistake, but "carcass" no longer names anything.

- **N4: `WITH_NEXT` can escape as `ValueError`, not `LayoutSolveError`**
  (`shelving_core/solver.py:176`): when the next board is at least as thick
  as the quoted spacing, `Fixed(size_mm=rule.size_mm - next_thickness_mm)`
  hits `Fixed.__post_init__`'s `size_mm > 0` check
  (`shelving_core/layout.py:57-58`) and raises `ValueError`, bypassing the
  `LayoutSolveError` contract that `solve`'s callers are told to catch. A
  `nonpositive_opening` (or `unresolvable_basis`) raise against the
  region's id would keep the failure surface uniform; worth a test either
  way, since nothing currently pins the behaviour.

- **N5: `docs/architecture.md:3-9`'s superseded banner is now wrong**: it
  claims the document "is still an accurate description of the code until
  the rewrite lands", and this branch is that rewrite landing — the object
  layer, the split tree, and the plank types it describes are gone. Out of
  this task's declared scope, so fix it here only if it is cheap; otherwise
  it wants its own task before the banner misleads someone.
