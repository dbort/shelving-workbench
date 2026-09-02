# Friction log

Friction log for working in this repo: moments where completing a task forced an unnecessary workaround. An entry qualifies when there is a clear "this would have been simpler if X existed or Y returned this data" - missing tools, missing data, poor return shapes, absent markers, docs that had to be reverse-engineered.

Logging is part of the work itself: same session, never deferred. A workaround that succeeded smoothly still gets logged: success is what hides the papercut. Entries are raw material for tooling/docs/API improvements.

This file is the canonical rule, per the repo's doc architecture (`pipeline.md` explains the convention); `CLAUDE.md` and the agent files carry at most a one-line pointer here. It lives in `.claude/docs/` because it's agent-contract material: not swept by `doc-hygiene`.

## Origin

From Benjamin André-Micolon's [linkedin post](https://lnkd.in/p/g4ARbEpH) on 2026-08-17.

## Format

Newest first. One bullet per papercut:

- `YYYY-MM-DD` - **<what was needed>**: what happened; the workaround used. Simpler if: <the missing tool/data/doc>.

## Adding an entry mid-task

An entry written during sh-XXX task work commits on that task's branch with the rest of the work and reaches `main` when the task merges - never a separate commit to `main` (`pipeline.md` § Git branching).

## Solving a papercut

Fixes route like any other work (`pipeline.md` § Task files and directories, last paragraph): task-sized ones become a sh-XXX task via `new-task`; small ones commit directly. Fix each papercut in its own dedicated commit whose message records BOTH the original papercut (the friction it captured) AND how it was solved, in broad strokes - the code carries the detail. Delete the entry from this file in that same commit: the commit history is the durable record, this file tracks only what is still open.

Sweeping the log is a human-triggered act, like task sign-off: the user asks for a sweep; no agent schedules one on its own.

## Entries

- `2026-08-31` - **Bash-tool shells have no coreutils on `PATH`**: the Bash tool runs non-login, non-interactive shells with a minimal PATH frozen per session and no `.bashrc`/`.profile` sourced; on this VM that PATH omits the dirs holding `df`, `ls`, `du`, `find`, `rm`, and `git`, so every diagnostic command fails by bare name. Worked around by hard-coding absolute paths (`/usr/bin/df`, `/bin/ls`, `/usr/bin/du`, `/usr/bin/find`, `/bin/rm`, `/usr/bin/git`) in each call. Simpler if: the VM setup put `/usr/bin` and `/bin` on the PATH the Bash tool inherits (e.g. extend `env.PATH` in `~/.claude/settings.json` beyond `${HOME}/.local/bin:${PATH}`, or set it in the VM's default environment), so scripts and ad-hoc commands can call standard tools by name.
