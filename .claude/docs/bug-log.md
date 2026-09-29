---
next_id: bug-011
---

# Bug log

Functional defects in the workbench on `main`: wrong output, a refusal that
should succeed, a crash, behavior that contradicts the design docs or a
task's Must Haves. Log it in the same session, even if fixed at once. A
defect a task branch introduces and fixes never reaches `main` and gets no
entry. Friction in building the workbench goes in `friction-log.md`.

Format, oldest first:

- `bug-NNN` - **<what's wrong>**: what a user sees, how it was found, and
  the root cause once known. Fix: `ad hoc` or `sh-XXX task`, with the
  reason for that call.

Make the ad-hoc-vs-task call when logging. Ad hoc suits a small, localized
fix whose correct behavior is not in question. A task suits a fix to
shared logic or one that needs a design decision.

The id is `next_id` from the front matter; increment it in the same
commit. It only moves forward, even when entries are deleted. An entry
written during task work commits on the task's branch. The commit that
fixes a bug records the bug and its fix and deletes the entry. Sweeping
the log happens only when the user asks.

## Entries

- `bug-001` - **an untagged object that fails thin-axis classification
  hard-refuses the whole scan, not just that object**: `Shelving_Scan` and
  `Shelving_ResizeUnit` refuse outright when any box in the container has
  no single thinnest axis (e.g. a cube, three tied extents), even when
  that object carries none of this workbench's own properties and was
  always going to end up in `WriteResult.left_alone`, never touching the
  solved layout. `scan()`'s top-level loop
  (`freecad/Shelving/core/scan.py`, the per-box loop calling
  `_classify_thin_axis`) has no fallback: every box must classify or the
  whole call raises `ScanError`. This is inconsistent with how a
  not-axis-aligned object is already handled: that case is gracefully
  added to `Skipped` at the `container.py` classification layer, never a
  hard refusal. Found during `sh-018`'s manual QA sign-off (M7 case 4: a
  cube-shaped `Part::Box` added as a "this workbench ignores it" example
  instead blocked the whole Resize Unit call with `REFUSED: HandAdded: no
  single thin axis`). Worked around for that one doc case by changing the
  example box's dimensions so it isn't a cube
  (`docs/manual-qa.md`, `sh-018` commit `3bd0291`); the underlying gap in
  `scan.py` is untouched. Fix: `sh-XXX task`. `_classify_thin_axis` is
  called from `scan()`'s shared per-box loop, used by every caller, and
  the right restructuring (defer classification until a box's
  match-status against the current layout is known? catch the failure and
  redirect to `skipped` unconditionally? something else?) is a real design
  question, not a mechanical patch, worth a `new-task` interview rather
  than an ad hoc commit into shared scanning logic.

- `bug-003` - **a board's catalog-thickness mismatch cannot be reconciled
  when its containing `Division` has no direct `Bay` sibling, crashing
  `solve` on real fixtures scanned against an ordinary human-chosen
  catalog**: any `Board` whose resolved catalog thickness differs from
  its own raw measured width needs a sibling in the same `Division` to
  absorb the difference so `distribute()`'s exact-sum requirement still
  holds (`solver.py`, `EPS_MM = 1e-6`). `sh-026` (in progress, parked
  on its own branch) fixes this when a direct `Bay` sibling exists,
  largest wins when several do, and makes `scan` refuse with `ScanError`
  otherwise. It does not, and structurally
  cannot without a materially bigger fix, handle the case where the only
  sibling is a content-bearing `Division` (no `Bay` at that level at
  all): confirmed on `real_stair_step.boxes.json` with a coarse
  `ply18`/`mdf12`-style catalog, where the root-level top board
  (`panelYX`) mismatches by 0.2626 mm and its only sibling is the
  `columns` `Division`. Three implementation rounds explored fixes that
  each looked correct in isolation and broke on the real fixture: (1)
  growing the largest sibling's own reported size relocates the mismatch
  into that sibling's children instead of resolving it, since a
  `Division`'s own size is only meaningful along its *parent's* axis, not
  its own; (2) freezing one chosen descendant and recursing does not
  generalize, because `solver.py`'s `_place` passes a `Division`'s
  cross-axes through **unchanged** to every child (`_place`'s own
  docstring: "shares space's extent along its own axis among its items
  and passes the other two axes through unchanged"), so every descendant
  that itself divides along the *originating* axis independently needs
  its own absorber for the *same* delta, not just the one path a
  recursive-freeze chooses. Found during `sh-026`'s own implementation
  (rounds 2-3), each round's diagnosis verified against the actual
  `distribute()` trace, not guessed. Worked around by narrowing `sh-026`'s
  own scope to the direct-`Bay`-sibling case only, `ScanError`-refusing
  (not crashing) the no-`Bay` case instead of silently producing wrong
  geometry; the underlying gap is untouched. Round 4 found that this
  narrowing also refuses the default `Shelving_CreateUnit` shape
  (`Bottom, Division[Left, Bay, Right], Top`) after a catalog thickness
  edit, failing `tools/freecad_catalog_smoke.py`'s two reflow tests:
  Bottom/Top's only sibling is the inner `Division`, with its `Bay` one
  level down. That shape has no same-axis descendant, so round 3's
  recursive freeze did pass there; adding a shelf to the default unit
  would turn it into this entry's hard case. Fix: `sh-XXX task`. The
  correct fix needs to identify every descendant sharing the mismatch's
  own axis (reachable via cross-axis passthrough through an arbitrary
  number of intervening `Division`s) and give each one its own
  independent absorber for the same delta, or relocate the whole
  reconciliation into `solver.py`'s `distribute()` itself rather than
  pre-computing `scan.py`-side `Fixed` rules that have to anticipate
  every axis `_place` will later pass them through; either is a real
  architectural decision, not a mechanical patch, worth a `new-task`
  interview starting from this entry's trace rather than re-deriving it
  from scratch.

- `bug-004` - **the Edit Unit panel's elevation is drawn far larger than
  the task pane, so a whole unit cannot be seen or worked on at once**:
  the `QGraphicsView` in `freecad/Shelving/editor/panel.py` shows the scene
  at 1 scene unit per pixel, and scene units are millimetres
  (`editor/scene.py`), so a typical unit is several times taller and wider
  than the docked Tasks pane. The user had to scroll down about 12 screens
  and right about 2 to see all of it. Found during `sh-020`'s manual QA
  sign-off. The panel never fits the view to the scene or offers any
  zoom. Fix: `sh-XXX task`. Fit-to-view on open is the obvious minimum,
  but the user wants the editing interface itself rethought. The options
  include zoom in/out controls and a full-screen, Sketcher-style editing
  mode, and choosing between them is a product decision for a `new-task`
  interview.

- `bug-005` - **once a divider is deleted from beside a stack of shelves,
  a full-height divider cannot be added back without first deleting the
  shelves**: starting from the default unit, add a divider, then add a
  shelf on one side, then delete the divider. The shelves now span the
  whole unit, as expected, but no button can now add a divider running the
  full height of the unit. The whole-width region is a `Division` holding
  the shelves, not a `Bay`. `Session.can_split` and `core.edit.split_region`
  act only on a selected `Bay`, and the elevation offers no way to select
  a `Division` region. The only compartments that can be split are the bays
  between the shelves, each of which gets a divider only its own height.
  Found during `sh-020`'s manual QA sign-off. Fix: `sh-XXX task`. It needs
  a new edit, splitting a `Division` region across the cross axis by
  wrapping it (or re-parenting its shelves into two halves). It also needs
  a way to select a non-leaf region in the scene. Which shelves each half
  keeps, and how a user picks a region that has no area of its own to
  click, are design questions and not a mechanical patch.

- `bug-007` - **a board moved by hand snaps back on the next rescan when a
  stored `Fill` rule bounds it**: steps to reproduce:
  1. Create Unit.
  2. In the editor, add one shelf, then click OK.
  3. Move the shelf down 60 mm by hand.
  4. Run `unit_ops.rescan_unit`.

  The shelf returns to z 441.0 from 381.0. The same happens inside the
  editor session, and with Resize Unit and Reflow All. The scan reads the
  moved geometry correctly: the two bays are unequal, so it would assign
  `Fixed`. But `record.with_stored_rules` then overwrites both bays with
  the stored `Fill` rules keyed by their bounding boards, which still
  exist, and the solve puts the shelf back in the middle. This contradicts
  `docs/roadmap.md` M7's "a board moved by hand between operations is
  taken up rather than overwritten". The mechanism predates `sh-020` (it
  comes from `sh-018`'s rule record), but the editor is what makes shelves
  with stored `Fill` rules common. Found during `sh-020`'s manual QA
  sign-off, as a second contributor to the same user report as bug-006.
  Fix: `sh-XXX task`. A stored rule has to yield when the scanned geometry
  disagrees with what that rule would solve to, but it still has to win
  where geometry is ambiguous (the reason `Basis.WITH_NEXT` is stored).
  Choosing that tolerance and precedence is a design question for
  `new-task`.
- `bug-009` - **elevation dimensions overlap each other and their labels**:
  in the Edit Unit panel, dimensions for different regions draw on top of
  one another, labels included, so some values are unreadable. Found in
  sh-021's manual QA on FreeCAD 1.1.1. Root cause: `_add_region_dimensions`
  in `freecad/Shelving/editor/scene.py` places each dimension line at a
  fixed fraction of its region's cross extent (the centre for a bay or
  void, a quarter for a nested division) with no awareness of the other
  dimensions, so nested and neighbouring regions collide. Fix: `sh-XXX
  task`, because choosing where dimensions go (offset lanes, drawing only
  the selected region's, moving labels outside the unit) is a design
  decision the user wants to make separately.
- `bug-010` - **a dimension set from an expression keeps only the resolved
  number**: typing `VarSet.Len` or binding it with f(x) sizes the region
  once, but the rule stores the millimetre value, so a later change to the
  `VarSet` moves nothing. FreeCAD users expect a bound length to follow its
  expression. Found in sh-021's manual QA. Root cause: a region's size lives
  in the container's rule record (`freecad/Shelving/core/record.py`), which
  holds numbers, not a document property that `ExpressionEngine` can drive;
  the dimension field binds to a temporary probe object only so it can
  resolve names. Fix: `sh-XXX task`, since storing and re-evaluating
  expressions per region changes the rule record, reflow, and the editor,
  and needs design decisions.
