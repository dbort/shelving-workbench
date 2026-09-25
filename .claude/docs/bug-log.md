---
next_id: bug-008
---

# Bug log

Bug log for functional defects in this project's own shipped code: wrong
output, a refusal that should succeed (or vice versa), a crash, behavior
that contradicts the design docs or a task's own Must Haves. An entry
qualifies when the workbench itself behaves incorrectly for a real user,
not when the tools used to build it got in the way.

This is the user-visible counterpart to `.claude/docs/friction-log.md`,
which tracks the opposite: friction in *developing and testing* this
project (missing tools, awkward APIs, docs that had to be reverse-engineered),
never in what the shipped workbench actually does. A workaround that let a
task proceed does not retroactively make the underlying defect a friction
entry; if the shipped behavior is wrong, it is a bug, whichever document
was open when it was found.

Logging is part of the work itself: same session, never deferred, whether
or not the bug gets fixed immediately.

This file is the canonical rule, per the repo's doc architecture
(`pipeline.md` explains the convention); `CLAUDE.md` and the agent files
carry at most a one-line pointer here. It lives in `.claude/docs/` because
it's agent-contract material: not swept by `doc-hygiene`.

## Format

Oldest first, by id. One bullet per bug:

- `bug-NNN` - **<what's wrong>**: what a user sees, how it was found, and
  the root cause once known. Fix: `ad hoc` or `sh-XXX task`, with the
  reason for that call.

## Ad hoc vs. a task

Record this call at log time, as part of the entry, not deferred to
whenever the fix actually happens — the point is to triage while the bug
is fresh, not to relitigate it later.

Lean **ad hoc** when the fix is small and localized (one function or
module), the correct behavior isn't in question (a mechanical correction,
not a product decision), and it can be verified with a focused test or two
without a planning interview.

Lean **sh-XXX task** when the fix touches shared logic many callers rely
on, when there's a genuine design decision to make (not just "what's
correct" but "what's desired"), or when the right fix has enough shape
that a `new-task` interview would actually sharpen it rather than just add
process. A bug found mid-task can still warrant its own separate task
rather than folding into the one that found it, if fixing it properly
would expand that task's own scope past what it set out to do.

Either way, log the bug even if it gets fixed immediately: this file is
the search-first record of what's already been found, so nobody re-derives
a root cause from scratch.

## Assigning an id

This file's front matter carries `next_id`, the only source of truth for
the next number. To add an entry: take the value of `next_id` verbatim as
the new entry's id, append the entry at the end of `## Entries`, then
increment `next_id` to the next number and commit both changes together.

Never derive an id by scanning `## Entries`, and never consult git history
to work one out. Both look plausible and both are wrong the moment the
highest-numbered entry has been deleted: reading it off the remaining
entries, or off history, reissues an id that already exists in a past
commit, in a closed task file, or in another document's cross-reference.
The counter alone is authoritative, specifically because it still
increases after the entry it points past is gone.

Deleting an entry never changes `next_id`. The counter only moves forward;
an id is retired with the entry it named, not returned to the pool.

## Adding an entry mid-task

An entry written during sh-XXX task work commits on that task's branch
with the rest of the work and reaches `main` when the task merges - never
a separate commit to `main` (`pipeline.md` § Git branching). A bug found
outside any task's own work commits directly to `main`.

## Solving a bug

Fixes route by the `## Ad hoc vs. a task` call already recorded on the
entry: task-sized ones become a sh-XXX task via `new-task`; ad hoc ones
commit directly. Either way, the fix commit (or the task's own final
commit) records BOTH the original bug (what was wrong) AND how it was
solved, in broad strokes - the code and its tests carry the detail. Delete
the entry from this file in that same commit: the commit history (or the
task's own file, once merged) is the durable record; this file tracks only
what is still open.

Do not touch `next_id` when deleting: it only moves forward, per
`## Assigning an id` above.

Sweeping the log is a human-triggered act, like task sign-off: the user
asks for a sweep; no agent schedules one on its own.

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

- `bug-006` - **an editor-built layout does not survive a rescan: reopening
  the editor and making any edit moves shelves the user never touched**:
  steps to reproduce:
  1. Create Unit.
  2. In the editor, add a divider.
  3. Add a shelf in the left opening.
  4. Add a shelf in the top-left opening, then click OK.
  5. Reopen the editor and add a shelf on the right.

  Both left shelves move, from z 441.0 / 661.5 to 294.0 / 588.0. The root
  cause is that `core.edit.split_region` replaces a `Bay` with a nested
  `Division(axis, [Bay, Board, Bay])` even when the enclosing `Division`
  already runs along that axis. That produces
  `Division z[Bay, shelf1, Division z[Bay, shelf2, Bay]]`, which is halves
  of a half. Scanning cannot recover same-axis nesting from geometry, so
  `Session` rereads the column as a flat `Division z[Bay, shelf1, Bay,
  shelf2, Bay]`. The stored `Fill` rules keyed to shelf1 and shelf2 then
  apply to the outer two bays, and the column solves to equal thirds. The
  bug shows up only when something forces a re-solve and write: the next
  edit, Resize Unit, or Reflow All. Found during `sh-020`'s manual QA
  sign-off, while reproducing the user's report, with a `freecadcmd`
  script driving `Session`. Fix: `sh-XXX task`. `split_region` has to
  splice into a same-axis parent rather than nest, and flattening then has
  to give the split bay's two halves rules that keep the current geometry.
  Rules that do that (a `Fixed` pair, or `Weighted` values scaled by the
  parent's weights) are a design choice. The fix also has to decide what
  `merge_at` does in a flat run, which interacts with bug-005.

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
