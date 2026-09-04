# Writing `freecadcmd` headless scripts

`freecadcmd` runs a Python script inside a FreeCAD interpreter with no GUI.
`pixi run tests` uses it for `tools/freecad_smoke.py`, and later milestones
add more headless scripts for CI checks. Three of its behaviors differ from
a plain `python script.py` run; each is handled in the code cited below.

## The script's exit status is discarded

`freecadcmd script.py` exits 0 regardless of what the script does.
`sys.exit(N)`, an uncaught exception, and `os._exit(N)` all leave the
shell with status 0. A headless script that needs to report pass or fail
must print a marker line on success and have its caller grep stdout for
that line, because the return code carries no signal.

`tools/run-tests.sh` does this: it captures the smoke script's output and
greps for `shelving workbench import OK`, treating a missing marker as
failure. See the marker that `tools/freecad_smoke.py` prints.

## FreeCAD freezes the `freecad` namespace package's `__path__`

FreeCAD imports its own `freecad` namespace package during startup and
fixes its `__path__` at that point. A `freecad.shelving` that lives in a
source checkout rather than on FreeCAD's addon path is not importable from
a bare `sys.path` insert alone: the namespace package will not look in the
new location. After inserting the repo root on `sys.path`, the script also
has to refresh the namespace path with
`freecad.__path__ = extend_path(freecad.__path__, "freecad")`.

See `tools/freecad_smoke.py`, which does the `sys.path` insert and the
`extend_path` refresh together before importing `freecad.shelving`. An
installed workbench never needs this, because FreeCAD's addon discovery
puts it on the frozen path in the first place.

## `import FreeCADGui` returns a stub that lacks `Workbench`

Under `freecadcmd` there is no GUI, but `import FreeCADGui` still succeeds.
It returns a stub module with no `ImportError` raised, and that stub does
not define `Workbench`. An `except ImportError` guard alone is therefore
not enough to protect GUI-only code: the import passes and the
`Gui.Workbench` attribute access is what fails. Code that subclasses
`Gui.Workbench` also has to check `hasattr(Gui, "Workbench")` (or
`getattr(Gui, "Workbench", None)`) and fall back when it is absent.

See `freecad/shelving/init_gui.py`, which catches `ImportError` and, on the
success path, drops `Gui` to `None` when `hasattr(Gui, "Workbench")` is
false so the workbench base class and the `addWorkbench` call are skipped.

## `App::Part` does not call a Python `Proxy.execute`

FreeCAD 1.0 under `freecadcmd` gives a bare `App::Part` no scripted-object
behavior. `tools/freecad_object_smoke.py::_probe_apart_execute` demonstrates
this on every `pixi run tests` run, using a `_Recorder` proxy whose `execute`
sets a flag. Each observation below maps to an assertion in that probe:

- `_apart_rejects_proxy_attr`: `doc.addObject("App::Part", "Probe")` then
  `part.Proxy = recorder` raises `AttributeError` (`'App.Part' object has no
  attribute 'Proxy'`). The C++ type has no `App::*Python` extension, so it
  holds no proxy; the probe treats this as `execute` never firing.
- `_apart_ignores_proxy_arg`: the three-argument
  `doc.addObject("App::Part", "Probe", recorder)` form does not raise, but the
  probe asserts the resulting object has no `Proxy` attribute, and after
  `touch()` + `recompute()` the recorder's `execute` has not fired.
- `_python_feature_executes` (positive control): the same `_Recorder` proxy
  passed the same three-argument way to `App::FeaturePython`,
  `App::GeometryPython`, and `App::DocumentObjectGroupPython` does receive
  `execute` on `recompute()`; the probe asserts all three fire. A FreeCAD that
  stopped dispatching `execute` altogether would flip this control and fail
  `pixi run tests`, so the `App::Part` result cannot pass vacuously.

The probe prints `APART_PROXY_EXECUTE: no`, hard-codes
`EXPECTED_APART_EXECUTE = False`, and asserts the observed value still matches,
so a future FreeCAD bump that changes the `App::Part` behavior fails `pixi run
tests`. Observed on FreeCAD 1.0.0 (`1.0.0R39109`).

Consequence for sh-012: the `ShelvingUnit` container cannot be a bare
`App::Part` that reconciles its children from its own `execute`. It must be a
scripted type that receives `execute` (an `App::DocumentObjectGroupPython` /
`App::FeaturePython` with a group extension, per the positive control above),
or an `App::Part` paired with a child `App::FeaturePython` "driver" object that
owns the reconciliation `execute`.
