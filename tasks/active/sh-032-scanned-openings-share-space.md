---
id: sh-032
title: "Scanned openings share leftover space"
---

# sh-032: Scanned openings share leftover space

## Summary
A unit modeled outside this workbench scans with every opening fixed at
its measured size whenever no two openings in a row match, so nothing can
absorb a change: typing a size, dragging a shelf, thinning a board and
Resize Unit are all refused (bug-012). After this task every opening in a
scanned unit shares leftover space in proportion to its scanned size, so
the scan moves nothing but every edit has somewhere to go, the same as a
unit built in the editor. A void, such as a plinth gap, keeps its size
unless nothing else in its row can change. It also fixes a sideways board's run
being a fraction of a millimeter off, which kept the scanned two-unit
fixture from ever solving. sh-031's stock swap depends on both.

## Must Have
- [ ] `pixi run tests` green.
- [ ] Scanning gives no `Bay` or `Division` a `Fixed` rule except an
      axis-wrap `Division` (a board shorter than its neighbors, wrapped
      with its `Void`). A run's sharing regions are its `Bay` and
      `Division` regions, or its `Void` regions when it has none; each
      other `Void` is `Fixed` at its scanned size. A run whose sharing
      regions are all equal within `snap_mm` gets `Fill` for each; any
      other run gets `Weighted` with weights proportional to each region's
      scanned size. Asserted in the core suite.
- [ ] A board scanned with its own `rule` (its run is not its thin axis)
      has that rule's `size_mm` equal to its slot width in the scan grid,
      the same width its siblings' sizes come from. Asserted in the core
      suite.
- [ ] `real_magicstart_f1.boxes.json`, `real_stair_step.boxes.json` and
      `real_two_units.boxes.json` each scan and solve at the default
      `snap_mm`, and every board's solved placement and size is within
      `snap_mm / 2` of its measured box. Asserted in the core suite.
- [ ] On the scanned Magic Start unit, each of these solves, asserted in
      the core suite: `set_size` on the lower bay to 300 mm, with the floor
      unmoved; `move_board` on the shelf 30 mm up, landing exactly; the
      shelf's `thickness_mm` changed to 12 mm; the unit 40 mm taller; the
      unit 40 mm wider. After the resizes every
      board keeps its `thickness_mm`.
- [ ] `real_stair_step.boxes.json` solves 40 mm taller and 40 mm wider
      along its horizontal elevation axis, and `real_two_units.boxes.json`
      solves 40 mm taller. Asserted in the core suite.
- [ ] Headless, on a copy of
      `tests/freecad/fixtures/woodworking_magic_start_default.FCStd`: a
      `Session` typed size of 300 mm on the lower bay succeeds and the
      shelf moves, and `unit_ops.resize_unit` 40 mm taller succeeds with
      every board 18 mm thick afterwards.
- [ ] `docs/scope-and-design.md` no longer says unequal neighbors are
      treated as fixed, and `docs/manual-qa.md`'s expected `Scan Unit`
      output matches what the report prints.
- [ ] bug-012's entry is deleted from `.claude/docs/bug-log.md` in the
      commit that fixes it.
- [ ] `mypy --strict` clean.

## Advice

DECISIONS (user, 2026-10-09):
- **Every region shares.** On a scanned unit, `Bay`, `Void` and
  `Division` regions all share leftover space in proportion to their
  scanned size. Only a size the user types or drags, or one a stored rule
  record carries, is `Fixed`. That makes a scanned unit behave like one
  built in the editor, whose split bays already share.
- **Voids share like compartments** (superseded on 2026-10-10, see the
  next entry), so a plinth gap grows and shrinks with the unit, and the
  void above a stair-step's short column lets the unit grow taller.
- **A void shares only as a last resort** (user, 2026-10-10, during
  `/work`, superseding the previous entry): it keeps its size unless nothing else in its run can change.
  Sharing it like a compartment moved Magic Start's floor on every edit
  inside the unit, and a 30 mm shelf drag landed 6.6 mm short because the
  plinth gap gave up part of the space. The void above a stair-step's
  short column is alone in its run, so it still shares, and the unit can
  grow taller.
- **The sideways-board slot fix belongs here**: the same cause class
  (scan produces a unit the solver refuses), the same file. Widening the
  two-unit fixture along its horizontal axis stays refused: its two tops
  sit side by side with no region between them, and nothing says which
  unit should grow.
- **Old documents are ignored.** A container written before this task
  stores its scanned `Fixed` rules in its rule record, and a stored rule
  wins over the scan. The workbench is unreleased; do not migrate.

IMPLEMENTER DECISIONS (2026-10-09, planning):
- Keep `Fill` for a run whose sharing regions are all equal within
  `snap_mm`, since it reads as "equal share" in the report and panel and
  matches what the editor writes. Use `Weighted(size_mm)` for every
  sharing region of any other run, so solving reproduces the scanned
  sizes exactly. Do not mix `Fill` (weight 1) with size-valued weights in
  one run: the solve would no longer reproduce the scan.
- An axis-wrap `Division` keeps its `Fixed` grid width (`_is_axis_wrap` in
  `freecad/Shelving/core/scan.py`). It is a board's slot, not an
  opening, and its own `Void` now absorbs changes along the wrap's axis.
- Basis: a scanned rule is never `Basis.WITH_NEXT`; that only comes from
  the stored record.

THE SLOT FIX: `_finalize_items` already sets a rule-less board's
`thickness_mm` to its slot width (`coords_mm` at its bounds). Give a board
with a `rule` the same treatment for its rule's `size_mm`, which today
keeps the raw measured span from `_make_board`. A run mixing raw and
snapped widths is off by up to `snap_mm / 2`, which is what kept
`real_two_units.boxes.json` from solving.

TESTS THAT CHANGE: `test_unequal_siblings_recover_as_fixed`,
`test_equal_siblings_recover_as_fill`, and the report tests in
`freecad/Shelving/core/tests/` assert today's rule. Rewrite them for the
new one rather than deleting them. Scan-only fixture tests that never
solved (`test_real_two_units_whole_tree`) gain a solve.

DOCS: `docs/scope-and-design.md` describes recovering rules ("equal
neighbors are treated as sharing and unequal ones as fixed"); state the
new rule. `docs/manual-qa.md` M6 case 1 shows the report's exact output;
update it. The README glossary's size-rule entry stays accurate.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python: no bare `Any`, no bare
containers in signatures, `mypy --strict` clean. Shell stays simple: this
task adds no shell.

## Plan
- [x] **Step 1** (`freecad/Shelving/core/scan.py`): Replace `_recover_rules`'s twin heuristic with the sharing rule above, keeping axis-wrap divisions `Fixed`, and set a ruled board's `rule.size_mm` to its slot width in `_finalize_items`.
- [x] **Step 2** (`freecad/Shelving/core/tests/`): Rewrite the recovery and report tests for the new rule; add the fixture solve-and-match tests and the Magic Start edit, thickness and resize tests, plus the stair-step and two-unit resize tests.
- [x] **Step 3** (`tests/freecad/`): The headless Magic Start session size and `resize_unit` tests.
- [x] **Step 4** (`docs/scope-and-design.md`, `docs/manual-qa.md`, `.claude/docs/bug-log.md`): The doc updates and bug-012's deletion.

## Review log

### Round 1: REJECTED
- **F1: Comments in unchanged tests now describe the removed heuristic as current behavior** (`freecad/Shelving/core/tests/test_edit.py:879-883`, `freecad/Shelving/core/tests/test_scan.py:978-985`): the `_two_unequal_fixed_openings_unit` docstring says scanning gives every opening without a same-size twin its own `Fixed` rule, and the `_stepped_columns_boxes` comment says the shape exercises `has_twin`, which this diff deletes. Restate the rationale for the current rule or drop the claim.
- **N1: Other references to the old heuristic** (`test_scan.py:539`, `:596`, `:649`, `:892-893`; `tests/freecad/test_write.py:488`): "equal-siblings case/recovery", "sibling-uniformity comparison", "Fill twins", "equal-siblings heuristic" name a mechanism that no longer exists.
- **N2: Stale comment on the placeholder board rule** (`freecad/Shelving/core/scan.py:679-683`): it says the board's measured span is what the Division must carry; `_finalize_items` now replaces it with the slot width.
- **N3: The slot-width Must Have is only tested indirectly** (`test_scanned_units.py:154-174`): no single board's `rule.size_mm` is checked against its own slot, and stair-step's ruled boards are not covered.
- **N4: `_recover_rules` docstring overstates "Only"** (`scan.py:887-888`): the scan also produces `Fixed` for a void beside compartments and for an axis-wrap division.
- **N5: Decision revised in place rather than appended** (task file Advice): the original voids bullet was replaced; the Must Have at line 40 runs past the wrap width.
- **N6: Evaluation doc still describes the old rule** (`docs/parametric-model-evaluation.md:142`, `:146`): non-blocking, the doc is not the design of record.

### Round 2: REJECTED
- **F1: The stepped-columns comments claim a regression guard the test no longer provides** (`freecad/Shelving/core/tests/test_scan.py:979-984`, `:991-995`, `:1036-1041`): "Only the wraps' exclusion from _finalize_items's rule recovery keeps each divider at its own height" is false; with `_is_axis_wrap` patched to always return `False` the test still passes, since an unexcluded wrap becomes `Weighted(18)` and the scan solve still gives 18 mm. The docstring's "not equalized ... by `Fill`" and the 162.4 mm counterfactual describe the removed twin heuristic. Restate the comments, or make the test guard the exclusion (assert each wrap is `Fixed(18)`, or widen the unit and assert each wrap stays 18 mm).
- **N1: Stale counterfactual in the report test** (`test_report.py:35`): an unexcluded wrap would now print a weight, not a bare line.
- **N2: Docstring contradicts its own assertion** (`test_scan.py:853`): says the column bodies are not equalized, but asserts both `Fill` at 887.0283 mm.
- **N3: Awkward line break in a docstring** (`scan.py:889`).
- **N4: The thickness check in the resize tests is close to vacuous** (`test_scanned_units.py:222`, `:327`): asserting where the growth went (for example the plinth keeping 100 mm) would be sharper.
- **N5: Task-file formatting** (task file `:16`, `:71`): lines past the wrap width; the Summary is five sentences against pipeline.md's 1-3.
