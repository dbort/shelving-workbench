---
id: sh-043
title: "Choose the unit's fixed point"
blocked_by: [sh-042]
---

# sh-043: Choose the unit's fixed point

## Summary
A unit's fixed point is the spot that stays put when its size changes. Edit
Unit's task panel gets a choice beside each of Width, Height and Depth: a
wall-mounted shelf keeps its back where it is when it gets deeper, and a
free-standing piece keeps its front. The 3D view marks the fixed point
with a small camera-facing marker. Every unit starts at its minimum
corner, which is how units behave today. Milestone M15.

## Must Have
- [x] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [x] Each model axis of a unit has a fixed side, one of the minimum end,
      the center, or the maximum end, stored on the container with the
      unit's other properties. A container without the stored value reads
      as the minimum end on every axis.
- [x] Resizing a unit along an axis keeps that axis's fixed side at its
      container coordinate within 1e-6 mm: the low face for the minimum
      end, the midpoint for the center, the high face for the maximum
      end. This holds through `Session.resize` and through
      `unit_ops.resize_unit`, on a unit offset from the container's origin
      as sh-042's tests build one.
- [x] Edit Unit's task panel shows a choice beside each of the Width,
      Height and Depth fields, offering "Left", "Center", "Right" for
      Width, "Bottom", "Center", "Top" for Height, and "Front", "Center",
      "Back" for Depth. Each label names the side as the editor's
      elevation frame shows it: with the front at the maximum Y, "Front"
      is the maximum end of Y and "Left" is the maximum end of X; with the
      facing unknown, "Front" is the end `elevation_frame` faces. The
      Unit box is a grid whose first row heads the fields' column "Size"
      and the choices' column "Fixed point". The "Fixed point" header
      draws the marker before its text, in the marker's View preference
      color, as tall as the font's capital letters and on the text's
      baseline.
- [x] Changing a choice is one undo step, "Set Fixed Point", inside the
      edit and after Close, and leaves every board's placement unchanged.
      The choice survives Close, reopening Edit Unit, and a rescan.
- [x] While Edit Unit is open, the 3D view shows the marker described in
      `## Advice` at the fixed point's document position on the unit's
      bounding box, facing the camera at every orientation, drawn over the
      boards, and moving to the new spot when a choice changes, when the
      unit resizes, and on Undo and Redo. A click on the marker does what
      the same click would do with no marker there.
- [x] The marker's image is redrawn at the view's device pixel ratio when
      it changes, as sh-041's padlocks are.
- [x] `README.md`'s glossary defines "Fixed point" in user terms, and
      `tests/test_readme_glossary.py` passes.
- [x] `freecad/Shelving/qa/cases/30-editor.toml` gains a case for what no
      test asserts: whether the marker is legible and sharp on a HiDPI
      screen at several zoom levels and orientations, and whether it reads
      as the point that stays put.
- [x] `docs/scope-and-design.md` describes the fixed point: its choices,
      the default, where it is stored, and the marker.

## Advice

DECISIONS (user, 2026-10-16, `/new-task`):
- **Every axis has three choices,** low side, center, high side, as
  PartDesign Pad offers one-sided, reversed and symmetric: a wall cabinet
  hung by its top keeps its top, and a unit centered on a wall keeps its
  center.
- **The default is the minimum corner on every axis,** as a `Part::Box`
  grows from its placement; no existing unit changes behavior.
- **The choice sits beside each size field in the task panel,** where the
  unit's size already is. The 3D view only shows the fixed point; making
  the marker draggable or clickable is later work.
- **Labels follow the editor's view:** left, right, front and back are as
  Edit Unit's camera shows them, the side it turns to face being the
  front, so a guessed facing reads the way the user already sees it.
- **Changing the fixed point is an undo step,** "Set Fixed Point", in the
  editor's Title Case, as every other edit is.
- **The marker is a 2D billboard** tracking the 3D fixed point and always
  facing the camera, shaped like Inkscape's rotation-center marker: a plus
  whose four arms meet in a chamfered hub with a round hole at its center.
  The user's reference, an 8.81 x 8.81 mm SVG, filled black, as one path
  (with `transform="translate(-86.51875,-98.160417)"`):
  `m 89.86945,98.160417 v 1.7601 l -1.5906,1.590603 h -1.7601 v 2.1115 h 1.7601 l 1.5906,1.5906 v 1.7601 h 2.1115 v -1.7601 l 1.5906,-1.5906 h 1.76061 v -2.1115 h -1.76061 l -1.5906,-1.590603 v -1.7601 z m 1.05575,2.934193 a 1.4721817,1.4721817 0 0 1 1.47226,1.47226 1.4721817,1.4721817 0 0 1 -1.47226,1.47226 1.4721817,1.4721817 0 0 1 -1.47175,-1.47226 1.4721817,1.4721817 0 0 1 1.47175,-1.47226 z`

CONSTRAINTS:
- Store the fixed side per model axis, never per label: a facing found or
  corrected later renames the choice but keeps the physical side. Follow
  `ShelvingFacing`'s string enumeration in `properties.py` ("min",
  "center", "max"), so an older container without the property reads as
  "min".
- Carry the fixed point on the `Unit` beside `depth_axis` and
  `front_at_min`, and have `core.edit.set_unit_size` move sh-042's unit
  position by the size change times 0, 1/2 or 1 per axis. The session's
  undo steps already write the unit and its container properties
  together, so "Set Fixed Point" needs no undo path of its own.
- The fixed point is measured on the same bounding box as the unit's size
  and position: the layout boards only, never set-aside panels.
- Draw the marker in Coin as a screen-aligned image at a 3D point, as the
  Sketcher draws its constraint icons (`SoImage`), not as a Qt widget over
  the view: Coin keeps it on its point through camera moves and resizes,
  which a floating widget has to be re-placed for (sh-041's resize fix).
  Make it unpickable (`SoPickStyle.UNPICKABLE`), since it is view-only.
- Draw it in an existing View preference color the editor or the Sketcher
  already reads, never a hard-coded one, so it follows the user's theme.
  Size it about 16 logical pixels, beside the 14-pixel padlocks.

FOLLOW FREECAD'S OWN TOOLS: PartDesign Pad's one-sided, reversed and
symmetric directions are the three choices; the Sketcher's `SoImage`
constraint icons are the billboard; a `Part::Box`'s growth from its
placement is the default.

STANDING OBLIGATIONS (`CLAUDE.md`):
- Typed Python: precise types (a `Literal` for the three sides);
  `pyrefly check` clean.
- Shell stays simple: no shell.
- Users never read the log: the choice and the marker are the UI; nothing
  here refuses.

DECISIONS (user, 2026-10-20, QA of round 1):
- **The choices sit under a "Fixed point" column header.** A side's name
  alone ("Top") does not say what it picks. A header row ("Size", "Fixed
  point") over a grid names the column once, where a label on every row
  would repeat it; tooltips alone are invisible until hovered.
- **The header carries the marker** (user, 2026-10-20): the same cross
  and color as the 3D view, before the text, scaled to the height of a
  capital X, tying the column to the mark in the view. Paint it as a path
  in the label so it stays sharp at any font size and pixel ratio.

## Plan
- [x] **Step 1** (`freecad/Shelving/core/layout.py`, `freecad/Shelving/core/edit.py`): The per-axis fixed side on `Unit`, and `set_unit_size` keeping it; core tests for each side on each axis.
- [x] **Step 2** (`freecad/Shelving/properties.py`, `freecad/Shelving/container.py`, `freecad/Shelving/unit_ops.py`): Store and read the fixed point on the container, defaulting to "min"; FreeCAD-tier tests for the round trip and `resize_unit`.
- [x] **Step 3** (`freecad/Shelving/editor/session.py`, `freecad/Shelving/editor/panel.py`): The "Set Fixed Point" session edit and the three choices beside the size fields, labeled through the elevation frame; tests for the labels under each facing, the undo step and the placements it leaves alone.
- [x] **Step 4** (`freecad/Shelving/editor/overlay.py`, `freecad/Shelving/editor/view_editor.py`): The marker drawn at the fixed point, unpickable, redrawn at a new device pixel ratio; view-tier tests for its position, its updates and a click through it.
- [x] **Step 5** (`README.md`, `docs/scope-and-design.md`, `freecad/Shelving/qa/cases/30-editor.toml`): The glossary entry, the design prose and the marker's QA case.
- [x] **Step 6** (`freecad/Shelving/editor/panel.py`, `README.md`, `docs/scope-and-design.md`, `freecad/Shelving/qa/cases/30-editor.toml`): The Unit box as a grid under "Size" and "Fixed point" column headers, from QA feedback; a GUI test for the grid, and the docs and QA case naming the column.
- [x] **Step 7** (`freecad/Shelving/editor/panel.py`, `freecad/Shelving/editor/view_editor.py`, `freecad/Shelving/editor/overlay.py`, docs, QA case): The marker before the "Fixed point" header's text, from the user's request; a GUI test rendering it against the "F" in the preference color.

## Review log

### Round 1: APPROVED
- **N1: The pixel-ratio test checks the QImage, not the Coin node** (`tests/freecad_view/test_fixed_point.py:211`): the test asserts `editor.marker_image.size()` after the `DevicePixelRatioChange`, which `_draw_marker` sets before `PointMarker.set_image` runs, so an SoImage that stopped updating would still pass. Also assert the size of the SoImage's own image.
- **N2: The after-Close undo check does not look at the step's name** (`tests/freecad/test_editor_session.py:1334`): after `session.close()` the test undoes and checks the fixed point, but never asserts `doc.UndoNames[0] == "Set Fixed Point"` first; the Must Have names the step after Close too.
- **N3: Session.resize is tested at 1e-6 mm for only one fixed side** (`tests/freecad/test_editor_session.py:1314`): only "max" on X goes through `Session.resize` at 1e-6 mm; a center case on the offset unit would cover the Must Have's Session path directly. Not blocking, since every path goes through `set_unit_size`.
- **N4: One overlong line in the design doc** (`docs/scope-and-design.md:238`): the edited "On the container" bullet has a 100-character line; reflow to 79.
- **N5: "Origin of its local frame" carries over an existing ambiguity** (`README.md:104`): the glossary's "Local frame" entry puts the origin at the front-bottom-left corner, which is not the minimum corner for a unit whose front is at +Y, and does not describe a unit offset in its container. Not new here; consider tightening it in a later task.
- **N6: The marker may be tinted by transparent boards** (`freecad/Shelving/editor/overlay.py:469`): with depth test and write off, transparent board faces drawn in Coin's delayed pass could blend over the marker. Untested; if it matters, add a step with a transparent board to the `editor.fixed_point` QA case.

### Round 2: APPROVED
- **N1: New overlong line in the design doc** (`docs/scope-and-design.md:195`): 67ed91d left a 106-character line in the fixed point's panel paragraph; reflow it to 79 columns. Round 1's N4 line is also still unwrapped.
- **N2: The grid test does not pin the field's stretch** (`tests/freecad_gui/test_panel.py:731`): dropping `setColumnStretch(1, 1)` (`freecad/Shelving/editor/panel.py:255`) would pass the test; assert `layout.columnStretch(1) == 1` and `layout.columnStretch(2) == 0`.
- **N3: The combos' tooltip and accessible name are untested** (`freecad/Shelving/editor/panel.py:270`): no test asserts the per-dimension `_FIXED_TIPS` text; the gap predates 67ed91d.

### Round 3: REJECTED
- **F1: The marker sits above the baseline at device pixel ratios above 1** (`freecad/Shelving/editor/panel.py:155`): `marker_rect` takes the baseline from integer `QFontMetrics` and floor division, while `QPainter.drawText` centers the line with real-valued metrics. At ratio 2 the marker lands 1 to 4 device px above the "F" depending on point size. Use `QFontMetricsF` and real division, fix the comment, and add a test rendering the header into a ratio-2 `QImage` that compares rows in device pixels.
- **N1: Right-to-left text would leave the marker on the wrong side** (`freecad/Shelving/editor/panel.py:162`): fine for today's untranslated text; mirror the margin and paint origin when `text().isRightToLeft()` if translations arrive.
- **N2: New overlong line in the QA case** (`freecad/Shelving/qa/cases/30-editor.toml:322`): a 92-character line in the "choose" step; reflow it.
- **N3: Round 2's N3 is still open** (`freecad/Shelving/editor/panel.py:270`): no test asserts the `_FIXED_TIPS` tooltip or accessible name.

### Round 4: APPROVED
- **N1: The marker's top can still overshoot the "F" by 2 to 4 device px at some font sizes** (`freecad/Shelving/editor/panel.py:155`): the bottom holds within 1 device px from 7 to 18 pt at ratios 1 to 3, but `QFontMetricsF.capHeight()` is the 1x-hinted cap height while the glyph rasterizes at device resolution, so at 11 and 16 pt at ratio 2 the marker stands about one logical pixel taller. Judge it in the `editor.fixed_point` QA case, or take the side from the glyph's outline (`QPainterPath.addText`).
- **N2: The header test's docstring claims more than it checks** (`tests/freecad_gui/test_panel.py:806`): "within a device pixel at each pixel ratio and font size" covers only 9, 13.5 and 18 pt; narrow it or add an 11 pt case once N1 is settled.
- **N3: Right-to-left text is still unhandled** (`freecad/Shelving/editor/panel.py:162`): round 3's N1 stands as a note.
