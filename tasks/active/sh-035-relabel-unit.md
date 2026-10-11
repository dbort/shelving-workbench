---
id: sh-035
title: "Relabel Unit"
blocked_by: [sh-022]
---

# sh-035: Relabel Unit

## Summary
A board's label is written once, when the board is created, so a user's own
names survive every edit; a new Relabel Unit command rewrites them on
request. A new board's color already comes from the board it copies its stock
from (sh-030). Milestone M10.

## Must Have
- [ ] `pixi run tests` green.
- [ ] `Shelving_RelabelUnit` rewrites every board's `Label` from its derived
      role. It acts on one selected container, runs in one transaction, and
      reports how many it changed.
- [ ] `Shelving_RelabelUnit` produces left and right names when the unit's
      facing is known and neutral ones when it is not. Asserted both ways on one
      document by setting `ShelvingFacing` between runs.
- [ ] A board renamed by hand keeps its name through a resize, and
      `relabel_unit` overwrites it and reports one changed.
- [ ] `Shelving_RelabelUnit` is in `init_gui`'s `TOOLBAR_COMMANDS`, so it
      shows on both the toolbar and the Shelving menu.
- [ ] `Shelving_RelabelUnit`'s refusal goes through sh-022's shared refusal
      helper, covered by sh-022's every-command test.
- [ ] A QA case in `freecad/Shelving/qa/cases/` covers relabel.
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
knows their renames were overwritten. Flipping a unit's facing from the editor
is separate later work on the roadmap; do not add it here.

RELABEL STAYS ON THE TOOLBAR (user decision, 2026-10-11). Simplifying the
workbench means removing commands that overlap another one; Relabel overlaps
nothing, so it is a first-class command.

REFUSALS USE sh-022's HELPER. The "exactly one container" refusal goes through
the shared refusal helper with a suggestion from its table, never a bare
`print`, which is why sh-022 is a hard blocker.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. Shell
stays simple does not apply; this task adds no shell.

Every length identifier carries `_mm`.

## Plan

- [ ] **Step 1** (`freecad/Shelving/unit_ops.py`): Add `relabel_unit(container)` rewriting every board's `Label` from its derived role and returning the count changed. It reads the container rather than taking a model, so it works on a unit that has never been scanned in this session. It opens no transaction.

- [ ] **Step 2** (`freecad/Shelving/commands/`, `freecad/Shelving/init_gui.py`): Add `Shelving_RelabelUnit` in the established shape, requiring exactly one selected container, refusing through the shared refusal helper, opening one transaction, calling `relabel_unit`, committing, and reporting the count changed. Add its id to `init_gui`'s `TOOLBAR_COMMANDS` and its module to `Initialize`'s deferred imports.

- [ ] **Step 3** (`tests/freecad/test_write.py`, `freecad/Shelving/qa/cases/`): Extend the write tests: a board renamed by hand keeps its name through a resize and `relabel_unit` overwrites it and reports one changed; `relabel_unit` produces neutral side names with no facing set and left and right names after setting `ShelvingFacing`. Add a QA case for relabel following `.claude/docs/qa-wizard.md`.

## Review log
