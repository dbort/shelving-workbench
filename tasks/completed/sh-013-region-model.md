---
id: sh-013
title: "The region model, no FreeCAD"
current_agent: user
current_phase: done
review_rejections: 2
---

# sh-013: The region model, no FreeCAD

## Summary
Replace the carcass split-tree with the region model: a region is a bay, a void,
or a division of an ordered run of boards and sub-regions along one axis, so the
carcass shell stops being a rule and becomes the outermost boards of the
outermost divisions. Regions carry a 3D extent, which folds the unit-wide depth
and the special-cased front inset into one per-face inset on a board. Tears out
the FreeCAD object layer and the SVG renderer in the same task, because both are
built on the carcass and neither survives the new design. Milestone M4.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [x] User sign-off

## Must Have
- [x] `pixi run tests` green.
- [x] `shelving_core.layout` exports `Axis`, `Basis`, `Fixed`, `Weighted`,
      `Fill`, `SizeRule`, `Insets`, `Board`, `Bay`, `Void`, `Division`,
      `Region`, `Item`, `Unit`. `grep -rn 'Carcass\|LapOrder\|PlankRole\|PlankSpec\|SplitRule\|class Split\|class Leaf\|class Divider' shelving_core/ freecad/ tools/ --include=*.py` (excluding `vendor/`) returns nothing.
- [x] `shelving_core/geometry.py` defines `Vec3` and `Space`; `Space` is an
      axis-aligned box as a minimum corner plus an extent, both `Vec3`.
- [x] `solve(unit, catalog)` returns one `Space` per region id and board id.
      `expand(unit, catalog)` returns `list[BoardSpec]`, one per `Board`, in
      tree order.
- [x] A closed box built from ordinary items expands to the geometry the
      carcass model produced, asserted against hard-coded expected values (the
      carcass is gone, so there is nothing to compare against at runtime).
- [x] A stepped unit of three columns of falling height expands to one top per
      column and emits no board for either `Void`.
- [x] Two `Board` items adjacent in one division expand touching, with the
      second's minimum corner equal to the first's maximum along the axis.
- [x] A `Fixed` rule with `Basis.WITH_NEXT` holds board positions when the
      catalog thickness changes; the same layout with `Basis.CLEAR` moves them.
      Both asserted in one test.
- [x] `LayoutSolveError` is raised with reason `overflow`,
      `no_slack_absorber`, `nonpositive_opening`, and `unresolvable_basis`,
      one test each.
- [x] `freecad/shelving/objects/`, `freecad/shelving/commands/create_unit.py`,
      `tools/freecad_object_smoke.py`, `shelving_core/svg.py`,
      `shelving_core/tests/test_svg.py`, `shelving_core/layout.schema.json`,
      and `shelving_core/tests/test_schema.py` do not exist.
- [x] `tests/test_layout_demo.py` drives the rebuilt demo and asserts its
      board table; it carries no `--svg` test, because the renderer is gone
      until M5.
- [x] `docs/manual-qa.md` carries no M3 case block and no reference to
      `tools/freecad_object_smoke.py`.
- [x] `freecadcmd` still imports the workbench: `tools/freecad_smoke.py` prints
      its OK marker and `tools/run-tests.sh` still greps for it.
- [x] `mypy --strict` clean over `shelving_core/`, `tools/`, `tests/`, and
      `freecad/shelving/`.

## Frontier Advice

CRITICAL: `spikes/plain_planks/general_model.py` is the worked design for the
region model and `spikes/plain_planks/test_general_model.py` for its tests.
COPY from them; do NOT move or delete them. The spike is the only way to look at
a layout while the workbench has no commands, and M6 deletes it.

The spike is 2D plus a unit-wide depth. This task is NOT. Regions carry a 3D
extent, a division names `Axis.X`, `Axis.Y`, or `Axis.Z`, and a board fills its
region's cross-section with a per-face inset. `Unit` therefore has NO depth
field and `Board` has NO `front_inset_mm` or `depth_mm`; those collapse into
`Insets`. Translate the spike, do not transcribe it.

VOCABULARY, settled in planning. Use exactly these names:
- `Unit` — outer size, default material, root region, id.
- `Division` — a region cut into an ordered run along one axis. NOT `Divide`,
  NOT `Split`.
- `Bay` — an enclosed compartment, open, part of the unit.
- `Void` — space inside the bounding box that is not part of the unit. What
  makes an outline stepped. Emits no board and is not a compartment.
- `Board` — one physical member. NOT `Plank`, NOT `Panel`. Rename every
  surviving `plank` identifier: `PlankSpec` becomes `BoardSpec`.
- There is NO wrapper type pairing a region with its rule. The rule is a field
  on `Bay`, `Void`, and `Division`. The root region's rule is unused because it
  has no parent; do not special-case it, do not validate it.

`SizeRule = Fixed | Weighted | Fill` replaces `SplitRule`. `Fixed` carries
`size_mm` and `basis: Basis`, defaulting to `Basis.CLEAR`.

MEASUREMENT BASIS. `Basis` has exactly two members, `CLEAR` and `WITH_NEXT`.
Do NOT add a `WITH_PREVIOUS`: an unimplemented member is the reserved-and-dead
pattern this repo was already bitten by with `Divider.lap`. `CLEAR` means the
number is the region's own extent along the axis. `WITH_NEXT` means the number
covers the region plus the item immediately after it in the run, which is how a
shelf spacing quoted top face to top face is stated. Resolve `WITH_NEXT` to a
clear size BEFORE calling `distribute`, by subtracting the next item's thickness;
`distribute` itself must NOT gain a basis case. If the region is the last item
in the run, or the next item is not a `Board`, raise `LayoutSolveError` with
reason `unresolvable_basis` naming the region id.

REUSE `shelving_core.solver.distribute` UNCHANGED. A board contributes
`Fixed(thickness_mm)` and a region contributes its own rule, so the arithmetic
never needed to know which was which. Pass an empty divider-thickness sequence.
Adding a fourth member to `SolveErrorReason` is the only edit `solver.py`'s
existing surface needs beyond the new `solve`.

`Board.role` is a free-form `str` set by the caller, defaulting to `""`. Do NOT
reintroduce a closed role enum: a stepped unit has several tops and none of them
is *the* top. Deriving a role from tree position is M7's problem, when labels
need it.

NO JSON, NO SCHEMA. Delete `layout.schema.json` and `tests/test_schema.py` and
do not replace them. The tree is derived from geometry each time under the
current design, and what M7 stores is a smaller record of rules and metadata
that it will design for its own shape. Tests express fixtures as Python
literals, which is what the spike already does.

The FreeCAD teardown is NOT a port. `freecad/shelving/objects/` and
`commands/create_unit.py` are built on the carcass and nothing in them survives.
KEEP `freecad/shelving/commands/__init__.py`, which M6 and M7 add commands to,
and KEEP `freecad/shelving/default_catalog.py`, which is M8's seed data; it is
orphaned until then and that is expected, do not delete it and do not flag it.
`init_gui.py` keeps registering the workbench and stops registering commands:
`Initialize` appends an empty toolbar and menu, and its deferred import of
`create_unit` goes.

`docs/manual-qa.md`'s seven M3 cases all drive the create-unit command, plank
reflow, or the `Layout` property, and its automation note points at the object
smoke. All of it goes with the object layer. Do NOT write replacement cases:
M6 adds its own once there is a command to drive.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python applies in full: no bare `Any`,
no bare `dict`/`list`/`tuple`/`set` in signatures or public attributes, and
`mypy --strict` over everything changed. Shell stays simple applies trivially:
the only shell edit is deleting the object-smoke block from
`tools/run-tests.sh`, no new logic.

Every length identifier carries its unit suffix (`size_mm`, `x_min_mm`,
`thickness_mm`). `Insets` fields are `_mm`.

ATOMICITY. Steps 4 through 10 are one change: replacing `layout.py` breaks
`solver.py`, `expand.py`, their tests, and `tools/layout_demo.py` at once, and
no clean split exists. Steps 1, 2, 3, and 11 each stand alone and must be green
on their own.

## Execution Plan

- [x] **Step 1** (`freecad/shelving/`, `tools/`, `docs/manual-qa.md`): Delete `freecad/shelving/objects/` entirely (`__init__.py`, `feature_types.py`, `geometry.py`, `labels.py`, `plank.py`, `shelving_unit.py`), delete `freecad/shelving/commands/create_unit.py`, and delete `tools/freecad_object_smoke.py`. In `freecad/shelving/init_gui.py`, remove the deferred `from freecad.shelving.commands import create_unit` import and set `command_ids` to an empty list, keeping the `appendToolbar` / `appendMenu` calls and the class docstring corrected to say the workbench registers no commands yet. In `tools/run-tests.sh`, delete the `freecad_object_smoke.py` block (the header printf, the capture, the echo, and the grep guard); leave the `freecad_smoke.py` block untouched. KEEP `freecad/shelving/commands/__init__.py` and `freecad/shelving/default_catalog.py`. In `docs/manual-qa.md`, delete the entire `## M3` section and its seven numbered cases, and repoint the automation note that names `tools/freecad_object_smoke.py` at `tools/freecad_smoke.py`; leave the loading-from-a-checkout section intact, since it still applies.

- [x] **Step 2** (`shelving_core/svg.py`, `shelving_core/tests/test_svg.py`, `tools/layout_demo.py`, `tests/test_layout_demo.py`, `README.md`): Delete `shelving_core/svg.py` and `shelving_core/tests/test_svg.py`. In `tools/layout_demo.py`, remove the `--svg` option, the `to_svg` and `rule_label` imports, the argument parsing for it, and every line that writes a file; the script keeps printing the catalog, the solved bays, and the plank table to stdout only, and takes no arguments. In `README.md`, drop the sentence beginning "Add `pixi run demo -- --svg`" and leave the rest of that paragraph intact. In `tests/test_layout_demo.py`, delete `test_demo_svg_flag_writes_a_parseable_svg` entirely along with its `xml.etree` and `Path` imports if nothing else uses them; leave `test_demo_runs_and_prints_the_solved_sample` alone in this step, it still passes against the carcass demo. Do not touch `shelving_core/layout.py` in this step.

- [x] **Step 3** (`shelving_core/geometry.py`, `shelving_core/tests/test_geometry.py`, `shelving_core/expand.py`): Create `shelving_core/geometry.py` with two frozen dataclasses. `Vec3(x_mm: float, y_mm: float, z_mm: float)`, moved verbatim from `expand.py` including its docstring. `Space(origin: Vec3, size: Vec3)`, an axis-aligned box in the unit's local frame given as a minimum corner and an extent, with a method returning the extent along a given `Axis`-shaped index and a method returning the maximum corner. Add `shelving_core/tests/test_geometry.py` covering both. In `expand.py`, replace the local `Vec3` definition with `from shelving_core.geometry import Vec3` and re-export it so existing importers keep working. This step is additive and must be green on its own.

- [x] **Step 4** (`shelving_core/layout.py`): Replace the module contents. Define `Axis(enum.StrEnum)` with `X`, `Y`, `Z`. Define `Basis(enum.StrEnum)` with `CLEAR` and `WITH_NEXT`. Keep `Fixed`, `Weighted`, `Fill` and their validation, adding `basis: Basis = Basis.CLEAR` to `Fixed` only; alias `SizeRule = Fixed | Weighted | Fill`. Define frozen `Insets` with `x_min_mm`, `x_max_mm`, `y_min_mm`, `y_max_mm`, `z_min_mm`, `z_max_mm`, all defaulting to `0.0`, documenting on the type that the pair on a division's own axis is ignored because a board fills that axis by its thickness. Define `Board(material: MaterialId | None = None, insets: Insets = Insets(), role: str = "", id: str = new_id())`. Define `Bay(rule: SizeRule = Fill(), id)` and `Void(rule: SizeRule = Fill(), id)` with docstrings stating that a `Void` is space inside the bounding box that is not part of the unit, holds no boards, and is not a compartment. Define `Division(axis: Axis, items: list[Item], rule: SizeRule = Fill(), id)` rejecting an empty `items` in `__post_init__`, with a docstring stating that items run in order along the axis and need not alternate, so two adjacent boards are two boards face to face. Alias `Region = Bay | Void | Division` and `Item = Board | Region`. Define `Unit(size_mm: Vec3, default_material: MaterialId, root: Region, id)` validating every component of `size_mm` positive and `default_material` non-empty. Delete `Carcass`, `Bay` as a union, `Leaf`, `Split`, `Divider`, `LapOrder`, `Orientation`, `SCHEMA_VERSION`, every `*Doc` TypedDict, and every `to_dict` / `to_json` / `from_dict` / `from_json` / `_*_to_doc` / `_*_from_doc` helper. Keep `new_id`.

- [x] **Step 5** (`shelving_core/solver.py`): Keep `EPS_MM`, `LayoutSolveError`, and `distribute` unchanged except for adding `"unresolvable_basis"` to `SolveErrorReason`. Delete `Rect`, `SolvedLayout`, `_interior_rect`, `_effective_thicknesses_mm`, `_place`, and the carcass `solve`. Add `solve(unit: Unit, catalog: Catalog) -> dict[str, Space]` returning one `Space` per region id and per board id, placing the root at origin `Vec3(0,0,0)` with extent `unit.size_mm`. For a `Division`, build the rule list by mapping each `Board` item to `Fixed(catalog[item.material or unit.default_material].thickness_mm)` and each region item to its own `rule`, resolving `Basis.WITH_NEXT` first in a separate helper that subtracts the next item's resolved thickness and raises `unresolvable_basis` when the region is last or the next item is not a `Board`; then call `distribute` with an empty divider sequence. Walk the resulting sizes along the division's axis from the region's minimum corner, passing the other two axes through unchanged. Raise `LayoutSolveError` with reason `nonpositive_opening` for any size at or below `EPS_MM`, naming the offending item's id.

- [x] **Step 6** (`shelving_core/expand.py`): Replace `PlankSpec` with frozen `BoardSpec(node_id: str, role: str, size: Vec3, placement: Vec3, material: MaterialId)`, keeping the docstring convention that `placement` is the minimum corner in the unit's local frame. Delete `PlankRole`. Replace `expand` with `expand(unit: Unit, catalog: Catalog) -> list[BoardSpec]`: call `solve`, walk the tree in order, and emit one `BoardSpec` per `Board`, applying that board's `Insets` to the two cross-section axes of its parent division and leaving the division's own axis at the solved extent. Keep `total_volume_mm3` retargeted to `BoardSpec`. State in the module docstring that a `Void` contributes no board.

- [x] **Step 7** (`shelving_core/tests/test_layout.py`): Rewrite. Cover construction and validation for every type: `Division` rejecting empty items, `Unit` rejecting a non-positive component of `size_mm` and an empty `default_material`, `Fixed` rejecting a non-positive size, `Weighted` rejecting a non-positive weight, `Insets` defaulting to zero on all six faces, and `Fixed` defaulting to `Basis.CLEAR`. Assert that two `new_id()` calls differ and that ids survive construction. Delete every carcass, JSON, and lap-order test.

- [x] **Step 8** (`shelving_core/tests/test_solver.py`): Rewrite the layout-level tests, keeping the existing `distribute` unit tests verbatim since `distribute` is unchanged. Add: a closed box placing its four shell boards and its interior correctly; a division mixing a `Fixed` region, a `Fill` region, and boards; a `Void` receiving a `Space` like any region; a division along `Axis.Y` proving the solver is axis-agnostic. Error tests, one each, asserting `LayoutSolveError.reason`: `overflow`, `no_slack_absorber`, `nonpositive_opening`, and `unresolvable_basis` for both the last-item case and the next-item-is-not-a-board case. Add the basis test: one layout solved twice against catalogs whose thickness differs, asserting that `Basis.WITH_NEXT` holds every board's minimum corner along the axis while `Basis.CLEAR` moves them.

- [x] **Step 9** (`shelving_core/tests/test_expand.py`): Rewrite. The equivalence test carries the carcass model's output as hard-coded expected `(size, placement)` tuples, sourced by running `spikes/plain_planks/test_general_model.py::test_closed_box_matches_the_carcass_model` before editing anything, with a comment saying the values are the carcass expansion and that the carcass no longer exists to compare against. Add: a stepped unit of three columns of falling height asserting one top per column at three descending heights and no board emitted for either `Void`; two adjacent `Board` items asserting the second's minimum corner equals the first's maximum along the axis; a board with non-zero `Insets` asserting both cross-section axes are inset and the division axis is not; `total_volume_mm3` over a known unit.

- [x] **Step 10** (`tools/layout_demo.py`, `tests/test_layout_demo.py`): Rebuild on the region model. Build a stepped sample unit, three columns of falling height on a continuous bottom board with a `Void` above the two shorter columns, plus at least one interior shelf and one board in a second material. Print the catalog, then one line per region id with its solved `Space`, then the board table with role, size, placement, and material, then the total volume. No arguments, no file output. Rewrite `tests/test_layout_demo.py::test_demo_runs_and_prints_the_solved_sample` against the new output: it drives the script as a subprocess exactly as it does now, and asserts the catalog line, the presence of a region line per region, a `Boards:` header, one row per board including the per-column tops and excluding anything for either `Void`, and the total-volume line. Keep the module docstring's point that this test is what catches a refactor of a name the demo imports.
  > **Checkpoint:** `pixi run tests` must be green here (Steps 4-10 are one atomic replacement of the core model).

- [x] **Step 11** (`README.md`): Rewrite the Glossary section for the region model. Define exactly the terms the code now uses: Unit, Region, Bay, Void, Division, Item, Board, Insets, Axis, size rule (Fixed, Weighted, Fill), Basis and what clear versus with-next measure, Catalog, MaterialEntry, MaterialId, BoardSpec, Vec3, Space, local coordinate frame, `distribute`, `solve`, `expand`. Delete the entries for Carcass, Leaf, Split, Divider, Plank, Joint, Butt joint, Lap order, Default carcass rule, PlankSpec, PlankRole, and Spacing solver. State under Board that user-facing documentation calls the same thing a panel. Keep the section's existing shape: one bullet per term, naming where it lives in `shelving_core`.
