---
id: sh-029
title: "Run the FreeCAD tests under plain pytest"
---

# sh-029: Run the FreeCAD tests under plain pytest

## Summary
The FreeCAD smoke tests stop running as self-invoking scripts under
`freecadcmd` and the `freecad` binary, and become ordinary pytest
directories that `pytest` runs directly, one headless and one with an
embedded offscreen GUI. That removes the per-file workarounds (recursion
guards, output flushing, `os._exit`, stdout redirection), shrinks
`tools/run-tests.sh` to a few lines, and drops FreeCAD's progress-bar noise
from the test output. One small `freecadcmd` check stays so FreeCAD's own
startup path is still exercised.

## Must Have
- [ ] `pixi run tests` green.
- [ ] `tools/freecad_scan_smoke.py`, `tools/freecad_write_smoke.py`,
      `tools/freecad_catalog_smoke.py`, `tools/freecad_editor_smoke.py` and
      `tools/freecad_panel_smoke.py` no longer exist.
- [ ] `pixi run pytest --collect-only -q tests/freecad` collects at least 47
      tests, and `QT_QPA_PLATFORM=offscreen pixi run pytest --collect-only -q
      tests/freecad_gui` at least 14. Those are the counts the five smokes
      have at planning time, so nothing is dropped in the move.
- [ ] No file under `tests/` contains `pytest.main`, `os._exit`, or
      `_SMOKE_RUNNING`.
- [ ] The core run in `tools/run-tests.sh` collects nothing from
      `tests/freecad/` or `tests/freecad_gui/`.
- [ ] `tools/run-tests.sh` runs FreeCAD in exactly three ways: one
      `freecadcmd` import check, `pytest tests/freecad`, and
      `QT_QPA_PLATFORM=offscreen pytest tests/freecad_gui`.
- [ ] A test module under `tests/freecad/` or `tests/freecad_gui/` that
      raises on import makes `pixi run tests` exit non-zero without hanging.
      Verified once by hand during `/work`, then reverted.
- [ ] The `freecadcmd` import check exits non-zero when the workbench or its
      GUI module fails to import, verified once by hand the same way.
- [ ] `pixi run tests` output contains no `Recompute` progress lines, and
      friction-021 is deleted from `.claude/docs/friction-log.md`.
- [ ] `docs/freecadcmd-notes.md` no longer exists. Its trimmed content is at
      `.claude/docs/freecad-notes.md`. No file outside `tasks/completed/`
      refers to `docs/freecadcmd-notes.md` or to any of the five old smoke
      paths.
- [ ] `QT_QPA_PLATFORM=offscreen pixi run pytest tests/freecad_gui`, run
      directly rather than through `tools/run-tests.sh`, passes and exits on
      its own within 60 s, and leaves the developer's real FreeCAD settings
      directories untouched.
- [ ] `mypy --strict` clean, including both new `conftest.py` files.

## Advice

BOOTSTRAP. `import freecad`, the conda-forge FreeCAD package's own Python
package, loads FreeCAD's libraries so `import FreeCAD, Part` works from
plain Python in the pixi environment. Verified on FreeCAD 1.0.0 with the
four headless smokes: 47 passed in about 0.5 s under one plain `pytest`,
with no `Recompute` lines; re-check on 1.1, which the environment now
pins. Each new directory's `conftest.py` does this before any test module
imports FreeCAD.

ISOLATED SETTINGS. Each conftest points FreeCAD at throwaway settings
before importing it: a temporary directory set as `XDG_CONFIG_HOME`,
`XDG_DATA_HOME` and `XDG_CACHE_HOME`, with `tools/freecad-test-user.cfg`
copied to `config/FreeCAD/v1-1/user.cfg`, removed at session end. Without
this, FreeCAD 1.1's GUI start blocks on a settings-migration dialog when
older settings exist, and a notification popup deadlocks it headless
(`docs/freecadcmd-notes.md`, the two FreeCAD 1.1 sections). Both conftests
must do it, not only `tools/run-tests.sh`, so that a developer running
`pytest tests/freecad_gui` directly gets the same safe start. Once both
conftests do it, `tools/run-tests.sh` keeps its own XDG block only if the
`freecadcmd` import check needs it; keep that check off the developer's
real settings either way.

TWO PROCESSES, NOT ONE. The headless and GUI tests run as separate pytest
invocations, and neither shares a process with the core run. A running GUI
changes headless behaviour (`ViewObject` is no longer `None`, and
`FreeCADGui` is real), and the core run must stay FreeCAD-free for
`freecad/Shelving/core/tests/test_no_freecad.py`.

GUI HOST. `tests/freecad_gui/conftest.py` creates the `QApplication` if
none exists and calls `FreeCADGui.showMainWindow()` under
`QT_QPA_PLATFORM=offscreen`, after the ISOLATED SETTINGS setup. Verified
with the panel smoke on 1.0.0 (8/8 passed, clean exit). Not yet verified on
1.1: without isolation, `showMainWindow()` hung in the migration dialog
there. If the process does not exit cleanly once all 14+ tests run, fix it
in the conftest (a session-scoped teardown), never with `os._exit` in a
test module.

ONE `freecadcmd` CHECK STAYS (user decision): a minimal script that imports
the workbench and its GUI-registration module the way FreeCAD's startup
loads them, as today's `test_init_gui_imports_cleanly` does, and exits 1 on
any failure. It is a plain script ending in an explicit `sys.exit`, not a
self-invoking pytest module: one import assertion does not justify bringing
back the recursion guard and flush. Its reason is to catch startup-path
bugs, such as the duplicate core classes fixed on the
`fix-vendored-import-identity` branch, that plain pytest's import path
cannot see.

TEST LOCATION (user decision): `tests/freecad/test_*.py` for headless,
`tests/freecad_gui/test_*.py` for GUI. Keep each test's assertions intact.
The move must not weaken any test. Fixtures shared within a directory go in
its `conftest.py`.

NOTES FILE (user decision): `docs/freecadcmd-notes.md` moves to
`.claude/docs/freecad-notes.md`. It is agent reference material, not a
user-facing document, and the new name covers more than `freecadcmd`.
Delete the sections that only served the self-invoking pattern (exit
status, `__name__`, the recursion guard, stdout flushing, the progress bar)
unless the remaining `freecadcmd` check relies on one. Keep the FreeCAD
behaviour facts (frozen namespace path, `FreeCADGui` stub, `UndoMode`,
`ViewObject`, GUI widget access, the Notification Area, and the two FreeCAD
1.1 startup sections), pointing their "how tests avoid this" sentences at
the conftests. Add a short section on the `import freecad` bootstrap and
the embedded GUI. Git history keeps what is deleted.

REFERENCES. Update every live reference to the old smoke paths and the
notes path: code comments (`editor/panel.py`, `editor/session.py`,
`commands/edit_unit.py`, `unit_ops.py`), `README.md` § Tests,
`docs/manual-qa.md`'s introduction (which tells readers where to move an
automated case), `docs/architecture.md`, `pixi.toml` comments,
`.claude/docs/bug-log.md`, and the planned task `sh-022`. Leave
`tasks/completed/` alone: it is history.

MIXED RUNS SKIP THE FREECAD DIRECTORIES (2026-10-03, user decision, after
review round 1): a pytest run collects `tests/freecad/` or
`tests/freecad_gui/` only when every target lies inside that one
directory. Any other run, a bare `pytest` included, leaves both out and
says so in its summary, rather than failing. `tests/collection.py` holds
the rule and `tests/conftest.py` applies it. FreeCAD starts in each
directory's `pytest_sessionstart` under the same rule, because pytest
imports the conftest of every directory named on its command line before
any collection hook runs.

THE TASK FILE ITSELF (2026-10-03, implementation note): this file names
the old smoke and notes paths to describe the move, so until `/ship` moves
it to `tasks/completed/` it is the one file outside that directory still
naming them. The Must Have about live references holds once it ships.

CI is the user's to watch. The x86_64 runners use the same conda-forge
package, so the bootstrap should hold there, but only a push shows it.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python: both conftests and every
moved test stay `mypy --strict` clean with no bare `Any`. Shell stays
simple: `tools/run-tests.sh` loses its per-smoke blocks and only gets
simpler.

## Plan
- [x] **Step 1** (`tests/freecad/conftest.py`, `tests/freecad/test_*.py`): Move the scan, write, catalog and editor smokes' tests in as plain pytest modules, with the isolated settings and the bootstrap in the conftest and every self-invoke block, guard and flush removed. They pass under `pixi run pytest tests/freecad`.
- [x] **Step 2** (`tests/freecad_gui/conftest.py`, `tests/freecad_gui/test_*.py`): Move the panel smoke in, with the isolated settings and the embedded offscreen GUI in the conftest and the stdout redirect and `os._exit` removed. It passes under `QT_QPA_PLATFORM=offscreen pixi run pytest tests/freecad_gui`, run directly, and exits cleanly.
- [x] **Step 3** (`tools/`): Add the `freecadcmd` import check script and delete the five old smokes.
- [x] **Step 4** (`tools/run-tests.sh`): Run the core suite excluding the two new directories, then the import check, `pytest tests/freecad`, and the offscreen `pytest tests/freecad_gui`, each failing the run on a non-zero status. Verify the hand checks in Must Have (an import error fails fast, no `Recompute` lines).
- [x] **Step 5** (`.claude/docs/freecad-notes.md`, every referencing file): Move and trim the notes, update every live reference listed in Advice, and delete friction-021 (the progress-bar noise this task removes).

## Review log

### Round 1: REJECTED
- **F1: Running the core suite and the FreeCAD directories in one pytest process hangs with no output** (`tests/freecad_gui/conftest.py:31`): `pixi run pytest` with no arguments, and `pixi run pytest freecad/Shelving/core tests`, hang in collection at `FreeCADGui.showMainWindow()` and leave `/tmp/shelving-freecad-*` behind; mixing without the GUI conftest instead fails `test_importing_every_submodule_does_not_load_freecadgui`. "TWO PROCESSES, NOT ONE" is enforced only by `tools/run-tests.sh`, though the README invites running pytest directly. Add a collection guard that keeps the FreeCAD directories out unless they are the only targets, or a conftest check that stops a mixed session with a clear message, with a test of that decision.
- **F2: The `_alive()` production fix has no test** (`freecad/Shelving/editor/panel.py:199`): with `_alive` forced to `True` the GUI suite still passes, the RuntimeErrors appearing only after pytest finishes. Add a test that destroys a field's widget, delivers focus-out and `editingFinished`, and asserts nothing reaches `sys.excepthook` or `sys.unraisablehook`; cover the panel-closing path the docstring names, or narrow the docstring.
- **N1: pixi.toml comment still describes "the headless FreeCAD import smoke"** (`pixi.toml:29`); `.claude/docs/pipeline.md:30` ("a headless FreeCAD smoke") is stale the same way.
- **N2: Over-long line in the cfg comment** (`tools/freecad-test-user.cfg:5`).

### Round 2: REJECTED
- **F1: The fix commit drops the executable bit from the check harness** (`tools/run-tests.sh:1`): b4598e5 changes its mode from 100755 to 100644, likely via a sed-style edit, so `./tools/run-tests.sh` fails with "Permission denied" though `pixi.toml:33` names it directly. Restore 100755.
- **F2: The hook wiring that prevents the mixed-run hang has no test** (`tests/conftest.py:13`, `tests/conftest.py:35`, `tests/freecad/conftest.py:26`, `tests/freecad_gui/conftest.py:33`): only the pure rule functions are tested; the ignore hook and its `--ignore` suppression, the `config.args` rewrite, the `pytest_sessionstart` guards and the summary notes were checked only by hand, and a pytest upgrade breaking either assumption would bring back round 1's hang unnoticed. Add a core-run test that runs pytest in a subprocess under a timeout (mixed targets plus a bare or `tests` variant) and asserts no FreeCAD test is collected, both skip notes appear, and no `/tmp/shelving-freecad-*` is left.
- **N1: The `tests/collection.py` docstrings are inaccurate** (`tests/collection.py:3`, `tests/collection.py:81`): FreeCAD now starts in `pytest_sessionstart`, not when the conftest loads; the cited notes do not say a mixed run hangs or fails; and `skipped_freecad_dir` is not a hook.
- **N2: The round-1 N1 fixes add over-long lines** (`.claude/docs/pipeline.md:30`, `pixi.toml:29`).
- **N3: The new GUI test checks only `sys.excepthook`** (`tests/freecad_gui/test_panel.py:523`): patching `sys.unraisablehook` too is cheap.

### Round 3: REJECTED
- **F1: The new run tests do not cover the `pytest_sessionstart` guards, and the test's comment claims they do** (`tests/test_collection_runs.py:82`, `tests/freecad/conftest.py:27`, `tests/freecad_gui/conftest.py:34`): removing either or both guards still gives 6 passed, because each `pytest_sessionfinish` deletes the tree its `pytest_sessionstart` made, so the settings-tree comparison cannot see a FreeCAD start. Have the subprocess report whether FreeCAD loaded (for example print `'FreeCADGui' in sys.modules` after `pytest.main`), assert it for the mixed cases, and fix the comment.
- **N1: The docstring's reason for keeping the directories apart did not reproduce** (`tests/collection.py:6`): with both guards removed, a mixed run started the GUI after headless FreeCAD without hanging; what holds is the core FreeCAD-free test failing and the changed headless behaviour.
- **N2: Ragged rewrap** (`.claude/docs/pipeline.md:32`).
- **N3: The settings-tree comparison is not isolated** (`tests/test_collection_runs.py:83`, `tests/test_collection_runs.py:101`): it globs the shared temp dir; give the subprocess its own `TMPDIR`.

### Round 4: REJECTED
- **F1: The round-3 fix puts `pytest.main` back under `tests/`, which a Must Have forbids** (`tests/test_collection_runs.py:36`): the child-process driver string calls `pytest.main`, so `grep -rn pytest.main tests/` matches and the Must Have is unmet as written. Get the same post-run state without it, for example `python -m pytest -p <plugin>` with a plugin whose `pytest_unconfigure` writes `XDG_CONFIG_HOME` and `'FreeCADGui' in sys.modules` to a file in `tmp_path`; or the user narrows the Must Have and Advice records it.
