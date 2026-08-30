# Skill: Approve & Merge a Task

## Purpose
Perform the User (Sign-off) step of the `tasks/active/*.md` pipeline (`.claude/docs/pipeline.md` § Phases) for a task sitting at `current_phase = "user_signoff"`: finalize its task file, re-sweep its branch for doc/comment rot introduced since the last `doc-hygiene` pass, merge it into `main` only after confirming the merged result actually passes both verification tiers, then clean up the branch.

Invoking this skill against a specific task IS the human sign-off act. There is no separate confirmation prompt inside this skill — deciding to run `/approve-task sh-XXX` is the approval; the skill's job is to execute it correctly, not to re-ask whether you meant it.

## Invocation
`/approve-task sh-XXX` — the task id is required, always. There's no auto-detection of "the" task at `user_signoff`: more than one task can be sitting there at once, so guessing which one you mean is worse than asking you to say it.

## Execution Protocol

### Step 1: Preflight
- If no `sh-XXX` argument was given, stop and ask for one.
- `git status --porcelain` must be empty. If it isn't, stop and tell the human to commit or stash first — don't operate on a dirty tree.
- Check for an in-progress merge or rebase (`.git/MERGE_HEAD`, `.git/rebase-merge`, `.git/rebase-apply`). If any exist, stop — something else is mid-operation and resolving it isn't this skill's job.
- Locate the task file and branch by that location:
  - Found at `tasks/active/sh-XXX-*.md`: `current_phase` must be `user_signoff` to proceed (Step 2). Anything else found here is either a task not yet ready (`planning`, `implementation`, `review`, `blocked_needs_human` — stop, report the actual phase) or anomalous (`done` sitting in `tasks/active/` means an earlier run didn't finish Step 3's move — stop, flag it, don't guess).
  - Found at `tasks/completed/sh-XXX-*.md`: `current_phase` should be `done`; anything else here is anomalous (stop, flag it). With `done` confirmed, check whether the `sh-XXX` branch ref still exists — `git rev-parse --verify --quiet refs/heads/sh-XXX` — **before** touching `--is-ancestor`, since that check needs a valid ref on both sides and errors outright (not a clean pass/fail) against one that's gone:
    - Branch **doesn't exist**: the only way it gets deleted is Step 4's success path, so this task is already fully closed out. Report that and stop — nothing to do.
    - Branch **exists**, and `git merge-base --is-ancestor sh-XXX main` **succeeds**: already merged, but the branch itself wasn't cleaned up (e.g. a prior run got interrupted between the merge commit and the `git branch -d`, or someone recreated it). Finish the leftover cleanup — `git branch -d sh-XXX` — and report that this run just tidied up an already-merged branch.
    - Branch **exists**, and `git merge-base --is-ancestor sh-XXX main` **fails**: genuinely not yet merged — a retry after a prior failed merge attempt (Step 4 aborted last time). Skip directly to Step 4.
  - Found at neither path: stop with an error naming the id that wasn't found.

### Step 2: Pre-merge doc-hygiene sweep (on branch `sh-XXX`)
A task branch can pick up commits after `dispatch-tasks`' post-review `doc-hygiene --diff=main` pass already ran — manual review feedback, follow-up refactors — content that pass never saw. Re-sweeping `--diff=main` again here would also re-litigate everything that pass already covered, so scope tighter:

- `git checkout sh-XXX`.
- Find the most recent `doc-hygiene:`-prefixed commit on this branch: `git log --format='%H %s' sh-XXX | grep -m1 '^[0-9a-f]\+ doc-hygiene:'`.
  - Found: invoke the `doc-hygiene` skill with `--diff=<that commit's SHA>` — scopes the sweep to only what changed since that pass, not the whole branch.
  - Not found (no `doc-hygiene` pass ever ran on this branch): invoke with `--diff=main` instead, matching what the first pass would have used.
- `doc-hygiene` never commits on its own, and runs its own sanity check (the fast checks) before reporting (see its `SKILL.md`). If it made edits and its sanity check passed, commit them: `doc-hygiene: pre-merge pass on sh-XXX`. If its sanity check failed, stop here and flag it prominently — don't carry unverified edits into Step 3.
- If it found nothing to fix, that's a normal outcome, not a failure. Note it and continue.

### Step 3: Finalize the task file (on branch `sh-XXX`)
- Set `current_phase: done` in the frontmatter.
- Check off `- [ ] User sign-off` under `## Status`.
- If a `docs/roadmap.md` milestone's **Status** line reads `Task sh-XXX` for this id, change it to `Done sh-XXX` and `git add docs/roadmap.md` so it rides along in this step's commit. The roadmap convention puts this flip here, at merge — not in the task's own steps. Skip cleanly if no such line exists.
- If `tasks/active/sh-XXX-REVIEW.md` exists, delete it. This normally shouldn't be necessary — the Reviewer already removes it on approval (`pipeline.md` § The rejection loop) — but check anyway rather than assume.
- **Stage the edit before moving the file — do not skip this.** `git add tasks/active/sh-XXX-*.md` first. `git mv` moves whatever blob the index currently has for that path; if the frontmatter edit above is still unstaged when `git mv` runs, it silently moves the STALE pre-edit content instead of what's actually on disk, and the commit that follows records a task as `done` while its own file still says `user_signoff`. This is a real failure mode, not a hypothetical — the staging step exists because it happened.
- `git mv tasks/active/sh-XXX-*.md tasks/completed/`.
- Before committing, confirm the staged content is actually correct: `git diff --cached -- tasks/completed/sh-XXX-*.md` (the file already shows at its new path in the index at this point) and check it shows `current_phase: done` and the checked-off box, not the old values. If it still shows the stale content despite staging first, something is wrong — stop and investigate rather than committing it.
- Commit: `sh-XXX: mark task done, move to tasks/completed/`, body `Confirmed by user sign-off.`
- Verify the commit itself landed correctly, not just the staged diff: `git show HEAD:tasks/completed/sh-XXX-*.md | head -16` and confirm `current_phase: done` and the checked box are really there. Don't skip this because the pre-commit check above passed — verify the actual commit, since that's the artifact Step 4 merges.

### Step 4: Merge into main, verified before it's real
- `git checkout main`. (Never `git fetch`/`git pull` first — this skill is local-only; syncing with any remote is a separate, explicit action for the human.)
- `git merge --no-commit --no-ff sh-XXX`.
  - Conflicts: stop immediately. Report which files conflict. Leave the repo in git's ordinary conflict state — don't attempt automatic resolution and don't `--abort` on the human's behalf; they may want to resolve it in place.
  - Clean: `main`'s working tree and index now hold the merged result, nothing committed yet — this is the load-bearing property that makes the next step safe. A failure here can never land in `main`'s history, because nothing has been committed to it yet.
- Run both verification tiers, fast then full (`pipeline.md` § Verification commands).
  - All pass: `git commit -m "Merge sh-XXX: <title from the task's frontmatter>"`, then `git branch -d sh-XXX` (plain `-d`, never `-D` — it refuses unless the branch is genuinely fully merged, which is the actual safety property here, not a formality). Report success.
  - Any fail: `git merge --abort`, which restores `main` to exactly its pre-merge state. Report the failure prominently (which check, its output) and stop. Do not delete `sh-XXX` — its Step 2/3 commits stand as-is. Once the underlying issue is fixed (on `sh-XXX`, or on `main` if something else regressed it), re-invoking `/approve-task sh-XXX` resumes at Step 4 via Step 1's retry-state check.

### Step 5: Report
State plainly: what got merged, whether `doc-hygiene` found anything to fix, whether the branch was deleted. List any other tasks still in `tasks/active/` (id + `current_phase`) as a reminder — not an action taken — that they may be worth merging `main` into to check for coexistence; this skill only ever touches the one branch it was invoked on plus `main`.

## Constraints
- Never invoke this skill from `dispatch-tasks` or any other unattended loop. `user_signoff` is explicitly human-gated (`pipeline.md` § Phases); this skill exists to be run BY a human, not on their behalf, and it treats invocation itself as the approval — that only holds if a human is the one doing the invoking.
- Never push to a remote. Every git operation here is local-only; publishing `main` (or anything else) is a separate, explicit action for the human to take.
- Never `git branch -D` — only the safety-checked `-d`.
- One task per invocation, even if several are eligible. Matches `dispatch-tasks`' own one-task-at-a-time discipline, for the same reason: all task work shares one working tree.
