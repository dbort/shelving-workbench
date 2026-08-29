# Working with the Task Pipeline

The human playbook for driving the repo day to day. The pipeline's rules
themselves (phases, branching, `blocked_by`, verification commands,
task-file conventions) live in
[`.claude/docs/pipeline.md`](../.claude/docs/pipeline.md) — this file only
covers what *you* do at each point.

## Starting a new task

1. Trigger the Planner: start a new conversation and describe the task, or
   ask directly for the `new-task` skill / `planner` agent.
2. It runs an in-depth interview — expect it to keep asking until the task
   is genuinely unambiguous, with a recommended answer attached to each
   question. Be concrete: vague answers here become the Implementer's
   problem later, since it can't ask follow-ups.
3. Review the generated `tasks/active/sh-XXX-[slug].md`. Check
   in particular:
   - `## Must Have`: are these machine-checkable, and do they capture what
     you meant?
   - `## Execution Plan`: does the file breakdown and ordering make sense?
4. Once you're satisfied, tell the Planner to advance the task (it will set
   `current_phase: implementation`), or run
   `/dispatch-tasks sh-XXX` against it directly — naming a
   `planning`-phase task to `dispatch-tasks` IS your approval, and it'll
   flip the phase and immediately start the Implementer in the same
   breath. Either way, nothing advances the task on its own.

## Running the pipeline forward

`dispatch-tasks` always takes a task id and only ever acts on that one
task — `/dispatch-tasks sh-XXX`. Once you name a task, it runs
forward through `planning` (if you haven't approved it yet),
`implementation`, and `review` on its own, stopping only when it needs
you: a still-blocked `planning`, `user_signoff`, or `blocked_needs_human`.
Two ways to invoke it:

- **One-shot:** ask Claude to "invoke the dispatch-tasks skill on
  sh-XXX" to nudge that task forward once.
- **Autonomous:** run `/loop invoke the dispatch-tasks skill
  sh-XXX` and let it self-pace against that same task. It stops
  once the task leaves `tasks/active/` (done or abandoned).

You don't need to babysit the loop. It skips the task entirely if it has an
unmet `blocked_by`, and reports whatever human-gated phase it's sitting
in; it keeps waking up until you act.

## Your gates in the pipeline

These are the phases nothing will auto-advance past. The loop will keep
surfacing them at you until you do something.

### `planning`
Covered above: approve or correct the task file before implementation starts.

### `user_signoff`
The Reviewer approved the diff. Before marking this done:
1. Check out the task's `sh-XXX` branch and exercise the task
   yourself; passing tests and lint don't guarantee it does what you
   wanted.
2. If it's good: run `/approve-task sh-XXX`. Running it against
   a task IS the sign-off: it finalizes the task file, re-sweeps the
   branch with `doc-hygiene`, and merges `sh-XXX` into `main`
   only after both verification tiers pass against the merged result.
3. If it's not good: don't hand it back through the pipeline yourself.
   Either fix it on the branch, or demote it back to `implementation` with a
   note in the task file about what's wrong.

### `blocked_needs_human`
The Reviewer bounced this task 3 times and gave up. Read
`tasks/active/sh-XXX-REVIEW.md` for what it kept rejecting.
Your options:
- Fix the underlying issue yourself on the `sh-XXX` branch,
  then move the task to whatever phase reflects reality (usually back to
  `review`, or straight to `user_signoff` if the fix is complete).
- Clarify or correct the task file (the ask may have been ambiguous or
  contradictory) and reset `review_rejections: 0`, `current_phase:
  implementation` to give the pipeline another shot.

## Escape hatches

The full pipeline is meant for real tasks, not every keystroke. For a
one-line fix or something you want to talk through, skip the task-file
machinery: ask directly, or use `/code-review` on a manual change. There's
no requirement that every commit in this repo come from a
`sh-XXX` task.
