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

CI is the user's to watch. The x86_64 runners use the same conda-forge
package, so the bootstrap should hold there, but only a push shows it.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python: both conftests and every
moved test stay `mypy --strict` clean with no bare `Any`. Shell stays
simple: `tools/run-tests.sh` loses its per-smoke blocks and only gets
simpler.

## Plan
- [ ] **Step 1** (`tests/freecad/conftest.py`, `tests/freecad/test_*.py`): Move the scan, write, catalog and editor smokes' tests in as plain pytest modules, with the isolated settings and the bootstrap in the conftest and every self-invoke block, guard and flush removed. They pass under `pixi run pytest tests/freecad`.
- [ ] **Step 2** (`tests/freecad_gui/conftest.py`, `tests/freecad_gui/test_*.py`): Move the panel smoke in, with the isolated settings and the embedded offscreen GUI in the conftest and the stdout redirect and `os._exit` removed. It passes under `QT_QPA_PLATFORM=offscreen pixi run pytest tests/freecad_gui`, run directly, and exits cleanly.
- [ ] **Step 3** (`tools/`): Add the `freecadcmd` import check script and delete the five old smokes.
- [ ] **Step 4** (`tools/run-tests.sh`): Run the core suite excluding the two new directories, then the import check, `pytest tests/freecad`, and the offscreen `pytest tests/freecad_gui`, each failing the run on a non-zero status. Verify the hand checks in Must Have (an import error fails fast, no `Recompute` lines).
- [ ] **Step 5** (`.claude/docs/freecad-notes.md`, every referencing file): Move and trim the notes, update every live reference listed in Advice, and delete friction-021 (the progress-bar noise this task removes).

## Review log
