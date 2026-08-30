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

- `2026-08-30` - **A way to get the fast tier's toolchain into a fresh shell**: reviewing sh-001 in an environment with no project virtualenv, `./test.sh --fast` died with `./test.sh: line 24: ruff: command not found` and exit 127. The message names neither the missing dependency set nor the fix, so the diagnosis took a detour through hunting for an existing venv, a `uv`/`pipx` install, and user-site binaries before landing on the README's `pip install -e .[dev]`. Workaround: built a throwaway venv outside the repo and installed the `dev` extra into it. Simpler if: `test.sh` preflighted for `ruff`/`mypy`/`pytest` and pointed at the install command, or the repo had a bootstrap script that provisions the dev environment.
