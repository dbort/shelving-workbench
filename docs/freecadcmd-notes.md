# Writing `freecadcmd` headless scripts

`freecadcmd` runs a Python script inside a FreeCAD interpreter with no GUI.
The full test tier uses it for `tools/freecad_smoke.py`, and later
milestones add more headless scripts for CI checks. Three of its behaviors
differ from a plain `python script.py` run; each is handled in the code
cited below.

## The script's exit status is discarded

`freecadcmd script.py` exits 0 regardless of what the script does.
`sys.exit(N)`, an uncaught exception, and `os._exit(N)` all leave the
shell with status 0. A headless script that needs to report pass or fail
must print a marker line on success and have its caller grep stdout for
that line, because the return code carries no signal.

`test.sh` does this: its `--full` tier captures the smoke script's output
and greps for `shelving workbench import OK`, treating a missing marker as
failure. See `test.sh` and the marker `tools/freecad_smoke.py` prints.

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
