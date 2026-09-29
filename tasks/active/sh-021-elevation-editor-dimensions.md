---
id: sh-021
title: "The elevation editor: dimensions"
blocked_by: [sh-020]
---

# sh-021: The elevation editor: dimensions

## Summary
The editing half of the panel: type an exact opening size, drag a board to set
one, and choose whether a dimension measures the clear opening or the spacing
across a board. Dragging changes the number and never what it measures, so a
drag can never rewrite intent. Also gives apply's untagged objects the
interactive choice M7 deferred here, since a panel has somewhere to put the
question. The dimension field is FreeCAD's own quantity input, so an expression
naming a variable works and this workbench inspects nothing a user types.
Milestone M9, part 2 of 2.

## Must Have
- [ ] `pixi run tests` green.
- [ ] `freecad/Shelving/core/edit.py` gains `set_size(unit, region_id, size_mm, basis)`
      returning a `Unit` with that region's rule replaced by a `Fixed` at that
      size and basis, leaving every sibling's rule untouched.
- [ ] `set_basis(unit, region_id, basis)` changes only what a size measures,
      recomputing the stored number so the geometry is unchanged. A test asserts
      the solved layout before and after is identical.
- [ ] The dimension field is FreeCAD's own quantity input, obtained through
      `FreeCADGui.UiLoader().createWidget`, so it accepts exactly what every
      other length field in FreeCAD accepts, including expressions naming a
      `VarSet`, and shows the resolved value as the user types. No input is
      inspected, rewritten, or refused by this workbench.
- [ ] If that widget proves unobtainable in the GUI, the fallback is a plain
      field passed verbatim to `FreeCAD.Units.parseQuantity`, with the parse
      error surfaced. Still no inspection of the text.
- [ ] Dragging a board sets the size of the region on one side, keeping that
      region's existing basis. A test drives a drag through the session and
      asserts the basis is unchanged and only the number moved.
- [ ] A dimension is drawn showing what it measures: a clear opening spans the
      void, a spacing spans from one board's face to the next and visibly
      crosses a board. Asserted by item geometry, not pixels.
- [ ] Changing a catalog thickness holds board positions for a region whose
      basis is spacing and moves them for one whose basis is clear. Asserted in
      the headless smoke against one document.
- [ ] The panel lists objects the write path left alone, with the reason, and
      offers to remove them or keep them; keeping is the default and removal
      happens only inside the session's transaction.
- [ ] An edit that will not solve returns the error and leaves the document at
      the last state that solved, as in sh-020.
- [ ] `docs/manual-qa.md`'s M9 section gains the dimension cases.
- [ ] `mypy --strict` clean.

## Advice

DRAGGING CHANGES THE NUMBER, NEVER WHAT IT MEASURES. This is the rule the whole
task hangs on. A region's `Basis` is set explicitly and persists; a drag
recomputes that region's `Fixed` size in whatever basis it already has. A drag
that silently flipped a clear opening into a spacing would rewrite the user's
intent, which is the same class of failure as a guessed facing, and the model
would then mean something different from what the user thinks.

BASIS IS PER DIMENSION, NOT A MODE. A real unit mixes them: a fixed 300 mm clear
slot for a router at the bottom and regular spacing above it. Set it on the
selected region and store it on that region's rule.

`set_basis` MUST NOT MOVE ANYTHING. Changing what a number measures is a change
of intent, not of geometry. Recompute the stored number so the solved layout is
identical, and assert that in a test. A user toggling the basis to see which
they meant must not find their unit has moved.

DO NOT VALIDATE, REWRITE, OR INSPECT WHAT THE USER TYPES. The field accepts
FreeCAD expression syntax, not a number: `(VarSet.someLength - 2 *
VarSet.someThickness) + 3/4"` is legitimate input. Any pattern check over that
grammar produces false refusals, and a false refusal has no workaround. A regex
looking for a whole number before a fraction matches `VarSet.x2 - 1/2"` on an
identifier ending in a digit, refusing a valid expression. Pass the text
through untouched.

USE FREECAD'S OWN QUANTITY INPUT WIDGET, via
`FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")` or the equivalent
input field. That gives expression support, the f(x) binding to a `VarSet`, the
user's configured unit schema, and a live display of the resolved value, all
without this workbench parsing anything. It also makes the field behave
identically to every other length field in FreeCAD, which is its own kind of
correctness.

NOT VERIFIED HEADLESSLY: `FreeCADGui.UiLoader` does not exist under
`freecadcmd`, so confirm the widget loads in a real GUI session early in this
task. If it does not, fall back to a plain field handed verbatim to
`FreeCAD.Units.parseQuantity`, surfacing its error. Do NOT fall back to
inspecting the text.

CONTEXT ON FREECAD'S PARSER, verified in this environment, recorded so nobody
rediscovers it and decides to "fix" it: `3/4"` is 19.05 mm and `1 + 1/2"` is
38.10 mm, both correct, with the unit applying to the whole sum. `12 1/2"`
raises. `1-1/2"` returns 12.70 mm, reading the hyphen as subtraction. That last
one is a wrong answer with no error, but it is FreeCAD's behaviour in every
length field in the application, so this workbench matches it rather than
diverging. A resolved-value display is what surfaces it, and it surfaces every
other surprising input too, which a pattern check never could.

DIMENSION DRAWING MUST DISTINGUISH THE TWO BASES. Use the drafting convention
the design already implies: witness lines touching the faces actually measured.
A clear dimension spans the void between two boards; a spacing dimension spans
from one board's face to the matching face of the next and so visibly crosses a
board. Drawn that way they are distinguishable without a label. Show the other
number as a readout beside it, because a person choosing stock wants both.

UNTAGGED OBJECTS, the choice M7 deferred here. sh-018's write path returns what
it left alone and never deletes an object this workbench did not write. The
panel lists those with their reasons and offers to remove or keep them, KEEPING
BY DEFAULT. Explain in the panel why it is asking: these were not generated by
the workbench, so it will not touch them unless told. Any removal happens inside
the session's transaction so Cancel reverses it.

LAYERING IS UNCHANGED FROM sh-020. Every decision with a right answer goes in
`freecad/Shelving/core/edit.py` and is tested in the fast suite. The scene renders and hit-tests, tested offscreen. The session owns the
document. The panel holds no logic worth testing. A drag in particular: the
scene reports which board moved and to what scene position, the session converts
that to a size and calls the core.

DRAG RE-SOLVES ON EACH STEP, writing the real boards as sh-020 does. Measured
cost is about nine milliseconds for forty-five boards, so a drag can update
live. If that proves slow on a larger unit, debounce in the panel rather than
introducing a second preview model.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. Shell
stays simple does not apply; this task adds no shell.

Every length identifier carries `_mm`.

DECISIONS MADE DURING `/work` (2026-09-27):

- THE DIMENSION FIELD BINDS TO A TEMPORARY PROBE OBJECT. The Step 1 spike
  showed the widget resolves a `VarSet` name only when bound to a document
  property, and that its f(x) dialog writes the expression straight into
  that property. A region's size is not a property, so `Session.open`
  creates a top-level `App::VarSet` probe with one Length property inside
  the transaction; `commit` deletes it before committing and `cancel`'s
  abort removes it. No expression survives the session; the rule stores the
  resolved number. Later `VarSet` edits do not move boards; storing
  expressions in rules would be its own task.
- `set_basis` ON A `Weighted` OR `Fill` REGION CONVERTS IT TO `Fixed` at its
  current solved size in the requested basis, so the geometry is unchanged
  and the region stops absorbing slack from then on.
- A DRAG SIZES THE REGION IMMEDIATELY BEFORE THE BOARD in its run (below or
  left), since that region's `WITH_NEXT` spacing ends at the dragged board's
  far face. A board first in its run, or with a board before it, refuses
  the drag.
- CORRECTION TO STEP 7's QA CASE: with the field's unit set to mm, the
  widget reads a bare number as millimetres even inside a sum, so `1 +
  1/2"` resolves to 13.70 mm, not 38.10 mm (`1" + 1/2"` is 38.10 mm). The
  manual QA case checks both readouts. Recorded in `docs/freecadcmd-notes.md`.
- SIGNATURES THE PLAN ABBREVIATED. `set_basis(unit, region_id, basis,
  catalog)` takes the catalog, as `split_region` and `merge_at` do: restating
  the number needs the solved extent and the next board's catalog thickness.
  `Session.begin_drag(board_id, grab_mm)` takes the unit-frame grab point so
  each `drag_to(pointer_mm)` keeps that point under the pointer instead of
  jumping the board by up to half its thickness on the first move. The
  drag's position-to-size conversion is `core.edit.move_board`, which calls
  `set_size`, keeping that decision in the fast-tested core.
- SMOKE TESTS ARE PYTEST MODULES (user instruction, after round 2). Every
  smoke under `tools/` is a self-invoking pytest module, never a hand-rolled
  runner or marker line, unless there is a strong stated reason.
  `freecad_panel_smoke.py` and `freecad_editor_smoke.py` both self-invoke
  before any FreeCAD import, so an import failure fails the run instead of
  passing (`freecadcmd`) or hanging (the GUI).
- MANUAL-QA FOLLOW-UPS (2026-09-27, the user's QA on FreeCAD 1.1.1).
  Text the quantity widget does not accept is never applied: a Return on it
  is consumed rather than reaching the task panel as OK, and leaving the
  field puts the last shown value back. The widget's own `acceptableInput`
  verdict decides, so this inspects no text, and the panel adds no
  as-you-type feedback of its own (2026-09-29: a live error line was
  removed at the user's request as unlike FreeCAD, and its show/hide made
  the task panel jump). Keeping only the resolved number is bug-010.
  Dimension lines end in arrowheads. Refusals read
  as plain sentences with no node ids (`describe_solve_error`). Overlapping
  dimensions are bug-009, deferred to its own task. A last region in a
  nested run (the upper bay under the unit's top) has no spacing basis,
  since the solver's `WITH_NEXT` reaches only the next item in the same
  run; the QA case says so rather than the model changing here.

## Plan

- [x] **Step 1** (spike, no committed code): Before writing the panel, open a real FreeCAD GUI session and confirm `FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")` returns a usable widget, that it accepts `1 + 1/2"` and an expression naming a `VarSet`, and that it exposes the resolved quantity to Python. Record the answer in `docs/freecadcmd-notes.md` under a heading for GUI-only widget access, including the exact widget name that worked. If none works, record that and use a plain field with `FreeCAD.Units.parseQuantity` for the rest of this task.

- [x] **Step 2** (`freecad/Shelving/core/edit.py`, `freecad/Shelving/core/tests/test_edit.py`): Add `set_size(unit, region_id, size_mm, basis)` replacing that region's rule with a `Fixed` carrying both, refusing an unknown id and a non-positive size. Add `set_basis(unit, region_id, basis)` changing only the basis and recomputing the stored number from the region's currently solved extent so the geometry is unchanged; refuse a `Basis.WITH_NEXT` on a region whose next item is not a board, since sh-013's solver cannot resolve it. Tests: `set_size` leaves siblings' rules untouched; `set_basis` in both directions leaves the solved layout identical, asserted space by space; the refusals; and the behaviour that gives basis its purpose, a layout solved against two catalogs of different thickness holding board positions under `WITH_NEXT` and moving them under `CLEAR`.

- [x] **Step 3** (`freecad/Shelving/editor/scene.py`): Add dimension items. For each region draw a dimension whose witness lines touch the faces its basis measures: a clear dimension spanning the void, a spacing dimension spanning from one board's face to the next and crossing that board. Tag each dimension item with its region id so it can be hit-tested and selected. Add a readout of the other basis's value beside it. Extend the offscreen suite: assert the two bases produce dimension items of different span for the same region, that a dimension item's endpoints lie on the faces expected, and that hit-testing a dimension returns its region id.

- [x] **Step 4** (`freecad/Shelving/editor/session.py`): Add the dimension operations. `set_size(size_mm)` taking a millimetre value already resolved by the widget, and calling the core with the selected region's EXISTING basis. The session does not see raw text: parsing belongs to FreeCAD's widget, and a parse failure never reaches here. `set_basis(basis)` calling the core. `begin_drag(board_id)`, `drag_to(position_mm)` and `end_drag()` converting a board's new position into a size for the region on one side and calling `set_size` with that region's existing basis, re-solving and writing on each step. Every one returns the new state or a structured failure, as in sh-020.

- [x] **Step 5** (`freecad/Shelving/editor/session.py`, `freecad/Shelving/editor/panel.py`): Add the untagged-object choice. The session exposes what the last write left alone, each with its reason, and a `remove_untagged(ids)` that deletes exactly those inside the session's transaction. The panel shows them in a list with checkboxes, all unchecked by default, with text explaining that these were not generated by the workbench and will be left alone unless selected. Wire the dimension field, the basis control, and drag handling on the view to the session, showing a failure's message without changing the view.

- [x] **Step 6** (`tools/freecad_editor_smoke.py`): Extend the headless check, driving the session. Assert: a set size fixes that region and redistributes its siblings; a drag changes the number and leaves the region's basis as it was; toggling basis leaves every board's placement identical; changing the catalog thickness afterwards holds board positions for a `WITH_NEXT` region and moves them for a `CLEAR` one in the same document; an untagged box is listed as left alone and survives unless selected, and is removed inside the transaction when it is; and cancel after all of the above restores the document exactly.

- [x] **Step 7** (`docs/manual-qa.md`, `README.md`): Extend the `## M9` section with the dimension cases: type an exact opening and watch the rest redistribute; type `1 + 1/2"` and confirm the field resolves it to 38.10 mm in the readout; bind the field to a `VarSet` property with the f(x) button and confirm it follows; drag a board and confirm the readout shows the basis it already had; switch a dimension to spacing and confirm nothing moves; change the stock thickness and confirm the spacing-based shelves hold while the clear-based ones move; and confirm the untagged-object list appears with nothing checked. Extend the README glossary with measurement basis and the drag rule.

## Review log

### Round 1: REJECTED
- **F1: A click on a board with any pointer jitter rewrites the region below it and drops the board selection** (`freecad/Shelving/editor/panel.py:322`, `freecad/Shelving/editor/panel.py:332`): every press on a board starts a drag and every held move calls `Session.drag_to`, with no start-drag distance; a 1 mm jitter turned the lower bay from `Fill()` into `Fixed(424.0, CLEAR)` and moved the selection off the board, disabling Delete. Start the drag only past `QApplication.startDragDistance()`, with a test.
- **F2: After one f(x) binding, the dimension field is read-only for every region for the rest of the session** (`freecad/Shelving/editor/panel.py:97`, `freecad/Shelving/editor/session.py:366`): the probe's expression is never cleared, so the field stays bound and read-only, and typed input is ignored. Clear the expression once its value is applied (or on selection change); add the sequence to manual QA case 12 and to the test in F3.
- **F3: The panel's wiring has logic but no durable test, and one-off GUI scripts found real defects** (`.claude/docs/friction-log.md:230`, `freecad/Shelving/editor/panel.py:126`): `pipeline.md` § Checks requires a durable test for a check needing live infrastructure. Add an offscreen-GUI panel smoke to `tools/run-tests.sh` covering the widget type, a typed value, an unchanged focus-out leaving a Fill region untouched, f(x) then typing on another region, a jittered click not dragging, a real drag keeping the basis, the untagged checkboxes unchecked by default, and Remove then reject restoring the object.
- **F4: Millimetre quantities without the `_mm` suffix** (`freecad/Shelving/editor/panel.py:128`, `freecad/Shelving/editor/panel.py:152`, `tools/freecad_editor_smoke.py:848`, `tools/freecad_editor_smoke.py:905`, `tests/test_editor_scene.py:277`): `value`, `shown`, `stock_thickness_before`, `grab`, and `_witness_xs`/`xs` need the `_mm` suffix.
- **N1: Untagged checkboxes reset on every refresh** (`freecad/Shelving/editor/panel.py:404`): keep the check state of names still listed.
- **N2: Axis-index helpers duplicated** (`freecad/Shelving/editor/session.py:64`, `freecad/Shelving/editor/session.py:71`): a shared `Vec3` component accessor in `core/geometry.py` would remove the copies.

### Round 2: APPROVED
- **N1: An exception before `main()` hangs the merge gate instead of failing it** (`tools/freecad_panel_smoke.py:27`, `tools/run-tests.sh:120`): an import-time exception leaves the offscreen GUI running with no timeout (verified: killed by `timeout 90`, exit 124). It can never pass falsely, but it contradicts the "exit code is trustworthy" comment. Guard the imports inside `main()` or a module-wide `try/finally: os._exit(...)`, or add a `timeout`.
- **N2: Stale claims that the panel has no tested logic and no coverage** (`freecad/Shelving/editor/panel.py:6-10`, `README.md:196`): the panel smoke now drives this module, and the panel holds the start-drag threshold, unchanged-value suppression, and check-state preservation. Restate both passages.
- **N3: `sed` artifact in the `_EditorView` docstring** (`freecad/Shelving/editor/panel.py:170`): "travelled_px" should read "travelled".
- **N4: Round-1 N2 is only partly adopted** (`freecad/Shelving/core/edit.py:537`, `freecad/Shelving/core/edit.py:592`, `freecad/Shelving/core/edit.py:636`, `freecad/Shelving/editor/scene.py:286-289`): the new code in `edit.py` and `scene.py` still uses the local `_axis_index`/`_component_mm` copies instead of `Axis.component_index`/`Vec3.component_mm`.
- **N5: Pixel offset without a unit suffix** (`tools/freecad_panel_smoke.py:179`): `step` should be `step_px`.
- **N6: friction-002 may now be fixable** (`.claude/docs/friction-log.md:31`): the offscreen `freecad` harness is the test mode it asks for; consider a follow-up task.

### Round 3: REJECTED
- **F1: The new freecadcmd-notes entry records a false fact about `sys.exit` under the GUI** (`docs/freecadcmd-notes.md:210-212`, `tools/freecad_panel_smoke.py:21-23`): `sys.exit` does end the GUI process. A bare `sys.exit(3)` exits 3, but once a document exists `sys.exit(N)` exits 1 whatever `N` is. A script that returns or raises hangs. `os._exit` is still right; restate both passages with the real reason.
- **N1: Round-2 N4 is still only partly adopted** (`freecad/Shelving/editor/scene.py:66`, `freecad/Shelving/editor/scene.py:76`): `scene.py` still defines and uses `_axis_index`/`_component_mm`.
- **N2: The other three freecadcmd smokes still self-invoke at the bottom of the file** (`tools/freecad_scan_smoke.py:486`, `tools/freecad_write_smoke.py:613`, `tools/freecad_catalog_smoke.py:534`): an import-time exception passes silently under freecadcmd. This predates the task; a follow-up should move each self-invoke to the top.
- **N3: Sentence fragment in the editor smoke docstring** (`tools/freecad_editor_smoke.py:8`).

### Round 4: APPROVED
- **N1: Round-3 N2 has no recorded follow-up** (`tools/freecad_scan_smoke.py:486`, `tools/freecad_write_smoke.py:613`, `tools/freecad_catalog_smoke.py:534`): the three older freecadcmd smokes still self-invoke at the bottom, so an import-time exception passes silently; file a task for it.
- **N2: Round-2 N4 is still only partly adopted** (`freecad/Shelving/core/edit.py:537`, `freecad/Shelving/core/edit.py:592`, `freecad/Shelving/core/edit.py:636`): the new `edit.py` call sites still use the file's local `_axis_index`. Consistency only.
- **N3: Overlong line in the rewrapped notes paragraph** (`docs/freecadcmd-notes.md:214`): runs to about 100 columns where the rest wraps at about 76.
