---
name: ship
description: "Human sign-off for a reviewed task: doc-hygiene sweep, mark done, verified merge into main. Run only when the user invokes /ship sh-XXX."
disable-model-invocation: true
---

# Ship a task

Invoking `/ship sh-XXX` is the user's sign-off. Pipeline rules:
`.claude/docs/pipeline.md`.

1. **Preflight.** Require a task id, a clean tree, and no merge or rebase
   in progress. If `sh-XXX` is already merged into `main`, delete it with
   `git branch -d` and stop. If the task is already in `tasks/completed/`
   on the branch, skip to step 4 (a retry after a failed merge).
   Otherwise the task file's last `## Review log` round on `sh-XXX` must
   be APPROVED.
2. **Hygiene.** On `sh-XXX`, run the `doc-hygiene` skill with
   `--diff=main`. If it made edits and its checks passed, commit them
   (`doc-hygiene: pre-merge pass on sh-XXX`). If its checks failed, stop.
3. **Finalize.** Tick every Must Have the review confirmed. If
   `docs/roadmap.md` references this id, mark it done there (a `Task
   sh-XXX` status becomes `Done sh-XXX`; a checklist box is ticked, and
   the rollup status becomes `Done` when it was the last box). Stage the
   edits, then `git mv tasks/active/sh-XXX-<slug>.md tasks/completed/`,
   and commit (`sh-XXX: mark task done`). Staging before the move matters:
   `git mv` moves the index's blob, not the file on disk.
4. **Merge.** `git checkout main`, then `git merge --no-commit --no-ff
   sh-XXX`. On conflicts, stop and leave them for the user. Run `pixi run
   tests` on the merged tree.
   - Green: commit `Merge sh-XXX: <title>`, then `git branch -d sh-XXX`
     (never `-D`).
   - Red: `git merge --abort`, report the failing check, and stop. The
     branch keeps its commits; re-running `/ship` resumes at this step.

Report what merged, what `doc-hygiene` changed, and `pixi run
task-status` for the remaining backlog.
