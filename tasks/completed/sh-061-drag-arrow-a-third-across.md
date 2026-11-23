---
id: sh-061
title: "Drag arrow a third across its opening"
---

# sh-061: Drag arrow a third across its opening

## Summary
Fixes bug-029: in a narrow column a selected shelf's drag arrow lands
against the divider at the column's right edge, because it sits a fixed
distance past the dimension line and that distance grows with the whole
unit. The arrow moves to a third of the way across the opening before
the board, mirroring the dimension line at two thirds, so it stays inside
any column wide enough to hold it. The same holds for a divider's arrow
in a short row. The arrow keeps its size.

## Must Have
- [x] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [x] `grep -rn "_ARROW_BESIDE_FRACTION" freecad tests` prints nothing.
- [x] `tests/test_editor_elevation.py`: on `_UNIT`, the divider's arrow
      has `at_mm[1]` within 1e-6 mm of `v0_mm + (v1_mm - v0_mm) / 3` of
      the rect of `column`, the region before the divider; on `_bookcase(locked=False)`, the shelf's arrow has
      `at_mm[0]` within 1e-6 mm of the lower bay's `h0_mm + width / 3`.
      Both keep `length_mm == 0.08 * 900`.
- [x] `tests/test_editor_elevation.py`: on a 900 mm wide unit split into
      four columns about 128 mm wide (the `large_unit` QA unit's
      proportions), a free shelf's arrow, whose heads reach
      `0.15 * length_mm` either side of `at_mm` across the run, has both
      heads inside the opening before it and clear of that opening's
      dimension line at two thirds across.
- [x] `.claude/docs/bug-log.md` has no `bug-029` entry.
- [x] `freecad/Shelving/qa/cases/30-editor.toml`, case "Equal and even
      spacing, from icons to a hand-moved shelf" (`editor.constraints`),
      step `drag`: its expected text says the second column's shelf's
      arrow sits about a third of the way across the column, clear of
      the dimension line and of the dividers.

## Advice
- The arrow goes at one third across the region before the board,
  measured on that region's rect (`before` in `arrow_for`), at the
  board's center along the run, as now. Rationale, the user's call: it
  mirrors the dimension line at two thirds, and a fraction of the region
  scales with the column where the old offset scaled with the unit.
- Arrow length stays `_ARROW_FRACTION * _longest_mm`; no cap by region
  width (user's call). Below about 65 mm wide a column's arrow heads can
  touch the dimension line; accepted.
- Check that nothing else sits at one third across: a leaf region's text
  sits a third *along* its line at two thirds across, and a region holding
  others draws its inside dimension a sixth across (`_Planner.labels`).
  The arrow at a third clears both at the board's height in a 128 mm
  column; the narrow-column test asserts the leaf case.
- The test's `0.15 * length_mm` head half-width comes from
  `arrow_geometry` in `editor/overlay.py` (cone `bottomRadius` 0.3 on an
  arrow spanning -1 to 1, scaled by `length_mm / 2`). Name that source in
  a comment in the test.
- Follow FreeCAD's own tools: no built-in workbench has a board drag arrow
  to copy; Coin draggers default to the object's center, and the user
  chose a third across for symmetry with the dimension.
- Standing obligations: Typed Python applies to the changed code. Shell,
  Users never read the log: not touched. Smoke set: no main user path is
  added, changed or removed, and no `smoke` test is touched.
- 2026-11-22, user, during `/work`: the narrow-column test builds the
  `large_unit` QA unit's actual proportions, 600 mm wide and 900 mm tall
  (four 127.5 mm columns, arrow `0.08 * 900` mm), where the Must Have's
  "900 mm wide" contradicts its own "about 128 mm" columns.

## Plan
- [x] **Step 1** (`freecad/Shelving/editor/elevation.py`): `arrow_for`
      places `at_mm` one third across `before`; delete
      `_ARROW_BESIDE_FRACTION` and its comment; rewrite the docstring's
      last sentence for the new placement.
- [x] **Step 2** (`freecad/Shelving/core/edit.py`): `region_before`'s
      docstring stops saying the arrow sits beside that region's
      dimension; it is the region the arrow is placed across.
- [x] **Step 3** (`tests/test_editor_elevation.py`): replace
      `test_a_movable_board_gets_an_arrow_beside_the_dimension_before_it`
      (its `> 2/3` assertion and its name) with the third-across checks
      for the divider and the shelf; add the four-column narrow test. Also
      `tests/freecad_view/test_editor_input.py`'s drag-by-arrow test,
      whose past-the-line assertion the plan missed, asserts the third.
- [x] **Step 4** (`freecad/Shelving/qa/cases/30-editor.toml`): extend the
      `editor.constraints` `drag` step's expected text as the Must Have
      says.
- [x] **Step 5** (`.claude/docs/bug-log.md`): delete the `bug-029` entry
      in the fixing commit.

## Review log

### Round 1: APPROVED
- **N1: Shelf check reuses `_UNIT`'s frame** (`tests/test_editor_elevation.py:463`): the `_bookcase(locked=False)` shelf arrow is computed with the frame built from `_UNIT`; correct because both units share size and facing, but `elevation_frame(unlocked)` would make the test independent of that coincidence.
- **N2: A divider's arrow can land on a shelf crossing the column at a third of its height** (`freecad/Shelving/editor/elevation.py:884`): nothing in the region before the board is excluded, so a board crossing it at that height can overlap the arrow. On `_UNIT` they clear by about 1.2 mm. The old placement had the same kind of exposure and the Advice settled the placement; a possible follow-up only.
