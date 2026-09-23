"""The material catalog as a document object.

A catalog is an ``App::DocumentObjectGroup`` carrying
``freecad.Shelving.properties.CATALOG_MARKER_PROP``, holding one
``App::VarSet`` per stock entry. Neither type needs a proxy, so a saved
document mentions no ``Proxy``, ``FeaturePython``, or ``PythonObject``: the
same promise the boards make (see ``freecad.Shelving.container``). Editing an
entry is the property editor and deleting one is the tree; this module adds
no dialog of its own. :func:`ensure_catalog` is the one entry point every
command uses, and :func:`read_catalog` turns a catalog group into the
``freecad.Shelving.core.materials.Catalog`` the solver and scanner consume.

``MaterialId`` is the stable key a board stores, not an entry's ``Name`` or
``Label``: either is renameable from the tree, and a rename must not orphan
a board that already references the id.

:func:`read_catalog` builds the whole document's catalog at once and raises
the moment any one entry cannot stand: a caller that needs every
entry validated together (an isolated check, or a case in this module's own
smoke) wants that. A command touching one unit does not: an unrelated
entry an editor left half-filled in (an :func:`add_entry` result nobody has
edited yet, say) has nothing to do with whether that unit's own boards
resolve, so :func:`read_usable_catalog` builds a catalog from only the
entries that individually validate and reports the rest as skipped rather
than refusing the whole document. A board that needed a skipped entry fails
the same way it already fails on any id absent from the catalog (see
``freecad.Shelving.core.scan``'s "not in the catalog" refusal, naming the
board), so the attribution a user sees is the board or unit touched, not a
bare entry name.
"""

from __future__ import annotations

from typing import cast

import FreeCAD

from freecad.Shelving import properties
from freecad.Shelving.core.materials import Catalog, MaterialEntry, MaterialId
from freecad.Shelving.default_catalog import DEFAULT_CATALOG

_GROUP_TYPE = "App::DocumentObjectGroup"
_ENTRY_TYPE = "App::VarSet"
_GROUP_NAME = "MaterialCatalog"
_GROUP_LABEL = "Material Catalog"

_PLACEHOLDER_ID = "new_material"
_PLACEHOLDER_DESCRIPTION = "New material"
_PLACEHOLDER_MATERIAL_TYPE = "unspecified"


def _catalog_groups(doc: FreeCAD.Document) -> list[FreeCAD.DocumentObject]:
    return [
        obj
        for obj in doc.Objects
        if obj.isDerivedFrom(_GROUP_TYPE) and properties.has_catalog_marker(obj)
    ]


def find_catalog(doc: FreeCAD.Document) -> FreeCAD.DocumentObject | None:
    """The one catalog group in ``doc``, ``None`` when there is none, or a
    ``ValueError`` naming both when there are two.

    Found by the marker property, not by ``Name`` or ``Label``: a group is
    renameable from the tree, and a rename must not silently detach the
    catalog a board's material id depends on.
    """
    groups = _catalog_groups(doc)
    if not groups:
        return None
    if len(groups) > 1:
        names = ", ".join(sorted(g.Name for g in groups))
        raise ValueError(
            f"document has two material catalogs ({names}); a board's material "
            "would otherwise depend on which one a command happened to find"
        )
    return groups[0]


def _sanitize_object_name(candidate: str) -> str:
    """``candidate`` cut down to the identifier-only characters a FreeCAD
    object ``Name`` accepts, or ``""`` when nothing survives;
    ``doc.addObject`` treats an empty or colliding name as a hint and assigns
    a fresh one, so this never has to be unique itself."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in candidate)
    cleaned = cleaned.strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _create_entry_object(
    doc: FreeCAD.Document,
    group: FreeCAD.DocumentObject,
    *,
    material_id: str,
    description: str,
    thickness_mm: float,
    material_type: str,
    nominal_thickness: str | None,
) -> FreeCAD.DocumentObject:
    raw = doc.addObject(_ENTRY_TYPE, _sanitize_object_name(material_id) or "Material")
    obj = cast("FreeCAD.DocumentObject", raw)
    cast("FreeCAD.DocumentObjectGroup", group).addObject(obj)
    entry = properties.ensure_entry_properties(obj)
    properties.write_entry_material_id(entry, MaterialId(material_id))
    properties.write_entry_description(entry, description)
    properties.write_entry_thickness_mm(entry, thickness_mm)
    properties.write_entry_material_type(entry, material_type)
    properties.write_entry_nominal_thickness(entry, nominal_thickness)
    entry.Label = description or obj.Name
    return obj


def seed_catalog(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    """Create the catalog group and one ``App::VarSet`` per entry of
    :data:`freecad.Shelving.default_catalog.DEFAULT_CATALOG`, each labelled
    from its description. Does not check whether ``doc`` already has one;
    callers needing that go through :func:`ensure_catalog`."""
    raw_group = doc.addObject(_GROUP_TYPE, _GROUP_NAME)
    group = cast("FreeCAD.DocumentObject", raw_group)
    group.Label = _GROUP_LABEL
    properties.ensure_catalog_group_properties(group)
    for default_entry in DEFAULT_CATALOG:
        _create_entry_object(
            doc,
            group,
            material_id=str(default_entry.id),
            description=default_entry.name,
            thickness_mm=default_entry.thickness_mm,
            material_type=default_entry.material_type,
            nominal_thickness=default_entry.nominal_thickness,
        )
    return group


def ensure_catalog(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    """``doc``'s existing catalog group, or a freshly seeded one when it has
    none. The only entry point a command needs: it never fails for want of a
    catalog, and never falls back to an in-code catalog without creating the
    document object, so a board written against it always has something real
    to reference."""
    existing = find_catalog(doc)
    if existing is not None:
        return existing
    return seed_catalog(doc)


def _entry_objects(group: FreeCAD.DocumentObject) -> list[FreeCAD.DocumentObject]:
    """Every member of ``group`` that carries the entry properties: what
    :func:`read_catalog` and :func:`add_entry` treat as a catalog entry. A
    member missing them is silently not an entry, the same tolerance
    ``freecad.Shelving.container`` gives an untagged object it does not
    recognize. Nothing this module adds is ever missing them; the only way
    one occurs is a user dragging some other object into the group."""
    members = cast("FreeCAD.DocumentObjectGroup", group).Group
    return [m for m in members if properties.has_entry_properties(m)]


def read_catalog(group: FreeCAD.DocumentObject) -> Catalog:
    """The :class:`~freecad.Shelving.core.materials.Catalog` built from every
    entry in ``group``, in the order the group holds them.

    Raises a ``ValueError`` naming both entries when two share a
    ``MaterialId``, naming the entry when its ``Thickness`` is zero or
    negative, and naming the entry when its ``MaterialId`` is blank: any of
    the three would make the catalog resolve a board's stored id
    ambiguously or unusably, so this refuses to build one rather than
    silently picking a winner or falling back to the object's ``Name``,
    which ``MaterialId`` is deliberately not (see this module's docstring).
    """
    entries: dict[MaterialId, MaterialEntry] = {}
    object_by_id: dict[MaterialId, FreeCAD.DocumentObject] = {}
    for obj in _entry_objects(group):
        material_id = properties.read_entry_material_id(obj)
        if material_id is None:
            raise ValueError(f"{obj.Name}: MaterialId must not be blank")
        thickness_mm = properties.read_entry_thickness_mm(obj)
        if thickness_mm <= 0:
            raise ValueError(
                f"{obj.Name}: Thickness must be greater than zero, got "
                f"{thickness_mm:g} mm"
            )
        if material_id in entries:
            raise ValueError(
                f"two catalog entries share MaterialId {material_id!r}: "
                f"{object_by_id[material_id].Name!r} and {obj.Name!r}"
            )
        entries[material_id] = MaterialEntry(
            id=material_id,
            name=properties.read_entry_description(obj),
            thickness_mm=thickness_mm,
            material_type=properties.read_entry_material_type(obj),
            nominal_thickness=properties.read_entry_nominal_thickness(obj),
        )
        object_by_id[material_id] = obj
    return Catalog(entries=entries)


def read_usable_catalog(
    group: FreeCAD.DocumentObject,
) -> tuple[Catalog, tuple[str, ...]]:
    """The :class:`~freecad.Shelving.core.materials.Catalog` built from every
    entry in ``group`` that individually validates, paired with one message
    per entry left out: a blank ``MaterialId``, a non-positive ``Thickness``,
    or a ``MaterialId`` shared with another entry (both sharers are left out,
    since neither can be preferred over the other).

    Unlike :func:`read_catalog`, an invalid entry does not stop the build: it
    is absent from the returned ``Catalog``, the same as an id nobody
    ever wrote a catalog entry for. This is what every catalog-touching
    command builds against, so one entry an editor has not finished yet
    never blocks a unit whose boards never reference it.
    """
    grouped: dict[MaterialId, list[tuple[FreeCAD.DocumentObject, float]]] = {}
    skipped: list[str] = []
    for obj in _entry_objects(group):
        material_id = properties.read_entry_material_id(obj)
        if material_id is None:
            skipped.append(f"{obj.Name}: MaterialId must not be blank")
            continue
        thickness_mm = properties.read_entry_thickness_mm(obj)
        if thickness_mm <= 0:
            skipped.append(
                f"{obj.Name}: Thickness must be greater than zero, got "
                f"{thickness_mm:g} mm"
            )
            continue
        grouped.setdefault(material_id, []).append((obj, thickness_mm))

    entries: dict[MaterialId, MaterialEntry] = {}
    for material_id, objs in grouped.items():
        if len(objs) > 1:
            names = ", ".join(sorted(obj.Name for obj, _thickness_mm in objs))
            skipped.append(
                f"two catalog entries share MaterialId {material_id!r}: {names}"
            )
            continue
        obj, thickness_mm = objs[0]
        entries[material_id] = MaterialEntry(
            id=material_id,
            name=properties.read_entry_description(obj),
            thickness_mm=thickness_mm,
            material_type=properties.read_entry_material_type(obj),
            nominal_thickness=properties.read_entry_nominal_thickness(obj),
        )
    return Catalog(entries=entries), tuple(skipped)


def _unique_placeholder_id(existing_ids: set[str]) -> str:
    if _PLACEHOLDER_ID not in existing_ids:
        return _PLACEHOLDER_ID
    suffix = 2
    candidate = f"{_PLACEHOLDER_ID}_{suffix}"
    while candidate in existing_ids:
        suffix += 1
        candidate = f"{_PLACEHOLDER_ID}_{suffix}"
    return candidate


def add_entry(group: FreeCAD.DocumentObject) -> FreeCAD.DocumentObject:
    """Append one blank entry to ``group`` with a placeholder ``MaterialId``
    that does not collide with an existing one, and return it.

    ``Thickness`` is left at its ``App::PropertyLength`` default of zero:
    the one field :func:`read_catalog` refuses on, so a blank entry left
    unedited is excluded by :func:`read_usable_catalog` and reported as
    skipped rather than silently resolving boards against a meaningless
    thickness. It stays unusable, by that id, until edited; it does not
    block any other entry.
    """
    doc = group.Document
    existing_ids = {
        str(properties.read_entry_material_id(obj) or "")
        for obj in _entry_objects(group)
    }
    return _create_entry_object(
        doc,
        group,
        material_id=_unique_placeholder_id(existing_ids),
        description=_PLACEHOLDER_DESCRIPTION,
        thickness_mm=0.0,
        material_type=_PLACEHOLDER_MATERIAL_TYPE,
        nominal_thickness=None,
    )
