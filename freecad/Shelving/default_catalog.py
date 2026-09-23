"""Seed data for a document's material catalog.

`freecad.Shelving.catalog.seed_catalog` copies these entries into a
document's own `App::VarSet` group the first time anything needs a catalog;
from then on the document's copy, editable through the property editor, is
authoritative, not this module. Standard library plus the sibling
`freecad.Shelving.core` package only; no `FreeCAD` import, so it loads under
a bare `python` as well as inside FreeCAD.
"""

from freecad.Shelving.core.materials import (
    Catalog,
    MaterialEntry,
    MaterialId,
)

_ENTRIES: tuple[MaterialEntry, ...] = (
    MaterialEntry(
        id=MaterialId("ply18"),
        name="18 mm birch plywood",
        thickness_mm=18.0,
        material_type="plywood",
        nominal_thickness='3/4"',
    ),
    MaterialEntry(
        id=MaterialId("ply12"),
        name="12 mm birch plywood",
        thickness_mm=12.0,
        material_type="plywood",
        nominal_thickness='1/2"',
    ),
    MaterialEntry(
        id=MaterialId("mdf19"),
        name="19 mm MDF",
        thickness_mm=19.0,
        material_type="mdf",
        nominal_thickness='3/4"',
    ),
    MaterialEntry(
        id=MaterialId("hardwood20"),
        name="20 mm hard maple",
        thickness_mm=20.0,
        material_type="solid wood",
    ),
)

DEFAULT_CATALOG: Catalog = Catalog(entries={entry.id: entry for entry in _ENTRIES})

DEFAULT_MATERIAL_ID: MaterialId = MaterialId("ply18")
