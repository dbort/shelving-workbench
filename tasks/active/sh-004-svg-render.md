---
id: sh-004
title: "SVG rendering of a solved layout"
current_agent: implementer
current_phase: implementation
review_rejections: 0
blocked_by: [sh-003]
---

# sh-004: SVG rendering of a solved layout

## Summary
Add a pure-Python SVG renderer for a solved `Carcass` layout so the demo (and
later the editor and docs) can show the nested rectangles instead of a wall of
`rect=(x,z,w,h)` text. `shelving_core/svg.py` turns a `Carcass` plus its
`SolvedLayout` into an SVG string; `tools/layout_demo.py` gains a `--svg PATH`
flag that writes one.

## Status
- [x] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have

### Renderer (`shelving_core/svg.py`)
- [ ] `to_svg(carcass: Carcass, layout: SolvedLayout, *, scale: float = 1.0, margin_mm: float = 20.0, font_size_mm: float = 12.0) -> str` is a pure function (stdlib only) returning a complete SVG document string. It reads the tree from `carcass` (for structure, ids, and the rule that positioned each child) and the placed rectangles from `layout`. It never calls `solve` and never touches the filesystem.
- [ ] Output is a single `<svg xmlns="http://www.w3.org/2000/svg" ...>` element with a `viewBox="0 0 W H"` in millimetre units (`W = carcass.width_mm + 2*margin_mm`, `H = carcass.height_mm + 2*margin_mm + title band`) and `width`/`height` attributes equal to the viewBox extents times `scale`. One SVG user unit is one millimetre.
- [ ] Y is flipped from solver space (origin front-bottom-left, +z up) to SVG space (+y down) by a helper: a rect at solver `(x_mm, z_mm, w_mm, h_mm)` draws at SVG `x = margin_mm + x_mm`, `y = margin_mm + (carcass.height_mm - z_mm - h_mm)` (plus the title band offset). All rects and text use this mapping; no mirrored text.
- [ ] Draws, in this order: the carcass outline rect (class `carcass`); one filled rect per `Divider` id (class `divider`); one stroked rect per `Leaf` id (class `leaf`). It does NOT draw a rect for `Split` nodes (their area is the union of their children). Element order within each kind follows a deterministic pre-order tree walk, not `dict` iteration order.
- [ ] Each `Leaf` gets a centered `<text class="label">` with three `<tspan>` lines: `{width_mm:g} x {height_mm:g} mm`, the leaf's short id (`id[:8]`), and the `SplitRule` that positioned it rendered by a `_rule_label(rule) -> str` helper (`Fixed 400 mm` / `Weighted 2` / `Fill`). The root `Leaf` of a carcass with no split has no rule line.
- [ ] A title `<text class="title">` above the drawing reads `Carcass {width_mm:g} x {height_mm:g} x {depth_mm:g} mm, default thickness {default_thickness_mm:g} mm`.
- [ ] A `<style>` block defines the `carcass` / `divider` / `leaf` / `label` / `title` classes (carcass: no fill, dark stroke; divider: solid mid-grey fill; leaf: faint fill, thin stroke; label/title: readable sans-serif at `font_size_mm`). No inline presentation attributes beyond geometry.
- [ ] All text content (rule labels, the title) is XML-escaped for `& < > "` by a small helper. `to_svg(c, l) == to_svg(c, l)` for the same inputs (fully deterministic; floats formatted with a fixed spec, no `repr`).
- [ ] `to_svg` assumes `layout` is a complete solve of `carcass`; a `carcass` node id absent from `layout` is a programmer error and may raise `KeyError`.
- [ ] Fully typed per CLAUDE.md "Typed Python": no bare `Any`/`dict`/`list` in signatures; helpers annotated; `shelving_core/svg.py` imports only from `shelving_core.layout`, `shelving_core.solver`, and the standard library. `mypy --strict` clean.

### Demo (`tools/layout_demo.py`)
- [ ] Gains an `argparse` CLI with one optional argument `--svg PATH`. With `--svg`, after solving it writes `to_svg(carcass, solved)` to `PATH` (UTF-8) and prints one confirmation line naming the path; the text tree dump still prints as before. Without `--svg`, behavior is unchanged.
- [ ] The module docstring is updated: it now has a command line (the "There is no command line" sentence is replaced with the `--svg` description). The `if _REPO_ROOT not in sys.path` guard stays.
- [ ] If `tools/layout_demo.py` carries its own rule-label helper, it is removed in favor of importing `_rule_label` from `shelving_core.svg` (single source).

### Tests
- [ ] `shelving_core/tests/test_svg.py`: `to_svg` output parses with `xml.etree.ElementTree.fromstring`; the root is the SVG element with a `viewBox`; for a known sample the `<rect>` count equals `n_leaves + n_dividers + 1`; there is one label `<text>` per leaf plus the title. For a 100x100 carcass, thickness 10, one `HORIZONTAL` `[Fill, Fill]` split: assert both leaf rects' SVG `x`/`y`/`width`/`height`, proving the y-flip (the child at higher solver `z` is drawn nearer the top of the SVG). A `>= 3`-child split renders 3 leaf rects and 2 divider rects. `to_svg` is called twice on the same input and the strings are equal.
- [ ] `tests/test_layout_demo.py` (repo-root, from sh-003) is extended: run `python tools/layout_demo.py --svg <tmp path>`, assert exit 0, the file exists and is non-empty, `ElementTree.fromstring` parses it, and its root tag is the SVG element. The existing no-arg assertions stay.
- [ ] `./test.sh --fast` exits 0; `pixi run full` / `./test.sh --full` green; `pixi run demo -- --svg <tmp>` writes a parseable SVG and exits 0.
- [ ] `mypy --strict` clean over `shelving_core` (incl. `svg.py`) and `tools/layout_demo.py`; `ruff check .` and `ruff format --check .` clean.

### Docs and vendoring
- [ ] `README.md`: the demo paragraph mentions `pixi run demo -- --svg layout.svg` (or `python tools/layout_demo.py --svg layout.svg`) writes an SVG elevation, and that it opens with Quick Look (spacebar in Finder) or any browser.
- [ ] `bash tools/vendor-core.sh` is re-run and the refreshed `freecad/shelving/vendor/shelving_core/svg.py` committed so `bash tools/vendor-core.sh --check` (in `--fast`) passes.

### Scope guard
- [ ] SVG only: no STL, no PNG, no new runtime or dev dependency. No FreeCAD import in `shelving_core/`. `shelving_core/svg.py` does not recompute a solve; it consumes the passed `SolvedLayout`.

## Frontier Advice

`blocked_by: [sh-003]` is a hard blocker: `shelving_core/svg.py` imports `Carcass`
from `shelving_core.layout` and `SolvedLayout` / `Rect` from
`shelving_core.solver`, and it amends `tools/layout_demo.py` and
`tests/test_layout_demo.py`, all of which sh-003 creates.

CRITICAL: `shelving_core` stays runtime-dependency-free. `to_svg` builds the SVG
with f-strings / `str.join`, not a third-party library and not
`xml.etree.ElementTree` for construction (ElementTree is fine in the TEST for
parsing). Standard library only: `xml.sax.saxutils.escape` (or a 4-replace
helper) for escaping.

STANDING OBLIGATIONS (`CLAUDE.md`): **Typed Python** applies and is satisfied
(fully annotated `to_svg`, `_rule_label`, coordinate helpers; no bare
`Any`/`dict`). No other standing obligation is active. Do NOT add
`from __future__ import annotations` (PEP 749); `svg.py` has no recursive
self-referential annotations, so none is needed.

COORDINATE MAPPING: one helper pair, used everywhere.
`_svg_x(x_mm) -> float = margin_mm + x_mm`.
`_svg_y(z_mm, h_mm) -> float = margin_mm + title_band_mm + (carcass.height_mm - z_mm - h_mm)`.
Do not use an SVG `transform` scale-flip on a group (it mirrors text). Format
every coordinate with a fixed spec (e.g. `f"{v:.3f}"`), never `str(float)` or
`repr`, so output is byte-stable.

STRUCTURE WALK: recurse the `carcass` tree in pre-order. At a `Split`, `zip`
`children` with `rules`; recurse into each child carrying that child's rule so a
`Leaf` can render its positioning rule. `Divider` ids come from
`Split.dividers`. Look each id up in `layout` (`layout[node_id]` -> `Rect`).
Collect `(kind, Rect, optional label lines)` during the walk, then emit carcass
outline, then all dividers, then all leaves+labels, then the title, so z-order
is deterministic and leaves/text sit above dividers.

`_rule_label`: `match rule: case Fixed(): f"Fixed {rule.size_mm:g} mm"; case
Weighted(): f"Weighted {rule.weight:g}"; case Fill(): "Fill"`. Exhaustive over
the `SplitRule` union. Put it in `svg.py`; if `tools/layout_demo.py` already
has an equivalent, delete that copy and import this one.

DEMO CLI: `argparse.ArgumentParser`, one `parser.add_argument("--svg",
type=pathlib.Path, default=None)`. Keep the text dump unconditional. On `--svg`,
`path.write_text(to_svg(carcass, solved), encoding="utf-8")` then
`print(f"wrote {path}")`. No other flags, no subcommands.

TEST y-FLIP ASSERTION: for the 100x100 / thickness 10 / `HORIZONTAL [Fill,
Fill]` case, the interior is 80x80 at solver `(10, 10)`. `distribute` splits 80
minus one 10 mm divider into two 35 mm openings. Child 0 (list order, low edge)
is at solver `z=10..45`; child 1 at solver `z=55..90`. In SVG space child 1
(higher `z`) must have the SMALLER `y` (nearer the top). Assert both leaves'
`y` and that child 1's `y` < child 0's `y`.

Friction log: record any workaround per `CLAUDE.md`.

## Execution Plan

- [x] **Step 1** (`shelving_core/svg.py`): Implement `to_svg`, `_rule_label`, `_svg_x`/`_svg_y`, and an XML-escape helper per the Must Have and Frontier Advice. Pure, stdlib-only, fully typed, deterministic output. Pre-order tree walk collecting elements, then emit carcass outline / dividers / leaves+labels / title in that order inside one `<svg>` with a mm `viewBox` and a `<style>` block.

- [x] **Step 2** (`shelving_core/tests/test_svg.py`): Tests per the Must Have "Tests" bullet: XML parse, root + viewBox, rect and text counts for a known sample, the explicit y-flip coordinate assertion for the 100x100 case, a `>= 3`-child split's rect counts, and determinism (`to_svg` called twice is equal).

- [x] **Step 3** (`tools/layout_demo.py`): Add the `argparse` `--svg PATH` flag per DEMO CLI; write the SVG and print a confirmation line when given; leave the text dump unconditional. Update the module docstring (replace "There is no command line"). Remove any local rule-label helper in favor of `shelving_core.svg._rule_label`.

- [x] **Step 4** (`tests/test_layout_demo.py`): Extend the existing repo-root test with a `--svg` case: subprocess-run `python tools/layout_demo.py --svg <tmp>`, assert exit 0, file exists and non-empty, parses as XML, root is the SVG element. Keep the existing assertions.

- [ ] **Step 5** (`README.md`, vendored copy): Update the demo paragraph in `README.md` to mention `pixi run demo -- --svg layout.svg` and opening the result with Quick Look or a browser. Run `bash tools/vendor-core.sh` and commit the refreshed `freecad/shelving/vendor/shelving_core/svg.py`. Confirm `./test.sh --fast` and `pixi run full` are green and `pixi run demo -- --svg /tmp/demo.svg` writes a parseable file.
