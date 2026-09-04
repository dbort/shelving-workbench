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

- `2026-09-03` - **`pixi run tests` attributes `freecadcmd` output to the wrong check**: each smoke block in `tools/run-tests.sh` captures one script's combined output and prints it as an unlabelled blob, and inside a blob Python's block-buffered `print` lines flush before FreeCAD's C++ start-up banner and recompute progress. Reviewing sh-011, the tail therefore read `shelving workbench import OK` / banner / `APART_PROXY_EXECUTE: no` / `shelving object layer OK` / banner / `Recompute......`, which looks like a third `freecadcmd` run and hides which script emitted what. Worked around by re-running the whole suite redirected to a file and counting lines back against `run-tests.sh` to split the blobs. Simpler if: each smoke block printed a header naming the script before its captured output (`== freecad_object_smoke.py`), matching the `== actionlint` style the workflow lint already uses.
- `2026-09-03` - **`App::Part` rejects a `Proxy` assignment, so the sh-011 probe pseudocode crashes as written**: the task's PROBE step specified `part = doc.addObject("App::Part", "Probe"); part.Proxy = _Recorder(); part.touch(); doc.recompute()`, but under FreeCAD 1.0.0 (`freecadcmd`) `part.Proxy = recorder` raises `AttributeError: 'App.Part' object has no attribute 'Proxy'` before any recompute happens: a bare `App::Part` has no `App::*Python` extension and cannot hold a proxy at all. Worked around by wrapping the assignment in `try/except AttributeError` and treating that as the observed "execute never called" outcome (`EXPECTED_APART_EXECUTE = False`), and by documenting the exact exception in `docs/freecadcmd-notes.md`. Simpler if: the probe pseudocode had anticipated that the scripted-object question for a C++ container type is "can it even take a Proxy", not just "does recompute call execute".
- `2026-09-03` - **Per-step green checks impossible across the mypy-gate widening in sh-011**: Step 1 adds `freecad/shelving/` to `[tool.mypy] files`, but the modules that make it type-clean (`objects/`, `catalog.py`) land in Steps 2-4 and the `init_gui.py` annotations land in Step 5, so `mypy` (hence `pixi run tests`) is red from Step 1 through Step 4 by construction. The task's Frontier Advice anticipates this and says to treat Steps 1-5 as one green checkpoint; did that, committing per-step underneath it. Simpler if: the Planner marked Steps 1-5 as a "verify at end of Step 5" span in the Execution Plan itself (as the 2026-09-02 entry below already asked for), so the per-step green rule and the plan agree.
- `2026-09-02` - **Per-step "green `pixi run tests`" is unachievable for an atomic API rename**: sh-009 step-scoping (run the checks after each Execution Plan step, never proceed past red) collides with the `Carcass.default_thickness_mm` -> `default_material` + `Catalog` change, which spans `layout.py`, `solver.py`, `svg.py`, `tools/layout_demo.py`, and five test modules that only compile/pass together. The suite is red from step 2 through step 6 by construction. Worked around by treating steps 2-6 as one green checkpoint and committing per-step underneath it. Also: the `vendor-core.sh --check` drift gate in `pixi run tests` goes red on every `shelving_core/` edit until the vendor script is re-run, but the plan only schedules that at step 8; re-ran it after each `shelving_core/` change. Simpler if: the Planner marked a span of steps as "verify at the end of step N" when an interface rename makes them inseparable, and folded a `vendor-core.sh` re-run into every step that touches `shelving_core/`.
- `2026-08-31` - **Bash-tool shells have no coreutils on `PATH`**: the Bash tool runs non-login, non-interactive shells with a minimal PATH frozen per session and no `.bashrc`/`.profile` sourced; on this VM that PATH omits the dirs holding `df`, `ls`, `du`, `find`, `rm`, and `git`, so every diagnostic command fails by bare name. Worked around by hard-coding absolute paths (`/usr/bin/df`, `/bin/ls`, `/usr/bin/du`, `/usr/bin/find`, `/bin/rm`, `/usr/bin/git`) in each call. Simpler if: the VM setup put `/usr/bin` and `/bin` on the PATH the Bash tool inherits (e.g. extend `env.PATH` in `~/.claude/settings.json` beyond `${HOME}/.local/bin:${PATH}`, or set it in the VM's default environment), so scripts and ad-hoc commands can call standard tools by name.
