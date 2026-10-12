---
id: sh-036
title: "Pyrefly replaces mypy"
---

# sh-036: Pyrefly replaces mypy

## Summary
The repo's type checker becomes pyrefly, run at its strict preset, and mypy
leaves the toolchain entirely. Pyrefly's strict preset already reports 22
things mypy --strict misses on today's tree (overriding methods without
`@override`, a few inferred `Any`s, one lambda whose argument widens to
`str`), and those are fixed as part of the switch.

## Must Have
- [ ] `pixi run tests` green, with `tools/run-tests.sh` running pyrefly
      where it ran mypy, and no mypy invocation left in it.
- [ ] `pixi.toml` lists `pyrefly` and not `mypy`; `pyproject.toml` has a
      `[tool.pyrefly]` table setting `preset = "strict"` and no
      `[tool.mypy]` table; `.gitignore` has no `.mypy_cache/` line.
- [ ] The pyrefly config disables no error kind and lowers none below its
      preset severity.
- [ ] Pyrefly honors only its own ignore comments (`enabled-ignores` set to
      `pyrefly` alone), and no tracked `.py` file contains `# type: ignore`.
- [ ] The strict preset is in force: deleting one of the new `@override`
      decorators, or annotating a function parameter away, makes
      `pixi run tests` fail at the pyrefly step.
- [ ] `git grep -n -i mypy -- ':!tasks/completed/' ':!pixi.lock'` prints
      nothing.
- [ ] `CLAUDE.md` § Typed Python names pyrefly's strict preset as the
      required check, and each active task file's "`mypy --strict` clean"
      Must Have and Advice line names pyrefly instead.

## Advice
REPLACE, NOT ALONGSIDE (user decision, 2026-10-11). Mypy goes from the
dependencies, the gate, the config, and every doc and comment. One checker
means one suppression syntax and no disagreements to arbitrate.

STRICT PRESET, NOTHING DISABLED (user decision, 2026-10-11). It is the closest
match to today's `mypy --strict` and goes past it. Fix every finding rather
than silencing an error kind. `missing-override-decorator` stays on: an
`@override` (from `typing`, Python 3.12) catches a Qt, FreeCAD or Workbench
base method renamed under a subclass.

WHAT STRICT REPORTS TODAY (pyrefly 1.3.2, probed before planning). The 22
findings are:
- 15 `missing-override-decorator`, in `editor/panel.py` (8), `init_gui.py`
  (4), `debug_log.py`, `tests/freecad_gui/test_panel.py` and
  `tests/test_editor_scene.py` (1 each).
- `bad-argument-type` at `qa/dock.py:176`: the `lambda _=False, v=verdict:`
  default widens `v` to `str`. Bind the verdict with a typed helper or
  `functools.partial` so `record` receives a `Verdict`.
- `implicit-any-type-argument` at `tests/freecad/test_editor_session.py:1257`.
- `implicit-any-lambda` at `tests/freecad/test_qa_actions.py:23` and
  `tests/freecad/test_temp_dirs.py:73`.
- `implicit-any-empty-container` at `tests/test_task_status.py:91` and
  `tools/check_action_pins.py:296`.

Expect the exact list to shift with the locked version. The gate's own output
is the authority.

IGNORE COMMENTS. Pyrefly honors `# type: ignore` by default. Set
`enabled-ignores` to pyrefly alone, so a stale mypy suppression cannot hide
a pyrefly error. With only pyrefly ignores honored, the one line that still
errors is `tests/freecad_materials.py:20`'s `import Materials`. Give it
`# pyrefly: ignore[missing-import]` and keep the reason it exists: FreeCAD
provides `Materials` at runtime and ships no stub for it. The nine
`# type: ignore[no-untyped-call]` comments (`commands/create_unit.py`,
`editor/session.py`, `init_gui.py`, `tests/freecad/test_editor_session.py`,
`tests/freecad_gui/test_stock.py`) silence nothing pyrefly reports, so
delete them. If pyrefly has an unused-ignore check, turn it on, so a
suppression that outlives its error fails the gate.

CONFIG. Put it in `pyproject.toml` `[tool.pyrefly]`, beside the other tool
tables:
- `project-includes`: `freecad/`, `tools/` and `tests/`, the same set mypy
  checked.
- `search-path`: the repo root, so `freecad.Shelving` resolves as the
  namespace package it is. `freecad/` carries no `__init__.py`.
- The interpreter: never hardcode a `.pixi/` path. Under `pixi run`,
  pyrefly finds the environment's Python on `PATH`, and that is how it
  sees `freecad-stubs` and `pyside6-stubs`.

Delete the mypy table and its `explicit_package_bases` comment. Pyrefly has
no equivalent problem, because the probe resolved every module with
`--search-path .` alone. Verify that the config, with no CLI flags, gives the
same result as the probe, so `pyrefly check` and an editor's pyrefly
language server read one config.

DEPENDENCY. Add `pyrefly = "*"` from conda-forge, beside `ruff`, which it
replaces in kind; `pixi.lock` pins the version. Re-lock for both
`linux-64` and `linux-aarch64`. `tools/check_lock_paths.py` must stay green.

COMMENTS THAT NAME MYPY. Reword each one around the checker's need, so the
rationale survives:
- `freecad/Shelving/commands/create_unit.py:45`: the re-check for `doc is
  None`.
- `freecad/Shelving/core/expand.py:19`: the explicit `as` re-export. Check
  whether pyrefly needs it; if not, decide by whether `Vec3` is part of
  `expand`'s public surface.
- `tools/__init__.py`'s docstring: it points at `[tool.mypy].files`.
- `pixi.toml`'s `pyside6-stubs` comment.
- `README.md` § Tests: "strict mypy".

FOUND DURING WORK (2026-10-11).
- `pyside6-stubs` declares a hard dependency on mypy, so `pixi.lock` still
  installs mypy even though nothing runs it. The lock is excluded from the
  grep Must Have for that reason.
- Pyrefly's strict preset has no counterpart to mypy's
  `disallow_untyped_calls`. A call into an unannotated freecad-stubs method
  such as `openTransaction` passes silently, which is why the nine
  `no-untyped-call` ignores had nothing left to suppress.

STANDING OBLIGATIONS (`CLAUDE.md`).
- **Typed Python:** this task rewrites that obligation's last sentence to
  name pyrefly's strict preset. The task's own Python changes meet the rule.
- **Shell stays simple:** `run-tests.sh` swaps one command for another and
  stays a linear sequence.
- **Users never read the log:** opted out. This task changes no
  user-facing behavior.

## Plan
- [x] **Step 1** (`pixi.toml`, `pixi.lock`, `pyproject.toml`, `.gitignore`,
      `tools/run-tests.sh`): pyrefly replaces mypy as a dependency, in the
      config and in the gate, per Advice § CONFIG and § IGNORE COMMENTS.
- [x] **Step 2** (the files listed in Advice § WHAT STRICT REPORTS TODAY):
      every strict finding fixed in code, none suppressed; `@override` on
      each overriding method.
- [x] **Step 3** (the files in Advice § IGNORE COMMENTS): no `# type:
      ignore` remains; `Materials` carries the one pyrefly ignore.
- [x] **Step 4** (`CLAUDE.md`, `README.md`, `tools/__init__.py`,
      `freecad/Shelving/commands/create_unit.py`,
      `freecad/Shelving/core/expand.py`, `pixi.toml` comments; the active
      task files `tasks/active/sh-023-preferences.md`,
      `sh-024-user-documentation-and-release.md`,
      `sh-031-editor-stock-list-and-swap.md`, `sh-035-relabel-unit.md`):
      every mention of mypy names pyrefly, or goes, per Advice § COMMENTS
      THAT NAME MYPY. The `git grep` Must Have is clean.
- [x] **Step 5**: confirm the strict-preset Must Have by hand, once by
      deleting an `@override` and once by dropping a parameter annotation.
      Restore both.

## Review log

### Round 1: REJECTED
- **F1: The strict preset and ignore policy are confirmed only by a manual check** (`pyproject.toml:34-49`, Plan Step 5): Must Haves 3-5 hold today, but nothing in `pixi run tests` keeps them true; disabling `missing-override-decorator`, dropping `preset = "strict"` or `enabled-ignores` would leave the gate green. Add a pytest that checks a fixture in `tmp_path` against the repo's `[tool.pyrefly]` table and asserts `missing-override-decorator`, `implicit-any-parameter` and `unused-ignore` fire, `# type: ignore` is not honored, and the run exits non-zero.
- **N1: Five strict-preset warnings stay in the tree, hidden by default** (`editor/panel.py:809`, `qa/report.py:107`, `properties.py:214`, `qa/dock.py:354`, `tools/check_action_pins.py:290`): two are `redundant-cast`, which `mypy --strict` reported as errors, so the gate is weaker there. Fix the five, or raise `redundant-cast` to error.
- **N2: `tools/__init__.py` docstring points at a whole table** (`tools/__init__.py:2`): name `[tool.pyrefly].project-includes`, the exact key, as the old text named `[tool.mypy].files`.

