# Driving FreeCAD's 3D view under Xvfb

What running FreeCAD's full GUI under a virtual X display can and cannot
tell an agent, learned on the `research/viewport-editing` branch
(FreeCAD 1.1.3, Qt 6.11, the aarch64 dev VM). The pytest GUI suite stays on
`QT_QPA_PLATFORM=offscreen`; this is for research and spikes that need the
3D view itself. `research/spikes/drive_viewport_spike.py` is a worked
example.

## Why it is needed

Offscreen Qt cannot create FreeCAD's 3D view: it prints "QOpenGLWidget is
not supported on this platform", and a script that touches the active view
can hang without output. Anything that needs the scene graph, picking,
navigation styles, draggers or a rendered image needs a real X server.

## Running

`Xvfb` and `xvfb-run` are system packages on the dev VM (`/usr/bin`,
xvfb 21.1.22), outside pixi. OpenGL comes from Mesa's llvmpipe, a software
renderer (OpenGL 4.5 compatibility profile).

```
xvfb-run -a -s "-screen 0 1600x1000x24" \
    env QT_QPA_PLATFORM=xcb PYTHONUNBUFFERED=1 \
    pixi run python path/to/script.py > out.txt 2>&1
```

- Start FreeCAD the way `tests/freecad_gui/conftest.py` does, through
  `tests.freecad_env` (`isolate_freecad_settings`, `load_freecad`), so a
  run never touches real settings.
- Redirect output to a file and read it afterward. Piping straight into
  `grep` lost all output in one run.
- End the script with `sys.stdout.flush()` and `os._exit(0)`: FreeCAD's GUI
  teardown can hang a scripted run.
- Pump the event loop between steps (`app.processEvents()` in a short
  sleep loop); layout, focus and deferred `QTimer.singleShot(0, ...)` work
  all need it.

## What it does well

- **Real input paths.** A `QMouseEvent` sent with
  `QApplication.sendEvent` to `view.graphicsView().viewport()` goes through
  FreeCAD's navigation style and Coin's event traversal exactly as a user's
  click does. That exercised draggers, selection gates and event callbacks
  under each navigation style (`view.setNavigationType(...)`), which
  reading the source alone had not settled.
- **Picking.** `view.getObjectInfo`, `projectPointToLine` and
  `getPointOnViewport` return real answers, so a script can aim at a
  model point and assert on what was picked.
- **Text evidence.** Logging from inside event callbacks gives a timed
  record of what reached the scene graph and whether something earlier
  handled it.
- **Rendering.** `view.saveImage(path, w, h, "White")` renders the view at
  any size. One small PNG (480 by 360, about 7 KB) settled a rendering
  question (mirrored dimension text) that pixel-counting heuristics could
  not, because the saved image keeps FreeCAD's gradient background.
- **Speed.** A full driver run with a dozen interactions takes about 10 s.

## What it cannot tell you

- **Focus and window activation.** There is no window manager. Focus
  moved between widgets in ways a desktop may not reproduce, so a focus
  result here is a hint, never proof.
- **HiDPI.** The device pixel ratio is 1. Anything that converts between
  Coin's device pixels and Qt's logical pixels needs a real HiDPI screen.
- **View size.** The 3D view stayed 404 by 300 pixels despite resizing the
  main window and maximizing the MDI subwindows. At that size an 18 mm
  board is about 6 pixels tall, so aim clicks with margin, and expect
  overlapping labels the user's screen would not show.
- **Platform-specific native crashes.** The dev VM's Linux builds are not
  the macOS FreeCAD bundle: different Coin and Qt versions, and a
  different compiler. A crash from destroying a dragged dragger
  (coin3d/coin#556) hit only on macOS, where clang drops a null check the
  Linux build keeps. Compare library versions with the user's crash report
  (`libCoin.80.0.3` there, `libCoin.so.80.0.10` here) before trusting a
  clean Xvfb run.
- **Feel and render speed.** llvmpipe renders in software. Python-side
  timings (solve, write, scene rebuild) are representative; frame rates
  are not.

## Scripted-input pitfalls

- **Double-click detection.** CAD navigation holds back a left press that
  comes sooner than `QApplication.doubleClickInterval` after the previous
  press, and replays it only at the release
  (`NavigationStyle::processClickEvent`). A script that grabs a dragger
  right after a click therefore never drags. Wait about 700 ms between
  gestures.
- **OpenInventor navigation** consumes plain left clicks (left-drag
  orbits). Selection there takes Ctrl, and the first Ctrl+click's press is
  consumed too, so only its release reaches the scene graph.
- **Aim at the right axis.** A dragger moves along one axis; a scripted
  drag across that axis moves nothing and looks like a failure.
- **Default units** from `unit_ops.create_unit` have one bay and only outer
  boards. Split first when a test needs an inner board, and expect the
  solver to refuse sizes that leave a run with no free opening.
