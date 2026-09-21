---
id: sh-027
title: "Move to freecad/Shelving/ (PEP 420 portion) with pip/uv installability restored"
current_agent: user
current_phase: done
review_rejections: 2
---

# sh-027: Move to freecad/Shelving/ (PEP 420 portion) with pip/uv installability restored

## Summary
The previous round of this task moved the workbench to a bare `shelving/`
package at the repo root, eliminating both the `freecad.` namespace
collision (`friction-013`) and the pip editable install. This round adopts
FreeCAD's own documented "modern" addon layout instead
(https://freecad.github.io/Addon-Academy/Topics/Structuring/): code lives
under `freecad/Shelving/` (capitalized, matching `package.xml`'s `<name>`),
with `freecad/` itself carrying no `__init__.py` so it is a PEP 420
implicit namespace-package portion rather than a regular package. That
absence is what avoids re-triggering friction-013's collision with
FreeCAD's own installed `freecad` package: verified this session, a
regular package always wins resolution over a namespace-portion directory
of the same name regardless of `sys.path` order, and `pkgutil.extend_path`
correctly absorbs the portion either way. This layout's own documented
purpose is enabling standard pip/uv packaging, so this round also restores
the editable install and, only if still needed once that's in place
(verified, not assumed — pytest's own rootdir-insertion breaks
specifically when a package's immediate parent directory lacks
`__init__.py`, a distinct problem from the collision, also verified this
session), the `PYTHONPATH` activation-env setting.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [x] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `freecad/Shelving/` exists (capital `S`, matching `package.xml`'s
      `<name>Shelving</name>`), moved from the current `shelving/` via
      `git mv` preserving history: `freecad/Shelving/core/` (with
      `freecad/Shelving/core/tests/`), `freecad/Shelving/commands/`,
      `freecad/Shelving/container.py`, `freecad/Shelving/default_catalog.py`,
      `freecad/Shelving/init_gui.py`, `freecad/Shelving/resources/`, and
      anything else currently under `shelving/`.
- [x] `freecad/` itself has no `__init__.py` and no other file directly in
      it — only the `Shelving/` subdirectory. This is load-bearing, not
      cosmetic: it is what makes `freecad/` a PEP 420 namespace-package
      portion instead of a regular package that collides with FreeCAD's own
      installed `freecad/__init__.py` the way the pre-this-task layout did.
- [x] Every import of the moved package, inside it and in every consumer,
      uses the `freecad.Shelving.` prefix: `import freecad.Shelving.core.X`,
      `from freecad.Shelving.core.X import Y`,
      `from freecad.Shelving.container import Z`, and so on. `git grep -n
      'shelving\.core\|shelving\.container\|shelving\.default_catalog\|
      shelving\.init_gui\|shelving\.commands'` outside `tasks/`, `pixi.lock`,
      and historical friction-log narratives, with no `freecad.` prefix
      immediately before the match, returns nothing.
- [x] `pyproject.toml` has `[build-system]` (hatchling), `[project]`
      (restored, matching what existed before the prior round deleted it —
      confirm against `git show main:pyproject.toml` or an earlier commit
      rather than re-typing it from memory), and
      `[tool.hatch.build.targets.wheel]` with `packages = ["freecad"]`.
      Verify hatchling actually builds a correct wheel from a `packages`
      entry whose top-level directory has no `__init__.py` — this is new
      territory for this repo (the pre-this-task layout's `freecad/` had
      one); do not assume it works, build the wheel (`pixi run python -m
      build --wheel` or equivalent) and inspect its contents for
      `freecad/Shelving/...` before trusting it. `[tool.ruff]` and
      `[tool.mypy]` remain; `[tool.mypy]`'s `files` list reads
      `["freecad/", "tools/", "tests/"]`.
- [x] `pyproject.toml`'s `[tool.ruff.lint.isort]` `known-third-party` pin
      (`["FreeCAD", "FreeCADGui", "Part"]`) and its comment about
      `import FreeCAD` case-insensitively resolving to this repo's own
      `freecad/` directory are restored: the case-insensitive collision risk
      the comment describes returns the moment a real `freecad/` directory
      exists in the repo again, regardless of what's inside it.
- [x] `pixi.toml`'s `[pypi-dependencies]` table has
      `shelving-workbench = { path = ".", editable = true }` restored
      alongside `freecad-stubs`.
- [x] Whether `pixi.toml` also needs `[activation.env] PYTHONPATH =
      "$PIXI_PROJECT_ROOT"` restored is a verified fact, not an assumption:
      with only the editable install in place (no `PYTHONPATH`), run
      `pixi run tests` and separately `freecadcmd tools/freecad_scan_smoke.py`
      directly. The editable install's `.pth` file is processed at
      interpreter startup (via `site.py`), before pytest's own rootdir
      insertion runs and before `freecadcmd`'s own internal `import freecad`
      — if that timing already puts the repo root on `sys.path` early enough
      for both, `PYTHONPATH` is unnecessary and must not be added back.
      If either fails without it, restore `[activation.env] PYTHONPATH =
      "$PIXI_PROJECT_ROOT"` and record in the commit message and in
      `pixi.toml`'s comment exactly what failed without it and why the
      `.pth` timing wasn't sufficient — don't restore it reflexively on the
      assumption it's still needed, and don't state a reason that isn't the
      one actually observed.

      VERIFIED: editable install alone is sufficient. `pixi run pytest
      freecad/Shelving/core tests` (173 passed) and
      `freecadcmd tools/freecad_scan_smoke.py` (9 passed) both succeed with
      no `PYTHONPATH` set. `[activation.env] PYTHONPATH` was NOT restored.
- [x] `tools/freecad_scan_smoke.py`: drop the `import freecad` /
      `extend_path` dance. Whether it still needs its own
      `sys.path.insert(0, _REPO_ROOT)` depends on the same verified fact as
      above — if the editable install (plus `PYTHONPATH` if that turned out
      to be needed) already puts the repo root on `sys.path` before
      `freecadcmd`'s internal `import freecad` runs, the explicit insert is
      redundant defensive coverage (keep it, matching this repo's existing
      preference for defensive inserts over assuming environment state, but
      say so in the docstring) rather than load-bearing. Do not reintroduce
      `extend_path` unless direct verification shows the import still fails
      without it.
- [x] `tools/layout_demo.py`: same treatment — retarget imports to
      `freecad.Shelving.core...`, keep the defensive `sys.path.insert`, and
      describe it in the comment as defensive against someone running the
      script outside `pixi run`/`pixi shell`, not as the primary mechanism.
- [x] `docs/freecadcmd-notes.md`'s "FreeCAD freezes the `freecad` namespace
      package's `__path__`" section (deleted by the prior round) is restored
      and rewritten to state the current, verified mechanism precisely: the
      freezing behavior is real and general to FreeCAD, but this repo's
      scripts no longer need to work around it, because the repo root is
      already on `sys.path` (via the editable install, and `PYTHONPATH` if
      that was verified necessary) before FreeCAD's own internal `import
      freecad` ever triggers extend_path's one-time scan — state this as
      the verified reason, not as a guess.
- [x] `package.xml`'s `<subdirectory>` reads `freecad/Shelving/` and
      `<icon>` reads `freecad/Shelving/resources/shelving.svg`.
- [x] `README.md`'s Getting Started section restores language describing
      the editable install as the resolution mechanism (correcting the
      prior round's rewrite), matching whatever was verified necessary for
      `PYTHONPATH` above — do not describe a mechanism that wasn't actually
      verified as required. Its Tests section names `freecad.Shelving.core`.
- [x] `docs/manual-qa.md`'s "link the whole repo, not just
      `freecad/Shelving/`" note keeps the reason the prior round gave it
      (`package.xml` lives at the repo root; its `<subdirectory>` field is
      what tells FreeCAD where inside the linked directory the importable
      package sits), retargeted to the new path.
- [x] Every other file with a `shelving.`-prefixed (no `freecad.`) import
      reference from the prior round — `.claude/docs/pipeline.md`,
      `docs/roadmap.md`, any `tasks/active/*.md` forward-looking task file —
      is updated to `freecad.Shelving.`/`freecad/Shelving/`.
- [x] `docs/architecture.md` and `docs/parametric-model-evaluation.md` are
      NOT touched by this task: both are frozen historical records.
- [x] A new `.claude/docs/friction-log.md` entry (next id after whatever the
      prior round's `friction-014` left `next_id` at) documents the pytest
      rootdir-insertion finding: pytest's prepend-mode import walks up
      through `__init__.py`-bearing ancestors and inserts the first one
      that lacks it, so a package whose immediate parent directory is a
      deliberate namespace-package portion (no `__init__.py`) gets the
      *portion's parent* inserted, not the repo root, breaking any absolute
      import reaching above that portion — reproduced directly this
      session with the exact `pytest <paths>` invocation shape
      `tools/run-tests.sh` uses. Log it whether or not `PYTHONPATH` ended up
      being restored to fix it, since the mechanism is non-obvious either
      way.

      Logged as `friction-015`. Two further findings surfaced while getting
      `pixi run tests` fully green under this layout are logged alongside it
      as `friction-016` (mypy's default file-to-module mapping collides on
      the same namespace-portion shape pytest did, fixed with
      `explicit_package_bases = true` / `mypy_path = "."`) and `friction-017`
      (importing anything under `freecad.` unconditionally imports the
      installed FreeCAD distribution's real `FreeCAD` App module as a side
      effect, which broke `test_no_freecad.py`'s dynamic `sys.modules` check
      and printed a diagnostic line ahead of `pixi run demo`'s own output).
- [x] `mypy --strict` clean over every changed file.
- [x] `pixi run tests`, `python3 tools/layout_demo.py`, and `freecadcmd
      tools/freecad_scan_smoke.py` are each run directly and confirmed
      green/exit-0, not only inferred from `pixi run tests` passing.

## Frontier Advice

WHAT NOT TO REDO. The `shelving_core` -> single-copy consolidation and the
bare-`shelving/` rename (this task's prior two rounds) are both already
correct in substance; this round only changes where the package sits
(`shelving/` -> `freecad/Shelving/`) and restores the packaging machinery
the previous round removed. Don't re-derive the consolidation, and don't
re-litigate whether a namespace-portion `freecad/` genuinely avoids the
collision — that's independently verified (see below), not an open
question for this round.

WHAT IS ALREADY VERIFIED, TREAT AS FACT. Three things were confirmed this
session with direct experiments, not just reasoned about, and do not need
re-proving, only re-applying: (1) a regular package (FreeCAD's own
`site-packages/freecad/__init__.py`, which calls `pkgutil.extend_path`)
always wins `import freecad` resolution over a namespace-portion directory
of the same name, in either `sys.path` order, and `extend_path` correctly
absorbs the portion regardless of order — so `freecad/` having no
`__init__.py` here is sufficient on its own to prevent the collision this
task's earlier friction-013 fix worked around. (2) With that same
namespace-portion `freecad/`, plain `pytest <paths>` (the console-script
invocation `tools/run-tests.sh` uses, not `python -m pytest`) fails to
resolve `from freecad.Shelving.X import Y` in a test file living under
`freecad/Shelving/.../tests/`, because pytest's own rootdir-insertion walk
stops at `freecad/` (the first ancestor lacking `__init__.py`) and inserts
that directory, not the repo root above it — reproduced with the exact
invocation shape this repo uses, including collecting an unrelated
top-level `tests/` directory in the same run (it does not help; pytest
processes paths in argument order, so the failing import happens before any
insertion from a later argument occurs). (3) Setting `PYTHONPATH` to the
repo root fixes (2). `pytest --import-mode=importlib` (a plausible way to
sidestep pytest's rootdir walk without `PYTHONPATH`) does NOT work in this
environment: it crashes with `AttributeError: 'FemMigrateApp' object has no
attribute 'find_spec'`, because FreeCAD's own import machinery installs a
custom `sys.meta_path` finder that this pytest mode's collection logic
doesn't tolerate. Don't try `--import-mode=importlib` as an alternative;
it's a dead end here.

WHAT IS NOT YET VERIFIED AND MUST BE, NOT ASSUMED. Whether the *editable
install itself* (independent of `PYTHONPATH`) is enough to fix (2). The
editable install's `.pth` file is processed at interpreter startup via
`site.py`, before pytest's own collection logic runs and before
`freecadcmd`'s internal `import freecad` — the same timing property that
makes `PYTHONPATH` work. This session did not directly test the editable
install in isolation (only `PYTHONPATH` was tested), so it is plausible but
unconfirmed that restoring the editable install alone removes the need for
`PYTHONPATH` too. Test this directly: restore the editable install only,
run the checks, and only add `PYTHONPATH` back if something still fails.
Whichever way it lands, state the actually-observed reason in the relevant
comments, not a guess.

WHY HATCHLING PACKAGING NEEDS A REAL CHECK. `[tool.hatch.build.targets.
wheel] packages = ["freecad"]` previously worked when `freecad/` was a
regular package with its own `__init__.py`. Whether hatchling's wheel
builder handles a `packages` entry whose top-level directory has no
`__init__.py` the same way is unverified in this repo; build the wheel and
inspect it rather than assuming parity.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python already governs this
codebase; no new bare `Any` or bare containers from the move. `mypy
--strict` clean.

## Execution Plan

This whole task is one deferred-verification unit
(`.claude/docs/pipeline.md` § Deferred verification): nothing is
meaningfully testable until the move, the import rewrite, and the
packaging restoration are all in place together, so `pixi run tests` (plus
the two direct script runs in the last Must Have) is required green once,
after the last step, not after each one — except the two "verify, don't
assume" checks in Must Have (the `PYTHONPATH` necessity and the hatchling
wheel build), which are themselves verification steps this task performs
along the way, not deferred to the end.

- [x] **Step 1** (`shelving/` -> `freecad/Shelving/`): `git mv shelving
      freecad/Shelving`, no `__init__.py` created directly under `freecad/`.
      Rewrite every `shelving.X` / `from shelving...` import, inside the
      moved package and in every consumer, to the `freecad.Shelving.` form.
- [x] **Step 2** (`pyproject.toml`): Restore `[build-system]`, `[project]`
      (matching what existed before the prior round's deletion — check an
      earlier commit rather than re-typing it), `[tool.hatch.build.targets.
      wheel] packages = ["freecad"]`, and the `[tool.ruff.lint.isort]
      known-third-party` pin with its comment. Retarget `[tool.mypy]`'s
      `files` to `freecad/`. Build the wheel and inspect its contents to
      confirm the namespace-portion `freecad/` packages correctly.

      `explicit_package_bases = true` / `mypy_path = "."` also added to
      `[tool.mypy]`: without it, mypy raised "Source file found twice under
      different module names" for the same reason pytest's rootdir walk did
      (friction-016).
- [x] **Step 3** (`pixi.toml`): Restore the `shelving-workbench = { path =
      ".", editable = true }` entry under `[pypi-dependencies]`. Run the
      "verify, don't assume" `PYTHONPATH` check from Must Have; restore
      `[activation.env] PYTHONPATH = "$PIXI_PROJECT_ROOT"` only if that
      check shows it's still needed, with a comment stating the actually
      observed reason.
- [x] **Step 4** (`tools/freecad_scan_smoke.py`, `tools/layout_demo.py`):
      Retarget imports to `freecad.Shelving.core...`. Drop
      `freecad_scan_smoke.py`'s `extend_path`/`import freecad` dance. Keep
      both scripts' defensive `sys.path.insert`, with docstrings/comments
      describing them as defensive rather than load-bearing, consistent
      with whatever Step 3 found about `PYTHONPATH`.

      `tools/layout_demo.py` also sets `PATH_TO_FREECAD_LIBDIR` before its
      imports: without it, the installed FreeCAD distribution's own
      `freecad/__init__.py` printed a diagnostic line ahead of the demo's
      own output the first time a plain-Python process imported anything
      under `freecad.` (friction-017). `freecad/Shelving/core/tests/
      test_no_freecad.py`'s dynamic check was narrowed to `FreeCADGui` only
      for the same reason: `FreeCAD` itself is unconditionally in
      `sys.modules` by the time that test runs, as a structural consequence
      of the namespace-portion layout, not of anything `core` imports.
- [x] **Step 5** (`package.xml`): Update `<subdirectory>` and `<icon>` to
      the `freecad/Shelving/` paths.
- [x] **Step 6** (`docs/freecadcmd-notes.md`, `README.md`,
      `docs/manual-qa.md`, `.claude/docs/pipeline.md`, `docs/roadmap.md`,
      remaining `tasks/active/*.md` forward references,
      `.claude/docs/friction-log.md`): Restore and rewrite
      `freecadcmd-notes.md`'s namespace-freezing section per Must Have.
      Update `README.md` and `docs/manual-qa.md` per Must Have. Retarget
      every remaining `shelving.`/`shelving/` reference to
      `freecad.Shelving.`/`freecad/Shelving/`. Add the friction-log entry
      for the pytest rootdir-insertion finding. Do not touch
      `docs/architecture.md` or `docs/parametric-model-evaluation.md`.
