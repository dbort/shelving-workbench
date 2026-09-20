"""Read a FreeCAD container into the core scanner's ``Box``/``Skipped`` records.

``read_container`` walks a selected ``App::Part``, ``App::LinkGroup``, or
``App::DocumentObjectGroup``, descending only into those three types: a
``PartDesign::Body`` or a boolean exposes its feature history through
``Group`` too, and descending into one would read its sketch and its pad as
if they were boards. Each leaf's placement is composed from the containers
between it and the selected container, excluding the selected container's
own placement, so a unit moved or rotated in a room reads identically to the
same unit at the origin. ``getGlobalPlacement`` is not usable for this: it
composes only through geo-feature groups, and an ``App::LinkGroup`` is not
one, so the chain is composed by hand.

A leaf's solid decides whether it is read as a board: a plain axis-aligned
box becomes a ``Box``, sized from ``Shape.BoundBox`` rather than from
``Length`` / ``Width`` / ``Height`` so a box rotated a quarter turn still
reads correctly. Anything else, not axis-aligned, a box minus rectangular
cutouts, no solid, or several solids, is reported in ``Skipped`` with the
reason rather than adopted: a part read as a board needs a pinned flag that
lets its size drive its region, which this task does not add.
"""

from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import Part

from freecad.shelving.vendor.shelving_core.geometry import Vec3
from freecad.shelving.vendor.shelving_core.scan import Box, Skipped

# A PartDesign Body also exposes a Group, holding that body's own feature
# history rather than separate parts, so it is deliberately absent here.
_CONTAINERS = ("App::Part", "App::LinkGroup", "App::DocumentObjectGroup")

_BOX_FACE_COUNT = 6
_VOLUME_TOL_MM3 = 1e-6
_MIN_EXTENT_MM = 1e-6
_NORMAL_TOL = 1e-6


class _ContainerObject(Protocol):
    """The property surface ``_children`` reads to find a container's
    members: ``Group`` (``App::Part``, ``App::DocumentObjectGroup``) or
    ``ElementList`` (``App::LinkGroup``, which ``freecad-stubs`` does not
    type at all). No container type carries both, so ``_children`` still
    probes with ``getattr`` rather than assuming either is present."""

    Group: list[FreeCAD.DocumentObject]
    ElementList: list[FreeCAD.DocumentObject]


def _children(obj: FreeCAD.DocumentObject) -> list[FreeCAD.DocumentObject]:
    if not any(obj.isDerivedFrom(kind) for kind in _CONTAINERS):
        return []
    container = cast("_ContainerObject", obj)
    # LinkGroup children live in ElementList, Part and plain groups use
    # Group; neither attribute exists on every container type, so this
    # reads whichever one the concrete object carries.
    for attr in ("ElementList", "Group"):
        members = getattr(container, attr, None)
        if isinstance(members, list):
            return [m for m in members if isinstance(m, FreeCAD.DocumentObject)]
    return []


def _walk(
    obj: FreeCAD.DocumentObject, placement: FreeCAD.Placement, seen: set[str]
) -> Iterator[tuple[FreeCAD.DocumentObject, FreeCAD.Placement]]:
    """Every leaf part under ``obj``, paired with the placement composed from
    ``obj`` downward.

    Deduplicates by document object name: a selection reaching the same
    object by two paths through the container tree must yield it once. The
    caller is responsible for not calling this on the selected container
    itself, which is how the container's own placement stays excluded while
    every nested container's placement still composes.
    """
    children = _children(obj)
    if not children:
        if obj.Name not in seen:
            seen.add(obj.Name)
            yield obj, placement
        return
    # An App::DocumentObjectGroup carries no Placement at all (it is a plain
    # group, not a geo-feature group), so this stays defensive rather than
    # assuming every container type has one.
    own = getattr(obj, "Placement", None)
    composed = (
        placement.multiply(own) if isinstance(own, FreeCAD.Placement) else placement
    )
    for child in children:
        yield from _walk(child, composed, seen)


def read_container(obj: FreeCAD.DocumentObject) -> tuple[list[Box], list[Skipped]]:
    """The core's ``Box`` records read from every leaf part under ``obj``,
    plus a ``Skipped`` record for each part whose solid could not be read as
    a plain axis-aligned board.

    ``obj`` is the selected container; its own placement never applies to
    the records, only the placements of any container nested beneath it.
    """
    boxes: list[Box] = []
    skipped: list[Skipped] = []
    seen: set[str] = set()
    for child in _children(obj):
        for leaf, placement in _walk(child, FreeCAD.Placement(), seen):
            shape = _shape(leaf)
            placed_shape = (
                _placed_shape(shape, placement) if shape is not None else None
            )
            reason = _skip_reason(leaf, placed_shape)
            if reason is not None:
                skipped.append(
                    Skipped(
                        name=leaf.Name,
                        label=leaf.Label,
                        type=leaf.TypeId,
                        reason=reason,
                    )
                )
                continue
            # A None reason only comes out of _skip_reason when placed_shape
            # is present and axis-aligned.
            assert placed_shape is not None
            bound = placed_shape.BoundBox
            boxes.append(
                Box(
                    name=leaf.Name,
                    corner_mm=Vec3(bound.XMin, bound.YMin, bound.ZMin),
                    size_mm=Vec3(bound.XLength, bound.YLength, bound.ZLength),
                )
            )
    return boxes, skipped


def _shape(obj: FreeCAD.DocumentObject) -> Part.Shape | None:
    shape = getattr(obj, "Shape", None)
    return shape if isinstance(shape, Part.Shape) else None


def _placed_shape(shape: Part.Shape, placement: FreeCAD.Placement) -> Part.Shape:
    """``shape`` (already carrying the leaf's own placement, which FreeCAD
    bakes into ``obj.Shape``) with the ancestor containers' composed
    ``placement`` applied on top, so its ``BoundBox`` is tight in the
    selected container's frame rather than the leaf's immediate parent's.

    A corner-only transform is not equivalent: a nested container's rotation
    swaps which axis an extent belongs to, which only a transform of the
    whole shape gets right.
    """
    placed = shape.copy()
    placed.Placement = placement.multiply(placed.Placement)
    return placed


def _axis_aligned(shape: Part.Shape) -> bool:
    """Whether every face of ``shape`` is planar with a normal along X, Y, or Z."""
    for face in shape.Faces:
        surface = face.Surface
        if not isinstance(surface, Part.Plane):
            return False
        axis = surface.Axis
        components = sorted(abs(c) for c in (axis.x, axis.y, axis.z))
        if abs(components[2] - 1.0) > _NORMAL_TOL or components[1] > _NORMAL_TOL:
            return False
    return True


def _close_volume(volume_mm3: float, bbox_volume_mm3: float) -> bool:
    return abs(volume_mm3 - bbox_volume_mm3) <= max(
        1e-6 * bbox_volume_mm3, _VOLUME_TOL_MM3
    )


def _is_box_piece(piece: Part.Shape) -> bool:
    bound = piece.BoundBox
    bbox_volume_mm3 = bound.XLength * bound.YLength * bound.ZLength
    return (
        len(piece.Faces) == _BOX_FACE_COUNT
        and _axis_aligned(piece)
        and _close_volume(piece.Volume, bbox_volume_mm3)
    )


def _piece_size_label(piece: Part.Shape) -> str:
    bound = piece.BoundBox
    return f"{bound.XLength:g} x {bound.YLength:g} x {bound.ZLength:g} mm"


def _bbox_solid(bound: FreeCAD.BoundBox) -> Part.Shape:
    return Part.makeBox(
        max(bound.XLength, _MIN_EXTENT_MM),
        max(bound.YLength, _MIN_EXTENT_MM),
        max(bound.ZLength, _MIN_EXTENT_MM),
        FreeCAD.Vector(bound.XMin, bound.YMin, bound.ZMin),
    )


def _skip_reason(obj: FreeCAD.DocumentObject, shape: Part.Shape | None) -> str | None:
    """``None`` for a plain axis-aligned box; otherwise why ``read_container``
    cannot adopt ``obj`` as a board: a box minus N rectangular cutouts, not
    axis-aligned, carries no solid, or holds N solids.

    ``shape`` is ``obj``'s solid already placed in the selected container's
    frame (the leaf's own placement composed with any nested containers'), so
    the axis-alignment check below catches a leaf whose own geometry is a
    plain box but which a nested container's non-90-degree rotation carries
    out of alignment, not only a leaf that is skewed on its own.
    """
    if shape is None or shape.isNull() or shape.Volume <= _VOLUME_TOL_MM3:
        return "carries no solid"
    solids = shape.Solids
    if not solids:
        return "carries no solid"
    if len(solids) > 1:
        return (
            f"holds {len(solids)} solids, such as a Draft array; its source "
            "object is exported separately, so its copies are missing"
        )
    if not _axis_aligned(shape):
        return "not axis-aligned"
    bound = shape.BoundBox
    bbox_volume_mm3 = bound.XLength * bound.YLength * bound.ZLength
    if len(shape.Faces) == _BOX_FACE_COUNT and _close_volume(
        shape.Volume, bbox_volume_mm3
    ):
        return None
    try:
        # Subtracting the solid from its own bounding box tells a
        # plank-plus-cutouts part from an irregular one.
        leftover = _bbox_solid(bound).cut(shape)
    except Exception:  # noqa: BLE001 - a pathological solid must not break a scan
        return f"a {obj.TypeId}, not a plain box"
    pieces = leftover.Solids
    if pieces and all(_is_box_piece(piece) for piece in pieces):
        sizes = ", ".join(_piece_size_label(piece) for piece in pieces)
        return f"a box minus {len(pieces)} rectangular cutout(s): {sizes}"
    return f"a {obj.TypeId}, not a plain box or a box with rectangular cutouts"
