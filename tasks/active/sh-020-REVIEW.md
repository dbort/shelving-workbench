# sh-020 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` exits 0 on the branch tip (ruff, format, mypy over 60 files,
267 pytest cases including `tests/test_editor_scene.py`, workflow lint, all four
FreeCAD smokes, and `shelving editor OK` printed and grepped). The three-layer
split is mostly in place. Two things block approval.

## Blocking findings
- **F1: Split axes are hard-coded in the panel, ignoring the unit's depth axis**
  (`freecad/Shelving/editor/panel.py:78-79`): **Split Horizontal** always passes
  `Axis.X` and **Split Vertical** always passes `Axis.Z`. The elevation's axes
  are `elevation_axes(unit.depth_axis)` (`freecad/Shelving/core/scan.py:338`),
  and scan can detect a depth axis of X or Z (the scan smoke covers a unit
  rotated a quarter turn, and a stored depth axis on a deep unit). For a unit
  with `depth_axis == Axis.X`, **Split Horizontal** would split the bay along
  its depth: the new board would be parallel to the elevation plane and would
  not show as a divider in the drawing. `depth_axis == Axis.Z` has the same
  problem for **Split Vertical**. This is a bug, and it is also the Frontier
  Advice's layer violation: mapping a button to a model axis is logic that
  depends on the unit, and it sits in the one module nothing tests. Move the
  mapping into `Session`, for example `split_across()`/`split_up()` or a
  `split(direction: Literal["horizontal", "vertical"])` that resolves the axis
  from `elevation_axes(self.unit.depth_axis)`, so the panel passes only what
  the user clicked. Add a smoke case that edits a unit whose depth axis is not
  Y and asserts the new board divides the bay in the elevation plane. While
  there, state in `docs/manual-qa.md` M9 case 3 which of the two buttons
  produces a shelf and which a vertical divider, so the manual check has a
  defined expected result.
- **F2: No test asserts what `split_region` produces**
  (`freecad/Shelving/core/tests/test_edit.py:219` and following): the Must Have
  requires that split "divides a `Bay` into two equal bays separated by a
  board". Step 1 specifies a `Division` along `axis` holding bay, board, bay,
  with both bays `Fill`, and a board material that defaults to the unit's.
  Only the round trip checks this, and only indirectly: any split output that
  `merge_at` happens to invert would pass. Add direct assertions on the split
  result: the replacement is a `Division` on the requested `axis` that carries
  the original bay's rule; its items are `Bay(Fill)`, `Board`, `Bay(Fill)`;
  the board's `material` is `None` by default and equals the argument when one
  is given; the untouched siblings are the same objects. Include the case
  where the root itself is the `Bay`.

## Non-blocking notes
- **N1: Eager PySide6 import can break the whole workbench**
  (`freecad/Shelving/commands/edit_unit.py:19`,
  `freecad/Shelving/editor/panel.py:21`): `init_gui` imports `edit_unit`
  during `Initialize`, and `edit_unit` imports the panel, and with it
  `PySide6`, at module scope. If that import fails on some user's FreeCAD
  build, every Shelving command fails to register, not only Edit Unit. The
  existing convention (`resize_unit.py:74`) imports Qt lazily inside the
  function that needs it. Importing `EditUnitPanel` inside `Activated` keeps
  any such failure contained to Edit Unit. I have not verified which Qt
  binding the target FreeCAD 1.0 install ships; this is a containment
  recommendation, not a confirmed break.
- **N2: A transaction is left open if the dialog never shows**
  (`freecad/Shelving/commands/edit_unit.py:70`,
  `freecad/Shelving/editor/panel.py:53-54`): the panel constructor opens the
  session's transaction before `Gui.Control.showDialog` runs. If `showDialog`
  refuses (another task dialog is already active), the transaction stays open
  and no dialog will ever commit or abort it. Separately, a scan or solve
  failure in `Session.__init__` escapes `Activated` as a traceback instead of
  a `REFUSED:` line like `resize_unit`'s.
- **N3: Refusals without a selection use an empty-string id**
  (`freecad/Shelving/editor/session.py:198`, `:210`): `EditFailure.node_id`
  is `""` for "nothing selected". `str | None` would state that directly.
  Neither refusal is exercised by the smoke. Also, the unsolvable-edit smoke
  (`tools/freecad_editor_smoke.py:238`) asserts only that an `EditFailure`
  came back; asserting its `node_id` would pin which refusal fired. The
  Must Have asks that the document stay "at the last state that did" solve.
  The smoke only checks this at session start, not after an accepted edit.
- **N4: The bounding-rect test is tautological**
  (`tests/test_editor_scene.py:113`): `sceneRect()` is exactly what
  `build_scene` sets from `unit.size_mm`. `scene.itemsBoundingRect()` would
  check that the drawn items fill the projected extent. Only
  `depth_axis == Axis.Y` is exercised. A second unit with a different depth
  axis would cover `_rect_for`'s projection and flip.
- **N5: The offscreen platform is not forced** (`tests/test_editor_scene.py:14`):
  `os.environ.setdefault` keeps any existing `QT_QPA_PLATFORM` (for example
  `wayland` or `xcb` exported in a developer's shell), so the suite would then
  open real windows or fail without a display. The Frontier Advice says to
  set it. Use a plain assignment.
- **N6: `merge_at` can silently drop a subtree and changes the rule on collapse**
  (`freecad/Shelving/core/edit.py:141-145`): the merged region is always the
  first neighbour. If the second neighbour is a `Division`, its boards
  disappear without a refusal, which is the "surprising tree" the Frontier
  Advice warns about, even though the letter of the spec allows it. When the
  enclosing `Division` collapses, the survivor takes the `Division`'s rule
  rather than its own. That is correct for the round trip, but the docstring
  only says the merged region carries "that neighbour's own rule". Document
  both behaviours, or refuse a merge whose second neighbour is not a leaf
  region.
- **N7: Dead check in the tests' `_find_bay_id` helpers**
  (`freecad/Shelving/core/tests/test_edit.py:92`,
  `tools/freecad_editor_smoke.py:71`): the recursive call raises instead of
  returning `None`, so `if found is not None` is dead. A nested `Division`
  with no bay also aborts the search instead of moving on to the next
  sibling.
- **N8: Execution Plan text was rewritten** (task file, Step 3): the
  Implementer replaced the Planner's path ("`freecad/Shelving/editor/tests/test_scene.py`
  or the repo's test location for FreeCAD-side code") with
  `tests/test_editor_scene.py` instead of only checking the step off.
  `tests/test_editor_scene.py` itself fits the plan: it is the "or" branch,
  it is the directory `pytest freecad/Shelving/core tests` already collects,
  and `scene.py` imports no FreeCAD, so plain pytest is correct.
  `freecad/Shelving/editor/tests/` would not have been collected without
  changing `run-tests.sh`. Record choices like this in the handoff, not in
  the plan text. Restore the original wording.

## Judged points raised by the Implementer
- **`pyside6-stubs==6.7.3.0` in `[pypi-dependencies]`: accepted.** The pin
  matches PySide6 6.7.3 in this environment. It follows the `freecad-stubs`
  precedent, carries a comment explaining why, and the lock adds only the
  stubs wheel (conda's `pyside6` still satisfies `pyside6>=6.0`).
  `check_lock_paths` passes.
- **`doc.UndoMode = 1` in `Session.open`: accepted.** Cancel and
  commit-then-undo only work when undo is on, and the smoke proves both. The
  rationale is in the docstring and in `docs/freecadcmd-notes.md`. GUI
  documents already have undo on, so the change has no effect there.
