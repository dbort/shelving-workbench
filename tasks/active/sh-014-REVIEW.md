# sh-014 Review — Round 2

**Verdict:** REJECTED

Round 1's F2 is closed: `test_thicknesses_mm_reports_every_distinct_board_thickness`,
`test_explicit_front_at_min_is_never_second_guessed` (parametrized both ways,
against the magicStart fixture whose inferred facing disagrees), and
`test_explicit_depth_axis_changes_which_axis_the_tree_divides_along` all land,
and N2 is folded in (`test_real_two_units_whole_tree` now scans with
`skipped=skipped` and asserts `result.skipped`). `pixi run tests` is green on
`sh-014` (157 passed, mypy strict over 32 files, ruff, `vendor-core --check`,
workflow lint, FreeCAD smoke), `python -m pytest spikes` is green (37 passed)
with `spikes/` byte-untouched by the diff, the four fixtures are byte-identical
to their `spikes/plain_planks/` originals, and the vendored
`freecad/shelving/vendor/shelving_core/scan.py` matches the core copy. Every
`## Must Have` is met. One thing blocks approval.

## Blocking findings

- **F1: round 1's `_mm` sweep is incomplete** (`shelving_core/scan.py:196`,
  `shelving_core/tests/test_scan.py:59`): commit dedc94c's message says it
  suffixed "every millimetre identifier in scan.py and test_scan.py", but the
  same class of violation round 1 rejected on is still present, including two
  function parameters, the category `CLAUDE.md` § Project conventions names
  first. The remaining millimetre-valued identifiers, exhaustively, so this
  finding can be closed in one pass:
  - `shelving_core/tests/test_scan.py:59-61` — `_box_json`'s `corner` and
    `size` parameters, which the body writes straight into `"corner_mm"` and
    `"size_mm"`.
  - `shelving_core/tests/test_scan.py:138-140` — `_box`'s `corner` and `size`
    parameters, which the body passes straight to `Box(corner_mm=...,
    size_mm=...)`. This helper is called 42 times in the file, so the
    unsuffixed names are the ones a reader of the tests actually sees.
  - `shelving_core/scan.py:196,203-204` — `sizes` (the box's three extents)
    and `smallest` (their minimum).
  - `shelving_core/scan.py:224-225` — `spans` inside `bounding_span_mm`, and
    the `hi` / `lo` generator targets over it.
  - `shelving_core/scan.py:276-277,291-292` — the `lo` / `hi` generator
    targets over `member_spans_mm`.
  - `shelving_core/scan.py:388-389` — the `v` comprehension target over
    `(p.h0_mm, p.h1_mm)` / `(p.v0_mm, p.v1_mm)`.

  Out of scope deliberately, so the list above is the whole job: locals bound
  to grid indices or counts (`i0`/`i1`/`j0`/`j1`, `spans` at `:673`, `bounds`,
  `nh`/`nv`, `along`/`across`, `a`/`b` in `_gap`) carry no physical unit and
  take no suffix. `extent_by_axis` at `:807` is a judgment call: its values are
  millimetres but its name reads as a mapping, so either leaving it or
  `extent_mm_by_axis` closes it.

  Renaming the listed identifiers in `shelving_core/scan.py` and
  `shelving_core/tests/test_scan.py`, then re-running `tools/vendor-core.sh` so
  `freecad/shelving/vendor/shelving_core/scan.py` stays in sync, closes F1.
  `spikes/plain_planks/` must stay untouched.

## Non-blocking notes

- **N1: the `round(..., 4)` in `thicknesses_mm` is still unpinned**
  (`shelving_core/scan.py:912`): the new
  `test_thicknesses_mm_reports_every_distinct_board_thickness` builds its boxes
  from `expand`, so the thicknesses are exactly 18.0 and 12.0 and the rounding
  never fires. What the round is for is real geometry, where two boards of the
  same stock measure 17.999999 and 18.000001 and would otherwise report as two
  distinct thicknesses. One assertion over a fixture-derived or
  deliberately-jittered pair of boxes would pin the behavior the constant
  exists for.
- **N2: the notched-panel test asserts the fixture, not any product code**
  (`shelving_core/tests/test_scan.py:752-776`): it reads `pad["name"]`,
  `pad["label"]`, `pad["type"]` out of the inspection JSON with a test-local
  `_find_pad`, hand-builds a `Skipped` from them, and compares against literals
  it also supplies, so no `shelving_core` code path runs. The Must Have's real
  proof is `test_real_two_units_whole_tree`, where `Pad003` reaches
  `result.skipped` through `export_from_json` and `scan`. Worth a line in the
  docstring saying so, so a future reader does not mistake this for coverage of
  a reader that does not exist.
