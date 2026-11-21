---
id: sh-054
title: "A lock is a constraint you can turn off"
---

# sh-054: A lock is a constraint you can turn off

## Summary
Makes a lock an ordinary constraint beside Equal and Even spacing,
rather than a flag on the opening. In the constraint list a lock row
gains the same checkbox as the others, so a lock can be turned off and
back on without losing its row. Locks are listed in the order they were
made, mixed in with the other constraints. A deleted lock, or a dropped
one, is treated like any other constraint. The 3D view keeps its
padlocks for now; sh-055 replaces them with Sketcher-style dimensions.

## Must Have
- [x] `pixi run tests` green; `pyrefly check` clean over the changed code.
- [x] `Bay`, `Void` and `Division` (`core/layout.py`) have no `lock`
      field, and `Constraint` is `Equal | EvenSpacing | Lock`, where `Lock`
      carries `region_id`, `basis`, `active` and `id` as `Equal` does.
      `grep -rnw LockRow freecad tests` prints nothing.
- [x] Core suite, on sh-046's column of 18 mm boards with fixed point
      `min`: bottom, A 300, shelf s1, B 300, shelf s2, C 300, top (972 mm
      tall):
      - locking A appends one active `Lock` naming A after the unit's
        existing constraints and moves nothing; locking A again adds none;
      - with A's Lock active, typing 400 into B gives A 300, C 200; with
        A's Lock deactivated, the same typing gives A 250, C 250;
      - turning A's Lock back on moves nothing and A keeps its size;
      - typing a size into a region whose Lock is deactivated turns that
        Lock on, and the unit still holds one Lock for the region;
      - with A locked at 300 and C locked at 200, an Equal on A and C is
        refused with a conflict naming both Locks' ids and the Equal's;
      - the existing split, merge, delete, drag, `held_by` and redundancy
        tests keep their expected layouts and lock outcomes, rewritten
        against `Lock`.
- [x] A unit scanned with no valid record holds an active `Lock` for each
      void the scan locks today, and none for a bay.
- [x] `rules_to_json` emits `{"schema_version": 3, "constraints": [...]}`
      with no `"locks"` key. A Lock entry is `{"kind": "lock", "active":
      <bool>, "basis": "clear" | "with_next", "region": <region key>}`, in
      the unit's constraint order. `rules_from_json` on a version 2 record
      gives its locks as active Locks, in tree order, ahead of its
      constraints. A Lock entry with an unknown basis or a missing region
      key is dropped and nothing is raised; a version 1 record still reads
      as no record.
- [x] Headless (`tests/freecad/`), opening a container in `Session`:
      - a stored deactivated Lock opens deactivated, holds nothing, and is
        written back with `"active": false` by the next edit;
      - a stored Lock whose region key matches nothing is dropped, and the
        one open notification reports it with the other dropped
        constraints;
      - turning a Lock off or on through `set_active` is one undo step that
        moves no board, and Undo restores the previous state;
      - Delete Deactivated removes deactivated Locks with the other
        deactivated constraints, in one undo step.
- [x] GUI (`tests/freecad_gui/test_constraint_list.py`): a Lock row has a
      checkbox, and unchecking it deactivates the Lock; a deactivated Lock
      row's icon is grayed in Qt's disabled mode; a Lock made after an
      Equal is listed after it; selecting a Lock row selects that Lock as a
      constraint, and with it selected, Opening size measures switches its
      basis moving nothing.
- [x] 3D view (`tests/freecad_view/test_padlocks.py`): an opening whose
      Lock is deactivated shows an open padlock and an unlocked
      dimension; clicking that padlock turns the same Lock back on.
- [x] `README.md` does not contain "every locked opening, then", and
      `docs/scope-and-design.md` does not contain "locks first in tree
      order".

## Advice
- **A lock is a constraint** (user decision: make locks less special). A
  `Lock` lives in `Unit.constraints` with its own `ConstraintId`, so
  everything keyed by constraint id (selection, conflicts, redundancy,
  flagged outlines, `constraint_regions`, delete, the list) handles it
  without a lock-specific path. A region holds at most one Lock: edits
  and the record reader keep that invariant, and locking a region whose
  Lock is deactivated turns that Lock on instead of adding one.
- **No stored size.** Sizes always come from the boards, so a Lock
  records only its region and basis. Turning one on locks the region at
  its current size and moves nothing. A lock therefore never comes in
  deactivated at open, and never conflicts when turned on; a redundant
  one is accepted with the existing warning.
- **Activation** (user decision): Lock rows get the checkbox, delete
  button and Delete Deactivated behavior Equal and Even spacing have. A
  deactivated Lock holds nothing, joins no boards in the drag rule, and
  does not count toward a reference axis.
- **List order** (user decision): rows in constraint order, locks
  included. A version 2 record's locks come first in tree order because
  that is the order the list showed them in.
- **Keep every lock outcome.** Split, merge, delete, drag, typed size and
  basis changes give the layouts and lock states they give today. Where
  code moved a region's lock to a new region id, as `split_region` does
  when it wraps a bay in a new Division, retarget the Lock to the new id.
  A Lock whose region an edit removes is dropped in the same edit, as
  Equal is.
- **Typed size** still locks: `set_size` adds a Lock, or turns a
  deactivated one on, in the same undo step.
- **Record:** convert version 2 rather than discarding it, since that is
  every saved unit's format and conversion is a few lines. Rewrite the
  `core/record.py` module docstring for the one constraint list; its
  rescan-key rationale stays.
- **The view stays as it is** apart from what activation forces: a
  closed padlock and locked dimension color for an active Lock, an open
  padlock and the unlocked color for none or a deactivated one. A click on
  a closed padlock deletes the Lock; on an open one it adds a Lock or turns
  the deactivated one on. The held board's padlock still deletes the Locks
  holding it. sh-055 replaces all of this.
- **Typed Python:** `Lock` is a frozen dataclass like `Equal`; the record
  entry a `TypedDict` with `kind: Literal["lock"]`.
- **Shell stays simple:** no shell in this task.
- **Follow FreeCAD's own tools:** the Sketcher keeps a dimension as one
  constraint among others in its list, with an active checkbox, in
  creation order.
- **Users never read the log:** the dropped-Lock report joins the
  existing open notification in the Notification Area.
- **No new manual QA case:** tests assert every outcome. Keep
  `editor.constraint_list` and `editor.padlocks` true.
- **Sequencing:** sh-055 builds on this and is blocked on it.

## Plan
- [x] **Step 1** (`core/layout.py`, `core/edit.py`, `core/solver.py`,
      `core/scan.py`, `core/tests/test_layout.py`, `test_edit.py`,
      `test_solver.py`, `test_constraints.py`, `test_scan.py`,
      `test_scanned_units.py`, `test_stock.py`, `test_expand.py`): `Lock`
      replaces the regions' `lock` field; `is_locked` becomes a query on
      the unit for an active Lock; the solver feeds active Locks to the
      engine as it feeds region locks today; lock, unlock, set_size,
      set_basis, set_active and the edits that drop constraints handle
      Lock; the scan makes Locks for the voids it locks.
- [x] **Step 2** (`core/record.py`, `core/tests/test_record.py`): schema
      version 3 with Lock entries, the version 2 conversion, restore and
      drop reporting for Locks.
- [x] **Step 3** (`container.py`, `unit_ops.py`, `qa/actions.py`,
      `tests/freecad/test_write.py`, `test_backs.py`,
      `test_qa_actions.py`, `test_editor_session.py`,
      `test_constraint_session.py`, `test_edit_history.py`): read and
      write the new record; `Session.set_lock`, `unlock_holders`,
      `set_active`, `delete_deactivated` and the open report treat a Lock
      as a constraint.
- [x] **Step 4** (`editor/session.py`, `editor/constraint_list.py`,
      `editor/panel.py`, `editor/fields.py`, `editor/elevation.py`,
      `editor/view_editor.py`, `tests/freecad_gui/test_constraint_list.py`,
      `test_panel.py`, `test_refusals.py`,
      `tests/freecad_view/test_constraint_list.py`, `test_padlocks.py`,
      `test_editor_drawing.py`, `test_editor_input.py`,
      `tests/test_editor_elevation.py`): `LockRow` folds into
      `ConstraintRow` with a lock kind; list order, checkbox and selection
      as above; padlocks and dimension colors follow the Lock's
      activation.
- [x] **Step 5** (`README.md`, `docs/scope-and-design.md`,
      `freecad/Shelving/qa/cases/30-editor.toml`): the glossary's Size
      rule, Deactivated constraint and Constraint list entries, the
      layout model's lock paragraphs, the constraint list paragraph and
      the record bullet describe a lock as a constraint with a checkbox in
      creation order. Adjust any QA expectation about Lock row order.

## Review log

### Round 1: APPROVED
- **N1: Restoring Locks under a shared key assumes they were stored in tree order** (`freecad/Shelving/core/record.py:497`): Locks under a key several regions share (runs of axis wraps keyed `~|~`) go to those regions in tree order, but a version 3 record stores them in constraint order. Deleting wrap A's Lock of A, B reopens it on A; deactivating B, deleting A's Lock and relocking A reopens with A off and B on. The version 2 reader locked every region sharing the key, so an unlock never persisted there either. The Lock entry shape the Must Have fixes cannot tell such regions apart, so not blocking; take it to the user or the bug log. The shared-key test covers only constraint order matching tree order.
- **N2: Unused TypedDict** (`freecad/Shelving/core/record.py:165`): `_LockMapEntryDoc` is never referenced; delete it or use it.
- **N3: Implementation notes checked against the Advice**: split and merge Lock carry-over, `carry_constraints` walking `after.constraints`, sizeless deactivated Lock rows, rows tracking selected constraints only, `lock_ids` for the lock-only conflict wording, and no smoke mark change are all consistent. Every Must Have has a test; `pixi run tests` passed in full on 3a5b9ef.
