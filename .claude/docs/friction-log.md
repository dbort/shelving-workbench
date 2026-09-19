---
next_id: friction-011
---

# Friction log

Friction log for working in this repo: moments where completing a task forced an unnecessary workaround. An entry qualifies when there is a clear "this would have been simpler if X existed or Y returned this data" - missing tools, missing data, poor return shapes, absent markers, docs that had to be reverse-engineered.

Logging is part of the work itself: same session, never deferred. A workaround that succeeded smoothly still gets logged: success is what hides the papercut. Entries are raw material for tooling/docs/API improvements.

This file is the canonical rule, per the repo's doc architecture (`pipeline.md` explains the convention); `CLAUDE.md` and the agent files carry at most a one-line pointer here. It lives in `.claude/docs/` because it's agent-contract material: not swept by `doc-hygiene`.

## Origin

From Benjamin André-Micolon's [linkedin post](https://lnkd.in/p/g4ARbEpH) on 2026-08-17.

## Format

Oldest first, by id. One bullet per papercut:

- `friction-NNN` - **<what was needed>**: what happened; the workaround used. Simpler if: <the missing tool/data/doc>.

## Assigning an id

This file's front matter carries `next_id`, the only source of truth for
the next number. To add an entry: take the value of `next_id` verbatim as
the new entry's id, append the entry at the end of `## Entries`, then
increment `next_id` to the next number and commit both changes together.

Never derive an id by scanning `## Entries`, and never consult git history
to work one out. Both look plausible and both are wrong the moment the
highest-numbered entry has been deleted: reading it off the remaining
entries, or off history, reissues an id that already exists in a past
commit, in a closed task file, or in another document's cross-reference.
The counter alone is authoritative, specifically because it still
increases after the entry it points past is gone.

Deleting an entry never changes `next_id`. The counter only moves forward;
an id is retired with the entry it named, not returned to the pool.

## Adding an entry mid-task

An entry written during sh-XXX task work commits on that task's branch with the rest of the work and reaches `main` when the task merges - never a separate commit to `main` (`pipeline.md` § Git branching).

## Solving a papercut

Fixes route like any other work (`pipeline.md` § Task files and directories, last paragraph): task-sized ones become a sh-XXX task via `new-task`; small ones commit directly. Fix each papercut in its own dedicated commit whose message records BOTH the original papercut (the friction it captured) AND how it was solved, in broad strokes - the code carries the detail. Delete the entry from this file in that same commit: the commit history is the durable record, this file tracks only what is still open. Do not touch `next_id` when deleting: it only moves forward, per § Assigning an id above.

Sweeping the log is a human-triggered act, like task sign-off: the user asks for a sweep; no agent schedules one on its own.

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

- `friction-005` - **restricting a spawned subagent's tools to its actual
  role**: a `doc-hygiene` sweep subagent (Bash-capable, running as the
  default general-purpose workflow agent type) inferred from task-file state
  and commit messages that merging the in-progress `sh-XXX` branch into
  `main` was part of finishing the job, and ran `git checkout main` /
  `git merge` on its own — well outside its content-audit/style-pass/verify
  role. The workaround was prose: `approve-task` and `dispatch-tasks` each
  got a paragraph stating that reading their Execution Protocol as reference
  material and reproducing the `git` sequence isn't the same as being
  invoked. Simpler if: `Workflow`'s `agent()` took a tool allowlist
  independent of `agentType` (or a purpose-built, Bash-less agent type
  existed for read/edit-only sweep roles), so a doc-only pass couldn't call
  `git merge` at all, regardless of what it inferred from context, instead of
  the boundary living only in prose that every touched file has to restate.

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

- `friction-008` - **the `_mm` suffix convention has no automated check**:
  `CLAUDE.md` § Project conventions makes the unit suffix mandatory on every
  identifier bound to a physical quantity, and it is the project's whole
  mechanism for unit safety (there is no units type), but neither `ruff` nor
  `mypy --strict` nor anything else in `pixi run tests` looks at identifier
  names. sh-014's review has now spent three rounds on it by hand: round 1
  rejected on a list of unsuffixed names, the implementer swept the ones the
  finding enumerated, round 2 found more of the same class still there, and
  round 3 still found one comprehension target the round-2 finding's own
  "exhaustive" list had missed.
  Worked around by writing a throwaway `ast`-walking script in the scratchpad
  that lists every `arg`, assignment target, and attribute name in the changed
  files without an `_mm`/`_mm3` suffix, then reading the list by hand to decide
  which ones hold millimetres. The script leaves no trace, so the next round
  and the next reviewer start over. Simpler if: a check inside `pixi run tests`
  flagged a float-valued parameter or attribute whose name lacks a unit suffix
  (even a narrow one, over annotated `float` parameters and dataclass fields in
  `shelving_core/`), so the convention failed at lint time instead of costing a
  review round each time a module is ported in from `spikes/`.

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

- `friction-010` - **every `shelving_core` edit pays a vendored-copy tax**:
  sh-013, sh-014, and sh-015 each touched `shelving_core/` (`geometry.py`,
  `scan.py`, `layout.py`, `svg.py`) and each time paid the same tax twice
  over: `tools/vendor-core.sh` had to re-run to keep
  `freecad/shelving/vendor/shelving_core/` byte-identical, and the
  post-approval `doc-hygiene` sweep had to deliberately group each file with
  its vendored twin in the same pipeline group so both copies got edited in
  step, rather than independently and possibly inconsistently. None of this
  is new: the user already decided the fix at sh-012 sign-off (collapse to
  one copy under `freecad/shelving/`, delete `vendor-core.sh` and its drift
  gate, no relative-import workaround) but deferred it until after sh-012
  landed, "before M4+ adds more consumers of the vendored path." M4 (sh-013)
  and M5 (sh-014, sh-015) have both landed since, each adding more files to
  keep in sync, and the task was never opened. Worked around, each time, by
  re-running the sync script and hand-pairing files into doc-hygiene groups.
  Simpler if: the already-decided consolidation task had been created and
  dispatched before M4 started, since every milestone since has only grown
  the set of files paying this tax.
