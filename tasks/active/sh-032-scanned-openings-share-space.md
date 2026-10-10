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
      unmoved; `move_board` on the shelf 30 mm up, landing exactly; the shelf's `thickness_mm` changed to 12 mm;
      the unit 40 mm taller; the unit 40 mm wider. After the resizes every
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
- **A void shares only as a last resort** (revised 2026-10-10 during
  `/work`): it keeps its size unless nothing else in its run can change.
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
