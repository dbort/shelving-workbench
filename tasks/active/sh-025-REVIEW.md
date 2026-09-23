# sh-025 Review — Round 2

**Verdict:** REJECTED

Context: this is the task's third review round. Round 2 approved the branch
and it went to `user_signoff`, where manual testing in a real FreeCAD
document found the defect below. The task file has since been updated
(commit `ce77dd4`) with two new Must Haves, Execution Plan Steps 7-8, and a
full diagnosis in `## Frontier Advice` "ROOT CAUSE, PART 3" / "THE FIX,
PART 3". That diagnosis is correct and is the authoritative spec for this
round; the findings below cite it rather than restating it.

`pixi run tests` is green on the branch tip (`ce77dd4`), so the checks do
not surface either finding. That is itself part of F2.

## Blocking findings

- **F1: A wrap `Division` is not excluded from the sibling-uniformity
  comparison, so dividers and column bodies get equalized by `Fill`**
  (`freecad/Shelving/core/scan.py:538`): `region_positions` filters on
  `not isinstance(item, Board)` only, so the `Division{Board(axis_size_mm=...),
  Void}` wrap this task's own Part-2 fix introduces (`scan.py:551` `_slab`'s
  fallback into `_region`) is fed to `_recover_rules`
  (`scan.py:828`, `has_twin` at `scan.py:838`) as though it were a genuine
  region. Reproduced against the branch tip with
  `real_stair_step.boxes.json`, a catalog built from the fixture's own
  thicknesses, `scan(..., snap_mm=0.1)` then `solve`: the outer `Axis.Y`
  "columns" division's four items (the wrap around `panelZX012`, the
  `Shelf015` column body, the wrap around `panelZX007`, the `panelYX003`
  column body) each come back with `rule=Fill()`, and each solves to
  `y=452.6337 mm`. The two dividers' true measured width is
  `18.2626 mm` (~25x inflation) and the two column bodies' is
  `887.0442 mm` / `886.9680 mm` (crushed to roughly half). The four equal
  shares plus the bare `panelZX008` board reconstruct the unit's full
  `1828.7975 mm` width, which is why nothing downstream errors: the tree is
  self-consistent and wrong. This is Must Have "NEW, from round-3 sign-off:
  ... `_finalize_items` excludes a wrap `Division` ..." (unmet) and
  Execution Plan Step 7 (unchecked, unimplemented). Implement it exactly as
  Frontier Advice "THE FIX, PART 3" prescribes: a shape-detecting helper
  (`_is_axis_wrap` or similar) used at both the exclusion filter and a
  direct `Fixed(size_mm=<raw grid width>, basis=Basis.CLEAR)` assignment,
  with `_recover_rules`' general has-twin logic left alone.

- **F2: No test asserts any wrapped board's or column body's cross-axis
  size, in either the real-fixture tests or the hand-built one**
  (`freecad/Shelving/core/tests/test_scan.py:775`,
  `freecad/Shelving/core/tests/test_scan.py:861`,
  `freecad/Shelving/core/tests/test_scan.py:977`): every assertion added
  across the three implementation rounds checks tree shape,
  `axis_size_mm`, and solved Z-extent.
  `test_real_stair_step_solves_to_three_distinct_divider_heights`
  (`test_scan.py:861`) is the only test that calls `solve` on the real
  fixture and it reads `spaces[board.id].size.z_mm` exclusively, so the
  452.6337 mm Y-sizes above pass through it untouched.
  `test_short_divider_between_differently_sized_bays_keeps_its_own_height`
  (`test_scan.py:977`) builds a single divider with no near-equal-width
  twin, so `has_twin` never fires there and the test would stay green even
  with F1 unfixed. Both new Must Haves' coverage is therefore absent: the
  fix for F1 must land together with committed assertions on the CROSS-axis
  sizes, per Execution Plan Step 8 — minimum, `panelZX012`'s and
  `panelZX007`'s own Y-widths (~18.24 mm each, not an equal share), the
  `Shelf015`-column's and `panelYX003`-column's own Y-widths (~887.02 mm
  and ~887.03 mm), and cross-axis assertions on the hand-built test, which
  needs a second near-equal-width divider (or a second near-equal-width
  bay) added so it can actually exercise `has_twin`. A fix without those
  assertions is not acceptable this round: the whole reason three rounds
  shipped this bug is that no committed test looks at that axis.

## Non-blocking notes

- **N1: `test_real_two_units_whole_tree` never solves, so its own wrap
  cannot be checked for the same defect**
  (`freecad/Shelving/core/tests/test_scan.py:896`): that fixture's `body`
  division also holds a wrap `Division` around `panelZX008` among several
  siblings, and the test asserts shape, `axis_size_mm`, and the `Void`'s
  rule but never calls `solve`, so whether `_recover_rules` equalizes
  anything there is currently unobservable. Hypothesis only, not
  reproduced: F1's fix may or may not change that fixture's solved widths,
  depending on whether any two of its `body` siblings land within
  `snap_mm`. While fixing F1, check it with a committed assertion rather
  than by eye, and fold the result into whichever test covers it.

- **N2: State the wrap's invariant where the reader meets it**
  (`freecad/Shelving/core/scan.py:530`): `_finalize_items`' docstring
  explains why a bare `Board` is excluded. Once the wrap exclusion lands,
  the same docstring should state the contract for it too, that a wrap
  `Division`'s axis size is fixed by construction and was never a region
  the sibling heuristic could speak about, so the next reader does not
  re-widen the filter back to `isinstance(item, Board)`.
