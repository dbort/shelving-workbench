---
id: sh-025
title: "Fix scan stretching a short divider over its void instead of splitting it off"
current_agent: reviewer
current_phase: review
review_rejections: 1
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
- [x] Planning
- [x] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] In `freecad/Shelving/core/scan.py`, a single board's "reaches across its slab"
      check in `_slab`/`_gap` treats a gap beyond `clearance_mm` the same
      way regardless of whether the space past the board is classified
      `outside` or enclosed: both fall through to `_region`'s existing
      recursive cut-finder rather than being silently absorbed as a
      near-zero inset. A gap within `clearance_mm` keeps behaving exactly as
      it does today, `outside` or not. (Unaffected by the round-5 redesign
      below; already correct.)
- [x] SUPERSEDES rounds 1-4's `axis_size_mm: float | None` field.
      `freecad/Shelving/core/layout.py`'s `Board` carries a new
      `rule: SizeRule | None = None` field instead: the SAME `Fixed` /
      `Weighted` / `Fill` type every `Bay`/`Void`/`Division` already carries
      as its own `rule`, now also available on `Board` for the board's
      solve-time rule along its containing `Division`'s own axis. `None`
      means "derive `Fixed` from catalog thickness", the only behavior
      before this task. `Board`'s and `Insets`'s docstrings state this as
      the actual invariant (a board's division-axis size is derived from
      catalog thickness ONLY when `rule` is `None`) rather than the
      unconditional "always" the type had before this task. See Frontier
      Advice "THE REDESIGN, PART 4" for why this replaces `axis_size_mm`
      rather than sitting alongside it.
- [x] `freecad/Shelving/core/solver.py`'s `_rule_for_item` returns
      `item.rule` directly when a `Board`'s `rule` is set, `Fixed(size_mm=
      _thickness_mm(...))` exactly as today otherwise. A `Board`'s own
      `rule` is NOT routed through `_resolve_with_next`: that resolution is
      for a region's `Basis.WITH_NEXT` quoting a spacing relative to the
      next item, a distinct concept a `Board`'s own rule has no use for.
- [x] `freecad/Shelving/core/scan.py`'s `_make_board` sets `rule` to
      `Fixed(size_mm=<the board's own measured span>, basis=Basis.CLEAR)`
      whenever the board is being placed under a `Division` axis that is
      not the board's own `thin_axis` (computed from the same `_Elevated`
      fields `_unit_size_mm` already reads for `pinned_size_mm`); leaves it
      `None` otherwise (the unchanged, thin-axis-matches-division-axis
      case).
- [x] `freecad/Shelving/core/scan.py`'s `_is_axis_wrap` (added round 4)
      detects a wrap by `boards[0].rule is not None` (was `axis_size_mm is
      not None`); `_finalize_items` still excludes such a wrap from
      `_recover_rules`'s sibling-uniformity comparison and assigns it
      `Fixed` at its own raw grid width directly, unchanged in mechanism
      from round 4, only the field it inspects renamed.
- [x] `freecad/Shelving/core/tests/test_scan.py`'s
      `test_real_stair_step_solves_to_three_distinct_divider_heights`
      (added round 3, extended round 4) is updated so every place it reads
      `.axis_size_mm` instead reads `.rule` (e.g. `board.rule ==
      Fixed(size_mm=pytest.approx(...))` or `board.rule is None`), with the
      same real-number coverage already established: solving
      `real_stair_step.boxes.json` produces three distinct Z-extents for
      `panelZX012`/`panelZX007`/`panelZX008` (~330 mm, ~940 mm, ~1480 mm),
      each wrapped board's `rule` is `Fixed` at its solved Z-extent (or
      `None` for the unwrapped one), and `panelZX012`'s/`panelZX007`'s own
      Y-cross-section plus the `Shelf015`/`panelYX003` column bodies' own
      Y-widths keep asserting their true raw values (~18.24 mm and ~887 mm
      respectively), not equalized. Same rename for
      `test_short_divider_between_differently_sized_bays_keeps_its_own_height`
      (added round 3, extended round 4) and its `_stepped_columns_boxes`
      fixture.
- [x] `freecad/Shelving/core/tests/test_scan.py`'s `test_real_two_units_whole_tree`
      keeps asserting the corrected tree shape for `panelFaceYX` (a
      1828.7975 mm void) and `panelZX008` (a 921.5374 mm void) established
      in round 1, renamed from `.axis_size_mm` to `.rule` the same way.
      `real_magicstart_f1` and every existing clearance-scale inset test
      stay green, unmodified in intent: a small gap (within `clearance_mm`)
      continues to be absorbed as a board inset exactly as today, whether
      the space beyond it is `outside` or enclosed.
- [x] `tools/layout_demo.py`'s `_divider` helper (added round 3, extended
      round 4) sets `rule=Fixed(size_mm=height_mm)` instead of
      `axis_size_mm=height_mm` on the wrapped `Board`; `divider0` keeps
      passing `None` since its true height already equals the unit's full
      height. This demo hand-builds its `Unit` directly, not through
      `scan`, so nothing computes the rule for it automatically; the
      caller still states the board's own true height explicitly, just
      through the same `SizeRule` type every other item in the tree already
      uses, per Frontier Advice "THE REDESIGN, PART 4".
- [x] `tests/test_layout_demo.py`'s printed-output assertions stay matched
      to the demo's actual output after the rename; re-run and re-read the
      real output rather than assuming the round-3/4 values are unaffected.
- [x] This task does NOT touch `snap_mm` handling, `_material_for_thickness_mm`,
      or the `snap_mm=0.1` argument already passed to `scan` for
      `real_stair_step` in `freecad/Shelving/core/tests/test_scan.py` or
      `freecad/Shelving/core/tests/test_svg.py`. That is a separate, already-logged,
      deliberately deferred issue (`friction-009` in
      `.claude/docs/friction-log.md`); leave those call sites exactly as
      they are. (Unaffected by the round-5 redesign.)
- [x] `mypy --strict` clean over every changed file.

## Frontier Advice

FIELD RENAMED IN ROUND 5: everywhere below that says `axis_size_mm` is
describing rounds 1-4's history accurately; the field itself is superseded
by `Board.rule: SizeRule | None` per "THE REDESIGN, PART 4" further down.
Read the history for the diagnosis, not as the current field name.

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

ROOT CAUSE, PART 3 (found at user sign-off, round 3's own code). Wrapping a
short divider in `Division{Board(axis_size_mm=...), Void}` (Part 2's fix)
changes what TYPE of item occupies that divider's own slot in the OUTER
division that positions it beside its neighbors: from a bare `Board`
(which `_finalize_items`, `freecad/Shelving/core/scan.py` ~line 537,
deliberately excludes from its sibling-uniformity comparison, per its own
comment: "two boards happening to be the same thickness as some region
must not make that region `Fill`") to a `Division` (which
`_finalize_items` does NOT exclude). Reproduced directly against
`real_stair_step`: the outer "columns" division's call into
`_finalize_items` receives `region_sizes_mm = [18.2411, 887.0227, 18.2372,
887.0251]` (the wrap around `panelZX012`, the `Shelf015` column body, the
wrap around `panelZX007`, the `panelYX003` column body). `_recover_rules`
finds the two ~18 mm items match each other within `snap_mm` and the two
~887 mm items match each other, so ALL FOUR get `Fill()` and split the
remaining span equally at 452.63 mm each: the two dividers balloon to
~25× their true thickness and the two column bodies are crushed to half
their true width. Confirmed by inspection in a real FreeCAD document: the
inflated dividers visibly crowd out the shelves and the second divider in
their own column bodies. This bug requires TWO near-equal-width dividers
(or two near-equal-width column bodies) in the same outer division to
manifest via `has_twin`, which is exactly why round 3's own new hand-built
test (a single divider, no twin to match against) never caught it, and why
neither `test_real_stair_step_whole_tree` nor
`test_real_two_units_whole_tree`'s existing assertions caught it either:
none of the three rounds asserted a wrapped board's or a column body's
CROSS-axis size, only Z-extent.

THE FIX, PART 3. In `_finalize_items`, exclude a wrap `Division` from
`region_positions`/`region_sizes_mm` the same way a bare `Board` already
is, and assign it `Fixed(size_mm=<its own raw grid width>,
basis=Basis.CLEAR)` directly, unconditionally, bypassing
`_recover_rules` entirely for it (matching how a bare `Board`'s size was
never subject to the sibling comparison either). Detect a wrap `Division`
by its exact, distinctive shape: exactly two items, one `Board` whose
`axis_size_mm` is not `None`, one `Void`; nothing else in this codebase
produces that shape. A helper (`_is_axis_wrap(item) -> bool` or similar)
checked before both the exclusion filter and the direct-Fixed-assignment
step keeps the two call sites in agreement. Do not change
`_recover_rules`'s general has-twin logic itself: it is correct for
genuine multi-item regions (two same-width `Bay`s legitimately sharing
`Fill`), the bug is only that a wrap `Division` was never a genuine region
to begin with.

THE REDESIGN, PART 4 (round 5, found at user sign-off, not a bug). Rounds
1-4's `Board.axis_size_mm: float | None` works and is now fully tested,
but it is a bespoke, axis-ambiguous field: its correct value depends on
which axis a `Board` happens to sit under at its current position in the
tree, information the field's own type (`float`) carries no hint of. A
caller authoring or editing a tree by hand (`tools/layout_demo.py` today;
`freecad/Shelving/core/edit.py`'s `split_region`/`merge_at`, planned for
sh-020's elevation editor, tomorrow) has to independently know "which axis
is my enclosing `Division` cutting along" to set it correctly, a fact nothing
else in this codebase requires a `Board`-tree author to reason about.
Replace it with `Board.rule: SizeRule | None`, reusing the exact `Fixed` /
`Weighted` / `Fill` type `Bay`, `Void`, and `Division` already carry as
their own `rule`. A `SizeRule` is already understood, by this codebase's
own established convention, to mean "size along whatever axis this item's
containing `Division` uses" — extending that same convention to `Board`
removes the axis-position dependency entirely: `Board(rule=Fixed(882.0))`
means the same thing regardless of where in the tree it ends up, exactly
like `Bay(rule=Fixed(300.0))` already does.

MECHANICAL SCOPE, verified by grep before this section was written:
`axis_size_mm` appears in `freecad/Shelving/core/layout.py` (the field
itself, `Board`'s and `Insets`' docstrings), `freecad/Shelving/core/solver.py`
(`_rule_for_item`), `freecad/Shelving/core/scan.py` (`_make_board`,
`_is_axis_wrap`, `_finalize_items`'s docstring), `freecad/Shelving/core/svg.py`
and `freecad/Shelving/core/expand.py` (one docstring reference each,
factual not behavioral), `tools/layout_demo.py` (`_divider`), and roughly
a dozen assertion sites across `freecad/Shelving/core/tests/test_scan.py`.
Every one of these is a rename plus, where the old code did
`axis_size_mm = <value>` then `Board(..., axis_size_mm=axis_size_mm)`, a
wrap into `Fixed(size_mm=<value>, basis=Basis.CLEAR)` assigned to `rule`
instead. `_finalize_items`'s SEPARATE wrap-`Division` sizing (the round-4
fix, assigning the OUTER wrapping `Division`'s own rule from its raw grid
width) is UNTOUCHED by this redesign: that computation is about the wrap's
position among its siblings, not about how the `Board` inside it expresses
its own axis value, and the two are independent. `_recover_rules`'s
general logic is untouched too, for the same reason as round 4.

WHAT DOES NOT CHANGE. `_rule_for_item`'s Board branch keeps its two-case
shape (explicit rule if set, else derive `Fixed` from catalog thickness);
only the explicit-value case's TYPE changes, from a bare `float` to a full
`SizeRule`. Do not route a `Board`'s own `rule` through
`_resolve_with_next`: `Basis.WITH_NEXT` quotes a spacing relative to the
NEXT item in a region's own list, a concept that belongs to a region
expressing "the opening plus the next board," not to a `Board` stating its
own size. If a caller ever sets `Basis.WITH_NEXT` on a `Board`'s `rule`,
that is unreachable from `scan()` today and out of this task's scope,
matching how round 3's Reviewer scoped the analogous `_resolve_with_next`
observation for `axis_size_mm`; do not add resolution logic for it
speculatively.

sh-026 INTERACTION, now a HARD BLOCKER (this task's frontmatter does not
list it as `blocked_by` since sh-026 depends on THIS task, not the other
way; sh-026's own frontmatter already has `blocked_by: [sh-025]`, added
during this task's own planning). sh-026 (still in planning) reconciles a
`Board`'s catalog thickness against its raw measured width by having ONE
`Fixed` sibling absorb the (small, sub-millimetre) delta; its own
`_finalize_items` change must skip any `Board` whose `rule` is set (round
5's name for what sh-026's own task file still calls `axis_size_mm` as of
this writing; whoever revises sh-026's plan next should update that
reference too), since such a board's division-axis contribution is already
exact by construction and has no catalog-thickness delta to reconcile
against. Do not let sh-026's delta-summing loop see `rule`-overridden
boards as ordinary catalog-thickness boards; that would silently
misattribute a ~300 mm "delta" to whatever sibling happens to be present.

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
needs wrapping needs its `rule` set explicitly in the hand-built tree too
(round 5's field; see "THE REDESIGN, PART 4"), since nothing computes it
automatically outside `scan.py`'s `_make_board`.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python already governs this
codebase throughout; no new bare `Any` or bare containers. `mypy --strict`
clean. Shell stays simple does not apply; this task adds no shell.

## Execution Plan

- [x] **Step 1** (`freecad/Shelving/core/layout.py`): Add `Board.axis_size_mm:
      float | None = None`. Update `Board`'s and `Insets`' docstrings to
      state the corrected, conditional invariant per Frontier Advice's
      "THE FIX, PART 2".
- [x] **Step 2** (`freecad/Shelving/core/solver.py`): `_rule_for_item` returns
      `Fixed(size_mm=item.axis_size_mm)` when a `Board`'s `axis_size_mm` is
      set, unchanged (`Fixed(size_mm=_thickness_mm(...))`) otherwise.
- [x] **Step 3** (`freecad/Shelving/core/scan.py`): Change `_slab`'s single-board
      "reaches across" check so a gap beyond `clearance_mm` falls through to
      `_region`'s recursive fallback whether `_gap` classifies the excess
      space as `outside` or enclosed (Frontier Advice "ROOT CAUSE, PART 1").
      In `_make_board`, set `axis_size_mm` whenever the enclosing division
      axis is not `board.thin_axis`, per Frontier Advice "THE FIX, PART 2".
- [x] **Step 4** (`freecad/Shelving/core/tests/test_scan.py`): Update
      `test_real_stair_step_whole_tree`'s assertions to the corrected tree
      shape (including each wrapped divider's `axis_size_mm`), update
      `test_real_two_units_whole_tree`'s assertions for `panelFaceYX` and
      `panelZX008`'s corrected shape, and add the new hand-built regression
      test for a short divider between two differently-sized bays, per Must
      Have. Steps 1-4 are one deferred-verification unit (`pipeline.md` §
      Deferred verification): steps 1-3 alone break pre-existing assertions
      in this file by design, so `pixi run tests` is only required green
      once, after step 4, not after any step alone.
- [x] **Step 5** (`tools/layout_demo.py`): Wrap whichever of
      `divider0`/`divider1` actually needs it in the `Division`+`Void`
      pattern, setting `axis_size_mm` explicitly on that `Board`, per
      Frontier Advice's sequencing note.
- [x] **Step 6** (`tests/test_layout_demo.py`): Update the printed-output
      assertions (board count, void count, per-row content) to match the
      corrected demo's actual real output. Steps 5-6 are one
      deferred-verification unit for the same reason as steps 1-4: run
      `pixi run tests` green once, after step 6.
- [x] **Step 7** (`freecad/Shelving/core/scan.py`): Fix `_finalize_items`
      per Frontier Advice "THE FIX, PART 3": add a helper detecting a wrap
      `Division` (exactly one `Board` with `axis_size_mm` set, one `Void`),
      exclude it from the sibling-uniformity comparison the same way a bare
      `Board` already is, and assign it `Fixed` at its own raw grid width
      directly.
- [x] **Step 8** (`freecad/Shelving/core/tests/test_scan.py`): Add the
      missing cross-axis assertions per the two NEW Must Haves: extend
      `test_real_stair_step_whole_tree` to assert `panelZX012`'s,
      `panelZX007`'s, the `Shelf015`-column's, and the `panelYX003`-column's
      own cross-axis (Y) sizes match their true raw widths, and extend the
      hand-built short-divider regression test to assert cross-axis sizes
      too. Steps 7-8 are one deferred-verification unit: run `pixi run
      tests` green once, after step 8, and confirm by walking the solved
      tree and printing each item's actual size the same way this round's
      diagnosis did, not by trusting the assertions alone.
- [x] **Step 9** (`freecad/Shelving/core/layout.py`): Replace
      `Board.axis_size_mm: float | None = None` with `Board.rule: SizeRule
      | None = None`. Update `Board`'s and `Insets`' docstrings to name
      `rule` instead of `axis_size_mm`, per Frontier Advice "THE REDESIGN,
      PART 4".
- [x] **Step 10** (`freecad/Shelving/core/solver.py`): `_rule_for_item`
      returns `item.rule` directly when a `Board`'s `rule` is set,
      unchanged (`Fixed(size_mm=_thickness_mm(...))`) otherwise. Do not
      route it through `_resolve_with_next`.
- [x] **Step 11** (`freecad/Shelving/core/scan.py`): In `_make_board`, set
      `rule = Fixed(size_mm=<measured span>, basis=Basis.CLEAR)` instead of
      `axis_size_mm = <measured span>`, same trigger condition (enclosing
      axis is not `board.thin_axis`) unchanged. In `_is_axis_wrap`, check
      `boards[0].rule is not None` instead of `axis_size_mm`. Leave
      `_finalize_items`'s own wrap-sizing logic (assigning the OUTER
      wrapping `Division`'s rule) untouched; it does not reference
      `axis_size_mm`/`rule` at all.
- [x] **Step 12** (`freecad/Shelving/core/svg.py`, `freecad/Shelving/core/expand.py`):
      Update the one docstring reference to `axis_size_mm` in each file to
      say `rule` instead. No behavioral change; these files never read the
      field, only mention it in prose.
- [x] **Step 13** (`freecad/Shelving/core/tests/test_scan.py`): Rename every
      `.axis_size_mm` read/assertion to `.rule`, wrapping the compared value
      in `Fixed(size_mm=...)` where the old assertion compared a bare float
      (e.g. `board.axis_size_mm == pytest.approx(X)` becomes `board.rule ==
      Fixed(size_mm=pytest.approx(X))`), and `... is None` assertions
      unchanged in shape. Covers
      `test_real_stair_step_solves_to_three_distinct_divider_heights`,
      `test_short_divider_between_differently_sized_bays_keeps_its_own_height`,
      `_stepped_columns_boxes`, and `test_real_two_units_whole_tree`. No
      new test cases; this step is a rename, not new coverage.
- [x] **Step 14** (`tools/layout_demo.py`): In `_divider`, set
      `rule=Fixed(size_mm=height_mm)` instead of `axis_size_mm=height_mm`
      on the wrapped `Board`; `divider0`'s call site keeps passing `None`.
      Rename the parameter from `axis_size_mm` to something reflecting the
      new type (e.g. `height_mm: float | None`, constructing `Fixed` inside
      `_divider` itself) or keep constructing `Fixed` at the call site,
      whichever reads more clearly; either is acceptable.
- [x] **Step 15** (`tests/test_layout_demo.py`): Update the printed-output
      assertions to match the renamed demo's actual real output. Steps
      9-15 are one deferred-verification unit (`pipeline.md` § Deferred
      verification): the rename touches every file at once and
      intermediate states will not type-check or pass tests, so `pixi run
      tests` and `mypy --strict` are only required green once, after step
      15. Confirm by walking the solved tree and printing real numbers
      again, the same way rounds 1-4 did; a pure rename should reproduce
      every number already established, not change any of them.
