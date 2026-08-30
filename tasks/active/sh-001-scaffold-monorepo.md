---
id: sh-001
title: "Scaffold monorepo with hardened CI and reproducible env (M0)"
current_agent: user
current_phase: user_signoff
review_rejections: 1
---

# sh-001: Scaffold monorepo with hardened CI and reproducible env (M0)

## Summary
Stand up the project skeleton for the Shelving Workbench and give it a firm
security and reproducibility foundation: a pure-Python `shelving_core` package,
a FreeCAD 1.0 namespace-package workbench that vendors a synced copy of it, the
`test.sh` two-tier harness, a pixi-managed environment shared by developers and
CI, a single `tools/install-deps.sh` setup script, and GitHub Actions workflows
hardened per a documented standard (SHA-pinned actions, least-privilege tokens,
Dependabot, harden-runner, OpenSSF Scorecard). No domain logic ships here. This
task supersedes sh-002, which is abandoned.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [ ] User sign-off

## Must Have

### Package skeleton
- [x] `./test.sh --fast` exits 0 and runs, in order: the toolchain preflight, `ruff check .`, `ruff format --check .`, `mypy` (strict, `shelving_core` only), the vendor-drift check, `pytest`.
- [x] `./test.sh --full` is a strict superset of `--fast` and is the single "run everything" command: it runs the entire `--fast` sequence, then `tools/lint-workflows.sh`, then the `freecadcmd` smoke test, in that order (cheapest to slowest), aborting at the first failure. It preflights for every tool it invokes (`ruff`/`mypy`/`pytest` plus `actionlint`/`zizmor`/`check-jsonschema`/`shellcheck`); if any is missing it names them, points at `tools/install-deps.sh` and `pixi shell`, and exits 3. When `freecadcmd` specifically is missing it still emits the exact `ERROR: freecadcmd not found on PATH. FreeCAD 1.0+ is required for the full test tier; see README.md.` message and exits 1. On success it exits 0.
- [x] `ruff check .` and `ruff format --check .` report no issues.
- [x] `mypy` in strict mode over `shelving_core` reports no errors; `freecad/` is excluded from type-checking.
- [x] `pytest` collects at least three tests and all pass.
- [x] No file under `shelving_core/` contains `import FreeCAD`, `from FreeCAD`, `import FreeCADGui`, or `from FreeCADGui`; a pytest asserts this by scanning source and by importing every `shelving_core` submodule and checking `FreeCAD`/`FreeCADGui` never entered `sys.modules`.
- [x] `freecad/shelving/vendor/shelving_core/` exists and its contents byte-match `shelving_core/` with `tests/` and `__pycache__/` excluded; `tools/vendor-core.sh` regenerates it and a drift-check step (used by `--fast`) fails when it is stale.
- [x] `freecad/shelving/__init__.py` and `freecad/shelving/init_gui.py` exist; `init_gui.py` defines a `Gui.Workbench` subclass (`MenuText`, `ToolTip`, `Icon`, `Initialize`, `GetClassName` returning `"Gui::PythonWorkbench"`) and calls `Gui.addWorkbench(...)`, guarded so module import under `freecadcmd` (no GUI) does not raise.
- [x] `package.xml` is valid XML, Addon Manager `content` type `workbench`, `name` Shelving, `version` 0.0.1, `maintainer` email `freecad@dbort.com`, `license` MIT, repository url `https://github.com/dbort/shelving-workbench`, and declares `freecadmin` 1.0.
- [x] `LICENSE` is the MIT license text, holder `Dave Bort`, year 2026; `pyproject.toml` license and author metadata match.
- [x] `pyproject.toml` sets `requires-python = ">=3.11"`, builds `shelving_core`, and defines a `dev` extra with `ruff`, `mypy`, `pytest`.
- [x] No `ShelvingUnit`, solver, expansion, catalog, or task-panel code exists anywhere in the tree.
- [x] `docs/roadmap.md` M0 **Status** line still reads `Task sh-001`; this task does not flip it to `Done` (that happens at merge, via `approve-task`).

### Test harness
- [x] `tests/test_harness_cli.py` (run by `--fast` via `pytest shelving_core tests`) covers `test.sh`'s exit-status contract: usage → 2, missing-tool preflight → 3 with names + pointer (both tiers, including `rsync`), and a source-scan for the exact `freecadcmd`-absent message + `exit 1`.

### Environment (pixi) and setup script
- [x] `pixi.toml` declares the `conda-forge` channel, `freecad` pinned to `1.0.*`, the dev toolchain (`ruff`, `mypy`, `pytest`), Python `3.12.*`, and both `linux-64` and `linux-aarch64` in platforms (CI is x86_64, the dev VM is aarch64); it defines `[tasks]` `fast` and `full` whose bodies are exactly `./test.sh --fast` and `./test.sh --full` (thin wrappers, no tier logic).
- [x] `pixi.lock` is committed and consistent with `pixi.toml`, covering both platforms; generate it with `pixi install`. pixi and conda-forge are reachable in the implementation environment (`pixi` is on `PATH`). Do not hand-fabricate the lock; if a run genuinely cannot reach conda-forge, run `tools/install-deps.sh` first, and only then fall back to the friction-log route.
- [x] `tools/install-deps.sh` starts with `set -euo pipefail`; when `pixi` is not on `PATH` it installs a pinned pixi release for the host arch (`uname -m` → `x86_64`/`aarch64`), verifying the published `.sha256`, into `~/.local/bin`, and ensures `~/.local/bin` is on `PATH` via `~/.bashrc` and `~/.profile`; then it creates `.venv/` with `python3` if absent and installs `-e .[dev]` into it, then runs `pixi install`. Re-running it is a no-op, not an error.
- [x] `tools/bootstrap-dev.sh` does not exist; `tools/install-deps.sh` is the only setup script.
- [x] `./test.sh --fast` preflights for `ruff`, `mypy`, and `pytest` on `PATH` before invoking any of them; if any is missing it names them, tells the reader to run `tools/install-deps.sh` and activate `.venv` (or `pixi shell`), and exits with status 3. Status 2 stays reserved for usage errors; a real lint/type/test failure still surfaces that tool's own status.

### GitHub Actions hardening
- [x] `.github/workflows/ci.yml` sets `permissions: {}` at workflow level; each job re-grants only what it needs (`contents: read`).
- [x] Every `uses:` in every workflow is pinned to a full 40-hex commit SHA with a trailing `# vX.Y.Z` comment. No `@vN` or `@branch` refs.
- [x] `actions/checkout` is invoked with `persist-credentials: false` everywhere.
- [x] Workflows trigger on `push` and `pull_request` only. No `pull_request_target` anywhere.
- [x] `runs-on` names a pinned runner image (`ubuntu-24.04`), not `ubuntu-latest`.
- [x] `step-security/harden-runner` is the first step of every job, with `egress-policy: audit`.
- [x] `ci.yml` has a `concurrency` group keyed on workflow + ref with `cancel-in-progress: true`.
- [x] `.github/workflows/ci.yml` has exactly two jobs: `fast` (bare `python -m venv`, `pip install -e .[dev]`, `./test.sh --fast` across a Python `3.11`/`3.12` matrix, no pixi and no FreeCAD) and `full` (`prefix-dev/setup-pixi` SHA-pinned with the lock frozen, `pixi run full`). There is no standalone `workflows` job: `pixi run full` runs `./test.sh --full`, which already includes `tools/lint-workflows.sh`.
- [x] No `run:` step interpolates `${{ github.event.* }}` or other attacker-controllable context directly into shell; a comment in `ci.yml` states this rule.
- [x] `.github/workflows/scorecard.yml` runs the OpenSSF Scorecard action (SHA-pinned) on `branch_protection_rule`, a weekly `schedule`, and `push` to `main`; its `permissions` are limited to `security-events: write`, `id-token: write`, `contents: read`; it uploads SARIF results.
- [x] `.github/dependabot.yml` enables the `github-actions` ecosystem (weekly) and the `pip` ecosystem (weekly) with a comment noting pixi is unsupported by Dependabot and `pixi.lock` is refreshed manually via `pixi update`.

### Workflow linting
- [x] `tools/lint-workflows.sh` (`set -euo pipefail`) runs, from one invocation and failing on any sub-failure: `actionlint` over `.github/workflows/`; `zizmor` (offline mode) over `.github/workflows/`; an offline pin-format check asserting every `uses:` in `.github/workflows/*.yml` matches `owner/repo@<40-hex> # vX.Y.Z`; and `check-jsonschema --builtin-schema vendor.dependabot` over `.github/dependabot.yml`.
- [x] `pixi.toml` provides `actionlint`, `zizmor`, `check-jsonschema`, and `shellcheck` (all conda-forge) and a `[tasks]` entry `lint-workflows` whose body is exactly `tools/lint-workflows.sh`.
- [x] `pixi run lint-workflows` (a granular shortcut for `tools/lint-workflows.sh`) exits 0 against this repo's own workflow files; any zizmor finding is either fixed or suppressed with an inline `# zizmor: ignore[<rule>]` and a one-line reason. `./test.sh --full` runs the same script and CI reaches it through the `full` job.
- [x] `docs/github-actions-hardening.md` gains a section stating that `tools/lint-workflows.sh` (run standalone as `pixi run lint-workflows`, and in CI via the `full` job's `./test.sh --full`) enforces this standard, listing what each of the four checks covers.
- [x] `README.md` presents `./test.sh --full` (or `pixi run full`) as the single "run everything" command and notes it is a superset of `--fast`; `pixi run lint-workflows` is listed as a granular shortcut.

### Docs
- [x] `docs/github-actions-hardening.md` documents the standard this task establishes (SHA pinning, `permissions: {}` + per-job grants, `pull_request` never `pull_request_target`, the injection rule, Dependabot coverage, harden-runner, Scorecard, pinned runner images) as the rule for all future workflow changes.
- [x] `README.md` documents: `tools/install-deps.sh` (installs a pinned pixi for the host arch if absent, sets up the venv and the pixi env; links pixi's docs) as the primary setup; the bare `python -m venv` + `pip install -e .[dev]` path as the minimal core-only alternative; and `./test.sh --fast` (FreeCAD-free) vs `./test.sh --full` (everything) as the tier interface.
- [x] The `2026-08-30` friction-log entry about getting the fast tier's toolchain into a fresh shell is removed from `.claude/docs/friction-log.md`.

## Frontier Advice

RESUME NOTE: the `sh-001` branch already carries three implementation passes
plus review approvals and `doc-hygiene` commits. The tree satisfies every Must
Have except the ones re-opened for this pass, which change `--full` into the
single "run everything" command. Treat this pass as a targeted rework of
`test.sh`, `ci.yml`, and the docs; leave everything else alone unless it breaks.
`tools/bootstrap-dev.sh` was never created; do not add it.

THIS PASS ("full means everything"):
- `test.sh --full` becomes a strict superset of `--fast`. Order: run the full
  `--fast` sequence, then `tools/lint-workflows.sh`, then the `freecadcmd` smoke
  test. Abort at the first failure. So a lint/type/test regression or a bad
  workflow file fails `--full` before FreeCAD is even touched.
- `--full` preflights for `ruff`/`mypy`/`pytest` AND `actionlint`/`zizmor`/
  `check-jsonschema`/`shellcheck`; any missing -> name them, point at
  `tools/install-deps.sh` / `pixi shell`, exit 3. `freecadcmd` missing keeps its
  own exact message and exit 1 (unchanged contract).
- `pixi run full` stays a one-line wrapper over `./test.sh --full`; `pixi run
  fast` and `pixi run lint-workflows` remain as granular shortcuts.
- `ci.yml` drops the standalone `workflows` job. Two jobs remain: `fast` (bare
  venv, matrix, FreeCAD-free) and `full` (pixi, `pixi run full` = everything).
- Update `docs/github-actions-hardening.md` and `README.md` to match.

WORKFLOW LINTING: `tools/lint-workflows.sh` is the single entry point (also
exposed as `pixi run lint-workflows`). It runs four checks, each fatal:
`actionlint .github/workflows` (schema + `run:` shellcheck; needs `shellcheck`
on PATH, which the pixi env provides), `zizmor --offline .github/workflows`
(Actions security audit), an offline `grep`/regex pin check over
`.github/workflows/*.yml` (every `uses:` is `owner/repo@<40-hex> # vX.Y.Z`), and
`check-jsonschema --builtin-schema vendor.dependabot .github/dependabot.yml`.
Run `zizmor` offline for determinism; do not pass a GitHub token. If `zizmor`
flags something on the existing hardened workflows, prefer fixing it; only
suppress with `# zizmor: ignore[rule]` plus a reason when the finding is a
confirmed false positive.

CRITICAL scope guard: STRUCTURE, ENVIRONMENT, and CI only. Do not implement the
split-tree, spacing solver, carcass expansion, material catalog, scripted
objects, or the 2.5D editor. Any Python module under `shelving_core/` beyond
`__init__.py` must be empty of domain logic.

Target: FreeCAD 1.0+, PySide6, Python 3.11+ (`shelving_core` must import on 3.11
through 3.13; the pixi env pins 3.12). Single root `pyproject.toml`, `hatchling`
backend, one distributed package `shelving_core`, plus `shelving_core/py.typed`.

`shelving_core` PURITY: never imports FreeCAD, directly or transitively.
Enforced by a test that both scans source for the four import forms (assembled
from fragments so the test file does not trip its own scan) and imports every
submodule then asserts `FreeCAD`/`FreeCADGui` are absent from `sys.modules`. Do
not add a conditional-import shim.

VENDORING: source of truth is top-level `shelving_core/`. `tools/vendor-core.sh`
copies it to `freecad/shelving/vendor/shelving_core/` excluding `tests/` and
`__pycache__/` (`rsync -a --delete --exclude tests --exclude __pycache__`).
`--check` re-copies into a `mktemp -d` and `diff -r`s the committed tree; any
diff exits 1 with a "run tools/vendor-core.sh and commit" message. Wired into
`--fast` before `pytest`. The workbench imports the core as
`from freecad.shelving.vendor import shelving_core`; it never adds the repo root
or top-level `shelving_core/` to `sys.path`.

`test.sh` STAYS AUTHORITATIVE for tier contents: `set -euo pipefail`, exactly
one of `--fast`/`--full` (else usage, exit 2). `--fast` runs its preflight
(exit 3, names missing `ruff`/`mypy`/`pytest`, points at `tools/install-deps.sh`)
then ruff, ruff format, mypy, `tools/vendor-core.sh --check`,
`pytest shelving_core`. `--full` is `--fast` plus more: it runs the entire
`--fast` sequence, then `tools/lint-workflows.sh`, then the `freecadcmd` smoke
test, aborting at the first failure. Its preflight additionally checks
`actionlint`/`zizmor`/`check-jsonschema`/`shellcheck` (same exit-3 treatment).
`freecadcmd` missing still prints `ERROR: freecadcmd not found on PATH. FreeCAD
1.0+ is required for the full test tier; see README.md.` and exits 1; present
runs `freecadcmd tools/freecad_smoke.py`. The `freecad_smoke.py` script prepends repo
root to `sys.path` (with a comment that workbench code never does this), imports
`freecad.shelving` and the vendored core, prints an OK line. pixi `[tasks]`
`fast`/`full` are literally `./test.sh --fast` / `./test.sh --full` with no
other logic.

`init_gui.py`: `freecadcmd` is headless and has no `FreeCADGui`. Guard with
`try: import FreeCADGui as Gui / except ImportError: Gui = None` and an
`if Gui is not None:` block around `addWorkbench`. Class base is
`Gui.Workbench if Gui else object`. `import freecad.shelving` must succeed under
`freecadcmd`; importing `init_gui` there must not raise.

PIXI: `pixi.toml` `[project]` (name, `channels = ["conda-forge"]`,
`platforms = ["linux-64", "linux-aarch64"]`), `[dependencies]`
`freecad = "1.0.*"`, `python = "3.12.*"`, `ruff`, `mypy`, `pytest`; `[tasks]`
`fast`/`full` as above. Generate `pixi.lock` with `pixi install`; it must
resolve for both platforms. The dev VM already has `pixi` on `PATH`
(`/usr/local/bin/pixi`, v0.78.0) and conda-forge is reachable, so this is a
normal build step. Do NOT hand-fabricate `pixi.lock`. Only if a run genuinely
cannot reach conda-forge: write a complete correct `pixi.toml`, add a
friction-log entry that the lock must be generated on a connected machine, and
note in the handoff that CI's `full` job (`setup-pixi` with the lock) is the
verification point.

`tools/install-deps.sh` is "always full": it sets up BOTH the bare `.venv`
(pip `-e .[dev]`, for the FreeCAD-free path and the CI fast leg's local
equivalent) AND the pixi env (`pixi install`). When `pixi` is missing it
installs a pinned pixi release itself: detect arch with `uname -m`
(`x86_64` -> `pixi-x86_64-unknown-linux-musl`,
`aarch64` -> `pixi-aarch64-unknown-linux-musl`), download that asset and its
`.sha256` from `https://github.com/prefix-dev/pixi/releases/download/<PINNED>/`,
verify, `install -m 0755` the binary to `~/.local/bin/pixi`, and append
`export PATH="$HOME/.local/bin:$PATH"` to `~/.bashrc` and `~/.profile` if not
already present. Pin the pixi version as a shell variable at the top of the
script (currently `v0.78.0`). It supersedes sh-002's `bootstrap-dev.sh`; do not
create that file.

CI HARDENING: pin every `uses:` to a 40-hex SHA with a `# vX.Y.Z` comment.
Actions needed: `actions/checkout`, `actions/setup-python`,
`prefix-dev/setup-pixi`, `step-security/harden-runner`, `ossf/scorecard-action`,
`github/codeql-action/upload-sarif` (for Scorecard). Use each action's current
stable release SHA; if you cannot verify a SHA offline, use the documented
release SHA from the action's releases page and flag every such line in the
handoff for the Reviewer to confirm against GitHub. `harden-runner`
`egress-policy: audit` (not `block`). `permissions: {}` top-level, per-job
minimal grants. The `fast` job is deliberately pixi-free and FreeCAD-free: it
proves `shelving_core` installs and passes `--fast` with no FreeCAD present. Do
not add pixi or FreeCAD to it. `setup-pixi` in the `full` job runs with the
lock frozen so a stale or missing lock fails the job rather than silently
re-solving.

sh-002 is superseded by this task. Its abandonment (tombstone in
`tasks/abandoned/`) is handled by the human/Planner, not by this task's
Execution Plan.

CLAUDE.md § Standing task-planning obligations lists no active entries.

DEV VM: aarch64, open network (PyPI + conda-forge + GitHub reachable),
persistent `/workspace` and `$HOME`. `pixi` 0.78.0 is at `/usr/local/bin/pixi`.
The Bash tool spawns non-login non-interactive shells with a frozen `PATH`, so
edits to `~/.bashrc`/`~/.profile` only take effect in a new Claude Code
session; call newly installed tools by absolute path or with an inline
`export PATH` within the same command.

Friction log: record any workaround per CLAUDE.md, including an offline
action-SHA lookup or a conda solve that could not run.

## Execution Plan

- [x] **Step 1** (`pyproject.toml`, `LICENSE`, `.gitignore`): `hatchling` backend; `[project]` `name = "shelving-workbench"`, `version = "0.0.1"`, `requires-python = ">=3.11"`, author `Dave Bort <freecad@dbort.com>`, `license = {text = "MIT"}`; `[project.optional-dependencies] dev = ["ruff", "mypy", "pytest"]`; `[tool.hatch.build.targets.wheel] packages = ["shelving_core"]`; `[tool.ruff]` (target `py311`, select `E`,`F`,`I`,`UP`,`B`); `[tool.mypy]` (`strict = true`, `files = ["shelving_core"]`, `exclude = ["freecad/"]`). `LICENSE`: MIT, `Copyright (c) 2026 Dave Bort`. `.gitignore`: Python caches, `dist/`, `build/`, `*.egg-info/`, `.venv/`, `.pixi/`, `.ruff_cache/`, `.mypy_cache/`, `.pytest_cache/`.

- [x] **Step 2** (`shelving_core/__init__.py`, `shelving_core/py.typed`, `shelving_core/tests/__init__.py`, `shelving_core/tests/test_smoke.py`, `shelving_core/tests/test_no_freecad.py`): `__init__.py` sets `__version__ = "0.0.1"` and a docstring stating the no-FreeCAD invariant; nothing else. Empty `py.typed`. `test_smoke.py` asserts `__version__` is a non-empty `str`. `test_no_freecad.py`: source scan for the four forbidden import forms (patterns built from fragments) plus a `pkgutil.walk_packages` import loop asserting `FreeCAD`/`FreeCADGui` absent from `sys.modules`.

- [x] **Step 3** (`freecad/__init__.py`, `freecad/shelving/__init__.py`, `freecad/shelving/init_gui.py`, `freecad/shelving/resources/shelving.svg`): namespace `__init__` files via `pkgutil.extend_path`; `init_gui.py` per Frontier Advice (guarded `Gui`, `ShelvingWorkbench` with `MenuText`/`ToolTip`/`Icon` and `Initialize`/`Activated`/`Deactivated`/`GetClassName`, guarded `addWorkbench`); a minimal placeholder SVG icon.

- [x] **Step 4** (`tools/vendor-core.sh`, `freecad/shelving/vendor/__init__.py`, `freecad/shelving/vendor/shelving_core/**`): `vendor-core.sh` with `set -euo pipefail`, repo-root resolution, the rsync copy, and `--check` mode (temp copy + `diff -r`, exit 1 + guidance on drift). Run it once to generate the committed vendored tree. Add `vendor/__init__.py`.

- [x] **Step 5** (`test.sh`, `tools/freecad_smoke.py`): `test.sh` per Frontier Advice, including the `--fast` preflight. `freecad_smoke.py` per Frontier Advice. (Reworked in Step 15: `--full` becomes a superset.)

- [x] **Step 6** (`package.xml`): Addon Manager metadata (`xmlns` Package_Metadata, `format="1"`): `name` Shelving, `version` 0.0.1, `description`, `maintainer` `Dave Bort` / `freecad@dbort.com`, `license` MIT (`file="LICENSE"`), `url` `repository` `https://github.com/dbort/shelving-workbench` + a `bugtracker`, `content/workbench` (`classname` `ShelvingWorkbench`, `subdirectory` `freecad/shelving/`, `icon` the resources SVG), `<freecadmin>1.0</freecadmin>`.

- [x] **Step 7** (`pixi.toml`, `pixi.lock`): `pixi.toml` per Frontier Advice (`linux-64` + `linux-aarch64`). Run `pixi install` to generate and commit `pixi.lock` for both platforms. If a run truly cannot reach conda-forge, leave `pixi.toml` complete, add the friction-log entry, and do not fabricate the lock.

- [x] **Step 8** (`tools/install-deps.sh`): `set -euo pipefail`; repo-root `cd`; a pinned `PIXI_VERSION` variable (`v0.78.0`); if `command -v pixi` fails, arch-detect and install the pinned pixi release to `~/.local/bin` with `.sha256` verification and add `~/.local/bin` to `~/.bashrc`/`~/.profile` (per Frontier Advice); conditional `python3 -m venv .venv`; `.venv/bin/pip install -e .[dev]`; `pixi install`; closing `echo` about activating `.venv` or `pixi shell` and re-opening the shell if `~/.local/bin` was just added. Idempotent. `chmod +x`.

- [x] **Step 9** (`.github/workflows/ci.yml`): `permissions: {}` top-level; `concurrency` group; triggers `push` + `pull_request`. Job `fast`: `runs-on: ubuntu-24.04`, `permissions: {contents: read}`, `harden-runner` (audit) first, `checkout` (SHA-pinned, `persist-credentials: false`), `setup-python` (SHA-pinned) over `strategy.matrix.python-version: ["3.11", "3.12"]`, `pip install -e .[dev]`, `./test.sh --fast`. Job `full`: `runs-on: ubuntu-24.04`, `permissions: {contents: read}`, `harden-runner` first, `checkout`, `prefix-dev/setup-pixi` (SHA-pinned, `frozen: true`), `pixi run full`. Comment stating the no-`${{ github.event.* }}`-in-`run` rule.

- [x] **Step 10** (`.github/workflows/scorecard.yml`, `.github/dependabot.yml`): Scorecard workflow per Must Have (SHA-pinned `ossf/scorecard-action` + `github/codeql-action/upload-sarif`; triggers `branch_protection_rule` + weekly `schedule` + `push` to `main`; `permissions` `security-events: write` / `id-token: write` / `contents: read`). `dependabot.yml`: `github-actions` weekly, `pip` weekly, comment on pixi being unsupported.

- [x] **Step 11** (`docs/github-actions-hardening.md`): Document the standard established here as the rule for future workflow edits.

- [x] **Step 12** (`README.md`, `.claude/docs/friction-log.md`): `README.md` per Must Have. Remove the `2026-08-30` toolchain friction-log entry.

- [x] **Step 13** (`tools/lint-workflows.sh`, `pixi.toml`, `.github/workflows/ci.yml`, `docs/github-actions-hardening.md`, `README.md`): Create `tools/lint-workflows.sh` per the WORKFLOW LINTING Frontier Advice (four fatal checks, `set -euo pipefail`, `chmod +x`). Add `actionlint`, `zizmor`, `check-jsonschema`, `shellcheck` to `pixi.toml` `[dependencies]` and a `[tasks] lint-workflows = "tools/lint-workflows.sh"`; re-run `pixi install` and commit the updated `pixi.lock`. Add the `workflows` job to `ci.yml` (ubuntu-24.04, `contents: read`, harden-runner first, pinned `checkout` + `setup-pixi`, `pixi run lint-workflows`). Run `pixi run lint-workflows` and resolve every finding against the repo's own workflows. Add the enforcement section to `docs/github-actions-hardening.md` and the `pixi run lint-workflows` line to `README.md`.

- [x] **Step 14** (verification of the prior pass): superseded by Step 16.

- [x] **Step 15** (`test.sh`, `.github/workflows/ci.yml`, `docs/github-actions-hardening.md`, `README.md`): Rework `test.sh --full` into a strict superset per the THIS PASS Frontier Advice: run the full `--fast` sequence, then `tools/lint-workflows.sh`, then the `freecadcmd` smoke, aborting at the first failure; extend the preflight to `actionlint`/`zizmor`/`check-jsonschema`/`shellcheck` (exit 3), keeping the `freecadcmd`-missing exit-1 + exact message. In `ci.yml`, delete the standalone `workflows` job, leaving `fast` and `full` only (`full` already runs `pixi run full`). Update the enforcement section of `docs/github-actions-hardening.md` (CI reaches `lint-workflows.sh` through the `full` job) and `README.md` (`./test.sh --full` / `pixi run full` is the one "run everything" command; `--fast` is the FreeCAD-free subset; `pixi run lint-workflows` a granular shortcut).

- [x] **Step 16** (verification, no new files): Confirm `docs/roadmap.md` M0 reads `Task sh-001`; grep the tree for no `ShelvingUnit`/solver/expansion/catalog/editor code; run `./test.sh --fast` green (in `.venv`), `pixi run full` green (covers lint-workflows + FreeCAD), and confirm `./test.sh` with no args and with a bad flag still exit 2.

- [x] **Step 17** (`tests/__init__.py`, `tests/test_harness_cli.py`, `test.sh`, `tools/lint-workflows.sh`, `.claude/docs/friction-log.md`): Round 1 review rework. Add a repo-root `tests/` package (not under `shelving_core/`, which ships in the wheel) with `test_harness_cli.py` covering `test.sh`'s CLI/exit-status contract: usage errors (no arg, `--bogus`, `--fast --full`) exit 2 with the usage line; `--fast`/`--full` under a stripped `PATH` exit 3 naming every missing preflight tool plus the `install-deps.sh` / `pixi shell` pointer; a source-scan for the exact `freecadcmd`-absent message followed by `exit 1`. Every subprocess call is shaped so `test.sh` exits before `run_fast` (which now runs `pytest shelving_core tests`), so the fast tier does not recurse. Point `run_fast` at `pytest shelving_core tests` (F1). Add `rsync` to both preflight lists in `test.sh` (N2). Widen `tools/lint-workflows.sh`'s pin-format check to glob `*.yml` and `*.yaml` (N1). Delete the `2026-08-30` friction-log entry about hand-building a `PATH` to review `test.sh`'s exit-status contract (F1 resolves it).
