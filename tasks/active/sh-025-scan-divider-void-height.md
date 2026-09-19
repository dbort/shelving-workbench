---
id: sh-025
title: "Fix scan stretching a short divider over its void instead of splitting it off"
current_agent: implementer
current_phase: planning
review_rejections: 0
---

# sh-025: Fix scan stretching a short divider over its void instead of splitting it off

## Summary
`scan`'s single-board "does it reach across the slab" check treats any
adjoining empty space classified `outside` (void, reachable from the grid's
border) as contributing zero gap, no matter how large. That silently
absorbs a real, large void into a divider board's own placement instead of
splitting it into the nested `Division`+`Void` the model already uses
correctly for column bodies, so a divider genuinely shorter than its
neighbors gets solved at their full height instead of its own. Confirmed
against real geometry: three real divider panels measuring 330 mm, 940 mm,
and 1480 mm tall all currently solve to the same 1480 mm.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] In `shelving_core/scan.py`, a single board's "reaches across its slab"
      check in `_slab`/`_gap` treats a gap beyond `clearance_mm` the same
      way regardless of whether the space past the board is classified
      `outside` or enclosed: both fall through to `_region`'s existing
      recursive cut-finder rather than being silently absorbed as a
      near-zero inset. A gap within `clearance_mm` keeps behaving exactly as
      it does today, `outside` or not.
- [ ] `shelving_core/tests/test_scan.py`'s `test_real_stair_step_whole_tree`
      is updated to assert the corrected tree shape: solving
      `real_stair_step.boxes.json` produces three distinct Z-extents for the
      `panelZX012`/`panelZX007`/`panelZX008` divider boards (approximately
      330 mm, 940 mm, and 1480 mm respectively, previously all identical at
      ~1480.337 mm), each wrapped in its own nested `Division`+`Void` where
      its real height falls short of its neighbors', matching the pattern
      already used for column bodies (`Bay`, `top`, `Void`).
- [ ] A new test in `shelving_core/tests/test_scan.py`, independent of the
      real fixture, hand-builds two adjacent bays of different heights
      separated by a divider shorter than the taller one, and asserts the
      divider solves to its own true height with an explicit `Void` sibling
      for the shortfall, not stretched to the taller bay's height.
- [ ] Every currently-passing scan/svg/layout test for the other fixtures
      (`real_two_units`, `real_magicstart_f1`) and every existing
      clearance-scale inset test stays green, unmodified in intent: a small
      gap (within `clearance_mm`) continues to be absorbed as a board inset
      exactly as today, whether the space beyond it is `outside` or
      enclosed.
- [ ] `tools/layout_demo.py`'s `_sample_unit`/`_column` are updated so
      `divider0`/`divider1` (or whichever of the two actually needs it once
      the fix lands) reflect their true, correctly stepped heights via the
      same `Division`+`Void` pattern, instead of being stretched to the
      unit's full height as bare `Board` siblings.
- [ ] `tests/test_layout_demo.py`'s printed-output assertions (board count,
      void count, per-row content) are updated to match the corrected
      demo's actual output — read the corrected demo's real printed output
      before writing the new assertion values; do not guess a count.
- [ ] This task does NOT touch `snap_mm` handling, `_material_for_thickness_mm`,
      or the `snap_mm=0.1` argument already passed to `scan` for
      `real_stair_step` in `shelving_core/tests/test_scan.py` or
      `shelving_core/tests/test_svg.py`. That is a separate, already-logged,
      deliberately deferred issue (`friction-009` in
      `.claude/docs/friction-log.md`); leave those call sites exactly as
      they are.
- [ ] `mypy --strict` clean over every changed file.

## Frontier Advice

ROOT CAUSE, verified by direct inspection, not guessed. `_gap` in
`shelving_core/scan.py` (~line 612) walks from a board's edge toward its
slab's boundary and returns the width of any ENCLOSED empty space it
crosses; its docstring states the existing, deliberate rule: "Outside cells
cost nothing." `_slab` (~line 525) calls `_gap` to decide whether a single
contained board "reaches across" its slab: if the returned gap on either
side exceeds `clearance_mm` (`DEFAULT_CLEARANCE_MM = 3.0`), it falls back to
`_region`'s general recursive cut-finder, which is what already correctly
builds a nested `Division`+`Void` for a bay whose own top is shorter than
its neighbors (see the working `Bay`/`top`/`Void` column pattern the tree
already produces). Because "outside" cells contribute zero to the gap
regardless of their extent, a board with a genuinely large void beyond it
(hundreds of mm, not a few mm of clearance) still passes the "reaches
across" check with `low_mm`/`high_mm` near zero, so `_make_board` records
near-zero `Insets` on that side and the board's SOLVED size, once placed by
`solver.py`, silently expands to fill the whole slab. The void is real and
correctly classified by `_Grid._flood_outside`; it just never becomes its
own tree node, because the single-board fast path in `_slab` never
recurses to find it.

THE FIX IS A NARROW ONE. Do not rewrite `_flood_outside`'s classification of
`outside` vs enclosed; that classification is already correct (verified:
the void regions the tree DOES already represent, in the per-column
`Bay`/`Void` structure, are built from the same `outside` data and are
correct). The bug is specifically in how `_slab`'s single-board fast path
USES that classification when deciding whether to skip recursion. Change
the clearance check so exceeding `clearance_mm` triggers the existing
`_region` fallback whether the excess space is `outside` or enclosed;
leave the sub-`clearance_mm` case exactly as it behaves today for both
classifications. Do not add a new inset field, a new `Item` variant, or new
tree-walking logic elsewhere; `_region`'s recursive cut-finder should
already produce the right `Division`+`Void` shape once it actually runs for
these cases, since it does so correctly for the analogous per-column case
today.

VERIFY AGAINST REAL NUMBERS, not just the updated test's own pass/fail.
Reproduce first: `boxes_from_json` +
`shelving_core/tests/fixtures/real_stair_step.boxes.json`, a catalog built
from the fixture's own thicknesses (`generic{t}` entries per distinct
thickness, see `_catalog_from_thicknesses` in `test_svg.py` for the exact
pattern), `scan(boxes, catalog, snap_mm=0.1)` (keep `snap_mm=0.1`; see the
out-of-scope note above), then `solve`. Before the fix, `panelZX012`,
`panelZX007`, and `panelZX008` all solve to `z_mm=1480.3374`. After the
fix, each must solve to its own true measured height: `panelZX012` ≈
330 mm, `panelZX007` ≈ 940 mm, `panelZX008` ≈ 1480 mm (it was already
correct by coincidence, being the tallest). Confirm this directly by
walking the solved tree and printing each divider board's solved `size`,
the same way the diagnosis for this task did; do not rely solely on the
updated test's assertions matching themselves.

`tools/layout_demo.py` SEQUENCING. `_sample_unit`'s `middle` Division has
`divider0` between `col0` (void_mm=0.0, tallest) and `col1` (void_mm=300),
and `divider1` between `col1` and `col2` (void_mm=600). `divider0`'s
correct height already happens to equal the unit's full height (col0 has no
step), so it may not need a code change; `divider1`'s correct height should
match `col1`'s height (300 mm shorter than the unit's full height, i.e. the
taller of `divider1`'s own two immediate neighbors), not the unit's full
height. Confirm which of the two actually needs the `Division`+`Void`
wrapping by computing it, not by assuming both do.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python already governs this
codebase throughout; no new bare `Any` or bare containers. `mypy --strict`
clean. Shell stays simple does not apply; this task adds no shell.

## Execution Plan

- [ ] **Step 1** (`shelving_core/scan.py`): Change `_slab`'s single-board
      "reaches across" check so a gap beyond `clearance_mm` falls through to
      `_region`'s recursive fallback whether `_gap` classifies the excess
      space as `outside` or enclosed, per Frontier Advice. Re-sync the
      vendored copy.
- [ ] **Step 2** (`shelving_core/tests/test_scan.py`): Update
      `test_real_stair_step_whole_tree`'s assertions to the corrected tree
      shape, and add the new hand-built regression test for a short divider
      between two differently-sized bays, per Must Have. Steps 1-2 are one
      deferred-verification unit (`pipeline.md` § Deferred verification):
      step 1 alone breaks the pre-existing assertions in step 2's file by
      design, so `pixi run tests` is only required green once, after step
      2, not after step 1 alone.
- [ ] **Step 3** (`tools/layout_demo.py`): Wrap whichever of
      `divider0`/`divider1` actually needs it in the `Division`+`Void`
      pattern per Frontier Advice's sequencing note.
- [ ] **Step 4** (`tests/test_layout_demo.py`): Update the printed-output
      assertions (board count, void count, per-row content) to match the
      corrected demo's actual real output. Steps 3-4 are one
      deferred-verification unit for the same reason as steps 1-2: run
      `pixi run tests` green once, after step 4.
