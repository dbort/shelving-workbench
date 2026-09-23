# sh-019 Review — Round 1

**Verdict:** REJECTED

`pixi run tests` is green on the branch tip (exit 0; `freecad_catalog_smoke.py`
printed all ten case lines and `shelving catalog OK`). The rejection is not a
failing check: it is that the milestone's headline behavior does not hold on the
path the workbench's own commands produce, and the new smoke's fixture is shaped
so that it cannot notice.

On the question the Implementer raised: their reading of Step 3 is correct.
"Take the catalog from `ensure_catalog(doc)`" is about where the value comes
from across the call chain, not a literal signature change. Step 3 itself
specifies `reflow_all(doc, catalog)` with an explicit catalog parameter, and the
Must Have is worded as "Every command that needs a catalog goes through it",
which `commands/resize_unit.py:146`, `commands/scan.py:83`,
`commands/reflow_all.py:63`, `commands/seed_catalog.py:60`, and
`commands/add_material.py:59` all satisfy. Keeping `catalog: Catalog` on
`resize_unit`/`rescan_unit` is fine and is not a finding.

## Blocking findings

- **F1: a board whose material equals the unit default never stores a
  `MaterialId`, so a thickness change cannot reach it**
  (`freecad/Shelving/core/scan.py:630`, `freecad/Shelving/container.py:537`,
  `freecad/Shelving/container.py:612`): the Frontier Advice states the mechanism
  this milestone rests on ("each board stores its material id, and sh-017's scan
  uses a stored material in preference to matching by thickness"). That premise
  is false for every unit the workbench writes today. Traced through the code:

  1. `_default_unit()` (`freecad/Shelving/unit_ops.py:44`) builds `Board(role=...)`
     nodes with no `material`, carrying only `default_material=DEFAULT_MATERIAL_ID`
     on the `Unit`.
  2. `write_container` writes `properties.write_board_material(tagged,
     board.material)` (`freecad/Shelving/container.py:537` for a created board,
     `:612` for an updated one) — the *layout node's* material, not the resolved
     `spec.material` that `expand` computed (`freecad/Shelving/core/expand.py:75`).
     `None` becomes `""` (`freecad/Shelving/properties.py:300-301`), so
     `Shelving_CreateUnit` leaves every board's `ShelvingMaterial` empty.
  3. A rescan does not repair it: `scan` deliberately elides the id when it
     matches the unit default, `material=None if material == ctx.default_material
     else material` (`freecad/Shelving/core/scan.py:630`). For a uniformly built
     unit the default *is* every board's material, so no board ever gets an id
     written, through `create_unit`, `resize_unit`, `rescan_unit`, or
     `reflow_all`.
  4. With no stored id, `_resolve_material` falls through to
     `_material_for_thickness_mm` (`freecad/Shelving/core/scan.py:818-826`), which
     raises `ScanError` when no catalog entry is within `snap_mm` (0.5). After a
     user edits `ply18` from 18 mm to 25 mm, an existing 18 mm board is 7 mm from
     `ply18`, 6 mm from `ply12`, 1 mm from `mdf19`, and 2 mm from `hardwood20`
     (`freecad/Shelving/default_catalog.py:17-45`), so the scan refuses:
     `bottom: no material has thickness 18 mm`.

  The consequence is that `Shelving_ReflowAll` refuses every unit in exactly the
  scenario the Must Have names ("Changing an entry's `Thickness` and running
  `Shelving_ReflowAll` rewrites every board using it while each unit's outside
  dimensions hold"), whenever the unit was produced by `Shelving_CreateUnit`
  rather than hand-built with per-board ids. `docs/manual-qa.md:333-351` (M8 step
  2) documents precisely that flow as expected to succeed, so the branch ships a
  manual-QA script that fails at the first reflow, and the same is true of the
  "run Resize Unit or Scan Unit first" line, which refuses after the edit for the
  same reason.

  This is stated as a code-reading, not a reproduction: the Reviewer deliberately
  did not run it by hand, because the fix needs a committed test either way. The
  Implementer's own smoke helper comment (`tools/freecad_catalog_smoke.py:71-78`,
  "every board carries `material_id` explicitly rather than inheriting
  `Unit.default_material` silently ... which is the whole mechanism this smoke's
  milestone case depends on") suggests this was noticed and worked around in the
  fixture rather than fixed in the product.

  Fixing it is a judgement call this review does not make for you: writing
  `spec.material` instead of `board.material` at `container.py:537`/`:612` stores
  the resolved id on every board, while dropping the elision at `scan.py:630`
  would change what a scanned `Unit` tree looks like and may have sh-017/sh-018
  consequences. Whichever route, the branch has to end with a board written by
  `Shelving_CreateUnit` carrying a resolvable `MaterialId`.

- **F2: the milestone case proves the reflow only for a fixture no command
  produces** (`tools/freecad_catalog_smoke.py:285-356`,
  `tools/freecad_catalog_smoke.py:71-99`): the two units in
  `_case_reflow_all_rewrites_the_changed_material` are built by
  `_closed_box_unit`, which sets `material=ply18` on all four boards, so the
  stored-id precedence path is exercised and F1 is invisible. Meanwhile
  `_case_create_unit_seeds_catalog_and_uses_it`
  (`tools/freecad_catalog_smoke.py:235-251`) asserts only that each box's thin
  axis equals the catalog's `ply18` thickness; it never checks that the boards
  reference catalog ids, although `read_container` already hands back
  `Box.material` for exactly that (`freecad/Shelving/core/scan.py:82`,
  `freecad/Shelving/container.py:168`). Step 5 asks for "`create_unit` on an
  empty document seeds the catalog and writes boards referencing its ids", which
  is unmet as an assertion and (per F1) as behavior.

  The round that fixes F1 needs a committed case in `tools/freecad_catalog_smoke.py`
  that goes through the real path end to end: build the unit with
  `unit_ops.create_unit`, assert each resulting board's stored `MaterialId`
  resolves in `read_catalog(find_catalog(doc))`, change that entry's `Thickness`
  from 18 to 25, run `reflow_all`, and assert the boards are 25 mm while the
  unit's bounding box is unchanged. Keeping the existing hand-built two-unit case
  for the continue-past-a-refusal half is fine; it just cannot be the only
  evidence for the thickness change reaching the boards.

## Non-blocking notes

- **N1: re-read the M8 manual-QA section once F1 lands**
  (`docs/manual-qa.md:333-372`): step 2's ordering (edit the thickness, then "run
  **Resize Unit** or **Scan Unit** first ... then run **Reflow All**") has both
  commands refusing under current behavior, and step 3's `updated 4` expectation
  assumes step 2 completed. The prose is otherwise in the file's established
  shape; it just needs to match whatever F1's fix makes true.
- **N2: a blanked `MaterialId` silently becomes the object `Name`**
  (`freecad/Shelving/catalog.py:167`): `read_entry_material_id(obj) or
  MaterialId(obj.Name)` means a user who clears the field in the property editor
  gets a catalog entry keyed on `Material001` rather than an error, which sits
  awkwardly beside the module's own "`MaterialId` is the stable key, not an
  entry's `Name` or `Label`" docstring and beside the strictness applied to a
  duplicate id or a non-positive thickness. Raising naming the entry would be
  consistent.
- **N3: `Shelving_Scan` mutates the document without a transaction**
  (`freecad/Shelving/commands/scan.py:83`): `ensure_catalog` can create a group
  plus four `App::VarSet` objects from inside a command that otherwise only
  reports, and unlike the other four catalog-touching commands this one opens no
  transaction, so those creations are not one undo step.
- **N4: the thickness writer casts a `float` to `FreeCAD.Quantity`**
  (`freecad/Shelving/properties.py:435`): the cast is untrue at runtime (a plain
  float is what gets assigned, which `App::PropertyLength` accepts). Typing
  `CatalogEntryObject.Thickness` as `float | FreeCAD.Quantity` would let the
  writer drop the cast while `read_entry_thickness_mm` keeps the `float()`
  conversion it already does.
