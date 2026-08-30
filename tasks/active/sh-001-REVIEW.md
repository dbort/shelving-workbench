# sh-001 Review — Round 1

**Verdict:** REJECTED

Both verification tiers pass on `sh-001` (`3410902`): `./test.sh --fast` in
`.venv` exits 0, and `pixi run full` exits 0 running the fast sequence, then
`tools/lint-workflows.sh`, then the `freecadcmd` smoke, in that order. Every
`## Must Have` behavior named in this pass's rework is present in the code and
behaves correctly when exercised by hand. The single blocking finding is that
none of that hand-exercising is captured by a committed test.

## Blocking findings

- **F1: `test.sh`'s exit-status contract has no automated coverage**
  (`test.sh:26-46`, `test.sh:58-87`): the harness's usage, preflight, and
  FreeCAD-missing behaviors are enumerated as `## Must Have` conditions and are
  load-bearing for the pipeline (agents distinguish exit 2, exit 3, and a tool's
  own status), yet the only way to verify them is to run `test.sh` by hand with
  a doctored `PATH`. Confirming them this round required building a symlink farm
  of the pixi env's binaries minus `freecadcmd` and several `env -i PATH=...`
  invocations; none of that is committed, so nothing re-runs it and every future
  reviewer repeats it from scratch. Concretely uncovered:
  - no argument, an unknown flag, and two flags each exit 2 with the usage line
    (`test.sh:26-29`, `test.sh:58`, `test.sh:84-86`);
  - `--fast` preflights exactly `ruff mypy pytest` and `--full` preflights
    exactly `ruff mypy pytest actionlint zizmor check-jsonschema shellcheck`,
    exiting 3 with every missing tool named and the `tools/install-deps.sh` /
    `pixi shell` pointer (`test.sh:34-46`, `test.sh:62`, `test.sh:68`);
  - `--full` with `freecadcmd` absent exits 1 with the exact string
    `ERROR: freecadcmd not found on PATH. FreeCAD 1.0+ is required for the full
    test tier; see README.md.` (`test.sh:71-74`).

  This is pure shell logic, so it belongs in the fast tier as a real test, not
  in the full tier's live-FreeCAD harness. Two wrinkles the fix has to handle,
  noted so the next round does not discover them the hard way:
  1. **Recursion.** `run_fast` invokes `pytest shelving_core`, so a test that
     shells out to `./test.sh --fast` or a `--full` run that gets past the
     preflight re-enters pytest. Drive the usage and preflight cases with a
     `PATH` that makes `preflight` exit before `run_fast` is reached (that is
     what makes them cheap and safe), and cover the exact `freecadcmd` message
     some other way that cannot recurse: asserting the literal string and the
     `exit 1` in `test.sh`'s source is acceptable here (the repo already uses a
     source-scan test in `shelving_core/tests/test_no_freecad.py`), as is an
     explicit no-recursion escape hatch in the harness.
  2. **Placement.** `test.sh:55` runs `pytest shelving_core`, and
     `shelving_core` is the FreeCAD-free package that ships in the wheel
     (`pyproject.toml:26-27`); harness tests are not part of that package's
     contract. Prefer a repo-root `tests/` directory with `test.sh` invoking
     `pytest shelving_core tests`, or state in the task file why the harness
     tests live inside `shelving_core/tests/` instead.

## Non-blocking notes

- **N1: the pin-format check only globs `*.yml`** (`tools/lint-workflows.sh:41`):
  a workflow added as `.github/workflows/foo.yaml` is still seen by `actionlint`
  and `zizmor` (both take the directory) but silently escapes the
  `owner/repo@<40-hex> # vX.Y.Z` check. Widening the glob to `*.yml` and `*.yaml`
  closes it. Fold into whatever round addresses F1.
- **N2: `rsync` is not preflighted** (`test.sh:34-46`, `tools/vendor-core.sh:32`):
  the vendor-drift step shells out to `rsync`, so a host without it fails mid-tier
  with a bare status 127 rather than the exit-3 message that names the missing
  tool. Either add `rsync` to both preflight lists or note that it is assumed
  present.

## Verification run this round

- `./test.sh --fast` in `.venv` (Python 3.14): exit 0, 3 tests passed.
- `pixi run full`: exit 0. Order confirmed from the output and from
  `test.sh:65-83`: ruff, ruff format, mypy, vendor drift, pytest, then
  `actionlint` / `zizmor` / pin format / dependabot schema, then the FreeCAD
  smoke line.
- `pixi run lint-workflows` standalone: exit 0. `pixi lock --check`:
  lock already up to date; `pixi.toml` and `pixi.lock` are untouched this pass.
- `.github/workflows/ci.yml` has exactly the `fast` and `full` jobs; the
  standalone `workflows` job is gone and the diff against the previously
  approved commit removes nothing else. `permissions: {}` at workflow level with
  per-job `contents: read`, harden-runner first in both jobs and in
  `scorecard.yml`, SHA pins with `# vX.Y.Z` comments on every `uses:` (enforced
  by the pin check), the injection-rule comment, and the concurrency block all
  remain.
- `docs/roadmap.md:22` still reads `**Status:** Task sh-001`; no domain code
  (`ShelvingUnit`, solver, expansion, catalog, task panel) anywhere in the tree.
- `README.md` and `docs/github-actions-hardening.md` describe `--full` as the
  single "run everything" command and a superset of `--fast`, CI reaching
  `lint-workflows.sh` through the `full` job, and `pixi run lint-workflows` as a
  granular shortcut.
