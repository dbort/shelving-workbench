---
id: sh-020
title: "The elevation editor: structure"
current_agent: implementer
current_phase: implementation
review_rejections: 0
blocked_by: [sh-019]
---

# sh-020: The elevation editor: structure

## Summary
The modal task panel and everything structural in it: an elevation drawn from a
scanned unit, click a compartment to select it, split it along either axis,
delete a board to merge its neighbours. Edits are tree operations in the core
where the fast suite can test them, the Qt scene only renders and hit-tests, and
the panel is a thin shell over both. Live preview writes the real boards inside
one transaction, so OK commits and Cancel reverses the whole session.
Sign-off added: clearer button labels, opening the editor from any selection
inside one unit, switchable timing logs, and a fix so an editor-built layout
reads back unchanged instead of shifting shelves on the next edit (bug-006).
Milestone M9, part 1 of 2.

## Status
- [x] Planning
- [x] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `freecad/Shelving/core/edit.py` exports `split_region`, `merge_at`, and
      `EditError`. Every function takes a `Unit` and returns a `Unit`, never
      mutating its argument, and imports no Qt and no FreeCAD.
- [x] `split_region(unit, region_id, axis, material)` divides a `Bay` into two
      equal bays separated by a board, and refuses a `Void`, a `Division`, and
      an unknown id, each naming what it refused.
- [x] `merge_at(unit, board_id)` removes a board and merges the regions either
      side into one, and refuses a board whose neighbours are not both regions,
      naming it.
- [x] Splitting then merging at the new board returns a unit whose tree shape
      equals the original. Asserted for at least three starting shapes.
- [x] `freecad/Shelving/editor/scene.py` builds a `QGraphicsScene` from a
      `Unit` and its solved spaces, with each item carrying the id of the region
      or board it draws, and hit-testing a scene point returning that id.
- [x] The scene is tested headlessly: an offscreen `QApplication`, an asserted
      item count and bounding rect, hit tests landing on the expected ids, and a
      simulated click through `QtTest` reaching the scene.
- [x] A `Void` draws distinctly from a `Bay`, and a selected region draws
      distinctly from an unselected one. Asserted by item state, not by pixels.
- [x] `Shelving_EditUnit` is enabled, and opens the panel, when
      `container.unit_for_selection` names one unit: the unit's container, or
      objects that all sit inside the same unit. A lone container with no
      `ShelvingUnitId` also qualifies. Anything else is disabled and refused
      with a message. The editor smoke covers the mapping.
- [x] The panel's split buttons read **Add Divider** and **Add Shelf**.
- [x] `freecad/Shelving/debug_log.py`: `enabled` defaults `True`, callers read
      `is_enabled()`, each Edit Unit run logs `BEGIN`/`END` markers sharing a
      `#N` id and timestamp with every stage's time between them, and
      `tests/test_debug_log.py` covers markers, ids and the switch.
- [x] Splitting a bay whose parent `Division` runs along the split axis
      inserts `Bay, Board, Bay` into that parent's run; no same-axis
      `Division` is ever nested directly inside another. Asserted in
      `test_edit.py`.
- [x] A merge never leaves a same-axis `Division` directly inside another,
      and moves no surviving board. Asserted in `test_edit.py` for the
      divider, shelf left, delete divider sequence.
- [x] No edit moves a board it did not create or delete: after every split and
      merge, every surviving board's solved origin and size match its
      pre-edit values within `1e-6` mm. Asserted in `test_edit.py` for splits
      and merges in runs of Fill, Weighted and Fixed siblings, the user's
      bug-006 sequence among them.
- [x] An editor-built layout reads back unchanged. After the bug-006 sequence
      (divider; shelf left; shelf top-left; OK), a fresh `Session` on the
      container solves every board to its document placement and size within
      `1e-6` mm, and a further edit elsewhere moves no left-side board.
      Asserted in `tools/freecad_editor_smoke.py`.
- [x] bug-006's entry is deleted from `.claude/docs/bug-log.md` in the
      commit that fixes it; `next_id` unchanged.
- [x] The panel opens one transaction on show, commits on OK, aborts on Cancel.
      A test drives the underlying session object, not the panel, through a
      split and a cancel, and asserts the document is byte-identical in board
      count, names, sizes and placements.
- [x] An edit that will not solve leaves the document at the last state that
      did: the session returns the error rather than raising, and no partial
      write reaches the document. One test per refusal reason.
- [x] `tools/freecad_editor_smoke.py` prints `shelving editor OK` and
      `tools/run-tests.sh` greps for it.
- [x] `docs/manual-qa.md` has an M9 section covering the panel shell, selection,
      split, merge, and undo of a whole session.
- [x] `mypy --strict` clean.

## Frontier Advice

THREE LAYERS, and the split is the point of this task. Do not collapse them.
1. `freecad/Shelving/core/edit.py`: tree operations. `Unit` in, `Unit` out. No Qt, no
   FreeCAD, tested in the fast suite. Every editing decision that has a right
   answer lives here.
2. `freecad/Shelving/editor/scene.py`: Qt rendering and hit testing. Builds
   items from a `Unit` plus its solved spaces, tags each with an id, answers
   "what is at this point". Knows nothing about documents or transactions.
3. `freecad/Shelving/editor/session.py` and `panel.py`: the session owns the
   document, the transaction, and the write path; the panel is the Qt dialog
   wiring buttons to the session. The panel must hold NO logic worth testing.

WHY: verified against this environment, an offscreen `QApplication` works under
`freecadcmd` with `QT_QPA_PLATFORM=offscreen`, and `QGraphicsScene`, hit
testing, and `QtTest` simulated clicks all function. What does NOT exist
headlessly is `FreeCADGui.Control`, the task-panel shell. So layers 1 and 2 are
fully testable and only the dialog wiring is manual. Any logic that leaks into
`panel.py` becomes untestable.

TESTS FOR LAYER 2 MUST SET `QT_QPA_PLATFORM=offscreen` BEFORE importing
PySide6, and must reuse `QtWidgets.QApplication.instance()` when one exists; a
second `QApplication` in one process aborts. PySide6 is 6.7.3 in this
environment.

EDITS RETURN A RESULT, NEVER RAISE THROUGH THE PANEL. `freecad.Shelving.core.edit`
raises `EditError` for a structurally impossible request, such as splitting a
`Void`. The session catches both that and `LayoutSolveError`, returns the
message and the offending id to the panel, and leaves the document untouched.
The document must never hold geometry that does not satisfy the model: reject
the edit whole rather than writing part of it.

LIVE PREVIEW WRITES REAL BOARDS. On each accepted edit, call sh-018's write
path inside the transaction the panel already opened. Measured cost is about
nine milliseconds for forty-five boards, so this is interactive. Do NOT build a
second preview model: it would have to agree with the real write path, and any
divergence would show the user something apply does not produce.

ONE TRANSACTION PER SESSION. `openTransaction` when the panel opens,
`commitTransaction` on OK, `abortTransaction` on Cancel, so the whole session
is one undo step. Never open a transaction per edit. The transaction calls need
`# type: ignore[no-untyped-call]`; `freecad-stubs` leaves them unannotated.

SPLIT SEMANTICS. `split_region` puts a board in the middle of a bay, giving two
equal openings. The board's material is the caller's argument,
defaulting to the unit's. The new board's id is a fresh `new_id()`; sh-018's
write path assigns the real FreeCAD name when it creates the object.

MERGE SEMANTICS. `merge_at` is the exact inverse: remove the board, replace the
two neighbouring regions with one. A board whose
neighbours are not both regions, meaning it sits against another board or at the
end of a run, cannot be merged and must be refused by name rather than producing
a surprising tree.

IMPORT CORE TYPES FROM ONE PLACE ONLY. `freecad/Shelving/editor/session.py`
does `isinstance` / structural matching on `Region`, `Bay`, `Void`, `Division`,
`Board` to decide what a selection permits. Import every core type
`session.py` matches against from `freecad.Shelving.core.*`, fully qualified,
consistently through the module, the same way every other FreeCAD-layer
module in this codebase does. `freecad.Shelving.core` exists as a single copy
in this codebase (`freecad/Shelving/core/`); a prior version of this
workbench, before that consolidation, lost every divider because two
importable copies of the same classes produced two distinct `Board` classes
that `isinstance` silently failed to match across.

BUG-006: EDITS MUST SURVIVE A RESCAN. Read `.claude/docs/bug-log.md` bug-006
first. Scanning cannot see same-axis nesting in geometry: a column the editor
built as `z[Bay, s1, z[Bay, s2, Bay]]` rescans as `z[Bay, s1, Bay, s2, Bay]`,
and stored rules keyed by bounding boards then solve it to different sizes.
RULES:
1. FLAT RUNS ONLY. When the selected bay's parent `Division` has the split
   axis, splice `Bay, Board, Bay` into the parent's `items` in the bay's
   place. Nest a new `Division` only when the axis differs from the parent's
   (or the bay is the root). Never produce a same-axis `Division` directly
   inside another.
2. GEOMETRY-PRESERVING RULES. Choose the new regions' rules so `solve`
   reproduces the pre-edit sizes of every other region in the run. A `Fixed`
   bay splits into two `Fixed` halves of `(size - thickness) / 2`. For
   weighted or `Fill` bays: a weighted region's size is `w / W_total * L`,
   where `L` is the leftover the run's weighted regions share. Solve for the
   halves' equal weight `w` so every other weighted sibling keeps its size
   and each half gets `(size - thickness) / 2`. When the run holds no other
   weighted region, give both halves `Fill`. Merging is the inverse: the
   merged region takes `size1 + thickness + size2`, `Fixed` if both were
   `Fixed`, otherwise a weight solved the same way.
3. `edit.py` MAY IMPORT `core.solver` to read current sizes. `split_region`
   and `merge_at` take the `Catalog` as a new parameter; this relaxes the
   module docstring's "no solver call", so update it.
4. Existing rejections stay: a solve failure is still returned by the
   session, not raised.
5. OUT OF SCOPE: bug-005, splitting a non-`Bay` region, and bug-007, stored
   rules overriding hand-moved geometry. Do not fix them here; a test may
   avoid hand moves.
6. MERGE KEEPS RUNS FLAT TOO. When a merge collapses a `Division` to a
   single region and that region is itself a `Division` on the
   grandparent's axis (divider, shelf left, delete divider), splice its
   items into the grandparent's run in its place, assigning rules by rule 2
   so no board moves. Dropping a divided second neighbour's subtree is
   otherwise unchanged.

DEBUG LOG STAYS. `freecad/Shelving/debug_log.py` and its `Stopwatch` calls
in `edit_unit.py`, `panel.py`, `session.py` are permanent diagnostics the
user asked to keep; do not remove them. New or changed code MAY add
`debug_log.log` lines where a future bug report would need them.

SELECTION IS A REGION ID OR A BOARD ID, held by the session, not the scene. The
scene reports what a point hit; the session decides what that means and what the
buttons do with it. Splitting acts on a selected `Bay`; deleting acts on a
selected `Board`.

DIMENSIONS ARE NOT IN THIS TASK. No typed sizes, no dragging, no measurement
basis, no untagged-object choice. Those are sh-021. Draw sizes as static labels
if useful, but wire no editing to them.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. PySide6 is
typed, so do not reach for `Any` at the Qt boundary. Shell stays simple applies:
the only shell edit is adding a smoke block to `tools/run-tests.sh` in the same
shape as the existing ones.

Every length identifier carries `_mm`.

## Execution Plan

- [x] **Step 1** (`freecad/Shelving/core/edit.py`, `freecad/Shelving/core/tests/test_edit.py`): Create the module. `EditError(ValueError)` carrying the offending id. `split_region(unit, region_id, axis, material=None) -> Unit` rebuilding the tree with the named `Bay` replaced by a `Division` along `axis` holding bay, board, bay, both bays `Fill`; refuse a `Void`, a `Division`, and an unknown id. `merge_at(unit, board_id) -> Unit` replacing a board and its two neighbouring regions with one region carrying the first's rule; refuse a board whose neighbours are not both regions and an unknown id. Both must return a new tree and leave the argument untouched, asserted. Tests: each refusal; split then merge round-trips the tree shape for a single bay, a nested division, and a stepped unit; the argument unit is unchanged after each call.

- [x] **Step 2** (`freecad/Shelving/editor/scene.py`): Create the scene builder, importing Qt but no FreeCAD. `build_scene(unit, spaces, selected_id=None) -> QGraphicsScene` adding one rect per region and per board, projected along the unit's depth axis, each carrying its id via `setData`. A `Void` gets a distinct brush from a `Bay`, and the selected item gets a distinct pen. `hit_test(scene, point) -> str | None` returning the id of the topmost item at a scene point. Keep the drawing primitives shared with `freecad/Shelving/core/svg.py` in spirit but do not import it: an SVG string cannot become Qt items.

- [x] **Step 3** (`freecad/Shelving/editor/tests/test_scene.py` or the repo's test location for FreeCAD-side code): Create the offscreen suite. Set `QT_QPA_PLATFORM=offscreen` before importing PySide6 and reuse an existing `QApplication`. Assert: item count matches regions plus boards; the scene bounding rect matches the unit's projected extent; hit tests at points inside a known bay, a known board, and a known void return those ids; a point outside returns `None`; the selected item's pen differs from the others'; a `Void`'s brush differs from a `Bay`'s; and a `QtTest.QTest.mouseClick` on a view over the scene reaches the scene and reports the expected id.

- [x] **Step 4** (`freecad/Shelving/editor/session.py`): Create the session, which owns the document side and holds every decision the panel would otherwise make. Construct from a container: read it, scan it, apply stored rules, and keep the resulting `Unit` plus the catalog. `open()` starting the transaction. `select(id)`, `can_split()`, `can_merge()` reporting what the current selection permits. `split(axis)` and `merge()` calling the core edit, re-solving, writing through sh-018's write path, and returning either the new state or a structured failure carrying the message and the offending id; on failure change nothing. `commit()` and `cancel()` ending the transaction. No Qt anywhere in this module.

- [x] **Step 5** (`freecad/Shelving/editor/panel.py`, `freecad/Shelving/commands/edit_unit.py`, `freecad/Shelving/init_gui.py`): The task panel and its command. The panel holds a `QGraphicsView` over the scene, buttons for Split Horizontal, Split Vertical and Delete, and a message line; it constructs a session, rebuilds the scene after each edit, enables buttons from `can_split` and `can_merge`, and shows a failure's message without changing the view. `getStandardButtons` returning OK and Cancel, `accept` calling `commit`, `reject` calling `cancel`. `Shelving_EditUnit` requires exactly one selected container and shows the panel through `FreeCADGui.Control.showDialog`, behind the headless-safe guard. Add the id to `init_gui`'s `command_ids`.

- [x] **Step 6** (`tools/freecad_editor_smoke.py`, `tools/run-tests.sh`): The headless functional check, driving the SESSION rather than the panel, since `FreeCADGui.Control` does not exist under `freecadcmd`. Build a document with a unit, open a session, and assert: selecting a bay permits split and not merge; splitting writes one new board and two bays; selecting that board permits merge; merging removes it and restores the original board count and names; an edit that cannot solve returns a failure and leaves board count, names, sizes and placements unchanged; cancel after several edits restores the document to its opening state exactly; commit after the same edits leaves them in place and one undo reverses the lot. Print `shelving editor OK` last and add a matching block to `tools/run-tests.sh`.

- [x] **Step 7** (`docs/manual-qa.md`, `README.md`): Add an `## M9` section in the file's numbered-steps-then-expected-result shape, covering what only a human can check: the panel opens and docks, the elevation is legible and matches the 3D, clicking a compartment highlights it, Split and Delete are enabled only when they apply, the 3D follows each edit, Cancel reverses everything, and one undo after OK reverses the whole session. Extend the README glossary with the three editor layers and the session, in the section's existing one-bullet-per-term shape.

- [x] **Step 8** (`freecad/Shelving/editor/panel.py`, `freecad/Shelving/container.py`, `freecad/Shelving/commands/edit_unit.py`, `tools/freecad_editor_smoke.py`, `docs/manual-qa.md`, `README.md`): Sign-off feedback, done at `user_signoff` (commit ed632a9). Buttons read Add Divider and Add Shelf. `container.unit_for_selection` resolves a selection to its unit by walking group membership up `InList`; `Shelving_EditUnit` uses it for `IsActive` and `Activated`. Smoke check `_check_selection_maps_to_its_unit`; manual QA M9 case 8. REVIEWER: verify this step; it has not been reviewed.

- [x] **Step 9** (`freecad/Shelving/debug_log.py`, `tests/test_debug_log.py`, `freecad/Shelving/commands/edit_unit.py`, `freecad/Shelving/editor/panel.py`, `freecad/Shelving/editor/session.py`, `README.md`): Switchable timing log, done at `user_signoff` (commit 595b406). REVIEWER: verify this step; it has not been reviewed.

- [x] **Step 10** (`freecad/Shelving/core/edit.py`, `freecad/Shelving/core/tests/test_edit.py`, `freecad/Shelving/editor/session.py`): Fix bug-006 per Frontier Advice § BUG-006. Splice same-axis splits into the parent run; assign geometry-preserving rules on split and merge; pass the session's catalog through. Tests: no same-axis nesting after any split; every surviving board's solved origin and size unchanged within `1e-6` mm across split and merge in Fill-only, Weighted, Fixed and mixed runs; the bug-006 sequence built in core (divider, shelf left, shelf top-left) keeps both left shelves where they were; split-then-merge still round-trips tree shape AND geometry; existing refusals unchanged.

- [x] **Step 11** (`tools/freecad_editor_smoke.py`, `docs/manual-qa.md`, `.claude/docs/bug-log.md`): Smoke `_check_an_editor_layout_survives_a_rescan`: in a real document run the bug-006 sequence through `Session`, commit, open a fresh `Session`, assert every board's solved placement and size match the document within `1e-6` mm, add a shelf on the right, commit, assert no left-side board moved. Add M9 case 9 reproducing the bug-006 steps with the expected result that the left shelves stay put. Delete bug-006 from `.claude/docs/bug-log.md` in the fixing commit, leaving `next_id` untouched; the commit message names bug-006 and how it was fixed.
