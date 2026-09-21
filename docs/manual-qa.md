# Manual QA

A living catalog of checks a human runs in the FreeCAD GUI. Some behavior has no
headless assertion yet: property-editor reflow, toolbar and menu wiring, and
tree presentation only exist once a real `FreeCADGui` is running.

Every case here is a candidate for automation. When a headless path to a check
becomes possible, move it into the relevant headless `freecadcmd` pytest
module under `tools/` (run by `pixi run tests`) and delete it from this file.
`tools/freecad_scan_smoke.py` is the module for scanning; other milestones
add their own modules as they need them. The commit history keeps the
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

- Link the whole repo, not just `freecad/Shelving/`. `package.xml` lives at
  the repo root, and its `<subdirectory>` field is what tells FreeCAD where
  inside the linked directory the importable workbench package sits;
  linking only `freecad/Shelving/` would drop `package.xml` (and the
  Addon-Manager-facing metadata it carries: name, description, icon,
  license, URLs) from the loaded tree.
- If **Shelving** does not appear, open **View → Panels → Report view** and the
  Python console and look for an import error. Confirm the link points at the
  directory holding `package.xml`.
- A plain copy of the repo into `Mod/` works too, but edits then need a
  re-copy; the symlink keeps the checkout live.

## M6 — Read a container

Prerequisite: a FreeCAD 1.0 install with this workbench on its addon path,
**View → Panels → Report view** open, and a document built to a known
state so every run of these cases starts from the same geometry.
`Shelving_Scan` and `Shelving_ExportBoxes` print their results to the
Report view with `print()`, not to the Python console, so keep the Report
view open: it's easy to miss otherwise. `Ctrl+N` for a new document, open
the Python console (**View → Panels → Python console**), and paste:

```python
doc = App.ActiveDocument
part = doc.addObject("App::Part", "TestUnit")


def add_box(name, size_mm, corner_mm, angle_deg=0.0):
    box = doc.addObject("Part::Box", name)
    box.Length, box.Width, box.Height = size_mm
    box.Placement = App.Placement(
        App.Vector(*corner_mm), App.Rotation(App.Vector(0, 0, 1), angle_deg)
    )
    part.addObject(box)


# A closed 600 x 600 x 300 mm shell with one shelf, the same geometry
# tools/freecad_scan_smoke.py's _build_shell builds and asserts against.
add_box("Bottom", (600.0, 300.0, 18.0), (0.0, 0.0, 0.0))
add_box("Top", (600.0, 300.0, 18.0), (0.0, 0.0, 582.0))
add_box("LeftSide", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
add_box("RightSide", (18.0, 300.0, 564.0), (582.0, 0.0, 18.0))
add_box("Shelf", (564.0, 300.0, 18.0), (18.0, 0.0, 291.0))
doc.recompute()
```

This is the "TestUnit" `App::Part` the cases below refer to.

### 1. Scan reports the tree in the report view

1. Select **TestUnit** in the tree.
2. Run **Scan Unit** from the **Shelving** toolbar or menu.

Expected: the report view prints a plane line naming the depth axis and
overall size, a facing line, and an indented tree of divisions, bays, voids,
and boards matching the unit's shape. Nothing in the document changes: no
property is written, no object created, no placement moved. Exactly (the
timestamp FreeCAD prepends varies):

```
depth axis y, size 600 x 300 x 600 mm
WARNING: nothing says which side this unit faces, so left and right below are a coin flip: the tree is correct either way.

division along z
  board Bottom (default material)
  division along x, 564 mm (clear)
    board LeftSide (default material)
    division along z, 564 mm (clear)
      bay
      board Shelf (default material)
      bay
    board RightSide (default material)
  board Top (default material)
```

### 2. A scan can succeed while reporting a skipped part

An unreadable part inside an otherwise-valid container does not by itself
make the scan fail: `read_container` sets it aside as `Skipped` and
`scan` still builds a tree from the rest, as long as the rest is still a
complete, enclosed unit on its own. This case exercises that path, not a
refusal: case 4 below is the refusal.

1. With **TestUnit** still selected in the tree, paste into the Python
   console (the same "Skewed" part `tools/freecad_scan_smoke.py` asserts
   is skipped, so its expected reason is known ahead of time):
   ```python
   add_box("Skewed", (100.0, 50.0, 20.0), (0.0, 400.0, 0.0), angle_deg=30.0)
   doc.recompute()
   ```
2. Select **TestUnit** and run **Scan Unit** again.

Expected: the report view prints the same tree as case 1, with a skipped
block appended:

```
skipped (1):
  Skewed [Part::Box]: not axis-aligned
```

The document does not change, and the 3D selection is untouched: this is a
successful scan, not a refusal.

### 3. Export Boxes writes JSON beside the document

Run this against the document as case 2 left it, before case 4 adds
anything further. Case 4 comes last because nothing needs the document
afterward.

1. Save the document if it has not been saved yet (the export path sits next
   to the saved file).
2. Select **TestUnit** and run **Export Boxes** from the toolbar or menu.

Expected: the report view prints how many boxes and skipped parts were
written and a path ending in `<label>.boxes.json`; that file exists next to
the saved document. It reads:

```json
{
  "boxes": [
    {"name": "Bottom", "corner_mm": [0.0, 0.0, 0.0], "size_mm": [600.0, 300.0, 18.0]},
    {"name": "Top", "corner_mm": [0.0, 0.0, 582.0], "size_mm": [600.0, 300.0, 18.0]},
    {"name": "LeftSide", "corner_mm": [0.0, 0.0, 18.0], "size_mm": [18.0, 300.0, 564.0]},
    {"name": "RightSide", "corner_mm": [582.0, 0.0, 18.0], "size_mm": [18.0, 300.0, 564.0]},
    {"name": "Shelf", "corner_mm": [18.0, 0.0, 291.0], "size_mm": [564.0, 300.0, 18.0]}
  ],
  "skipped": [
    {"name": "Skewed", "label": "Skewed", "type": "Part::Box", "reason": "not axis-aligned"}
  ]
}
```

### 4. A refusal names the offending parts and selects them in the 3D view

Unlike case 2, this makes the readable geometry itself invalid, so `scan`
raises rather than returning a tree with a skipped part.

1. With **TestUnit** still selected, paste into the Python console to add a
   box occupying the exact same space as `LeftSide` (any solid overlap
   triggers the same refusal; an exact duplicate is the simplest to get
   right by hand):
   ```python
   add_box("Overlap", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
   doc.recompute()
   ```
2. Select **TestUnit** and run **Scan Unit** again.

Expected:

```
REFUSED: Overlap overlaps LeftSide
objects: Overlap, LeftSide
```

The 3D view's selection clears and re-selects both **Overlap** and
**LeftSide**, visibly highlighted, rather than leaving the whole container
selected.

## M7 — Write a container

Prerequisite: a FreeCAD 1.0 install with this workbench on its addon path,
**View → Panels → Report view** open, a new document (`Ctrl+N`).
`Shelving_CreateUnit` and `Shelving_ResizeUnit` print their results to the
Report view with `print()`, not to the Python console, so keep the Report
view open.

### 1. Create a unit and confirm the tree holds plain boxes with a Shelving property group

1. With nothing selected, run **Create Unit** from the **Shelving** toolbar
   or menu.

Expected: a new `ShelvingUnit` `App::Part` appears in the tree, holding four
`Part::Box` objects labelled **Bottom**, **Top**, **Side 1**, **Side 2** (a
fresh unit has no evidence of which way it faces, so the sides are numbered
rather than called left/right). Select **Bottom** and open the property
editor: a **Shelving** group holds `ShelvingMaterial`, `ShelvingBornAs`,
`ShelvingBornIn`, and `ShelvingIrregular`. Select **ShelvingUnit** itself: its
own **Shelving** group holds `ShelvingUnitId`, `ShelvingDepthAxis`,
`ShelvingFacing` (`unknown`), and `ShelvingRules`. The Report view prints how
many boards were created.

### 2. Resize it and confirm boards move while labels and colours hold

1. Select **Bottom**, rename its label to `MyBottom` (F2, or the property
   editor's `Label` field), and give it a colour (right-click → **Appearance…**
   or the toolbar's colour swatch).
2. Select **ShelvingUnit** and run **Resize Unit**. Enter a width, depth, and
   height each noticeably different from the current ones (the dialog is
   seeded from the unit's current measured size).

Expected: the same four objects move and resize to the new outer dimensions;
no new objects appear and none are deleted. **Bottom**'s label stays
`MyBottom` and its colour is unchanged. The Report view prints an
`updated 4, created 0, deleted 0, left alone 0` line (counts may differ if
you added other geometry first).

### 3. Move a board by hand, rescan, and confirm the layout takes the edit up

1. Select one of the side boards and drag it (or edit its `Placement` in the
   property editor) so it no longer lines up with **Bottom** and **Top**.
2. Select **ShelvingUnit** and run **Resize Unit** again, entering the exact
   same width, depth, and height as before (or run **Scan Unit** first to
   confirm the moved board is still read correctly, then resize).

Expected: the hand-moved board snaps back into its correct position as part
of the reapplied layout; the layout reflows around the edit rather than
preserving the stray placement, since every resize rescans the container
fresh rather than trusting a cached tree.

### 4. Put an unrelated box in the container and confirm apply leaves it and says so

1. Select **ShelvingUnit**, add a plain `Part::Box` directly into it via the
   Python console:
   ```python
   doc = App.ActiveDocument
   part = doc.getObject("ShelvingUnit")
   extra = doc.addObject("Part::Box", "HandAdded")
   extra.Length, extra.Width, extra.Height = 50.0, 50.0, 50.0
   extra.Placement = App.Placement(App.Vector(2000.0, 2000.0, 2000.0), App.Rotation())
   part.addObject(extra)
   doc.recompute()
   ```
2. Select **ShelvingUnit** and run **Resize Unit**, entering any new size.

Expected: **HandAdded** is untouched (same position, still in the tree, not
deleted), because it carries none of this workbench's properties. The Report
view's line includes `left alone 1` and names `HandAdded` on the line below
it.

### 5. Save, quit, move the workbench off the path, reopen, and confirm the document is intact

1. Save the document.
2. Quit FreeCAD.
3. Rename or move the `shelving-workbench` symlink (or copy) out of your
   `Mod/` directory (see "Loading the workbench from this checkout" above),
   so FreeCAD cannot find the workbench.
4. Restart FreeCAD and open the saved document.

Expected: the document opens without an error dialog or a report-view
warning about a missing module, and the unit's boxes are present, correctly
sized, and at their saved positions: plain `Part::Box` geometry needs no
scripted type to regenerate. Restore the symlink afterward to keep using the
workbench.
