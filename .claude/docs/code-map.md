# Code map

An index of where each layer lives and which way its imports run. Each
module's docstring is the authority on what it does; this file never
restates one. `tests/test_code_map.py` checks that every path here exists,
that every top-level entry under `freecad/Shelving/` is listed, and that
the file stays under its word cap.

Each layer imports only the layers listed above it.

- `freecad/Shelving/core/`: the layout model, scanner, solver and edits, in
  pure Python, with its suite in `freecad/Shelving/core/tests/`. It never
  imports FreeCAD (`freecad/Shelving/core/tests/test_no_freecad.py`).
- `freecad/Shelving/properties.py`, `freecad/Shelving/container.py`,
  `freecad/Shelving/unit_ops.py`: reading and writing a FreeCAD document
  against the core. Tested headless in `tests/freecad/`.
- `freecad/Shelving/editor/`: `scene.py` draws and hit-tests with no
  document; `session.py` owns the document and its one transaction;
  `panel.py` is the Qt shell over a session. Tested in
  `tests/test_editor_scene.py`, `tests/freecad/test_editor_session.py`
  and `tests/freecad_gui/`.
- `freecad/Shelving/commands/`: one thin module per toolbar command.
- `freecad/Shelving/init_gui.py`: workbench registration.
- `freecad/Shelving/debug_log.py`: Report-view diagnostics, usable from
  any layer.
- `freecad/Shelving/resources/`: the workbench icon.

Outside the package: `tools/` holds the check scripts `pixi run tests`
drives, through `tools/run-tests.sh`.
