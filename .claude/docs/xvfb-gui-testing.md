# Testing FreeCAD's 3D view under Xvfb

What running FreeCAD's GUI on a virtual X display can and cannot tell a
test, and how `tests/freecad_view/` does it. The offscreen suite in
`tests/freecad_gui/` stays on `QT_QPA_PLATFORM=offscreen`; only a test that
needs the 3D view belongs here.

## Why a display is needed

Offscreen Qt cannot create FreeCAD's 3D view: it prints "QOpenGLWidget is
not supported on this platform", and a test touching the active view can
hang without output. `Std_Undo` and `Std_Redo` send their message to the
active view, so offscreen they do nothing at all. Picking, navigation
styles, draggers, Coin event callbacks and a drawn image all need a real X
server.

## Running

`pixi run tests` runs the suite last, through `tools/xvfb_run.py`. On its
own:

```sh
pixi run python -m tools.xvfb_run pytest tests/freecad_view -k refusal
```

The launcher starts conda-forge's `Xvfb` from the pixi environment with
`-displayfd`, so the server picks a free display and reports it once it
accepts connections, then runs the command with `DISPLAY` set and
`QT_QPA_PLATFORM=xcb`, and stops the server on every exit path. The
environment carries what that server needs: `xkeyboard-config` (passed as
`-xkbdir`, since conda-forge installs it under
`share/xkeyboard-config-2` while its Xvfb looks in `share/X11/xkb`) and
Mesa's `llvmpipe` for GLX. Without Mesa, Qt reports "neither GLX nor EGL
are enabled". No system package is involved, so CI and the dev VM run the
same build.

`tests/freecad_view/conftest.py` refuses to start FreeCAD without that
display, starts the GUI once per process against throwaway settings, and
its `driver` fixture gives each test a new document with an active 3D view.
`tests/freecad_view/view.py` holds the driver.

## The driver

- **Real input paths.** A `QMouseEvent` sent with `QApplication.sendEvent`
  to `view.graphicsView().viewport()` goes through FreeCAD's navigation
  style and Coin's event traversal exactly as a user's click does.
- **Coordinates.** `view.getPointOnViewport` answers in device pixels with
  y up; Qt events take logical pixels with y down. The driver converts
  both ways, dividing by the device pixel ratio, which is 1 under Xvfb.
- **Gesture gaps.** CAD navigation holds back a left press that comes
  sooner than `QApplication.doubleClickInterval()` after the previous one
  and replays it only at the release (`NavigationStyle::processClickEvent`),
  so a drag right after a click never starts. The driver waits out the
  interval before each press.
- **Drags** are press, several moves carrying the held button, release,
  with the event loop pumped between each.
- **Waiting.** `pump()` runs the event loop until 30 ms pass with no event,
  capped at 2 s. FreeCAD fires idle timers about every 40 ms, so the loop
  is never silent for long, while work in progress produces an event every
  few milliseconds. A camera animation and the editor's 20 ms turn poll
  keep it busy, so `pump()` returns once a turn has finished.
  `pump(ms)` runs for a fixed time instead. Use it only to stop partway
  through something, such as a turn still running. Fixed waits sized
  generously were most of the suite's run time.
- **Short animations.** `tools/freecad-test-user.cfg` sets FreeCAD's
  `AnimationDuration` to 100 ms. Animations stay on, so tests take the
  animated path a user meets. A test that acts mid-turn takes the
  `slow_turns` fixture and acts without a `pump()` in between, which
  would wait the turn out. Tests assert where the camera starts and ends,
  never that it moved in between. Whether a turn's frames ever move the
  camera is unreliable to assert: with a 1 s turn, a turn back started
  right after Edit Unit's turn sometimes had not moved after 500 ms. The
  `editor.camera` manual QA case checks that turns run smoothly.
- **Images.** `grab()` returns the view as drawn, in device pixels, and
  `color_at` reads it at a document point. Lighting and blending change a
  color, so compare the same point before and after rather than against a
  configured color.

## Pitfalls

- **Keep the `QGraphicsView` wrapper.** Once the wrapper
  `view.graphicsView()` returns is collected, the viewport's wrapper reads
  as deleted. The driver holds it.
- **A new document's view appears only after Qt runs.** Read
  `ActiveView` before pumping and it is the previous, deleted view.
- **Camera moves animate.** `viewFront` and `fitAll` animate when
  navigation animations are on; `pump()` waits them out before a grab.
- **The Tasks dock is hidden.** In a fresh FreeCAD 1.1 profile the Tasks
  dock sits in the right-hand overlay panel, which stays hidden until
  hovered, so a task dialog's buttons are not visible; press them with
  `click()`.
- **Commands register when the workbench first activates.** Activate
  `ShelvingWorkbench` before `FreeCADGui.runCommand("Shelving_...")`.
- **Notification popups stay off.** A popup deadlocks FreeCAD 1.1 under
  Xvfb as it does offscreen (`freecad-notes.md`), and the test settings
  turn them off. The Notification Area's status-bar button still counts
  each notification. The status bar's own message is gone again by the
  time a test reads it, so it is not asserted. Under conda-forge's FreeCAD
  1.1.3 with popups off, `PrintTranslatedUserError` text does not reach the
  Report view while `PrintError` text does, so the Report view is not
  asserted either; the `scan.refusal` manual step checks it in a desktop
  FreeCAD (`freecad-notes.md` § User-facing errors).
- **Focus the 3D view before `Std_Undo` or `Std_Redo`.** Under Xvfb,
  FreeCAD disabled both while keyboard focus sat in a task panel's combo
  box.
- **The Notification Area does not count a repeated message.** Its
  status-bar count stays put when the same text comes again; to assert a
  message seen twice, record the calls that report it instead.
- **The Report view is not where `print` goes under pytest.** pytest
  captures standard output first; read it with `capsys`.
- **FreeCAD's GUI takes over standard output** in a child process too, so
  a child FreeCAD hands results back through a file
  (`open_without_workbench.py`).
- **The editable install puts this workbench on `sys.path`,** and FreeCAD
  loads every `freecad.*` package it can import. A child that must run
  without the workbench removes the repository's entries from `sys.path`
  before importing `freecad`.
- **`pivy` must be imported** before `getSceneGraph()`, or it raises "No
  SWIG wrapped library loaded", and only after `showMainWindow()`: a child
  process that imported it first, through the editor's modules, crashed
  rendering its first 3D view under `MALLOC_PERTURB_`.
- **A path `SoSearchAction` finds lives only as long as the action.** Copy
  and `ref()` each one before the action is collected.
- **Wait for the editor's camera turn.** Edit Unit animates the camera
  toward the unit; aim only once `ViewEditor.turning` is false, as
  `tests/freecad_view/editor.py`'s `edit_unit` does.

## What it cannot tell you

- **Focus and window activation.** There is no window manager; a focus
  result here is a hint, never proof.
- **HiDPI.** The device pixel ratio is 1.
- **View size.** The 3D view is about 400 by 300 pixels in a test run
  alone, and larger once earlier tests in the same process have changed
  the window layout, so a test that needs a pixel scale sets the camera
  itself. In a fitted view an 18 mm board is a few pixels tall, inside
  FreeCAD's pick radius of its edges: zoom in before aiming at a face.
- **Platform-specific native crashes.** The Linux builds here are not the
  macOS FreeCAD bundle: a crash from destroying a dragged dragger
  (coin3d/coin#556) hits only on macOS, where clang drops a null check the
  Linux build keeps.
- **Feel and frame rate.** llvmpipe renders in software; Python-side
  timings are representative, frame rates are not.
