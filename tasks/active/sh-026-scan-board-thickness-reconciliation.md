---
id: sh-026
title: "Reconcile a board's catalog-resolved thickness with its raw measured width"
current_agent: implementer
current_phase: implementation
review_rejections: 0
blocked_by: [sh-025]
---

# sh-026: Reconcile a board's catalog-resolved thickness with its raw measured width

## Summary
A `Board`'s solved size always comes from its resolved material's catalog
thickness (`solver.py`'s `_thickness_mm`), never its own raw measured
width, while every sibling `Bay`/`Void`/nested `Division` in the same
`Division` gets its `Fixed` size from raw grid coordinates that scan
computes with no knowledge of catalog thickness at all. Whenever those two
numbers differ, even by a fraction of a millimetre, a division with no
`Fill`/`Weighted` sibling to absorb the difference fails to solve, because
`distribute()` is deliberately exact (`EPS_MM = 1e-6`) by design. `scan`
already resolves every board's material before building the tree
(`ctx.materials_by_name`); it just never uses that to keep sibling sizes
consistent with it.

## Status
- [x] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] When a `Division` contains a `Board` whose resolved catalog thickness
      differs from its own raw measured width by more than floating-point
      tolerance, and the division has exactly one non-`Board`,
      non-`Fill`/`Weighted` (i.e. `Fixed`) sibling, that sibling's recovered
      `Fixed` size absorbs the delta so the division's total exactly sums to
      its known span, and `solve` succeeds. A `Board` whose `rule` is set
      (sh-025) is excluded from this reconciliation entirely: it
      contributes no delta, whatever its raw measured width is.
- [ ] When such a division instead has two or more `Fixed` siblings and no
      `Fill`/`Weighted` absorber, `scan` raises `ScanError` naming the
      mismatched board(s) and the ambiguous siblings, rather than guessing
      which sibling absorbs the residual.
- [ ] A `Fill`/`Weighted` sibling present in the division absorbs the delta
      exactly as it already absorbs ordinary slack today; no behavior change
      when one exists.
- [ ] Two new tests in `freecad/Shelving/core/tests/test_scan.py`, independent of
      any real fixture: (1) a hand-built division with one board whose
      catalog-resolved thickness differs from its raw measured width and
      exactly one `Fixed` sibling, asserting the sibling's solved size
      absorbs the delta and `solve` succeeds with exact numbers; (2) the
      same setup with two `Fixed` siblings and no absorber, asserting
      `ScanError` is raised naming the board and both ambiguous siblings.
- [ ] `freecad/Shelving/core/tests/test_scan.py`'s `test_real_stair_step_whole_tree`
      and `freecad/Shelving/core/tests/test_svg.py`'s
      `test_real_stair_step_renders_end_to_end_with_a_void` no longer pass
      `snap_mm=0.1` to `scan` for this fixture — remove the argument (fall
      back to `DEFAULT_SNAP_MM`) and confirm both still pass. If either
      still needs a non-default `snap_mm` after this fix, that is a signal
      the fix is incomplete, not a reason to restore the tighter value.
- [ ] `solve()` succeeds on `real_two_units` (`freecad/Shelving/core/tests/fixtures/real_two_units.boxes.json`),
      asserted by a committed test, with both the existing fixed `ply18`/`mdf12`
      catalog and a fixture-derived catalog. Confirmed failing before this
      task on both `main` and `sh-025`'s branch tip (`LayoutSolveError`,
      reason `no_slack_absorber`, sub-millimetre `slack_mm`: 0.2626 mm on
      `main` with the coarse catalog, 0.0279 mm with a fixture-derived one)
      by sh-025's round-3 review — the same catalog-thickness-vs-measured-width
      class this task exists to fix, on a second fixture the original
      planning pass did not check. `test_real_two_units_whole_tree` currently
      asserts tree shape only, never calling `solve`; extend it (or add a
      sibling test) rather than leaving this fixture's own reconciliation
      unverified.
- [ ] `_material_for_thickness_mm`'s matching strategy (first catalog entry
      within tolerance, not nearest) is UNCHANGED by this task — this task
      fixes the downstream geometric reconciliation, not material matching.
      Do not touch it.
- [ ] `mypy --strict` clean over every changed file.

## Frontier Advice

sh-025 HAS MERGED; `blocked_by` STAYS FOR THE RECORD, NOT AS A LIVE GATE.
`sh-025` (fixed scan's divider-height stretching, in `tasks/completed/`)
touched `freecad/Shelving/core/scan.py`, `freecad/Shelving/core/layout.py`,
and `freecad/Shelving/core/solver.py`'s `_rule_for_item`, the exact
function this task's own fix depends on, confirming the original
"mechanically independent" claim this section made was wrong. `sh-025`
added `Board.rule: SizeRule | None` (`freecad/Shelving/core/layout.py:124`;
went through an intermediate `axis_size_mm: float | None` shape in its own
rounds 1-4, replaced by `rule` in round 5 for reasons unrelated to this
task, see `tasks/completed/sh-025-scan-divider-void-height.md`'s Frontier
Advice "THE REDESIGN, PART 4" if curious), consumed by `_rule_for_item`
(`solver.py:213-216`) in place of catalog thickness when set, for a board
whose containing `Division` axis is not its own thin axis (a divider
shorter than its neighbor, the case `_finalize_items`'s
`generic{t}`-per-thickness catalog fixtures do not otherwise exercise).
THE FIX below's delta-summing loop must skip any `Board` whose `rule` is
set: such a board's division-axis contribution is exact by construction
(it is the board's own raw measured extent, not a catalog-resolved
thickness with a small delta to reconcile), and treating it as an ordinary
catalog-thickness board would misattribute a potentially large "delta"
(hundreds of mm, not the sub-millimetre gap this task targets) to whatever
`Fixed` sibling happens to be present. This task also touches
`test_real_stair_step_whole_tree`, the same fixture and test function
`sh-025` touches (a different function within `scan.py`,
`_finalize_items`/`_recover_rules` here vs `_slab`/`_gap`/`_make_board`
there, but the same `_rule_for_item` both tasks change the meaning of).
Implementation may start now.

ROOT CAUSE, verified by direct inspection. `solver.py`'s `_thickness_mm`
(~line 159) returns `catalog[board.material or unit.default_material].thickness_mm`
for a `Board`'s size along its division's axis; it never looks at the
board's own measured extent. `scan.py`'s `_finalize_items` (~line 540)
computes every OTHER sibling's `Fixed` size from
`coords_mm[bounds[i+1]] - coords_mm[bounds[i]]`, i.e. purely from grid
snap-line coordinates built from raw measured geometry
(`_snap_lines`/`_Grid`), with no catalog awareness: it takes only
`(raw, bounds, coords_mm, snap_mm)`, not `ctx`. The division's total span
(`axis_span_mm` in `solver.py`'s `_place`) is itself rooted in the same raw
grid coordinates, so it is exactly self-consistent with every item's OWN
raw slot width — but a `Board`'s solve-time contribution is swapped for its
catalog thickness instead of its raw slot width, and nothing compensates.
Reproduced directly: scanning `real_stair_step.boxes.json` with
`snap_mm=0.5` (the true default) fails with `overflow
({'slack_mm': -0.254, ...})`; the same failure reproduces even against the
existing fixed `ply18`/`mdf12` catalog from other tests, which is 0.26 mm
off this fixture's real ply thickness. This is a systemic risk for ANY
division with a `Fixed`-and-`Board`-only mix (no `Fill`/`Weighted`), not a
one-fixture quirk: any real scanned board whose measured thickness is not
EXACTLY equal to its resolved catalog thickness (the normal case, since
`snap_mm` exists precisely to tolerate that) can trigger it.

THE FIX. Thread `ctx` (or at minimum `ctx.materials_by_name` plus the
catalog) into `_finalize_items`, and before or while calling
`_recover_rules`, compute each `Board` sibling's delta
(`catalog[resolved].thickness_mm` minus the board's own raw measured
width, i.e. its raw slot width from `coords_mm`/`bounds` at that board's
own position in `raw`), EXCLUDING any `Board` whose `rule` is set (sh-025)
from this computation entirely: that board's division-axis contribution is
already its own raw measured value by construction, not catalog
thickness, so it has no catalog-vs-raw delta to reconcile and must not be
summed into the residual. `scan.py`'s own `_is_axis_wrap` helper already
identifies the analogous wrap-`Division` case for `_finalize_items`'s
sibling-uniformity filter (sh-025's round 4); this task's exclusion is the
same idea applied to a plain `Board` sibling's `rule` rather than a
wrapping `Division`'s shape, not a case `_is_axis_wrap` itself already
covers. Sum the deltas across the remaining `Board` items in the division.
If the division has exactly one non-`Board`, non-`Fill`/`Weighted`
region item, add the summed delta to that item's recovered `Fixed` size
before it is assigned. If there is a `Fill`/`Weighted` sibling instead,
leave `_recover_rules` untouched: `distribute` already absorbs the
resulting slack correctly through the existing mechanism, since the
`Board`'s `Fixed(catalog_thickness)` rule already carries the corrected
number by the time `solve` runs; no separate handling needed for that case,
confirm this by testing it rather than assuming it. If there are two or
more `Fixed` (non-`Fill`/`Weighted`) siblings and no absorber, raise
`ScanError` (not a new `LayoutSolveError` reason: this is detected in
`scan`, before `solve` ever runs) naming the mismatched board(s) via
`ScanError.objects`, per the existing `ScanError(message, objects)`
pattern (~line 101). Do not guess which of several `Fixed` siblings should
absorb it.

WHY snap_mm=0.1 MASKED THIS RATHER THAN FIXING IT. The real fixture's
shelves measure ~18.0086 mm and its panels/sides/dividers measure
~18.2626 mm: different parts of the same physical cabinet, 0.25 mm apart,
which the fixture's own auto-generated test catalog
(`_catalog_from_thicknesses` in `test_svg.py`) treats as two DISTINCT
catalog entries by construction (one per distinct thickness rounded to 4
decimals). Both entries are within the true default `snap_mm=0.5` of
either real measurement, so `_material_for_thickness_mm`'s "first entry
within tolerance" behavior resolves every board in the fixture to the
SAME one entry regardless, which is correct: these boards are meant to
share one nominal material. The tighter `snap_mm=0.1` sh-015 used did not
fix that; it happened to narrow the gap between measured and resolved
values enough, for this one fixture, to stay under the solver's slack
tolerance by accident. It changes nothing about whether the underlying
reconciliation is correct, and it is why the Must Have above requires
removing it rather than tuning it further.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python already governs this
codebase throughout; no new bare `Any` or bare containers. `mypy --strict`
clean. Shell stays simple does not apply; this task adds no shell.

## Execution Plan

- [ ] **Step 1** (`freecad/Shelving/core/scan.py`): Thread catalog/material
      resolution into `_finalize_items` and implement the single-absorber
      and ambiguous-error cases per Frontier Advice.
- [ ] **Step 2** (`freecad/Shelving/core/tests/test_scan.py`): Add the two new
      hand-built tests (single absorber succeeds; ambiguous case raises
      `ScanError`), and remove `snap_mm=0.1` from
      `test_real_stair_step_whole_tree`'s `scan` call, confirming it still
      passes at the true default. Steps 1-2 are one deferred-verification
      unit (`pipeline.md` § Deferred verification): step 1 alone does not
      make step 2's still-`snap_mm=0.1`-pinned assertions meaningful, so
      `pixi run tests` is only required green once, after step 2.
- [ ] **Step 3** (`freecad/Shelving/core/tests/test_svg.py`): Remove `snap_mm=0.1`
      from `test_real_stair_step_renders_end_to_end_with_a_void`'s `scan`
      call, confirming it still passes at the true default. Independent of
      steps 1-2's own file changes but depends on step 1's fix landing
      first; run `pixi run tests` green after this step.
- [ ] **Step 4** (`freecad/Shelving/core/tests/test_scan.py`): Extend
      `test_real_two_units_whole_tree` (or add a sibling test) to call
      `solve()` on `real_two_units` and assert it succeeds, with both the
      existing fixed `ply18`/`mdf12` catalog and a fixture-derived catalog
      (mirroring `test_svg.py`'s `_catalog_from_thicknesses` pattern),
      closing the Must Have this task's own planning added after round-3
      sign-off found `real_two_units` fails to solve on `main` today.
      Depends on step 1's fix landing first; run `pixi run tests` green
      after this step.
