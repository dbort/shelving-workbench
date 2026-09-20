# sh-016 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green on the branch tip (ruff, `mypy --strict` over 39
files, 174 pytest cases, the workflow lints, the vendored-core drift check,
and both `freecadcmd` smokes including `shelving scan OK`). The rejection is
about a correctness hole in the frame composition, two behaviors a Must Have
names that no committed test exercises, and one Must Have that is checked off
but not true.

## Blocking findings

- **F1: a nested container's rotation is applied to the corner point but not
  to the extents** (`freecad/shelving/container.py:129-141`): `read_container`
  transforms only the minimum corner,
  `placement.multVec(FreeCAD.Vector(bound.XMin, bound.YMin, bound.ZMin))`,
  and then takes `size_mm` straight from `bound.XLength/YLength/ZLength`,
  which are extents in the *nested* container's frame. `_walk`
  (`freecad/shelving/container.py:77-104`) composes
  `placement.multiply(own)` for every container it descends through, so a
  nested `App::Part` or `App::LinkGroup` carrying a quarter-turn about Z
  reaches this line with a rotation in it. Under that rotation the X and Y
  extents must swap and the transformed minimum corner is not the transform
  of the untransformed minimum corner: a 100 x 50 x 20 mm box at the nested
  origin, under a +90 degree Z rotation, spans x in [-50, 0] and y in
  [0, 100], while the current code reports corner (0, 0, 0) and size
  (100, 50, 20). Translation-only nested placements are handled correctly,
  which is why nothing currently fails.

  The same ordering issue makes the refusal path miss: `_skip_reason`
  (`freecad/shelving/container.py:193-231`) inspects the leaf's own
  `Shape` in the nested frame, so a nested container rotated by something
  that is *not* a multiple of 90 degrees yields a leaf that looks
  axis-aligned and is silently adopted as a `Box` whose corner and size do
  not describe the solid, rather than landing in `Skipped`. The spike this
  ported from refused any composed rotation outright
  (`spikes/plain_planks/export_boxes.py` on `main`, the
  `_ROTATION_TOL_DEG` check); the ported walk dropped that guard without
  replacing it. Either transform the bounding box properly (e.g. bbox of
  the placement applied to the shape/its eight corners) or refuse a
  composed rotation that is not an exact multiple of 90 degrees, and pick
  deliberately between those.

  This is also the untested half of the Must Have "the container's own
  placement is excluded, nested container placements are composed": the
  smoke only moves and rotates the *selected* container
  (`tools/freecad_scan_smoke.py:234-247`), where the assertion is that
  nothing changes. No case in the branch puts a non-identity placement on a
  *nested* container, so the composition side of that Must Have has zero
  coverage. The fix needs a committed case in
  `tools/freecad_scan_smoke.py` with a nested rotated container asserting
  the leaf's corner and size in the selected container's frame.

- **F2: no test refuses a skewed box** (`freecad/shelving/container.py:150-158`,
  `tools/freecad_scan_smoke.py:266-288`): the Must Have reads "A box rotated
  by a multiple of 90 degrees reads correctly; a skewed one is refused by
  name." The smoke covers the first clause (the `Rotated` box) and nothing
  covers the second. `_axis_aligned`'s `False` branch, and with it the
  "not axis-aligned" skip reason, is never reached by any test on the
  branch: the notched body is axis-aligned, so it exits through the
  box-minus-cutouts path instead. A box rotated, say, 30 degrees about Z,
  added to the smoke's container with an assertion that it produces one
  `Skipped` naming that object and reason, closes it.

- **F3: `docs/roadmap.md` still points at deleted spike files**
  (`docs/roadmap.md:146`, `docs/roadmap.md:171`): the Must Have
  "`spikes/` does not exist and nothing references it" is checked off, but
  the M4 section still reads "`spikes/plain_planks/general_model.py` is the
  worked design; copy from it rather than moving it, so the spike keeps
  running as the fallback for the two milestones during which the workbench
  has no commands", and M5 "`spikes/plain_planks/scan.py` and its fixtures
  are the worked design; copy from them, again leaving the spike intact."
  Both are present-tense instructions naming paths this branch deletes.
  `docs/parametric-model-evaluation.md` got exactly this treatment
  (state what the spike proved, not where it lived) and `docs/roadmap.md`
  was missed. The M6 hits at `docs/roadmap.md:207` and `:216` are fine:
  they describe the deletion. The remaining grep hits are frozen records
  (`tasks/completed/*`, `.claude/docs/friction-log.md`) or explicitly
  conditional (`tasks/active/sh-027-...` guards every mention with "if
  still present"), and need no edit.

## Non-blocking notes

- **N1: the export command's JSON shape has no test**
  (`freecad/shelving/commands/export_boxes.py:99-123`): the dict is built
  inline inside `Activated`, so nothing checks that what it writes parses
  back through `shelving_core.scan.export_from_json`. The keys match
  `_parse` today by inspection, but this file is the mechanism for
  capturing a unit that scanning refuses, and a silent format drift would
  only show up in a bug report nobody can read. Pulling the dict build into
  a module-level helper over `list[Box]`/`list[Skipped]` makes it pure
  enough to round-trip in the fast suite with no FreeCAD import.
- **N2: the move-and-rotate assertion passes vacuously if the mutation does
  not take** (`tools/freecad_scan_smoke.py:234-247`): the case asserts
  `before == after` after writing `part.Placement`, which also holds if the
  write had no effect. Asserting the placement actually landed (or that a
  child's global placement moved) before comparing the records makes it a
  real test of the exclusion rule.
- **N3: `_CONTAINERS` is defined three times**
  (`freecad/shelving/container.py:34`, `freecad/shelving/commands/scan.py:22`,
  `freecad/shelving/commands/export_boxes.py:23`), as are
  `_selected_container`, `_CommandResources`, and `_ICON` across the two
  command modules. The descendable-container set and the selection envelope
  are the same rule; three copies can drift independently.
- **N4: `FacingEvidence.NONE` has no entry in `_FACING_WHY`**
  (`shelving_core/report.py:15-22`, used at `shelving_core/report.py:54`):
  unreachable through `scan`, which only ever pairs `NONE` with
  `front_at_min is None`, but `report` is a public function over an
  arbitrary `ScanResult` and would raise `KeyError` on that combination. A
  `.get` with a neutral fallback removes the sharp edge.
- **N5: `_piece_size_mm` returns a `str`**
  (`freecad/shelving/container.py:179-181`): `CLAUDE.md` § Project
  conventions gives the `_mm` suffix to the numeric quantity, and says an
  identifier whose value is a label rather than the number takes no suffix.
- **N6: `--` used as an em-dash aside** (`docs/manual-qa.md:74`): "inside
  the same `App::Part` -- for example a `PartDesign::Body`...". The writing
  rules call for a comma, colon, or separate sentence.
