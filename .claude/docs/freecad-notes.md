# FreeCAD runtime notes

FreeCAD and Woodworking behaviors this repo's code and tests depend on,
each verified against a real build. The pytest suites import FreeCAD as a
library; `freecadcmd` runs only `tools/freecadcmd_import_check.py`, which
covers the startup path library import skips.

## Plain Python reaches FreeCAD through `import freecad`

The conda-forge package ships a `freecad` Python package. Importing it
loads FreeCAD's libraries, after which `import FreeCAD`, `Part` and
`FreeCADGui` work from plain Python with `FreeCAD.GuiUp` 0 (1.0.0, 1.1.3).
Each test directory's `conftest.py` imports it first. For the GUI suite,
`tests/freecad_gui/conftest.py` creates the `QApplication` and calls
`FreeCADGui.showMainWindow()` under `QT_QPA_PLATFORM=offscreen`. FreeCAD
reads its settings location only at startup, so `tests/freecad_env.py`
points it at throwaway settings before the import.

This import skips FreeCAD's own startup: add-on discovery and the frozen
namespace path below.

## Qt versions

The macOS FreeCAD 1.1.4 app runs Qt 6.8.3; pixi's conda-forge build runs
Qt 6.11. Code that runs in both can use Qt API up to 6.8, such as
`QEvent.Type.DevicePixelRatioChange` (6.6), which `editor/view_editor.py`
watches for.

## `freecadcmd` script quirks

- An uncaught exception exits 0 with an `Exception while processing file`
  line. `sys.exit(N)` and `os._exit(N)` do propagate `N`, so a script
  catches every failure itself and ends in `sys.exit`.
- A script runs as a module named after its filename stem, never
  `"__main__"`, so an `if __name__ == "__main__":` guard silently never
  fires. Call `main()` at module level.
- Teardown does not flush stdout, so output just before exit, tracebacks
  included, can vanish. Call `sys.stdout.flush()` before every exit.

## FreeCAD freezes the `freecad` namespace package's `__path__`

FreeCAD imports `freecad` during startup, and `pkgutil.extend_path` sees
only what is on `sys.path` then; a later `sys.path` insert is not picked
up. The editable install's `.pth` file puts the repo root on `sys.path`
at interpreter startup, before that import, so no script needs a
workaround.

`freecad/` has no `__init__.py`, so FreeCAD's own regular
`freecad/__init__.py` wins resolution. It imports `FreeCAD` and, in plain
Python with `PATH_TO_FREECAD_LIBDIR` unset, prints a diagnostic line to
stdout. A script that needs clean stdout sets that variable first.

## `import FreeCADGui` returns a stub that lacks `Workbench`

Without a GUI (under `freecadcmd`, or plain Python), `import FreeCADGui`
succeeds and returns a stub with no `Workbench`. Guard GUI-only code with
`hasattr(Gui, "Workbench")` as well as `except ImportError`, as
`freecad/Shelving/init_gui.py` does.

## Scripted proxies

Not used today; relevant to a future live-unit driver (FreeCAD 1.0.0).

- A bare `App::Part` takes no `Proxy` and never calls `execute`. Only the
  `App::*Python` types (`FeaturePython`, `GeometryPython`,
  `DocumentObjectGroupPython`) do.
- An exception in `Proxy.execute` does not escape `doc.recompute()`; the
  object's `State` becomes `['Touched', 'Invalid']`. Assert on `"Invalid"`
  or `isValid()`, never on `"Touched"` alone.

## A scripted document's `UndoMode` starts off

`FreeCAD.newDocument()` returns a document with `UndoMode == 0`, so
`abortTransaction` silently reverts nothing. Set `doc.UndoMode = 1` before
`openTransaction`, as `Session.open` does.

## Transactions and the undo stack

Seen on FreeCAD 1.1.3 (conda-forge); `editor/history.py` relies on each.

- `doc.openTransaction(name)` only names a pending application
  transaction (`FreeCAD.getActiveTransaction()` gives its name and id);
  the document's transaction opens at the first change, firing
  `slotOpenTransaction`. A commit or abort with no change leaves the name
  pending, and the next change anywhere, by anyone, is recorded under it.
  `FreeCAD.closeActiveTransaction()` clears it.
- Inside a Gui command, FreeCAD ignores `closeActiveTransaction(False)`
  until the command returns, and the pending transaction can outlive it;
  `closeActiveTransaction(True)` aborts at once, discarding the step just
  committed. Edit Unit declares `CmdType: NoTransaction` so FreeCAD opens
  no transaction of its own around it.
- `slotCommitTransaction`, `slotUndoDocument` and `slotRedoDocument` see
  `UndoCount` and `RedoCount` already updated. An Undo while a transaction
  is open commits it first, then undoes it.
- Past `MaxUndoSize` (default 20) each commit drops the oldest step, so
  `UndoCount` stops growing; the stack carries names and no ids a script
  can read.
- `Std_Undo` and `Std_Redo` were disabled under Xvfb while keyboard
  focus sat in a task panel's combo box, and ran with focus in the 3D
  view. On macOS (1.1.4), Cmd-Z ran with focus on a task panel button.

## Selection gestures in the 3D view

Seen on FreeCAD 1.1.3 under Xvfb; `editor/view_editor.py` relies on each.

- `Gui.Selection.getSelectionEx(doc, 0)` groups entries by object, and an
  object selected whole beside one of its own elements shows only the
  element. `getSelectionEx(doc, 0, True)` lists every entry on its own.
- Ctrl-click on an object selected whole does not deselect it: FreeCAD
  finds the clicked element unselected and adds it. Ctrl-click on a
  selected element removes it, and Ctrl-click on empty space keeps the
  selection.
- Under Inventor navigation, selecting is Ctrl-click and adds as under CAD
  navigation; a plain click on an object or on empty space leaves the
  selection as it was.
- Setting `ShapeMaterial` leaves the view's `ShapeAppearance` alone. A
  library material's appearance values come back as text, a color as
  `"(0.8984, 0.7305, 0.3906, 1.0)"`, which the Material workbench's own
  editor parses the same way.

## A `DocumentObject`'s `ViewObject` is `None`

Without the GUI every object's `ViewObject` is `None`, so color and other
view state can be asserted only in `tests/freecad_gui/`.

## Copies and object identity

Measured on 1.0. A copy within a document gets a new `Name`, as does any
copy whose name collides. A copy into another document keeps its `Name`,
and that document has a different `doc.Uid`. Save As keeps the `Uid`, so
two files can share one. The provenance check (`Name` plus `Uid` at
tagging) relies on all four.

## Containers

- `getGlobalPlacement` composes only through geo-feature groups, and
  `App::LinkGroup` is not one; `container.py` composes the chain by hand.
- `App::DocumentObjectGroup` has no `Placement` at all.
- A `PartDesign::Body` lists its construction (sketch, pad) in `Group`;
  the walk treats a body or a boolean as one part and descends only into
  `App::Part`, `App::LinkGroup` and plain groups.
- A selection can reach one object by several paths, so walks deduplicate
  by document object.

## Woodworking conventions

Read from `dprojects/Woodworking`'s source and saved documents.

- Panels are mostly `Part::Box`, also `PartDesign::Pad`, `Part::Cut`,
  links and clones. `Length` runs along X, `Width` along Y (depth),
  `Height` along Z, front at low Y. Tools write plain values, never
  expressions.
- `magicStart` puts its cabinets in an `App::LinkGroup`. Its variants ship
  both lap orders: F0 runs the floor and top full width, F1 runs the sides
  full height, so no house lap order can be assumed.
- A generated shelf is inset 1 mm from each side and shallower than the
  sides, sitting between a front and a back panel. A plinth leaves a gap
  below the floor.
- A back can sit proud behind the carcass. A proud panel much thinner than
  the stock is an overlay back, while one of stock thickness is a door; the
  facing hint got this backwards on the first real cabinet it read.
- The cut list (`getDimensions`) reads `Length`/`Width`/`Height` and groups
  by container label.

## GUI-only widget access: `Gui::QuantitySpinBox`

`FreeCADGui.UiLoader` exists only with the GUI up (verified on 1.0.0 and
1.1.3).

A one-off script can run under the GUI binary as
`QT_QPA_PLATFORM=offscreen pixi run freecad script.py`, with the throwaway
settings below. The GUI keeps running after the script, so end it with
`os._exit(status)`: once a document is open, `sys.exit(N)` exits 1. The
GUI routes `sys.stdout` to the Report view; write to `sys.__stderr__`.

- `UiLoader().createWidget("Gui::QuantitySpinBox")` works; PySide6 sees a
  `QAbstractSpinBox`, so FreeCAD's API is reached through Qt properties and
  string signatures. `Gui::InputField` is also available.
- Read the value in millimeters with `widget.property("rawValue")`;
  `property("value")` raises (no `Base::Quantity` converter). Connect
  `valueChanged(double)` only through
  `QtCore.QObject.connect(widget, QtCore.SIGNAL("valueChanged(double)"), slot)`.
- With `setProperty("unit", "mm")`, a bare number is millimeters even in a
  sum: `1 + 1/2"` is 13.70 mm, `1" + 1/2"` is 38.10 mm, `1-1/2"` is
  -11.70 mm, and `12 1/2"` is rejected. `FreeCAD.Units.parseQuantity`
  disagrees (38.10 mm for the first, and it rejects `1" + 1/2"`).
- A name such as `VarSet.Len - 2 * 18 mm` resolves only once the widget is
  bound with `FreeCADGui.ExpressionBinding(widget).bind(obj, "Prop")`.
  Bound, it accepts the text typed directly, with no leading `=`.
- Typing `=` in a bound widget opens `Gui::Dialog::DlgExpressionInput`
  (its child `expression` is a `QLineEdit` in 1.0, a `QPlainTextEdit`
  subclass in 1.1). Accepting writes straight into the bound property's
  `ExpressionEngine` inside any open transaction, even with `autoApply()`
  false. The widget does not refresh when the `VarSet` later changes.
- Unacceptable text blocks Return, so `editingFinished` fires only for
  resolved input. On Return, 1.1 replaces the text with the resolved value.

A region's size is not a document property, so the session adds a hidden,
transient `App::PropertyLength` per size field to the container at open,
outside any undo step, and removes them at Close (`session.py`,
`FIELD_PROPERTIES`). Bound there, a field resolves `VarSet` names and
offers f(x). Accepting f(x) writes into whatever transaction is open, so
the field opens one before the dialog shows and aborts it once it has read
the resolved number, which leaves no undo step and no expression
(`fields.py`). Clearing the expression before the abort is what makes the
widget editable again: the abort alone leaves it read-only.

## `SoDatumLabel` outside the Sketcher

- Since FreeCAD 1.1.2 it draws its lines at the z its `pnts` carry, and
  still draws its arrowheads at a fixed z near 0 (`ZARROW_TEXT_OFFSET`);
  1.1.1 drew the lines at z 0 too. Its text is drawn without a depth test.
- Its bounding box has no depth: z 0 whatever `pnts` say. FreeCAD's
  orthographic camera clips just in front of the scene's box, so a label
  lifted off a face can lose its lines and text, keeping its arrowheads,
  when the camera looks square on. On a Mac (FreeCAD 1.1.4) it did; under
  Xvfb (1.1.3) the margin happened to hold. The editor puts invisible
  points at the labels' height to widen the box (`overlay.py`).
- It reports itself transparent, so Coin sorts it with other transparent
  shapes unless an `SoTransparencyType` of `BLEND` is in force.

## FreeCAD 1.1 offers a settings migration at the first GUI start

Settings live per version under the XDG directories
(`~/.config/FreeCAD/v1-1/`). Finding an older version's, the first GUI
start opens a modal migration dialog before any script runs, and headless
startup never finishes. Empty `XDG_CONFIG_HOME`, `XDG_DATA_HOME` and
`XDG_CACHE_HOME` avoid it. `freecadcmd` shows no dialog.

## A headless notification popup deadlocks FreeCAD 1.1

Under the offscreen platform (or Xvfb), a Qt warning becomes a
notification whose popup calls `QWidget::raise()`, which warns again and
re-enters `NotificationArea::pushNotification` while it holds its own
mutex. Setting
`BaseApp/Preferences/NotificationArea/NonIntrusiveNotificationsEnabled`
to false avoids it; `tools/freecad-test-user.cfg` does, and every test
run installs that file. (On this aarch64 VM, `gdb` cannot attach; use
`eu-stack`.)

## User-facing errors: the Notification Area

`FreeCAD.Console.PrintTranslatedUserError("Shelving", message)` pops the
message from the status bar's Notification Area, shows it in red in the
status bar, and keeps it in the Report view (1.1.1 desktop; 1.0.0 accepts
the call). Under Xvfb, conda-forge's 1.1.3 with notification popups off
counts it in the Notification Area but leaves it out of the Report view,
where `PrintError` text still appears. The stubs declare one argument, so
`refusals.report_error` casts. An offscreen GUI records nothing in the
Notification Area.
