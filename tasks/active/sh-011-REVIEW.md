# sh-011 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green end to end on `sh-011` (check_lock_paths, ruff
check + format, `mypy` strict over 27 files including the five new
`freecad/shelving/` modules, shellcheck, vendor drift, 146 pytest, workflow
lint, both `freecadcmd` smokes; `APART_PROXY_EXECUTE: no` then `shelving
object layer OK`). `shelving_core/` and `freecad/shelving/vendor/` are
untouched, the scope guard holds, the lock is repo-relative (`- pypi: ./`)
with `freecad-stubs` resolved for both `linux-64` and `linux-aarch64`, and
there is no `# type: ignore`, no `Any`, and no blanket `ignore_errors` /
`ignore_missing_imports` anywhere in the diff. One blocking finding stands
between that and approval.

## Blocking findings

- **F1: the probe's recorded findings outrun what the probe actually
  checks** (`docs/freecadcmd-notes.md:61-66`,
  `tools/freecad_object_smoke.py:121-142`): the Must Have requires the notes
  section be "written from what the probe actually prints, not assumed", and
  `_probe_apart_execute` only ever exercises one path: `part.Proxy =
  recorder` raises `AttributeError`, `observed = False`, done. The doc's
  second bullet (the three-argument `doc.addObject("App::Part", name,
  objProxy)` form "does not raise, but ... its `execute` is never invoked on
  recompute") and third bullet (`App::FeaturePython`,
  `App::GeometryPython`, and `App::DocumentObjectGroupPython` "all call
  `Proxy.execute` on every recompute") are recorded as observed fact but
  come from side experiments with no trace in `pixi run tests`. That third
  bullet is exactly what the "Consequence for sh-012" paragraph
  (`docs/freecadcmd-notes.md:72-77`) branches on, so the next task's
  container architecture rests on a manual observation nothing re-checks;
  the task file's own PROBE advice says the finding "must be unambiguous and
  committed on this branch".

  Compounding it, the probe has no positive control. On the
  `AttributeError` path, `_Recorder.execute` is never shown to fire at all
  in this script, so `EXPECTED_APART_EXECUTE = False` also holds
  vacuously: a future FreeCAD in which proxy attachment or recompute
  dispatch changed shape (a different exception, a renamed hook) still
  prints `APART_PROXY_EXECUTE: no` and still passes, defeating the stated
  purpose that "a future FreeCAD bump that flips the behavior fails `pixi
  run tests` loudly". Extend `_probe_apart_execute` (or add a sibling probe
  called from `main`) to assert, with the same `_Recorder`, that an
  `App::FeaturePython` *does* receive `execute` on recompute, plus whichever
  of the `App::GeometryPython` / `App::DocumentObjectGroupPython` /
  three-argument-`App::Part` claims the doc keeps; drop from the doc any
  bullet no assertion covers. Per `pipeline.md` § Verification commands,
  this belongs as a durable check inside `pixi run tests`, not as a one-off
  run that evaporated with the implementation session.

## Non-blocking notes

- **N1: cross-references name a section heading that does not exist**
  (`tools/freecad_object_smoke.py:7`, `:47`, `:140-141`): all three point at
  the `"App::Part and Proxy.execute"` section of
  `docs/freecadcmd-notes.md`, whose actual heading is ``## `App::Part` does
  not call a Python `Proxy.execute` `` (`docs/freecadcmd-notes.md:49`). A
  reader grepping the quoted phrase finds nothing. Fold the wording fix into
  the F1 round.

- **N2: workbench docstring narrates a milestone, not the class**
  (`freecad/shelving/init_gui.py:34-36`): "M3 adds the plank object layer
  below the unit container" describes the project, not
  `ShelvingWorkbench`, which still only registers itself. State what the
  workbench provides now and leave the object layer to `objects/`.

- **N3: the new smoke script is unannotated and outside the mypy gate**
  (`tools/freecad_object_smoke.py:56`, `:59`, `:62`, `pyproject.toml:28-33`):
  consistent with the existing `tools/freecad_smoke.py` and with the task
  scoping strict typing to `freecad/shelving/`, so not this round's problem.
  Worth a follow-up now that `freecad-stubs` makes both smokes checkable.
