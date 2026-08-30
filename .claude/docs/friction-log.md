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

- `2026-08-30` - **Reviewing `test.sh`'s own exit-status contract needed a hand-built `PATH`**: checking sh-001's Must Have exit codes (2 for usage, 3 for a failed preflight naming the missing tools, 1 plus an exact message when `freecadcmd` is absent) meant several `env -i PATH=...` runs plus a scratch directory of symlinks to the pixi env's binaries with `freecadcmd` left out, because that is the only way to reach the FreeCAD-missing branch while the rest of the tier still runs. None of it is committed, so it re-runs from scratch every review round. Simpler if: the harness had a fast-tier self-test for its own CLI contract (tracked as F1 in `tasks/active/sh-001-REVIEW.md`; delete this entry in the commit that adds it).
- `2026-08-30` - **Reviewing SHA-pinned workflows had no tooling behind it**: verifying sh-001's `.github/workflows/` meant (a) parsing the YAML to confirm `permissions`, `runs-on`, and first-step ordering per job, and (b) confirming six `uses:` SHAs really name the commits their `# vX.Y.Z` comments claim. Neither the `dev` extra's `.venv` nor the base VM has a YAML parser or an Actions linter, so parsing borrowed `.pixi/envs/default/bin/python` for `yaml`; SHA verification was a hand-rolled `curl` loop against the GitHub API that also had to dereference annotated tag objects to their commits. Neither check is in the fast tier, so nothing re-runs them on the next workflow edit. Simpler if: `actionlint` and a `tools/check-action-pins.sh` ran inside `./test.sh --fast`.
- `2026-08-30` - **FreeCAD 1.0 `freecadcmd` headless contract had to be reverse-engineered for sh-001's `--full` tier**: three assumed behaviors were all wrong and only surfaced by running real FreeCAD. (1) `freecadcmd script.py` exits 0 no matter what the script does - `sys.exit(7)`, an uncaught exception, even `os._exit(7)` all yield shell status 0, so `test.sh --full` cannot trust the return code and instead greps the smoke script's stdout for an "import OK" marker. (2) FreeCAD imports its own `freecad` namespace package during start-up with a frozen `__path__`, so importing a checkout-based `freecad.shelving` needs an explicit `extend_path(freecad.__path__, "freecad")` refresh, not just `sys.path.insert`. (3) Under `freecadcmd`, `import FreeCADGui` returns a stub module (no `ImportError`) that lacks `Workbench`, so an `except ImportError` guard in `init_gui.py` is insufficient; it also has to check `hasattr(Gui, "Workbench")`. Simpler if: a short "writing a `freecadcmd` smoke script" note in `docs/` captured these, or `freecadcmd` propagated exit status.
