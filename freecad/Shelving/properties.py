"""Every FreeCAD property this workbench reads or writes, named once.

No other module spells one of these property names directly: a board's
``ShelvingMaterial``, ``ShelvingBornAs``, ``ShelvingBornIn``, and
``ShelvingIrregular``, a container's ``ShelvingUnitId``,
``ShelvingDepthAxis``, ``ShelvingFacing``, and ``ShelvingRules``, the
catalog group's marker ``ShelvingCatalog``, and a catalog entry's
``MaterialId``, ``Description``, ``Thickness``, ``MaterialType``, and
``NominalThickness``. The board, container, and marker properties sit in a
``Shelving`` property group so they stand out from a plain object's built-ins
in the property editor; the entry properties carry no such prefix because
their names are already the ones a user editing a stock item expects.

``ensure_board_properties``, ``ensure_container_properties``,
``ensure_catalog_group_properties``, and ``ensure_entry_properties`` add
whatever is missing and are idempotent, so a caller can call any of them on
every write without checking first. ``freecad-stubs`` types only the generic
``DocumentObject``, with no way to express "a ``DocumentObject`` that also
carries these dynamically-added properties"; ``BoardObject``,
``ContainerObject``, ``CatalogGroupObject``, and ``CatalogEntryObject`` are
the ``Protocol`` classes that let the rest of the workbench read and write
them with real types instead of ``getattr`` chains, and the ``ensure_*``
functions are what a caller casts through to get one.

Facing is stored as a string enumeration (``"min"`` / ``"max"`` /
``"unknown"``) rather than a nullable boolean: a FreeCAD property has no null,
and ``Unit.front_at_min`` has three states (front at the depth
axis's minimum end, its maximum end, or undetermined), so collapsing to two
string values plus "property absent" would conflate "never written" with
"determined to be undetermined".

A catalog entry's ``Thickness`` is an ``App::PropertyLength``, so the
property editor shows it with units and respects the user's unit schema; it
reads back as a ``FreeCAD.Quantity``, not a ``float``, so
``read_entry_thickness_mm`` converts it to a plain millimetre float rather
than leaving that conversion to every caller.
"""

from __future__ import annotations

from typing import Protocol, cast

import FreeCAD

from freecad.Shelving.core.layout import Axis
from freecad.Shelving.core.materials import MaterialId

GROUP_NAME = "Shelving"

MATERIAL_PROP = "ShelvingMaterial"
BORN_AS_PROP = "ShelvingBornAs"
BORN_IN_PROP = "ShelvingBornIn"
IRREGULAR_PROP = "ShelvingIrregular"

UNIT_ID_PROP = "ShelvingUnitId"
DEPTH_AXIS_PROP = "ShelvingDepthAxis"
FACING_PROP = "ShelvingFacing"
RULES_PROP = "ShelvingRules"

CATALOG_MARKER_PROP = "ShelvingCatalog"

ENTRY_MATERIAL_ID_PROP = "MaterialId"
ENTRY_DESCRIPTION_PROP = "Description"
ENTRY_THICKNESS_PROP = "Thickness"
ENTRY_MATERIAL_TYPE_PROP = "MaterialType"
ENTRY_NOMINAL_THICKNESS_PROP = "NominalThickness"

_BOARD_PROP_NAMES = (MATERIAL_PROP, BORN_AS_PROP, BORN_IN_PROP, IRREGULAR_PROP)
_CONTAINER_PROP_NAMES = (UNIT_ID_PROP, DEPTH_AXIS_PROP, FACING_PROP, RULES_PROP)
_ENTRY_PROP_NAMES = (
    ENTRY_MATERIAL_ID_PROP,
    ENTRY_DESCRIPTION_PROP,
    ENTRY_THICKNESS_PROP,
    ENTRY_MATERIAL_TYPE_PROP,
    ENTRY_NOMINAL_THICKNESS_PROP,
)

_FACING_MIN = "min"
_FACING_MAX = "max"
_FACING_UNKNOWN = "unknown"
_FACING_ENUM_VALS = [_FACING_MIN, _FACING_MAX, _FACING_UNKNOWN]

_AXIS_BY_VALUE: dict[str, Axis] = {axis.value: axis for axis in Axis}


class BoardObject(Protocol):
    """A board's ``DocumentObject`` after :func:`ensure_board_properties`."""

    Name: str
    ShelvingMaterial: str
    ShelvingBornAs: str
    ShelvingBornIn: str
    ShelvingIrregular: bool


class ContainerObject(Protocol):
    """A container's ``DocumentObject`` after
    :func:`ensure_container_properties`."""

    Name: str
    ShelvingUnitId: str
    ShelvingDepthAxis: str
    ShelvingFacing: str
    ShelvingRules: str


class CatalogGroupObject(Protocol):
    """The catalog's ``App::DocumentObjectGroup`` after
    :func:`ensure_catalog_group_properties`."""

    Name: str
    ShelvingCatalog: bool


class CatalogEntryObject(Protocol):
    """One catalog entry's ``App::VarSet`` after
    :func:`ensure_entry_properties`."""

    Name: str
    Label: str
    MaterialId: str
    Description: str
    # App::PropertyLength reads back as a Quantity but accepts a plain
    # float on assignment, which is what write_entry_thickness_mm writes.
    Thickness: float | FreeCAD.Quantity
    MaterialType: str
    NominalThickness: str


def has_board_properties(obj: FreeCAD.DocumentObject) -> bool:
    """Whether ``obj`` already carries every board provenance property.

    This, not any single property, is what the deletion and left-alone rules
    (``freecad.Shelving.container.write_container``) mean by "carries this
    workbench's provenance": a part the workbench never wrote has none of
    these four, and a part only partway tagged is a bug, not a state a
    caller should trust piecemeal.
    """
    return all(hasattr(obj, name) for name in _BOARD_PROP_NAMES)


def has_container_properties(obj: FreeCAD.DocumentObject) -> bool:
    """Whether ``obj`` already carries every container property."""
    return all(hasattr(obj, name) for name in _CONTAINER_PROP_NAMES)


def has_catalog_marker(obj: FreeCAD.DocumentObject) -> bool:
    """Whether ``obj`` is a group tagged as the document's material catalog.

    Checked by property, not by ``Name`` or ``Label``: either is renameable
    from the tree, and a rename must not silently detach the catalog.
    """
    return bool(getattr(obj, CATALOG_MARKER_PROP, False))


def has_entry_properties(obj: FreeCAD.DocumentObject) -> bool:
    """Whether ``obj`` already carries every catalog entry property."""
    return all(hasattr(obj, name) for name in _ENTRY_PROP_NAMES)


def ensure_board_properties(obj: FreeCAD.DocumentObject) -> BoardObject:
    """Add any of the four board properties ``obj`` is missing, and return
    it narrowed to :class:`BoardObject`. A no-op, property by property, on an
    object that already carries some or all of them."""
    if not hasattr(obj, MATERIAL_PROP):
        obj.addProperty(
            "App::PropertyString",
            MATERIAL_PROP,
            GROUP_NAME,
            "The catalog material id this board resolves to, bypassing "
            "thickness matching. Empty means none stored.",
        )
    if not hasattr(obj, BORN_AS_PROP):
        obj.addProperty(
            "App::PropertyString",
            BORN_AS_PROP,
            GROUP_NAME,
            "The document object Name this board had when the workbench "
            "first tagged it.",
        )
    if not hasattr(obj, BORN_IN_PROP):
        obj.addProperty(
            "App::PropertyString",
            BORN_IN_PROP,
            GROUP_NAME,
            "The document Uid at the moment the workbench first tagged this board.",
        )
    if not hasattr(obj, IRREGULAR_PROP):
        obj.addProperty(
            "App::PropertyBool",
            IRREGULAR_PROP,
            GROUP_NAME,
            "Whether this board's shape is geometrically irregular: its "
            "size is verified against the layout rather than derived from it.",
        )
    return cast("BoardObject", obj)


def ensure_container_properties(obj: FreeCAD.DocumentObject) -> ContainerObject:
    """Add any of the four container properties ``obj`` is missing, and
    return it narrowed to :class:`ContainerObject`."""
    if not hasattr(obj, UNIT_ID_PROP):
        obj.addProperty(
            "App::PropertyString",
            UNIT_ID_PROP,
            GROUP_NAME,
            "The core Unit.id this container was last written from.",
        )
    if not hasattr(obj, DEPTH_AXIS_PROP):
        obj.addProperty(
            "App::PropertyString",
            DEPTH_AXIS_PROP,
            GROUP_NAME,
            "Which axis ('x', 'y', or 'z') runs front to back.",
        )
    if not hasattr(obj, FACING_PROP):
        obj.addProperty(
            "App::PropertyEnumeration",
            FACING_PROP,
            GROUP_NAME,
            "Which end of the depth axis is the front: 'min', 'max', or 'unknown'.",
            enum_vals=_FACING_ENUM_VALS,
        )
        setattr(obj, FACING_PROP, _FACING_UNKNOWN)
    if not hasattr(obj, RULES_PROP):
        obj.addProperty(
            "App::PropertyString",
            RULES_PROP,
            GROUP_NAME,
            "The per-region size rule record, as freecad.Shelving.core."
            "record.rules_to_json emits it.",
        )
    return cast("ContainerObject", obj)


def ensure_catalog_group_properties(obj: FreeCAD.DocumentObject) -> CatalogGroupObject:
    """Add the catalog marker property to ``obj`` if it is missing, and
    return it narrowed to :class:`CatalogGroupObject`."""
    if not hasattr(obj, CATALOG_MARKER_PROP):
        obj.addProperty(
            "App::PropertyBool",
            CATALOG_MARKER_PROP,
            GROUP_NAME,
            "Marks this group as the document's one material catalog.",
        )
        setattr(obj, CATALOG_MARKER_PROP, True)
    return cast("CatalogGroupObject", obj)


def ensure_entry_properties(obj: FreeCAD.DocumentObject) -> CatalogEntryObject:
    """Add any of the five catalog entry properties ``obj`` is missing, and
    return it narrowed to :class:`CatalogEntryObject`."""
    if not hasattr(obj, ENTRY_MATERIAL_ID_PROP):
        obj.addProperty(
            "App::PropertyString",
            ENTRY_MATERIAL_ID_PROP,
            GROUP_NAME,
            "The stable id a board's ShelvingMaterial references. Renaming "
            "this object's Name or Label never changes it.",
        )
    if not hasattr(obj, ENTRY_DESCRIPTION_PROP):
        obj.addProperty(
            "App::PropertyString",
            ENTRY_DESCRIPTION_PROP,
            GROUP_NAME,
            "Human-readable description of the stock item.",
        )
    if not hasattr(obj, ENTRY_THICKNESS_PROP):
        obj.addProperty(
            "App::PropertyLength",
            ENTRY_THICKNESS_PROP,
            GROUP_NAME,
            "The measured panel thickness the solver subtracts for dividers "
            "and the carcass shell.",
        )
    if not hasattr(obj, ENTRY_MATERIAL_TYPE_PROP):
        obj.addProperty(
            "App::PropertyString",
            ENTRY_MATERIAL_TYPE_PROP,
            GROUP_NAME,
            "Free-form stock category, such as 'plywood' or 'mdf'.",
        )
    if not hasattr(obj, ENTRY_NOMINAL_THICKNESS_PROP):
        obj.addProperty(
            "App::PropertyString",
            ENTRY_NOMINAL_THICKNESS_PROP,
            GROUP_NAME,
            "Free human label for the callout thickness (e.g. '3/4\"'), not "
            "a millimetre value. Empty means unset.",
        )
    return cast("CatalogEntryObject", obj)


def read_board_material(obj: FreeCAD.DocumentObject) -> MaterialId | None:
    """``obj``'s stored material id, or ``None`` when absent or unset."""
    value = getattr(obj, MATERIAL_PROP, "")
    if not isinstance(value, str) or not value:
        return None
    return MaterialId(value)


def write_board_material(obj: BoardObject, material: MaterialId | None) -> None:
    obj.ShelvingMaterial = material or ""


def read_board_born_as(obj: FreeCAD.DocumentObject) -> str | None:
    """The ``Name`` ``obj`` had when the workbench first tagged it, or
    ``None`` when the property is absent."""
    value = getattr(obj, BORN_AS_PROP, "")
    return value if isinstance(value, str) and value else None


def write_board_born_as(obj: BoardObject, name: str) -> None:
    obj.ShelvingBornAs = name


def read_board_born_in(obj: FreeCAD.DocumentObject) -> str | None:
    """The document ``Uid`` at the moment ``obj`` was first tagged, or
    ``None`` when the property is absent."""
    value = getattr(obj, BORN_IN_PROP, "")
    return value if isinstance(value, str) and value else None


def write_board_born_in(obj: BoardObject, uid: str) -> None:
    obj.ShelvingBornIn = uid


def read_board_irregular(obj: FreeCAD.DocumentObject) -> bool:
    """Whether ``obj`` is stored as geometrically irregular; ``False`` when
    the property is absent."""
    value = getattr(obj, IRREGULAR_PROP, False)
    return bool(value) if isinstance(value, bool) else False


def write_board_irregular(obj: BoardObject, irregular: bool) -> None:
    obj.ShelvingIrregular = irregular


def is_copy(obj: FreeCAD.DocumentObject, doc: FreeCAD.Document) -> bool:
    """Whether ``obj``'s own provenance marks it a copy of another board:
    its ``Name`` differs from the ``ShelvingBornAs`` it carries, or ``doc``'s
    ``Uid`` differs from its ``ShelvingBornIn``.

    ``False`` for an object with no provenance recorded at all (nothing to
    compare against, so nothing says it is a copy of anything this
    workbench wrote) as well as for a continuously-existing tagged object.
    See the module docstring on ``freecad.Shelving.core.record`` and this
    task's Frontier Advice for why a mismatch means "copy" rather than
    "relocation" only when ``Name`` differs; a ``BornIn`` mismatch alone
    (same ``Name``, different ``Uid``) means the object was copied into a
    fresh document, not duplicated within one.
    """
    born_as = read_board_born_as(obj)
    born_in = read_board_born_in(obj)
    if born_as is None or born_in is None:
        return False
    return born_as != obj.Name or born_in != doc.Uid


def read_container_unit_id(obj: FreeCAD.DocumentObject) -> str | None:
    value = getattr(obj, UNIT_ID_PROP, "")
    return value if isinstance(value, str) and value else None


def write_container_unit_id(obj: ContainerObject, unit_id: str) -> None:
    obj.ShelvingUnitId = unit_id


def read_container_depth_axis(obj: FreeCAD.DocumentObject) -> Axis | None:
    value = getattr(obj, DEPTH_AXIS_PROP, "")
    if not isinstance(value, str) or value not in _AXIS_BY_VALUE:
        return None
    return _AXIS_BY_VALUE[value]


def write_container_depth_axis(obj: ContainerObject, axis: Axis | None) -> None:
    obj.ShelvingDepthAxis = axis.value if axis is not None else ""


def read_container_facing(obj: FreeCAD.DocumentObject) -> bool | None:
    """``True`` when the front is at the depth axis's minimum end, ``False``
    at its maximum, ``None`` when undetermined or the property is absent:
    both collapse to ``None`` because ``Unit.front_at_min`` itself does not
    distinguish "never determined" from "determined to be undetermined"."""
    value = getattr(obj, FACING_PROP, _FACING_UNKNOWN)
    if value == _FACING_MIN:
        return True
    if value == _FACING_MAX:
        return False
    return None


def write_container_facing(obj: ContainerObject, front_at_min: bool | None) -> None:
    if front_at_min is True:
        obj.ShelvingFacing = _FACING_MIN
    elif front_at_min is False:
        obj.ShelvingFacing = _FACING_MAX
    else:
        obj.ShelvingFacing = _FACING_UNKNOWN


def read_container_rules_json(obj: FreeCAD.DocumentObject) -> str | None:
    value = getattr(obj, RULES_PROP, "")
    return value if isinstance(value, str) and value else None


def write_container_rules_json(obj: ContainerObject, rules_json: str) -> None:
    obj.ShelvingRules = rules_json


def read_entry_material_id(obj: FreeCAD.DocumentObject) -> MaterialId | None:
    value = getattr(obj, ENTRY_MATERIAL_ID_PROP, "")
    return MaterialId(value) if isinstance(value, str) and value else None


def write_entry_material_id(obj: CatalogEntryObject, material_id: MaterialId) -> None:
    obj.MaterialId = str(material_id)


def read_entry_description(obj: FreeCAD.DocumentObject) -> str:
    value = getattr(obj, ENTRY_DESCRIPTION_PROP, "")
    return value if isinstance(value, str) else ""


def write_entry_description(obj: CatalogEntryObject, description: str) -> None:
    obj.Description = description


def read_entry_thickness_mm(obj: FreeCAD.DocumentObject) -> float:
    """``obj``'s ``Thickness`` in millimetres, converted from the
    ``FreeCAD.Quantity`` an ``App::PropertyLength`` reads back as; ``0.0``
    when the property is absent."""
    value = getattr(obj, ENTRY_THICKNESS_PROP, None)
    return float(value) if value is not None else 0.0


def write_entry_thickness_mm(obj: CatalogEntryObject, thickness_mm: float) -> None:
    obj.Thickness = thickness_mm


def read_entry_material_type(obj: FreeCAD.DocumentObject) -> str:
    value = getattr(obj, ENTRY_MATERIAL_TYPE_PROP, "")
    return value if isinstance(value, str) else ""


def write_entry_material_type(obj: CatalogEntryObject, material_type: str) -> None:
    obj.MaterialType = material_type


def read_entry_nominal_thickness(obj: FreeCAD.DocumentObject) -> str | None:
    value = getattr(obj, ENTRY_NOMINAL_THICKNESS_PROP, "")
    return value if isinstance(value, str) and value else None


def write_entry_nominal_thickness(
    obj: CatalogEntryObject, nominal_thickness: str | None
) -> None:
    obj.NominalThickness = nominal_thickness or ""
