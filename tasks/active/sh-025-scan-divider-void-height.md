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
splitting it into a nested `Division`+`Void`, so a divider genuinely
shorter than its neighbors gets solved at their full height instead of its
own. Confirmed against real geometry: three real divider panels measuring
330 mm, 940 mm, and 1480 mm tall all currently solve to the same 1480 mm.

A first implementation attempt found the fix is deeper than a `scan.py`
change alone: the layout model has no way to say "this board's size along
its own containing division is a measured value, not its catalog
thickness", which is exactly what's needed once a divider is correctly
wrapped in a `Division`+`Void` whose axis differs from the divider's own
thickness axis. This revision adds that model support (`layout.py`,
`solver.py`) alongside the original `scan.py` fix.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] In `freecad/Shelving/core/scan.py`, a single board's "reaches across its slab"
      check in `_slab`/`_gap` treats a gap beyond `clearance_mm` the same
      way regardless of whether the space past the board is classified
      `outside` or enclosed: both fall through to `_region`'s existing
      recursive cut-finder rather than being silently absorbed as a
      near-zero inset. A gap within `clearance_mm` keeps behaving exactly as
      it does today, `outside` or not.
- [ ] `freecad/Shelving/core/layout.py`'s `Board` carries a new
      `axis_size_mm: float | None = None` field: the board's `Fixed` size
      along its containing `Division`'s own axis when it is NOT the board's
      catalog thickness; `None` means "use catalog thickness", the only
      behavior before this task. `Board`'s and `Insets`'s docstrings are
      updated to state this as the actual invariant (a board's division-axis
      size is its thickness ONLY when `axis_size_mm` is `None`) rather than
      the current unconditional "always".
- [ ] `freecad/Shelving/core/solver.py`'s `_rule_for_item` returns
      `Fixed(size_mm=item.axis_size_mm)` when a `Board`'s `axis_size_mm` is
      set, `Fixed(size_mm=_thickness_mm(...))` exactly as today otherwise.
- [ ] `freecad/Shelving/core/scan.py`'s `_make_board` sets `axis_size_mm`
      whenever the board is being placed under a `Division` axis that is not
      the board's own `thin_axis` (computed from the board's real measured
      span along that axis, the same `_Elevated` fields `_unit_size_mm`
      already reads for `pinned_size_mm`); leaves it `None` otherwise (the
      unchanged, thin-axis-matches-division-axis case).
- [ ] `freecad/Shelving/core/tests/test_scan.py`'s `test_real_stair_step_whole_tree`
      is updated to assert the corrected tree shape: solving
      `real_stair_step.boxes.json` produces three distinct Z-extents for the
      `panelZX012`/`panelZX007`/`panelZX008` divider boards (approximately
      330 mm, 940 mm, and 1480 mm respectively, previously all identical at
      ~1480.337 mm), each wrapped in its own nested `Division`+`Void` where
      its real height falls short of its neighbors', matching the pattern
      already used for column bodies (`Bay`, `top`, `Void`), and each
      wrapped board's `axis_size_mm` matches its solved Z-extent.
- [ ] A new test in `freecad/Shelving/core/tests/test_scan.py`, independent of the
      real fixture, hand-builds two adjacent bays of different heights
      separated by a divider shorter than the taller one, and asserts the
      divider solves to its own true height with an explicit `Void` sibling
      for the shortfall, not stretched to the taller bay's height.
- [ ] `freecad/Shelving/core/tests/test_scan.py`'s `test_real_two_units_whole_tree`
      is updated to assert the CORRECTED tree shape for `panelFaceYX` (a
      1828.7975 mm void) and `panelZX008` (a 921.5374 mm void): this task's
      own round-1 implementation attempt, applied exactly as originally
      specified, surfaced and fixed the identical bug on these two boards,
      which the original planning pass's real-geometry check missed. Do not
      leave this fixture's test asserting the pre-fix (stretched) shape.
      `real_magicstart_f1` and every existing clearance-scale inset test
      stay green, unmodified in intent: a small gap (within `clearance_mm`)
      continues to be absorbed as a board inset exactly as today, whether
      the space beyond it is `outside` or enclosed.
- [ ] `tools/layout_demo.py`'s `_sample_unit`/`_column` are updated so
      `divider0`/`divider1` (or whichever of the two actually needs it once
      the fix lands) reflect their true, correctly stepped heights via the
      same `Division`+`Void` pattern with `axis_size_mm` set explicitly
      (this demo hand-builds its `Unit` directly, not through `scan`, so
      nothing computes `axis_size_mm` for it automatically), instead of
      being stretched to the unit's full height as bare `Board` siblings.
- [ ] `tests/test_layout_demo.py`'s printed-output assertions (board count,
      void count, per-row content) are updated to match the corrected
      demo's actual output — read the corrected demo's real printed output
      before writing the new assertion values; do not guess a count.
- [ ] This task does NOT touch `snap_mm` handling, `_material_for_thickness_mm`,
      or the `snap_mm=0.1` argument already passed to `scan` for
      `real_stair_step` in `freecad/Shelving/core/tests/test_scan.py` or
      `freecad/Shelving/core/tests/test_svg.py`. That is a separate, already-logged,
      deliberately deferred issue (`friction-009` in
      `.claude/docs/friction-log.md`); leave those call sites exactly as
      they are.
- [ ] `mypy --strict` clean over every changed file.

## Frontier Advice

ROUND 1 FAILED ON A WRONG "NARROW FIX" CLAIM. Round 1 implemented exactly
what an earlier version of this advice prescribed (the `_slab`/`_gap`
change below, alone) and, applied exactly as specified, broke `solve()`
outright for this task's own primary target
(`LayoutSolveError("no_slack_absorber", slack_mm=311.9374,
available_mm=1480.3374)` for `panelZX012`). The claim that `_region`'s
existing cut-finder "should already produce the right shape... since it
does so correctly for the analogous per-column case today" is false for a
board whose own thin axis differs from the axis its shortfall needs
carved along, which is exactly this bug's own case. This section replaces
that reasoning; do not resurrect it.

ROOT CAUSE, PART 1 (scan.py, still correct). `_gap` in
`freecad/Shelving/core/scan.py` (~line 657) walks from a board's edge toward its
slab's boundary and returns the width of any ENCLOSED empty space it
crosses; its docstring states the existing, deliberate rule: "Outside cells
cost nothing." `_slab` (~line 551) calls `_gap` to decide whether a single
contained board "reaches across" its slab: if the returned gap on either
side exceeds `clearance_mm` (`DEFAULT_CLEARANCE_MM = 3.0`), it falls back to
`_region`'s general recursive cut-finder. Because "outside" cells contribute
zero to the gap regardless of their extent, a board with a genuinely large
void beyond it (hundreds of mm, not a few mm of clearance) still passes the
"reaches across" check with `low_mm`/`high_mm` near zero, so `_make_board`
records near-zero `Insets` on that side and the board's SOLVED size, once
placed by `solver.py`, silently expands to fill the whole slab. This part
of the diagnosis is unchanged and still correct: `_flood_outside`'s
`outside`/enclosed classification is correct, and the fix here is still to
make the clearance check trigger `_region`'s fallback whether the excess
space is `outside` or enclosed, leaving the sub-`clearance_mm` case exactly
as it behaves today for both classifications.

ROOT CAUSE, PART 2 (layout.py/solver.py, the part round 1 missed). Once the
part-1 fix makes `_slab` correctly fall back to `_region`, `_region`'s
cut-finder DOES find a valid cut, but along the divider's OWN thin axis'
COMPLEMENT, not along its thin axis: the divider's thin-axis footprint is
already tightly bound by the OUTER division that positioned it beside its
neighbors (that is what makes it a lone contained board in the first
place), so `_clean_lines`' candidate range (`range(lo+1, hi)`, strictly
interior to the region it is searching) has no room left on the thin axis;
the divider's own far face on the OTHER axis (its real height limit) is the
only available cut. `_region` correctly produces
`Division(axis=<the other axis>){Board(divider), Void}`, but
`freecad/Shelving/core/layout.py`'s `Board` and `Insets` docstrings currently state,
as an unconditional rule, that "a board always fills its region's extent
along that axis with its own thickness", and `solver.py`'s `_rule_for_item`
(~line 194, calling `_thickness_mm` at ~line 158) enforces exactly that for
EVERY `Board`, with no exception. For a divider whose real height (330.2 mm)
is what the Division's axis must carry, using its catalog thickness
(≈18.26 mm) instead is wrong by construction: 330.2 − 18.26 ≈ 312 mm is
the exact unaccounted slack round 1's `solve()` failure reported. This is
not a scan.py bug; it is a gap in what the `Board`/`Insets`/`_rule_for_item`
model can express at all.

WHY THIS IS NOT AN ILLEGAL OR RARE CASE, so do not try to refuse it
instead of handling it. It arises whenever a board's own thin axis differs
from the axis of its real shortfall, which is inherent whenever a board
positioned by one axis (a vertical divider positioned by the
column-separating axis) is short along a DIFFERENT axis (its height) than
its own thickness axis: true of every vertical divider shorter than its
neighbor, not a corner case of this one fixture. The same code path
would equally catch a shelf narrower than its bay (a horizontal shortfall
against a Z-thin board); this task does not need to add a case for that,
the fix below already covers it because the condition it checks is general,
not divider-specific. The already-existing `ScanError` in `_region`
("no line crosses the region... the layout is not a tree", raised when
NEITHER axis has any valid cut at all) already covers genuine
non-representability and is untouched by this task; there is no additional
"should this refuse" case to add.

THE FIX, PART 2. Give `Board` (`freecad/Shelving/core/layout.py`) a new
`axis_size_mm: float | None = None` field: when set, it is the board's
`Fixed` size along its containing `Division`'s own axis, overriding catalog
thickness; `None` preserves every existing behavior exactly. Update
`Board`'s and `Insets`' docstrings to state the corrected, conditional
invariant (thickness only when `axis_size_mm` is `None`) rather than the
current unconditional "always" claim, since that claim is now false and a
future reader would otherwise reintroduce round 1's mistake by trusting it.
In `solver.py`, `_rule_for_item` (~line 194) returns
`Fixed(size_mm=item.axis_size_mm)` when set, `Fixed(size_mm=_thickness_mm(...))`
exactly as today otherwise; this is the only change `_rule_for_item` needs.
In `scan.py`'s `_make_board` (~line 604), determine the enclosing division's
axis from `cross_axis` (it is `ctx.horizontal` when `cross_axis is
ctx.vertical`, and vice versa, since these are the grid's only two axes;
depth is handled separately and unconditionally, as it already is, and is
never the enclosing axis here): when that axis is NOT `board.thin_axis`,
set `axis_size_mm` from the board's own real measured span along it
(`board.h1_mm - board.h0_mm` or `board.v1_mm - board.v0_mm` as appropriate;
the same `_Elevated` fields `_unit_size_mm` already reads for
`pinned_size_mm`, so no new geometry plumbing is needed); leave it `None`
otherwise (the unchanged, thin-axis-matches-division-axis case, which is
every board this codebase currently scans correctly). Do not add a new
`Item` variant or new tree-walking logic; `_region`'s cut-finder itself
needs no change, only what happens with the `Board` it already produces.

sh-026 INTERACTION, now a HARD BLOCKER (this task's frontmatter does not
list it as `blocked_by` since sh-026 depends on THIS task, not the other
way; sh-026's own frontmatter is being updated to add `blocked_by:
[sh-025]` in this same planning pass). sh-026 (still in planning) reconciles
a `Board`'s catalog thickness against its raw measured width by having ONE
`Fixed` sibling absorb the (small, sub-millimetre) delta; its own
`_finalize_items` change must skip any `Board` whose `axis_size_mm` is set,
since such a board's division-axis contribution is already exact by
construction and has no catalog-thickness delta to reconcile against. Do
not let sh-026's delta-summing loop see `axis_size_mm`-overridden boards as
ordinary catalog-thickness boards; that would silently misattribute a
~300 mm "delta" to whatever sibling happens to be present.

VERIFY AGAINST REAL NUMBERS, not just the updated test's own pass/fail.
Reproduce first: `boxes_from_json` +
`freecad/Shelving/core/tests/fixtures/real_stair_step.boxes.json`, a catalog built
from the fixture's own thicknesses (`generic{t}` entries per distinct
thickness, see `_catalog_from_thicknesses` in `test_svg.py` for the exact
pattern), `scan(boxes, catalog, snap_mm=0.1)` (keep `snap_mm=0.1`; see the
out-of-scope note above), then `solve`. Before the fix, `panelZX012`,
`panelZX007`, and `panelZX008` all solve to `z_mm=1480.3374`. After the
fix, each must solve to its own true measured height: `panelZX012` ≈
330 mm, `panelZX007` ≈ 940 mm, `panelZX008` ≈ 1480 mm (it was already
correct by coincidence, being the tallest), and each wrapped divider's
`axis_size_mm` must equal that same solved height. Confirm this directly by
walking the solved tree and printing each divider board's solved `size`
and `axis_size_mm`, the same way round 1's diagnosis did; do not rely
solely on the updated test's assertions matching themselves. Do the same
for `real_two_units`'s `panelFaceYX` and `panelZX008` (1828.7975 mm and
921.5374 mm voids respectively): round 1's reproduction confirmed the fix
correctly changes these too, so the updated
`test_real_two_units_whole_tree` assertions must reflect their corrected
shape, not the pre-fix stretched one.

`tools/layout_demo.py` SEQUENCING. `_sample_unit`'s `middle` Division has
`divider0` between `col0` (void_mm=0.0, tallest) and `col1` (void_mm=300),
and `divider1` between `col1` and `col2` (void_mm=600). `divider0`'s
correct height already happens to equal the unit's full height (col0 has no
step), so it may not need a code change; `divider1`'s correct height should
match `col1`'s height (300 mm shorter than the unit's full height, i.e. the
taller of `divider1`'s own two immediate neighbors), not the unit's full
height. Confirm which of the two actually needs the `Division`+`Void`
wrapping by computing it, not by assuming both do. This demo hand-builds
its `Unit` directly rather than going through `scan`, so whichever divider
needs wrapping needs its `axis_size_mm` set explicitly in the hand-built
tree too; nothing computes it automatically outside `scan.py`'s
`_make_board`.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python already governs this
codebase throughout; no new bare `Any` or bare containers. `mypy --strict`
clean. Shell stays simple does not apply; this task adds no shell.

## Execution Plan

- [ ] **Step 1** (`freecad/Shelving/core/layout.py`): Add `Board.axis_size_mm:
      float | None = None`. Update `Board`'s and `Insets`' docstrings to
      state the corrected, conditional invariant per Frontier Advice's
      "THE FIX, PART 2".
- [ ] **Step 2** (`freecad/Shelving/core/solver.py`): `_rule_for_item` returns
      `Fixed(size_mm=item.axis_size_mm)` when a `Board`'s `axis_size_mm` is
      set, unchanged (`Fixed(size_mm=_thickness_mm(...))`) otherwise.
- [ ] **Step 3** (`freecad/Shelving/core/scan.py`): Change `_slab`'s single-board
      "reaches across" check so a gap beyond `clearance_mm` falls through to
      `_region`'s recursive fallback whether `_gap` classifies the excess
      space as `outside` or enclosed (Frontier Advice "ROOT CAUSE, PART 1").
      In `_make_board`, set `axis_size_mm` whenever the enclosing division
      axis is not `board.thin_axis`, per Frontier Advice "THE FIX, PART 2".
- [ ] **Step 4** (`freecad/Shelving/core/tests/test_scan.py`): Update
      `test_real_stair_step_whole_tree`'s assertions to the corrected tree
      shape (including each wrapped divider's `axis_size_mm`), update
      `test_real_two_units_whole_tree`'s assertions for `panelFaceYX` and
      `panelZX008`'s corrected shape, and add the new hand-built regression
      test for a short divider between two differently-sized bays, per Must
      Have. Steps 1-4 are one deferred-verification unit (`pipeline.md` §
      Deferred verification): steps 1-3 alone break pre-existing assertions
      in this file by design, so `pixi run tests` is only required green
      once, after step 4, not after any step alone.
- [ ] **Step 5** (`tools/layout_demo.py`): Wrap whichever of
      `divider0`/`divider1` actually needs it in the `Division`+`Void`
      pattern, setting `axis_size_mm` explicitly on that `Board`, per
      Frontier Advice's sequencing note.
- [ ] **Step 6** (`tests/test_layout_demo.py`): Update the printed-output
      assertions (board count, void count, per-row content) to match the
      corrected demo's actual real output. Steps 5-6 are one
      deferred-verification unit for the same reason as steps 1-4: run
      `pixi run tests` green once, after step 6.
