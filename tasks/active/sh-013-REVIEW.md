# sh-013 Review — Round 2

**Verdict:** REJECTED

`pixi run tests` is green on the branch tip (121 passed; ruff, `ruff format
--check`, `mypy --strict` over 30 files, the vendored-core drift check, the
workflow lint, and the `freecad_smoke.py` OK marker all pass). Every
`## Must Have` line still checks out against the diff, and round 1's two
blocking findings are resolved:

- **F1 (spike unimportable) — fixed.** `spikes/plain_planks/carcass_model.py`
  carries the pre-deletion carcass model, all five spike modules import from it
  instead of the deleted `shelving_core` names, and
  `tests/test_spike_importable.py` makes `pixi run tests` fail the next time a
  rename breaks the package, so the guard is durable rather than a one-off
  manual import. Block-by-block comparison against `git show
  main:shelving_core/{layout,solver,expand}.py` shows the carcass types,
  `_interior_rect`, `_effective_thicknesses_mm`, `_place`, `solve`, `expand`,
  and `_append_divider_specs` carried over with their logic intact.
- **F2 (README demo paragraph) — fixed** (`README.md:17-19`).

Round 1's non-blocking notes N1-N5 are all addressed as well (`tops_mm` /
`expected_mm3`, the "used to" framing, the `Vec3` docstring's frame,
`_resolve_with_next` now raising `LayoutSolveError` with a test pinning it, and
the `docs/architecture.md` banner).

The findings below are the same class as round 1's F2 — a statement this branch
made false — in two places the round-2 pass did not reach. One of them is
created by the round-2 banner fix itself.

## Blocking findings

- **F1: `docs/freecadcmd-notes.md` points at a deleted script**
  (`docs/freecadcmd-notes.md:4-5`): "`pixi run tests` uses it for
  `tools/freecad_smoke.py` and `tools/freecad_object_smoke.py`". Step 1 deleted
  `tools/freecad_object_smoke.py` and removed its block from
  `tools/run-tests.sh:51+`, so the named file no longer exists anywhere in the
  tree and `pixi run tests` drives exactly one `freecadcmd` script. The
  sentence is the document's opening claim about what the harness runs, and a
  reader following the path finds nothing. `docs/manual-qa.md:8` got the
  equivalent repoint in step 1; this file was missed. Nothing else in
  `docs/freecadcmd-notes.md` depends on the deleted script: the rest of that
  paragraph and the exit-status section already cite `tools/freecad_smoke.py`
  and `tools/run-tests.sh`, so dropping the second name is the whole fix.

- **F2: `README.md` claims `docs/architecture.md` describes the current code,
  which this branch's own edit denies** (`README.md:14-15`,
  `README.md:63-64`, against `docs/architecture.md:3-9`). The README says
  "[`docs/architecture.md`](docs/architecture.md) describes the design the code
  implements today", and the Glossary preamble introduces the region-model
  vocabulary as "how each term maps onto the code in `shelving_core`, which
  follows [`docs/architecture.md`](docs/architecture.md)". Both were true on
  `main`; commit 1889faf rewrote the `architecture.md` banner to say it
  describes the design "implemented before the region-model rewrite
  (`docs/roadmap.md` M4) ... not because the rest of the document still matches
  the code". So the front page now asserts the opposite of the document it
  links to, and the glossary it introduces defines `Region`, `Bay`, `Void`,
  `Division`, `Insets`, `Basis`, and `BoardSpec`, none of which appear in
  `architecture.md` at all. Two sentences, both in files this branch already
  rewrites; point them at `docs/scope-and-design.md` (the design of record per
  the banner) or state plainly that `architecture.md` is the superseded
  pre-M4 design.

## Non-blocking notes

- **N1: `carcass_model.py` overstates how verbatim it is**
  (`spikes/plain_planks/carcass_model.py:8-10`): "a byte-for-byte copy of what
  those modules held immediately before that deletion ... minus the JSON
  interop layer nothing here calls". Diffing the module's top-level blocks
  against `git show main:shelving_core/{layout,solver,expand}.py` shows three
  further differences: `Divider.lap` and its `LapOrder` type are dropped, and
  the docstrings on `_place`, `expand`, `_append_divider_specs`, and `Split`
  are trimmed or rewrapped. Dropping `lap` is the right call (it is the
  reserved-and-dead member the task file calls out, and nothing read it), but
  the claim sends a maintainer looking for an empty diff they will not find.
  "A copy of ... minus the JSON interop layer and the reserved `Divider.lap`"
  is accurate.

- **N2: `Space`'s docstring has a grammatical slip**
  (`shelving_core/geometry.py:28`): "a minimum corner ``origin`` plus an
  ``size`` extent" reads "an size".

- **N3: stale vocabulary in the README's opening paragraph** (`README.md:9`):
  "expands into individually editable 3D plank solids". The task settles
  `Board` as the name and the new glossary says user-facing documentation
  calls the same thing a panel, so "plank" survives here only in the sentence
  that introduces the project. The object layer that produced those solids is
  also gone until M6, which makes the present tense generous, though that part
  reads as product intent rather than a claim about today's code.

- **N4: the spike guard covers imports but `spikes/` stays outside both mypy
  and pytest** (`pyproject.toml:35-41`, `tools/run-tests.sh:40`,
  `tests/test_spike_importable.py`): the 369 new lines of
  `spikes/plain_planks/carcass_model.py` are linted by `ruff check .` but not
  type-checked, and `test_general_model.py` / `test_scan.py` are imported
  without their bodies ever running, so a behavioural break in the vendored
  model would pass the checks. That matches what round 1 asked for (an import
  or collection guard) and the task's Must Have scopes `mypy --strict` to
  `shelving_core/`, `tools/`, `tests/`, and `freecad/shelving/`, so this is not
  a finding against the branch. It is worth a sentence in whatever task
  decides the spike's fate before M6, since `pixi run tests` running `pytest
  spikes` is the durable version of the check.
