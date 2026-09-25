# sh-020 Review — Round 5

**Verdict:** REJECTED

Round 5 is the first round since the human reset `review_rejections` to 0,
so the count is now 1.

Scope: 67b1cb4, the round-4 fixes. `pixi run tests` is green at the branch
tip: ruff clean, mypy clean on 62 files, 290 core tests passed, all smokes
passed, `shelving editor OK`, exit 0.

The round-4 findings are resolved:
- F1: when `anchor is None`, `_splice_collapsed_child`
  (`freecad/Shelving/core/edit.py:394`) keeps the promoted children's
  rules. This is correct. With no other driven claimant in the grandparent
  run, the children claim exactly the leftover that the collapsed
  `Division` claimed, whether it was `Fixed` or driven. Their existing
  weights already divide that leftover the same way. The new test
  `test_merge_collapse_with_no_other_driven_sibling_moves_no_board` covers
  the case with unequal driven children (about 166 / 74 / 74 mm), which
  `Fill()` would have equalized.
- N1: `_merge_at` reports a direct collapse, and the splice is gated on it
  (`edit.py:350-352`). The recursive branch always reports `False`.
- N2: the Must Have and rule 6 wording now use the reachable sequence.

## Blocking findings

- **F1: bug-008 comes from sh-020's own `Session`, not from shipped code, so
  it belongs in this task** (`freecad/Shelving/editor/session.py:164-178`).
  It does not belong in `.claude/docs/bug-log.md`.

  On `main`, every caller of `write_container` either writes a hand-built
  unit once (`create_unit`) or writes a unit it has just rescanned
  (`unit_ops._rescanned_unit`). A rescan makes every `Board.id` equal to
  its object's `Name`. Because of that, the fact that `_create_board` names
  an object from `role` rather than from `id` is never visible there.
  `write_container` already remaps new ids to real Names for the rule
  record (`container.py:655`), and nothing writes that same unit a second
  time.

  `Session._apply` is the first caller that does write it a second time. It
  writes `candidate` and then keeps `candidate` as `self.unit`, with its
  split-created boards still carrying uuid ids that no document object is
  named after. That breaks `write_container`'s documented precondition
  ("A board matches an existing object by its `Board.id` equalling the
  object's `Name` (set that way by `read_container` and ... `scan`)"). As a
  result, every later edit in the session deletes and recreates every board
  the session created earlier.

  The damage is limited:
  - Geometry is not affected.
  - The rule record stays consistent, because it is remapped on every
    write.
  - The bug-006 rescan invariant still holds. After commit, a fresh
    `Session` rescans, so ids equal Names again. The rescan smoke
    (`tools/freecad_editor_smoke.py:228-285`) snapshots every board by name
    across a one-write fresh session, and that assertion is not weakened.

  It is still an identity defect in this task's new code. Object Names
  churn on every edit, and per-object state is lost. The Frontier Advice
  assumed "sh-018's write path assigns the real FreeCAD name when it
  creates the object", meaning once, and Session never adopts that name.

  Fix direction, local to this task:
  - Have `write_container` report its `id_renames`, for example as a new
    `WriteResult` field.
  - Have `Session._apply` rename `self.unit`'s board ids and `self.spaces`'
    keys through that mapping. `container._renamed_board_ids` already
    exists for this.

  This does not require choosing between rename-on-write and
  provenance-matching.

  Required:
  - A session-level smoke assertion that a board created by one split keeps
    its object `Name` through a second, unrelated split, and that
    `session.unit`'s ids equal the document's Names after each edit.
  - Delete the bug-008 entry from `.claude/docs/bug-log.md` in the fixing
    commit, leaving `next_id: bug-009`.

- **F2: the collapse-splice smoke asserts nothing about the splice**
  (`tools/freecad_editor_smoke.py:328-340`). The only boards it checks are
  the four boundary boards, and no split or merge in any sequence moves
  those. The boards the splice could move are the first shelf and the
  shelf left of the divider, and the bug-008 workaround excludes them. The
  merge Must Have ("Asserted in `test_edit.py`") is still met by the core
  tests, so no Must Have is failed. However, the check's stated purpose,
  that a real `Session` delete reaches the splice without moving a board,
  is not verified. Once F1 is fixed, snapshot every board by Name before
  the delete and assert that every surviving board keeps its placement and
  its size along the column's axis. The widened left shelf's X extent is
  expected to change.

## Non-blocking notes

- **N1: the core F1 fixture is a bare column.** On the default unit, the
  smoke's sequence reaches the splice's anchored branch, because the upper
  bay is `Fill`. Only a scanned hand-built unit with all-`Fixed` openings
  reaches the `anchor is None` branch. That is fine. It is noted only so
  that nobody reads the smoke as covering the branch F1 fixed.
