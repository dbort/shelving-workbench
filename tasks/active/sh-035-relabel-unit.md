---
id: sh-035
title: "Relabel Unit"
blocked_by: [sh-022]
---

# sh-035: Relabel Unit

## Summary
A board's label is written once, when the board is created, so a user's own
names survive every edit; a new Relabel Unit command rewrites them on
request. With a unit's container selected it renames every board except the
ones renamed by hand. With boards selected it renames exactly those. Each
board remembers the label the workbench last gave it, which is how a hand
rename is told apart from a generated name. The result shows in the
Notification Area, and any boards it kept stay selected, so running the
command again renames them too. A new board's color already comes from the
board it copies its stock from (sh-030). Milestone M10.

## Must Have
- [ ] `pixi run tests` green.
- [ ] Every board the workbench names, whether at creation, at copy adoption
      or by relabel, carries a `ShelvingGivenLabel` string property in the
      Shelving group, holding the `Label` read back after the write. A suffix
      FreeCAD adds for uniqueness ("Shelf 001") is part of what is recorded.
- [ ] With the container selected, `Shelving_RelabelUnit` rewrites every
      board whose `Label` equals its `ShelvingGivenLabel` or that has none,
      and keeps every board whose `Label` differs. A board selected
      explicitly is always rewritten, even alongside the container. With only
      boards selected, only those are rewritten. Asserted on one document: a
      board renamed by hand keeps its name through a resize and through a
      container relabel, and is overwritten once it is selected.
- [ ] A board without `ShelvingGivenLabel`, such as a hand-built unit's
      `Cube001`, is rewritten by a container relabel.
- [ ] The selection resolves through `unit_for_selection`, as Edit Unit's
      does. A selection naming no single unit is refused through sh-022's
      shared refusal helper, with a suggestion that does not name another
      command. A unit the scan cannot read is refused with the `ScanError`'s
      reason and objects, as Edit Unit refuses it. Covered by sh-022's
      every-command test.
- [ ] Selected parts the scan does not read as boards (back panels,
      unreadable parts, objects left alone) keep their labels and are counted
      in the report. They are never refused.
- [ ] Left and right names when the unit's facing is known, neutral ones when
      it is not. Asserted both ways on one document by setting
      `ShelvingFacing` between runs.
- [ ] Names that trade places within one unit land exactly. Two shelves whose
      labels were swapped by hand, both selected and relabeled, end as
      "Shelf 1" and "Shelf 2", with no FreeCAD suffix on either.
- [ ] In a document holding two units, relabeling the second unit records
      FreeCAD's suffixed labels. A second relabel of that unit changes none
      and keeps none.
- [ ] The run is one transaction, named "Relabel Unit". Its result is a
      Notification Area notification, not an error, with number-agnostic
      lines: "Boards relabeled: N" always, plus "Kept, renamed by hand: N"
      (with a hint that selecting those boards and running Relabel Unit
      renames them) and "Not boards, left alone: N", each shown only when
      N > 0. Afterward the kept boards are selected; with none kept, the
      selection is left alone.
- [ ] The generated label text ("Top", "Shelf {n}", "Left Side", ...) lives
      in one table of English literals in `container.py`.
- [ ] A board is an end board ("Bottom", "Top", a side, "Front", "Back")
      when only voids lie between it and that end of its division, so open
      space past a board does not make it a shelf or divider. Asserted on
      `tests/freecad/fixtures/woodworking_magic_start_default.FCStd`: the
      floor above the kick space is "Bottom", the shelf is "Shelf 1", and a
      bay-board-bay division still names its board "Shelf N".
- [ ] `Shelving_RelabelUnit` is in `init_gui`'s `TOOLBAR_COMMANDS`, so it
      shows on both the toolbar and the Shelving menu.
- [ ] A QA case in `freecad/Shelving/qa/cases/` covers relabel: a container
      run that keeps a hand rename, then a run on the kept board that renames
      it.
- [ ] `pyrefly check` clean.

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

USER CONTROL IS SELECTION AND SPARING, NOTHING MORE (user decision,
2026-10-21). The container selects the whole unit with hand renames spared;
a selected board is a request to rename that board. No preview dialog, since
no FreeCAD batch command has one and undo covers a mistake. No naming
templates: sh-023 already rules out a label-style preference.

A HAND RENAME IS `Label != ShelvingGivenLabel`. A missing record means the
workbench never named the board, so there is no rename to protect and it is
rewritten (user decision, 2026-10-21, reaffirmed 2026-10-22 knowing that
magicStart's five "Furniture - ..." names are lost to a container relabel).
This overwrites a pre-sh-035 document's hand renames once; the report and
undo cover that. Write the
record wherever the workbench writes a `Label`: `_create_board`, the copy
adoption in `write_container`, and relabel. Add it through
`properties.py`'s board-property path in the existing style, not as a
one-off `addProperty`.

FREECAD MAKES LABELS UNIQUE BY DEFAULT. With `DuplicateLabels` off (the
default, checked on FreeCAD 1.1.3), a second "Shelf 1" becomes "Shelf 001"
and a second "Left Side" becomes "Left Side001". Accept the suffix (user
decision, 2026-10-21), as every workbench does, with no unit prefix or
numbering of our own. Three consequences:
- Record the `Label` read back after assignment, never the requested string.
  Otherwise every suffixed board reads as renamed by hand and is spared
  forever.
- Count a board as changed only when its `Label` differs after the write.
  Compare the derived name against the record, never against the
  suffixed `Label`, or every run rewrites the second unit.
- Assign in two passes within a unit: every target board to a temporary
  unique label first, then each to its final name. Otherwise a swap
  (Shelf 1 ↔ Shelf 2) collides with the label it has not yet vacated and
  picks up a suffix.

LOCALE IS DEFERRED (user decision, 2026-10-21). Labels stay English
literals, gathered into one table so a later task can wrap them in
`translate()` as whole phrases ("Shelf {n}", not "Shelf" + number). The
`Later` section of `docs/roadmap.md` carries that work. The record holds
the text actually written, so a document named in one language later reads
as generated in another, and relabel will convert it with no change to this
design.

END BOARDS SKIP VOIDS (user decision, 2026-10-22). `_label_for_board` keys
"Bottom"/"Top" and the sides on `index == 0` / `index == last_index`, so
magicStart's floor, which has a kick-space `Void` below it, is named
"Shelf 1". The rule is "only `Void`s between the board and that end". It is
not "first or last `Board`": a nested bay-board-bay division would then call
its lone shelf "Bottom". Apply it on all three axes. Creation labels change
with it, so update any test that asserted the old names.

RELABEL IS NOT AUTOMATIC WHEN FACING CHANGES. A unit scanned without a facing
gets neutral side names; setting the facing later does not rewrite them, because
a label is never rewritten on an update and a user may have renamed one. The
relabel command is the answer, and its report says how many it changed so a user
knows their renames were overwritten. Flipping a unit's facing from the editor
is separate later work on the roadmap; do not add it here.

RELABEL STAYS ON THE TOOLBAR (user decision, 2026-10-11). Simplifying the
workbench means removing commands that overlap another one; Relabel overlaps
nothing, so it is a first-class command.

REFUSALS USE sh-022's HELPER. Refusals go through `report_refusal` with a
suggestion from `SUGGESTIONS`, never a bare `print`, which is why sh-022 is
a hard blocker. `no_unit_selected`'s text ends "run Edit Unit again"; make it
command-neutral ("then run the command again", as `task_panel_open` reads)
rather than adding a near-duplicate reason.

THE SUCCESS REPORT IS UI (CLAUDE.md, users never read the log). Add a
notice beside `report_error` in `refusals.py` that prints through
`FreeCAD.Console.PrintTranslatedNotification`, which FreeCAD 1.1.3 has, and
reuse `_select` for the kept boards. Keep the lines number-agnostic, with
the count after a colon, so no text depends on N.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `pyrefly check` clean. Shell
stays simple does not apply; this task adds no shell. Follow FreeCAD's own
tools: selection-driven scope and a selection afterward follow Edit Unit's and
the refusal helper's precedent; FreeCAD has no batch rename to copy beyond
that. Users never read the log: covered by the notice above.

Every length identifier carries `_mm`.

## Plan

- [ ] **Step 1** (`freecad/Shelving/properties.py`, `freecad/Shelving/container.py`): Add `GIVEN_LABEL_PROP = "ShelvingGivenLabel"` to the board properties with a reader returning `str | None`. Gather `_label_for_board`'s literals into one module-level table, and decide end boards by "only voids toward that end" instead of by index. Add a label writer that assigns, reads `Label` back and stores it in the record; route `_create_board` and the copy-adoption branch of `write_container` through it.

- [ ] **Step 2** (`freecad/Shelving/unit_ops.py`): Add `relabel_unit(container, selected)` that scans the container itself, so it works on a unit never scanned this session, derives labels with `_derive_labels`, and returns a frozen result dataclass of changed, kept (by object name) and not-board counts. `selected` holds the selected objects; the container among them means whole-unit with sparing. It assigns in two passes through temporary labels, compares derived names against the record, and opens no transaction. It raises `ScanError` unchanged.

- [ ] **Step 3** (`freecad/Shelving/refusals.py`): Add the notification-level notice and a public way to select objects by name for it; make `no_unit_selected`'s suggestion command-neutral.

- [ ] **Step 4** (`freecad/Shelving/commands/`, `freecad/Shelving/init_gui.py`): Add `Shelving_RelabelUnit` in Edit Unit's shape: `unit_for_selection`, refuse through `report_refusal`, open one "Relabel Unit" transaction, call `relabel_unit`, commit (abort on an exception), report through the notice, select the kept boards. Add its id to `TOOLBAR_COMMANDS` and its module to `Initialize`'s deferred imports.

- [ ] **Step 5** (`tests/freecad/test_write.py`, `freecad/Shelving/qa/cases/`, `docs/roadmap.md`): Cover every Must Have assertion headless: the record after creation and after a suffixed write, sparing and forcing, no-record rewrite, facing both ways, a hand swap landing unsuffixed, a second unit going idle on its second run, and non-board counting. Add the QA case following `.claude/docs/qa-wizard.md`. Add a "Translations" item to the roadmap's `Later` section: wrap UI strings and generated labels in `translate()` and ship `.ts`/`.qm` files through `addLanguagePath`.

## Review log
