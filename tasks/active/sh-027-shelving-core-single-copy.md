---
id: sh-027
title: "Collapse shelving_core to a single copy under freecad/shelving/core/"
current_agent: implementer
current_phase: implementation
review_rejections: 0
---

# sh-027: Collapse shelving_core to a single copy under freecad/shelving/core/

## Summary
The repo keeps `shelving_core` in two places today: the source of truth at
repo-root `shelving_core/` and a byte-identical vendored copy at
`freecad/shelving/vendor/shelving_core/`, synced by `tools/vendor-core.sh`
and drift-checked in `pixi run tests`. `shelving_core` is never shipped or
consumed independently of the workbench, so the sync is pure overhead:
every edit to it has to be re-vendored, and every `doc-hygiene` pass has to
hand-pair each file with its vendored twin. This collapses the two into
one copy that lives inside the workbench itself, at
`freecad/shelving/core/`, and deletes the vendoring machinery outright.

## Status
- [x] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] `shelving_core/` no longer exists at the repo root. Its modules
      (`layout.py`, `solver.py`, `expand.py`, `materials.py`, `scan.py`,
      `svg.py`, `geometry.py`, `__init__.py`) live at
      `freecad/shelving/core/`; its tests live at
      `freecad/shelving/core/tests/`, a one-to-one rename, not a merge into
      the repo-root `tests/` directory.
- [ ] `freecad/shelving/vendor/` does not exist. `tools/vendor-core.sh` does
      not exist. `tools/run-tests.sh` no longer runs a
      `vendor-core.sh --check` step.
- [ ] Every module under `freecad/shelving/core/` imports its own siblings
      via fully-qualified `freecad.shelving.core.X` imports — not the old
      bare `shelving_core.X`, and not the relative `.X` imports the dual-copy
      setup required as a stopgap.
- [ ] `freecad/shelving/core/tests/test_relative_intra_package_imports.py`
      does not exist. Its entire justification (keeping a second,
      simultaneously-importable copy self-consistent) no longer applies
      once there is one copy.
- [ ] `freecad/shelving/core/tests/test_no_freecad.py` still exists,
      retargeted to the new package location, and still passes.
- [ ] Every consumer outside the moved package imports from
      `freecad.shelving.core`, not `shelving_core`:
      `freecad/shelving/default_catalog.py`, `freecad/shelving/__init__.py`'s
      docstring, `tools/freecad_scan_smoke.py`, `tools/layout_demo.py`. If
      `spikes/plain_planks/` still exists at implementation time (it should
      not — see Frontier Advice's sequencing note), update its imports too:
      `carcass_model.py`, `freecad_spike.py`, `general_model.py`, `scan.py`,
      `test_general_model.py`, `test_scan.py`.
- [ ] `pyproject.toml`'s `[tool.hatch.build.targets.wheel]` `packages` lists
      `freecad`, not `shelving_core`, so `import freecad.shelving.core...`
      resolves the same way `import shelving_core` did today for
      non-pytest script invocations (`tools/layout_demo.py`,
      `tools/freecad_scan_smoke.py`). `[tool.mypy]`'s `files` list and the
      vendor-path `exclude`/override block are retargeted to the new
      location; the vendor-specific override is deleted outright, since
      there is no second copy left to skip.
- [ ] `pixi.toml`'s comments referencing `shelving_core` by its old location
      are updated to match; fix the stale `shelving_core/tests/test_schema.py`
      reference in passing (that file no longer exists, from an earlier,
      unrelated cleanup).
- [ ] `README.md`'s Tests section no longer lists a "vendored-core drift
      check" among what `pixi run tests` covers.
- [ ] `docs/manual-qa.md`'s "link the whole repo, not just
      `freecad/shelving/`" note no longer cites `shelving_core` living only
      at the repo root, or an unlanded "vendored-core rework," as its
      reason. Confirm whether linking the whole repo is still necessary
      (check where `package.xml` lives) and reword the note's stated reason
      accordingly; do not just delete the note without checking.
- [ ] `docs/architecture.md` and `docs/parametric-model-evaluation.md` are
      NOT touched by this task. Both are frozen historical records (the
      first explicitly describes the pre-M4 design per `README.md`'s own
      pointer; the second is an evaluation doc that states nothing in it is
      a decision of record). Editing either to reflect the new layout would
      misrepresent what was true at the time each was written.
- [ ] `mypy --strict` clean over every changed file.

## Frontier Advice

SEQUENCING, recommended, not enforced by `blocked_by`. Wait for `sh-016`
(M6) to land before starting this task. `spikes/plain_planks/` imports
top-level `shelving_core` directly in six files, and M6 deletes
`spikes/` outright (`docs/roadmap.md` § M6, which also deletes
`tests/test_spike_importable.py`, the guard that exists only to protect
those imports). Starting this task first means updating those six files'
imports only to delete them shortly after. This task's own code does not
require `sh-016`'s output, so no hard `blocked_by` is set, but check
whether `spikes/plain_planks/` still exists before starting; if it does,
`sh-016` likely has not landed yet and it is worth confirming with the user
before proceeding.

THE MOVE ITSELF. `git mv shelving_core freecad/shelving/core` preserves
history; do the equivalent for `shelving_core/tests/` landing at
`freecad/shelving/core/tests/`. Every internal cross-module import inside
the moved package (e.g. `expand.py` importing `layout.py`) becomes
`from freecad.shelving.core.layout import Board`-style, fully qualified,
per the settled design — not `from .layout import Board`, even though
that would also work; the relative-import convention was a deliberate,
now-unnecessary stopgap and reverting it is itself a Must Have, not just
a side effect of the move.

WHY THE RELATIVE-IMPORT TEST GOES AWAY. `test_relative_intra_package_imports.py`
existed specifically because an absolute self-import
(`from shelving_core.layout import Board`) resolves against whichever
`shelving_core` happens to be first on `sys.path`, not necessarily the
copy the importing file lives in, when two copies are simultaneously
importable, which caused a real "two class identities" bug
(`friction-001`, already fixed by that convention). Once there is exactly
one copy, that risk cannot recur; the test would just be asserting a
now-meaningless constraint, so delete it along with the convention it
enforced.

PACKAGING MECHANICS, not a preference, a consequence of the location
choice. `tools/layout_demo.py` and `tools/freecad_scan_smoke.py` resolve
their imports today via the editable pip install
(`pyproject.toml`'s `packages = ["shelving_core"]`), not via pytest's
rootdir path insertion, which only covers pytest-collected files.
`tools/freecad_scan_smoke.py` self-invokes pytest, but its own top-level
imports run when `freecadcmd` first execs it, before `pytest.main()` is
ever called, so pytest's own path handling is not yet in play at that
point either; the same packaging concern applies to it as to any other
`freecadcmd`-run script. Switch `packages` to `["freecad"]` so
`freecad.shelving.core...` resolves the same way for these non-pytest
script invocations. Verify this by actually running both scripts directly
(`python3 tools/layout_demo.py`, `freecadcmd tools/freecad_scan_smoke.py`,
not just `pytest`), since a pytest-only check would not catch this class
of breakage.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python already governs this
codebase throughout; no new bare `Any` or bare containers introduced by
the move. `mypy --strict` clean. Shell stays simple applies to any edits
inside `tools/run-tests.sh`/`tools/vendor-core.sh`'s deletion; this task
removes shell, it does not add any.

## Execution Plan

This whole task is one deferred-verification unit
(`.claude/docs/pipeline.md` § Deferred verification): nothing is
meaningfully testable until the move, the import updates, and the
packaging config are all in place together, so `pixi run tests` is
required green once, after the last step, not after each one.

- [ ] **Step 1** (`shelving_core/` → `freecad/shelving/core/`): Move the
      package and its tests via `git mv`. Rewrite every internal
      cross-module import to the fully-qualified `freecad.shelving.core.X`
      form. Delete `test_relative_intra_package_imports.py`. Retarget
      `test_no_freecad.py` to the new package location.
- [ ] **Step 2** (`freecad/shelving/vendor/`, `tools/vendor-core.sh`,
      `tools/run-tests.sh`): Delete the vendor tree and the sync script.
      Remove the `vendor-core.sh --check` step from `run-tests.sh`.
- [ ] **Step 3** (`freecad/shelving/default_catalog.py`,
      `freecad/shelving/__init__.py`, `tools/freecad_scan_smoke.py`,
      `tools/layout_demo.py`, and `spikes/plain_planks/`'s six files if
      still present): Update every remaining `shelving_core` import to
      `freecad.shelving.core`.
- [ ] **Step 4** (`pyproject.toml`, `pixi.toml`): Switch the wheel
      `packages` target and retarget the `mypy` config per Frontier
      Advice's packaging note. Update `pixi.toml`'s stale comments,
      including the `test_schema.py` reference.
- [ ] **Step 5** (`README.md`, `docs/manual-qa.md`): Update the Tests
      section and the "link the whole repo" note per the Must Haves above.
      Do not touch `docs/architecture.md` or
      `docs/parametric-model-evaluation.md`.
