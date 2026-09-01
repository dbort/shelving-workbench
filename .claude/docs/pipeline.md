# Task Pipeline — Canonical Semantics

This file is the single authoritative definition of the sh-XXX
task pipeline: its phases, branching rules, dependencies, verification
commands, and task-file conventions. Every other file that mentions these
rules (`CLAUDE.md`, `.claude/agents/*`, `.claude/skills/*`,
`docs/agent-usage.md`) links to an anchor here and restates at most one
line. When pipeline behavior changes, change this file first, then grep
those files for restatements to update.

It lives in `.claude/docs/` because it's an agent contract: its absolutes
("never", "always") are literal invariants, and `doc-hygiene`'s style pass
must never soften them. `docs/` is for human-facing prose and IS swept;
`.claude/docs/` is not. See `CLAUDE.md` for the convention.

Growth rule: if a section outgrows this file (roughly 300 lines total),
graduate that section to its own file in `.claude/docs/` and leave a link
here. Don't split preemptively.

## Verification commands

The one place the repo's check commands are defined; agents and skills
reference this section rather than naming a command themselves. Edit the
command below to match this repo's tooling.

**The checks** — one command is the repo's whole verification surface:
static analysis, the `shelving_core` unit suite, repository-consistency
checks, the workflow-hardening lint, and a headless FreeCAD import smoke.
It runs its steps in order and aborts at the first failure. A few seconds
end to end, so it is cheap enough to run many times per task.

```sh
pixi run tests
```

Who runs what:
- The Implementer runs the checks after each Execution Plan step.
- The Reviewer runs the checks, on every review, unconditionally.
- `approve-task` runs the checks on the merged result before committing
  the merge.
- `doc-hygiene`'s sanity check runs the checks.

If a task's work can only be verified by a live-infrastructure check that
`pixi run tests` does not yet express, that check belongs as a durable
automated test inside `pixi run tests` — not as a one-off shell command
that evaporates after the session that ran it.

## Phases

Each task file's `current_phase` frontmatter field drives everything. The
full cycle:

| `current_phase` | Owner | What happens |
|---|---|---|
| `planning` | Planner + human | The Planner (via the `new-task` skill) interviews the user in depth and generates the task file. Human-gated: the user must approve the generated file before the Planner sets `current_phase: implementation`. |
| `implementation` | Implementer | Executes the task file's `## Execution Plan` steps in order on the task's `sh-XXX` branch, then hands off to `review`. |
| `review` | Reviewer | Diffs the branch against `main`, runs the checks itself via Bash (§ Verification commands), and either approves (→ `user_signoff`) or rejects (see the rejection loop below). |
| `user_signoff` | Human | The user tests the branch manually, then runs `/approve-task sh-XXX` — invoking that skill against a task IS the sign-off act. It finalizes the task file, re-sweeps with `doc-hygiene`, and merges into `main` only after the merged result passes the checks. |
| `blocked_needs_human` | Human | Dead end for the automated pipeline: the rejection cap was hit. The user fixes the code, clarifies the task file, or resets `review_rejections: 0` and demotes to `implementation` for another run. |
| `done` | — | Terminal. The task file moves to `tasks/completed/` (done by `approve-task`). A `done` task still sitting in `tasks/active/` is an anomaly worth flagging. |

**Human gates:** `planning`, `user_signoff`, and `blocked_needs_human` are
never auto-advanced or auto-dispatched. Automated agents report them and
wait; only a human moves a task past one. Automated agents also never reset
`review_rejections` or move a task out of `blocked_needs_human`.

### The rejection loop

On rejection, the Reviewer writes findings to
`tasks/active/sh-XXX-REVIEW.md` (same id as the task file, so
concurrent tasks can't collide) and increments `review_rejections`:

- **Below the cap (3):** demote to `current_phase: implementation`,
  `current_agent: implementer`. The Implementer resumes on the same
  `sh-XXX` branch.
- **At the cap:** set `current_phase: blocked_needs_human` instead of
  looping again. Append a note to `sh-XXX-REVIEW.md` saying the
  cap was hit.

On approval, the Reviewer removes any stale `sh-XXX-REVIEW.md`
— a clean approval leaves no rejection notes behind. (`approve-task`
double-checks this at sign-off anyway.)

#### `sh-XXX-REVIEW.md` format

Use this template rather than inventing a structure per round or
searching prior tasks for precedent:

```markdown
# sh-XXX Review — Round N

**Verdict:** REJECTED

## Blocking findings
- **F1: <short title>** (`path/to/file:line`): what's wrong and why it
  blocks approval.
- **F2: <short title>** (`path/to/file:line`): ...

## Non-blocking notes
- **N1: <short title>** (`path/to/file:line`): worth fixing, not worth
  another round on its own; fold into whatever round addresses the
  blocking findings.
```

`Round N` is this task's current rejection count *after* incrementing (the
first rejection is Round 1). Omit `## Non-blocking notes` when there are
none. At the cap, append a final section:

```markdown
## Cap reached
review_rejections is at 3. current_phase is now blocked_needs_human. A
human can clarify the task's requirements, fix the code directly, or
reset review_rejections to 0 and demote to implementation for another
round.
```

### Phase transitions go through skills, not direct agent calls

Advance a task only by invoking the skill that owns the transition:
`new-task` for `planning`, `dispatch-tasks` for `implementation`/`review`,
`approve-task` for `user_signoff` → `done`. Never invoke the
Implementer/Reviewer subagents directly via the Agent tool as a shortcut:
the skills bundle required side effects (branch verification, phase
chaining, the post-approval `doc-hygiene` pass) that a bare subagent call
skips. This is a hard rule.

The `planning` → `implementation` transition specifically has two
legitimate triggers, both requiring the user's explicit say-so: inline via
`new-task`/the Planner agent when the user confirms the generated file
mid-interview, or via `dispatch-tasks sh-XXX` naming a task
that's still at `planning` — naming it that way IS the approval, the same
pattern `approve-task` already uses for `user_signoff`. Either way the
file is already complete by the time this transition fires (the interview
happens before the file exists), so the gate is a human blessing finished
content, not a live conversation.

## Dispatch semantics

The `dispatch-tasks` skill is the sole dispatcher (its `SKILL.md` holds the
step-by-step protocol; these are the invariants it implements). Each
invocation is one **tick**: a single reconciliation pass against the one
named task, advancing it as far as it currently goes. A tick doesn't
correspond to one phase transition — chaining (below) can carry it through
several — nor does every tick move the task at all: once it's parked at a
human gate, further ticks are just polling for whether the user has acted,
not new work.

- **Acts only on a named task.** `dispatch-tasks sh-XXX` takes
  a required task id and only ever touches that one task — it never scans
  `tasks/active/` to pick an eligible task on its own. All task work shares
  one working tree (see § Git branching), so there's no scenario where it
  needs to arbitrate between several ready tasks in one invocation.
- **Planning auto-approval:** if the named task is at `planning` and
  unblocked, naming it is treated as the user's approval — `dispatch-tasks`
  flips it to `implementation` itself (see § Phase transitions) before
  chaining into the Implementer.
- **Chaining:** the named task runs to completion within the tick —
  implementation → review, and on a rejection under the cap, back to
  implementation and review again — stopping only at a human gate or when
  the task leaves `tasks/active/`.
- **Post-approval hygiene:** the moment the Reviewer approves,
  `dispatch-tasks` runs `doc-hygiene --diff=main` on the branch, before the
  code merges — the last easy point to catch doc rot in what the agents
  wrote.
- **Loop mode:** driven by `/loop invoke the dispatch-tasks skill
  sh-XXX`, it self-paces, re-supplying the same task id on each
  wake-up, and ends itself once that task leaves `tasks/active/`.

## Git branching

- Each task's work happens on a branch named exactly `sh-XXX`
  (matching the task's id), created from `main` by the Implementer the
  first time the task reaches `implementation`. A bounced-back task
  resumes on the same branch; never create a second branch for one task.
- **Never commit task work directly to `main`.** Work lands on `main` only
  via `approve-task` merging a `sh-XXX` branch, and that merge
  commits only after the checks (§ Verification commands) pass on the
  merged result — a broken merge never enters `main`'s history.
- A task's phase-transition commits live on its `sh-XXX`
  branch, not `main`. The working tree's copy of a task file is stale for
  any task whose branch isn't currently checked out; read authoritative
  state via `git show sh-XXX:tasks/active/sh-XXX-*.md`
  (details in `dispatch-tasks`'s Step 1).

## Task dependencies (`blocked_by`)

A task file may declare `blocked_by: [sh-XXX, ...]` in its
frontmatter: task ids that must be `done` (present in `tasks/completed/`)
before this task can be dispatched to `implementation` or `review`, or
auto-advanced out of `planning` by `dispatch-tasks`.

- **Hard blockers only:** something this task's code or tests genuinely
  cannot proceed without (e.g. it imports a package another still-open task
  creates). Softer, advisory sequencing ("more meaningful once X lands")
  stays as prose in `## Frontier Advice` — informative for a human or the
  Reviewer, not enforced.
- **Absent means unblocked.** That's the default; don't write
  `blocked_by: []`.
- **`dispatch-tasks` is the sole enforcement point.** It skips a blocked
  task regardless of its `current_phase` and reports the unmet id(s). No
  other agent checks the field — a second check would just be a second
  place for the logic to drift.

## Task files and directories

- **`tasks/active/`** — open tasks, one `sh-XXX-[slug].md`
  each, created by the `new-task` skill (its `SKILL.md` holds the file
  blueprint and writing rules).
- **`tasks/completed/`** — tasks that reached `done`, moved here by
  `approve-task`.
- **`tasks/abandoned/`** — tombstones for tasks dropped before shipping
  (superseded, no longer needed). A tombstone keeps the id, title, and a
  `## Summary` (same human-readable 1-3-sentence convention as an active
  task's), plus why it was abandoned and what superseded it; the full
  original plan stays recoverable from git history at the old
  `tasks/active/` path. Abandoning is a human/Planner decision, like
  `done` — no automated agent abandons a task on its own.
- **Id allocation:** the next unused integer across ALL THREE directories,
  zero-padded to match existing width. An id is never reused, whether the
  task completed or was abandoned.
- **Frontmatter fields:** `id`, `title`, `current_agent`
  (planner/implementer/reviewer/user), `current_phase` (see § Phases),
  `review_rejections` (see the rejection loop), optional `blocked_by`
  (see § Task dependencies).

Not every commit needs a task. The pipeline is for real units of work; a
one-line fix or an interactive session can commit directly (on a branch —
the never-commit-task-work-to-`main` rule above is about task work, but
keeping `main` merge-only is the repo-wide habit).
