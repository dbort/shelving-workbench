# Manual QA

A living catalog of checks a human runs in the FreeCAD GUI. Some behavior has no
headless assertion yet: property-editor reflow, toolbar and menu wiring, and
tree presentation only exist once a real `FreeCADGui` is running.

Every case here is a candidate for automation. When a headless path to a check
becomes possible, move it into `tools/freecad_smoke.py` (run by
`pixi run tests`) and delete it from this file. The commit history keeps the
record; this file tracks only what still needs a human.

Each case is numbered steps followed by an explicit expected result, written so
someone who did not build the feature can run it. Cases are grouped by
milestone.

## Loading the workbench from this checkout

The cases below need FreeCAD to load the workbench from your working copy rather
than from an Addon Manager release. FreeCAD discovers a workbench by scanning `Mod`
directories at startup, so symlink the repo into the user `Mod` directory.

Find the FreeCAD user directory. Its default for FreeCAD 1.0 is
`~/.local/share/FreeCAD/` on Linux and
`~/Library/Application Support/FreeCAD/` on macOS; the FreeCAD Python console
prints the exact path with `App.getUserAppDataDir()`. `Mod/` sits directly
under it.

From the repo root:

```sh
# Linux
mkdir -p ~/.local/share/FreeCAD/Mod
ln -s "$(pwd)" ~/.local/share/FreeCAD/Mod/shelving-workbench
```

```sh
# macOS
mkdir -p ~/Library/Application\ Support/FreeCAD/Mod
ln -s "$(pwd)" ~/Library/Application\ Support/FreeCAD/Mod/shelving-workbench
```

Restart FreeCAD and pick **Shelving** in the workbench selector. To uninstall,
delete the symlink (not its target).

Notes:

- Link the whole repo, not just `freecad/shelving/`. The workbench imports
  `shelving_core`, and only the repo root has it; until the vendored-core
  rework lands, `freecad/shelving/vendor/` is not self-contained.
- If **Shelving** does not appear, open **View → Panels → Report view** and the
  Python console and look for an import error. Confirm the link points at the
  directory holding `package.xml`.
- A plain copy of the repo into `Mod/` works too, but edits then need a
  re-copy; the symlink keeps the checkout live.

## M6 — Read a container

Prerequisite: a FreeCAD 1.0 install with this workbench on its addon path, and
a new document (`Ctrl+N`) with an `App::Part` grouping `Part::Box` objects
that form a closed unit, for example four boxes as a shell plus a shelf.

### 1. Scan reports the tree in the report view

1. Select the `App::Part` in the tree.
2. Run **Scan Unit** from the **Shelving** toolbar or menu.

Expected: the report view prints a plane line naming the depth axis and
overall size, a facing line, and an indented tree of divisions, bays, voids,
and boards matching the unit's shape. Nothing in the document changes: no
property is written, no object created, no placement moved.

### 2. A refusal names the offending part and selects it in the 3D view

1. Add a part the walk cannot read as a board inside the same `App::Part`:
   for example a `PartDesign::Body` whose pad has a notch cut into it, or a
   box rotated off-axis.
2. Select the `App::Part` and run **Scan Unit** again.

Expected: the report view prints a refusal naming the part and the reason
(for instance "a box minus 1 rectangular cutout(s)" for the notched body).
The 3D view's selection clears and re-selects only that part, visibly
highlighted, rather than leaving the whole container selected.

### 3. Export Boxes writes JSON beside the document

1. Save the document if it has not been saved yet (the export path sits next
   to the saved file).
2. Select the `App::Part` and run **Export Boxes** from the toolbar or menu.

Expected: the report view prints how many boxes and skipped parts were
written and a path ending in `<label>.boxes.json`; that file exists next to
the saved document and contains a `boxes` array and a `skipped` array. This
works even for the container from case 2, which Scan Unit refuses.
