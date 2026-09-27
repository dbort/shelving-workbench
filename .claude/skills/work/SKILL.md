---
name: work
description: Implement a planned sh-XXX task on its branch and loop it with the reviewer until approved. Run only when the user invokes /work sh-XXX.
disable-model-invocation: true
---

# Work a task

Invoking `/work sh-XXX` is the user's approval of that task's plan.
Pipeline rules: `.claude/docs/pipeline.md`.

1. **Preflight.** Require a task id and a clean tree. Find
   `tasks/active/sh-XXX-<slug>.md`; stop if it is missing or any
   `blocked_by` id is not in `tasks/completed/`.
2. **Branch.** Check out `sh-XXX`, creating it from `main` if absent.
   Read the task file there, including every `## Review log` round.
3. **Implement** the Plan, addressing any open findings from the last
   REJECTED round. Check off steps as they land. Follow `CLAUDE.md`
   conventions. When a product or behavior decision is not settled by the
   task file, ask the user, then append the answer to `## Advice` (dated).
   Log workarounds in `.claude/docs/friction-log.md` and defects in
   shipped code in `.claude/docs/bug-log.md`.
4. **Verify and commit.** `pixi run tests` green; everything committed on
   `sh-XXX` (`git status --porcelain` empty). The reviewer diffs committed
   state only.
5. **Review.** Run the `reviewer` subagent, naming the task file. Append
   its verdict and findings to `## Review log` as the next round, and
   commit.
   - REJECTED, fewer than three rejections this invocation: go to step 3.
   - REJECTED for the third time this invocation: stop and ask the user
     how to proceed.
   - APPROVED: stop. Report that the task awaits `/ship sh-XXX`.

Report the rounds this run took, one line each.
