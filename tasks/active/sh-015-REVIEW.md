# sh-015 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green on the branch tip (172 passed, ruff/mypy/vendor-sync
clean, FreeCAD smoke OK), and most Must Haves are met. Two things block
approval.

## Blocking findings

- **F1: the `axis` override is never exercised by a test**
  (`shelving_core/svg.py:403-405`, `shelving_core/tests/test_svg.py`): the
  Must Have reads "`to_svg` projects along the unit's `depth_axis`, accepts an
  explicit axis override, and raises `ValueError` naming the unit when neither
  is set". The first and third clauses have tests; the second does not. No
  test in the suite passes `axis=` to `to_svg` (`grep -n "axis" test_svg.py`
  shows only `depth_axis=` on constructed units and division `axis=`), so
  neither "`axis` wins over `depth_axis`" nor "`axis` rescues a unit whose
  `depth_axis` is `None`" is covered.

  The consequence reaches past the argument itself: every hand-built unit in
  the suite uses `depth_axis=Axis.Y`, so `_elevation_axes`
  (`shelving_core/svg.py:116-129`) is only ever called with `Axis.Y`. Its
  `Axis.Z` branch — the one where the vertical axis becomes `Axis.Y` instead
  of `Axis.Z` — and the corresponding `v_index == 1` path through
  `_Frame.rect` (`shelving_core/svg.py:329-344`) are unexecuted by the whole
  suite. A sign or index error in the non-`Z`-vertical projection would ship
  silently. Add tests that (a) render a `depth_axis=None` unit with an
  explicit `axis=` and get a document, (b) render one unit twice with
  `axis=Axis.Y` and `axis=Axis.Z` and assert the `viewBox` width/height follow
  the projected extents of the correct axis pair, and (c) assert `axis=`
  overrides a conflicting `depth_axis`.

- **F2: millimetre quantities without the `_mm` suffix**
  (`shelving_core/svg.py:152-153`, `173-174`, `183-186`, `248`, `443-444`,
  `457`, `461`, `475`, `496`): `CLAUDE.md` § Project conventions requires the
  unit suffix on every identifier bound to a quantity with a physical unit,
  including locals and parameters, and this task's `## Frontier Advice`
  restates it ("Every length identifier carries `_mm`"). One SVG user unit is
  one millimetre here (module docstring, line 12) and the `viewBox` is in
  millimetres, so `x`, `y`, `cx`, `cy`, `first_y`, `line_height`, `row_y`,
  `view_w`, and `view_h` are all millimetre lengths and all lack the suffix.
  The same lines make the inconsistency plain: `_rect_line(css_class, x, y,
  width_mm, height_mm)` at `shelving_core/svg.py:150-156` and the unpacking
  `x, y, width_mm, height_mm = frame.rect(...)` at `457`/`461`/`475`/`496`
  carry the suffix on half of one 4-tuple of identical quantities. `top_mm`
  and `left_mm` at `240-241` already do it right.

  That the deleted pre-M4 renderer named them this way is not a licence: the
  Frontier Advice blesses reusing its primitives, not its naming, and this is
  a new file. A tidy fix is to give `_Frame.rect`
  (`shelving_core/svg.py:329`) a small frozen `NamedTuple`/dataclass return
  with `x_mm`/`y_mm`/`width_mm`/`height_mm` fields instead of a bare
  `tuple[float, float, float, float]`, which renames the call sites by
  construction.

## Non-blocking notes

- **N1: the determinism test cannot fail**
  (`shelving_core/tests/test_svg.py:196-199`): `to_svg(u, s, c) == to_svg(u,
  s, c)` on the same objects in one process is true for any pure function; it
  would not catch the failure mode the Frontier Advice names (a `set` or
  unordered `dict` reaching the output), because a `set` of the same elements
  iterates the same way twice in one process. Build the unit and solve it
  twice from scratch (fresh `uuid4` node ids, fresh `Catalog` dict insertion)
  and compare the two documents; that version fails if legend colour
  assignment ever starts depending on `seen_materials`
  (`shelving_core/svg.py:430-434`) rather than `material_order`.

- **N2: the inset test asserts "smaller", not "the inset extent"**
  (`shelving_core/tests/test_svg.py:225-236`): the Must Have says the board
  renders *at its inset extent*. Asserting the exact expected width and height
  (plain minus `x_min_mm + x_max_mm`, minus `z_min_mm + z_max_mm`) and the
  shifted `x`/`y` costs one more line and pins the geometry rather than its
  direction.

- **N3: `_apply_insets` and `_elevation_axes` are now duplicated verbatim**
  (`shelving_core/svg.py:262-308` vs `shelving_core/expand.py:80-122`;
  `shelving_core/svg.py:116-129` vs `shelving_core/scan.py:326-334`): unlike
  `_axis_index`, which is a four-line helper already duplicated on `main`,
  `_apply_insets` is fifty lines of geometry that must agree with `expand`'s
  copy or the picture shows a different board than the cut list. The docstring
  at `shelving_core/svg.py:269-275` argues for the copy; if it stays, a test
  asserting the svg board rect matches `expand`'s `BoardSpec` size and
  placement for one inset unit would catch the drift the duplication invites.

- **N4: a `Division`'s own `rule` never reaches the drawing**
  (`shelving_core/svg.py:347-374`): Step 2 says "emit a rule label per
  region", and a `Division` is a `Region`. Only `Bay` and `Void` rules are
  labelled. Defensible (a division has no rect of its own) and not a Must
  Have, but a scanned unit's division rules are then invisible in the output.
