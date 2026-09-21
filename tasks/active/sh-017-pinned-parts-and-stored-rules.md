---
id: sh-017
title: "Pinned parts and the stored rule record"
current_agent: implementer
current_phase: implementation
review_rejections: 0
blocked_by: [sh-013, sh-014]
---

# sh-017: Pinned parts and the stored rule record

## Summary
The core half of writing a container. Adds the pinned board, a part the
workbench cannot regenerate such as a notched panel, which the solver verifies
rather than derives and which apply will move but never rewrite. Adds the
record of what geometry cannot carry, the per-region size rules, keyed by the
boards that bound each region so it survives a rescan that assigns fresh ids.
Milestone M7, part 1 of 2.

## Status
- [x] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] `Board` carries `pinned_size_mm: Vec3 | None = None`. `None` means the
      board is regenerable; a value means it is not, and carries the shape it
      is pinned at.
- [ ] `solve` verifies a pinned board rather than deriving it: it computes the
      extent the layout implies and raises `LayoutSolveError` with reason
      `pinned_mismatch`, naming the board, when that differs from
      `pinned_size_mm` by more than `EPS_MM` on any axis.
- [ ] `Box` carries `pinned: bool = False`. `scan` places a pinned box as a
      `Board` with `pinned_size_mm` set from its measured extent, rather than
      listing it in `skipped`.
- [ ] `Box` carries `material: MaterialId | None = None`. When set, `scan` uses
      it and does NOT match by thickness; an id absent from the catalog raises
      `ScanError` naming the board. Thickness matching applies only to a box
      with no material. Two tests: a board whose stored material names an entry
      whose thickness differs from its measured extent still resolves to that
      entry; a board with no material still matches by thickness.
- [ ] `freecad/Shelving/core/record.py` exports `rule_key`, `rules_to_json`,
      `rules_from_json`, and `with_stored_rules`.
- [ ] A region's rule key is the names of the boards bounding it along its
      division's axis, with an explicit sentinel for an end of the run, so the
      key survives a rescan that assigns fresh region ids.
- [ ] `with_stored_rules(unit, rules)` returns a `Unit` with every matching
      region's rule replaced and every unmatched region left as scanned. A test
      proves a rule whose key no longer matches, because a bounding board was
      renamed, falls back to the scanned rule rather than raising.
- [ ] Round trip: for at least three units, `rules_from_json(rules_to_json(u))`
      applied through `with_stored_rules` to a rescan of `expand(u)` reproduces
      every rule, including a `Fixed` that the equal-siblings heuristic would
      have recovered as `Fill`.
- [ ] The record carries a schema version and `rules_from_json` raises
      `ValueError` on any other version.
- [ ] `mypy --strict` clean; `freecad.Shelving.core` imports no FreeCAD.

## Frontier Advice

CRITICAL CONTEXT: this is the core half of M7. The FreeCAD half, sh-018,
stores what this task defines and writes boards back to a container. Build
nothing FreeCAD here; `tests/test_no_freecad.py` must still pass.

PINNED SEMANTICS, decided in planning after rejecting the alternative. A pinned
board's size does NOT drive its region upward. The unit's overall size is the
user's input and everything below it is derived, so a size that drove upward
would fight that and would need a solve that pushes both directions, which is a
different algorithm from the one every existing test is written against.
Instead: the solver derives the board's extent as it does for any board, then
CHECKS it against `pinned_size_mm` and raises. This is honest. Resizing a unit
in the direction a notched panel spans fails, because you cannot stretch a
notched panel.

`pinned_size_mm` is ONE field, not a boolean plus a size. A boolean would be
redundant with the size being present, and the two could disagree. `None` is
the regenerable case and is the default, so every existing construction site is
unchanged.

Do NOT name it `fixed_size_mm`: `Fixed` is already a size rule and the
collision would make both harder to read.

THE RULE KEY IS THE HARD PART. A region's id is a fresh uuid on every scan, so
a record keyed by region id matches nothing after a rescan and the whole
mechanism is dead. Key instead by the boards that bound the region along its
division's axis: the item before it and the item after it in the run. Use the
board's `id`, which sh-018 sets to the FreeCAD object name, so the key is
stable for as long as those boards are. A region at either end of a run has no
neighbour on that side; use an explicit sentinel string, not an empty string,
so a key is unambiguous when read back. Serialise a key as a single string with
a separator that cannot occur in a FreeCAD object name.

CONSEQUENCES OF THAT KEY, state them in the module docstring because they are
not obvious. A renamed or deleted bounding board invalidates its neighbours'
keys, and the correct response is to fall back to the scanned rule rather than
to raise: the geometry is still right, only the intent is lost, and the
equal-siblings heuristic is the documented fallback. Two regions in different
divisions cannot collide, because a board bounds at most one region on each
side within one run.

WHAT IS NOT IN THE RECORD. Only the per-region rules. The unit id, the depth
axis, and the facing are single values that sh-018 stores as three ordinary
container properties, legible and bindable in the property editor. A board's
material, its provenance, and its pinned size live on the board's own object.
The record exists solely because a bay is not a board and so has nowhere else
to put its rule.

MEASUREMENT BASIS RIDES ALONG. A `Fixed` rule carries its `Basis`, so
serialise and restore it. A stored `Basis.WITH_NEXT` is the only way that
intent survives a rescan at all, since a clear opening and a shelf spacing
place the boards identically and scanning always recovers `Basis.CLEAR`.

MATERIAL PRECEDENCE IS LOAD-BEARING, and the reason is not local to this task.
M8 lets a user change a catalog entry's thickness. If scanning always matched by
thickness, changing `ply18` from 18 mm to 25 mm would leave every existing 18 mm
board matching nothing, the scan would refuse, and there would be no path from
the old geometry to the new. A stored material breaks that: the board says
`ply18`, the catalog says `ply18` is 25 mm now, and the solve produces 25 mm
boards. So a `Box` with a material set MUST bypass thickness matching entirely.
Thickness matching survives only for untagged geometry this workbench never
wrote.

SCAN CHANGES ARE SMALL. `Box` gains `pinned: bool = False` and
`material: MaterialId | None = None`. In `scan`, a box
with `pinned` set is placed as a `Board` carrying `pinned_size_mm` from its
measured extent, and is NOT added to `skipped`. Everything else about the
classification is unchanged: a pinned box still has to be axis-aligned and
still has to fit the partition, and it refuses the same way if it does not.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no
bare containers in signatures or public attributes, `Mapping` rather than
`dict` in parameters, `mypy --strict` clean. Shell stays simple does not apply;
this task adds no shell.

Every length identifier carries `_mm`.

## Execution Plan

- [x] **Step 1** (`freecad/Shelving/core/layout.py`, `freecad/Shelving/core/tests/test_layout.py`): Add `pinned_size_mm: Vec3 | None = None` to `Board`, positioned before `id`. Document on the field that `None` means the board is regenerable, that a value means the workbench cannot reproduce this part and carries the shape it is pinned at, and that the solver verifies rather than derives it. Add construction tests for both the default and a set value. Change nothing else.

- [ ] **Step 2** (`freecad/Shelving/core/solver.py`, `freecad/Shelving/core/tests/test_solver.py`): Add `"pinned_mismatch"` to `SolveErrorReason`. In `solve`, after computing a board's `Space`, when that board carries `pinned_size_mm`, compare the derived extent against it on all three axes and raise `LayoutSolveError(board.id, "pinned_mismatch", detail)` when any differs by more than `EPS_MM`; `detail` carries the derived and the pinned extent. Tests: a unit whose layout matches its pinned board solves; the same unit widened raises with the board named; a pinned board agreeing within `EPS_MM` does not raise.

- [ ] **Step 3** (`freecad/Shelving/core/scan.py`, `freecad/Shelving/core/tests/test_scan.py`): Add `pinned: bool = False` and `material: MaterialId | None = None` to `Box`. In `scan`, place a box with `pinned` set as a `Board` whose `pinned_size_mm` is its measured extent, and do not add it to `skipped`. Route material resolution through the stored value when present: use it directly, raise `ScanError` naming the board when it is absent from the catalog, and fall back to thickness matching only for a box with no material. The unit's `default_material` becomes the most common resolved material rather than the most common thickness. Tests: a pinned box scans with `pinned_size_mm` set and an otherwise identical tree; a box whose stored material names an entry whose thickness differs from its measured extent resolves to that entry rather than refusing; a box with no material still matches by thickness; a stored material absent from the catalog refuses naming the board.

- [ ] **Step 4** (`freecad/Shelving/core/record.py`): Create the module. `RULE_RECORD_VERSION: int`. A module-level sentinel constant for "no neighbour on this side" and a separator constant that cannot occur in a FreeCAD object name. `rule_key(before: str | None, after: str | None) -> str` building the key from the two bounding board ids. A private walk yielding `(key, rule)` for every region in a unit, pairing each region with the items either side of it in its division's run; the root region has no division and therefore no key, so skip it. `rules_to_json(unit) -> str` emitting `{"schema_version": ..., "rules": {key: rule_doc}}` with a rule doc per `SizeRule` variant, carrying `basis` for a `Fixed`. `rules_from_json(text) -> Mapping[str, SizeRule]` narrowing every value with isinstance checks before construction and raising `ValueError` on a version mismatch or a malformed rule. `with_stored_rules(unit, rules) -> Unit` rebuilding the tree with a matching region's rule replaced and an unmatched region left alone. Document the key's stability consequences per Frontier Advice.

- [ ] **Step 5** (`freecad/Shelving/core/tests/test_record.py`): Create the suite. `rule_key` builds distinct keys for distinct neighbour pairs and the same key for the same pair. `rules_to_json` emits one entry per non-root region, with a `Fixed`'s basis preserved for both `Basis` members. `rules_from_json` round-trips each rule variant and raises on a wrong version, a missing key, a malformed rule type, and a non-numeric size. `with_stored_rules` replaces a matching rule, leaves an unmatched region's rule as it was, and returns a unit whose tree is otherwise identical.

- [ ] **Step 6** (`freecad/Shelving/core/tests/test_record.py`): Add the intent-survival suite, which is the point of the module. For at least three units, one with all-equal bays, one with a deliberately `Fixed` bay that happens to equal its siblings, and one using `Basis.WITH_NEXT`: serialise the rules, `expand` the unit, convert to `Box` records, `scan` them back, confirm the scanned rules differ from the originals where the heuristic cannot tell, then apply the stored rules with `with_stored_rules` and confirm every rule matches the original. Add the renamed-board case: alter one board's id before rescanning and assert the affected region keeps its scanned rule rather than raising, while every other region is restored.
