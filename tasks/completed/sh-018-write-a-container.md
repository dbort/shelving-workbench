---
id: sh-018
title: "Write a container"
current_agent: user
current_phase: done
review_rejections: 1
blocked_by: [sh-016, sh-017]
---

# sh-018: Write a container

## Summary
Write a layout back to a container as plain `Part::Box` objects, matched by the
object's own name so a rename, a colour, or a downstream reference survives, and
deleting only objects this workbench tagged so a part it did not write is never
removed. Stores what geometry cannot carry, then reads it back, so a rescan
recovers the intent it was given rather than re-guessing it. Adds **Create
Unit** and **Resize Unit**, both going through the same path. Milestone M7,
part 2 of 2.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [x] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `freecad/Shelving/container.py` exports `write_container(container, unit,
      catalog)` returning what it updated, created, deleted, and left alone.
- [x] Matching is by the document object's own `Name`, carried on
      `Board.id`. A test renames a board's `Label`, colours it, and asserts both
      survive an apply that changes the unit's size.
- [x] Deletion removes ONLY objects carrying this workbench's provenance
      properties and absent from the tree. A test puts an untagged box and a
      skipped non-box part in the container and asserts apply leaves both, and
      that the result names them as left alone.
- [x] Each board carries `ShelvingMaterial`, `ShelvingBornAs`, `ShelvingBornIn`,
      and `ShelvingIrregular`, in a `Shelving` property group.
- [x] A newly created board gets a readable `Label` derived from its position in
      the tree, never containing left or right while the unit's facing is
      unknown. A label is set at creation only and never rewritten, so a user
      rename sticks; asserted by renaming a board and resizing.
- [x] The container carries `ShelvingUnitId`, `ShelvingDepthAxis`,
      `ShelvingFacing`, and `ShelvingRules`, the last holding
      `freecad.Shelving.core.record.rules_to_json`.
- [x] `read_container` reads the stored properties back, so `scan` receives each
      board's stored material and irregular flag, and the caller can apply
      stored rules. A round-trip test asserts a `Fixed` rule that the equal-siblings
      heuristic would recover as `Fill` survives apply, rescan, and re-apply
      unchanged. A second asserts a board resolves through its stored material
      even when that entry's thickness no longer matches its measured extent.
- [x] A board whose `ShelvingBornAs` differs from its current `Name` is treated
      as a copy: its stored record is dropped and it is adopted as new geometry.
      A test copies a board within the document and asserts it becomes a new
      board rather than colliding with the original.
- [x] A non-box part is read as a pinned board rather than skipped; apply moves
      it but never rewrites its shape. A test asserts a padded notched profile
      keeps its solid across an apply that moves it.
- [x] `Shelving_CreateUnit` seeds a closed single-bay unit in a new `App::Part`
      at fixed defaults, and `Shelving_ResizeUnit` prompts for outer dimensions,
      rescans, substitutes, and reapplies. Both run inside one undo transaction
      and both are inactive without a document.
- [x] A saved document reopens with the workbench off the import path with every
      board present, correctly sized, and carrying its properties; the saved
      `Document.xml` contains no `Proxy`, `FeaturePython`, or `PythonObject`
      entry. Asserted in the headless smoke.
- [x] `tools/freecad_write_smoke.py` is a real pytest module, structured
      like `tools/freecad_scan_smoke.py`: one named `test_*` function per
      case below, self-invoking `pytest.main([__file__, ...])`, and
      `tools/run-tests.sh` checks its actual exit status rather than
      grepping output for a marker line.
- [x] `docs/manual-qa.md` has an M7 section covering create, resize, reflow
      after a hand edit, and the uninstalled-workbench reopen.
- [x] `mypy --strict` clean.

## Frontier Advice

IDENTITY IS THE DOCUMENT OBJECT'S `Name`, never a property we store. A property
would be copied along with the object and two boards would then claim one
identity with no way to tell which was the original. Set `Board.id` to the
object's `Name` when reading, and match on it when writing. This makes a
duplicate a distinct entity by construction rather than a conflict to resolve.

STORED MATERIAL MUST REACH `scan`. Fill `Box.material` from `ShelvingMaterial`
so scanning uses it rather than matching by thickness. Without this, M8's
catalog edits are impossible: changing an entry's thickness would leave every
board using it matching nothing and the rescan would refuse.

PROVENANCE IS TWO FIELDS, and they classify what a mismatch means rather than
providing identity. `ShelvingBornAs` is the `Name` the board had when tagged and
`ShelvingBornIn` is `doc.Uid` at that moment. Verified behaviour of FreeCAD 1.0:
a copy within a document gets a new `Name`, so `Name != ShelvingBornAs` means a
copy; a copy into a fresh document keeps its `Name` but the document `Uid`
differs, so that means a relocation; `Save As` does NOT change `Uid`, so two
files share one, which is benign because each file is self-consistent and
merging them forces a rename the first check catches.

A COPY IS ADOPTED, NOT REJECTED. When `Name != ShelvingBornAs`, drop the board's
stored record and treat it as new geometry. Somebody copying a shelf to make
another shelf wanted a new shelf, and this is what gives it to them.

LABELS ARE GENERATED AT CREATION ONLY. A board created by the write path gets a
`Label` from its role, derived from its division's axis and its position in that
division's run: the outermost boards of a vertical-axis division are `Bottom`
and `Top`, of a horizontal-axis division are the two sides, and an interior
board is `Shelf N` or `Divider N` by axis. While `front_at_min` is `None` the
sides are `Side 1` and `Side 2` in axis order; once facing is known they are
`Left Side` and `Right Side` accordingly. NEVER contain left or right while
facing is unknown: a mirrored label is the exact failure this design has been
avoiding, and a scanned unit usually has no facing.

A label is written only when the object is created and is NEVER rewritten on an
update, so a user rename survives every resize. Taking the workbench's opinion
back is an explicit command in M10, alongside the equivalent for colour.
This also covers a matched object's first adoption: a hand-built board (a
notched panel slotted into a bay, say) swept into the tree while still
untagged gets its provenance stamped but keeps whatever `Label` its author
gave it, the same as any other update. Only a genuine copy (`Name !=
ShelvingBornAs`) gets a fresh generated `Label` on adoption, matching a
newly-created board — round-1 review (`tasks/active/sh-018-REVIEW.md`)
caught an earlier draft overwriting the hand-built board's `Label` too;
flagged here for `user_signoff` since it is a deliberate behavior choice
on data the user authored outside the workbench.

DELETION RULE, decided in planning. An object is a deletion candidate ONLY if it
carries the provenance properties AND is absent from the tree. Anything untagged
is left exactly where it is. Without this the first apply on a scanned unit
would delete every part scanning could not read, including a notched panel it
explicitly reported rather than dropped. `write_container` RETURNS what it left
alone, and the commands print that list, so the user is told which objects the
workbench declined to touch. Offering an interactive choice about those objects
belongs to M9's panel, which has somewhere to put a checkbox; do NOT build a
dialog for it here.

RESIZE RESCANS EVERY TIME. Read the container fresh, scan it, substitute the new
outer size, apply. Never cache a model between commands. A cached tree goes
stale the moment a user moves a board by hand, and applying a stale tree is how
apply would delete something that was added since. The scan costs under a
millisecond.

NO DIMENSION PROPERTIES ON THE CONTAINER. The unit's size is its geometry, so a
`Width` property would be a second source of truth for something the boards
already say, and with nothing recomputing it, it would be a property that lies.
Resize is a command. Binding a unit's size to a room dimension needs a property
that something recomputes, which is the live-unit driver the roadmap defers.

WRITE PLAIN `Part::Box` OBJECTS ONLY. No `Part::FeaturePython`, no proxy, no
view provider of our own. That is what lets a document open correctly without
this workbench installed, and the smoke asserts it by reading the saved
`Document.xml`.

PINNED BOARDS ARE MOVED, NEVER REWRITTEN. `read_container` sets `Box.irregular`
for a part that is not a plain axis-aligned box, so `scan` places it as a
pinned board. On apply, set that object's `Placement` and leave its shape untouched; do
not set `Length`, `Width`, or `Height`, and do not recreate it. sh-017's solver
already raises `pinned_mismatch` when the layout would require a different size,
so apply can trust the tree it is given.

EVERYTHING RUNS IN ONE TRANSACTION. Each command calls `openTransaction` once
and `commitTransaction` once, so one undo reverses the whole operation. On any
exception, `abortTransaction` and report; never leave a half-written container.
`freecad-stubs` leaves the transaction methods unannotated, so those three calls
need `# type: ignore[no-untyped-call]`, as the deleted create-unit command did.

GUARD EVERY GUI TOUCH. Command modules must import cleanly under `freecadcmd`,
where `FreeCADGui` is a stub without `addCommand`. The smoke calls the write and
command helper functions directly rather than through `Gui`, so factor each
command's work into a plain function the smoke can call.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. FreeCAD's
stubs type only the generic `DocumentObject`, so extend the `Protocol` classes
sh-016 defines rather than reaching for `Any`. Shell stays simple applies: the
only shell edit is adding a smoke block to `tools/run-tests.sh` in the same shape
as the existing ones, no new logic.

Every length identifier carries `_mm`.

## Execution Plan

- [x] **Step 1** (`freecad/Shelving/properties.py`): Create the module owning every property this workbench writes, so no other module spells a property name. Constants for the group name and for each property: `ShelvingMaterial`, `ShelvingBornAs`, `ShelvingBornIn`, `ShelvingIrregular` on a board; `ShelvingUnitId`, `ShelvingDepthAxis`, `ShelvingFacing`, `ShelvingRules` on a container. `ensure_board_properties(obj)` and `ensure_container_properties(obj)` adding any that are missing, idempotent so a second call is a no-op. Typed readers and writers for each, with the facing stored as a string enumeration of `min`, `max`, `unknown` rather than a nullable boolean, because a FreeCAD string property has no null. A `Protocol` for the tagged-object surface.

- [x] **Step 2** (`freecad/Shelving/container.py`): Extend `read_container` to read the stored properties back. Set each `Box.name` to the object's `Name` as before, set `Box.irregular` for any part the classifier reports as not a plain axis-aligned box, and set `Box.material` from `ShelvingMaterial` when present. Return, alongside the boxes and the skipped list, the container's stored record: unit id, depth axis, facing, and the raw rules string, each absent when its property is missing. Detect a copy: when a board carries `ShelvingBornAs` differing from its `Name`, or `ShelvingBornIn` differing from the document `Uid`, report it so the caller knows its stored record must be dropped. Do not change the walk itself.

- [x] **Step 3** (`freecad/Shelving/container.py`): Add `write_container(container, unit, catalog)`. Expand the unit, then reconcile by `Board.id` against `Name`: update a matching object's `Length`, `Width`, `Height` and `Placement` in place, create a `Part::Box` for a board with no match, stamp its provenance from its new `Name` and the document `Uid`, and set its `Label` from its derived role per Frontier Advice, and delete an object that carries provenance and is absent from the tree. Never touch an object without provenance; collect those into a left-alone list. For a pinned board set only `Placement`. Write the container's four properties, with the rules from `freecad.Shelving.core.record.rules_to_json`. Return a frozen result carrying the four name lists. Do NOT open a transaction here; the commands own that.

- [x] **Step 4** (`freecad/Shelving/unit_ops.py`): Create the plain functions the commands and the smoke both call, so no command logic lives behind a `Gui` guard. `create_unit(doc) -> DocumentObject` building an `App::Part`, constructing a closed single-bay unit at fixed defaults against the in-code catalog, and calling `write_container`. `resize_unit(container, size_mm, catalog)` reading the container, scanning it, applying the stored rules with `freecad.Shelving.core.record.with_stored_rules`, substituting the new outer size, and calling `write_container`. `rescan_unit(container, catalog)` doing the same without a size change, which is what a reflow after a hand edit is. Each returns the write result so a caller can report it.

- [x] **Step 5** (`freecad/Shelving/commands/create_unit.py`, `freecad/Shelving/commands/resize_unit.py`, `freecad/Shelving/init_gui.py`): Add the two commands in the established shape: a `GetResources` returning menu text, tooltip and the workbench icon, an `IsActive` requiring an active document, and for resize also requiring exactly one container selected. Each opens one transaction, calls its `unit_ops` function, commits, and prints the write result to the report view including the left-alone list; on exception, abort the transaction and print the error. Resize prompts for width, height and depth with FreeCAD's input dialog, seeded from the container's current measured extent. Register both behind the headless-safe `Gui.addCommand` guard and add their ids to `init_gui`'s `command_ids`.

- [x] **Step 6** (`tools/freecad_write_smoke.py`, `tools/run-tests.sh`): Create the headless functional check, following `tools/freecad_scan_smoke.py`'s preamble and its structure: a real pytest module that self-invokes `pytest.main([__file__, ...])` and calls `sys.exit` on the result, not a hand-rolled assert-and-marker script (see `docs/freecadcmd-notes.md` for the guards that structure needs: the environment-variable recursion guard, the explicit `sys.stdout.flush()` before `sys.exit`, and why `if __name__ == "__main__":` does not work under `freecadcmd`). Assert, in order: `create_unit` produces a container of plain `Part::Box` objects with the four container properties and four board properties set; scanning it back yields the same tree; `resize_unit` to a larger size updates the same document objects rather than recreating them, checked by `Name`; a newly created board's `Label` names its role and contains neither left nor right when the unit's facing is unknown, and contains them when it is known; a board's `Label` and colour survive that resize; an untagged box and a padded notched body placed in the container are left alone and named in the result; the notched body's solid is unchanged after a resize that moves it; a board copied within the document is adopted as a new board on the next rescan; a `Fixed` rule the heuristic would recover as `Fill` survives apply, rescan and re-apply; and after `saveAs`, `closeDocument` and `openDocument`, every board is present and correctly sized while the `Document.xml` inside the archive contains no `Proxy`, `FeaturePython`, or `PythonObject` entry. One test function per case, not one long assertion sequence. Add a matching block to `tools/run-tests.sh` that checks the script's exit status.
  > **Checkpoint:** `pixi run tests` must be green here (Steps 2-6 are one write path; the reconciler has no caller until the commands and the smoke exist).

- [x] **Step 7** (`docs/manual-qa.md`, `README.md`): Add an `## M7` section in the file's numbered-steps-then-expected-result shape, with cases for: create a unit and confirm the tree holds plain boxes with a `Shelving` property group; resize it and confirm boards move while labels and colours hold; move a board by hand, rescan, and confirm the layout takes the edit up; put an unrelated box in the container and confirm apply leaves it and says so; and save, quit, move the workbench off the path, reopen, and confirm the document is intact. Extend the README glossary with `write_container`, the property names, the provenance rule, and the deletion rule, in the section's existing one-bullet-per-term shape.
