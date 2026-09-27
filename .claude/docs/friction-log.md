---
next_id: friction-024
---

# Friction log

Moments where developing or testing this repo forced a workaround: a
missing tool, data in the wrong shape, a doc that had to be
reverse-engineered. Log it in the same session, even when the workaround
succeeded. Defects in the shipped workbench go in `bug-log.md` instead.
The idea comes from Benjamin André-Micolon's
[post](https://lnkd.in/p/g4ARbEpH) of 2026-08-17.

An entry qualifies only if its fix is something this repo could build or
write. An upstream tool's permanent behavior belongs in a comment at the
call site, a `docs/*.md` note, or a Claude memory, not here.

Format, oldest first:

- `friction-NNN` - **<what was needed>**: what happened; the workaround
  used. Simpler if: <the missing tool/data/doc>.

The id is `next_id` from the front matter; increment it in the same
commit. It only moves forward, even when entries are deleted. An entry
written during task work commits on the task's branch. The commit that
fixes a papercut records the papercut and its fix and deletes the entry.

## Entries

- `friction-002` - **no headless signal for GUI rendering**: sh-012's sign-off
  defect was that a `Part::FeaturePython` plank with a valid `Shape` never drew
  in the FreeCAD 1.0.0 GUI, because it had no `ViewProvider` proxy. The fix
  (`PlankViewProvider`) can only be exercised in a real GUI: under `freecadcmd`
  `obj.ViewObject` is `None`, so `pixi run tests` cannot assert
  `ViewObject.isVisible()` or that the view-provider binding took. Worked around
  with a Python-console macro in `docs/manual-qa.md` case 2 that the user runs
  once by hand. Simpler if: `freecadcmd` exposed a minimal `ViewObject` (even a
  headless stub whose `isVisible()` / display-mode wiring could be asserted), or
  there were an offscreen-GUI test mode, so view-provider regressions were caught
  by the merge gate instead of at human sign-off.

- `friction-003` - **`freecad-stubs` types names that do not exist at runtime**:
  the plain-planks spike annotated a `Protocol` with `FreeCAD.Quantity` for a
  `Part::Box`'s `Length`. `mypy --strict` accepted it, but FreeCAD 1.0.0 raised
  `module 'FreeCAD' has no attribute 'Quantity'` when the class body evaluated
  the annotation (the runtime name is `FreeCAD.Units.Quantity`). Worked around
  with `from __future__ import annotations` so the annotations are never
  evaluated. Simpler if: the stubs matched the runtime module layout, or the
  repo's type check had a runtime-import smoke that caught a stub-only name
  before it reached a script.

- `friction-004` - **no documented way to get a box's global placement under an
  `App::LinkGroup`**: the spike needed each plank's document-frame corner.
  `getGlobalPlacement` composes only through geo-feature groups, and an
  `App::LinkGroup` is not one, so it silently returns the local placement for a
  Woodworking-style unit (`magicStart` puts its cabinets in a `LinkGroup`).
  Found by testing both container types rather than from any doc; Woodworking
  hits the same wall and hand-rolls `getContainersOffset`. Worked around by
  walking the container chain and multiplying placements in
  `spikes/plain_planks/export_boxes.py`. Simpler if: `getGlobalPlacement`
  composed through link containers too, or the API doc stated which container
  types it honours so the gap was findable without an experiment.

- `friction-006` - **a dataclass default instance of an unhashable class fails
  at import time, not at review time**: sh-013's task file literally specified
  `Bay(rule: SizeRule = Fill(), id)`-shaped defaults for `Bay`, `Void`, and
  `Division`. `Fill`/`Fixed`/`Weighted` are plain (non-frozen) dataclasses, so
  `@dataclass`-generated `__hash__` is `None` for them; CPython's dataclass
  machinery (3.11+) rejects any unhashable default value as a mutable default,
  not only the `list`/`dict`/`set` cases the "mutable default" rule is usually
  remembered for. `ruff` and `mypy --strict` both accept the code silently; the
  failure only surfaces as a `ValueError` the first time the module is
  imported, which the pytest suite already exercises but a plain `python
  tools/layout_demo.py` run caught first. Worked around with
  `field(default_factory=Fill)` on all three. Simpler if: `mypy --strict` or
  `ruff` flagged a non-frozen-dataclass-instance default the same way they'd
  flag a bare `[]` or `{}`, so the mistake surfaced at lint time instead of
  first import.

- `friction-007` - **a task's `## Frontier Advice` named only two of five spike
  files it put at risk**: sh-013's Frontier Advice called
  `spikes/plain_planks/general_model.py` and `test_general_model.py` CRITICAL
  and said not to delete them, but Step 4's deletion of `Carcass`, `Leaf`,
  `Split`, `Divider`, `Orientation`, and `SplitRule` from `shelving_core.layout`
  (and `PlankRole`/`PlankSpec`/`Rect` from `expand.py`/`solver.py`) also broke
  three files the advice never mentioned: `scan.py`, `test_scan.py`, and
  `freecad_spike.py`, none of which the plan's Must Haves or `pixi run tests`
  cover (`pytest shelving_core tests` never touches `spikes/`). The round-1
  review caught it; nothing in the task file said the whole package, not just
  the two named modules, had to keep importing. Reverse-engineered the actual
  scope from `docs/roadmap.md`'s M4/M5/M6 entries, which do commit to the
  entire `spikes/plain_planks/` directory surviving until M6. Worked around by
  vendoring the deleted carcass model verbatim into
  `spikes/plain_planks/carcass_model.py` and repointing all five files' imports
  at it, plus a `tests/test_spike_importable.py` import-collection guard so
  `pixi run tests` catches the next name this package depends on. Simpler if:
  the task file's Frontier Advice had named every file a deletion step put at
  risk, not just the two the plan actively reused, or the Must Have list
  included an import check for the directory the plan promised to keep alive.

- `friction-009` - **a board snapped to its catalog material keeps its raw
  measured extent everywhere else, so a within-tolerance match can still fail
  to solve**: sh-015's end-to-end fixture test needed a catalog built from
  `real_stair_step.boxes.json`'s own measured thicknesses (no fixed catalog is
  given for it elsewhere). That fixture has two boards measured 0.25 mm apart
  (18.0086 mm, 18.2626 mm) that are the same real-world material; the
  measurement gap is ordinary tolerance, and `_material_for_thickness_mm`
  correctly resolves both to the one catalog entry within `snap_mm` (0.5 mm
  default) of each. The actual defect is downstream: nothing reconciles a
  board's geometric extent to the thickness it was just snapped to, so a
  division whose one `Fixed` sibling was sized from a board's *original*
  measured extent no longer sums to the span once that board's snapped
  thickness differs from its raw measurement, and `solve` fails with an
  opaque `no_slack_absorber` naming an unrelated division rather than the
  board whose thickness moved. Diagnosed by bisecting: the same
  `no_slack_absorber` reproduced even with the existing fixed
  `ply18`/`mdf12` test catalog, which was 0.26 mm off this fixture's real ply
  thickness in the same direction. Worked around by passing a tighter
  `snap_mm=0.1` to `scan` for this fixture's test so both boards' measured
  thicknesses landed close enough to the catalog entry that the extent
  mismatch stayed under the solver's own slack, sidestepping the reconciliation
  gap rather than closing it. This is exactly the kind of tolerance a human
  builder would also hit (two measurements of the same board never agree to
  the micron), so it is a real model gap, not a test-fixture quirk. Simpler
  if: a board's geometric extent were corrected to its snapped catalog
  thickness at the point of the snap, so every sibling sized against it
  agrees; short of that, `scan` or `solve` naming the board whose extent and
  material disagree, instead of an unrelated division's slack failing to
  balance. Possible product angle, not scoped or planned: the editing UI
  could surface a within-tolerance match instead of applying it silently,
  and let the user confirm snapping the board to the catalog dimension.

- `friction-011` - **`App::DocumentObjectGroup` carries no `Placement`
  property at all**: sh-016's container walk composed `obj.Placement` for
  every container with children, on the reasonable-looking assumption that
  any container a document tree can nest (`App::Part`, `App::LinkGroup`,
  `App::DocumentObjectGroup`) has one, since the first two do. A headless
  smoke-test run raised `AttributeError` the moment a plain
  `App::DocumentObjectGroup` entered the tree (used to prove the same object
  reachable by two paths still yields one record). Nothing in
  `docs/freecadcmd-notes.md` or `freecad-stubs` flagged the gap; it only
  surfaced by running real geometry through `freecadcmd`. Worked around by
  reading `Placement` with `getattr(obj, "Placement", None)` and skipping the
  compose step when it is absent. Simpler if: `freecad-stubs` distinguished
  the `GeoFeatureGroup`-derived container types (which carry `Placement`)
  from `App::DocumentObjectGroup` (which does not), or
  `docs/freecadcmd-notes.md` carried this alongside its existing
  container-behavior entries.

- `friction-012` - **no documented recipe for building a `PartDesign::Body`
  headlessly**: sh-016's functional smoke test needed a real notched panel
  (a `PartDesign::Body` holding a `Sketcher::SketchObject` and a
  `PartDesign::Pad`) to exercise the box-minus-cutouts skip path, and neither
  `docs/freecadcmd-notes.md` nor any surviving code showed the construction:
  the tuple shape a sketch's `AttachmentSupport` needs, that a fresh
  `PartDesign::Body` auto-creates an `Origin` whose `XY_Plane` is reachable
  via `doc.getObject("XY_Plane")`, or that a body's own children come from
  `GroupExtension.newObject`, not `Document.addObject`. Reverse-engineered by
  trial against a real `freecadcmd` interpreter. Simpler if:
  `docs/freecadcmd-notes.md` carried a short "building a PartDesign feature
  headlessly" recipe, since this task is unlikely to be the last one needing
  more than a bare `Part::Box`.

- `friction-019` - **diff-scoped `doc-hygiene` never re-examines a
  pre-existing content violation on a line its own diff extends**: found
  during `sh-019` manual sign-off review, on `freecad/Shelving/init_gui.py`'s
  `ShelvingWorkbench` docstring: `"Initialize registers the Shelving toolbar
  and menu, wired to the Shelving_Scan, ... commands."` names every command
  id, and `Initialize`'s own `command_ids` list four lines later names the
  same ids verbatim, a textbook case of this skill's own content-audit rule
  1 ("a file-level or function-level preamble that lists the... functions...
  that follow: it is 'what' content even when it is not line-adjacent").
  This branch's diff added three more command ids to both the docstring and
  the list (`Shelving_SeedCatalog`, `Shelving_AddMaterial`,
  `Shelving_ReflowAll`), so the diff touched, and worsened, the exact line
  carrying the violation. Two separate `doc-hygiene --diff=main` runs on
  this branch (after the round-1 review approval, and again after round 3)
  both left it: the content-audit agent's own report said the docstring
  "matches pre-existing listing style... not something this diff
  introduced." The skill's diff-scope instruction is why: it tells an agent
  to constrain edits to "changed lines, plus any pre-existing comment nearby
  that the diff has made stale," and explicitly "do not perform a general
  hygiene sweep of unrelated, unchanged content elsewhere in the file, even
  if you notice something else worth fixing there." A three-name append to
  an already-duplicating list is a changed line, but the violation itself
  predates the diff, so "made stale by this diff" reads as false even
  though the diff makes the existing violation larger. Fixed ad hoc on
  `sh-019`'s own branch by trimming the docstring to `"FreeCAD workbench
  entry point for parametric shelving."` and removing the id list, since
  that one instance was small and localized. Simpler if: `doc-hygiene`'s
  content-audit and diff-scope prompts treated "this diff added a line to
  an already-violating block" as in-scope, distinct from "this diff made a
  previously-fine comment inaccurate," so a growing duplication does not
  keep surviving sweep after sweep just because no single sweep introduced
  it.

- `friction-020` - **a task's Execution Plan named only one of two test files
  a corrected tree shape changed**: sh-025's Must Have list and Execution
  Plan Step 4 named `test_scan.py`'s `real_stair_step`/`real_two_units`
  whole-tree assertions as needing an update for the corrected
  `Division`+`Void` wrapping, but the same fixture's rendered text summary
  in `test_report.py::test_stair_step_report_shows_plane_facing_and_tree`
  also asserts a literal indentation depth for `panelZX012`, which shifted
  one level deeper once the fix wrapped it. `pixi run tests` at the
  deferred checkpoint caught it as an unplanned failure only after steps 1-4
  landed, not named anywhere in the task file. Fixed by updating that one
  assertion to the corrected report output. Simpler if: the planning pass
  had grepped the fixture name (`REAL_STAIR_STEP`/`real_stair_step`) across
  `freecad/Shelving/core/tests/` before writing the Must Have list, the way
  friction-007 already flagged for a deletion step's blast radius; a
  tree-shape change has the same "everything that renders this fixture" risk
  a signature-deletion change does.
- `friction-021` - **readable `pixi run tests` output**: in sh-020's review,
  the FreeCAD smokes printed `Recompute......` progress bars made of tabs and
  percentages, which hid the pass/fail lines. The workaround was to
  redirect the run to a file, record `$?` separately, and pipe the log through
  `tr '\t' ' ' | grep -Ev 'Recompute|\([0-9]+ %\)'` to read it. Simpler if:
  `tools/run-tests.sh` (or the smokes themselves) suppressed or filtered
  FreeCAD's console progress indicator so the harness output shows only the
  check headers and results.
- `friction-022` - **a way to run doc-hygiene's embedded workflow script
  outside a real sweep**: merging its content and style passes changed the JS
  inside `.claude/skills/doc-hygiene/SKILL.md`, and nothing in the repo can
  parse or dry-run that script; the environment has no JS runtime. The
  workaround was extracting the fenced block with an ad hoc Python snippet,
  stubbing `agent`/`pipeline`, and running it under `pixi exec -s nodejs
  node` to confirm every prompt rendered. Simpler if: a check in `pixi run
  tests` extracted the block, stubbed the workflow API, and dry-ran it in
  both full-tree and diff-scoped modes.
- `friction-023` - **no merge-gate coverage for the editor panel's wiring**:
  sh-021's panel logic (the quantity field reporting only a changed value,
  applying on the f(x) dialog closing, drag press/move/release, the
  untagged-object checkboxes) could only be exercised by one-off scripts
  run under `QT_QPA_PLATFORM=offscreen pixi run freecad script.py`, which
  also caught two real defects (an f(x) expression never reaching the
  layout, a focus-out fixing a Fill region). Those scripts lived in the
  session scratchpad and are gone. Simpler if: `pixi run tests` ran a GUI
  smoke under that offscreen `freecad` invocation
  (`docs/freecadcmd-notes.md`, "GUI-only widget access"), which would also
  answer `friction-002`.
