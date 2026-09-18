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
question. Milestone M9, part 2 of 2.

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
- [ ] `shelving_core/parse.py` exports `looks_like_mixed_number(text) -> bool`,
      true for a whole number followed by a fraction whether spaced or
      hyphenated, false for a bare fraction, a decimal, and a sum.
- [ ] A dimension field refuses a mixed number with a message recommending the
      plus form, and accepts everything FreeCAD accepts otherwise. Verified
      behaviour: `3/4"` is 19.05 mm, `1 + 1/2"` is 38.10 mm, `2+3/8"` is
      60.325 mm, while `1-1/2"` reads as 12.70 mm and `12 1/2"` errors, which is
      why both are refused before FreeCAD sees them.
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

FRACTION INPUT, verified against this environment's FreeCAD rather than assumed:
- `3/4"` parses to 19.05 mm, correct.
- `1 + 1/2"` parses to 38.10 mm and `2+3/8"` to 60.325 mm, both correct; the
  unit applies to the whole sum.
- `12 1/2"` raises `ValueError`, so the form a woodworker writes fails.
- `1-1/2"` returns 12.70 mm, reading the hyphen as subtraction, which is a
  SILENTLY WRONG dimension and the reason for the guard.

So: refuse a mixed number BEFORE handing text to `FreeCAD.Units.parseQuantity`,
with a message naming the plus form, for example "type 1 + 1/2\" rather than
1-1/2\"". Do NOT write a unit parser; FreeCAD's honours the user's unit schema
and everything else it accepts stays accepted. `looks_like_mixed_number` lives
in the core so the fast suite covers every form without FreeCAD.

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
`shelving_core/edit.py` or `shelving_core/parse.py` and is tested in the fast
suite. The scene renders and hit-tests, tested offscreen. The session owns the
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

- [ ] **Step 1** (`shelving_core/parse.py`, `shelving_core/tests/test_parse.py`): Create the module with `looks_like_mixed_number(text) -> bool`, matching a whole number followed by a fraction with either a space or a hyphen between them, before an optional unit suffix. Return false for a bare fraction, a decimal, an integer, a sum with a plus, and a parenthesised expression. Document that the hyphenated form is refused because FreeCAD reads it as subtraction and returns a wrong value rather than an error. Tests covering every form in the Frontier Advice table plus whitespace variants.

- [ ] **Step 2** (`shelving_core/edit.py`, `shelving_core/tests/test_edit.py`): Add `set_size(unit, region_id, size_mm, basis)` replacing that region's rule with a `Fixed` carrying both, refusing an unknown id and a non-positive size. Add `set_basis(unit, region_id, basis)` changing only the basis and recomputing the stored number from the region's currently solved extent so the geometry is unchanged; refuse a `Basis.WITH_NEXT` on a region whose next item is not a board, since sh-013's solver cannot resolve it. Tests: `set_size` leaves siblings' rules untouched; `set_basis` in both directions leaves the solved layout identical, asserted space by space; the refusals; and the behaviour that gives basis its purpose, a layout solved against two catalogs of different thickness holding board positions under `WITH_NEXT` and moving them under `CLEAR`.

- [ ] **Step 3** (`freecad/shelving/editor/scene.py`): Add dimension items. For each region draw a dimension whose witness lines touch the faces its basis measures: a clear dimension spanning the void, a spacing dimension spanning from one board's face to the next and crossing that board. Tag each dimension item with its region id so it can be hit-tested and selected. Add a readout of the other basis's value beside it. Extend the offscreen suite: assert the two bases produce dimension items of different span for the same region, that a dimension item's endpoints lie on the faces expected, and that hit-testing a dimension returns its region id.

- [ ] **Step 4** (`freecad/shelving/editor/session.py`): Add the dimension operations. `set_size(text)` taking the raw field text, refusing it when `looks_like_mixed_number` is true with the plus-form message, otherwise parsing with `FreeCAD.Units.parseQuantity`, converting to millimetres, and calling the core with the selected region's EXISTING basis. `set_basis(basis)` calling the core. `begin_drag(board_id)`, `drag_to(position_mm)` and `end_drag()` converting a board's new position into a size for the region on one side and calling `set_size` with that region's existing basis, re-solving and writing on each step. Every one returns the new state or a structured failure, as in sh-020.

- [ ] **Step 5** (`freecad/shelving/editor/session.py`, `freecad/shelving/editor/panel.py`): Add the untagged-object choice. The session exposes what the last write left alone, each with its reason, and a `remove_untagged(ids)` that deletes exactly those inside the session's transaction. The panel shows them in a list with checkboxes, all unchecked by default, with text explaining that these were not generated by the workbench and will be left alone unless selected. Wire the dimension field, the basis control, and drag handling on the view to the session, showing a failure's message without changing the view.

- [ ] **Step 6** (`tools/freecad_editor_smoke.py`): Extend the headless check, driving the session. Assert: a typed size fixes that region and redistributes its siblings; a mixed number is refused with the plus-form message and changes nothing; `1 + 1/2"` is accepted as 38.10 mm; a drag changes the number and leaves the region's basis as it was; toggling basis leaves every board's placement identical; changing the catalog thickness afterwards holds board positions for a `WITH_NEXT` region and moves them for a `CLEAR` one in the same document; an untagged box is listed as left alone and survives unless selected, and is removed inside the transaction when it is; and cancel after all of the above restores the document exactly.

- [ ] **Step 7** (`docs/manual-qa.md`, `README.md`): Extend the `## M9` section with the dimension cases: type an exact opening and watch the rest redistribute; type `12 1/2"` and confirm the message recommends `12 + 1/2"`; type that and confirm it is accepted; drag a board and confirm the readout shows the basis it already had; switch a dimension to spacing and confirm nothing moves; change the stock thickness and confirm the spacing-based shelves hold while the clear-based ones move; and confirm the untagged-object list appears with nothing checked. Extend the README glossary with measurement basis, the drag rule, and the mixed-number guard.
