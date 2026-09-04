# Manual QA

A living catalog of checks a human runs in the FreeCAD GUI. Some behavior has no
headless assertion yet: property-editor reflow, toolbar and menu wiring, and
tree presentation only exist once a real `FreeCADGui` is running.

Every case here is a candidate for automation. When a headless path to a check
becomes possible, move it into `tools/freecad_object_smoke.py` (run by
`pixi run tests`) and delete it from this file. The commit history keeps the
record; this file tracks only what still needs a human.

Each case is numbered steps followed by an explicit expected result, written so
someone who did not build the feature can run it. Cases are grouped by
milestone.

## M3 — `ShelvingUnit`

Prerequisite: a FreeCAD 1.0 install with this workbench on its addon path, and a
new empty document (`Ctrl+N`).

### 1. Workbench exposes the command

1. Open the workbench selector and switch to **Shelving**.
2. Look at the toolbar area and the menu bar.

Expected: a **Shelving** toolbar and a **Shelving** menu are present, each
holding a single **Create Unit** entry with the workbench icon.

### 2. Create Unit seeds one unit with four named planks

1. With a document open, run **Create Unit** from the toolbar or the menu.

Expected: the tree gains one `ShelvingUnit` container. Expanding it shows a
`ShelvingUnitDriver` plus four plank objects labelled `Bottom`, `Top`,
`Left Side`, and `Right Side`. The 3D view shows a closed box 900 mm wide,
1800 mm tall, and 300 mm deep, with the top and bottom running the full width
and the two sides captured between them.

### 3. The scalar properties reflow the planks

1. Select the `ShelvingUnitDriver` and open the property editor.
2. Set **Width** to `1000 mm`. Recompute if it does not happen automatically.
3. Set **Height** to `2000 mm`.
4. Set **Depth** to `400 mm`.

Expected: after each edit the shell planks resize and reposition to match. The
right side sits at the new width minus one panel thickness, the top sits at the
new height minus one thickness, and every plank is the new depth.

### 4. `DefaultMaterial` re-thicknesses the shell

1. On the `ShelvingUnitDriver`, change **DefaultMaterial** from `ply18` to
   `ply12`. Recompute.

Expected: all four shell planks become 12 mm thick (the `ply12` catalog
thickness) and the sides shift to stay captured between the thinner top and
bottom. Switching back to `ply18` restores 18 mm.

### 5. Hand-edited `Layout` adds shelves

1. On the `ShelvingUnitDriver`, set the property editor to show hidden
   properties (right-click in the editor, **Show hidden**).
2. Edit **Layout**: replace the root `{"kind": "leaf", ...}` with a
   `{"kind": "split", "orientation": "horizontal", ...}` node carrying three
   `leaf` children, three `fill` rules, and two dividers. Keep the outer
   `carcass` `id` unchanged.
3. Recompute.

Expected: two new plank objects labelled `Shelf 1` and `Shelf 2` appear under
the container, spanning the interior width at evenly spaced heights. The four
shell planks keep their identity and labels.

### 6. A renamed plank keeps its name

1. Rename one plank's **Label** in the tree (for example `Bottom` to
   `Base panel`).
2. Change **Width** on the driver and recompute.

Expected: the plank still reflows to the new size, and its label stays
`Base panel`. Generated labels are written only when a plank is first created.

### 7. An over-constrained layout shows an error with no stale geometry

1. On the `ShelvingUnitDriver`, edit **Layout** so a split's `fixed` opening
   sizes add up to more than the space available (for example two `fixed` rules
   of `5000` each in a unit 1800 mm tall).
2. Recompute.

Expected: the `ShelvingUnitDriver` shows a recompute-error marker in the tree,
the report view names the solver overflow, and the 3D view still shows the last
good geometry. No plank is added or removed, and **Layout** still holds the
text just entered (`execute` does not rewrite it on failure). Fixing the sizes
and recomputing clears the error.
