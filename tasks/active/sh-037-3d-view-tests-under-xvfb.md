---
id: sh-037
title: "3D-view tests under Xvfb"
---

# sh-037: 3D-view tests under Xvfb

## Summary
A new test tier runs FreeCAD's real 3D view under a virtual X display inside
`pixi run tests` and CI, with helpers that click, drag and press keys in the
view the way a user does. The offscreen GUI suite cannot create a 3D view, so
today anything that needs one (picking, draggers, `Std_Undo`, a rendered
image) is manual QA; this tier is what sh-039, sh-040 and sh-041 test
against, and it takes over the existing manual QA steps it can assert.
Milestone M14.

## Must Have
- [ ] `pixi run tests` green, and it runs the new `tests/freecad_view/`
      suite under Xvfb in its own process, separate from the headless and
      offscreen GUI suites.
- [ ] Xvfb comes from conda-forge's `xorg-xvfb-server` in `pixi.toml` for
      both `linux-64` and `linux-aarch64`, with `pixi.lock` updated; no
      system package is required, and `.github/workflows/ci.yml` still runs
      only `pixi run tests`.
- [ ] Starting and stopping Xvfb is typed Python (a free display number,
      `DISPLAY` set for the tier, the server stopped on every exit path,
      including a failed or interrupted run), not shell logic;
      `tools/run-tests.sh` gains at most a thin line invoking it.
- [ ] The tier starts FreeCAD's GUI once per process against throwaway
      settings (`tests.freecad_env`), and gives each test a new document
      with an active `Gui::View3DInventor` whose `getSize()` is positive;
      documents a test opened are closed after it.
- [ ] Typed helpers in `tests/freecad_view/` send real Qt events to
      `view.graphicsView().viewport()`: a click at a document point, a drag
      between two points, a key press, and an event pump. Tests prove them:
      - a click on a `Part::Box`'s face puts that box in
        `FreeCADGui.Selection.getSelectionEx()`;
      - a drag along an `SoTranslate1Dragger`'s axis added to the scene
        graph changes its `translation`;
      - `FreeCADGui.runCommand("Std_Undo")` undoes a committed transaction
        (it sends its message to the active view, so it does nothing
        offscreen).
- [ ] `write.opens-without-workbench` is no longer a manual QA case: a
      view-tier test saves a unit made by `unit_ops.create_unit`, opens it
      in a FreeCAD GUI process (under the same Xvfb) whose module path
      does not include this workbench, and asserts that every board is
      present with its saved bounding box and that the Report view and the
      process's output carry no error or warning naming a missing module.
- [ ] `scan.export-and-refusal`'s `refusal` step loses every expectation
      the tier asserts. At least: a view-tier test runs Edit Unit through
      its toolbar command on the overlap fixture and asserts the
      Notification Area shows the Shelving error and Overlap and LeftSide
      are drawn in FreeCAD's selection color in a rendered image of the
      view. What remains of the step, if anything, is what only a person
      can judge.
- [ ] Every other step of `freecad/Shelving/qa/cases/10-scan.toml` and
      `20-write.toml` was checked against the tier, and each one it can
      assert moved into `tests/freecad_view/`; the commit that removes a
      step names the test that replaced it. `30-editor.toml` is unchanged.
- [ ] `.claude/docs/xvfb-gui-testing.md` exists on `main`, describing this
      tier, its helpers and its limits, and `.claude/docs/code-map.md`
      lists `tests/freecad_view/`.
- [ ] `pyrefly check` clean over the new code; `tests/test_qa_cases.py`
      and `tests/test_code_map.py` pass.

## Advice

DECISIONS (user, 2026-10-13):
- **A new tier, not a replacement.** The offscreen suite in
  `tests/freecad_gui/` stays as it is, on `QT_QPA_PLATFORM=offscreen`:
  it is fast and needs no display. Only tests that need the 3D view go in
  `tests/freecad_view/`.
- **This task replaces manual QA where it can.** It owns the
  `10-scan.toml` and `20-write.toml` audit. Leave `30-editor.toml` alone:
  sh-039, sh-040 and sh-041 rewrite those cases for the editor that
  replaces today's.

FINDINGS from the viewport spike (branch `research/viewport-editing` at
`06d20ab`; keep that branch until sh-041 ships). Read
`06d20ab:.claude/docs/xvfb-gui-testing.md` and the driver
`06d20ab:research/spikes/drive_viewport_spike.py`, the worked example
whose `qt_point`, `send`, `click`, `drag` and `pump` the helpers grow
from:
- Offscreen Qt prints "QOpenGLWidget is not supported on this platform"
  and a script touching the active view can hang. Run the tier with
  `QT_QPA_PLATFORM=xcb`.
- OpenGL is Mesa's llvmpipe. If CI's runner lacks a library the dev VM
  has, add it from conda-forge, never through `apt`.
- `view.getPointOnViewport` is device pixels, y up; Qt events want
  logical pixels, y down. Under Xvfb the ratio is 1, so the helpers must
  still divide by `devicePixelRatioF()` to stay correct elsewhere.
- The view stayed 404 by 300 px whatever the main window size. Aim with
  margin: an 18 mm board is about 6 px tall in a default unit.
- CAD navigation (the default) holds back a press that comes sooner than
  `QApplication.doubleClickInterval()` after the previous one and replays
  it at release. Helpers wait past that interval between gestures
  (the driver used 700 ms).
- `QMouseEvent` carries the held buttons on move events; a drag is press,
  several moves with the button held, release, pumping between each.
- FreeCAD's GUI teardown can hang a scripted run. If a clean exit hangs,
  end the process with `os._exit` after the results are written, as the
  driver does, and make sure pytest's exit status survives that.
- `tests/freecad_gui/conftest.py` turns notification popups off because a
  popup deadlocks FreeCAD 1.1 offscreen. Under Xvfb, check whether that
  still holds before asserting on a popup; the Notification Area's own
  widget is the fallback to assert on.
- A rendered image comes from `view.saveImage(path, w, h, "White")`. It
  keeps FreeCAD's gradient background, so compare colors only at points
  projected onto the object, with a tolerance.
- FreeCAD imports a module once per process. Tests that need a fresh
  FreeCAD (the without-workbench test) run it as a subprocess.

CONSTRAINTS:
- Keep the tier's runtime modest, comparable to the offscreen GUI
  suite's: one FreeCAD per process, a new document per test, no fixed
  sleeps longer than a gesture gap.
- The tier must not run inside the offscreen suite's process, and the
  offscreen conftest must not start Xvfb (`tests/collection.py`'s
  `runs_only_inside` pattern keeps a conftest from acting on a run that
  names other directories).
- Nothing in `freecad/Shelving/` changes for this task except what a
  test needs as a public, generally useful helper (the QA wizard's
  public-API rule applies to tests too in spirit: no test-only hooks).
- `freecad/Shelving/qa/` setup actions and checks that only removed steps
  used are deleted with them; `tests/test_qa_guard_rails.py` stays green.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: the Xvfb launcher and the helpers are typed, with no bare
  `Any` except at pivy and FreeCAD boundaries, each commented; `pyrefly
  check` clean.
- Shell stays simple: the launcher is Python with importable, tested
  functions (choosing a display, waiting for the server); bash only
  invokes it.
- Users never read the log: no user-facing behavior changes.

## Plan
- [ ] **Step 1** (`pixi.toml`, `pixi.lock`): Add `xorg-xvfb-server` for both platforms.
- [ ] **Step 2** (`tools/`, `tools/run-tests.sh`): A typed Xvfb launcher that picks a free display, waits for the server, runs the view suite under it with `QT_QPA_PLATFORM=xcb`, and always stops it; unit tests for its pure functions; one line in `run-tests.sh`.
- [ ] **Step 3** (`tests/freecad_view/conftest.py`, `tests/freecad_view/`): Session start of FreeCAD's GUI with isolated settings, a per-test document with an active 3D view, and the typed event helpers, with the three helper-proving tests.
- [ ] **Step 4** (`tests/freecad_view/`, `freecad/Shelving/qa/cases/20-write.toml`, `freecad/Shelving/qa/actions.py`): The opens-without-workbench subprocess test; delete the manual case and any action only it used.
- [ ] **Step 5** (`tests/freecad_view/`, `freecad/Shelving/qa/cases/10-scan.toml`, `20-write.toml`, `freecad/Shelving/qa/actions.py`): The refusal test with the notification and the rendered selection color; audit every other step of both files and move each assertable one into the tier.
- [ ] **Step 6** (`.claude/docs/xvfb-gui-testing.md`, `.claude/docs/code-map.md`, `README.md` § Tests): Bring the Xvfb notes from `06d20ab`, rewritten for this tier; list the tier in the code map and the README's test section.

## Review log
