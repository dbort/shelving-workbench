# Manual QA

Checks a human runs in the FreeCAD GUI, because they need a real display:
toolbar and task-panel wiring, notification popups, the 3D view following
an edit, and what an elevation looks like. Anything a test can assert
belongs in `tests/freecad/` or `tests/freecad_gui/` instead; when a case
becomes automatable, move it there and delete it here.

Each case lists numbered steps and an expected result, written for someone
who did not build the feature.

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

### Starting points

- **Fresh unit**: **File → New**, then **Create Unit** from the
  **Shelving** toolbar.
- **Shelf unit**: a fresh unit; select its container (`ShelvingUnit`), run
  **Edit Unit**, click the open bay, and click **Add Shelf**. The panel
  stays open.

## Scan

**Start:** **File → New**, then paste into the Python console:

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


add_box("Bottom", (600.0, 300.0, 18.0), (0.0, 0.0, 0.0))
add_box("Top", (600.0, 300.0, 18.0), (0.0, 0.0, 582.0))
add_box("LeftSide", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
add_box("RightSide", (18.0, 300.0, 564.0), (582.0, 0.0, 18.0))
add_box("Shelf", (564.0, 300.0, 18.0), (18.0, 0.0, 291.0))
doc.recompute()
```

### 1. Scan, export, and a refusal

1. Select **TestUnit** and run **Scan Unit**.

   Expected: the Report view prints the depth axis and size, a facing
   warning, and an indented tree with two bays either side of `Shelf`.
   Nothing in the document changes.

2. Add an unreadable part, then scan again:
   `add_box("Skewed", (100.0, 50.0, 20.0), (0.0, 400.0, 0.0), angle_deg=30.0); doc.recompute()`

   Expected: the same tree, followed by `skipped (1)` naming `Skewed` as
   not axis-aligned. The selection is untouched.

3. Save the document, select **TestUnit**, and run **Export Boxes**.

   Expected: `TestUnit.boxes.json` appears beside the saved file, and the
   Report view prints its path and how many boxes and skipped parts it
   holds.

4. Add a box overlapping a side, then scan again:
   `add_box("Overlap", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0)); doc.recompute()`

   Expected: `REFUSED: Overlap overlaps LeftSide`, and the 3D view's
   selection changes to **Overlap** and **LeftSide**, both visibly
   highlighted.

## Write

### 2. A board moved by hand within the joint clearance is corrected

**Start:** a fresh unit.

1. Select **Side 1** and change its `Placement` → `Position` → `x` from
   `0` to `2`, moving it 2 mm toward the center. A larger move, or one
   along another axis, makes a different layout or a refusal.
2. Select the container, run **Edit Unit**, type `1010` into **Height**,
   press Return, and click **OK**.

Expected: **Side 1** is back at `x = 0`, without being moved back by hand.

### 3. A document opens without the workbench

**Start:** a fresh unit, saved.

1. Quit FreeCAD, move the `shelving-workbench` symlink out of `Mod/`,
   restart, and open the saved document.

Expected: no error dialog and no Report-view warning about a missing
module; every board is present, correctly sized, where it was. Restore the
symlink afterward.

## Editor

Overlapping dimensions in a crowded elevation are a known defect
(bug-009), not a failure of these cases.

### 4. One editing session

**Start:** a fresh unit.

1. Select the container and run **Edit Unit**.

   Expected: a panel titled **Edit Unit** docks in the Tasks tab and shows
   an elevation matching the 3D view's shape and proportions. **Add
   Divider**, **Add Shelf** and **Delete** are disabled.

2. Click the open bay.

   Expected: its outline draws distinctly until something else is clicked.
   The two **Add** buttons enable; **Delete** stays disabled.

3. Click **Add Divider**.

   Expected: a vertical divider splits the bay in the elevation, and the
   3D view shows it as a real box while the panel is still open.

4. Click an outer board (a side, the top or the bottom) and click
   **Delete**.

   Expected: a **Shelving** error pops up from the Notification Area and
   shows in red in the status bar, saying in plain words, with no internal
   ids, that removing that board would not join two openings. Nothing
   changes and the panel stays usable.

5. Click the new divider and click **Delete**, then add it again and click
   **OK**.

   Expected: the merge redraws one bay; after **OK** the panel closes with
   the divider in place.

6. Run **Edit → Undo** once.

   Expected: the whole session reverses in one step.

### 5. Dimensions

**Start:** **File → New**, then in the Python console:

```python
doc = App.ActiveDocument
varset = doc.addObject("App::VarSet", "VarSet")
varset.addProperty("App::PropertyLength", "Len")
varset.Len = "300 mm"
doc.recompute()
```

Then continue as for a shelf unit.

1. Click the lower bay.

   Expected: a dimension over each bay: a line with an arrowhead at each
   end touching short witness lines, labeled with its value, the other
   basis's value beside it in gray. **Size** shows the clear height.

2. Type `300` in **Size** and press Return.

   Expected: the shelf moves in the elevation and the 3D view, and the
   upper bay's dimension absorbs the difference.

3. Choose **Spacing (through the next board)**.

   Expected: nothing moves; the dimension now runs through the shelf and
   reads `318`, with `clear 300` beside it.

4. Drag the shelf up a few centimeters with the mouse and release.

   Expected: the shelf follows the pointer, and the basis still reads
   **Spacing**.

5. Click **Size**, type `=`, enter `VarSet.Len - 20 mm` in the f(x)
   dialog, and accept.

   Expected: the lower bay follows to 280 mm. While the panel is open a
   `Shelving dimension (temporary)` object sits in the tree.

6. Click **Cancel**.

   Expected: the unit is back to a single bay, and the temporary object is
   gone.

### 6. Objects this workbench did not create

**Start:** a fresh unit.

1. Add a **Part → Cube** sized 400 × 5 × 400 mm (`Length`, `Width`,
   `Height`), drag it onto the unit's container in the tree, select the
   container, and run **Edit Unit**.

Expected: a box titled **Objects this workbench did not create** lists the
cube, unchecked, with a reason that wraps onto several lines rather than
making the panel scroll sideways.

### 7. Unit size controls

**Start:** a fresh unit; select the container and run **Edit Unit**.

1. Hold the **Height** field's up arrow, then turn the mouse wheel over
   **Width**.

   Expected: the unit grows in the 3D view at every step of the held arrow
   and changes with every notch of the wheel.

2. Hold the **Height** down arrow until the unit stops shrinking.

   Expected: a single error in the Notification Area, and the field shows
   the last height that worked.

3. Click **Cancel**.

   Expected: the unit is back to 600 × 300 × 900 mm.
