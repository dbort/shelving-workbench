# sh-020 Review — Round 4

**Verdict:** REJECTED

Third rejection (round 2 was an approval), so `review_rejections` is now 3.

Scope: the whole diff since the round-3 rejection (a23cf15): e961a22 (Frontier
Advice rule 6 and the new merge Must Have) and 4b1a877 (round-3 fixes).
`pixi run tests` is green at the branch tip: ruff clean, mypy clean on 62
files, 289 core tests passed, all smokes passed, `shelving editor OK`.

The round-3 findings are resolved:
- F1: the `split_region` docstring now states the nest/splice rule the right
  way round.
- F2: the three new tests cover what was missing. They run a split and a
  merge in a four-bay run with three other driven siblings of different
  weights, and a `Fixed` + `Weighted` merge while other `Weighted` siblings
  remain.
- F3: the core test and the smoke both pick the upper bay, and the core test
  asserts it by Z origin.
- N1, N2, N3 and N5 are done as suggested.

When `_splice_collapsed_child` has an anchor, its weight arithmetic is
correct. Let P be the promoted `Division`, G the grandparent run and D the
collapsing `Division`. Each driven child of P gets `w = size * w_a / s_a`,
so it shares G's size/weight ratio `r`. If D was driven, the new slack is
`S - s_D + sum(driven child sizes)`. That equals `r * (W - w_D) + sum(sizes)`,
so every other region in G keeps its size. If D was `Fixed`, both sides gain
`sum(driven child sizes)` instead. `spaces[child.id]` is also the right size
source. The merge runs on D's other axis, so P's extent along G's axis, and
therefore every child's extent, is the same before and after the merge.

On the Implementer's claim: it is correct for that exact sequence, but the
collapse branch is still reachable from a real unit. `_default_unit`'s X
run is `[left_side, Bay, right_side]`. "Divider" splices into it, and
deleting that divider leaves `[left_side, merged, right_side]`: three items,
so no collapse. Nested `Division`s from a cross-axis split have no side
boards, though. On a real unit, "shelf; divider in the lower bay; shelf in
its left half; delete the divider" collapses the X `Division` to the Z one
and promotes it into the Z run that the first shelf created. That reaches
`_splice_collapsed_child`.

## Blocking findings

- **F1: the collapse splice moves boards when the grandparent run has no
  other driven region** (`freecad/Shelving/core/edit.py:374-376`). When
  `anchor is None`, every driven child of the promoted `Division` is
  rewritten to `Fill()`, which gives them all equal shares of G's slack.
  That is only correct when P has at most one driven child, or when all its
  driven children are the same size. It differs from the split and merge
  `anchor is None` cases, which each produce equal halves or a single
  region.

  Why this is reachable: scanning a hand-built unit gives every opening
  without a same-size twin `Fixed` (`scan.py` `_recover_rules`). For
  example, a column `[bottom, A(350, Fixed), shelf, B(400, Fixed), top]`
  followed by these edits:
  1. Divider in A. This nests `X[l, div, r]` with A's `Fixed` rule.
  2. Shelf in l. This nests `P = Z[l1, s, l2]`, both halves `Fill`.
  3. Shelf in l1. This splices into P, giving
     `[Weighted(h/L2), s', Weighted(h/L2), s, Fill]`, where `h ~ L2/2`.
  4. Delete the divider. The X `Division` collapses to P, and P splices into
     the column. B is `Fixed`, so there is no anchor, and all three bays
     become `Fill`. `s` and `s'` both move.

  This contradicts the new Must Have "A merge ... moves no surviving board".
  I got this from reading the code and did not run it. The next round should
  prove or disprove it with a committed test.

  Fix direction (one line): when `anchor is None`, keep the child's existing
  rule unchanged. Its driven siblings already share one ratio from P's own
  `distribute()` call, and once spliced they are the only driven items in G.
  G's leftover is then exactly the sum of their sizes.

  Required test: a grandparent run whose other regions are all `Fixed`,
  with a promoted `Division` that has two or more driven children of
  different sizes, asserting `_assert_surviving_boards_unchanged` across the
  merge. Building it with the real-unit sequence above, starting from a
  `_default_unit`-shaped tree (side boards present), would also cover the
  reachability point. The existing `_bare_column_unit` fixture is a
  one-item `Division`, a shape the editor cannot produce.

## Non-blocking notes

- **N1: the splice trigger is broader than a collapse**
  (`freecad/Shelving/core/edit.py:336-338`). The condition is
  `child_found and isinstance(new_child, Division) and new_child.axis ==
  region.axis`. That also fires for a child that did not collapse but was
  already same-axis nested. In that case `merged` keeps `before.id`, and
  `spaces[before.id]` is the pre-merge size, not the merged size, so the
  weight would be wrong. Scanning never produces same-axis nesting, and
  after this task the editor does not either, so this is unreachable today.
  Gating the condition on an actual collapse, for example by having
  `_merge_at` report it, would make the contract match the docstring.
- **N2: Must Have wording** (`tasks/active/sh-020-elevation-editor-structure.md:65-67`
  and Frontier Advice rule 6 at `:188`). "Divider, shelf left, delete
  divider" does not collapse anything on a real unit (see above). A human
  may want to restate the sequence as "shelf, divider below it, shelf left
  of the divider, delete divider".

## Cap reached
review_rejections is at 3. current_phase is now blocked_needs_human. A
human can clarify the task's requirements, fix the code directly, or
reset review_rejections to 0 and demote to implementation for another
round. F1 is a one-line change (keep the existing rule when `anchor is
None` in `_splice_collapsed_child`) plus the test described above. Every
other part of the task passed review.
