---
id: sh-023
title: "The preferences page"
blocked_by: [sh-021]
---

# sh-023: The preferences page

## Summary
A preferences page holding the five values that are currently constants: the
starter unit's width, height and depth, and the snap and joint-clearance
tolerances scanning uses. The tolerances matter because they are
what someone diagnosing a refusal needs to reach, and editing the source is not
a reasonable answer. A Developer group holds two toggles, the timing log and
the QA wizard, both off by default. Milestone M10, part 2 of 3.

## Must Have
- [ ] `pixi run tests` green.
- [ ] A preferences page appears under FreeCAD's Shelving group holding exactly
      five values: `CreateWidth`, `CreateHeight`, `CreateDepth`,
      `SnapTolerance`, `JointClearance`, and a Developer group holding two
      toggles, `DebugLog` and `QAWizard`, both off by default.
- [ ] `freecad.Shelving.debug_log.is_enabled` and
      `freecad.Shelving.qa.is_enabled` read the Developer toggles, replacing
      their module flags.
- [ ] `freecad/Shelving/preferences.py` exports a typed reader per value, each
      returning the stored value or the module's documented default, and each
      falling back to that default rather than raising on a missing, malformed
      or out-of-range stored value.
- [ ] Create Unit takes its dimensions from preferences; scanning takes both
      tolerances from preferences. No command reads a hard-coded constant for
      any of the five.
- [ ] The defaults equal the constants those call sites use today, so a user who
      never opens the page sees no behavior change. Asserted by comparing each
      reader's default against the core constant it replaces.
- [ ] A non-positive dimension, a non-positive tolerance, and a snap tolerance at
      or above the joint clearance each fall back to the default and report once
      to the report view rather than failing a command.
- [ ] The readers are tested without FreeCAD's parameter system by injecting a
      mapping, so every fallback path is covered in the fast suite.
- [ ] `tools/freecad_prefs_smoke.py` prints `shelving prefs OK` and
      `tools/run-tests.sh` greps for it.
- [ ] A QA case in `freecad/Shelving/qa/cases/` covers changing a preference
      and seeing it take effect.
- [ ] `mypy --strict` clean.

## Advice

FIVE VALUES, NO MORE. The page holds what a user changes often and what someone
diagnosing a refusal needs: the starter unit's three dimensions and the two
tolerances. There is no default-material preference (user decision,
2026-10-09, during sh-030's planning): Create Unit uses FreeCAD's Default
material, and a board's material belongs to FreeCAD and the Woodworking
workbench. Do NOT add preferences for color behavior, label style, or
anything else with one obviously right answer; that is how a preferences page
becomes unmaintainable, and every added value is a branch every command carries
forever.

THE DEVELOPER GROUP (user, 2026-10-10, during sh-034's planning) sits apart
from the five: it holds the timing log and QA wizard toggles, which are
module flags until this page exists. Both are on by default as flags and off
by default as preferences, since only developers need either.

WHY THE TOLERANCES ARE HERE and the other constants are not: real geometry has
coincident edges disagreeing by up to 0.09 mm, and a user whose model is worse
than that gets a refusal with no way forward except editing the source.
Everything else in the core is a design decision rather than a fit to somebody's
geometry.

A READER NEVER RAISES. FreeCAD's parameter store returns whatever was last
written, including values written by a previous version or by hand. Every reader
validates and falls back to its documented default on anything missing,
malformed, or out of range, and reports once so a user learns their setting was
ignored rather than silently getting different behavior. A command must not
fail because a preference is bad.

CROSS-VALIDATION MATTERS FOR THE TOLERANCES. A snap tolerance at or above the
joint clearance makes scanning incoherent: lines that should merge as one grid
line and gaps that should read as joints stop being distinguishable. Reject that
combination in the reader, falling back to both defaults together rather than
mixing a stored value with a default.

DEFAULTS MUST EQUAL TODAY'S CONSTANTS, and a test must assert it against the
core constants rather than repeating the numbers. A user who never opens the
page must see no change at all, and a literal copied into the preferences module
would drift the first time the core value changes.

TEST WITHOUT FREECAD'S PARAMETER SYSTEM. Take the parameter source as an
injected mapping with a small protocol, so the fast suite covers every fallback
and cross-validation path, and the FreeCAD-backed implementation is a thin
adapter. Only the adapter and the page registration need the smoke.

THE PAGE ITSELF is a `.ui` file registered through
`FreeCADGui.addPreferencePage`, the standard mechanism, with each widget bound
to its parameter path by FreeCAD's own preference widgets so the page needs no
save logic. Register it from `init_gui` behind the headless-safe guard. The page
cannot be exercised under `freecadcmd`, so the smoke covers the readers and the
registration call, and a manual case covers the page appearing.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, a `Protocol` for the injected
parameter source rather than a bare `dict`, `mypy --strict` clean. Shell stays
simple applies: the only shell edit is adding a smoke block to
`tools/run-tests.sh` in the same shape as the existing ones.

Every length identifier carries `_mm`.

## Plan

- [ ] **Step 1** (`freecad/Shelving/preferences.py`, tests): Create the module with an injected parameter source. A `Protocol` with typed getters for a float, a string and a bool. One reader per value, each carrying its documented default as a module constant imported from the core where one exists, validating and falling back. `read_tolerances()` returning both together and falling back to both defaults when the snap is at or above the clearance. A reporting hook the caller supplies, so the module itself does not import FreeCAD. Tests over an injected mapping covering: each value read cleanly; each missing, each malformed, each out of range; the tolerance cross-validation; and an assertion that every default equals the core constant it replaces.

- [ ] **Step 2** (`freecad/Shelving/preferences.py`): Add the FreeCAD-backed adapter implementing the protocol over `FreeCAD.ParamGet` under this workbench's parameter path, and a module-level accessor returning readers bound to it. Keep the adapter thin: no validation lives here, only the parameter reads.

- [ ] **Step 3** (`freecad/Shelving/unit_ops.py`, `freecad/Shelving/container.py`, `freecad/Shelving/commands/`, `freecad/Shelving/debug_log.py`, `freecad/Shelving/qa/__init__.py`): Replace every hard-coded use of the five values with a preferences read, and make `debug_log.is_enabled` and `qa.is_enabled` read the two Developer toggles instead of their module flags. Create Unit takes its three; the read path takes both tolerances and passes them to `scan`. Grep for the constants afterwards and confirm no command names one directly. Route the reporting hook to the report view so an ignored preference is visible.

- [ ] **Step 4** (`freecad/Shelving/resources/preferences.ui`, `freecad/Shelving/init_gui.py`): Create the page with FreeCAD's own preference widgets bound to the five parameter paths and the two Developer toggles, grouped as starter unit, tolerances and Developer, each with a tooltip saying what it affects and, for the tolerances, what a refusal looks like when they are wrong. Register it from `init_gui` with `FreeCADGui.addPreferencePage` behind the headless-safe guard.

- [ ] **Step 5** (`tools/freecad_prefs_smoke.py`, `tools/run-tests.sh`, `freecad/Shelving/qa/cases/`): The headless check. Assert: the readers bound to FreeCAD's parameter store return the documented defaults on a clean profile; writing a value through `ParamGet` changes what Create Unit produces; writing a bad value leaves behavior at the default and reports; the tolerance cross-validation fires when both are written incompatibly; and registering the page does not raise when the GUI is absent. Print `shelving prefs OK` and add a matching block to `tools/run-tests.sh`. Add a QA case in `freecad/Shelving/qa/cases/` for opening the page, changing the starter width, and creating a unit at the new size.

## Review log
