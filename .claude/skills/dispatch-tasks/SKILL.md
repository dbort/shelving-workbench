# Skill: Task Dispatcher

## Purpose
Drive one named task through the `tasks/active/*.md` pipeline (`.claude/docs/pipeline.md`), so the Planner/Implementer/Reviewer handoff doesn't require the user to manually invoke each subagent. Requires a target task id as an argument, e.g. `dispatch-tasks sh-022` — this skill only ever acts on that one task, never scans `tasks/active/` for something else to work on. If invoked with no id, stop and ask which task to name rather than guessing.

**Running this skill on a task at `planning` is the user's explicit approval
of that task's plan.** The user has read the task file and is authorizing
implementation to start, including the one bookkeeping commit to `main`
that records the approval (task file only, no code; `pipeline.md` § Phase
transitions). Don't ask the user to confirm again.

Each invocation is one **tick**: a single reconciliation pass against the named task, advancing it as far as it currently goes. A tick isn't one phase transition — the named task's own review-fix-review cycle runs to completion within it, see "Automated phase chaining" under Step 2, so a single tick can involve several subagent calls back to back — and it isn't guaranteed to move the task at all: once the task is parked at a human gate, later ticks (loop mode's repeated wake-ups) just recheck whether the user has acted, they don't repeat work already done. Supports two invocation modes:
- **One-shot:** the user (or another skill) invokes this skill directly, naming a task, for a single tick. Do Steps 1-3 and stop — no wake-up scheduling.
- **Loop:** invoked via `/loop invoke the dispatch-tasks skill sh-XXX` (dynamic self-pacing mode). Do Steps 1-4 each tick — Step 4 schedules the next one, re-supplying the same task id.

Tell these apart from how you were triggered this turn, not from the task files themselves: if the current turn's instructions came from `/loop` (e.g. the user ran `/loop invoke the dispatch-tasks skill`, or this is a wake-up fired by a prior `ScheduleWakeup` call from this same loop), you're in loop mode. If the user (or a skill) just asked you to "run"/"invoke"/"dispatch" this skill directly with no `/loop` involved, you're in one-shot mode. When genuinely unsure which mode applies, default to one-shot — skipping an unrequested `ScheduleWakeup` is always safe, while scheduling one the user didn't ask for is not.

## Execution Protocol


### Step 1: Locate the named task
Run `python3 tools/task_status.py` (or `pixi run task-status`) and find the given id in its `tasks` array.

- **Found:** read `current_phase`, `review_rejections`, `blocked`, `unmet_blockers`, `branch_exists`, and `source` straight from that entry. The tool already performs the authoritative-read sequence — working tree vs. a `branch:sh-XXX` read straight from that branch's own tip, `tasks/active/` falling back to `tasks/completed/` for a task whose `approve-task` run finished finalizing but hasn't merged yet (`pipeline.md` § Git branching) — and already resolves `blocked_by` against `tasks/completed/`'s ids (`pipeline.md` § Task dependencies). Don't re-derive any of this by hand with `git show`/`git rev-parse`.
- **Not found in the `tasks` array:** the id isn't in `tasks/active/` (the tool only reports that directory). Check `tasks/completed/sh-XXX-*.md` and `tasks/abandoned/sh-XXX-*.md` directly to give a specific reason ("sh-XXX is already done" / "sh-XXX was abandoned"); if it's in neither, report "no such task" and stop — don't fall back to scanning or picking a different task.

Between successive dispatches within the same tick (see "Automated phase chaining" below), re-run the tool rather than reading the task file's frontmatter directly — it reflects whatever the last subagent call just committed.

### Step 2: Dispatch by phase
If Step 1's entry reported `blocked: true`, don't dispatch to any subagent, and don't perform the planning auto-approval flip either, regardless of `current_phase`. Report it in Step 3 as blocked on `unmet_blockers` and stop.

Act according to the unblocked task's `current_phase`:

| `current_phase` | Action |
|---|---|
| `planning` | Naming this task is the user's approval (`pipeline.md` § Phase transitions) — the interview already happened when `new-task` generated this file, so there's nothing left to auto-dispatch, only a phase flip to record. Set `current_phase: implementation`, `current_agent: implementer`, check off `Planning` in `## Status`, and commit that change directly to `main` (no `sh-XXX` branch exists yet at this point — same pre-branch pattern the Planner agent itself uses when the user confirms mid-interview). Then immediately proceed to the `implementation` row below for this same task, in this same tick. |
| `implementation` | Invoke the `implementer` subagent (Agent tool) with a prompt naming this exact task file path. |
| `review` | Invoke the `reviewer` subagent (Agent tool) with a prompt naming this exact task file path. If the Reviewer approves (task now sits at `user_signoff`), run the post-approval doc-hygiene pass below before reporting. If the Reviewer instead bounces the task back to `implementation`, skip the hygiene pass entirely — more code changes are coming next round anyway, so a pass now would just be re-litigated. |
| `user_signoff` | Skip. Report it as "awaiting user sign-off." |
| `blocked_needs_human` | Skip. Report it as "blocked — needs human input," and include the `review_rejections` count. |
| `done` | Skip, but flag it — a `done` task shouldn't still be in `tasks/active/`; it should have been moved to `tasks/completed/` by the user. |

Only ever the named task is touched — there's no scan across `tasks/active/` and so no other task to arbitrate against or report as "waiting its turn." Every task's Implementer/Reviewer work happens on that task's `sh-XXX` branch against one shared working tree (`pipeline.md` § Git branching); scoping to one named task at a time is what keeps two different tasks from ever checking out branches and running builds/tests out from under each other in the same tick.

#### Automated phase chaining
Don't stop after a single subagent call just because the named task landed in another automated phase. Immediately dispatch the next matching action for that SAME task, in this same invocation, and keep going until the task reaches a phase that requires a human, or leaves `tasks/active/` entirely. Concretely:
- `planning` (unblocked) → auto-approval flip runs → task now at `implementation` → immediately dispatch the Implementer for it, same as if it had started there.
- `implementation` → Implementer runs → task now at `review` → immediately dispatch the Reviewer for it. No separate invocation, and no need to check with the user first.
- `review` → Reviewer bounces it back to `implementation` and `review_rejections` is still below the cap (3) → immediately dispatch the Implementer again for it.
- `review` → Reviewer approves → task now at `user_signoff` → run the post-approval doc-hygiene pass below, then stop chaining this task. `user_signoff` requires the user.
- `review` → the rejection that just happened pushed `review_rejections` to the cap → task now at `blocked_needs_human` → stop chaining. This also requires the user.

This applies in both one-shot and loop mode: the named task's own planning-approval-through-review-fix-review cycle runs to completion — or to whichever human gate it hits first — without pausing for approval at each phase transition. Only the pipeline's existing human-gated phases (`planning` when blocked, `user_signoff`, `blocked_needs_human`) pause it; nothing here changes what those gates require.

#### Post-approval doc-hygiene pass
Runs once, right after the Reviewer approves a task (`review` → `user_signoff`), on that task's own `sh-XXX` branch — before the code merges is the last easy point to catch AI-writing-style tells and content rot in what the Implementer/Reviewer wrote, without re-litigating the rest of the repo.

1. Ensure the working tree is on the task's `sh-XXX` branch (the Reviewer subagent should have left it there; verify with `git status`/`git branch --show-current` rather than assuming).
2. Invoke the `doc-hygiene` skill with `--diff=main` (see `.claude/skills/doc-hygiene/SKILL.md`) — scopes the sweep to everything committed on this branch since it diverged from `main`, not the whole repo.
3. `doc-hygiene` never commits on its own (by its own design) — if it made any edits, `git status` will show them uncommitted on the `sh-XXX` branch afterward.
4. Read `doc-hygiene`'s own Step 5 sanity-check result (the checks, `pipeline.md` § Verification commands):
   - **Sanity check passed:** if there were edits, commit them on the `sh-XXX` branch with a message like `doc-hygiene: post-review pass on sh-XXX` (substituting the real id). If there were no edits (`doc-hygiene` reported nothing to fix), there's nothing to commit — note that plainly in Step 3's report rather than treating it as a failure.
   - **Sanity check failed:** do **not** commit anything, do **not** auto-fix, and do **not** let the task quietly proceed to `user_signoff` as if this pass never happened — leave the edits uncommitted on the branch exactly as `doc-hygiene` left them, and flag this prominently in Step 3's report as needing human attention. A hygiene pass breaking the build is anomalous (it's meant to touch only comments/prose) and deserves a look before the user trusts this task's `user_signoff` state.
5. Either way, the task's `current_phase` stays `user_signoff` — this pass only ever adds a commit (or nothing) on top of an already-approved branch; it never changes phase itself.

### Step 3: Report
Give a one-line status summary for the named task: phase before this tick, phase after (or "unchanged"). If it chained through more than one phase this tick, show the full path rather than just the endpoints (e.g. "sh-022: planning → implementation → review → user_signoff", or "sh-012: review → implementation → review → blocked_needs_human (rejection cap reached)") so a rejection round — or the planning auto-approval — is visible, not collapsed away. If the task was skipped due to `blocked_by`, say so explicitly and name every unmet id (e.g. "sh-007: blocked — waiting on sh-005"), and note if that blocked it out of the planning auto-approval specifically. If a review approval triggered the post-approval doc-hygiene pass, say what it did: committed edits, nothing to fix, or (prominently) that its sanity check failed and needs human attention. If Step 1 had to read the task's state from its own branch because the working tree's copy was stale, say so plainly (e.g. "sh-013: user_signoff — read from branch sh-013, the copy in the current working tree is stale") rather than silently reporting the corrected phase as if it came from the obvious place. If the id didn't resolve to a task in `tasks/active/` at all, report that instead (per Step 1) and stop — there's nothing further to do this tick.

### Step 4: Decide the next wake-up (loop mode only)
Skip this step entirely in one-shot mode — just stop after Step 3's report. Do not call `ScheduleWakeup` at all when not in loop mode; scheduling one unprompted leaves a recurring wake-up running that the user never asked for.

In loop mode:
- If the named task is no longer present in `tasks/active/` (moved to `tasks/completed/` or `tasks/abandoned/`): do not schedule another wake-up. Call `ScheduleWakeup` with `stop: true` and tell the user the loop ended because there's nothing left to dispatch for that task.
- Otherwise: call `ScheduleWakeup` with a reasonable delay (a few minutes to ~15, depending on whether anything is actively running vs. it's sitting in a human-gated phase) and pass the same loop prompt — including this same task id — back through `prompt` so the next tick re-invokes this skill against the same task.

## Constraints
- Never act on any task other than the one explicitly named by the caller — no scanning `tasks/active/` for something else to work on, even if the named task turns out to be blocked or already done.
- This skill's legitimacy comes from being actually invoked, this turn, for the named task — not from a subagent independently reproducing its steps with Bash after finding a task at `planning` or `implementation` (`pipeline.md` § Phase transitions go through skills, not direct agent calls).
- The `planning` → `implementation` flip is the one phase transition this skill performs directly rather than delegating to a subagent (`pipeline.md` § Phase transitions) — it's a bookkeeping-only commit representing the user's already-given approval, not code generation. Never treat it as license to touch the task file's actual content (Must Have, Frontier Advice, Execution Plan) — that's `new-task`'s job, not this skill's.
- Never advance a task past a human-gated phase (`user_signoff`, `blocked_needs_human`, or a still-blocked `planning`) yourself — those exist specifically to require a person.
- Never reset `review_rejections` or move a task out of `blocked_needs_human` — only the user does that (`pipeline.md` § Phases).
- Don't edit code directly from this skill — dispatch to the subagents; they do the work. The one exception (beyond the planning-flip commit above) is the post-approval doc-hygiene pass: `doc-hygiene` (a separate skill) makes the edits and this skill only commits its output, never authors changes itself.
