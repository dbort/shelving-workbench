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

- `2026-09-04` - **`freecad-stubs` types names that do not exist at runtime**:
  the plain-planks spike annotated a `Protocol` with `FreeCAD.Quantity` for a
  `Part::Box`'s `Length`. `mypy --strict` accepted it, but FreeCAD 1.0.0 raised
  `module 'FreeCAD' has no attribute 'Quantity'` when the class body evaluated
  the annotation (the runtime name is `FreeCAD.Units.Quantity`). Worked around
  with `from __future__ import annotations` so the annotations are never
  evaluated. Simpler if: the stubs matched the runtime module layout, or the
  repo's type check had a runtime-import smoke that caught a stub-only name
  before it reached a script.

- `2026-09-04` - **no documented way to get a box's global placement under an
  `App::LinkGroup`**: the spike needed each plank's document-frame corner.
  `getGlobalPlacement` composes only through geo-feature groups, and an
  `App::LinkGroup` is not one, so it silently returns the local placement for a
  Woodworking-style unit (`magicStart` puts its cabinets in a `LinkGroup`).
  Found by testing both container types rather than from any doc; Woodworking
  hits the same wall and hand-rolls `getContainersOffset`. Worked around by
  walking the container chain and multiplying placements in
  `spikes/plain_planks/export_boxes.py`. Simpler if: `getGlobalPlacement`
  composed through link containers too, or the API doc stated which container
  types it honours so the gap was findable without an experiment.

- `2026-09-03` - **no headless signal for GUI rendering**: sh-012's sign-off
  defect was that a `Part::FeaturePython` plank with a valid `Shape` never drew
  in the FreeCAD 1.0.0 GUI, because it had no `ViewProvider` proxy. The fix
  (`PlankViewProvider`) can only be exercised in a real GUI: under `freecadcmd`
  `obj.ViewObject` is `None`, so `pixi run tests` cannot assert
  `ViewObject.isVisible()` or that the view-provider binding took. Worked around
  with a Python-console macro in `docs/manual-qa.md` case 2 that the user runs
  once by hand. Simpler if: `freecadcmd` exposed a minimal `ViewObject` (even a
  headless stub whose `isVisible()` / display-mode wiring could be asserted), or
  there were an offscreen-GUI test mode, so view-provider regressions were caught
  by the merge gate instead of at human sign-off.

- `2026-09-03` - **vendored `shelving_core` splits into two class identities**:
  sh-012's `ShelvingUnit.execute` calls `expand(carcass, ...)`. The Frontier
  Advice said to import `Carcass` / `Leaf` / `expand` from
  `freecad.shelving.vendor.shelving_core.*`, but the vendored `expand.py` /
  `solver.py` are byte-identical to upstream and import their layout classes with
  `from shelving_core.layout import ...` (bare distribution name). In the CI
  environment top-level `shelving_core` is importable, so `expand` type-checks
  its input against `shelving_core.layout.Split` while a carcass built from
  `freecad.shelving.vendor.shelving_core.layout` is a different `Split` class:
  every `isinstance(bay, Split)` misses and all dividers/shelves are dropped with
  no error. Worked around by importing the layout/solver/expand/materials surface
  in `objects/shelving_unit.py` from top-level `shelving_core.*` so the classes
  match what `expand` binds; `plank.py` and `labels.py` keep the vendored import
  (they only touch standalone helpers like `Vec3` / `PlankRole`). Simpler if: the
  vendored copy used relative imports (`from .layout import ...`), or
  `tools/vendor-core.sh` rewrote the intra-package imports to the
  `freecad.shelving.vendor.shelving_core` prefix, so there is one class identity
  regardless of which path a consumer imports.
