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
Each smoke test names the user path it covers, and a new standing
planning obligation makes every future task keep that set representative
as features come and go.

## Must Have
- [ ] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [ ] No `full_only` marker or mention remains in the repository outside
      `tasks/completed/` and the logs (`git grep full_only`).
- [ ] `tests/conftest.py` registers a `smoke` marker that takes one
      argument, the user path the test covers
      (`@pytest.mark.smoke("open Edit Unit, change a size")`);
      `pytest --markers` lists it with that signature and a description
      of what earns a test the marker.
- [ ] `pixi run tests` fails, naming the test, on a `smoke` mark with no
      path, an empty path, or more than one argument, and on two `smoke`
      marks that give the same path, whether both are in one suite or one
      is in `tests/freecad_gui/` and the other in `tests/freecad_view/`.
      A test covers each case.
- [ ] `pixi run tests -- --smoke` runs, in full: the static checks, the
      core and repository pytest run, the workflow lint, the `freecadcmd`
      import check, and `tests/freecad/`. In `tests/freecad_gui/` it runs
      only the tests marked `smoke`. In `tests/freecad_view/` it runs exactly these three and no other:
      - `test_editor_input.py::test_a_selected_board_drags_by_its_arrow_under_each_navigation_style[Gui::CADNavigationStyle]`
      - `test_undo_in_the_editor.py::test_undo_and_redo_step_one_edit_and_the_panel_follows`
      - `test_scan_and_write.py::test_edit_unit_reads_a_hand_built_unit_and_close_changes_nothing`
- [ ] In a smoke run, the `tests/freecad_gui/` and `tests/freecad_view/`
      pytest output each ends with the list of smoke tests that ran, each
      with its user path.
- [ ] `CLAUDE.md` § Standing task-planning obligations has a **Smoke set
      stays representative** entry per the Advice.
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
- **GUI picks** (user decision): the smallest set of
  `tests/freecad_gui/` tests that together give quick confidence the
  workbench's GUI is healthy. Choose by coverage of the main user paths,
  not by module: a module may contribute two tests or none. Prefer a
  test that walks a path end to end over several narrow ones, and the
  cheaper of two tests that cover the same path.
- **Keeping the set representative** (user decision): the path on each
  mark records why the test is in smoke, so a later task can see what
  the set covers and what a removal loses. The duplicate-path check
  catches two tests claiming one path, the likeliest sign that one is
  redundant. Completeness takes judgment no check can make, so it goes in
  a standing obligation, which `new-task` already applies to every plan.
  Add this entry to `CLAUDE.md`, worded to that list's style: a task that
  adds, changes or removes a main user path in the GUI or 3D view, or
  deletes or rewrites a `smoke` test, adds, moves or retires `smoke`
  marks so the set still gives quick confidence in the workbench's
  health and the smoke run stays well inside its 90 s limit. A task that
  touches none of these says so in `## Advice`. The 90 s limit is the
  counterweight against the set growing.
- Paths are short user-vocabulary phrases ("drag a selected board by its
  arrow"), no function or class names, so the printed list reads as a
  coverage summary. The duplicate check compares the strings exactly;
  do not build fuzzy matching.
- The two marked suites run in separate pytest processes, so a check
  inside one run cannot see the other's marks. Put the cross-suite
  duplicate check where both are visible, such as a repository test in
  the core run that reads the marks from both directories' sources.
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
- [ ] **Step 1** (`tests/conftest.py`, a new repository test under `tests/`, `tests/freecad_view/test_undo_in_the_editor.py`, `tests/freecad_view/test_offset_unit.py`, `tests/freecad_view/test_editor_input.py`, `tests/freecad_view/test_padlocks.py`, `tests/freecad_view/test_editor_drawing.py`): Replace the `full_only` marker registration with `smoke`, its description saying a test earns it by being part of the small set that together shows the GUI and 3D view are healthy, and that every smoke test also runs in the full suite. Validate every collected `smoke` mark's argument and print the run's smoke tests with their paths at the end of a run that selected `-m smoke`. Add the repository test for duplicate paths across both suites and tests for each invalid-mark case. Remove every `full_only` mark, collapsing `pytest.param(..., marks=...)` wrappers back to plain values.
- [ ] **Step 2** (`tests/freecad_gui/test_*.py`, `tests/freecad_view/test_editor_input.py`, `tests/freecad_view/test_undo_in_the_editor.py`, `tests/freecad_view/test_scan_and_write.py`): Mark the GUI set chosen per the Advice and the three 3D-view tests `smoke`, each with its user path; the drag test's mark goes on its CAD-style parameter only.
- [ ] **Step 3** (`tools/run-tests.sh`, `tools/` limit helper if needed, its test under `tests/`): `--smoke` adds `-m smoke` to the `tests/freecad_gui` and `tests/freecad_view` pytest runs and runs the whole script under the 90 s limit with process-group kill, exit 124 and the stderr message. Test the limit with a short limit and a stand-in command that spawns a child, asserting status, message and that the child is gone.
- [ ] **Step 4** (`README.md`, `CLAUDE.md`, `.claude/docs/pipeline.md`, `.claude/docs/code-map.md` if it describes smoke): Describe smoke as opt-in by marker in the two GUI suites, the rest whole, under a 90 s hard limit, each mark naming its user path; add the standing obligation to `CLAUDE.md`; keep the `/ship` exception in `pipeline.md` § Checks unchanged.
- [ ] **Step 5**: Time `pixi run tests -- --smoke` on the dev VM, save its output and exit status to a file, and record the wall time in the review log.

## Review log
