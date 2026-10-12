---
id: sh-022
title: "Refusals, and removing Scan Unit"
blocked_by: [sh-021]
---

# sh-022: Refusals, and removing Scan Unit

## Summary
Makes every refusal across the workbench say the same kind of thing: what
failed, which objects, and what to do, with those objects selected. With that
in place, Edit Unit tells a user everything Scan Unit did about a hand-built
unit, so Scan Unit and its text report are removed and Edit Unit is the one
way in. Milestone M10, part 1.

## Must Have
- [ ] `pixi run tests` green.
- [ ] Every command reports a refusal through one shared helper carrying a
      summary line, the offending object names, and a suggested next step.
      A test asserts each command's refusal path goes through it.
- [ ] A refusal selects its named objects in the 3D view. Extended to every
      command that names objects.
- [ ] Edit Unit on a hand-built container that does not scan refuses through
      the helper, naming and selecting the objects the scanner names, with a
      suggested next step. Asserted in `tests/freecad_gui/` on a container
      holding two overlapping boards.
- [ ] `Shelving_Scan` is not registered: absent from `init_gui`'s
      `TOOLBAR_COMMANDS` and the Shelving menu. `freecad/Shelving/commands/scan.py`,
      `freecad/Shelving/core/report.py` and
      `freecad/Shelving/core/tests/test_report.py` are deleted, and no file
      outside `tasks/completed/` names `Shelving_Scan`, `ScanCommand`,
      `Scan Unit` or `core.report`.
- [ ] An over-constrained edit leaves no stale geometry: the document is at the
      last state that solved, asserted by comparing board sizes and placements
      before and after a refused operation.
- [ ] `freecad/Shelving/qa/cases/10-scan.toml` runs on Edit Unit instead of
      Scan Unit, and QA cases cover a refusal's appearance.
- [ ] `mypy --strict` clean.

## Advice

ONE WAY IN (user decision, 2026-10-11). The goal is removing commands that
overlap another one, not lowering the command count. Edit Unit already opens
and scans a hand-built container (`container.unit_for_selection`), so Scan
Unit overlaps it. What only Scan Unit did, and where each goes:
- refusal with the offending objects selected: the shared helper, used by
  Edit Unit;
- the skipped-parts list: already the editor's left-alone list, with
  reasons;
- the text region tree (`core/report.py`): the elevation view shows the same
  tree, so it is deleted with its tests, not kept as a diagnostic;
- the "facing unknown" warning: dropped here. Flipping a unit's facing from
  the editor is later work on the roadmap.

EXPORT BOXES STAYS AS IT IS (user decision, 2026-10-11). It overlaps no other
command; it regenerates the core fixtures and captures a unit that will not
scan. Leave it on the toolbar and do not route its write through `scan`. Its
own "exactly one container" refusal goes through the helper like every other.

REFUSALS ARE ONE SHAPE ACROSS THE WORKBENCH. A shared helper takes a summary,
the offending object names, and a suggested next step, prints them to the report
view in that order, and selects the objects. Route every command's failure path
through it. The value is that a user learns one format: what failed, which
objects, what to do. Do NOT invent a dialog; the report view is where FreeCAD's
own messages go. Selecting the offenders is the behavior Scan Unit's
`_select_offenders` has today: clear the selection, then add each named object
that still exists.

THE SUGGESTED NEXT STEP IS NOT DECORATION. A refusal that names six objects and
stops leaves a user guessing. Each refusal reason gets a specific suggestion:
an unreadable part says what shape it found and that grouping or simplifying it
would help; an over-constrained layout names the region and says which sizes
compete. Write them as data beside the reason, not as prose scattered through
the commands.

NO STALE GEOMETRY, restating sh-020's rule because it is the milestone's verify
line. A refused operation changes nothing: the session and the commands both
reject an edit whole rather than writing part of it, so the document is always
at a state that solved.

THE EDITOR'S OWN EDIT REFUSALS STAY AS THEY ARE (user decision, 2026-10-11).
The helper covers the toolbar commands only. A refused split, merge, resize or
drag inside the open editor keeps sh-021's Notification Area popup through
`report_error`, with no suggestion line and no 3D selection: a refused edit
often names a region, which has no document object to select.

A REFUSAL POPS UP (user decision, 2026-10-11, after manual QA). A command's
refusal is easy to miss in the Report view alone, so `report_refusal` sends
its three lines as one message through `report_error`, the editor's
Notification Area call, which now lives in `refusals.py`. The message still
lands in the Report view; the selection is unchanged.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. Shell
stays simple does not apply; this task adds no shell.

Every length identifier carries `_mm`.

## Plan

- [x] **Step 1** (`freecad/Shelving/refusals.py`, `.claude/docs/code-map.md`): Create the shared refusal helper in the FreeCAD layer. `report_refusal(summary, objects, suggestion)` printing the three parts to the report view in a fixed order and selecting the named objects in the 3D view, guarded for a missing GUI. A table mapping each known refusal reason, the solver's and the scanner's, to its suggested next step, so a suggestion is data rather than prose repeated in every command. List the module in the code map, which `tests/test_code_map.py` requires.

- [x] **Step 2** (`freecad/Shelving/commands/edit_unit.py`, `export_boxes.py`, `create_unit.py`): Route every command's failure path through the helper. Edit Unit passes a `ScanError`'s objects from building the panel, so a hand-built unit that does not scan is refused with its offenders selected.

- [x] **Step 3** (`freecad/Shelving/commands/scan.py`, `freecad/Shelving/core/report.py`, `freecad/Shelving/core/tests/test_report.py`, `freecad/Shelving/init_gui.py`): Delete the three files. Remove `Shelving_Scan` from `TOOLBAR_COMMANDS` and `scan` from `Initialize`'s deferred imports.

- [x] **Step 4** (`tests/freecad/test_scan.py`, `.claude/docs/qa-wizard.md`): Update the remaining mentions. `test_scan.py`'s depth-axis test docstring (about line 405) cites `ScanCommand.Activated` and Scan Unit; restate it against the editor session's read and `resize_unit`, keeping the discrepancy it pins. The qa-wizard contract's instruction-line example becomes "Run Edit Unit.". Grep afterward for the names in the Must Have.

- [x] **Step 5** (`tests/freecad/`, `tests/freecad_gui/`): The every-command refusal test; the Edit Unit refusal test on overlapping boards, asserting the summary, the named objects, the suggestion and the 3D selection; and a refused operation leaving every board's size and placement unchanged.

- [x] **Step 6** (`freecad/Shelving/qa/cases/10-scan.toml`, `freecad/Shelving/qa/actions.py`): Move the case onto Edit Unit, keeping its id. The "scan" step opens the editor on TestUnit, showing two bays either side of Shelf; the "skipped-part" step shows Skewed in the left-alone list with its reason; the export step is unchanged; the "refusal" step runs Edit Unit and expects the summary, objects and suggestion in the Report view with Overlap and LeftSide selected. Follow `.claude/docs/qa-wizard.md`.

## Review log

### Round 1: APPROVED
- **N1: Roadmap box still names Scan Unit** (`docs/roadmap.md:12`): correctly left, since `pipeline.md` § Roadmap reserves box edits for `/ship`; `/ship` must tick or rename it, or the "no file names `Scan Unit`" Must Have stays false once the task file moves to `tasks/completed/`.
- **N2: Two Edit Unit refusal paths have no test** (`freecad/Shelving/commands/edit_unit.py:108`, `:152`): the `unexpected` catch and the `showDialog` failure (`task_panel_open`, which also cancels the session) go through the helper untested, as does the `_build` guard that cancels the transaction when building the form fails (`freecad/Shelving/editor/panel.py:565`). The Must Have is met at one path per command.
- **N3: Two next steps for no_slack_absorber** (`freecad/Shelving/refusals.py:78`): `describe_solve_error`'s summary already advises "Change a size, or leave one opening free" (`freecad/Shelving/core/solver.py:318-323`), and the `Next:` line then says to undo the hand move and resize in Edit Unit.
- **N4: no_thin_axis suggestion reads as describing the refused part** (`freecad/Shelving/refusals.py:42`): "A board is thinner in one direction than in the other two." reads as a claim about the part; "A board must be thinner..." states the rule.
- **N5: Ambiguous test docstring** (`tests/freecad/test_refusals.py`): "a refusal prints and selects nothing" can read as "prints nothing"; the test asserts it prints all three lines and selects nothing.

### Round 2: APPROVED
- **N1: Roadmap box still names Scan Unit** (`docs/roadmap.md:12`): carried over from round 1 and still correctly deferred to `/ship`, which ticks or renames the box; the Must Have's grep is clean once it does and the task file moves to `tasks/completed/`.
