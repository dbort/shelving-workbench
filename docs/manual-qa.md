# Manual QA

Checks a human runs in the FreeCAD GUI, because they need a real display:
toolbar and task-panel wiring, notification popups, the 3D view following
an edit, and what an elevation looks like. Anything a test can assert
belongs in `tests/freecad/` or `tests/freecad_gui/` instead; when a case
becomes automatable, move it there and delete its case file entry.

Each case is a sequence of steps, each with an expected result, written
for someone who did not build the feature.

## Setup

### Load the workbench from this checkout

FreeCAD finds workbenches by scanning its `Mod` directories at startup.
Symlink the whole repository there, since `package.xml` at the root tells
FreeCAD where the package sits. The FreeCAD 1.1 user directory is
`~/.local/share/FreeCAD/v1-1/` on Linux and
`~/Library/Application Support/FreeCAD/v1-1/` on macOS
(`App.getUserAppDataDir()` prints it). On Linux, from the repository
root:

```sh
mkdir -p ~/.local/share/FreeCAD/v1-1/Mod
ln -s "$(pwd)" ~/.local/share/FreeCAD/v1-1/Mod/shelving-workbench
```

Restart FreeCAD and pick **Shelving** in the workbench selector. If it is
missing, look for an import error in **View → Panels → Report view**.
Delete the symlink to uninstall.

Keep the Report view open for every case: the commands print there. Each
command run is bracketed by `===== BEGIN` and `===== END` lines sharing
one `#N` id. Turn that diagnostic output off from the Python console with
`from freecad.Shelving import debug_log; debug_log.enabled = False`.

## Run the QA wizard

The cases live in `freecad/Shelving/qa/cases/`, one TOML file per feature
area, and the QA wizard walks through them.

1. Pick the **Shelving** workbench and run **Shelving → QA Wizard**. A
   **QA Wizard** panel docks on the right of the main window.
2. Click **Start next case**, or select a case and click **Open selected
   case**. Each step says what to do and what to expect. A button runs a
   step's setup, such as creating a fresh unit, so no code needs pasting
   into the Python console.
3. Record **Pass**, **Fail** or **Skip**, with a comment if there is
   anything to say. A verdict is final and moves to the next step; to redo
   a case, click **Restart case**.
4. Back in the case list, click **Save report**. The JSON report goes to
   `report.json` in `shelving-qa-<your user name>/` under FreeCAD's temp
   directory (`App.getTempPath()`), holding each step's verdict, comment,
   check result, button presses and Report view output. Its path goes on
   the clipboard, ready to paste into a review session, which reads the
   file.

Progress is saved after every verdict. Reopening the wizard, even after
restarting FreeCAD, offers to resume.

The wizard is developer tooling, on while
`from freecad.Shelving import qa; qa.enabled` is true, which it is by
default. How its cases are written, and what keeps it small, is in
`.claude/docs/qa-wizard.md`.
