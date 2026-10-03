# FreeCAD runtime notes

FreeCAD behaviours this repo's tests and code depend on, each verified
directly. The pytest suites in `tests/freecad/` and `tests/freecad_gui/`
import FreeCAD as a library from plain Python (the next section);
`freecadcmd` runs only `tools/freecadcmd_import_check.py`, which covers the
startup path that library import skips.

## Plain Python reaches FreeCAD through `import freecad`

The conda-forge FreeCAD package ships its own `freecad` Python package.
Importing it loads FreeCAD's libraries, after which `import FreeCAD`,
`import Part` and `import FreeCADGui` work from plain Python in the pixi
environment, with `FreeCAD.GuiUp` 0 (verified on 1.0.0 and 1.1.3). The
FreeCAD tests run this way: each test directory's `conftest.py` imports it
before any test module does, and the headless suites run in about half a
second with none of `freecadcmd`'s console noise. For the GUI,
`tests/freecad_gui/conftest.py` creates the `QApplication` and calls
`FreeCADGui.showMainWindow()` under `QT_QPA_PLATFORM=offscreen`; the
process then exits normally when pytest finishes. Either way FreeCAD must
first be pointed at throwaway settings, because it reads their location
only at startup (`tests/freecad_env.py`, and the two FreeCAD 1.1
sections below).

What this import does not do is FreeCAD's own startup: add-on discovery
and the frozen `freecad` namespace path described below.

## Only an uncaught exception discards the exit status

`freecadcmd script.py` exits 0 for an uncaught exception, printing an
`Exception while processing file: ...` line instead of propagating a
failure code. Both `sys.exit(N)` and `os._exit(N)` are unaffected and
propagate `N` as the real process exit status (verified directly: both
were tested against this repo's pinned FreeCAD 1.0.0 build).

`tools/freecadcmd_import_check.py` therefore catches every failure itself
and ends in `sys.exit` with its own status, which `tools/run-tests.sh`
checks directly.

## A run script's `__name__` is its filename stem, not `"__main__"`

`freecadcmd script.py` executes the script as a module named after its own
filename (`script`, from `script.py`), not `"__main__"` the way a plain
`python script.py` run does (verified directly). An
`if __name__ == "__main__":` guard at the bottom of a `freecadcmd`-run
script silently never fires: the guarded code never runs, and the script
still exits 0, having done nothing past defining whatever came before the
guard.

Consequence for `tools/freecadcmd_import_check.py`: its call to `main()`
and its `sys.exit` run unconditionally at module level, with no
`__name__` guard.

## `freecadcmd`'s own stdout buffering can hide a script's last output

A `freecadcmd` script's process teardown does not flush Python's stdout
buffer the way a normal interpreter shutdown does. Output written just
before the script's final `sys.exit(N)` can be silently lost, tracebacks
included (confirmed:
reproduced with and without an explicit flush). Call `sys.stdout.flush()`
immediately before any exit call that ends a `freecadcmd` script, not just
on the success path.

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
Verified directly: `import freecad.Shelving.core.X` resolves
correctly under `freecadcmd` with no `sys.path` insert of any kind, and no
`extend_path` refresh, present in the calling script at all.

`freecad/` itself carries no `__init__.py` (a PEP 420 namespace-package
portion, not a regular package), so importing anything under
`freecad.Shelving` first resolves the *installed* FreeCAD distribution's
own `freecad/__init__.py`: a regular package always wins resolution over a
namespace-portion directory of the same name, confirmed directly. That
`__init__.py` unconditionally imports the `FreeCAD` App module as part of
its own `extend_path` bookkeeping and, when `PATH_TO_FREECAD_LIBDIR` is
unset, prints a diagnostic line to stdout the first time this happens in a
plain Python process (not under `freecadcmd`, which has already imported
`FreeCAD` by the time a script runs). `tools/layout_demo.py` sets
`PATH_TO_FREECAD_LIBDIR` defensively before its own imports to suppress
that diagnostic; see its module docstring.

## `import FreeCADGui` returns a stub that lacks `Workbench`

Under `freecadcmd`, or in plain Python with FreeCAD imported but no GUI
started (verified on 1.1.3), `import FreeCADGui` still succeeds.
It returns a stub module with no `ImportError` raised, and that stub does
not define `Workbench`. An `except ImportError` guard alone is therefore
not enough to protect GUI-only code: the import passes and the
`Gui.Workbench` attribute access is what fails. Code that subclasses
`Gui.Workbench` also has to check `hasattr(Gui, "Workbench")` (or
`getattr(Gui, "Workbench", None)`) and fall back when it is absent.

See `freecad/Shelving/init_gui.py`, which catches `ImportError` and, on the
success path, drops `Gui` to `None` when `hasattr(Gui, "Workbench")` is
false so the workbench base class and the `addWorkbench` call are skipped.
`tools/freecadcmd_import_check.py` exercises this under `freecadcmd`, and
`tests/freecad/test_scan.py`'s `test_init_gui_imports_cleanly` imports the
module from plain Python too.

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

## A scripted document's `UndoMode` starts off

`FreeCAD.newDocument(name)` returns a document with `UndoMode == 0`
(verified against FreeCAD 1.0.0), unlike a document created through
the GUI, whose default comes from the user's preferences and is normally
on. With `UndoMode` off, `openTransaction`/`commitTransaction`/
`abortTransaction` still run without raising, but record nothing:
`abortTransaction` is a silent no-op, leaving every edit made since
`openTransaction` in place instead of reverting it.

Consequence for any headless caller whose correctness depends on abort
reverting: set `doc.UndoMode = 1` before the first
`openTransaction`, rather than assuming a document is undo-capable because
it opened without error. `freecad/Shelving/editor/session.py`'s `Session.open`
does this for that reason.

## A `DocumentObject`'s `ViewObject` is `None`

Without the GUI, FreeCAD gives every `DocumentObject` a `ViewObject`
attribute of `None` rather than omitting it or raising (verified on a
freshly created `Part::Box`: on 1.0.0 under `freecadcmd`, and on 1.1.3 in
plain Python). There is no 3D view for a `ViewObjectPy` to
represent, so nothing headless can read or write view-only state such as
`ShapeColor`.

Consequence: a headless test cannot assert that a colour survives an
operation; that case has to stay in `docs/manual-qa.md` instead
(`tests/freecad/test_write.py`'s resize test does the same check for
`Label`, which is ordinary `DocumentObject` state and unaffected).

## GUI-only widget access: `Gui::QuantitySpinBox`

`FreeCADGui.UiLoader` exists only once the GUI is up: in tests, under
`tests/freecad_gui/conftest.py` (the first section). The following was
verified against FreeCAD 1.0.0 and again against 1.1.3.

A one-off script can also run under the GUI binary, as
`QT_QPA_PLATFORM=offscreen pixi run freecad script.py`, given the
throwaway settings from the two FreeCAD 1.1 sections below. The GUI keeps
running after such a script returns or raises, so the process hangs.
`sys.exit(N)` does end it, but once the script has opened a document the
process exits 1 whatever `N` is (a bare `sys.exit(3)` with no document
exits 3), so the script must end in `os._exit(status)`. The GUI also routes
`sys.stdout` to its Report view; write to `sys.__stderr__` to see output.

- `FreeCADGui.UiLoader().createWidget("Gui::QuantitySpinBox")` returns a
  working widget. PySide6 sees it as a `QAbstractSpinBox`, so its
  FreeCAD-specific API is reached through Qt properties and string
  signatures, never Python attributes. `Gui::InputField` is also
  available.
- The resolved value, in millimetres for a length, is
  `widget.property("rawValue")`. `widget.property("value")` raises: PySide6
  has no converter for `Base::Quantity`. The `valueChanged(double)` signal
  is only reachable as
  `QtCore.QObject.connect(widget, QtCore.SIGNAL("valueChanged(double)"), slot)`.
- With `widget.setProperty("unit", "mm")`, a bare number is millimetres,
  including inside a sum: `1 + 1/2"` resolves to 13.70 mm (1 mm plus
  12.70 mm), where `FreeCAD.Units.parseQuantity` gives 38.10 mm for the same
  text. `1" + 1/2"` resolves to 38.10 mm, `1-1/2"` to -11.70 mm, and
  `12 1/2"` is not acceptable input. `parseQuantity` itself rejects
  `1" + 1/2"` with "invalid unit expression".
- An expression naming a document object, such as `VarSet.Len - 2 * 18 mm`,
  resolves only once the widget is bound to a property of an object in
  that document:
  `FreeCADGui.ExpressionBinding(widget).bind(obj, "PropertyName")`. Unbound,
  the same text is not acceptable input. A bound widget accepts it typed
  directly, with no leading `=`.
- Typing `=` into a bound widget opens its f(x) dialog
  (`Gui::Dialog::DlgExpressionInput`, with the expression in a child named
  `expression`: a `QLineEdit` in 1.0, a `Gui::ExpressionTextEdit`, which
  is a `QPlainTextEdit`, in 1.1). Accepting it writes the expression
  straight into the bound property's `ExpressionEngine`, even with
  `autoApply()` false, inside whatever document transaction is already
  open; `abortTransaction` reverts it. The widget does not refresh when the
  referenced `VarSet` later changes.
- Unacceptable text blocks Return, so `editingFinished` fires only for
  input the widget resolved. On Return, 1.1 replaces accepted text with the
  resolved value (`1" + 1/2"` becomes `38.10 mm`); 1.0 kept the typed text.

`freecad/Shelving/editor/panel.py` binds its dimension field to a temporary
probe object the session creates for exactly this reason: a region's size
is not itself a document property, so without the probe the field could
not resolve a `VarSet` name.

## FreeCAD 1.1 offers a settings migration at the first GUI start

FreeCAD 1.1 keeps user settings in per-version directories under the XDG
config, data and cache directories (`~/.config/FreeCAD/v1-1/` and so on).
When it finds settings from an older version, the first GUI start opens a
modal dialog offering to migrate them (`Gui::Dialog::DlgVersionMigrator`,
from `StartupPostProcess::checkVersionMigration`), before any script runs.
Headless, nothing answers it, so startup never finishes (verified on 1.1.3
with a native stack). Starting with empty XDG directories avoids it:
`XDG_CONFIG_HOME`, `XDG_DATA_HOME` and `XDG_CACHE_HOME` are enough, and
`HOME` can stay as it is. `freecadcmd` shows no such dialog.

## A headless notification popup deadlocks FreeCAD 1.1

Under Qt's offscreen platform, any Qt warning (such as "This plugin does
not support propagateSizeHints()") goes through FreeCAD's message handler
into the Notification Area. Showing that notification's popup calls
`QWidget::raise()`, which the offscreen platform answers with another
warning, and that re-enters `Gui::NotificationArea::pushNotification`
while `showInNotificationArea` still holds the area's mutex. The main
thread then waits on that mutex forever (verified on 1.1.3 with `eu-stack`:
the system and conda-forge `gdb` both fail on this VM with "Unable to fetch
SVE/SSVE vector length"). The same happens under Xvfb. Setting
`BaseApp/Preferences/NotificationArea/NonIntrusiveNotificationsEnabled` to
false avoids it. `tools/freecad-test-user.cfg` sets it, and both
`tests/freecad_env.py` and `tools/run-tests.sh` install that file into
the throwaway settings every FreeCAD test run uses. Notifications still
reach the Notification Area and the Report view, only without a popup.

## User-facing errors: the Notification Area

`FreeCAD.Console.PrintTranslatedUserError("Shelving", message)` pops the
message up briefly from the status bar's Notification Area, labelled with
the notifier `"Shelving"`, shows it in red in the status bar, and keeps it
in the Report view. The user confirmed this in FreeCAD 1.1.1; 1.0.0 accepts
the same call. freecad-stubs declares the function with one argument, so
`freecad/Shelving/editor/panel.py`'s `report_error` casts it. An offscreen
GUI records nothing in the Notification Area, so only a real display shows
whether the popup appears.
