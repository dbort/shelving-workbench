---
id: sh-022
title: "Appearance and error surfacing"
blocked_by: [sh-021]
---

# sh-022: Appearance and error surfacing

## Summary
A board's label is written once, when the board is created, so a user's own
names survive every edit, and a command rewrites them on request. A new board's
color already comes from the board it copies its stock from (sh-030). Makes
every refusal across the workbench say the same kind of thing: what failed,
which objects, and what to do. Milestone M10, part 1 of 3.

## Must Have
- [ ] `pixi run tests` green.
- [ ] `Shelving_RelabelUnit` rewrites every board's `Label` from its derived
      role. It acts on one selected container, runs in one transaction, and
      reports how many it changed.
- [ ] `Shelving_RelabelUnit` produces left and right names when the unit's
      facing is known and neutral ones when it is not. Asserted both ways on one
      document by setting `ShelvingFacing` between runs.
- [ ] Every command reports a refusal through one shared helper carrying a
      summary line, the offending object names, and a suggested next step.
      A test asserts each command's refusal path goes through it.
- [ ] A refusal selects its named objects in the 3D view, as sh-016's Scan does.
      Extended to every command that names objects.
- [ ] An over-constrained edit leaves no stale geometry: the document is at the
      last state that solved, asserted by comparing board sizes and placements
      before and after a refused operation.
- [ ] QA cases in `freecad/Shelving/qa/cases/` cover relabel and a refusal's
      appearance.
- [ ] `mypy --strict` clean.

## Advice

THE OWNERSHIP RULE, and everything here follows from it. The workbench states an
opinion when it CREATES something and never again. A board gets a label at
creation, and a color copied from its source board (sh-030); an update
rewrites neither. That is what makes sh-018's
promise true, that a rename and a color survive a resize, and it is asserted in
that task's smoke. Taking the opinion back is an explicit command, never a side
effect of an edit.

DO NOT ADD A VIEW PROVIDER. Boards are plain `Part::Box` objects with no proxy,
which is what lets a document open without this workbench.

NO COLOR COMMAND (user decision, 2026-10-09, during sh-030's planning): a
board's color comes from its source board and the editor's stock swap
(sh-031) changes it, so there is no color-by-material mapping and no
recolor command.

RELABEL IS NOT AUTOMATIC WHEN FACING CHANGES. A unit scanned without a facing
gets neutral side names; setting the facing later does not rewrite them, because
a label is never rewritten on an update and a user may have renamed one. The
relabel command is the answer, and its report says how many it changed so a user
knows their renames were overwritten.

REFUSALS ARE ONE SHAPE ACROSS THE WORKBENCH. A shared helper takes a summary,
the offending object names, and a suggested next step, prints them to the report
view in that order, and selects the objects. Route every command's failure path
through it. The value is that a user learns one format: what failed, which
objects, what to do. Do NOT invent a dialog; the report view is where FreeCAD's
own messages go and where sh-016 already puts a refusal.

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

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. Shell
stays simple does not apply; this task adds no shell.

Every length identifier carries `_mm`.

## Plan

- [ ] **Step 1** (`freecad/Shelving/unit_ops.py`): Add `relabel_unit(container)` rewriting every board's `Label` from its derived role and returning the count changed. It reads the container rather than taking a model, so it works on a unit that has never been scanned in this session. It opens no transaction.

- [ ] **Step 2** (`freecad/Shelving/report.py`): Create the shared refusal helper in the FreeCAD layer. `report_refusal(summary, objects, suggestion)` printing the three parts to the report view in a fixed order and selecting the named objects in the 3D view, guarded for a missing GUI. A table mapping each known refusal reason, the solver's and the scanner's, to its suggested next step, so a suggestion is data rather than prose repeated in every command. Route every existing command's failure path through it.

- [ ] **Step 3** (`freecad/Shelving/commands/`, `freecad/Shelving/init_gui.py`): Add `Shelving_RelabelUnit` in the established shape, requiring exactly one selected container, opening one transaction, calling `relabel_unit`, committing, and reporting the count changed. Add its id to `init_gui`'s `TOOLBAR_COMMANDS`.

- [ ] **Step 4** (`tests/freecad/test_write.py`, `freecad/Shelving/qa/cases/`): Extend the write tests: a board renamed by hand keeps its name through a resize and `relabel_unit` overwrites it and reports one changed; `relabel_unit` produces neutral side names with no facing set and left and right names after setting `ShelvingFacing`; and a refused operation leaves every board's size and placement unchanged. Add QA cases in `freecad/Shelving/qa/cases/` for relabel and for a refusal showing its summary, objects and suggestion while selecting the objects in the 3D view.

## Review log
