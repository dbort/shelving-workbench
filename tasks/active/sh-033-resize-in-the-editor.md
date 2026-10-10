---
id: sh-033
title: "Resize a unit in the editor panel"
---

# sh-033: Resize a unit in the editor panel

## Summary
The Edit Unit panel gains a Unit section with width, depth and height fields,
so a unit's outer size changes in the same place as everything else, inside
the session's one transaction, with the 3D view following each change. A
typed size applies on Return or when the field loses focus, and each spin
step applies at once, so stepping a dimension shows the unit grow or shrink
live. The separate Resize Unit command and its three dialogs go away.

## Must Have
- [ ] `pixi run tests` green.
- [ ] A core edit returns `unit` with a new outer size and its tree
      unchanged. It refuses, with `EditError`, a size that is not positive
      on any axis. Asserted in the core suite.
- [ ] `Session` resizes its unit inside the session transaction and returns
      an `EditFailure` on refusal, changing nothing. Asserted headless:
      - on a fresh `create_unit` unit, resizing to 600 x 300 x 1000 mm
        writes boards whose sides are 964 mm tall, and `cancel` restores
        every board's size and placement;
      - a size too small to hold the boards returns an `EditFailure`, and
        every board is unchanged;
      - on a copy of
        `tests/freecad/fixtures/woodworking_magic_start_default.FCStd`,
        resizing 40 mm taller leaves the plinth gap 100 mm and every board
        18 mm thick.
- [ ] In `tests/freecad_gui/`, the panel on a fresh unit:
      - shows a Unit section with width 600 mm, depth 300 mm and height
        900 mm;
      - typing 1000 mm in height and pressing Return makes the sides
        964 mm tall;
      - one spin step up on the width field, with no Return, changes the
        top board's length by that step;
      - a refused size reports the error, leaves every board unchanged,
        and the field shows the unit's current size again;
      - the fields show the new size after any resize, and stay correct
        after a split or a merge.
- [ ] `freecad/Shelving/commands/resize_unit.py` no longer exists, and the
      workbench registers no `Shelving_ResizeUnit` command.
      `unit_ops.resize_unit` and `unit_ops.unit_size_mm` remain.
- [ ] `docs/manual-qa.md` has no case that runs Resize Unit; its M7 resize
      cases use the panel's Unit section, and a new case steps a dimension
      with the spin arrows and watches the 3D view follow.
- [ ] `mypy --strict` clean.

## Advice

DECISIONS (user, 2026-10-10):
- **When a change applies:** on Return or when the field loses focus, as
  the opening size field does, and immediately on each spin step (arrow
  buttons, arrow keys, mouse wheel). Never on each keystroke: typing 800
  would pass through 8 and 80.
- **Resize Unit goes.** Edit Unit is the one place to change a unit's
  size. Keep `unit_ops.resize_unit` and `unit_ops.unit_size_mm`: tests and
  scripts use them, and they are the headless path.
- **Fields only.** No dragging the unit's outer edges in the elevation:
  the elevation is still drawn at 1 mm per pixel (bug-004), so an outer
  edge is often off screen. Edge dragging belongs with that rework.
- **Placement:** a "Unit" group at the top of the panel, above the
  elevation, always visible whatever is selected.

CONSTRAINTS:
- Use the same widget as the opening size field (FreeCAD's
  `Gui::QuantitySpinBox` through the UI loader), so the unit fields accept
  what every FreeCAD length field accepts, including a `VarSet`
  expression, resolved once as the opening field does (bug-010 covers
  keeping it bound). Reuse the existing field class rather than a second
  copy of its Return, focus-out and restore handling.
- A spin step applying at once is new for this field class; give the unit
  fields that behavior. Leave the opening size field's behavior as it is.
- Field values come from `Session.unit.size_mm`, the scanned size, which
  leaves out set-aside parts such as a back panel (sh-032's resize fix).
- A resize keeps the unit's minimum corner where it is, as
  `unit_ops.resize_unit` does: width grows to the right of the elevation's
  low end, height upward, depth toward the depth axis's high end. Where
  the change goes inside the unit is the solver's existing rule.
- Refusals use the panel's existing error reporting (`report_error`, the
  same path the opening size field uses), and a drag-style flood of
  repeated failures must report once, as drags already do.
- Spin steps write the document once per step. Keep the step size the
  widget's default.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python: no bare `Any`, no bare
containers in signatures, `mypy --strict` clean. Shell stays simple: this
task adds no shell.

## Plan
- [x] **Step 1** (`freecad/Shelving/core/edit.py`, core tests): A unit-size edit returning the unit with a new outer size, refusing a non-positive axis with `EditError`.
- [x] **Step 2** (`freecad/Shelving/editor/session.py`): `Session` exposes the unit's size and a resize that goes through `_apply`, returning `EditFailure` on refusal.
- [x] **Step 3** (`freecad/Shelving/editor/panel.py`): The Unit group with width, depth and height fields built on the existing dimension field class, applying on Return, focus-out and each spin step, refreshed after every edit.
- [x] **Step 4** (`freecad/Shelving/commands/resize_unit.py`, `freecad/Shelving/init_gui.py`, tests that import the command): Remove the command and its registration; keep `unit_ops.resize_unit` and `unit_ops.unit_size_mm`.
- [x] **Step 5** (`tests/freecad/`, `tests/freecad_gui/`): The headless session and GUI panel Must Have tests.
- [x] **Step 6** (`docs/manual-qa.md`, `README.md`): Rewrite the M7 resize cases for the panel, add the spin-step case, and update any glossary or command list that names Resize Unit.

## Review log

### Round 1: REJECTED
- **F1: A wheel scroll past a limit floods the error report, and no test covers it** (`freecad/Shelving/editor/panel.py:146`): `_StepWatch` starts a new burst on every `Wheel` event and `_resize` reports once per burst, so a touchpad gesture past a refused size raises dozens of notifications. Treat an unbroken run of wheel events as one burst, and add a GUI test sending several `QWheelEvent`s past the limit that asserts exactly one report.
- **N1: A click in the text counts as a step** (`panel.py:144`): a `MouseButtonPress` on the line edit sets `stepping`, so a following context-menu paste or middle-click paste applies with no Return. Count mouse presses only on the spin box.
- **N2: The plinth gap is never checked against 100 mm** (`tests/freecad/test_editor_session.py:1110`): only Floor's z is compared before and after.
- **N3: The `ValueError` text is wrong for resize** (`freecad/Shelving/editor/session.py:312`): `_elevation_axes` still says "no depth_axis to split by direction".
- **N4: The roadmap still presents Resize Unit as current** (`docs/roadmap.md:249`).
- **N5: The `unit_ops` module docstring is hard to parse** (`freecad/Shelving/unit_ops.py:1`).
