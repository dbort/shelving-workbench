# sh-014 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green on `sh-014` (153 passed, mypy strict over 32 files,
ruff, vendor-core --check, workflow lint, FreeCAD smoke), the spike suite
still passes untouched (37 passed under `spikes/plain_planks`), the four
fixtures are byte-identical to their `spikes/plain_planks/` originals, and the
tree/refusal/round-trip Must Haves are met. Two things block approval.

## Blocking findings

- **F1: length identifiers without the `_mm` suffix**
  (`shelving_core/scan.py:534`, `shelving_core/tests/test_scan.py:189`):
  `CLAUDE.md` § Project conventions makes the unit suffix mandatory on every
  identifier bound to a physical quantity, including function parameters and
  locals, and the task restates it ("Every length identifier carries `_mm`").
  The ported code carries the spike's unsuffixed names through:
  - `shelving_core/scan.py:534-551` — `low` / `high` are millimetre gap
    widths; they are compared against `ctx.clearance_mm` at line 545 and
    passed to `_make_board`'s `low_mm` / `high_mm` at line 551.
  - `shelving_core/scan.py:388-389` — `self.hs` / `self.vs` are millimetre
    grid-line coordinates, and the same values flow through `coords`
    (`:473`, `:479`, `:495`, `:657`) and `_gap`'s `lines` parameter (`:592`).
  - `shelving_core/scan.py:701-719` — `_snap_lines`'s `values`, `lines`,
    `cluster`, and `value`; `shelving_core/scan.py:722` — `_index_of`'s
    `value`; `shelving_core/scan.py:316-323` — `_median`'s `sorted_values`
    (millimetre thicknesses at the only call site, `:283`).
  - `shelving_core/tests/test_scan.py:189` — `_closed_box(..., t: float =
    18.0, d: float = 300.0)`, and the same names as locals at `:234`
    (`t, d = 18.0, 300.0`) and `:273` (`d = 300.0`). Existing tests set the
    bar here: `shelving_core/tests/test_expand.py:45` uses
    `width_mm`/`depth_mm`/`height_mm`.
  Copying from the spike is what the task asked for, but the spike predates
  nothing: the convention applies to the new module. Rename in `scan.py` and
  `test_scan.py`; the spike itself must stay untouched.

- **F2: public scan surface with no test at all**
  (`shelving_core/scan.py:800`, `:823-829`): three affordances the Frontier
  Advice names explicitly have zero coverage, and nothing in `test_scan.py`
  mentions them (`grep` for `thicknesses_mm`, `GIVEN`, `depth_axis=`,
  `front_at_min=` in the test file returns nothing):
  - `ScanResult.thicknesses_mm` (`:800`, populated at `:888` with a
    `round(..., 4)` that is itself an untested decision) is never asserted by
    any test.
  - `scan(..., front_at_min=...)` — the `else` branch at `:828-829` is the
    only producer of `FacingEvidence.GIVEN`, which the Must Have lists as a
    required export. The spike had `test_an_explicit_facing_is_never_
    second_guessed` for exactly this; the port dropped it.
  - `scan(..., depth_axis=...)` — the override at `:823-824` that
    `detect_depth_axis`'s own docstring points callers at for the
    deeper-than-wide case ("`scan` takes an explicit `depth_axis` for that
    case") is never exercised.
  Add unit tests: one asserting `thicknesses_mm` for a unit with two stock
  thicknesses, one asserting an explicit `front_at_min` is returned verbatim
  with `FacingEvidence.GIVEN` and is not second-guessed against the geometry
  (a fixture whose inferred facing is the opposite makes the point), and one
  asserting an explicit `depth_axis` that differs from the detected one
  changes which axis the tree divides along.

## Non-blocking notes

- **N1: two refusal tests drive private helpers, not `scan`**
  (`shelving_core/tests/test_scan.py:212`, `:248`): the bay-boundary and
  partly-enclosed cases call `_contained` / `_empty` with hand-built
  `_Elevated` records and hand-picked grid indices. The docstrings argue the
  recursion never constructs such a window, which reads correct — every cut
  line is a face of every board inside the parent, so a sub-window cannot
  straddle one. That makes these guards unreachable from `scan` and the tests
  pins on internals rather than behavior. Worth one line in each docstring
  saying the guard is defensive (kept because the spike raised it), or a
  public-entry-point input if one exists.
- **N2: `skipped` is asserted on the parse, not the scan**
  (`shelving_core/tests/test_scan.py:611-618`): `test_real_two_units_whole_
  tree` reads `skipped` from `export_from_json` but scans without
  `skipped=skipped`, so `result.skipped` is empty and the Must Have's "the
  notched panel appearing in `skipped`" is only proven of the parser. Passing
  it through and asserting on `result.skipped` ties the two halves together.
