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
2. Select **ShelvingUnit** and run **Resize Unit**. Enter width `800`, depth
   `350`, height `1000` (the dialog is seeded from the unit's current
   measured size; overwrite all three).

Expected: the same four objects move and resize to 800 × 350 × 1000 mm; no
new objects appear and none are deleted. **Bottom**'s label stays
`MyBottom` and its colour is unchanged. The Report view prints an
`updated 4, created 0, deleted 0, left alone 0` line (counts may differ if
you added other geometry first).

### 3. Move a board by hand, rescan, and confirm the layout takes the edit up

1. Select **Side 1**. In the property editor, expand `Placement` →
   `Position` and change `x` from `0` to `2`, moving it 2 mm toward the
   unit's centre. Use exactly this axis, direction, and distance:
   - Any move along `z` overlaps **Bottom** or **Top**: at this size
     **Side 1** and **Side 2** are captured flush against both with no
     slack.
   - Moving **Side 1** *away* from the unit along `x` opens a gap in the
     shell wider than the scan's 3 mm clearance tolerance, and both of
     those refuse instead of demonstrating the reflow this case is about.
   - Moving it *toward the centre* by more than 3 mm scans and resizes
     successfully, but does not demonstrate reflow either: past 3 mm the
     scanner reads the gap as a real void rather than clearance-tolerant
     measurement noise, correctly, since nothing tells it an edit that size
     was accidental rather than a deliberate design change. The board then
     stays exactly where you put it, because that reading is now a
     different, equally valid layout, not a stray edit to correct. 2 mm
     keeps this comfortably inside the tolerant range.
2. Select **ShelvingUnit** and run **Resize Unit** again, entering `800`,
   `350`, `1000`, the same dimensions as case 2 (or run **Scan Unit** first
   to confirm the moved board is still read correctly, then resize).

Expected: the hand-moved board snaps back to `x = 0` as part of the
reapplied layout; the layout reflows around the edit rather than preserving
the stray placement, since every resize rescans the container fresh rather
than trusting a cached tree. You do not need to move the board back by
hand first: running Resize Unit (or Scan Unit) is what corrects it.

### 4. Put an unrelated box in the container and confirm apply leaves it and says so

1. Select **ShelvingUnit**, add a plain `Part::Box` directly into it via the
   Python console. Use exactly these dimensions, not a cube: scanning
   requires a board to have one uniquely thinnest axis to read its
   thickness from, and a cube has three tied extents, so it refuses the
   whole scan rather than reading this one object as unrelated. Thinnest
   along `y` (this unit's depth axis) also keeps it out of thickness/material
   matching, the same way this case's automated counterpart
   (`tools/freecad_write_smoke.py`'s `BackPanel`) does it:
   ```python
   doc = App.ActiveDocument
   part = doc.getObject("ShelvingUnit")
   extra = doc.addObject("Part::Box", "HandAdded")
   extra.Length, extra.Width, extra.Height = 50.0, 5.0, 50.0
   extra.Placement = App.Placement(App.Vector(2000.0, 2000.0, 2000.0), App.Rotation())
   part.addObject(extra)
   doc.recompute()
   ```
2. Select **ShelvingUnit** and run **Resize Unit**. Enter width `900`,
   depth `400`, height `1100`.

Expected: **HandAdded** stays exactly where it was, still in the tree and
not deleted, because it carries none of this workbench's properties. The Report
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

## M8 — The material catalog as a document object

Prerequisite: a FreeCAD 1.0 install with this workbench on its addon path,
**View → Panels → Report view** open, a new document (`Ctrl+N`).

### 1. Create a unit on an empty document and confirm a materials group appears

1. With nothing selected, run **Create Unit** from the **Shelving** toolbar
   or menu.

Expected: alongside the new `ShelvingUnit`, a **Material Catalog** group
appears in the tree, holding four `App::VarSet` entries (one per stock item
in `freecad.Shelving.default_catalog.DEFAULT_CATALOG`). Select one, such as
**18 mm birch plywood**: the property editor shows `MaterialId`,
`Description`, `Thickness`, `MaterialType`, and `NominalThickness` directly,
with no group prefix and no dialog. `Thickness` shows with units (`18 mm`).

### 2. Change a thickness and confirm nothing moves until Reflow All runs

1. Select the **18 mm birch plywood** entry. In the property editor, change
   `Thickness` from `18 mm` to `25 mm`.

Expected: nothing in the 3D view moves. Reflow runs only as an explicit
command, not through FreeCAD's automatic recompute; a property edit alone
never touches a board.

2. With nothing selected, run **Reflow All** from the **Shelving** toolbar
   or menu.

Expected: the Report view prints one line for `ShelvingUnit`, in the same
`updated N, created N, deleted N, left alone N` shape **Resize Unit**
prints. **Bottom**, **Top**, and both sides are now 25 mm thick (check
`Height` on **Bottom**, or measure in the 3D view), while the unit's outside
size (600 × 300 × 900, or whatever you last resized it to) is unchanged:
the interior bay absorbed the extra 7 mm on each of the two Z-axis boards.

### 3. Add a material, leave it unedited, then assign it to one board and reflow

1. Run **Add Material** from the **Shelving** toolbar or menu.

Expected: a new entry named **New material** appears in the **Material
Catalog** group and is selected, so the property editor already shows its
properties: `MaterialId` reads `new_material`, `Thickness` reads `0 mm`.

2. Leaving the new entry exactly as it is (`Thickness` still `0 mm`), select
   nothing and run **Reflow All**, exercising the existing unit while an
   incomplete entry sits unused in the catalog.

Expected: the Report view prints a `catalog entry skipped: <New material's
object name>: Thickness must be greater than zero, got 0 mm` line, followed
by the normal `ShelvingUnit` line reporting the reflow as usual (`updated
0` if nothing changed since case 2, or otherwise consistent with whatever
state the unit was left in). Nothing about the unit is refused: the
unfinished entry sits in the catalog unusable, but no board references it,
so it never blocks a unit that doesn't need it (sh-019 review round 2, F1).
Compare case 4 of the M6 section, where a genuinely invalid *board* refuses
the whole scan and names the offenders: an unreferenced, merely incomplete
catalog entry must not do the same.

3. Select the new entry again and change `MaterialId` to something
   memorable (`oak6`, say), `Thickness` to `6 mm`, and `MaterialType` to
   `hardwood`.
4. Select **Bottom** (or any other board) and change its `ShelvingMaterial`
   property from `ply18` to `oak6`.
5. Run **Reflow All**.

Expected: no `catalog entry skipped` line this time, since every entry now
validates. **Bottom** is now 6 mm thick; every other board is unaffected.
The Report view's `ShelvingUnit` line shows `updated 4`. Running **Reflow
All** again with `ShelvingMaterial` left at `oak6` reproduces the same
result rather than drifting, since the stored id, not thickness matching,
is what a rescan resolves it by.

## M9 — The elevation editor

Prerequisite: a FreeCAD 1.0 or later install with this workbench on its
addon path, and **View → Panels → Report view** open.

Every case or group of cases opens with a **Start** line naming the state
it expects. Cases grouped under one heading run in order in one sitting,
each continuing from where the previous case left off. Two starting points
recur:

- **Fresh unit**: **File → New**, then **Create Unit** from the
  **Shelving** toolbar. No panel is open.
- **Shelf unit**: a fresh unit, then select its container (`ShelvingUnit`)
  and run **Edit Unit**, click the open bay, and click **Add Shelf**. The
  panel stays open showing a lower bay, a shelf, and an upper bay.

### Cases 1-6: one editing session on a fresh unit

**Start:** a fresh unit.

#### 1. Open the panel and confirm it docks and matches the 3D view

1. Select the unit's container (`ShelvingUnit`) and run **Edit Unit** from
   the **Shelving** toolbar or menu.

Expected: a task panel opens and docks in the Tasks tab (it does not float
as a separate window), titled **Edit Unit**, showing a flat elevation of
the unit: one rectangle per bay, per void, and per board, legible at a
glance and matching the shape and proportions of the same unit in the 3D
view. **OK** and **Cancel** buttons are present; **Add Divider**, **Add
Shelf**, and **Delete** are present but disabled, since nothing is selected
yet.

#### 2. Click a compartment and confirm only the Add buttons enable

1. Click the open bay in the elevation.

Expected: that bay's rectangle draws distinctly from the others (a visibly
different outline), and stays that way until a different item is clicked.
**Add Divider** and **Add Shelf** enable; **Delete** stays disabled, since
a bay, not a board, is selected.

#### 3. Add a divider and confirm the elevation and the 3D view both follow

1. With the bay still selected, click **Add Divider**.

Expected: the elevation redraws immediately with a new **vertical** divider
board down the bay's middle, leaving two smaller bays side by side, both
roughly equal in size; no error notification appears. **Add Shelf** would
instead divide the bay top and bottom with a **horizontal** shelf.
Switching to the 3D view (without closing the panel) shows the same new
board as a real, positioned box, not only a drawing. Each edit runs the
workbench's real write path, so no separate preview exists that could
disagree with it. Click the new divider board: **Delete** enables and both
**Add** buttons disable, since a board, not a bay, is now selected.

#### 4. Delete a board that cannot be merged and confirm an error notification, not a crash

1. Click one of the unit's original outer boards (a side, the bottom, or
   the top) rather than the divider just created.
2. Click **Delete**.

Expected: a **Shelving** error pops up from FreeCAD's Notification Area
and shows in red in the status bar. It reports a refusal naming that board
(its neighbour on at least one side is not an open compartment). The
elevation is unchanged, the panel stays open and usable, and nothing in the
Report view suggests a crash or an unhandled exception.

#### 5. Delete the divider and confirm the merge reverses the split

1. Click the divider board created in case 3 and click **Delete**.

Expected: the elevation redraws back to the single original bay, and the
3D view shows the divider board gone, the two smaller bays merged back into
one open compartment matching what case 1 started from.

#### 6. Cancel and confirm the whole session reverses

1. Repeat case 3 (add the divider again).
2. Click **Cancel**.

Expected: the panel closes, and the document, in both the 3D view and a
fresh **Edit Unit** re-opened afterward, is exactly the fresh unit this
group started from: the new divider board is gone, and board count and
names match.

### 7. Commit and confirm one Undo reverses the whole session

**Start:** a fresh unit (the document cases 1-6 leave behind will do).

1. Select the container, run **Edit Unit**, click the bay, and click **Add
   Divider**.
2. Click **OK**.

Expected: the panel closes and the new board stays in the document (3D
view and elevation on the next **Edit Unit** open both show it).

3. Run **Edit → Undo** once (or `Ctrl+Z`).

Expected: the entire session reverses in that one undo step, back to the
document's state from before step 1. The panel opens one transaction for
the whole session rather than one per edit, so the undo reverses the whole
commit, not only the divider's own edit.

### 8. Open the editor from a board selection

**Start:** a fresh unit.

1. Click one of the unit's boards in the 3D view (or in the tree), then
   Ctrl-click a second board of the same unit.

Expected: **Edit Unit** is enabled, and running it opens the panel on that
unit, the same as selecting the container in case 1. Cancel the panel.

2. Create a second unit (**Create Unit**), then select one board from each
   unit.

Expected: **Edit Unit** is disabled, since the selection does not name a
single unit.

### 9. An editor-built layout survives a rescan (bug-006)

**Start:** a fresh unit.

1. Select the container, run **Edit Unit**, click the bay, and click **Add
   Divider**.
2. Select the left-hand opening and click **Add Shelf**.
3. Select the upper-left opening (the upper of the two equal halves the
   last shelf just made) and click **Add Shelf** again.
4. Click **OK**.
5. Run **Edit Unit** again, select the right-hand opening, and click
   **Add Shelf**.
6. Click **OK**.

Expected: at every step the elevation and the 3D view show only the new
board moving; neither shelf added on the left in steps 2-3 shifts when the
shelf on the right is added in step 5, and re-opening **Edit Unit** after
step 6 still shows both left-hand shelves exactly where steps 2-3 put them.

### Cases 10-14: dimensions in one editing session

**Start:**

1. **File → New**.
2. In the Python console, create a `VarSet` holding a length:

   ```python
   doc = App.ActiveDocument
   varset = doc.addObject("App::VarSet", "VarSet")
   varset.addProperty("App::PropertyLength", "Len")
   varset.Len = "300 mm"
   doc.recompute()
   ```

3. Run **Create Unit**, then continue as for a shelf unit: select the
   container, run **Edit Unit**, click the open bay, and click **Add
   Shelf**.

Dimensions overlapping one another in a crowded elevation is a known
defect (bug-009), not a failure of these cases.

#### 10. Type an exact opening and watch the rest redistribute

1. Click the lower bay.

Expected: the **Size** field shows the bay's current clear height, the
readout below it shows both `clear` and `spacing` values (spacing being 18
mm more, the shelf's thickness), and notes that the bay shares the leftover
space. A dimension is drawn over each bay: a line with an arrowhead at each
end, each tip touching a short witness line, labelled with its value, the
other value beside it in grey.

2. Type `300` in **Size** and press Return.

Expected: the shelf moves so the lower bay's dimension reads `300`; the upper
bay's dimension grows or shrinks by the difference, the 3D view follows,
the lower bay stays selected, and the panel stays open.

#### 11. Type an inch expression and confirm the readout resolves it

1. With the lower bay still selected, type `1" + 1/2"` and press Return.

Expected: the field and the dimension resolve it to 38.10 mm.

2. Type `1 + 1/2"` (no unit on the `1`) and press Return.

Expected: 13.70 mm. FreeCAD's length fields read a bare number as
millimetres even inside a sum, so this is 1 mm plus 12.70 mm; the workbench
passes the text to FreeCAD untouched and shows what FreeCAD made of it.

3. Type `12 1/2"`.

Expected: the panel stays where it is (no scroll jump) and nothing else
appears in it; the field behaves as any FreeCAD length field does with text
it cannot read.

4. Press Return.

Expected: nothing changes: the panel stays open and the lower bay is still
13.70 mm.

5. Press Tab.

Expected: the field goes back to 13.70 mm and the layout does not change.

#### 12. Bind the field to a VarSet and confirm it follows

1. With the lower bay still selected, type `VarSet.Len` and press Return.

Expected: the lower bay becomes 300 mm clear.

2. Click in **Size**, type `=`, enter `VarSet.Len - 20 mm` in the f(x) dialog
   and accept it.

Expected: the lower bay follows to 280 mm. While the panel is open a
`Shelving dimension (temporary)` object appears at the top of the tree; it
is gone once the panel closes at the end of case 14. Changing `VarSet.Len`
afterwards does not move the shelf, since the unit keeps only the resolved
size (bug-010).

3. Click the upper bay, click the lower bay again, type `250` and press
   Return.

Expected: the field's f(x) icon is white, meaning no expression is bound,
and the field accepts the typing; the lower bay becomes 250 mm.

#### 13. Drag a board and confirm the readout keeps its basis

1. With the lower bay still selected, set **Size** to `300`, then choose
   **Spacing (through the next board)**.

Expected: nothing moves; the dimension now runs from the bottom board's top
face through the shelf to the shelf's top face and reads `318`, with
`clear 300` beside it.

2. Drag the shelf up by a few centimetres and release.

Expected: the shelf follows the pointer, the lower bay becomes selected,
its dimension still spans through the shelf, and the basis control still
reads **Spacing**: only the number changed.

3. Drag the shelf down past the bottom board.

Expected: one **Shelving** error notification in plain words, however far
the drag goes, and the shelf stays at its last good position.

4. Click the shelf without moving the mouse.

Expected: the shelf is selected and **Delete** enables; the lower bay's
size does not change.

#### 14. Switch a dimension's basis and confirm nothing moves

1. Click the lower bay and switch between **Clear opening** and
   **Spacing** several times.

Expected: no board moves in the elevation or the 3D view; only the drawn
dimension changes, between spanning the lower bay alone and spanning on
through the shelf, with the two numbers trading places between label and
readout.

2. Click the upper bay.

Expected: the basis control is disabled and the upper bay's dimension shows
only its clear height. The board above it is the unit's top, which belongs
to the outer frame rather than the upper bay's own column, so the upper bay
has no board after it to measure a spacing through.

3. Click **Cancel**.

Expected: the panel closes, the unit is back to the fresh unit's single
bay, and the temporary object is gone from the tree.

### 15. Change the stock thickness and confirm spacings hold and clears move

**Start:** a fresh unit.

1. Select the container, run **Edit Unit**, click the bay, and click **Add
   Divider**. Click the left bay and click **Add Shelf**; click the right
   bay and click **Add Shelf**.
2. Click the left lower bay, choose **Spacing (through the next board)**,
   then type `300` and press Return.
3. Click the right lower bay, leave **Clear opening** chosen, type `282`,
   and press Return. Both shelves now sit at the same height.
4. Click **OK**.
5. In the materials group, select the `ply18` entry (**18 mm birch
   plywood**), change its `Thickness` from `18 mm` to `25 mm`, then run
   **Reflow All**.

Expected: the left shelf stays exactly where it was; the right shelf rises
by 7 mm, following the thicker bottom board.

### 16. Confirm the untagged-object list appears with nothing checked

**Start:** a fresh unit.

1. Add a **Part → Cube**, set its `Length` to `400 mm`, `Width` to `5 mm`,
   and `Height` to `400 mm` (thin front to back), then drag it onto the
   unit's container in the tree.
2. Select the container and run **Edit Unit**.

Expected: a box titled **Objects this workbench did not create** lists the
cube with the reason it is not part of the layout, its checkbox unchecked,
and text saying the workbench leaves such objects alone unless they are
selected. The reason wraps onto several lines rather than making the panel
scroll sideways. Make any edit: the cube stays where it is.

3. Check the cube and click **Remove Selected**, then **Cancel**.

Expected: the cube disappears on **Remove Selected** and returns on
**Cancel**. With nothing checked, **OK** keeps it.

### 17. An unsolvable size leaves the last good state

**Start:** a shelf unit.

1. Click the lower bay, type `5000`, and press Return.

Expected: a **Shelving** error notification explains in plain words that
the fixed sizes add up to more than the space available, naming how much
more, with no internal ids; the elevation and 3D view stay exactly as
before the attempt, and the panel stays open and usable.
