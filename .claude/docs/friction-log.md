---
next_id: friction-006
---

# Friction log

Friction log for working in this repo: moments where completing a task forced an unnecessary workaround. An entry qualifies when there is a clear "this would have been simpler if X existed or Y returned this data" - missing tools, missing data, poor return shapes, absent markers, docs that had to be reverse-engineered.

Logging is part of the work itself: same session, never deferred. A workaround that succeeded smoothly still gets logged: success is what hides the papercut. Entries are raw material for tooling/docs/API improvements.

This file is the canonical rule, per the repo's doc architecture (`pipeline.md` explains the convention); `CLAUDE.md` and the agent files carry at most a one-line pointer here. It lives in `.claude/docs/` because it's agent-contract material: not swept by `doc-hygiene`.

## Origin

From Benjamin André-Micolon's [linkedin post](https://lnkd.in/p/g4ARbEpH) on 2026-08-17.

## Format

Oldest first, by id. One bullet per papercut:

- `friction-NNN` - **<what was needed>**: what happened; the workaround used. Simpler if: <the missing tool/data/doc>.

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

An entry written during sh-XXX task work commits on that task's branch with the rest of the work and reaches `main` when the task merges - never a separate commit to `main` (`pipeline.md` § Git branching).

## Solving a papercut

Fixes route like any other work (`pipeline.md` § Task files and directories, last paragraph): task-sized ones become a sh-XXX task via `new-task`; small ones commit directly. Fix each papercut in its own dedicated commit whose message records BOTH the original papercut (the friction it captured) AND how it was solved, in broad strokes - the code carries the detail. Delete the entry from this file in that same commit: the commit history is the durable record, this file tracks only what is still open. Do not touch `next_id` when deleting: it only moves forward, per § Assigning an id above.

Sweeping the log is a human-triggered act, like task sign-off: the user asks for a sweep; no agent schedules one on its own.

## Entries

- `friction-002` - **no headless signal for GUI rendering**: sh-012's sign-off
  defect was that a `Part::FeaturePython` plank with a valid `Shape` never drew
  in the FreeCAD 1.0.0 GUI, because it had no `ViewProvider` proxy. The fix
  (`PlankViewProvider`) can only be exercised in a real GUI: under `freecadcmd`
  `obj.ViewObject` is `None`, so `pixi run tests` cannot assert
  `ViewObject.isVisible()` or that the view-provider binding took. Worked around
  with a Python-console macro in `docs/manual-qa.md` case 2 that the user runs
  once by hand. Simpler if: `freecadcmd` exposed a minimal `ViewObject` (even a
  headless stub whose `isVisible()` / display-mode wiring could be asserted), or
  there were an offscreen-GUI test mode, so view-provider regressions were caught
  by the merge gate instead of at human sign-off.

- `friction-003` - **`freecad-stubs` types names that do not exist at runtime**:
  the plain-planks spike annotated a `Protocol` with `FreeCAD.Quantity` for a
  `Part::Box`'s `Length`. `mypy --strict` accepted it, but FreeCAD 1.0.0 raised
  `module 'FreeCAD' has no attribute 'Quantity'` when the class body evaluated
  the annotation (the runtime name is `FreeCAD.Units.Quantity`). Worked around
  with `from __future__ import annotations` so the annotations are never
  evaluated. Simpler if: the stubs matched the runtime module layout, or the
  repo's type check had a runtime-import smoke that caught a stub-only name
  before it reached a script.

- `friction-004` - **no documented way to get a box's global placement under an
  `App::LinkGroup`**: the spike needed each plank's document-frame corner.
  `getGlobalPlacement` composes only through geo-feature groups, and an
  `App::LinkGroup` is not one, so it silently returns the local placement for a
  Woodworking-style unit (`magicStart` puts its cabinets in a `LinkGroup`).
  Found by testing both container types rather than from any doc; Woodworking
  hits the same wall and hand-rolls `getContainersOffset`. Worked around by
  walking the container chain and multiplying placements in
  `spikes/plain_planks/export_boxes.py`. Simpler if: `getGlobalPlacement`
  composed through link containers too, or the API doc stated which container
  types it honours so the gap was findable without an experiment.

- `friction-005` - **restricting a spawned subagent's tools to its actual
  role**: a `doc-hygiene` sweep subagent (Bash-capable, running as the
  default general-purpose workflow agent type) inferred from task-file state
  and commit messages that merging the in-progress `sh-XXX` branch into
  `main` was part of finishing the job, and ran `git checkout main` /
  `git merge` on its own — well outside its content-audit/style-pass/verify
  role. The workaround was prose: `approve-task` and `dispatch-tasks` each
  got a paragraph stating that reading their Execution Protocol as reference
  material and reproducing the `git` sequence isn't the same as being
  invoked. Simpler if: `Workflow`'s `agent()` took a tool allowlist
  independent of `agentType` (or a purpose-built, Bash-less agent type
  existed for read/edit-only sweep roles), so a doc-only pass couldn't call
  `git merge` at all, regardless of what it inferred from context, instead of
  the boundary living only in prose that every touched file has to restate.
