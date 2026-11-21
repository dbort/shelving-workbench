---
id: sh-058
title: "Opt-in smoke tests under a hard time limit"
---

# sh-058: Opt-in smoke tests under a hard time limit

## Summary
`pixi run tests -- --smoke` took over five minutes at the last merge,
close to the full suite, because it left out only a handful of tests and
the 3D-view suite alone took 275 s. Smoke becomes opt-in: in the two GUI
FreeCAD suites only tests marked `smoke` run, which brings the run to
roughly 40 s on the dev VM. A hard 90 s limit stops the run and fails it,
so the smoke set cannot quietly grow back and a hung test cannot stall it.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] No `full_only` marker or mention remains in the repository outside
      `tasks/completed/` and the logs (`git grep full_only`).
- [ ] `tests/conftest.py` registers a `smoke` marker; `pytest --markers`
      lists it with a description of what earns a test the marker.
- [ ] `pixi run tests -- --smoke` runs, in full: the static checks, the
      core and repository pytest run, the workflow lint, the `freecadcmd`
      import check, and `tests/freecad/`. In `tests/freecad_gui/` it runs
      only the tests marked `smoke`, exactly one per `test_*.py` module.
      In `tests/freecad_view/` it runs exactly these three and no other:
      - `test_editor_input.py::test_a_selected_board_drags_by_its_arrow_under_each_navigation_style[Gui::CADNavigationStyle]`
      - `test_undo_in_the_editor.py::test_undo_and_redo_step_one_edit_and_the_panel_follows`
      - `test_scan_and_write.py::test_edit_unit_reads_a_hand_built_unit_and_close_changes_nothing`
- [ ] The full run (`pixi run tests` without `--smoke`) runs every test,
      including every parametrization that carried `full_only`.
- [ ] `pixi run tests -- --smoke` on the dev VM finishes in under 50 s of
      wall time; the measured time is recorded in the review log.
- [ ] A smoke run still going 90 s after it started is stopped: the
      command exits with status 124 and prints to stderr a line naming
      the 90 s smoke limit. Every process it started, including Xvfb and
      FreeCAD, is gone afterward. A test asserts the exit status, the
      message and the cleanup by driving the limit mechanism with a short
      limit against a stand-in command that starts a child process, and
      finishes in a few seconds.
- [ ] The full run has no time limit.
- [ ] `README.md`, `.claude/docs/pipeline.md` § Checks, the
      `tools/run-tests.sh` header comment and the marker description
      describe smoke as opt-in and state the 90 s limit.

## Advice
- **Opt-in scope** (user decision): only `tests/freecad_gui/` and
  `tests/freecad_view/` filter by marker. The core and repository tests
  (9 s) and `tests/freecad/` (6 s) stay whole in smoke because they are
  cheap and carry the repository invariants; the user chose more
  coverage over a few seconds.
- **3D-view picks** (user decision): the three tests in the Must Have.
  The drag sends a real click and drag through FreeCAD's navigation style
  and Coin's event traversal to the editor and on to the document; the
  undo test covers in-view edits against FreeCAD's undo stack and the
  task panel; the scan-and-write test covers reading a hand-built unit
  and writing nothing back. Mark only the CAD navigation-style
  parametrization of the drag test.
- **GUI picks:** one test per `tests/freecad_gui/test_*.py` module, the
  one that walks that module's main user path most broadly. Prefer a
  cheaper test when two cover the same path.
- **Pass the marker filter as arguments to the two GUI pytest runs, never
  through `PYTEST_ADDOPTS`:** `tests/test_collection_runs.py` starts
  child pytest runs with the inherited environment, and a `-m smoke`
  there would deselect everything in them. Remove the existing
  `PYTEST_ADDOPTS` export for `--smoke`.
- A tier left with no `smoke` test makes pytest exit 5 ("no tests
  collected"), which `set -e` turns into a failed run. That is the guard
  against a suite silently dropping out of smoke; do not suppress it.
- **Time limit** (user decision): 90 s, about three times the measured
  target, so an overloaded machine that stalls threads still passes a
  healthy run. It covers the whole smoke run from start to finish,
  static checks included, because that is the wait the user feels. Kill
  and fail at the limit (user decision) rather than finishing first, so
  a hang is bounded. Exit 124 follows coreutils `timeout`. The 90 lives
  in one named place.
- Kill the whole process group, not only the direct child: pytest,
  FreeCAD and Xvfb run as descendants, and `tools/xvfb_run.py` already
  stops its server when terminated
  (`tests/test_xvfb_run.py::test_a_terminated_launcher_stops_its_server_and_command`).
- **No parallel workers** (user decision): no pytest-xdist. Measured with
  four workers, the 3D-view suite exposed a test that depends on redraw
  timing under load, and eight workers came close to the VM's memory.
- **Shell stays simple:** a coreutils `timeout` call behind one
  conditional is within the rule. If the limit needs more than that to
  be testable without a user-facing knob, put it in a typed Python
  function under `tools/` that the test calls directly with a short
  limit, and have `run-tests.sh` invoke it.
- **Typed Python:** any new Python (conftest hook, limit function, test)
  is fully typed under the strict pyrefly preset.
- **Follow FreeCAD's own tools:** opted out. This is test
  infrastructure with no FreeCAD-facing behavior.
- **Users never read the log:** opted out. The timeout message goes to
  the developer's terminal running the checks, which is that tool's own
  UI.
- `.claude/skills/ship/SKILL.md` already names `--smoke` without
  describing its contents; it needs no edit.

## Plan
- [ ] **Step 1** (`tests/conftest.py`, `tests/freecad_view/test_undo_in_the_editor.py`, `tests/freecad_view/test_offset_unit.py`, `tests/freecad_view/test_editor_input.py`, `tests/freecad_view/test_padlocks.py`, `tests/freecad_view/test_editor_drawing.py`): Replace the `full_only` marker registration with `smoke`, its description saying a test earns it by being its GUI module's representative or one of the three 3D-view picks, and that every smoke test also runs in the full suite. Remove every `full_only` mark, collapsing `pytest.param(..., marks=...)` wrappers back to plain values.
- [ ] **Step 2** (`tests/freecad_gui/test_*.py`, `tests/freecad_view/test_editor_input.py`, `tests/freecad_view/test_undo_in_the_editor.py`, `tests/freecad_view/test_scan_and_write.py`): Mark one test per GUI module and the three 3D-view tests `smoke`; the drag test's mark goes on its CAD-style parameter only.
- [ ] **Step 3** (`tools/run-tests.sh`, `tools/` limit helper if needed, its test under `tests/`): `--smoke` adds `-m smoke` to the `tests/freecad_gui` and `tests/freecad_view` pytest runs and runs the whole script under the 90 s limit with process-group kill, exit 124 and the stderr message. Test the limit with a short limit and a stand-in command that spawns a child, asserting status, message and that the child is gone.
- [ ] **Step 4** (`README.md`, `.claude/docs/pipeline.md`, `.claude/docs/code-map.md` if it describes smoke): Describe smoke as opt-in by marker in the two GUI suites, the rest whole, under a 90 s hard limit; keep the `/ship` exception in `pipeline.md` § Checks unchanged.
- [ ] **Step 5**: Time `pixi run tests -- --smoke` on the dev VM, save its output and exit status to a file, and record the wall time in the review log.

## Review log
