# sh-020 Review — Round 3

Scope: commits since the round-2 approval (80a7df9): Step 8 (ed632a9),
Step 9 (595b406), Steps 10-11 (405bf78). `pixi run tests` is green at the
branch tip (ruff, mypy 62 files, 284 core tests, all smokes, `shelving
editor OK`).

The weight-solving in `core/edit.py` is correct as far as derivation goes.
Every driven item in one `distribute()` call has the same size/weight
ratio `r = S / W`. Giving each half `w_h = h / r` gives
`S' = r * W' = S - b + 2h = S - t`, which is the new slack, so every other
driven sibling keeps its size, however many there are and whatever their
weights. The merge inverse and the Fixed/Fill fallbacks check out the
same way. The findings below are about coverage and accuracy, not that
arithmetic. Steps 8 and 9 (`unit_for_selection`, button labels,
`debug_log`) meet their Must Haves and have no blocking findings.

## Blocking findings

- **F1** `freecad/Shelving/core/edit.py:119-127`: `split_region`'s
  docstring states the bug-006 rule backwards. It says "When
  ``region_id``'s parent ``Division`` already runs along ``axis`` ... the
  replacement is a new ``Division``", then "Otherwise ``region_id``'s parent
  already runs along ``axis``: ... splice". The code (`_split_replacement`,
  `parent.axis != axis` -> nest) does the opposite of the first sentence.
  This is the caller-facing contract for the central fix of this round, and
  a reader following it would reintroduce bug-006. Fix: first sentence ->
  "When the parent runs along a *different* axis (or `region_id` is the
  root)".

- **F2** `freecad/Shelving/core/tests/test_edit.py:90`, `:533`, `:553`:
  no test covers a run where the edited bay has **two or more other driven
  siblings with different weights**. The whole "any one driven sibling
  anchors the ratio" design (`_other_driven_anchor`, `edit.py:83`) depends
  on that case. `_run_unit` has only two bays, so after the split or merge
  the anchor is always the only other driven item. The intervening-Fixed
  test also has just one other driven sibling. If the anchor logic were
  wrong (for example, using the anchor's weight share rather than its
  ratio), every current test would still pass. The Must Have ("splits and
  merges in runs of Fill, Weighted and Fixed siblings") and the dispatcher's
  review brief both call out this case. Add at least:
  - a split of a middle bay in a run such as
    `[Board, Weighted(1), Board, Weighted(2.5), Board, Fill, Board, Weighted(4), Board]`,
    asserting every surviving board and every untouched bay keeps its
    `Space`;
  - the matching merge back in the same run;
  - a merge of a `Fixed` + driven pair while other driven siblings of
    different weights remain, since that is the non-trivial `Weighted`
    branch of `_merged_rule`, `edit.py:~352`.

- **F3** `tools/freecad_editor_smoke.py:253` and
  `freecad/Shelving/core/tests/test_edit.py:605`: the "shelf top-left" step
  splits the **bottom**-left bay. `solve` places a run's items from the
  axis minimum up (`solver.py`, `cursor_mm` starts at `space.origin`), so
  after the Z split of the left bay, the first bay depth-first (`[0]` /
  `_find_bay_id`) is the lower one. Both sites' comments and the Must Have
  ("divider; shelf left; shelf top-left; OK") name top-left. The spliced
  code path is the same either way, but the tests do not run the sequence
  they say they run, and the Must Have names that sequence. Fix: pick the
  upper bay, e.g. `_find_bay_ids_in_order(...)[1]` in the smoke, and an
  equivalent selector in the core test (not `_find_bay_id`). Optionally
  assert it is the upper one by comparing Z origins.

## Non-blocking notes

- **N1** `tools/freecad_editor_smoke.py:198`: `_assert_session_matches_document`
  iterates only the board ids the fresh scan produced. A board the rescan
  dropped or skipped would go unnoticed. Consider also asserting that
  `_board_ids(fresh.unit.root)` equals the set of `Part::Box` names in the
  container.
- **N2** `tools/freecad_editor_smoke.py:260`, `:274`: `left_side_before`
  snapshots every board, not only the left-side ones. That is a stronger
  check and is fine, but the name misdescribes it. Rename it (e.g.
  `boards_before`) or filter to the left side.
- **N3** `docs/manual-qa.md:493`: "the smaller bay the last shelf just
  made": both halves are equal, so neither is smaller. At `:503`, "where
  cases 2-3 put them" should be "steps 2-3". Step 5 adds a divider on the
  right, while bug-006's report added a shelf. Either is valid for "an edit
  elsewhere", but matching the report makes the manual case a direct repro.
- **N4** `freecad/Shelving/core/edit.py` `_merge_at`: when a merge
  collapses a cross-axis Division whose surviving item is itself a
  Division on the grandparent's axis, the result can be same-axis nesting.
  Frontier Advice rule 6 leaves merge's collapse behaviour unchanged, so
  this is out of scope here. Flagging it only because it produces the
  bug-006 shape through the merge path. It may deserve its own bug-log
  entry once someone confirms it.
- **N5** The split tests assert no same-axis nesting plus preserved
  geometry, but none checks directly that the parent's `items` gained
  exactly `Bay, Board, Bay` in the split bay's slot, which is the literal
  Must Have wording. One assertion on the item kinds around the index
  would close that.
