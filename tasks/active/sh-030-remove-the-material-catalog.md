---
id: sh-030
title: "Remove the material catalog"
---

# sh-030: Remove the material catalog

## Summary
The workbench stops managing materials. A board's thickness becomes its own
measured size, and its material, colour and grain stay where the Woodworking
workbench keeps them: FreeCAD's `ShapeMaterial`, the board's appearance, and a
per-face `Grain` list. A new shelf or divider copies all of that from the most
fitting existing board: another shelf in the same opening first, then one
elsewhere in the unit, then the carcass, so shelves can be a different stock
from the carcass. Seed Catalog, Add Material and Reflow All go away; changing
stock in the editor is a separate, later task.

## Must Have
- [ ] `pixi run tests` green.
- [ ] `freecad/Shelving/core/materials.py`, `freecad/Shelving/core/materials.schema.json`,
      `freecad/Shelving/catalog.py`, `freecad/Shelving/default_catalog.py`,
      `freecad/Shelving/commands/add_material.py`,
      `freecad/Shelving/commands/seed_catalog.py`,
      `freecad/Shelving/commands/reflow_all.py` and
      `tests/freecad/test_catalog.py` no longer exist, and
      `git grep -i -E "catalog|MaterialId|default_material"` finds nothing
      under `freecad/`, `tests/` or `tools/`.
- [ ] `solve`, `expand`, `scan`, `split_region` and `merge_at` take no
      catalog argument, and the workbench registers no `Shelving_SeedCatalog`,
      `Shelving_AddMaterial` or `Shelving_ReflowAll` command.
- [ ] A board's extent along its run is its own slot width in the scan grid.
      Asserted in the core suite: `real_stair_step.boxes.json` at the default
      `snap_mm` scans and solves (sh-026's reproduction), and a box set mixing
      17.6 mm and 19 mm boards scans and solves with each board's solved
      extent within 1e-6 mm of its slot width.
- [ ] A core function returns the source board for a new board, by the rule in
      Advice (SOURCE BOARD). Core tests cover each step:
      - a parallel interior board in the same opening wins over a nearer
        carcass board;
      - with no interior board in the opening, the nearest parallel interior
        board elsewhere in the unit;
      - with no interior board at all, the nearest parallel carcass board.

      Another test asserts that on the Magic Start fixture's tree the floor,
      top and sides are carcass and the shelf is interior.
- [ ] On `tests/freecad/fixtures/woodworking_magic_start_default.FCStd` (a
      copy), after the test gives the shelf a 12 mm thickness, a non-default
      `ShapeMaterial` and a `Grain` list, Add Shelf in the lower bay creates a
      board 12 mm thick with the shelf's `ShapeMaterial` name and `Grain`
      list.
- [ ] On a fresh `create_unit` unit, the first Add Shelf creates a board
      copying the bottom board's thickness and `ShapeMaterial`.
- [ ] In `tests/freecad_gui/`: a new board's `ShapeAppearance` equals its
      source board's, per-face colours included; resizing a unit leaves a
      hand-set board colour unchanged; `create_unit`'s boards are 18 mm thick
      with diffuse colour (247, 185, 108).
- [ ] A write never changes an existing board's `ShapeMaterial`, `Grain` or
      appearance. Asserted headless for `ShapeMaterial` and `Grain` across a
      resize.
- [ ] A container whose boards carry a leftover `ShelvingMaterial` property,
      in a document holding a leftover catalog group, opens in Edit Unit and
      takes an Add Shelf. The catalog group and every object in it are
      unchanged afterwards.
- [ ] `tasks/active/sh-022-appearance-and-errors.md` no longer plans
      `Shelving_RecolourUnit` or a material-to-colour mapping,
      `tasks/active/sh-023-preferences.md` no longer plans a default-material
      preference, and `docs/roadmap.md` marks M8 superseded by sh-030 under a
      legend entry for that status.
- [ ] `docs/manual-qa.md` has no M8 section and no case that edits a catalog
      or runs Reflow All, and has a case for a new shelf copying a shelf of
      different stock from the carcass.
- [ ] `mypy --strict` clean.

## Advice

DECISIONS (user, 2026-10-09). The workbench honours Woodworking's
conventions and never imports Woodworking code, so it works with or without
Woodworking installed:
- **Material:** FreeCAD's `ShapeMaterial` plus the board's appearance
  (`ViewObject.ShapeAppearance`). That's what Woodworking's `panelMaterial`
  sets, and its cut list reads `ShapeMaterial.Name`.
- **Grain:** an `App::PropertyStringList` named `Grain`, in property group
  `Woodworking`, one entry per face, as Woodworking's grainH/V/X tools write
  it. Never create or copy Woodworking's grain-arrow Draft texts.
- **Old documents:** ignore existing catalog groups and `ShelvingMaterial`
  properties: no migration, no cleanup. The workbench is unreleased.

THICKNESS IS GEOMETRY. A `Board`'s extent along its run is its own slot width
in the scan grid (`coords_mm` at its bounds), the same coordinates every
sibling's size comes from, so a run always adds up exactly. That dissolves
sh-026's mismatch, so do not port sh-026's reconciliation. A slot width can
differ from the raw box thickness by up to half `snap_mm` (0.25 mm at the
default); the user accepted that the first write moves boards by that much.
Keep sh-025's `Board.rule` for a board whose run axis is not its thin axis.
Represent thickness however reads best, either a `thickness_mm` on `Board` or
`Board.rule` for every board, but keep the field's `_mm` suffix.

SOURCE BOARD. A board the editor creates is always interior, and copies
thickness, `ShapeMaterial`, appearance and `Grain` from a source board,
chosen in this order:
1. a parallel interior board in the same opening, meaning the new board's
   own run;
2. the nearest parallel interior board anywhere in the unit;
3. the nearest parallel carcass board.

"Parallel" means the same thin axis. A board is carcass when, along its run,
everything between one of its faces and the unit's edge is `Void` or outside
the unit: no `Bay` on that side. This is a tree rule, not a bounding-box
test, because Magic Start's floor sits 100 mm up over a plinth gap. On the
Magic Start tree the sides, floor and top are carcass and the shelf is
interior. Decide the source in the core as a pure, tested function. Carry
the chosen source board's id on the new `Board` so the write path can copy
from that object; it need not persist after creation.

COPYING STOCK, in the write path, only when creating a board:
- `ShapeMaterial` from the source object;
- `Grain`, when the source has it, as a property of the same type and group;
- the whole `ShapeAppearance` list, per-face colours, transparency and shine
  included (user decision), and only when a `ViewObject` exists. Headless,
  `ViewObject` is `None` (`.claude/docs/freecad-notes.md`), so appearance
  tests belong in `tests/freecad_gui/`.

An update never touches any of these on an existing board.

CREATE UNIT stays, with Magic Start's look: 18 mm boards, FreeCAD's Default
material (leave `ShapeMaterial` as FreeCAD creates it), and diffuse colour
(247, 185, 108) when a GUI exists.

REMOVED:
- the catalog modules and the default catalog;
- the Seed Catalog, Add Material and Reflow All commands, and
  `unit_ops.reflow_all`;
- the board and catalog-entry properties in `freecad/Shelving/properties.py`;
- the `material` field on scan's `Box`, and `Unit.default_material`;
- catalog-driven colour in `freecad/Shelving/core/svg.py`, which draws boards
  in one neutral colour instead, since the core holds no appearance;
- `tests/freecad/test_catalog.py`. Before deleting it, move any test there
  that isn't about the catalog, such as saving a document and reopening it
  without a proxy, to `tests/freecad/test_write.py` (unless it already has an
  equivalent).

FOLDED-IN PLAN EDITS (user decision): this task rewrites
- `tasks/active/sh-022-appearance-and-errors.md`: drop
  `Shelving_RecolourUnit` and colour-by-material-id, since a new board's
  colour now comes from its source board here; keep Relabel and the shared
  refusal helper.
- `tasks/active/sh-023-preferences.md`: drop the default-material preference.
- `docs/roadmap.md`: add a legend entry for a milestone superseded by later
  work, and apply it to M8 (superseded by sh-030); M10's colour text follows
  sh-022.

The editor's stock list and stock swap are a separate later task. Until then
nothing in the workbench changes a board's thickness or material, so
`docs/manual-qa.md`'s M9 case 15 (stock thickness through Reflow All) goes.
That task will re-add it.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python: no bare `Any`, no bare
containers in signatures, `mypy --strict` clean; the FreeCAD property access
for `ShapeMaterial`, `Grain` and `ShapeAppearance` goes through typed
Protocols like the existing ones. Shell stays simple: this task changes no
shell script beyond removing what no longer exists, if anything.

## Plan
- [ ] **Step 1** (`freecad/Shelving/core/`): Remove the catalog from the core. Boards carry their own run-axis extent from the scan grid. `solve`, `expand`, `scan`, `split_region`, `merge_at` and the basis helpers in `edit.py` lose their catalog argument. Scan's `Box` loses `material`, `Unit` loses `default_material`, and `svg.py` draws boards in one neutral colour. Core tests follow, including sh-026's stair-step reproduction and a mixed 17.6/19 mm case.
- [ ] **Step 2** (`freecad/Shelving/core/edit.py` or a new core module, plus tests): Carcass classification and the SOURCE BOARD rule as a pure function. `split_region` gives the new board its source's thickness and records the source board's id.
- [ ] **Step 3** (`freecad/Shelving/`): Remove the catalog modules, the three commands and their registration, the board and entry properties, and `unit_ops.reflow_all`. The session and panel stop reading a catalog. The write path copies `ShapeMaterial`, `Grain` and, with a GUI, `ShapeAppearance` from the source object when creating a board, and never on update. Create Unit uses the Magic Start defaults.
- [ ] **Step 4** (`tests/freecad/`, `tests/freecad_gui/`): Delete `test_catalog.py` after moving out anything not about the catalog. Add the headless Must Have tests: the Magic Start stock copy, the create_unit fallback, update-never-touches, and leftover catalog objects. Add the GUI tests: appearance copy, a hand colour surviving a resize, Create Unit's colour.
- [ ] **Step 5** (`tools/layout_demo.py`, `README.md`, `docs/`, `.claude/docs/freecad-notes.md`): The demo runs without a catalog. Remove the catalog glossary terms and M8 manual QA; rewrite the docs' material passages for the Woodworking conventions and the source-board rule; add the manual-QA case for a shelf of different stock.
- [ ] **Step 6** (`tasks/active/sh-022-*.md`, `tasks/active/sh-023-*.md`, `docs/roadmap.md`): The folded-in plan edits from Advice.

## Review log
