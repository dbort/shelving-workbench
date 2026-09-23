---
next_id: bug-003
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
