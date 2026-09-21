---
id: sh-019
title: "The material catalog as a document object"
current_agent: implementer
current_phase: planning
review_rejections: 0
blocked_by: [sh-018]
---

# sh-019: The material catalog as a document object

## Summary
Move the catalog out of code and into the document: a group of `App::VarSet`
entries, one per stock item, each editable in the property editor with no dialog
and no proxy. Seeded from the in-code default the first time anything needs it.
Adds a command that reflows every tagged unit in the document, which is what
makes a changed thickness reach the boards using it. Milestone M8.

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] `pixi run tests` green.
- [ ] `freecad/Shelving/catalog.py` exports `find_catalog`, `seed_catalog`,
      `ensure_catalog`, `read_catalog`, and `add_entry`.
- [ ] A catalog is an `App::DocumentObjectGroup` carrying a marker property,
      holding one `App::VarSet` per entry. No proxy anywhere: a saved document's
      `Document.xml` contains no `Proxy`, `FeaturePython`, or `PythonObject`
      entry, asserted in the smoke.
- [ ] Each entry carries `MaterialId`, `Description`, `Thickness`,
      `MaterialType`, and `NominalThickness`, and `read_catalog` builds a
      `shelving_core.materials.Catalog` from them.
- [ ] `find_catalog` returns the one catalog in a document, `None` when there is
      none, and raises naming both objects when there are two.
- [ ] `read_catalog` raises naming both entries when two share a `MaterialId`,
      and naming the entry when a `Thickness` is zero or negative.
- [ ] `ensure_catalog(doc)` seeds from `freecad.Shelving.default_catalog` when
      the document has none and returns the existing one otherwise. Every
      command that needs a catalog goes through it, so Create Unit works on an
      empty document with no setup.
- [ ] `Shelving_SeedCatalog` and `Shelving_AddMaterial` are registered and
      appear in the toolbar and menu. There is NO edit dialog: editing and
      deleting are the property editor and the tree.
- [ ] `Shelving_ReflowAll` rescans and rewrites every container carrying
      `ShelvingUnitId`, continues past a unit that refuses, and reports per unit.
- [ ] Changing an entry's `Thickness` and running `Shelving_ReflowAll` rewrites
      every board using it while each unit's outside dimensions hold. Asserted
      in the headless smoke against a document holding two units.
- [ ] A board whose `ShelvingMaterial` names no catalog entry refuses at scan,
      naming the board.
- [ ] `tools/freecad_catalog_smoke.py` prints `shelving catalog OK` and
      `tools/run-tests.sh` greps for it.
- [ ] `docs/manual-qa.md` has an M8 section; `freecad/Shelving/default_catalog.py`
      no longer claims M4 will replace it.
- [ ] `mypy --strict` clean.

## Frontier Advice

`App::VarSet` IS THE ENTRY TYPE, verified against FreeCAD 1.0. It is a native
property container needing no proxy, its properties survive a save and reload,
and a saved document mentions neither `Proxy` nor `FeaturePython`. That is what
keeps a catalog readable in a document whose owner never installed this
workbench, which is the same promise the boards make. Do NOT use
`App::FeaturePython`: it needs a proxy and a document that loses the workbench
then shows a broken object.

NO EDIT DIALOG. Entries are plain objects with plain properties, so editing one
is the property editor and deleting one is the tree, both of which every FreeCAD
user already knows. Two commands only: seed a catalog, and add a blank entry.
Building a panel that lists entries with add, edit and remove would duplicate
the property editor for no gain.

`Thickness` IS AN `App::PropertyLength`, so the property editor shows it with
units and respects the user's unit schema. Read it as `float(obj.Thickness)` to
get millimetres; a `PropertyLength` reads back as a `Quantity`, not a float, and
passing a `Quantity` into the core would break its typing.

`MaterialId` IS THE STABLE KEY, not the object's `Name` and not its `Label`.
Boards store a material id, so renaming an entry's object must not orphan them.
That means a duplicate `MaterialId` is an error rather than something to
silently resolve: raise naming both entries, because a board referring to that
id would otherwise be ambiguous. This is the mirror of the board copy problem,
and a copied entry is exactly how it arises.

ONE CATALOG PER DOCUMENT, found by a marker property on the group, not by object
name. A name is renameable from the tree and a rename would silently detach the
catalog. Two catalogs is an error naming both, because a board's material would
otherwise depend on which one a command happened to find.

SEED ON DEMAND. `ensure_catalog` is the only entry point commands use. A fresh
document then works with no setup, and nothing ever fails for want of a catalog.
Do NOT fall back to the in-code catalog without creating the object: a board
would then store a material id that the document does not contain, and the
reference dangles the moment anyone else opens it.

REFLOW IS A COMMAND, NOT A RECOMPUTE. Nothing in this design recomputes on its
own, so a changed thickness is stale until `Shelving_ReflowAll` runs. That is
consistent with M7, where the unit's size is geometry and Resize is a command.
`Shelving_ReflowAll` finds every container carrying `ShelvingUnitId`, calls
sh-018's `rescan_unit` on each inside ONE transaction, and reports per unit. A
unit that raises must NOT abort the others: collect its error, continue, and
report every failure at the end.

WHY A RESCAN PICKS UP A THICKNESS CHANGE AT ALL, since it is not obvious: each
board stores its material id, and sh-017's scan uses a stored material in
preference to matching by thickness. So a board still 18 mm thick resolves to
`ply18`, the catalog now says `ply18` is 25 mm, and the solve produces 25 mm
boards. Without that precedence this milestone would be impossible, because
every existing board would match no entry.

DO NOT ADD A PHYSICAL-MATERIAL REFERENCE. Stock and substance are separate
lists: a thickness belongs to the sheet you bought, a density to the material.
Referencing FreeCAD's material system is a recorded future path whose first real
payoff is mass, and a field nothing reads is the reserved-and-dead pattern this
repo was already bitten by. `App::VarSet` lets a user add such a property by
hand meanwhile.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python in full: no bare `Any`, no bare
containers in signatures or public attributes, `mypy --strict` clean. FreeCAD's
stubs type only the generic `DocumentObject`, so extend the `Protocol` classes
in `freecad/Shelving/properties.py` rather than reaching for `Any`. Shell stays
simple applies: the only shell edit is adding a smoke block to
`tools/run-tests.sh` in the same shape as the existing ones, no new logic.

Every length identifier carries `_mm`.

## Execution Plan

- [ ] **Step 1** (`freecad/Shelving/properties.py`): Extend the property module with the catalog's names and accessors, so no other module spells one. The group's marker property, and the five entry properties `MaterialId`, `Description`, `Thickness`, `MaterialType`, `NominalThickness`. `ensure_entry_properties(obj)` adding any that are missing, idempotent. Typed readers and writers, with the thickness reader returning a plain `float` in millimetres from the `Quantity` a `PropertyLength` yields. A `Protocol` for the entry surface.

- [ ] **Step 2** (`freecad/Shelving/catalog.py`): Create the module. `find_catalog(doc)` scanning the document for a group carrying the marker, returning `None` for none and raising a `ValueError` naming both for two. `seed_catalog(doc)` creating the group and one `App::VarSet` per entry of `freecad.Shelving.default_catalog.DEFAULT_CATALOG`, labelling each from its description. `ensure_catalog(doc)` returning the existing catalog or seeding one. `read_catalog(group)` building a `shelving_core.materials.Catalog`, raising a `ValueError` naming both entries on a duplicate `MaterialId` and naming the entry on a non-positive `Thickness`. `add_entry(group, ...)` appending one blank entry with a placeholder id that does not collide with an existing one.

- [ ] **Step 3** (`freecad/Shelving/unit_ops.py`): Route every catalog use through the document. Change `create_unit`, `resize_unit`, and `rescan_unit` to take the catalog from `ensure_catalog(doc)` rather than the in-code default. Add `reflow_all(doc, catalog)` finding every container carrying `ShelvingUnitId`, calling `rescan_unit` on each, collecting per-unit results and per-unit errors without stopping, and returning both. Do NOT open a transaction here; the command owns it.

- [ ] **Step 4** (`freecad/Shelving/commands/`, `freecad/Shelving/init_gui.py`): Add three commands in the established shape, each behind the headless-safe `Gui.addCommand` guard. `Shelving_SeedCatalog` calling `ensure_catalog` and reporting whether it created or found one. `Shelving_AddMaterial` calling `ensure_catalog` then `add_entry`, and selecting the new entry so the user lands in its properties. `Shelving_ReflowAll` opening one transaction, calling `reflow_all`, committing, and printing one line per unit plus every collected error; on an exception outside the per-unit loop, abort the transaction. Add all three ids to `init_gui`'s `command_ids`.

- [ ] **Step 5** (`tools/freecad_catalog_smoke.py`, `tools/run-tests.sh`): Create the headless functional check, following the existing smokes' preamble. Assert, in order: `ensure_catalog` on an empty document creates a group of `App::VarSet` entries matching the in-code default, and a second call returns the same object rather than creating another; `read_catalog` reproduces the default catalog; a second group carrying the marker makes `find_catalog` raise naming both; a duplicate `MaterialId` and a zero `Thickness` each raise naming the entry; `create_unit` on an empty document seeds the catalog and writes boards referencing its ids. Then the milestone's point: build a document with two units, change one entry's `Thickness` from 18 to 25, run `reflow_all`, and assert every board using that entry is now 25 mm thick while each unit's overall bounding box is unchanged, and that a unit whose layout cannot absorb the change reports its error without preventing the other unit from reflowing. Finally save, reload, and assert the archive mentions no `Proxy`, `FeaturePython`, or `PythonObject`. Print `shelving catalog OK` last, and add a matching block to `tools/run-tests.sh`.

- [ ] **Step 6** (`freecad/Shelving/default_catalog.py`, `docs/manual-qa.md`, `README.md`): Rewrite the module docstring: it is the seed data for a document catalog, not a stopgap, and the sentence naming M4 as its replacement is wrong and goes. Delete `DEFAULT_CATALOG_IDS` if nothing references it after Step 3. Add an `## M8` section to `docs/manual-qa.md` in the file's numbered-steps-then-expected-result shape, covering: create a unit on an empty document and confirm a materials group appears; change a thickness in the property editor and confirm nothing moves until Reflow All runs, then confirm boards change while the unit's outside size holds; add a material, assign it to one board by editing that board's `ShelvingMaterial`, and reflow. Extend the README glossary with catalog entry, `MaterialId` as the stable key, the one-catalog rule, and Reflow All, in the section's existing one-bullet-per-term shape.
