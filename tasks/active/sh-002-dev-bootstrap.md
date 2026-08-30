---
id: sh-002
title: "Dev-env bootstrap script and CI Python matrix"
current_agent: implementer
current_phase: planning
review_rejections: 0
blocked_by: [sh-001]
---

# sh-002: Dev-env bootstrap script and CI Python matrix

## Summary
Add a one-command dev-environment setup script and make `./test.sh --fast`
fail with a useful pointer instead of a bare `command not found` when the
toolchain is missing. Also widen the CI fast job to a Python 3.11 and 3.12
matrix so version-specific breakage is caught. Resolves the open friction-log
entry from sh-001's review.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `tools/bootstrap-dev.sh` exists, is executable, starts with `set -euo pipefail`, creates `.venv/` with `python3` if it is absent, installs `-e .[dev]` into it, and is safe to run repeatedly (re-run is a no-op reinstall, not an error).
- [ ] `tools/bootstrap-dev.sh` never runs `pip install` against the system interpreter; all installs go into `.venv/`, so a PEP 668 externally-managed system Python does not break it.
- [ ] `./test.sh --fast` preflights for `ruff`, `mypy`, and `pytest` on `PATH` before invoking any of them. If one or more is missing it prints a message naming the missing tool(s) and telling the reader to run `tools/bootstrap-dev.sh` then activate `.venv` (or activate an existing venv), and exits with status 3.
- [ ] Exit status 3 is used only for this missing-toolchain case: usage errors stay at 2, and a genuine lint/type/test failure still surfaces that tool's own non-zero status.
- [ ] When `ruff`, `mypy`, and `pytest` are all present, `./test.sh --fast` behaves exactly as before (no extra output, same steps, exit 0 on success).
- [ ] `./test.sh --full` is unchanged.
- [ ] `.github/workflows/ci.yml` `fast` job runs a matrix over Python `3.11` and `3.12`; both legs must pass for the job to pass. The `full` job is untouched.
- [ ] `README.md` Development section presents `tools/bootstrap-dev.sh` as the one-step setup, keeping the `./test.sh --fast` line.
- [ ] The `2026-08-30` friction-log entry about getting the fast tier's toolchain into a fresh shell is removed from `.claude/docs/friction-log.md`.
- [ ] No changes under `shelving_core/` or `freecad/`.

## Frontier Advice

Scope: developer-tooling only. Do not touch `shelving_core/` or `freecad/`
package code, `pyproject.toml` dependency lists, or `package.xml`.

`blocked_by: [sh-001]` is a hard blocker: this task edits `test.sh`,
`.github/workflows/ci.yml`, `README.md`, and `.claude/docs/friction-log.md`,
all of which sh-001 creates or writes. It cannot be implemented or reviewed
until sh-001 is in `tasks/completed/`.

`tools/bootstrap-dev.sh`: resolve repo root from `BASH_SOURCE`, `cd` there.
`python3 -m venv .venv` only when `.venv/` does not already exist. Then
`.venv/bin/pip install -e .[dev]` unconditionally (cheap no-op when satisfied).
Print a final line telling the user to `source .venv/bin/activate`. Keep it
short; no argument parsing.

`test.sh` preflight: add it inside the `--fast` case, before the first tool
call, as a small loop over `ruff mypy pytest` using `command -v`. Collect the
missing ones, and if the list is non-empty, `echo` to stderr a message of the
form `missing dev tools: <names>. Run tools/bootstrap-dev.sh and activate
.venv (or activate your venv).` then `exit 3`. Do not attempt to auto-install
from inside `test.sh`. Leave the `--full` case and the usage/`exit 2` path
alone.

CI matrix: in the `fast` job add
`strategy: { matrix: { python-version: ["3.11", "3.12"] } }` and set the
`setup-python` `python-version` to `${{ matrix.python-version }}`. Do not add a
matrix to the `full` job; conda-forge FreeCAD pins its own Python.

Friction-log deletion: per `.claude/docs/friction-log.md` ("Solving a
papercut"), the entry is removed in the same change that fixes it, and that
removal rides this task's branch to `main` at merge. Do not add a replacement
entry.

CLAUDE.md standing task-planning obligations: none are active; nothing to
satisfy or opt out of.

## Execution Plan

- [ ] **Step 1** (`tools/bootstrap-dev.sh`): Create the script per Frontier Advice: `set -euo pipefail`, repo-root `cd`, conditional `python3 -m venv .venv`, `.venv/bin/pip install -e .[dev]`, closing `echo` about `source .venv/bin/activate`. `chmod +x`.
- [ ] **Step 2** (`test.sh`): In the `--fast` branch only, add a preflight loop over `ruff mypy pytest` via `command -v`; on any missing, print `missing dev tools: <names>. Run tools/bootstrap-dev.sh and activate .venv (or activate your venv).` to stderr and `exit 3`. Then the existing five steps run unchanged. Do not modify the `--full` branch or the usage path.
- [ ] **Step 3** (`.github/workflows/ci.yml`): Add `strategy.matrix.python-version: ["3.11", "3.12"]` to the `fast` job and wire `setup-python`'s `python-version` to `${{ matrix.python-version }}`. Leave the `full` job as-is.
- [ ] **Step 4** (`README.md`): Rewrite the Development section so step one is `tools/bootstrap-dev.sh` (one-step: makes `.venv`, installs the `dev` extra), step two is `source .venv/bin/activate`, step three is `./test.sh --fast`. Keep the sentence listing what the fast tier runs.
- [ ] **Step 5** (`.claude/docs/friction-log.md`): Delete the `2026-08-30` entry under `## Entries` about the fast tier's toolchain in a fresh shell. Leave the rest of the file intact.
