# sh-025 Review — Round 1

**Verdict:** REJECTED

This rejection is a human-directed design change, not a defect. The branch
tip's code and tests are correct: `pixi run tests` is green here (249
passed in the core suite, plus the 10/12/13-test FreeCAD smokes, static
analysis, and the workflow lints, exit 0), round 3's review approved this
same mechanism, and round 4 fixed the one real bug found in it at sign-off.
Nothing below says the shipped `axis_size_mm` mechanism computes a wrong
number.

What it does say is that the task file's `## Must Have` list and
`## Execution Plan` were rewritten by the user after round 3's approval
(commit `685062e`), and the branch no longer satisfies them. Frontier
Advice "THE REDESIGN, PART 4" replaces `Board.axis_size_mm: float | None`
with `Board.rule: SizeRule | None`, reusing the `Fixed`/`Weighted`/`Fill`
type every `Bay`/`Void`/`Division` already carries, so a caller building a
tree by hand never has to know which axis its enclosing `Division` cuts
along to set the field correctly. That section and Execution Plan Steps
9-15 are the authoritative spec for this round; the findings below are
pointers into them, not an independent re-derivation of the scope. Steps
9-15 are one deferred-verification unit, so `pixi run tests` and `mypy
--strict` are required green once, after Step 15, per the task file's own
checkpoint note.

The user reset `review_rejections` to 0 themselves (commit `b8eb77b`)
before this round, so this is Round 1 against a fresh cap of 3 even though
it is the fifth review pass on this branch by history.

## Blocking findings

- **F1: `Board.axis_size_mm` still exists; `Board.rule` does not**
  (`freecad/Shelving/core/layout.py:121`, docstrings at
  `freecad/Shelving/core/layout.py:83-91` and `101-105`): Execution Plan
  Step 9 and the second `## Must Have` require `rule: SizeRule | None =
  None` in its place, with `Board`'s and `Insets`' docstrings naming
  `rule`. Both docstrings currently name `axis_size_mm`.

- **F2: `_rule_for_item` wraps a float instead of returning the rule**
  (`freecad/Shelving/core/solver.py:209-212`, docstring at `201-208`):
  Step 10 requires `return item.rule` when a `Board`'s `rule` is set,
  keeping the `Fixed(size_mm=_thickness_mm(...))` branch otherwise, and
  explicitly not routing a `Board`'s own rule through
  `_resolve_with_next` (Frontier Advice "WHAT DOES NOT CHANGE").

- **F3: `scan.py` still computes and passes a bare float**
  (`freecad/Shelving/core/scan.py:674-686`, `_make_board`): Step 11
  requires `rule = Fixed(size_mm=<measured span>, basis=Basis.CLEAR)` with
  the same trigger condition (enclosing axis is not `board.thin_axis`)
  unchanged.

- **F4: `_is_axis_wrap` inspects the old field**
  (`freecad/Shelving/core/scan.py:537`, docstring at `525-536`; related
  prose at `550` and `555`): Step 11 requires `boards[0].rule is not None`.
  `_finalize_items`' own wrap-sizing logic (the round-4 fix) stays
  untouched per Frontier Advice "MECHANICAL SCOPE"; only the field this
  predicate reads, and the surrounding docstrings that name it, change.

- **F5: prose references to the removed field**
  (`freecad/Shelving/core/svg.py:268`,
  `freecad/Shelving/core/expand.py:86`): Step 12 requires each to say
  `rule`. No behavioral change; neither file reads the field.

- **F6: test assertions still read `.axis_size_mm`**
  (`freecad/Shelving/core/tests/test_scan.py:800`, `813`, `822`, `865`,
  `891-892`, `946`, `953`, `956`, `959`, `979`, `981`, `1034`): Step 13
  requires each read to become `.rule`, with a bare-float comparison
  wrapped as `board.rule == Fixed(size_mm=pytest.approx(X))` and `is None`
  assertions unchanged in shape. This is a rename, not new coverage: the
  real-number coverage the `## Must Have` list enumerates (three distinct
  divider Z-extents ~330/~940/~1480 mm, the cross-axis Y widths ~18.24 mm
  and ~887 mm, `real_two_units`' 1828.7975 mm and 921.5374 mm voids) must
  survive it unchanged in value.

- **F7: `tools/layout_demo.py` still sets `axis_size_mm`**
  (`tools/layout_demo.py:131`, `136`, `142`, `146`, comment at `182`):
  Step 14 requires `rule=Fixed(size_mm=height_mm)` on the wrapped `Board`,
  with `divider0`'s call site still passing `None`. Step 14 leaves the
  `_divider` parameter's own shape to the implementer's judgement (a
  `height_mm: float | None` that constructs `Fixed` internally, or a
  `SizeRule` built at the call site); either is acceptable, but the stale
  `axis_size_mm` name in the docstring at `136` and the comment at `182`
  goes either way.

- **F8: `tests/test_layout_demo.py`'s printed-output assertions unverified
  against the renamed demo** (`tests/test_layout_demo.py`): Step 15 and
  the corresponding `## Must Have` require re-running the demo and reading
  its real output rather than assuming the round-3/4 values are unaffected.
  A pure rename should reproduce every number already established; confirm
  that by walking the solved tree and printing the real numbers, per
  Frontier Advice "VERIFY AGAINST REAL NUMBERS".

## Non-blocking notes

- **N1: sh-026's plan still names the old field**
  (`tasks/active/sh-026-scan-board-thickness-reconciliation.md:38`, `76`,
  `82`, `122`): Frontier Advice "sh-026 INTERACTION" flags this and says
  whoever revises sh-026's plan next should update the reference. sh-026 is
  still at `planning` and is not this task's file to edit; leaving it to
  that task's own planning round is fine, and it is called out here only so
  the rename is not assumed to have covered it.
