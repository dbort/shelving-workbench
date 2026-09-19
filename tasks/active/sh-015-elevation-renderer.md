---
id: sh-015
title: "The elevation renderer, rebuilt on the region model"
current_agent: user
current_phase: user_signoff
review_rejections: 1
blocked_by: [sh-014]
---

# sh-015: The elevation renderer, rebuilt on the region model

## Summary
Rebuild the SVG elevation renderer that M4 removed, drawing a `Unit` projected
along its depth axis. Adds what the region model gained and the carcass never
had: a `Void` drawn distinctly from a `Bay`, so a stepped outline reads at a
glance, and a board drawn at its inset extent, so a shelf held off its sides
looks held off. Its test renders a scanned real fixture, which is why it follows
scanning rather than the model. Milestone M5, part 2 of 2.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [ ] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `shelving_core/svg.py` exports `to_svg` and `rule_label`. `to_svg` takes a
      `Unit`, its solved `Space` map, and a `Catalog`, and returns a complete
      SVG document string.
- [x] A `Void` renders visibly distinct from a `Bay`, asserted by a test that
      renders a stepped unit and a closed unit of the same outer size and shows
      the documents differ in a way attributable to the void.
- [x] A board with non-zero `Insets` renders at its inset extent, asserted
      against the plain-board case.
- [x] Two boards face to face render as two rectangles sharing an edge, not one.
- [x] `to_svg` projects along the unit's `depth_axis`, accepts an explicit axis
      override, and raises `ValueError` naming the unit when neither is set.
- [x] A test renders a scanned real fixture end to end: read the fixture, scan
      it, solve it, render it, and parse the result as XML with the expected
      root tag.
- [x] `pixi run demo -- --svg PATH` writes a parseable SVG again, and
      `tests/test_layout_demo.py` asserts it.
- [x] Output is deterministic: rendering the same unit twice returns identical
      strings, asserted by a test.
- [x] `mypy --strict` clean; `shelving_core` imports no FreeCAD.

## Frontier Advice

REFERENCE, not a template: the renderer M4 deleted is at
`git show <merge-base>:shelving_core/svg.py`, and its tests at
`shelving_core/tests/test_svg.py` in the same commit. Its drawing primitives,
its SVG assembly, its title band, its legend and its scale handling are all
reusable verbatim. Its tree walk is not: it walked a carcass. Read it for the
primitives, write the walk fresh.

WHAT IS DIFFERENT FROM THE OLD RENDERER, and the reason this task exists:
- A `Void` is space inside the bounding box that is NOT part of the unit. Draw
  it distinctly from a `Bay`, hatched or in a muted fill, and label it as not
  part of the unit. A stepped outline is nothing but voids, so a renderer that
  draws them like bays makes a stepped unit and a closed one look identical.
- A `Board` carries `Insets`. Draw it at its inset extent inside its solved
  `Space`, so a shelf held a millimetre off each side is visibly held off.
- Two boards can sit face to face in one division. They must render as two
  rectangles sharing an edge, with both labels legible, not as one merged block.
- A division names an `Axis`, not a two-valued orientation. The renderer
  projects along the unit's depth axis and draws the other two.

SIGNATURE: `to_svg(unit: Unit, spaces: Mapping[str, Space], catalog: Catalog,
*, axis: Axis | None = None, scale: float = 1.0, margin_mm: float = 20.0,
font_size_mm: float = 12.0) -> str`. Take the solved spaces rather than solving
internally, matching the old renderer, so a caller that has already solved does
not solve twice and a test can render a deliberately odd layout. A node id
absent from `spaces` is a programmer error: raise `KeyError`. A material id
absent from `catalog` raises `KeyError`. The projection axis is `axis` when
given, else `unit.depth_axis`; when both are `None` raise `ValueError` naming
the unit id, because a unit that has never been scanned has no depth axis and
guessing one would draw a wrong picture silently.

DETERMINISM IS A REQUIREMENT, not a nicety. Iterate regions and boards in tree
order and assign legend colours in first-appearance order of material id. Never
iterate a `set` or an unordered `dict` when the result reaches the output.

`rule_label` keeps its job of turning a `SizeRule` into a short display string,
extended for `Basis`: a `Fixed` with `Basis.WITH_NEXT` must read differently
from one with `Basis.CLEAR`, because the two mean different things and a picture
that shows them the same defeats the point of drawing dimensions at all.

DO NOT solve, scan, or read files inside `svg.py`. It is a pure function from a
model plus a solve to a string. The fixture test wires
`export_from_json` to `scan` to `solve` to `to_svg` in the test, not in the
module.

DO NOT touch `spikes/plain_planks/`. M6 deletes it.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no
bare containers in signatures or public attributes, `Mapping` and `Sequence`
rather than `dict` and `list` in parameters, `mypy --strict` clean. Shell stays
simple does not apply; this task adds no shell.

Every length identifier carries `_mm`. The SVG `viewBox` stays in millimetres
and `scale` multiplies only the root `width` and `height`, as the old renderer
did.

## Execution Plan

- [x] **Step 1** (`shelving_core/svg.py`): Create the module with the non-walking half, copied from the deleted renderer and retargeted. Bring across the number formatter, the XML escaper, the style block, the title band, the legend block, the material colour palette, and the document assembly. Define `rule_label(rule: SizeRule) -> str` over the `Fixed | Weighted | Fill` union, rendering a `Fixed` with `Basis.WITH_NEXT` distinctly from one with `Basis.CLEAR`. Add the two coordinate helpers that map a millimetre position on the projected axes to SVG user units, taking the projection axis pair rather than assuming X and Z. Export nothing else yet; this step must be green with no `to_svg`.

- [x] **Step 2** (`shelving_core/svg.py`): Add the walk and `to_svg`. Resolve the projection axis per Frontier Advice, raising `ValueError` naming the unit when it is unresolvable. Walk the tree in order, emitting for each `Bay` an open rectangle with its solved size labelled, for each `Void` a distinct hatched or muted rectangle labelled as outside the unit, and for each `Board` a filled rectangle at its inset extent coloured by resolved material, labelled with its role when it has one. Emit a rule label per region using `rule_label`. Assign legend colours in first-appearance order of material id.

- [x] **Step 3** (`shelving_core/tests/test_svg.py`): Create the suite over hand-built units. Assert: the document parses as XML with the SVG root tag; the `viewBox` matches the unit's projected extent plus margins; `scale` changes the root `width` and `height` and leaves the `viewBox` alone; a material absent from the catalog raises `KeyError`; a node id absent from `spaces` raises `KeyError`; a unit with no `depth_axis` and no `axis` argument raises `ValueError` naming the unit; rendering the same unit twice returns identical strings; a `Fixed` with each `Basis` produces different rule labels.

- [x] **Step 4** (`shelving_core/tests/test_svg.py`): Add the three region-model tests. A stepped unit and a closed unit of the same outer size render to different documents, with the difference attributable to the void's distinct fill or hatch rather than to size. A board with non-zero `Insets` renders a smaller rectangle than the same board with zero insets, on both projected axes. Two boards face to face in one division produce two rectangles sharing an edge, asserted by finding both rects and checking their adjacency, with both labels present.

- [x] **Step 5** (`shelving_core/tests/test_svg.py`): Add the end-to-end fixture test. Read `shelving_core/tests/fixtures/real_stair_step.boxes.json` with `export_from_json`, `scan` it against a catalog built from its own thicknesses, `solve` the resulting unit, render it, and assert the document parses and contains at least one void rectangle, because a stepped unit must show its steps. Repeat for `real_magicstart_f1`, asserting its plinth void renders.

- [x] **Step 6** (`tools/layout_demo.py`, `tests/test_layout_demo.py`, `README.md`): Restore the `--svg PATH` option: the script keeps printing its text dump unconditionally and writes the SVG plus a confirmation line only when the flag is given. Parse arguments with `argparse`. Restore `test_demo_svg_flag_writes_a_parseable_svg` in `tests/test_layout_demo.py`, driving the script as a subprocess, parsing the written file as XML, and asserting the text dump still prints. In `README.md`, restore the sentence describing `pixi run demo -- --svg layout.svg` to the paragraph it was removed from.

- [x] **Step 7** (`README.md`): Extend the Glossary with `to_svg` and `rule_label` in the section's existing one-bullet-per-term shape, and state under the elevation entry that the renderer projects along the unit's depth axis and draws a void distinctly from a bay.
