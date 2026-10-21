"""Every FreeCAD property this workbench reads or writes, named once.

No other module spells one of these property names directly: a board's
``ShelvingBornAs``, ``ShelvingBornIn``, and ``ShelvingIrregular``, a
container's ``ShelvingUnitId``, ``ShelvingDepthAxis``, ``ShelvingFacing``,
``ShelvingRules``, ``ShelvingFixedX``, ``ShelvingFixedY``, and
``ShelvingFixedZ``, and the board stock the workbench copies but never
owns: FreeCAD's ``ShapeMaterial``, the view's ``ShapeAppearance``, and the
Woodworking workbench's per-face ``Grain`` list. The workbench's own
properties sit in a ``Shelving`` property group so they stand out from a
plain object's built-ins in the property editor.

``ensure_board_properties`` and ``ensure_container_properties`` add whatever
is missing and are idempotent, so a caller can call either on every write
without checking first. ``freecad-stubs`` types only the generic
``DocumentObject``, with no way to express "a ``DocumentObject`` that also
carries these dynamically-added properties"; the ``Protocol`` classes here
let the rest of the workbench read and write them with real types instead
of ``getattr`` chains, and the ``ensure_*`` functions are what a caller
casts through to get one.

Facing is stored as a string enumeration (``"min"`` / ``"max"`` /
``"unknown"``) rather than a nullable boolean: a FreeCAD property has no null,
and ``Unit.front_at_min`` has three states (front at the depth
axis's minimum end, its maximum end, or undetermined), so collapsing to two
string values plus "property absent" would conflate "never written" with
"determined to be undetermined".

The fixed point is three string enumerations of the same kind, one per
model axis (``"min"`` / ``"center"`` / ``"max"``). A container without
them reads as ``"min"`` on every axis: the minimum corner, which a
``Part::Box`` grows from too.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from typing import Protocol, cast

import FreeCAD

from freecad.Shelving.core.layout import Axis, FixedPoint, FixedSide
from freecad.Shelving.core.stock import Color

GROUP_NAME = "Shelving"

BORN_AS_PROP = "ShelvingBornAs"
BORN_IN_PROP = "ShelvingBornIn"
IRREGULAR_PROP = "ShelvingIrregular"

UNIT_ID_PROP = "ShelvingUnitId"
DEPTH_AXIS_PROP = "ShelvingDepthAxis"
FACING_PROP = "ShelvingFacing"
RULES_PROP = "ShelvingRules"
FIXED_PROPS: Mapping[Axis, str] = {
    Axis.X: "ShelvingFixedX",
    Axis.Y: "ShelvingFixedY",
    Axis.Z: "ShelvingFixedZ",
}

# The Woodworking workbench's grain list: one entry per face, in its own
# property group. Copied with the type and group the source carries.
GRAIN_PROP = "Grain"

_BOARD_PROP_NAMES = (BORN_AS_PROP, BORN_IN_PROP, IRREGULAR_PROP)
_CONTAINER_PROP_NAMES = (
    UNIT_ID_PROP,
    DEPTH_AXIS_PROP,
    FACING_PROP,
    RULES_PROP,
    *FIXED_PROPS.values(),
)
_FACING_MIN = "min"
_FACING_MAX = "max"
_FACING_UNKNOWN = "unknown"
_FACING_ENUM_VALS = [_FACING_MIN, _FACING_MAX, _FACING_UNKNOWN]
_FIXED_SIDES: tuple[FixedSide, ...] = ("min", "center", "max")

_AXIS_BY_VALUE: dict[str, Axis] = {axis.value: axis for axis in Axis}


class BoardObject(Protocol):
    """A board's ``DocumentObject`` after :func:`ensure_board_properties`."""

    Name: str
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
    ShelvingFixedX: str
    ShelvingFixedY: str
    ShelvingFixedZ: str


class FreeCADMaterial(Protocol):
    """A ``Materials.Material``, which ``freecad-stubs`` does not type."""

    Name: str
    UUID: str

    def hasAppearanceProperty(self, name: str, /) -> bool: ...

    # A color comes back as text such as "(0.8984, 0.7305, 0.3906, 1.0)".
    def getAppearanceValue(self, name: str, /) -> str: ...


class _MaterialManager(Protocol):
    """A ``Materials.MaterialManager``, which ``freecad-stubs`` does not type."""

    # Raises LookupError for a UUID the library does not hold.
    def getMaterial(self, uuid: str, /) -> FreeCADMaterial: ...


class _MaterialObject(Protocol):
    ShapeMaterial: FreeCADMaterial


class _GrainObject(Protocol):
    Grain: list[str]


class _AppearanceView(Protocol):
    """A view provider's appearance: one ``FreeCAD.Material`` per face, or a
    single entry applying to every face."""

    ShapeAppearance: list[FreeCAD.Material]


def has_board_properties(obj: FreeCAD.DocumentObject) -> bool:
    """Whether ``obj`` already carries every board provenance property.

    This, not any single property, is what the deletion and left-alone rules
    (``freecad.Shelving.container.write_container``) mean by "carries this
    workbench's provenance": a part the workbench never wrote has none of
    these three, and a part only partway tagged is a bug, not a state a
    caller should trust piecemeal.
    """
    return all(hasattr(obj, name) for name in _BOARD_PROP_NAMES)


def has_container_properties(obj: FreeCAD.DocumentObject) -> bool:
    """Whether ``obj`` already carries every container property."""
    return all(hasattr(obj, name) for name in _CONTAINER_PROP_NAMES)


def ensure_board_properties(obj: FreeCAD.DocumentObject) -> BoardObject:
    """Add any of the three board properties ``obj`` is missing, and return
    it narrowed to :class:`BoardObject`. A no-op, property by property, on an
    object that already carries some or all of them."""
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
    """Add any of the container properties ``obj`` is missing, and return
    it narrowed to :class:`ContainerObject`. A fixed side added here starts
    at ``"min"``."""
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
    for axis, name in FIXED_PROPS.items():
        if not hasattr(obj, name):
            obj.addProperty(
                "App::PropertyEnumeration",
                name,
                GROUP_NAME,
                f"Which side of the unit stays put along {axis.value} when its "
                "size changes: 'min', 'center', or 'max'.",
                enum_vals=list(_FIXED_SIDES),
            )
            setattr(obj, name, "min")
    return cast("ContainerObject", obj)


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
    return value if isinstance(value, bool) else False


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


def read_container_fixed_point(obj: FreeCAD.DocumentObject) -> FixedPoint:
    """The fixed side ``obj`` stores on each axis, ``"min"`` on any axis
    whose property is absent or holds no side."""
    fixed = FixedPoint()
    for axis, name in FIXED_PROPS.items():
        value = getattr(obj, name, "min")
        for side in _FIXED_SIDES:
            if value == side:
                fixed = fixed.with_side(axis, side)
    return fixed


def write_container_fixed_point(obj: ContainerObject, fixed: FixedPoint) -> None:
    obj.ShelvingFixedX = fixed.x
    obj.ShelvingFixedY = fixed.y
    obj.ShelvingFixedZ = fixed.z


def read_container_rules_json(obj: FreeCAD.DocumentObject) -> str | None:
    value = getattr(obj, RULES_PROP, "")
    return value if isinstance(value, str) and value else None


def write_container_rules_json(obj: ContainerObject, rules_json: str) -> None:
    obj.ShelvingRules = rules_json


def read_material_name(obj: FreeCAD.DocumentObject) -> str | None:
    """The name of ``obj``'s ``ShapeMaterial``, or ``None`` when it has none."""
    if not hasattr(obj, "ShapeMaterial"):
        return None
    return cast("_MaterialObject", obj).ShapeMaterial.Name


def library_material(uuid: str) -> FreeCADMaterial | None:
    """The material ``uuid`` names in FreeCAD's material library, the user's
    own libraries included, or ``None`` when the library holds none."""
    # freecad-stubs has no stub for the Materials module; _MaterialManager
    # types the one call made on it.
    import Materials  # pyrefly: ignore[missing-import]

    manager = cast("_MaterialManager", Materials.MaterialManager())
    try:
        return manager.getMaterial(uuid)
    except LookupError:
        return None


def write_material(obj: FreeCAD.DocumentObject, material: FreeCADMaterial) -> None:
    """Give ``obj`` the ``ShapeMaterial`` ``material``; nothing for an object
    without one. Leaves its appearance alone."""
    if hasattr(obj, "ShapeMaterial"):
        cast("_MaterialObject", obj).ShapeMaterial = material


def material_color(material: FreeCADMaterial) -> Color | None:
    """``material``'s appearance diffuse color, or ``None`` when it has none
    or the library's text for it does not read as one."""
    if not material.hasAppearanceProperty("DiffuseColor"):
        return None
    # The Material workbench's own editor reads this text the same way.
    parts = material.getAppearanceValue("DiffuseColor").strip().strip("()").split(",")
    try:
        channels = [float(part) for part in parts[:3]]
    except ValueError:
        return None
    if len(channels) != 3:
        return None
    return (_channel(channels[0]), _channel(channels[1]), _channel(channels[2]))


def _channel(value: float) -> int:
    return max(0, min(255, round(value * 255)))


def dominant_color(obj: FreeCAD.DocumentObject) -> Color | None:
    """The diffuse color most of ``obj``'s appearance entries carry, the
    first of them on a tie, or ``None`` without a GUI, where no object has
    an appearance."""
    view = _appearance_view(obj)
    if view is None or not view.ShapeAppearance:
        return None
    counts = Counter(
        (
            _channel(m.DiffuseColor[0]),
            _channel(m.DiffuseColor[1]),
            _channel(m.DiffuseColor[2]),
        )
        for m in view.ShapeAppearance
    )
    return counts.most_common(1)[0][0]


def read_grain(obj: FreeCAD.DocumentObject) -> list[str] | None:
    """``obj``'s Woodworking ``Grain`` list, or ``None`` when it has none."""
    if not hasattr(obj, GRAIN_PROP):
        return None
    return list(cast("_GrainObject", obj).Grain)


def _appearance_view(obj: FreeCAD.DocumentObject) -> _AppearanceView | None:
    """``obj``'s view provider, or ``None`` without a GUI, where FreeCAD
    creates no view provider at all."""
    view = obj.ViewObject
    return cast("_AppearanceView", view) if view is not None else None


def copy_stock(source: FreeCAD.DocumentObject, target: FreeCAD.DocumentObject) -> None:
    """Give ``target`` ``source``'s ``ShapeMaterial``, its ``Grain`` when it
    has one, in the same property type and group, and with a GUI its whole
    ``ShapeAppearance``, per-face colors included.

    Each property ``source`` lacks leaves ``target``'s own unchanged.
    """
    if hasattr(source, "ShapeMaterial") and hasattr(target, "ShapeMaterial"):
        material = cast("_MaterialObject", source).ShapeMaterial
        cast("_MaterialObject", target).ShapeMaterial = material
    if hasattr(source, GRAIN_PROP):
        if not hasattr(target, GRAIN_PROP):
            target.addProperty(
                source.getTypeIdOfProperty(GRAIN_PROP),
                GRAIN_PROP,
                source.getGroupOfProperty(GRAIN_PROP),
            )
        cast("_GrainObject", target).Grain = list(cast("_GrainObject", source).Grain)
    source_view = _appearance_view(source)
    target_view = _appearance_view(target)
    if source_view is not None and target_view is not None:
        target_view.ShapeAppearance = list(source_view.ShapeAppearance)


def paint(obj: FreeCAD.DocumentObject, rgb: Color) -> None:
    """Give every face of ``obj`` the diffuse color ``rgb`` (0 to 255 per
    channel), keeping the rest of its appearance. Does nothing without a GUI.
    """
    view = _appearance_view(obj)
    if view is None:
        return
    appearance = view.ShapeAppearance[0]
    appearance.DiffuseColor = (rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1.0)
    view.ShapeAppearance = [appearance]
