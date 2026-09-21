"""Read and write a FreeCAD container against the core scanner's records.

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
box becomes a plain ``Box``, sized from ``Shape.BoundBox`` rather than from
``Length`` / ``Width`` / ``Height`` so a box rotated a quarter turn still
reads correctly. A single-solid, axis-aligned part that is not a plain box
(a notched panel) becomes a ``Box`` with ``irregular=True``, its bounding
box standing in for the shape scanning cannot regenerate. Only a part with
no solid, several solids, or a solid that is not axis-aligned (its bounding
box would not describe the space it actually occupies) is reported in
``Skipped`` with the reason instead.

``write_container`` is the inverse: given a solved ``Unit``, it reconciles a
container's ``Part::Box`` children against the unit's boards by document
object ``Name``, updating what matches, creating what does not, and deleting
only what this workbench tagged and the tree no longer names. See
``write_container``'s own docstring and this repo's ``sh-018`` task file for
the identity and provenance rules it follows.
"""

import dataclasses
from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import Part

from freecad.Shelving import properties
from freecad.Shelving.core.expand import BoardSpec, expand
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Axis, Board, Division, Item, Region, Unit
from freecad.Shelving.core.materials import Catalog
from freecad.Shelving.core.record import rules_to_json
from freecad.Shelving.core.scan import Box, Skipped, elevation_axes

# A PartDesign Body also exposes a Group, holding that body's own feature
# history rather than separate parts, so it is deliberately absent here.
_CONTAINERS = ("App::Part", "App::LinkGroup", "App::DocumentObjectGroup")

_BOX_FACE_COUNT = 6
_VOLUME_TOL_MM3 = 1e-6
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


@dataclasses.dataclass(frozen=True)
class ContainerRecord:
    """``obj``'s own stored properties, read back by :func:`read_container`.

    Each of the first four fields is ``None`` when its property was never
    written (an untouched container, or one from before this workbench wrote
    it). A determined-but-unknown ``front_at_min`` reads back as ``None``
    too: ``Unit.front_at_min`` itself does not distinguish "never
    determined" from "determined to be undetermined"; see
    ``freecad.Shelving.properties.read_container_facing``. ``copied`` names
    every board whose own provenance marks it a copy of another
    (``freecad.Shelving.properties.is_copy``); a caller drops a copy's stored
    identity and treats it as new geometry rather than as a continuation of
    the board it was copied from.
    """

    unit_id: str | None
    depth_axis: Axis | None
    front_at_min: bool | None
    rules_json: str | None
    copied: frozenset[str]


def read_container(
    obj: FreeCAD.DocumentObject,
) -> tuple[list[Box], list[Skipped], ContainerRecord]:
    """The core's ``Box`` records read from every leaf part under ``obj``,
    a ``Skipped`` record for each part that could not be read at all, and
    ``obj``'s own :class:`ContainerRecord`.

    ``obj`` is the selected container; its own placement never applies to
    the records, only the placements of any container nested beneath it.
    """
    boxes: list[Box] = []
    skipped: list[Skipped] = []
    copied: set[str] = set()
    seen: set[str] = set()
    doc = obj.Document
    for child in _children(obj):
        for leaf, placement in _walk(child, FreeCAD.Placement(), seen):
            shape = _shape(leaf)
            placed_shape = (
                _placed_shape(shape, placement) if shape is not None else None
            )
            classification = _classify(placed_shape)
            if classification.skip_reason is not None:
                skipped.append(
                    Skipped(
                        name=leaf.Name,
                        label=leaf.Label,
                        type=leaf.TypeId,
                        reason=classification.skip_reason,
                    )
                )
                continue
            # skip_reason is only None when placed_shape is present and
            # axis-aligned.
            assert placed_shape is not None
            bound = placed_shape.BoundBox
            boxes.append(
                Box(
                    name=leaf.Name,
                    corner_mm=Vec3(bound.XMin, bound.YMin, bound.ZMin),
                    size_mm=Vec3(bound.XLength, bound.YLength, bound.ZLength),
                    irregular=classification.irregular,
                    material=properties.read_board_material(leaf),
                )
            )
            if properties.is_copy(leaf, doc):
                copied.add(leaf.Name)
    record = ContainerRecord(
        unit_id=properties.read_container_unit_id(obj),
        depth_axis=properties.read_container_depth_axis(obj),
        front_at_min=properties.read_container_facing(obj),
        rules_json=properties.read_container_rules_json(obj),
        copied=frozenset(copied),
    )
    return boxes, skipped, record


def _shape(obj: FreeCAD.DocumentObject) -> Part.Shape | None:
    shape = getattr(obj, "Shape", None)
    return shape if isinstance(shape, Part.Shape) else None


def _placed_shape(shape: Part.Shape, placement: FreeCAD.Placement) -> Part.Shape:
    """``shape`` already carries the leaf's own placement, which FreeCAD
    bakes into ``obj.Shape``, with the ancestor containers' composed
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


@dataclasses.dataclass(frozen=True)
class _Classification:
    """What ``read_container`` should do with one leaf part: adopt it as a
    plain board, adopt it as an irregular one (``irregular=True``), or skip
    it with ``skip_reason`` naming why."""

    skip_reason: str | None
    irregular: bool


_PLAIN = _Classification(skip_reason=None, irregular=False)
_IRREGULAR = _Classification(skip_reason=None, irregular=True)


def _classify(shape: Part.Shape | None) -> _Classification:
    """How ``read_container`` should treat a leaf whose placed solid is
    ``shape``: a plain box, an irregular one, or unreadable.

    A part with no solid, several solids, or a solid that is not
    axis-aligned is unreadable: there is no single bounding box that
    faithfully describes the space it occupies (a skewed box's axis-aligned
    bounding box is larger than the solid itself, and several solids have no
    one box to report at all). Anything else, one axis-aligned solid, plain
    box or not, gets a bounding box that does describe its footprint, so a
    non-box shape (a notched panel) is adopted as irregular rather than
    skipped: its measured extent becomes ``Board.pinned_size_mm`` for the
    solver to verify rather than derive.

    ``shape`` is the leaf's solid already placed in the selected container's
    frame (the leaf's own placement composed with any nested containers'),
    so the axis-alignment check here catches a leaf whose own geometry is a
    plain box but which a nested container's non-90-degree rotation carries
    out of alignment, not only a leaf that is skewed on its own.
    """
    if shape is None or shape.isNull() or shape.Volume <= _VOLUME_TOL_MM3:
        return _Classification(skip_reason="carries no solid", irregular=False)
    solids = shape.Solids
    if not solids:
        return _Classification(skip_reason="carries no solid", irregular=False)
    if len(solids) > 1:
        return _Classification(
            skip_reason=(
                f"holds {len(solids)} solids, such as a Draft array; its source "
                "object is exported separately, so its copies are missing"
            ),
            irregular=False,
        )
    if not _axis_aligned(shape):
        return _Classification(skip_reason="not axis-aligned", irregular=False)
    bound = shape.BoundBox
    bbox_volume_mm3 = bound.XLength * bound.YLength * bound.ZLength
    if len(shape.Faces) == _BOX_FACE_COUNT and _close_volume(
        shape.Volume, bbox_volume_mm3
    ):
        return _PLAIN
    return _IRREGULAR


# ---------------------------------------------------------------------------
# write_container
# ---------------------------------------------------------------------------


class _Placeable(Protocol):
    """A ``DocumentObject`` with a settable ``Placement``: every leaf this
    module writes."""

    Placement: FreeCAD.Placement
    Label: str


class _BoxFeature(_Placeable, Protocol):
    """The ``Part::Box`` property surface ``write_container`` writes."""

    Length: float
    Width: float
    Height: float


@dataclasses.dataclass(frozen=True)
class WriteResult:
    """The document object ``Name`` of every board ``write_container``
    touched, or declined to, in one call.

    ``created`` also holds a matched board adopted from a copy (see
    ``freecad.Shelving.properties.is_copy``): the same document object as
    before the call, but re-baptized with a fresh provenance and label, so
    it is reported the way a user would think of it, as a new board, not as
    an update to the board it was copied from.
    """

    updated: tuple[str, ...]
    created: tuple[str, ...]
    deleted: tuple[str, ...]
    left_alone: tuple[str, ...]


def _boards_by_id(region: Region) -> dict[str, Board]:
    if not isinstance(region, Division):
        return {}
    out: dict[str, Board] = {}
    for item in region.items:
        if isinstance(item, Board):
            out[item.id] = item
        else:
            out.update(_boards_by_id(item))
    return out


def _existing_leaves(
    container: FreeCAD.DocumentObject,
) -> dict[str, FreeCAD.DocumentObject]:
    """Every leaf part already under ``container``, by ``Name``, at any
    nesting depth: what ``read_container`` would also read as boards or
    skip, the set ``write_container`` reconciles against."""
    leaves: dict[str, FreeCAD.DocumentObject] = {}
    seen: set[str] = set()
    for child in _children(container):
        for leaf, _placement in _walk(child, FreeCAD.Placement(), seen):
            leaves[leaf.Name] = leaf
    return leaves


_AXIS_VECTORS: dict[Axis, tuple[int, int, int]] = {
    Axis.X: (1, 0, 0),
    Axis.Y: (0, 1, 0),
    Axis.Z: (0, 0, 1),
}


def _cross3(a: tuple[int, int, int], b: tuple[int, int, int]) -> tuple[int, int, int]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _right_sign(
    depth_axis: Axis, vertical_axis: Axis, horizontal_axis: Axis, front_at_min: bool
) -> int:
    """``1`` when the horizontal axis's maximum end is the viewer's right,
    ``-1`` when its minimum end is.

    Standing at the front looking into the unit, "right" is ``forward ×
    up`` by the right-hand rule; ``forward`` is ``+depth_axis`` when the
    front is at the depth axis's minimum end (``front_at_min``) and
    ``-depth_axis`` otherwise, since facing the opposite end of the unit
    mirrors which physical direction "right" points without changing either
    axis. The result is always aligned with ``horizontal_axis``, since
    ``forward`` and ``up`` are the other two axes of an orthonormal frame.
    """
    forward = _AXIS_VECTORS[depth_axis]
    if not front_at_min:
        forward = (-forward[0], -forward[1], -forward[2])
    up = _AXIS_VECTORS[vertical_axis]
    cross = _cross3(forward, up)
    horizontal = _AXIS_VECTORS[horizontal_axis]
    dot = sum(c * h for c, h in zip(cross, horizontal, strict=True))
    assert dot in (1, -1), (depth_axis, vertical_axis, horizontal_axis, cross)
    return dot


def _label_for_board(
    division_axis: Axis,
    index: int,
    last_index: int,
    horizontal_axis: Axis,
    vertical_axis: Axis,
    right_sign: int | None,
    counters: dict[str, int],
) -> str:
    """The generated ``Label`` for a ``Board`` at ``index`` of ``last_index``
    in a division cut along ``division_axis``. See this task's Frontier
    Advice for the naming rule; ``counters`` is shared and mutated across
    one call to :func:`_derive_labels`, so "Shelf N" / "Divider N" number
    sequentially across the whole tree rather than per division.
    """
    is_edge = index == 0 or index == last_index
    if division_axis == vertical_axis:
        if is_edge:
            return "Bottom" if index == 0 else "Top"
        counters["shelf"] += 1
        return f"Shelf {counters['shelf']}"
    if division_axis == horizontal_axis:
        if is_edge:
            at_max = index == last_index
            if right_sign is None:
                return "Side 1" if index == 0 else "Side 2"
            is_right = (right_sign == 1) == at_max
            return "Right Side" if is_right else "Left Side"
        counters["divider"] += 1
        return f"Divider {counters['divider']}"
    # A division cut along the depth axis: neither scan() nor create_unit's
    # fixed shape ever produces one, since scanning only ever divides the
    # elevation plane. Kept generic, rather than raising, so a hand-built
    # Unit that does use one still gets a usable label instead of an
    # exception from deep inside a write.
    if is_edge:
        return "Front" if index == 0 else "Back"
    counters["shelf"] += 1
    return f"Shelf {counters['shelf']}"


def _walk_labels(
    region: Region,
    horizontal_axis: Axis,
    vertical_axis: Axis,
    right_sign: int | None,
    counters: dict[str, int],
    labels: dict[str, str],
) -> None:
    if not isinstance(region, Division):
        return
    items = region.items
    last_index = len(items) - 1
    for index, item in enumerate(items):
        if isinstance(item, Board):
            labels[item.id] = _label_for_board(
                region.axis,
                index,
                last_index,
                horizontal_axis,
                vertical_axis,
                right_sign,
                counters,
            )
        else:
            _walk_labels(
                item, horizontal_axis, vertical_axis, right_sign, counters, labels
            )


def _derive_labels(unit: Unit) -> dict[str, str]:
    """A generated ``Label`` for every ``Board`` in ``unit``, by id.

    ``write_container`` applies this only to a board it creates or adopts
    from a copy; every other board keeps whatever ``Label`` it already
    carries, per this task's "labels are generated at creation only" rule.
    """
    depth_axis = unit.depth_axis if unit.depth_axis is not None else Axis.Y
    horizontal_axis, vertical_axis = elevation_axes(depth_axis)
    right_sign = (
        _right_sign(depth_axis, vertical_axis, horizontal_axis, unit.front_at_min)
        if unit.front_at_min is not None
        else None
    )
    labels: dict[str, str] = {}
    _walk_labels(
        unit.root,
        horizontal_axis,
        vertical_axis,
        right_sign,
        {"shelf": 0, "divider": 0},
        labels,
    )
    return labels


def _sanitize_name(role: str) -> str:
    """``role`` cut down to the identifier-only characters a FreeCAD object
    ``Name`` accepts (letters, digits, underscore), or ``""`` when nothing
    survives; ``doc.addObject`` treats an empty or colliding name as a hint
    and assigns a fresh one, so this never has to be unique itself."""
    cleaned = "".join(c if c.isalnum() or c == "_" else "_" for c in role).strip("_")
    if cleaned and cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _renamed_board_ids(region: Region, renames: dict[str, str]) -> Region:
    """``region`` with every ``Board.id`` present in ``renames`` replaced by
    its mapped value; every other board and every region's own id is
    untouched. See ``write_container``'s ``id_renames`` comment for why this
    runs before ``rules_to_json``."""
    if not isinstance(region, Division):
        return region
    new_items: list[Item] = []
    for item in region.items:
        if isinstance(item, Board):
            new_name = renames.get(item.id)
            new_items.append(
                dataclasses.replace(item, id=new_name) if new_name is not None else item
            )
        else:
            new_items.append(_renamed_board_ids(item, renames))
    return dataclasses.replace(region, items=new_items)


def _write_geometry(obj: FreeCAD.DocumentObject, spec: BoardSpec, board: Board) -> None:
    """Place ``obj`` at ``spec.placement``, and size it to ``spec.size``
    unless ``board`` is pinned: sh-017's solver already verified a pinned
    board's derived size against its measured extent, so this only ever
    moves one, never resizes or recreates its shape."""
    placeable = cast("_Placeable", obj)
    placeable.Placement = FreeCAD.Placement(
        FreeCAD.Vector(spec.placement.x_mm, spec.placement.y_mm, spec.placement.z_mm),
        FreeCAD.Rotation(),
    )
    if board.pinned_size_mm is None:
        box = cast("_BoxFeature", obj)
        box.Length = spec.size.x_mm
        box.Width = spec.size.y_mm
        box.Height = spec.size.z_mm


def _create_board(
    doc: FreeCAD.Document,
    container: FreeCAD.DocumentObject,
    spec: BoardSpec,
    board: Board,
    label: str,
) -> FreeCAD.DocumentObject:
    raw = doc.addObject("Part::Box", _sanitize_name(board.role) or "Board")
    obj = cast("FreeCAD.DocumentObject", raw)
    cast("FreeCAD.DocumentObjectGroup", container).addObject(obj)
    _write_geometry(obj, spec, board)
    tagged = properties.ensure_board_properties(obj)
    properties.write_board_material(tagged, board.material)
    properties.write_board_irregular(tagged, board.pinned_size_mm is not None)
    properties.write_board_born_as(tagged, obj.Name)
    properties.write_board_born_in(tagged, doc.Uid)
    cast("_Placeable", obj).Label = label
    return obj


def write_container(
    container: FreeCAD.DocumentObject, unit: Unit, catalog: Catalog
) -> WriteResult:
    """Reconcile ``container``'s ``Part::Box`` children against ``unit``.

    A board matches an existing object by its ``Board.id`` equalling the
    object's ``Name`` (set that way by ``read_container`` and
    ``freecad.Shelving.core.scan.scan``). A match is written in place: its
    geometry always, and, if this is the first time this call finds it
    carrying no provenance (a part a user built directly and positioned
    into a valid slot in the layout, such as a hand-modelled irregular
    board) or its provenance marks it a copy, a fresh label and provenance
    too, reported in ``WriteResult.created`` alongside a genuinely new
    object since the workbench is adopting it for the first time either
    way. A board with no match is created and tagged the same way. An
    object that carries provenance and is NOT matched is deleted, its
    layout entry gone; one that matches nothing and carries no provenance
    either is left exactly alone, reported in ``WriteResult.left_alone``.
    The scanner routes an object away from ever matching anything at all
    (a panel set aside by ``freecad.Shelving.core.scan.scan``, or a part
    ``read_container`` could not read) when it has no defensible place in
    the tree, which is what actually keeps stray geometry untouched;
    "carries no provenance" alone does not. Writes ``container``'s own
    four properties, including the rule record from
    ``freecad.Shelving.core.record.rules_to_json``. Opens no transaction;
    the caller owns that.
    """
    doc = container.Document
    specs = expand(unit, catalog)
    boards_by_id = _boards_by_id(unit.root)
    labels = _derive_labels(unit)
    existing = _existing_leaves(container)
    matched_names: set[str] = set()
    # A board created in this call keeps whatever id `unit` gave it (a fresh
    # uuid for a hand-built Unit, since nothing has scanned it from a real
    # object yet); the stored rule record has to be keyed by the real
    # FreeCAD Name a rescan will read back, so every such id is remapped to
    # the object's actual Name before rules_to_json runs below. A matched
    # board needs no entry: its id already equals its object's Name, or
    # write_container would not have matched it.
    id_renames: dict[str, str] = {}

    updated: list[str] = []
    created: list[str] = []
    for spec in specs:
        board = boards_by_id[spec.node_id]
        obj = existing.get(spec.node_id)
        if obj is None:
            new_obj = _create_board(doc, container, spec, board, labels[spec.node_id])
            if new_obj.Name != spec.node_id:
                id_renames[spec.node_id] = new_obj.Name
            created.append(new_obj.Name)
            continue
        matched_names.add(obj.Name)
        # A match overrides "never touch an untagged object": being named by
        # the tree is exactly what makes an object part of the layout. Only
        # an object the tree does not name is untouchable, which is decided
        # below, once, for everything the loop above left unmatched.
        adopting = not properties.has_board_properties(obj) or properties.is_copy(
            obj, doc
        )
        _write_geometry(obj, spec, board)
        tagged = properties.ensure_board_properties(obj)
        properties.write_board_material(tagged, board.material)
        properties.write_board_irregular(tagged, board.pinned_size_mm is not None)
        if adopting:
            properties.write_board_born_as(tagged, obj.Name)
            properties.write_board_born_in(tagged, doc.Uid)
            cast("_Placeable", obj).Label = labels[spec.node_id]
            created.append(obj.Name)
        else:
            updated.append(obj.Name)

    rules_unit = (
        dataclasses.replace(unit, root=_renamed_board_ids(unit.root, id_renames))
        if id_renames
        else unit
    )
    container_props = properties.ensure_container_properties(container)
    properties.write_container_unit_id(container_props, unit.id)
    properties.write_container_depth_axis(container_props, unit.depth_axis)
    properties.write_container_facing(container_props, unit.front_at_min)
    properties.write_container_rules_json(container_props, rules_to_json(rules_unit))

    deleted: list[str] = []
    left_alone: list[str] = []
    for name, obj in existing.items():
        if name in matched_names:
            # Every matched object was just tagged above, adopted or not, so
            # there is nothing left to classify here.
            continue
        if properties.has_board_properties(obj):
            doc.removeObject(name)
            deleted.append(name)
        else:
            left_alone.append(name)

    return WriteResult(
        updated=tuple(sorted(updated)),
        created=tuple(sorted(created)),
        deleted=tuple(sorted(deleted)),
        left_alone=tuple(sorted(left_alone)),
    )
