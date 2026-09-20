---
id: sh-021
title: "The elevation editor: dimensions"
current_agent: implementer
current_phase: planning
review_rejections: 0
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

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] `shelving_core/edit.py` gains `set_size(unit, region_id, size_mm, basis)`
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

## Frontier Advice

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
`shelving_core/edit.py` and is tested in the fast suite. The scene renders and hit-tests, tested offscreen. The session owns the
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

## Execution Plan

- [ ] **Step 1** (spike, no committed code): Before writing the panel, open a real FreeCAD GUI session and confirm `FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")` returns a usable widget, that it accepts `1 + 1/2"` and an expression naming a `VarSet`, and that it exposes the resolved quantity to Python. Record the answer in `docs/freecadcmd-notes.md` under a heading for GUI-only widget access, including the exact widget name that worked. If none works, record that and use a plain field with `FreeCAD.Units.parseQuantity` for the rest of this task.

- [ ] **Step 2** (`shelving_core/edit.py`, `shelving_core/tests/test_edit.py`): Add `set_size(unit, region_id, size_mm, basis)` replacing that region's rule with a `Fixed` carrying both, refusing an unknown id and a non-positive size. Add `set_basis(unit, region_id, basis)` changing only the basis and recomputing the stored number from the region's currently solved extent so the geometry is unchanged; refuse a `Basis.WITH_NEXT` on a region whose next item is not a board, since sh-013's solver cannot resolve it. Tests: `set_size` leaves siblings' rules untouched; `set_basis` in both directions leaves the solved layout identical, asserted space by space; the refusals; and the behaviour that gives basis its purpose, a layout solved against two catalogs of different thickness holding board positions under `WITH_NEXT` and moving them under `CLEAR`.

- [ ] **Step 3** (`shelving/editor/scene.py`): Add dimension items. For each region draw a dimension whose witness lines touch the faces its basis measures: a clear dimension spanning the void, a spacing dimension spanning from one board's face to the next and crossing that board. Tag each dimension item with its region id so it can be hit-tested and selected. Add a readout of the other basis's value beside it. Extend the offscreen suite: assert the two bases produce dimension items of different span for the same region, that a dimension item's endpoints lie on the faces expected, and that hit-testing a dimension returns its region id.

- [ ] **Step 4** (`shelving/editor/session.py`): Add the dimension operations. `set_size(size_mm)` taking a millimetre value already resolved by the widget, and calling the core with the selected region's EXISTING basis. The session does not see raw text: parsing belongs to FreeCAD's widget, and a parse failure never reaches here. `set_basis(basis)` calling the core. `begin_drag(board_id)`, `drag_to(position_mm)` and `end_drag()` converting a board's new position into a size for the region on one side and calling `set_size` with that region's existing basis, re-solving and writing on each step. Every one returns the new state or a structured failure, as in sh-020.

- [ ] **Step 5** (`shelving/editor/session.py`, `shelving/editor/panel.py`): Add the untagged-object choice. The session exposes what the last write left alone, each with its reason, and a `remove_untagged(ids)` that deletes exactly those inside the session's transaction. The panel shows them in a list with checkboxes, all unchecked by default, with text explaining that these were not generated by the workbench and will be left alone unless selected. Wire the dimension field, the basis control, and drag handling on the view to the session, showing a failure's message without changing the view.

- [ ] **Step 6** (`tools/freecad_editor_smoke.py`): Extend the headless check, driving the session. Assert: a set size fixes that region and redistributes its siblings; a drag changes the number and leaves the region's basis as it was; toggling basis leaves every board's placement identical; changing the catalog thickness afterwards holds board positions for a `WITH_NEXT` region and moves them for a `CLEAR` one in the same document; an untagged box is listed as left alone and survives unless selected, and is removed inside the transaction when it is; and cancel after all of the above restores the document exactly.

- [ ] **Step 7** (`docs/manual-qa.md`, `README.md`): Extend the `## M9` section with the dimension cases: type an exact opening and watch the rest redistribute; type `1 + 1/2"` and confirm the field resolves it to 38.10 mm in the readout; bind the field to a `VarSet` property with the f(x) button and confirm it follows; drag a board and confirm the readout shows the basis it already had; switch a dimension to spacing and confirm nothing moves; change the stock thickness and confirm the spacing-based shelves hold while the clear-based ones move; and confirm the untagged-object list appears with nothing checked. Extend the README glossary with measurement basis and the drag rule.
