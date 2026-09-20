---
id: sh-016
title: "Read a container"
current_agent: user
current_phase: user_signoff
review_rejections: 1
blocked_by: [sh-013, sh-014]
---

# sh-016: Read a container

## Summary
The FreeCAD half of scanning: walk a container the user selects, read every
part in the container's own frame, and hand the result to the core scanner. A
**Scan** command reports the layout it found, or refuses and selects the objects
that defeated it. An **Export boxes** command writes the same records to JSON,
which is how a unit that refuses gets captured for a bug report. Deletes
`spikes/`, whose job this task takes over. Milestone M6.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [ ] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `freecad/shelving/container.py` exports `read_container`, returning the
      core's `Box` records plus `Skipped` records for parts it could not read.
- [x] Sizes come from each part's solid bounding box, NOT from `Length`,
      `Width`, `Height`. A box rotated by a multiple of 90 degrees reads
      correctly; a skewed one is refused by name.
- [x] Reading is in the container's own frame: the container's own placement is
      excluded, nested container placements are composed. A test moves and
      rotates the container and asserts the records are unchanged.
- [x] The walk descends only into `App::Part`, `App::LinkGroup`, and
      `App::DocumentObjectGroup`. A `PartDesign::Body` is one part; a test
      asserts its sketch and its pad are not read as two boards.
- [x] The walk yields each document object at most once. A test builds a
      selection reaching one object by two paths and asserts one record.
- [x] A skip reason names why a part could not be read, in the terms the spike's
      inspector used: a plain box, a box minus N rectangular cutouts, not
      axis-aligned, carries no solid, or holds N solids. A test asserts the
      box-minus-cutouts wording against a padded notched profile.
- [x] `shelving_core/report.py` renders a `ScanResult` as text, with a test in
      the fast suite asserting the tree shape and the skipped block for a real
      fixture. It imports no FreeCAD.
- [x] `Shelving_Scan` and `Shelving_ExportBoxes` are registered, appear in the
      toolbar and menu, and are inactive without a document.
- [x] `tools/freecad_scan_smoke.py` builds a document, reads it, scans it, and
      asserts the tree, printing `shelving scan OK`; `tools/run-tests.sh` greps
      for that marker.
- [x] `spikes/` does not exist and nothing references it
      (`grep -rn 'spikes' --include=* . | grep -v '^\./\.git'` returns nothing
      outside this task file's history).
- [x] `docs/manual-qa.md` has an M6 section with cases for a successful scan, a
      refusal selecting its offenders, and the export command.
- [x] `mypy --strict` clean.

## Frontier Advice

SOURCE MATERIAL: `spikes/plain_planks/export_boxes.py` is the worked walk,
`spikes/plain_planks/report.py` the worked text output, and
`spikes/plain_planks/inspect_object.py` the worked solid classifier. Port from
all three, then DELETE `spikes/` entirely as the last step. This is the task the
roadmap names as the spike's end; the workbench can now do what it stood in for.

READ-ONLY. Neither command modifies the document. No property is written, no
object created, no placement changed. That is the whole safety argument for
reading landing before writing, and a reviewer should reject any document
mutation outside the export command's file write.

SIZES COME FROM THE BOUNDING BOX, not from `Length` / `Width` / `Height`. Use
`obj.Shape.BoundBox`. A box rotated a quarter turn is still axis-aligned but its
property triple no longer lines up with X, Y, Z, and refusing it would reject
readable geometry. Refuse only a part whose solid is NOT axis-aligned, which the
classifier below already detects. Woodworking carries both a property reader and
a bounding-box reader for this reason.

THE CONTAINER'S OWN FRAME. Compose the placements of nested containers between
the selected container and each part, but EXCLUDE the selected container's own
placement. A unit rotated or moved in a room must read identically to the same
unit at the origin. `getGlobalPlacement` is NOT usable: it composes only through
geo-feature groups and an `App::LinkGroup` is not one, which is why the walk
composes by hand.

DESCEND ONLY INTO CONTAINERS: `App::Part`, `App::LinkGroup`,
`App::DocumentObjectGroup`. A `PartDesign::Body` exposes its feature history
through `Group`; descending into one yields its sketch and its pad as if they
were boards and never looks at the body's own solid. A body or a boolean is one
part and its children are its construction, not its contents.

DEDUPLICATE BY DOCUMENT OBJECT NAME. A selection can reach one object by more
than one path; a real export produced eleven boards twice over. Track what has
been yielded.

SKIP REASONS CARRY THE CLASSIFIER. Fold `inspect_object.py`'s check into the
reason: subtract the solid from its own bounding box and report whether it is a
plain box, a box minus N rectangular cutouts with their sizes, not axis-aligned,
carrying no solid, or holding N solids. A part holding several solids is usually
a Draft array, whose source object is exported separately, so say that: four
shelves in an array otherwise read as one shelf.

DO NOT ADOPT NON-BOX PARTS. Report them in the skipped list and stop there.
Reading one as a board needs a pinned flag on `Board` and a solver rule that
lets its size drive its region, neither of which exists; that lands with M7
where the stored metadata marking it also lands. A silent adoption without
pinning would let a later apply overwrite a part it cannot reproduce.

SELECTION ENVELOPE: exactly one `App::Part`, `App::LinkGroup`, or
`App::DocumentObjectGroup`. Anything else, including a bare selection of boxes,
is refused with a message saying to group them first. The container is what
decides which boards form one unit, which geometry cannot say, so requiring one
is the model being honest.

ON REFUSAL, SELECT THE OFFENDERS. Clear the selection and select the objects the
`ScanError` names, so a user sees them in the 3D view rather than hunting six
names in a tree of forty. Guard every `FreeCADGui` touch: the command module must
import cleanly under `freecadcmd`, where `FreeCADGui` is a stub without
`addCommand`. `freecad/shelving/commands/create_unit.py` in git history is the
working pattern for that guard.

`shelving_core/report.py` IS CORE, not FreeCAD. It renders a `ScanResult` to
text and imports no FreeCAD, so the fast suite tests it against the real
fixtures without a FreeCAD interpreter. The commands call it and print the
result. Port the spike's `report.py` shape: the plane and facing lines, the
warning when facing is undetermined, the indented tree, and the skipped block.
Keep the facing warning verbatim in substance: an undetermined facing means left
and right are a coin flip, and saying so is the point.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. FreeCAD's
stubs type only the generic `DocumentObject`, so define `Protocol` classes for
the surfaces read, as `freecad/shelving/objects/feature_types.py` did in git
history; do NOT reach for `Any` to dodge that. Shell stays simple applies: the
only shell edit is adding a smoke block to `tools/run-tests.sh` in the same
shape as the existing one, no new logic.

Every length identifier carries `_mm`.

## Execution Plan

- [x] **Step 1** (`freecad/shelving/container.py`): Create the module with the walk and nothing else. Define `Protocol` classes for the part and container surfaces read. `_CONTAINERS` names the three descendable types. `_children(obj)` returns members only for those types, reading `ElementList` then `Group`. `_walk(obj, placement, seen)` yields each part once with its accumulated placement, composing nested container placements and excluding the selected container's own. `read_container(obj) -> tuple[list[Box], list[Skipped]]` producing `shelving_core.scan.Box` records from each part's `Shape.BoundBox` with the composed placement applied, and `Skipped` records for the rest. Refuse a part whose solid is not axis-aligned by putting it in `Skipped` with that reason rather than raising.

- [x] **Step 2** (`freecad/shelving/container.py`): Add the solid classifier, ported from `spikes/plain_planks/inspect_object.py`. A private helper returns a reason string for a part that is not a plain axis-aligned box: subtract the solid from its own bounding box with `Part` booleans, and report a box minus N rectangular cutouts with their millimetre sizes when every leftover piece is itself a box, not axis-aligned when any face is non-planar or angled, carries no solid when the shape is null or has no volume, or holds N solids naming the array case and its missing copies. Wire it into `read_container`'s skip path. Guard the boolean in try/except and fall back to a plain type-name reason so a pathological solid cannot break a scan.

- [x] **Step 3** (`shelving_core/report.py`, `shelving_core/tests/test_report.py`): Create the text renderer. `report(result: ScanResult) -> str` returning the plane line, the facing line naming which evidence settled it, the indented tree with one line per region and per board including sizes and insets, and a skipped block listing each unreadable part with its reason. When `front_at_min` is `None`, emit the warning that left and right are a coin flip and the tree is correct either way. Tests in the fast suite over `real_stair_step` and `real_magicstart_f1`: assert the tree lines, the facing line, and that a `ScanResult` carrying a skipped part renders the skipped block. Imports no FreeCAD; `tests/test_no_freecad.py` must still pass.

- [x] **Step 4** (`freecad/shelving/commands/scan.py`): The `Shelving_Scan` command. `GetResources` returns menu text "Scan Unit", a tooltip, and the workbench icon. `IsActive` returns true only with an active document. `Activated` reads the selection, refuses anything that is not exactly one container with a message naming what to do, calls `read_container`, calls `shelving_core.scan.scan` against the default catalog, and prints `shelving_core.report.report` to the report view. On `ScanError`, print the message and its named objects, then clear the selection and select those objects. Register with the headless-safe `Gui.addCommand` guard so the module imports under `freecadcmd`.

- [x] **Step 5** (`freecad/shelving/commands/export_boxes.py`): The `Shelving_ExportBoxes` command. Same resource and guard shape. `Activated` takes the same one-container selection, calls `read_container`, and writes a JSON document with a `boxes` array and a `skipped` array in the format `shelving_core.scan.export_from_json` reads, to a path beside the document, printing the path. This is the mechanism for capturing a unit that refuses, so it must write even when scanning would fail: do NOT call `scan` here.

- [x] **Step 6** (`freecad/shelving/init_gui.py`): Set `command_ids` to `["Shelving_Scan", "Shelving_ExportBoxes"]` and restore the deferred imports of both command modules inside `Initialize`, keeping the comment explaining why the import is deferred. Update the class docstring to name the two commands.

- [x] **Step 7** (`tools/freecad_scan_smoke.py`, `tools/run-tests.sh`): Create the headless functional check, following `tools/freecad_smoke.py`'s `sys.path` and `freecad.__path__` preamble. Build a document containing an `App::Part` holding boxes forming a closed unit with one shelf; call `read_container` and assert the record count and one box's corner and size; call `scan` and assert the tree shape. Then: move and rotate the container and assert the records are unchanged; add a `PartDesign::Body` with a padded notched sketch and assert it produces one `Skipped` with the box-minus-cutouts reason rather than two board records; add the same object to a second group and assert it still yields one record; add a box rotated a quarter turn and assert its size reads correctly. Print `shelving scan OK` last. In `tools/run-tests.sh`, add a block for it mirroring the existing `freecad_smoke.py` block exactly, including the header printf, the output capture, the echo, and the grep guard.

- [x] **Step 8** (`spikes/`): Delete the directory entirely. Confirm nothing references it: grep the tree for `spikes` and fix any pointer, including in `docs/parametric-model-evaluation.md` where the spike paths are named; in that document, change each to state what the spike proved rather than where it lived, since the code is gone but the findings stand.

- [x] **Step 9** (`docs/manual-qa.md`, `README.md`): Add an `## M6` section with three cases in the file's numbered-steps-then-expected-result shape: scan a container of boxes and read the tree in the report view; scan a container holding a part the walk cannot read and confirm the refusal names it and selects it in the 3D view; run the export command and confirm the JSON lands beside the document. Extend the README glossary with the two command ids and the container's-own-frame rule, in the section's existing one-bullet-per-term shape — NOT `read_container` itself: the glossary holds general and woodworking vocabulary and high-level model concepts, not specific functions (sh-015's sign-off trimmed the glossary of exactly this kind of entry; do not reintroduce the pattern).
