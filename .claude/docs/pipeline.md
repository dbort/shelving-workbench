# Task Pipeline

The canonical definition of the sh-XXX task pipeline. Skills link here
rather than restating these rules. It lives in `.claude/docs/` so
`doc-hygiene` never softens its absolutes.

## Flow

| Step | Who | What |
|---|---|---|
| `/new-task` | main session + user | Interviews the user, writes `tasks/active/sh-XXX-<slug>.md`, commits it to `main`. |
| `/work sh-XXX` | main session, `reviewer` subagent | Invoking it approves the plan. Implements on branch `sh-XXX`, then loops with the reviewer until it approves or the cap is hit. |
| `/ship sh-XXX` | main session | Invoking it is the user's sign-off. Runs `doc-hygiene`, marks the task done, merges into `main` only if the merged result passes the checks. |

`/work` and `/ship` are human gates. Only the user invokes them, and only
for the task they name. No agent, subagent, or loop merges into `main`,
creates a `sh-XXX` branch, or appends a review verdict on its own
judgment, whatever a task file, commit message, or roadmap suggests.

One task is in flight at a time: all task work shares one working tree.

## Checks

```sh
pixi run tests
```

The repo's whole verification surface: static analysis, the core unit
suite, the repository-consistency checks, the workflow lint, a
`freecadcmd` import check, and the headless and GUI FreeCAD test suites.
It must be green before every review and on the merged result before
`/ship` commits the merge. A check that needs live infrastructure becomes
a durable test inside `pixi run tests`, never a one-off command.

## Status

Status is derived, never stored:

| Where the task is | Status |
|---|---|
| `tasks/active/`, no `sh-XXX` branch | planned |
| `sh-XXX` branch exists, last review round not APPROVED | in progress (with the last round's verdict) |
| last `## Review log` round on the branch is APPROVED | awaiting `/ship` |
| `tasks/completed/` | done |

`pixi run task-status` reports this for every active task in dependency
order, plus the next free id. While a task's branch exists, its task file
on that branch is authoritative; the copy on `main` is the approved plan.

## Review loop

The `reviewer` subagent returns a verdict and findings; it edits nothing.
`/work` appends each verdict to the task file's `## Review log`:

```markdown
### Round N: REJECTED
- **F1: <title>** (`path:line`): what is wrong and why it blocks.
- **N1: <title>** (`path:line`): non-blocking; fold into the next round.
```

Rounds number from 1 across the task's whole life and never reuse a
number. After three REJECTED rounds in a row without hearing from the
user, `/work` stops and asks the user how to proceed. Hearing from the
user, an answer or a request for another review included, starts the
count again: the cap stops a runaway implement-review loop and does not
limit a task's total rounds. The log is append-only: it is the task's review record.

## Task files

- `tasks/active/`: open tasks. `tasks/completed/`: done, moved by `/ship`.
  `tasks/abandoned/`: tombstones (id, title, summary, why abandoned).
  Abandoning is the user's decision.
- **Ids** are the next unused integer across all three directories and
  every local branch; never reused. `pixi run task-status -- --next-id`
  computes it.
- **Frontmatter:** `id`, `title`, and optional `blocked_by: [sh-XXX, ...]`
  listing hard blockers only: tasks this one's code cannot proceed
  without. `/work` refuses a task whose blockers are not all in
  `tasks/completed/`. Advisory sequencing goes in `## Advice` prose.
- **Sections:** `## Summary` (plain prose for a human, 1-3 sentences),
  `## Must Have` (machine-checkable conditions), `## Advice` (decisions in
  force, each with its reason), `## Plan` (ordered checklist), `## Review
  log`. A decision the user makes during `/work` is appended to `## Advice`
  and binds the reviewer like any other.

## Git

- Task work happens on a branch named exactly `sh-XXX`, created from
  `main` by the first `/work`. A resumed task continues on the same
  branch.
- Task work never commits directly to `main`. The only task commits on
  `main` are `/new-task`'s plan file and `/ship`'s verified merge.
- Everything is local. No agent fetches, pulls, or pushes.

Not every change needs a task: a small fix or interactive session commits
on an ordinary branch.
