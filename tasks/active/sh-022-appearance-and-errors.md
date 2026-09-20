---
id: sh-022
title: "Appearance and error surfacing"
current_agent: implementer
current_phase: planning
review_rejections: 0
blocked_by: [sh-021]
---

# sh-022: Appearance and error surfacing

## Summary
A new board takes its material's colour when it is written, so a unit is
readable the moment it exists, while an update never touches colour and a label
is never rewritten, so a user's own choices survive. Two commands take the
workbench's opinion back on request, one for colour and one for labels. Makes
every refusal across the workbench say the same kind of thing: what failed,
which objects, and what to do. Milestone M10, part 1 of 3.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] A board created by the write path gets `ShapeColor` from its material.
      An update never sets `ShapeColor`. Asserted: create, recolour one board by
      hand, resize, and the hand colour survives.
- [ ] Colour comes from a deterministic mapping of material id to colour, stable
      across sessions and documents, so the same material is the same colour
      everywhere. Asserted by mapping the same id twice in one test.
- [ ] `Shelving_RecolourUnit` sets every board's `ShapeColor` from its material,
      and `Shelving_RelabelUnit` rewrites every board's `Label` from its derived
      role. Both act on one selected container, both run in one transaction,
      and both report how many they changed.
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
- [ ] `docs/manual-qa.md` gains M10 cases for colour, relabel, and a refusal's
      appearance.
- [ ] `mypy --strict` clean.

## Frontier Advice

THE OWNERSHIP RULE, and everything here follows from it. The workbench states an
opinion when it CREATES something and never again. A board gets a colour and a
label at creation; an update rewrites neither. That is what makes sh-018's
promise true, that a rename and a colour survive a resize, and it is asserted in
that task's smoke. Taking the opinion back is an explicit command, never a side
effect of an edit.

DO NOT ADD A VIEW PROVIDER. Boards are plain `Part::Box` objects with no proxy,
which is what lets a document open without this workbench. Colour is set
directly on `obj.ViewObject.ShapeColor`. `ViewObject` is `None` under
`freecadcmd`, so guard every access and let the headless path skip colouring
entirely; the smoke asserts the guard rather than the colour.

COLOUR MUST BE DETERMINISTIC FROM THE MATERIAL ID, not assigned in encounter
order. A hash of the id into a fixed palette gives the same material the same
colour in every unit and every document, which is the whole point of colouring
by material. Encounter order would make two units disagree. Keep the palette
small and distinguishable, and record in a comment that it is chosen for
distinguishability rather than realism, because nobody is fooled by a flat
colour standing in for birch.

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
compete; a thickness matching no catalog entry says to add one. Write them as
data beside the reason, not as prose scattered through the commands.

NO STALE GEOMETRY, restating sh-020's rule because it is the milestone's verify
line. A refused operation changes nothing: the session and the commands both
reject an edit whole rather than writing part of it, so the document is always
at a state that solved.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. Shell
stays simple does not apply; this task adds no shell.

Every length identifier carries `_mm`.

## Execution Plan

- [ ] **Step 1** (`shelving_core/appearance.py`, `shelving_core/tests/test_appearance.py`): Create the deterministic colour mapping in the core, so it is testable without FreeCAD and the SVG renderer can share it. `colour_for(material_id) -> tuple[float, float, float]` hashing the id into a fixed palette of distinguishable colours, documented as chosen for distinguishability rather than realism. Tests: the same id maps to the same colour across calls; distinct ids in a realistic catalog map to distinct colours; every component is within range.

- [ ] **Step 2** (`shelving/container.py`): Set colour and label on creation only. When the write path creates a board, set `Label` from its derived role, which sh-018 already does, and set `ViewObject.ShapeColor` from `shelving_core.appearance.colour_for`, guarding for `ViewObject` being `None` headlessly. The update path must touch neither. Extend the write result to report how many boards were coloured, so the commands can say so.

- [ ] **Step 3** (`shelving/unit_ops.py`): Add `recolour_unit(container)` setting every board's `ShapeColor` from its stored material and returning the count changed, and `relabel_unit(container)` rewriting every board's `Label` from its derived role and returning the count changed. Both read the container rather than taking a model, so they work on a unit that has never been scanned in this session. Neither opens a transaction.

- [ ] **Step 4** (`shelving/report.py`): Create the shared refusal helper in the FreeCAD layer. `report_refusal(summary, objects, suggestion)` printing the three parts to the report view in a fixed order and selecting the named objects in the 3D view, guarded for a missing GUI. A table mapping each known refusal reason, the solver's and the scanner's, to its suggested next step, so a suggestion is data rather than prose repeated in every command. Route every existing command's failure path through it.

- [ ] **Step 5** (`shelving/commands/`, `shelving/init_gui.py`): Add `Shelving_RecolourUnit` and `Shelving_RelabelUnit` in the established shape, each requiring exactly one selected container, each opening one transaction, calling its `unit_ops` function, committing, and reporting the count changed. Add both ids to `init_gui`'s `command_ids`.

- [ ] **Step 6** (`tools/freecad_write_smoke.py`, `docs/manual-qa.md`): Extend the write smoke: a created board's `ShapeColor` matches `colour_for` its material when a `ViewObject` exists and the path is skipped without raising when it does not; recolouring one board by hand and resizing leaves that colour; `recolour_unit` restores it and reports one changed; a board renamed by hand keeps its name through a resize and `relabel_unit` overwrites it and reports one changed; `relabel_unit` produces neutral side names with no facing set and left and right names after setting `ShelvingFacing`; and a refused operation leaves every board's size and placement unchanged. Add M10 cases to `docs/manual-qa.md` for colour appearing on a new unit, a hand colour surviving a resize, recolour taking it back, and a refusal showing its summary, objects and suggestion while selecting the objects in the 3D view.
