---
id: sh-020
title: "The elevation editor: structure"
current_agent: implementer
current_phase: planning
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
Milestone M9, part 1 of 2.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] `shelving_core/edit.py` exports `split_region`, `merge_at`, and
      `EditError`. Every function takes a `Unit` and returns a `Unit`, never
      mutating its argument, and imports no Qt and no FreeCAD.
- [ ] `split_region(unit, region_id, axis, material)` divides a `Bay` into two
      equal bays separated by a board, and refuses a `Void`, a `Division`, and
      an unknown id, each naming what it refused.
- [ ] `merge_at(unit, board_id)` removes a board and merges the regions either
      side into one, and refuses a board whose neighbours are not both regions,
      naming it.
- [ ] Splitting then merging at the new board returns a unit whose tree shape
      equals the original. Asserted for at least three starting shapes.
- [ ] `shelving/editor/scene.py` builds a `QGraphicsScene` from a
      `Unit` and its solved spaces, with each item carrying the id of the region
      or board it draws, and hit-testing a scene point returning that id.
- [ ] The scene is tested headlessly: an offscreen `QApplication`, an asserted
      item count and bounding rect, hit tests landing on the expected ids, and a
      simulated click through `QtTest` reaching the scene.
- [ ] A `Void` draws distinctly from a `Bay`, and a selected region draws
      distinctly from an unselected one. Asserted by item state, not by pixels.
- [ ] `Shelving_EditUnit` opens the panel on exactly one selected container,
      refusing anything else with a message.
- [ ] The panel opens one transaction on show, commits on OK, aborts on Cancel.
      A test drives the underlying session object, not the panel, through a
      split and a cancel, and asserts the document is byte-identical in board
      count, names, sizes and placements.
- [ ] An edit that will not solve leaves the document at the last state that
      did: the session returns the error rather than raising, and no partial
      write reaches the document. One test per refusal reason.
- [ ] `tools/freecad_editor_smoke.py` prints `shelving editor OK` and
      `tools/run-tests.sh` greps for it.
- [ ] `docs/manual-qa.md` has an M9 section covering the panel shell, selection,
      split, merge, and undo of a whole session.
- [ ] `mypy --strict` clean.

## Frontier Advice

THREE LAYERS, and the split is the point of this task. Do not collapse them.
1. `shelving_core/edit.py`: tree operations. `Unit` in, `Unit` out. No Qt, no
   FreeCAD, tested in the fast suite. Every editing decision that has a right
   answer lives here.
2. `shelving/editor/scene.py`: Qt rendering and hit testing. Builds
   items from a `Unit` plus its solved spaces, tags each with an id, answers
   "what is at this point". Knows nothing about documents or transactions.
3. `shelving/editor/session.py` and `panel.py`: the session owns the
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

EDITS RETURN A RESULT, NEVER RAISE THROUGH THE PANEL. `shelving_core.edit`
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

SPLIT SEMANTICS. `split_region` puts a board in the middle of a bay and gives
each half a `Fill` rule, so the two openings share the space equally and a later
resize keeps them equal. The board's material is the caller's argument,
defaulting to the unit's. The new board's id is a fresh `new_id()`; sh-018's
write path assigns the real FreeCAD name when it creates the object.

MERGE SEMANTICS. `merge_at` is the exact inverse: remove the board, replace the
two neighbouring regions with one whose rule is the first's. A board whose
neighbours are not both regions, meaning it sits against another board or at the
end of a run, cannot be merged and must be refused by name rather than producing
a surprising tree.

IMPORT CORE TYPES FROM ONE PLACE ONLY. `shelving/editor/session.py`
does `isinstance` / structural matching on `Region`, `Bay`, `Void`, `Division`,
`Board` to decide what a selection permits. `shelving_core/` and
`shelving/vendor/shelving_core/` are byte-identical but distinct Python
packages; a `Board` imported from one is not the same class as one imported
from the other, so `isinstance` silently returns false across them with no
error. `shelving_core`'s own modules import each other relatively, so the
vendored copy is internally self-consistent no matter what else is on
`sys.path` (enforced by a test in `shelving_core/tests/`, named for this
invariant), but that guarantee is about `shelving_core`'s own internals, not
about this file: import every core type `session.py` matches against from
`shelving_core.*` (never `shelving.vendor.shelving_core.*`),
consistently through the module, the same way every other FreeCAD-layer
module in this codebase does. A prior version of this workbench lost every
divider by breaking that rule.

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

- [ ] **Step 1** (`shelving_core/edit.py`, `shelving_core/tests/test_edit.py`): Create the module. `EditError(ValueError)` carrying the offending id. `split_region(unit, region_id, axis, material=None) -> Unit` rebuilding the tree with the named `Bay` replaced by a `Division` along `axis` holding bay, board, bay, both bays `Fill`; refuse a `Void`, a `Division`, and an unknown id. `merge_at(unit, board_id) -> Unit` replacing a board and its two neighbouring regions with one region carrying the first's rule; refuse a board whose neighbours are not both regions and an unknown id. Both must return a new tree and leave the argument untouched, asserted. Tests: each refusal; split then merge round-trips the tree shape for a single bay, a nested division, and a stepped unit; the argument unit is unchanged after each call.

- [ ] **Step 2** (`shelving/editor/scene.py`): Create the scene builder, importing Qt but no FreeCAD. `build_scene(unit, spaces, selected_id=None) -> QGraphicsScene` adding one rect per region and per board, projected along the unit's depth axis, each carrying its id via `setData`. A `Void` gets a distinct brush from a `Bay`, and the selected item gets a distinct pen. `hit_test(scene, point) -> str | None` returning the id of the topmost item at a scene point. Keep the drawing primitives shared with `shelving_core/svg.py` in spirit but do not import it: an SVG string cannot become Qt items.

- [ ] **Step 3** (`shelving/editor/tests/test_scene.py` or the repo's test location for FreeCAD-side code): Create the offscreen suite. Set `QT_QPA_PLATFORM=offscreen` before importing PySide6 and reuse an existing `QApplication`. Assert: item count matches regions plus boards; the scene bounding rect matches the unit's projected extent; hit tests at points inside a known bay, a known board, and a known void return those ids; a point outside returns `None`; the selected item's pen differs from the others'; a `Void`'s brush differs from a `Bay`'s; and a `QtTest.QTest.mouseClick` on a view over the scene reaches the scene and reports the expected id.

- [ ] **Step 4** (`shelving/editor/session.py`): Create the session, which owns the document side and holds every decision the panel would otherwise make. Construct from a container: read it, scan it, apply stored rules, and keep the resulting `Unit` plus the catalog. `open()` starting the transaction. `select(id)`, `can_split()`, `can_merge()` reporting what the current selection permits. `split(axis)` and `merge()` calling the core edit, re-solving, writing through sh-018's write path, and returning either the new state or a structured failure carrying the message and the offending id; on failure change nothing. `commit()` and `cancel()` ending the transaction. No Qt anywhere in this module.

- [ ] **Step 5** (`shelving/editor/panel.py`, `shelving/commands/edit_unit.py`, `shelving/init_gui.py`): The task panel and its command. The panel holds a `QGraphicsView` over the scene, buttons for Split Horizontal, Split Vertical and Delete, and a message line; it constructs a session, rebuilds the scene after each edit, enables buttons from `can_split` and `can_merge`, and shows a failure's message without changing the view. `getStandardButtons` returning OK and Cancel, `accept` calling `commit`, `reject` calling `cancel`. `Shelving_EditUnit` requires exactly one selected container and shows the panel through `FreeCADGui.Control.showDialog`, behind the headless-safe guard. Add the id to `init_gui`'s `command_ids`.

- [ ] **Step 6** (`tools/freecad_editor_smoke.py`, `tools/run-tests.sh`): The headless functional check, driving the SESSION rather than the panel, since `FreeCADGui.Control` does not exist under `freecadcmd`. Build a document with a unit, open a session, and assert: selecting a bay permits split and not merge; splitting writes one new board and two bays; selecting that board permits merge; merging removes it and restores the original board count and names; an edit that cannot solve returns a failure and leaves board count, names, sizes and placements unchanged; cancel after several edits restores the document to its opening state exactly; commit after the same edits leaves them in place and one undo reverses the lot. Print `shelving editor OK` last and add a matching block to `tools/run-tests.sh`.

- [ ] **Step 7** (`docs/manual-qa.md`, `README.md`): Add an `## M9` section in the file's numbered-steps-then-expected-result shape, covering what only a human can check: the panel opens and docks, the elevation is legible and matches the 3D, clicking a compartment highlights it, Split and Delete are enabled only when they apply, the 3D follows each edit, Cancel reverses everything, and one undo after OK reverses the whole session. Extend the README glossary with the three editor layers and the session, in the section's existing one-bullet-per-term shape.
