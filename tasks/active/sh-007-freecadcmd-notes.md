---
id: sh-007
title: "Document the freecadcmd headless-script contract"
current_agent: implementer
current_phase: planning
review_rejections: 0
---

# sh-007: Document the freecadcmd headless-script contract

## Summary
Three `freecadcmd` behaviors surprised sh-001 and were only found by running
real FreeCAD; all three are handled in code but written down nowhere. M3 and
later milestones write a lot of `freecadcmd`-facing code, so this captures the
contract in `docs/freecadcmd-notes.md`.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `docs/freecadcmd-notes.md` exists and documents these three behaviors, each with a sentence on the consequence and a pointer to the file that handles it:
  1. **`freecadcmd script.py` does not propagate the script's exit status.** `sys.exit(N)`, an uncaught exception, and `os._exit(N)` all yield shell status 0. A smoke or CI script must signal pass/fail with a stdout marker the caller greps for, not with its return code. Handled in `test.sh` (the `--full` tier greps for `shelving workbench import OK`).
  2. **FreeCAD imports its own `freecad` namespace package at startup and freezes its `__path__`.** Importing a checkout-based `freecad.shelving` (not installed on FreeCAD's addon path) needs `freecad.__path__ = extend_path(freecad.__path__, "freecad")` after a `sys.path` insert; a bare `sys.path.insert` alone does not make `freecad.shelving` importable. Handled in `tools/freecad_smoke.py`.
  3. **Under `freecadcmd`, `import FreeCADGui` succeeds and returns a stub module that lacks `Workbench`.** No `ImportError` is raised, so an `except ImportError` guard is not enough; code that subclasses `Gui.Workbench` must also check `hasattr(Gui, "Workbench")` (or `getattr(Gui, "Workbench", None)`). Handled in `freecad/shelving/init_gui.py`.
- [ ] The doc is human-facing prose written to `doc-hygiene`'s rules: states current behavior plainly (no "used to" / "no longer"), explains the *why*/consequence, no throat-clearing openers, no em-dash asides, no marketing adjectives.
- [ ] `docs/architecture.md` gains a one-line pointer to `docs/freecadcmd-notes.md` where it discusses the full / `freecadcmd` test tier or the `freecad_smoke.py` script. No other change to `architecture.md`.
- [ ] The `2026-08-30` `freecadcmd` headless-contract friction-log entry is removed from `.claude/docs/friction-log.md`.
- [ ] No code change. `./test.sh --fast` and `pixi run full` remain green (docs only).

## Frontier Advice

STANDING OBLIGATIONS (`CLAUDE.md`): none apply to a docs-only change; note that
explicitly in the handoff. Writing style is `doc-hygiene`'s "File content"
rules (`CLAUDE.md` § Writing style by destination): full prose, why-focused, no
filler adverbs, no em-dash asides, identifier-first where it names one.

SCOPE: this is documentation of behavior that already exists in the codebase.
Do not change `test.sh`, `tools/freecad_smoke.py`, or
`freecad/shelving/init_gui.py`. Verify each claim against the actual code before
writing it down (line pointers are welcome but keep them as "see
`path/to/file`" rather than brittle line numbers).

`docs/` placement: this is human-facing prose and IS swept by `doc-hygiene`
(unlike `.claude/docs/`). Keep it short, a page at most.

FRICTION LOG: delete the `2026-08-30` `freecadcmd` entry in the commit that
lands the doc.

## Execution Plan

- [ ] **Step 1** (`docs/freecadcmd-notes.md`): Write the doc per the Must Have. Confirm each of the three behaviors against `test.sh`, `tools/freecad_smoke.py`, and `freecad/shelving/init_gui.py` before describing it; cite each handling file by path.

- [ ] **Step 2** (`docs/architecture.md`): Add the one-line pointer to the new doc near the `freecadcmd` / full-tier discussion. No other edit.

- [ ] **Step 3** (`.claude/docs/friction-log.md`): Remove the `2026-08-30` `freecadcmd` headless-contract entry.

- [ ] **Step 4** (verification, no new files): `./test.sh --fast` and `pixi run full` still green (docs-only change). Re-read `docs/freecadcmd-notes.md` against the three source files for accuracy.
