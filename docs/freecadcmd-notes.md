# Writing `freecadcmd` headless scripts

`freecadcmd` runs a Python script inside a FreeCAD interpreter with no GUI.
`pixi run tests` uses it for `tools/freecad_scan_smoke.py`. Several of its
behaviors differ from a plain `python script.py` run; most are handled in
the code cited below.

## Only an uncaught exception discards the exit status

`freecadcmd script.py` exits 0 for an uncaught exception, printing an
`Exception while processing file: ...` line instead of propagating a
failure code. Both `sys.exit(N)` and `os._exit(N)` are unaffected and
propagate `N` as the real process exit status (verified directly: both
were tested against this repo's pinned FreeCAD 1.0.0 build).

`tools/freecad_scan_smoke.py` uses this directly: it is a real pytest
module (see the next two sections) whose trailing
`sys.exit(pytest.main([...]))` makes the process exit status itself the
pass/fail signal, so `tools/run-tests.sh` checks that directly rather than
grepping captured output for a marker line.

## A run script's `__name__` is its filename stem, not `"__main__"`

`freecadcmd script.py` executes the script as a module named after its own
filename (`script`, from `script.py`), not `"__main__"` the way a plain
`python script.py` run does (verified directly). An
`if __name__ == "__main__":` guard at the bottom of a `freecadcmd`-run
script silently never fires: the guarded code never runs, and the script
still exits 0, having done nothing past defining whatever came before the
guard.

Consequence for `tools/freecad_scan_smoke.py`, which self-invokes pytest
(see the next section): its entry point runs unconditionally at module
level, with no `__name__` guard of any kind, for exactly this reason.

## A self-invoking pytest module must guard against collecting itself

A `freecadcmd` script that turns around and calls
`pytest.main([__file__, ...])` on itself, to get real pytest reporting
instead of a hand-rolled assert-and-marker script, has to stop that call
from running a second time: pytest's own collection re-imports the target
file by path to find its `test_*` functions, and since that reimport
executes the file's top level again, an unconditional `pytest.main(...)`
call reached a second time inside that reimport starts a nested pytest
session recursively (confirmed). The nested `sys.exit` corrupts the outer
collection with an `INTERNALERROR`. An `if __name__ ==
"__main__":` guard cannot fix this either, per the previous section, and
would not help even if it worked: pytest's reimport does not reliably set
`__name__` to a different value than the original run did.

`tools/freecad_scan_smoke.py` breaks the cycle with an environment
variable set just before the real `pytest.main()` call: the variable
survives the reimport within the one process, so the second entry into
that code path sees it already set and skips calling `pytest.main()`
again.

## `freecadcmd`'s own stdout buffering can hide a script's last output

A `freecadcmd` script's process teardown does not flush Python's stdout
buffer the way a normal interpreter shutdown does. Output written just
before the script's final `sys.exit(N)` can be silently lost, including an
entire pytest `FAILURES` section with the actual traceback (confirmed:
reproduced with and without an explicit flush). Call `sys.stdout.flush()`
immediately before any exit call that ends a `freecadcmd` script, not just
on the success path.

## The recompute progress bar cannot be suppressed or made to interleave

`doc.recompute()` writes `Recompute......` progress text through a channel
that bypasses both Python-level and OS-level output control: neither
`contextlib.redirect_stdout`, nor `os.dup2` on file descriptors 1 and 2
around the call, nor `sys.stdout.reconfigure(line_buffering=True)` changes
when or whether it appears (all confirmed directly). It reliably shows up
in one block after a script's own output, not interleaved with it,
regardless of how many separate `recompute()` calls happened. A script
that wants to correlate a failure with which of several recompute-heavy
steps was in progress has to rely on naming those steps in its own output
(a pytest test name, in `tools/freecad_scan_smoke.py`'s case) rather than
trying to align them against the progress bar's own position in the
combined output.

Its last write ends in a bare `\r` with no trailing `\n` (confirmed
byte-for-byte), so the cursor sits at column 0 of that same line rather
than moving to a new one. Whatever prints next, a shell prompt included,
lands on top of it. This looks like output arriving after the process has
already exited, but it is a cursor-position artifact from a missing final
newline.

## FreeCAD freezes the `freecad` namespace package's `__path__`

FreeCAD imports its own `freecad` namespace package during startup and
fixes its `__path__` at that point: the one-time `pkgutil.extend_path` scan
that builds `__path__` only sees whatever is on `sys.path` at that moment,
so a directory added afterward is not picked up by a bare `sys.path`
insert alone. This is real and general to FreeCAD, not specific to this
repo's layout.

This repo's scripts do not need to work around it, because by the time
`freecadcmd` (or any interpreter in the pixi environment) reaches its own
internal `import freecad`, the repo root is already on `sys.path`: the
project's editable install (`pixi.toml`'s `[pypi-dependencies]`) places a
`.pth` file that `site.py` processes at interpreter startup, before either
`freecadcmd`'s internal import or pytest's own collection logic runs.
Verified directly this session: `import freecad.Shelving.core.X` resolves
correctly under `freecadcmd` with no `sys.path` insert of any kind, and no
`extend_path` refresh, present in the calling script at all.

`freecad/` itself carries no `__init__.py` (a PEP 420 namespace-package
portion, not a regular package), so importing anything under
`freecad.Shelving` first resolves the *installed* FreeCAD distribution's
own `freecad/__init__.py` (a regular package always wins resolution over a
namespace-portion directory of the same name, verified this session) —
which unconditionally imports the `FreeCAD` App module as part of its own
`extend_path` bookkeeping, and, when `PATH_TO_FREECAD_LIBDIR` is unset,
prints a diagnostic line to stdout the first time this happens in a plain
Python process (not under `freecadcmd`, which has already imported `FreeCAD`
by the time a script runs). `tools/layout_demo.py` sets
`PATH_TO_FREECAD_LIBDIR` defensively before its own imports to suppress
that diagnostic; see its module docstring.

## `import FreeCADGui` returns a stub that lacks `Workbench`

Under `freecadcmd` there is no GUI, but `import FreeCADGui` still succeeds.
It returns a stub module with no `ImportError` raised, and that stub does
not define `Workbench`. An `except ImportError` guard alone is therefore
not enough to protect GUI-only code: the import passes and the
`Gui.Workbench` attribute access is what fails. Code that subclasses
`Gui.Workbench` also has to check `hasattr(Gui, "Workbench")` (or
`getattr(Gui, "Workbench", None)`) and fall back when it is absent.

See `freecad/Shelving/init_gui.py`, which catches `ImportError` and, on the
success path, drops `Gui` to `None` when `hasattr(Gui, "Workbench")` is
false so the workbench base class and the `addWorkbench` call are skipped.
`tools/freecad_scan_smoke.py`'s `test_init_gui_imports_cleanly` is what
exercises this: nothing else imports `init_gui.py` as a side effect.

## `App::Part` does not call a Python `Proxy.execute`

FreeCAD 1.0.0 (`1.0.0R39109`) under `freecadcmd` gives a bare `App::Part` no
scripted-object behavior. Both ways of attaching a proxy fail to produce an
`execute` callback:

- `doc.addObject("App::Part", name)` then `part.Proxy = recorder` raises
  `AttributeError: 'App.Part' object has no attribute 'Proxy'`. The C++ type
  carries no `App::*Python` extension, so it holds no proxy at all.
- The three-argument `doc.addObject("App::Part", name, recorder)` form does not
  raise, but the resulting object still exposes no `Proxy` attribute, and a
  `touch()` + `recompute()` never calls the proxy's `execute`.

The scripted `App::*Python` types behave the opposite way: a proxy passed the
three-argument way to `App::FeaturePython`, `App::GeometryPython`, or
`App::DocumentObjectGroupPython` receives `execute` on every `recompute()`.

Consequence for sh-012: the `ShelvingUnit` container cannot be a bare
`App::Part` that reconciles its children from its own `execute`. It must be a
scripted type that receives `execute`, either an `App::DocumentObjectGroupPython`
or an `App::FeaturePython` with a group extension. The other option is an
`App::Part` paired with a child `App::FeaturePython` "driver" object that owns
the reconciliation `execute`.

## A proxy `execute` that raises marks the object `Invalid`

FreeCAD 1.0.0 (`1.0.0R39109`) under `freecadcmd` does not propagate an exception
raised inside a scripted object's `Proxy.execute` out of `doc.recompute()`. The
recompute call returns normally; the failure shows up on the object's state
instead. After a `RuntimeError` from `execute`, an `App::FeaturePython` driver
reports `driver.State == ['Touched', 'Invalid']` and `driver.isValid() is False`,
and stays that way across further recomputes until an `execute` succeeds. The
traceback is written to stderr.

Consequence for headless checks: assert the error path on `"Invalid" in
obj.State` or `obj.isValid() is False`. Do not assert on `"Touched" in obj.State`
alone: an object the recompute never visited also carries `"Touched"`, so that
predicate passes even when `execute` never ran.
