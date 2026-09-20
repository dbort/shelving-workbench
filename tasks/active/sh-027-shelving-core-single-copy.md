---
id: sh-027
title: "Rename freecad/shelving/ to shelving/ and drop the pip editable install"
current_agent: implementer
current_phase: implementation
review_rejections: 2
---

# sh-027: Rename freecad/shelving/ to shelving/ and drop the pip editable install

## Summary
This repo's Python package currently lives at `freecad/shelving/`, following
the `freecad.<name>` namespace convention some FreeCAD tooling docs suggest,
and resolves in dev/test tooling via a `pip install -e .` editable install
plus a `PYTHONPATH` activation-env setting added to work around this
checkout's `freecad` package colliding with FreeCAD's own installed
`freecad` namespace package. Neither convention is required by FreeCAD's own
workbench-creation docs or by real-world workbenches, and neither matches how
a real FreeCAD install actually loads this workbench (from a `Mod/` symlink
via `package.xml`'s `<subdirectory>`, no pip involved). This moves the
package to `shelving/` at the repo root, eliminating the namespace collision
at its source rather than working around it, and drops the editable install
and its `PYTHONPATH` workaround entirely, since pytest's own rootdir path
insertion and each script's own explicit `sys.path` insert are already
sufficient once nothing needs to resolve `freecad.shelving`.

## Status
- [x] Planning
- [x] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] `freecad/` does not exist anywhere in the repo (neither
      `freecad/__init__.py` nor any subdirectory). The package that lived at
      `freecad/shelving/` now lives at `shelving/`, moved via `git mv`
      preserving history: `shelving/core/` (with `shelving/core/tests/`),
      `shelving/commands/`, `shelving/container.py`,
      `shelving/default_catalog.py`, `shelving/init_gui.py`,
      `shelving/resources/`, and anything else that lived under
      `freecad/shelving/`.
- [ ] Every import of the moved package, inside it and in every consumer,
      uses the `shelving.` prefix, not `freecad.shelving.`:
      `import shelving.core.X`, `from shelving.core.X import Y`,
      `from shelving.container import Z`, and so on. `git grep -n
      'freecad\.shelving\|freecad/shelving'` outside `tasks/`, `pixi.lock`,
      and `.claude/docs/friction-log.md`'s historical narrative of
      `friction-009` returns nothing.
- [ ] `pyproject.toml` has no `[build-system]`, `[tool.hatch...]`, or
      `[project]` table. Nothing in this repo is pip-installed, built as a
      wheel, or registered as a Python package via `pyproject.toml`; the
      file's sole remaining job is holding `[tool.ruff]` and `[tool.mypy]`
      configuration. `[tool.mypy]`'s `files` list reads `["shelving/",
      "tools/", "tests/"]`.
- [ ] `pixi.toml` has no `[activation.env]` table and no
      `shelving-workbench = { path = ".", editable = true }` entry under
      `[pypi-dependencies]`. `freecad-stubs` remains under
      `[pypi-dependencies]`; confirm `pixi install` still resolves with it
      as the only entry there. `pixi.toml`'s comments describe the actual
      resolution mechanism (pytest's own rootdir insertion, plus each
      `tools/*.py` script's own `sys.path` insert), not the removed
      editable install or `PYTHONPATH` workaround.
- [ ] `tools/freecad_scan_smoke.py` no longer imports the `freecad`
      namespace package or calls `extend_path`; it resolves `shelving.*`
      imports via its existing `sys.path.insert(0, _REPO_ROOT)` alone, and
      its module docstring is updated to match (the "FreeCAD freezes the
      `freecad` namespace package's `__path__`" problem does not apply to a
      plain top-level package).
- [ ] `tools/layout_demo.py`'s `sys.path.insert(0, _REPO_ROOT)` and its
      imports are retargeted to `shelving.core...`; its docstring/comment no
      longer describes the editable install as the resolution path, since
      the explicit insert is now the only mechanism, not a defensive
      backstop against a losing race.
- [ ] `docs/freecadcmd-notes.md`'s "FreeCAD freezes the `freecad` namespace
      package's `__path__`" section is deleted: nothing in this repo imports
      anything under FreeCAD's own `freecad` namespace package once
      `freecad_scan_smoke.py`'s `extend_path` call is gone, so the finding
      has no code left to document.
- [ ] `package.xml`'s `<subdirectory>` reads `shelving/` and `<icon>` reads
      `shelving/resources/shelving.svg`.
- [ ] `README.md`'s Getting Started section states the actual resolution
      mechanism instead of the editable install: `shelving/` is a plain
      package (its own `__init__.py`, no `__init__.py` at the repo root
      above it), so pytest's prepend-mode rootdir walk inserts the repo
      root on `sys.path` for the test suite with no packaging step, and
      `tools/*.py` scripts carry their own explicit `sys.path` insert. Its
      Tests section names `shelving.core`, not `freecad.shelving.core`.
- [ ] `docs/manual-qa.md`'s "link the whole repo, not just
      `freecad/shelving/`" note (renamed to `shelving/`) states its current
      reason: `package.xml` lives at the repo root, and its `<subdirectory>`
      field is what tells FreeCAD where inside the linked directory the
      importable workbench package sits, so linking only `shelving/` would
      drop `package.xml` (and the Addon-Manager-facing metadata it carries)
      from the loaded tree.
- [ ] `pyproject.toml`'s `[tool.ruff.lint.isort]` `known-third-party` pin
      and its comment (about `import FreeCAD` case-insensitively resolving
      to this repo's own `freecad/` directory) are re-verified against the
      new layout: `shelving/` does not case-insensitively collide with
      `FreeCAD`, `FreeCADGui`, or `Part` the way `freecad/` did. If
      `ruff check .` / `ruff format --check .` pass cleanly without the
      pin, remove it and its now-inapplicable comment; if some other reason
      still requires it, correct the comment to state that reason instead
      of the removed one.
- [ ] Every other file the pre-move `git grep -n 'freecad\.shelving\|
      freecad/shelving'` found (`.claude/docs/pipeline.md`,
      `docs/roadmap.md`, and any `tasks/active/*.md` forward-looking task
      file not already updated) has its references updated to
      `shelving.`/`shelving/`, except the two frozen documents below.
- [ ] `docs/architecture.md` and `docs/parametric-model-evaluation.md` are
      NOT touched by this task: both are frozen historical records (the
      first explicitly describes the pre-M4 design per `README.md`'s own
      pointer; the second is an evaluation doc that states nothing in it is
      a decision of record).
- [ ] `mypy --strict` clean over every changed file.
- [ ] Beyond `pixi run tests` passing, `python3 tools/layout_demo.py` and
      `freecadcmd tools/freecad_scan_smoke.py` are each run directly (not
      only via `pixi run tests`, which already runs the latter) to confirm
      the plain `sys.path` insert resolves `shelving.*` with no packaging
      step at all — a pytest-only check would not catch a regression in
      either script's own import resolution.

## Frontier Advice

WHAT NOT TO REDO. This task's first two rounds (`6cf69a1`, `d666f0f`) already
did the correct `shelving_core/` -> `freecad/shelving/core/` consolidation:
single copy, fully-qualified sibling imports, the relative-import test
deleted, the vendor tree and `vendor-core.sh` removed. Round 2's rejection
(`tasks/active/sh-027-REVIEW.md`) was narrowly about the `PYTHONPATH`
friction-013 fix added in `d666f0f`, not about the consolidation. Do not
re-derive or second-guess the consolidation; only the `freecad.` -> bare
rename and the packaging removal are new work here.

F1/F2 ARE MOOT, NOT TO BE FIXED AS STATED. Round 2's two blocking findings
both concern the `[activation.env] PYTHONPATH` mechanism this task deletes
outright: F1 asked for a regression test proving the setting works, F2
flagged a stale comment about it. Deleting the mechanism resolves both by
removing what they were about. Do not add the test F1 describes; it would
assert nothing, since the setting it exercises no longer exists.

WHY THE RENAME REMOVES THE NEED FOR PYTHONPATH. Friction-013 existed because
this checkout's `freecad/__init__.py` and the conda environment's own
`freecad` package (FreeCAD's Python bindings shim,
`site-packages/freecad/__init__.py`) share the same top-level name and race
on `sys.path`. FreeCAD's own source comments that file `# TO NOT OVERWRITE
THIS FILE, NO OTHER MODULE IS ALLOWED TO PROVIDE A freecad/__init__.py
FILE`; this checkout's `freecad/__init__.py`, before this task, violates
that contract directly. Renaming to `shelving/` does not reorder the race,
it removes the collision: nothing else on `sys.path` is named `shelving`.

WHY NO PACKAGING STEP IS NEEDED AT ALL. `pytest shelving/core tests`
already gets the repo root at `sys.path[0]` for free: `shelving/` and every
directory below it that pytest collects from carries `__init__.py`, and the
repo root itself does not, so pytest's own prepend-mode rootdir walk stops
there and inserts it, the same mechanism that already worked for
`freecad/shelving/core` before this move (round 2's review confirmed this
explicitly). `tools/layout_demo.py` and `tools/freecad_scan_smoke.py` are
not pytest-collected, so they keep their own explicit
`sys.path.insert(0, _REPO_ROOT)` — `layout_demo.py` already has one
(previously described as a defensive backstop against the editable
install's losing race; it becomes the sole mechanism here) and
`freecad_scan_smoke.py`'s existing insert can drop its accompanying
`extend_path`/`import freecad` dance entirely, since that dance only
mattered for resolving something living inside FreeCAD's own frozen
`freecad` namespace package, which `shelving` is not part of.

PACKAGING FILES. `pyproject.toml` currently exists to drive the wheel build
the editable install used, and to hold `[tool.ruff]`/`[tool.mypy]` config.
The former has no reason to exist once nothing pip-installs this project:
delete `[build-system]`, `[tool.hatch.build.targets.wheel]`, and
`[project]` (its metadata duplicates `package.xml`, now the sole
authoritative source for it), keeping only `[tool.ruff]` and `[tool.mypy]`.
`pixi.toml`'s `[pypi-dependencies]` table loses its
`shelving-workbench = { path = ".", editable = true }` entry; its
`[activation.env]` table is deleted outright, since nothing else in the
manifest uses it.

MANUAL-QA'S LINK NOTE GETS A NEW, CORRECT REASON, NOT A DELETION.
`docs/manual-qa.md`'s existing "link the whole repo, not just
`freecad/shelving/`" note was written for the old dual-copy `shelving_core`
reason, already stale as of round 1. Its replacement reason: `package.xml`
lives at the repo root, not inside `shelving/`, and its `<subdirectory>`
field is what tells FreeCAD where inside a linked directory the actual
importable package sits. Link only `shelving/` and FreeCAD's Addon Manager
loses `package.xml` (name, description, icon, license, URLs) even though
the raw Python import might still resolve via the classname. State this
directly; it rests on where the files sit, not on a runtime test this task
performs.

DOCS THAT DESCRIBE THE REMOVED MECHANISM.
`docs/freecadcmd-notes.md`'s "FreeCAD freezes the `freecad` namespace
package's `__path__`" section documents a problem only
`tools/freecad_scan_smoke.py`'s `extend_path` dance ever exercised in this
repo, and this task deletes that dance. Delete the section rather than
reframing it as historical, since it would then describe nothing this
repository's code exercises.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python already governs this
codebase throughout; no new bare `Any` or bare containers introduced by the
move. `mypy --strict` clean. This task removes packaging and shell surface,
it does not add any.

## Execution Plan

This whole task is one deferred-verification unit
(`.claude/docs/pipeline.md` § Deferred verification): nothing is
meaningfully testable until the move, the import rewrite, and the
packaging removal are all in place together, so `pixi run tests` (plus the
two direct script runs in the last Must Have) is required green once,
after the last step, not after each one.

- [ ] **Step 1** (`freecad/shelving/` -> `shelving/`, `freecad/__init__.py`
      deleted): `git mv freecad/shelving shelving`, then `git rm
      freecad/__init__.py` and confirm `freecad/` no longer exists. Rewrite
      every `freecad.shelving.X` / `from freecad.shelving...` import, inside
      the moved package and in every consumer under `shelving/`, `tools/`,
      and `tests/`, to the `shelving.` form.
- [ ] **Step 2** (`tools/freecad_scan_smoke.py`): Drop the `import freecad`
      and `extend_path` call; keep the existing `sys.path.insert(0,
      _REPO_ROOT)`. Retarget its `shelving.*` imports. Rewrite the module
      docstring's explanation of the namespace-package problem, since it no
      longer applies.
- [ ] **Step 3** (`tools/layout_demo.py`): Retarget its `shelving.core...`
      imports. Rewrite the comment above its `sys.path.insert` call: it is
      now the sole resolution mechanism, not a defensive backstop against
      the editable install's `.pth` losing a race.
- [ ] **Step 4** (`pyproject.toml`, `pixi.toml`): Delete `[build-system]`,
      `[tool.hatch.build.targets.wheel]`, and `[project]` from
      `pyproject.toml`, keeping `[tool.ruff]` and `[tool.mypy]` (retarget
      `files` to `shelving/`). Re-verify the `[tool.ruff.lint.isort]`
      `known-third-party` pin per the Must Have above; remove or correct it.
      Delete `pixi.toml`'s `[activation.env]` table and the
      `shelving-workbench` editable entry under `[pypi-dependencies]`;
      update its remaining comments to describe the actual resolution
      mechanism.
- [ ] **Step 5** (`package.xml`): Update `<subdirectory>` and `<icon>` to
      the `shelving/` paths.
- [ ] **Step 6** (`README.md`, `docs/manual-qa.md`,
      `docs/freecadcmd-notes.md`, `docs/roadmap.md`,
      `.claude/docs/pipeline.md`, and any remaining `tasks/active/*.md`
      forward-looking references): Update prose per the Must Haves above.
      Delete `docs/freecadcmd-notes.md`'s namespace-freezing section. Reword
      `docs/manual-qa.md`'s link note with its new reason. Do not touch
      `docs/architecture.md` or `docs/parametric-model-evaluation.md`.
