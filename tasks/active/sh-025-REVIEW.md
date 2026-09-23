# sh-025 Review — Round 1

**Verdict:** REJECTED

The implementation is substantively right: `pixi run tests` is green
(248 + 10 + 12 + 13 passed, `mypy --strict` clean over 51 files, exit 0)
on the branch tip, the `_slab`/`_gap` split into
`(enclosed_mm, total_mm)` does what Must Have 2 asks, `axis_size_mm`'s
trigger in `_make_board` is the general `enclosing_axis is not
board.thin_axis` condition the plan calls for (not a narrower one), and
every real number asserted in the updated tests matches the fixture
geometry when traced by hand (`panelZX012` 330.2, `panelZX007` 940.5874,
`panelZX008` 1480.3374; `real_two_units`'s 921.5374 = 939.8 − 18.2626 and
`panelFaceYX`'s 1625.6 span with its 1828.7975 void; the demo's
300 mm × 18 mm × 300 mm = 1,620,000 mm3 volume delta). Two findings block
approval.

## Blocking findings

- **F1: the real fixture's corrected heights are never asserted through
  `solve`, and `panelZX008`'s height is not asserted at all**
  (`freecad/Shelving/core/tests/test_scan.py:775-822`): the Must Have for
  `test_real_stair_step_whole_tree` asks it to assert that "solving
  `real_stair_step.boxes.json` produces three distinct Z-extents for the
  `panelZX012`/`panelZX007`/`panelZX008` divider boards ... and each
  wrapped board's `axis_size_mm` matches its solved Z-extent". The test as
  written never calls `solve` on this fixture: it asserts `axis_size_mm`
  against literals at lines 800 and 813, and for `panelZX008` asserts only
  `axis_size_mm is None` (line 822), so the third of the three distinct
  heights, 1480.3374 mm, appears in no assertion anywhere for this
  fixture. The task's headline claim, the one round 1 got wrong at exactly
  the `solve` step, therefore has no committed test on the real geometry:
  `test_svg.py::test_real_stair_step_renders_end_to_end_with_a_void`
  proves the fixture still solves at all, but asserts nothing about the
  divider extents, and the only solved-size assertions for the new
  mechanism are on the hand-built unit in
  `test_short_divider_between_differently_sized_bays_keeps_its_own_height`.
  Reviewing this required tracing the fixture's raw box sizes by hand to
  confirm the literals are the boards' true measured heights; that check
  leaves no trace in the repo, which is the signal the coverage is
  missing. Add a committed test that scans `real_stair_step.boxes.json`,
  calls `solve`, and asserts all three dividers' solved Z-extents
  (330.2 / 940.5874 / 1480.3374 mm), so the "three distinct heights"
  outcome is what the suite checks rather than an intermediate field.
  Hypothesis on the mechanics, for the next round to prove or disprove
  rather than something verified here: `test_real_stair_step_whole_tree`'s
  own `CATALOG` (ply18 at 18.0 mm) is ~0.26 mm off this fixture's real
  panel thickness, so `solve` on that scan may hit the overflow sh-026
  targets; `test_svg.py:370-381` already solves this fixture successfully
  using `_catalog_from_thicknesses(boxes)` plus `snap_mm=0.1`, so building
  the catalog that way (either as a new test in `test_scan.py` or by
  extending the existing `test_svg.py` end-to-end test) is the likely
  route. Adding a new call site with `snap_mm=0.1` is consistent with the
  "leave those call sites exactly as they are" Must Have, which is about
  not modifying the existing ones. If it turns out this assertion is
  genuinely unreachable until sh-026 lands, say so explicitly in the round
  report rather than dropping the requirement silently.

- **F2: `_slab` drops the `_mm` suffix from two identifiers that carried
  it** (`freecad/Shelving/core/scan.py:567`, `:574`, `:577`, `:584`,
  `:586-591`, `:600-601`): `low_mm`/`high_mm` became `low`/`high` now that
  they hold `(enclosed_mm, total_mm)` pairs. `CLAUDE.md` § Project
  conventions makes the unit suffix mandatory for every identifier bound
  to a quantity with a physical unit, locals included, and this file
  already applies it to tuple-valued mm quantities: `_span_mm(box,
  axis_index) -> tuple[float, float]` at `scan.py:195` and its
  `span_mm: tuple[float, float]` parameter at `:312`. The unsuffixed form
  also makes the threshold check read as `low[1] > ctx.clearance_mm`,
  comparing an unlabelled tuple element against a mm constant. Restore a
  unit-bearing name (`low_mm`/`high_mm` for the pairs, or names like
  `low_gap_mm`/`high_gap_mm` if the inner unpack at `:600-601` wants the
  shorter names).

## Non-blocking notes

- **N1: three other comments still state the now-conditional invariant as
  unconditional** (`freecad/Shelving/core/scan.py:533`,
  `freecad/Shelving/core/svg.py:267`,
  `freecad/Shelving/core/expand.py:86`): `Board` and `Insets` were updated
  per the Must Have, but `_finalize_items`' docstring ("a `Board`'s size
  along its division's axis is its own thickness"), and both
  `_apply_insets` docstrings ("its own thickness") repeat the claim the
  Frontier Advice wanted corrected precisely so a future reader does not
  trust it. Behavior in all three is unaffected; the wording is what is
  stale. `scan.py:533` is the one sh-026 will read while changing
  `_finalize_items`, so it is the one most worth fixing here.

- **N2: `_resolve_with_next` still reads catalog thickness for the next
  board** (`freecad/Shelving/core/solver.py:182`): a `Basis.WITH_NEXT`
  rule whose following item is an `axis_size_mm`-carrying `Board`
  subtracts the catalog thickness rather than the board's division-axis
  size. `scan` never emits `WITH_NEXT`, so only a hand-authored tree can
  reach it, and the Frontier Advice scoped `_rule_for_item` as the only
  solver change, so this is out of scope for this round; worth a comment
  or a follow-up rather than a silent inconsistency.

- **N3: the new report assertion is loose**
  (`freecad/Shelving/core/tests/test_report.py:40`): `assert "    division
  along z" in lines` matches any four-space-indented Z division in the
  whole report, so it does not actually pin `panelZX012`'s wrapper. The
  line below it (the six-space board line) carries the real content;
  consider asserting the two as adjacent lines, or dropping the weaker
  one.

- **N4: `_divider`'s first argument is ignored on one of its two call
  paths** (`tools/layout_demo.py:130-144`, `:182`): `_divider(
  middle_height_mm, 0.0, "divider0")` passes a height that the
  `void_mm <= 0` branch never uses. Making the caller's intent visible
  (`_divider(None, ...)`, or a separate bare-`Board` call for `divider0`)
  would read better. Also `id=f"{prefix}"` at `:144` and `:148` is just
  `id=prefix`.
