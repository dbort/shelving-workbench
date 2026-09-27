---
name: doc-hygiene
description: Sweep code comments and markdown docs for content rot and AI-writing-style tells, then verify no technical fact was lost. Use when asked for a hygiene pass, or from /ship.
---

# Doc & comment hygiene

Applies `CLAUDE.md` § Writing style by destination (the file-content
rules) to comments and markdown prose, then has a second agent confirm no
fact was lost. It never commits; the caller does.

The style rules are adapted in part from the **stop-slop** skill (MIT
License, Copyright (c) 2025 Hardik Pandya); see
`NOTICE-stop-slop-LICENSE.md` in this directory.

## Invocation

`/doc-hygiene [--diff=<ref>] [path]`

- `--diff=<ref>`: files changed in `git diff <ref>...HEAD`, and edits
  limited to the changed lines plus any nearby comment the change made
  stale. `/ship` uses `--diff=main`.
- `path`: limit to a file or directory. With neither argument, sweep every
  tracked file in full.

## Steps

1. **List files:** tracked `*.md`, `*.py`, `*.sh` in scope, excluding
   `tasks/`, `.claude/`, and `CLAUDE.md` (agent contracts whose absolutes
   are deliberate). Drop deleted paths. Stop if the list is empty.
2. **Edit:** run one `hygiene` subagent (no shell, so no git) with the
   file list, each file's `git diff <ref>...HEAD` hunks in diff mode, and
   this brief: apply `CLAUDE.md` § Writing style by destination to
   comments and markdown prose only; never change executable code,
   config, command syntax, or markdown structure; leave clean text
   untouched; preserve every technical fact and rationale; flag, don't
   fix, a comment that contradicts the code. In diff mode, edit only the
   changed lines plus any nearby comment they made stale. Report each
   edit as `file:line before -> after`.
3. **Verify:** run a second, fresh `hygiene` subagent with `git diff` of
   those files (the uncommitted edits) and the editor's report, told to
   edit nothing. It reports PASS or FLAGGED per file: a changed claim
   about behavior, a deleted rationale, or, in diff mode, edits outside
   the changed regions. Revert any flagged hunk that lost real content.
4. **Check:** run `pixi run tests`. A failure means an edit touched more
   than prose: stop and report it; do not auto-fix.
5. **Report** the edits by file.
