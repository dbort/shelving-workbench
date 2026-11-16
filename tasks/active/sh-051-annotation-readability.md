---
id: sh-051
title: "Padlocks join the icon row, and dimension text sits on a tile"
---

# sh-051: Padlocks join the icon row, and dimension text sits on a tile

## Summary
In the editor, each opening's padlock moves from before its dimension's
text to the head of the row of constraint icons after it. It is drawn and
clicked the same way those icons are, so the floating Qt buttons and the
spaces that made room for them in the text go away. Each dimension's text
also gets a rounded tile of the view's background behind it, like the
icons have, so a size stays readable over a translucent opening fill. The
held board's padlock becomes the same kind of image, and a click anywhere
on a text's tile opens its size field.

## Must Have
- [ ] Each opening's dimension draws its padlock as a Coin image in the
      row after its text, in slot 0, with that opening's constraint icons
      after it from slot 1. The padlock's tile has the same side as a
      constraint icon's tile and the same `_ICON_GAP_PX` gap, and one
      placement function (`icon_center_px` or its successor) places both:
      a view test finds the padlock's tile centered where that function
      puts slot 0, and the first constraint icon where it puts slot 1.
- [ ] The padlock is closed for a locked opening and open for an
      unlocked one, in the dimension's color, on a tile of
      `Style.tile_rgb` with `TILE_RADIUS_PX` corners (pixel test with the
      background monkeypatched, as `test_every_padlock_sits_on_a_rounded_tile_of_the_view_background`
      does today).
- [ ] A press on a dimension's padlock toggles that opening's lock, moves
      no board, changes no selection, and opens no size field. A press on a
      constraint icon selects the constraint as it does today. Refusals
      still go through `report_error`.
- [ ] A selected held board draws a closed padlock image centered on
      `HeldPadlock.at_mm`, facing the camera and unpickable, and a press on
      it unlocks the openings holding the board, as the button does today.
- [ ] No padlock is a Qt widget: `ViewEditor` has no `padlocks`,
      `board_padlock` or `padlock_for`, and `view_editor.py` and
      `overlay.py` define none of `_padlock_button`, `_bind_index`,
      `padlock_spaces`, `Style.padlock_spaces` or `_PADLOCK_GAP_PX`.
- [ ] A dimension's drawn string is `length_text(size_mm)` with no leading
      spaces.
- [ ] Each dimension's text sits on a rounded tile of `Style.tile_rgb`.
      The tile spans the text's advance width and the label font's height
      (swapped for a vertical dimension), plus `TILE_PAD_PX` (scaled by
      the device pixel ratio) on every side, with `TILE_RADIUS_PX` corners.
      A pixel test with the background monkeypatched reads the tile color
      in the pad beside the text and a different color just outside it.
- [ ] Every dimension's lines, arrowheads and text draw over every text
      tile: a dimension too short to hold its text clear of its arrowheads
      still shows those arrowheads under its text.
- [ ] A press anywhere on a dimension's text tile, and nowhere else,
      opens that dimension's size field: a press just inside a long text's
      tile corner opens it, and a press 2 px outside the tile opens none.
      `LABEL_HIT_PX` is gone. A padlock or icon wins a press over a tile.
- [ ] Padlocks, the held padlock, icons and text tiles are redrawn for a
      screen of another device pixel ratio and follow a view resize, zoom
      and drag (the existing `test_padlocks.py` and `test_constraints.py`
      cases, rewritten for images).
- [ ] Neighboring rows of dimensions outside the unit keep their text
      tiles clear of each other and of the unit
      (`test_rows_of_dimensions_outside_the_unit_clear_it_and_each_other`
      measures tiles).
- [ ] An overlay padlock image function in `editor/overlay.py` is public,
      and `tasks/active/sh-049-constraint-list.md` points at it in place
      of `_padlock_icon`.
- [ ] `pyrefly check` passes over the changed code and `pixi run tests`
      is green.

## Advice
- **Padlock as a row icon (user decision):** a Coin `SoImage`, drawn and
  hit-tested like a constraint icon, replaces the `QToolButton`. It takes
  slot 0 because every opening has one, so it always sits right after
  the text and the constraint icons line up after it. It differs from a
  constraint icon in only three ways: it takes the dimension's color
  (`Style.label_rgb`) instead of an icon state color, a press toggles the
  lock instead of selecting, and it has no constraint id. Plan it in
  `elevation.py` beside the constraint icons, with the slot numbering in
  one place, and have `_sort_press` dispatch on what it hit. Do not keep a
  second placement path for padlocks.
- **One tile size for the row:** draw the padlock glyph at the constraint
  icon side (`icon_side_px()`, the Sketcher's `ConstraintSymbolSize`) on
  the same `Tile`, so one `icon_px` places and hits every row entry.
  Retire `_PADLOCK_PX`, and scale the glyph's insets and stroke from the
  side.
- **Held padlock too (user decision):** draw it with `PointMarker` at
  `HeldPadlock.at_mm` and hit-test the square it covers before the row
  icons. That leaves one way to draw a padlock and deletes the stylesheet
  tile and the `QIcon` redraw path (`_draw_padlock_icons`, `_icon_ratio`
  handling for padlocks).
- **No tooltip or hover state (user decision):** the Sketcher's
  constraint icons have neither, and neither do ours. The padlock loses
  its tooltip, accessible name and auto-raise highlight. Do not add hover
  tracking.
- **Text tile placement:** draw every text tile in one layer before every
  `SoDatumLabel`, with no depth test or write, as the icons' images draw.
  That way a tile hides only fills and faces, never any dimension's line,
  arrowhead or text. `SoDatumLabel` has no background field (FreeCAD
  1.1's `drawImage` fills its text image transparent), so the tile has to
  be the workbench's own image, sized from `label_metrics` in device
  pixels as `_text_width_px` measures text.
- **Text hit area (user decision):** replace `label_at`'s radius test
  with the text tile's rectangle, so what opens the field matches what is
  drawn. Its callers are `view_editor.py`, `tests/freecad_view/editor.py`
  (which passes `LABEL_HIT_PX + 4`), `tests/freecad_view/test_editor_input.py`
  and `tests/test_editor_elevation.py`. Update each.
- **Row spacing:** `_ROW_GAP_PX` stays 8. The tile pad takes 2 px from
  each side of that gap, which still clears. Raise it only if the outer
  rows test fails.
- Keep a padlock image function (`QImage`, locked flag, rgb, tile, side)
  public in `overlay.py`, beside `constraint_icon_image`. sh-049's
  constraint list wraps it in a `QIcon`, so update its task file's pointer
  in the same change.
- **Typed Python:** applies. Model the row entry as a precise type (a
  dataclass or a union of `ConstraintIcon` and a padlock entry), with no
  bare containers in signatures.
- **Shell stays simple:** opted out. The task touches no shell.
- **Follow FreeCAD's own tools:** the padlock now follows the Sketcher's
  constraint icons (a Coin image in the view, hit-tested by the edit
  mode, with no tooltip). The text tile has no Sketcher precedent: its
  dimension text draws on a transparent background. It is built anyway
  (user decision) for the reason the icon tiles exist: the openings'
  translucent fills wash out text drawn straight on them.
- **Users never read the log:** satisfied. A lock toggle's refusal still
  reaches the Notification Area through `report_error`, and nothing new
  goes to the log.

## Plan
- [x] **Step 1** (`freecad/Shelving/editor/elevation.py`,
      `tests/test_editor_elevation.py`): plan a padlock row entry per
      label in slot 0 and shift constraint icon slots to start at 1. Make
      `icon_center_px` and `icon_at` cover both kinds, with docstrings
      that no longer mention padlock room. Replace `label_at`'s radius
      with a tile rectangle test that takes the label's tile size in
      device pixels, delete `LABEL_HIT_PX`, and update the elevation
      tests for slots, hits and the tile test.
- [x] **Step 2** (`freecad/Shelving/editor/overlay.py`): drop
      `Style.padlock_spaces`, the `view_style` parameter and the leading
      spaces in `label_string`. Add the public padlock image function,
      moved from `view_editor._padlock_icon` and drawn on a `Tile` at a
      given side. Add a text tile image function. Make `IconNode` (or a
      sibling) carry a padlock row entry, and give text tiles their own
      layer drawn before the dimensions.
- [x] **Step 3** (`freecad/Shelving/editor/view_editor.py`): delete the
      padlock button pool, `board_padlock`, `padlock_for`,
      `_padlock_button`, `_bind_index`, `padlock_spaces`, `_PADLOCK_*`,
      `_draw_padlock_icons` and the padlock part of `_place_widgets`.
      Draw padlocks with the row icons in `_draw_icons`, the held padlock
      as a `PointMarker`, and text tiles for every label, all redrawn in
      `_refit` on a ratio change. In `_sort_press`, check the arrow, then
      the held padlock, then row entries, toggling a lock or selecting a
      constraint by kind, then text tiles. Expose whatever public reads
      the tests need, such as a padlock's or text tile's center or rect
      in logical pixels, in the shape `icon_center` has.
- [x] **Step 4** (`tests/freecad_view/test_padlocks.py`,
      `tests/freecad_view/test_constraints.py`,
      `tests/freecad_view/test_editor_drawing.py`,
      `tests/freecad_view/test_multi_selection.py`,
      `tests/freecad_view/test_editor_input.py`,
      `tests/freecad_view/editor.py`): rewrite padlock tests to press
      images at their computed centers instead of clicking buttons, and
      to read padlock pixels from the drawn image. Replace
      `test_a_padlock_sits_in_a_blank_of_its_line_just_before_the_first_digit`
      with the slot-0 placement test. Measure text rects without padlock
      room (`_text_rect` and the outer-rows test use tiles). Assert the
      held padlock through its image instead of `board_padlock.isVisible()`.
      Add the text tile pixel, short-dimension arrowhead and tile hit
      tests from the Must Haves.
- [x] **Step 5** (`docs/scope-and-design.md`,
      `freecad/Shelving/qa/cases/30-editor.toml`,
      `.claude/docs/freecad-notes.md`,
      `tasks/active/sh-049-constraint-list.md`): describe the padlock as
      the head of the icon row and the text's tile in the design doc.
      Update the `editor.padlocks` case so its expectations say each
      padlock leads the row after its text and each size reads on its own
      tile over the opening fills. Update the Equal/Even case's "clear of
      it and of the padlock" wording to the icon following the padlock.
      Make the background note name the text tiles too, and point sh-049
      at the public padlock image function.
- [x] **Step 6**: run `pyrefly check` and `pixi run tests`, and fix
      failures until both are green.

## Review log
