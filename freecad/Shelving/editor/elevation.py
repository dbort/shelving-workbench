"""What the in-view editor draws over a unit, worked out in the unit's own
frame with no document, no Qt and no Coin.

Everything lies in one elevation frame: h along the elevation's horizontal,
v along its vertical, z toward the camera, origin at the unit's lower left
corner on the face the camera sees. ``SoDatumLabel`` lays its text out in
its local XY plane only, which is what forces that frame, and it turns
picking an opening into a ray meeting z = 0.
"""

from __future__ import annotations

import math
import os
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

from freecad.Shelving.core.edit import (
    EditError,
    Held,
    held_by,
    measure,
    region_before,
    run_axis,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    ConstraintId,
    Division,
    Equal,
    FixedSide,
    Insets,
    Lock,
    Region,
    Unit,
    Void,
    constraint_regions,
    owner_along,
    parent_divisions,
    region_lock,
)
from freecad.Shelving.core.scan import elevation_axes

Side = Literal["front", "back"]
FaceKind = Literal["bay", "void"]
# "constrained" outlines a fully constrained board, as the Sketcher colors
# a fully constrained edge.
OutlineRole = Literal["region", "selected", "holding", "constrained"]
# A driving dimension is an active Lock's, a deactivated one a deactivated
# Lock's, and a reference one shows a size nothing locks.
LabelRole = Literal["driving", "deactivated", "reference"]
# The elevation direction Lock Width or Lock Height acts along.
ElevationDirection = Literal["horizontal", "vertical"]
ConstraintKind = Literal["equal", "even_spacing"]

# The workbench's own icons in the Sketcher's constraint style. Drawing
# Equal as well as Even spacing keeps the pair matched and spares
# importing SketcherGui, whose import alone registers the Sketcher's icons
# (.claude/docs/freecad-notes.md).
_RESOURCES = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
ICON_SOURCES: Mapping[ConstraintKind, str] = {
    "equal": os.path.join(_RESOURCES, "Constraint_Equal.svg"),
    "even_spacing": os.path.join(_RESOURCES, "Constraint_EvenSpacing.svg"),
}
# Equal Width's and Equal Height's command icons and the constraint list
# rows' icons, Even Width and Even Height rows included, by the constraint
# and the elevation direction it holds sizes along. The view and the Even
# Spacing command draw the axis-free icons above: the dimension line an
# icon sits on already shows the direction, and the command's picks give
# it.
AXIS_ICON_SOURCES: Mapping[tuple[ConstraintKind, ElevationDirection], str] = {
    ("equal", "horizontal"): os.path.join(_RESOURCES, "Constraint_EqualWidth.svg"),
    ("equal", "vertical"): os.path.join(_RESOURCES, "Constraint_EqualHeight.svg"),
    ("even_spacing", "horizontal"): os.path.join(
        _RESOURCES, "Constraint_EvenWidth.svg"
    ),
    ("even_spacing", "vertical"): os.path.join(_RESOURCES, "Constraint_EvenHeight.svg"),
}
# Lock Width's and Lock Height's icons, after the Sketcher's horizontal and
# vertical distance constraints'.
LOCK_ICON_SOURCES: Mapping[ElevationDirection, str] = {
    "horizontal": os.path.join(_RESOURCES, "Constraint_HorizontalDistance.svg"),
    "vertical": os.path.join(_RESOURCES, "Constraint_VerticalDistance.svg"),
}
# Add Shelf's and Add Divider's icons, keyed by the elevation direction
# the split runs along, as the editor's split takes it.
ADD_ICON_SOURCES: Mapping[ElevationDirection, str] = {
    "vertical": os.path.join(_RESOURCES, "Shelving_AddShelf.svg"),
    "horizontal": os.path.join(_RESOURCES, "Shelving_AddDivider.svg"),
}

# How far in front of the face outlines and dimensions sit, so they do not
# z-fight with the board faces they lie on. Opening faces sit on the face
# itself: the fronts of the boards around an opening never overlap it.
LIFT_MM = 0.5
# The drag arrow's length, as a fraction of the unit's longer elevation side.
_ARROW_FRACTION = 0.08
_EPSILON_MM = 1e-6


class Rect(NamedTuple):
    """An axis-aligned rectangle in elevation millimeters."""

    h0_mm: float
    v0_mm: float
    h1_mm: float
    v1_mm: float

    def contains(self, h_mm: float, v_mm: float) -> bool:
        return self.h0_mm <= h_mm <= self.h1_mm and self.v0_mm <= v_mm <= self.v1_mm

    @property
    def center_mm(self) -> tuple[float, float]:
        return ((self.h0_mm + self.h1_mm) / 2, (self.v0_mm + self.v1_mm) / 2)


def _unit_vector(axis: Axis, sign: float = 1.0) -> Vec3:
    components = [0.0, 0.0, 0.0]
    components[axis.component_index] = sign
    return Vec3(*components)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return Vec3(
        a.y_mm * b.z_mm - a.z_mm * b.y_mm,
        a.z_mm * b.x_mm - a.x_mm * b.z_mm,
        a.x_mm * b.y_mm - a.y_mm * b.x_mm,
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a.x_mm * b.x_mm + a.y_mm * b.y_mm + a.z_mm * b.z_mm


def _scaled(a: Vec3, factor: float) -> Vec3:
    return Vec3(a.x_mm * factor, a.y_mm * factor, a.z_mm * factor)


def _sum(*vectors: Vec3) -> Vec3:
    return Vec3(
        sum(v.x_mm for v in vectors),
        sum(v.y_mm for v in vectors),
        sum(v.z_mm for v in vectors),
    )


@dataclass(frozen=True)
class ElevationFrame:
    """The elevation frame on one face of a unit, in the unit's frame."""

    horizontal: Axis
    vertical: Axis
    side: Side
    # Unit-frame unit vectors along the elevation's h, v and z: z is the
    # front face's outward normal on either face, so the frame on the back
    # face is the same rotation and draws at negative z.
    h_dir: Vec3
    v_dir: Vec3
    z_dir: Vec3
    # The unit-frame point at elevation (0, 0, 0).
    origin_mm: Vec3

    @property
    def z_sign(self) -> float:
        """+1 on the front face, -1 on the back: the sign of z toward the
        camera."""
        return 1.0 if self.side == "front" else -1.0

    def to_unit(self, h_mm: float, v_mm: float, z_mm: float = 0.0) -> Vec3:
        return _sum(
            self.origin_mm,
            _scaled(self.h_dir, h_mm),
            _scaled(self.v_dir, v_mm),
            _scaled(self.z_dir, z_mm),
        )

    def from_unit(self, point_mm: Vec3) -> tuple[float, float, float]:
        """``point_mm`` as elevation ``(h, v, z)`` millimeters."""
        offset = _sum(point_mm, _scaled(self.origin_mm, -1.0))
        return (
            _dot(offset, self.h_dir),
            _dot(offset, self.v_dir),
            _dot(offset, self.z_dir),
        )

    def rect(self, space: Space) -> Rect:
        """``space`` projected onto the elevation plane."""
        h0_mm, v0_mm, _ = self.from_unit(space.origin)
        h1_mm, v1_mm, _ = self.from_unit(space.max_corner())
        return Rect(
            min(h0_mm, h1_mm), min(v0_mm, v1_mm), max(h0_mm, h1_mm), max(v0_mm, v1_mm)
        )

    def matrix(self) -> tuple[float, ...]:
        """The frame as a row-major 4x4 matrix from elevation to unit
        coordinates, the order ``FreeCAD.Matrix`` takes."""
        h, v, z, o = self.h_dir, self.v_dir, self.z_dir, self.origin_mm
        return (
            h.x_mm, v.x_mm, z.x_mm, o.x_mm,
            h.y_mm, v.y_mm, z.y_mm, o.y_mm,
            h.z_mm, v.z_mm, z.z_mm, o.z_mm,
            0.0, 0.0, 0.0, 1.0,
        )  # fmt: skip


def elevation_frame(unit: Unit, side: Side = "front") -> ElevationFrame:
    """The frame on ``unit``'s front face, or on its back face with the same
    axes. The front is the end of the depth axis ``unit.front_at_min``
    names; when that is unknown, the side from which the elevation's
    horizontal runs along its axis's positive direction. Vertical always
    runs up its axis. Raises ``ValueError`` when the unit has no depth
    axis."""
    depth_axis = unit.depth_axis
    if depth_axis is None:
        raise ValueError(f"unit {unit.id!r} has no depth axis to draw an elevation on")
    horizontal, vertical = elevation_axes(depth_axis)
    h_dir = _unit_vector(horizontal)
    v_dir = _unit_vector(vertical)
    z_dir = _cross(h_dir, v_dir)
    depth_index = depth_axis.component_index
    toward_sign = z_dir.component_mm(depth_index)
    if unit.front_at_min is not None:
        front_sign = -1.0 if unit.front_at_min else 1.0
        if front_sign != toward_sign:
            # Seen from the real front, horizontal runs the other way.
            h_dir = _scaled(h_dir, -1.0)
            z_dir = _scaled(z_dir, -1.0)
            toward_sign = front_sign
    depth_mm = unit.size_mm.component_mm(depth_index)
    front_mm = depth_mm if toward_sign > 0 else 0.0
    face_mm = front_mm if side == "front" else depth_mm - front_mm
    position = unit.position_mm
    origin = [position.x_mm, position.y_mm, position.z_mm]
    origin[depth_index] += face_mm
    if h_dir.component_mm(horizontal.component_index) < 0:
        origin[horizontal.component_index] += unit.size_mm.component_mm(
            horizontal.component_index
        )
    return ElevationFrame(
        horizontal=horizontal,
        vertical=vertical,
        side=side,
        h_dir=h_dir,
        v_dir=v_dir,
        z_dir=z_dir,
        origin_mm=Vec3(*origin),
    )


class FixedChoice(NamedTuple):
    """One of the sides a unit's size field offers to keep put."""

    label: str
    side: FixedSide


def fixed_choices(
    unit: Unit, axis: Axis
) -> tuple[FixedChoice, FixedChoice, FixedChoice]:
    """The choices for ``axis``, in the order a size field lists them, each
    label naming its side as the front :func:`elevation_frame` shows it:
    "Left", "Center", "Right" along its horizontal, "Bottom", "Center",
    "Top" along its vertical, and "Front", "Center", "Back" along the depth
    axis, the front being the end the frame faces. Raises ``ValueError``
    when the unit has no depth axis."""
    frame = elevation_frame(unit)
    index = axis.component_index
    if axis == frame.horizontal:
        first, last = "Left", "Right"
        first_at_min = frame.h_dir.component_mm(index) > 0
    elif axis == frame.vertical:
        first, last = "Bottom", "Top"
        first_at_min = frame.v_dir.component_mm(index) > 0
    else:
        first, last = "Front", "Back"
        first_at_min = frame.z_dir.component_mm(index) < 0
    low: FixedSide = "min" if first_at_min else "max"
    high: FixedSide = "max" if first_at_min else "min"
    return (
        FixedChoice(first, low),
        FixedChoice("Center", "center"),
        FixedChoice(last, high),
    )


def _walk(
    region: Region, depth: int = 0
) -> Iterator[tuple[Region | Board, int, Division | None]]:
    """Every region and board under ``region`` with its nesting depth and
    the division it sits in, ``None`` for ``region`` itself."""
    yield region, depth, None
    if isinstance(region, Division):
        for item in region.items:
            if isinstance(item, Board):
                yield item, depth + 1, region
            else:
                for node, node_depth, parent in _walk(item, depth + 1):
                    yield node, node_depth, region if parent is None else parent


def _apply_insets(axis: Axis, space: Space, insets: Insets) -> Space:
    """``space`` with ``insets`` applied on the two axes across ``axis``.

    Mirrors :func:`freecad.Shelving.core.expand._apply_insets`; kept as its
    own copy here rather than reaching into that module's private name."""
    low = [space.origin.x_mm, space.origin.y_mm, space.origin.z_mm]
    size = [space.size.x_mm, space.size.y_mm, space.size.z_mm]
    by_axis = (
        (insets.x_min_mm, insets.x_max_mm),
        (insets.y_min_mm, insets.y_max_mm),
        (insets.z_min_mm, insets.z_max_mm),
    )
    for index, (low_mm, high_mm) in enumerate(by_axis):
        if index == axis.component_index:
            continue
        low[index] += low_mm
        size[index] -= low_mm + high_mm
    return Space(origin=Vec3(*low), size=Vec3(*size))


def board_space(unit: Unit, spaces: Mapping[str, Space], board_id: str) -> Space | None:
    """The space the board ``board_id`` fills, its insets applied; ``None``
    when ``unit`` has no such board."""
    for node, _depth, parent in _walk(unit.root):
        if isinstance(node, Board) and node.id == board_id and parent is not None:
            return _apply_insets(parent.axis, spaces[node.id], node.insets)
    return None


def board_ids(unit: Unit) -> frozenset[str]:
    """The id of every board in ``unit``."""
    return frozenset(
        node.id for node, _depth, _parent in _walk(unit.root) if isinstance(node, Board)
    )


@dataclass(frozen=True)
class Face:
    """An opening drawn as a translucent face."""

    region_id: str
    kind: FaceKind
    rect: Rect


@dataclass(frozen=True)
class Outline:
    rect: Rect
    role: OutlineRole


@dataclass(frozen=True)
class DimensionLabel:
    """One region's size, drawn as an ``SoDatumLabel`` from ``start_mm`` to
    ``end_mm``, both ``(h, v)`` elevation millimeters."""

    region_id: str
    start_mm: tuple[float, float]
    end_mm: tuple[float, float]
    # Left as a number: its text follows the user's unit system, which this
    # module, free of FreeCAD, cannot read.
    size_mm: float
    role: LabelRole
    # Where the text's center sits along the line, as a fraction from start.
    text_fraction: float
    # Whether the region's Lock is selected; a selected region leaves its
    # dimension as it is, as selecting Sketcher geometry does.
    selected: bool = False
    # The region's Lock, active or deactivated; None for a reference
    # dimension.
    lock_id: ConstraintId | None = None

    @property
    def text_at_mm(self) -> tuple[float, float]:
        """The ``(h, v)`` point the text is centered on."""
        (h0_mm, v0_mm), (h1_mm, v1_mm) = self.start_mm, self.end_mm
        return (
            h0_mm + self.text_fraction * (h1_mm - h0_mm),
            v0_mm + self.text_fraction * (v1_mm - v0_mm),
        )

    @property
    def length_mm(self) -> float:
        (h0_mm, v0_mm), (h1_mm, v1_mm) = self.start_mm, self.end_mm
        return math.hypot(h1_mm - h0_mm, v1_mm - v0_mm)

    @property
    def horizontal(self) -> bool:
        """Whether the line runs along the elevation's horizontal."""
        return self.start_mm[1] == self.end_mm[1]

    @property
    def text_shift_mm(self) -> float:
        """How far the text sits from the line's midpoint toward ``end_mm``:
        ``SoDatumLabel``'s ``param2``."""
        return (self.text_fraction - 0.5) * self.length_mm


# The first place in the row after a dimension's text; the constraint
# icons follow it in the order they were made.
FIRST_CONSTRAINT_SLOT = 0


@dataclass(frozen=True)
class ConstraintIcon:
    """One constraint's icon beside one of its openings' dimension text."""

    constraint_id: ConstraintId
    kind: ConstraintKind
    # The opening's dimension, whose text the icon sits after.
    label: DimensionLabel
    # The icon's place in the row after that text, from
    # FIRST_CONSTRAINT_SLOT.
    slot: int
    # Whether the constraint is enforced; a deactivated one's icon carries
    # a corner X.
    active: bool
    # Whether the constraint is selected; its icon takes the selection
    # color, whatever its activation.
    selected: bool


@dataclass(frozen=True)
class Overlay:
    """Everything drawn over the unit, in the order Coin draws it: faces,
    then outlines, then dimensions, then each dimension's row of constraint
    icons."""

    faces: Sequence[Face] = ()
    outlines: Sequence[Outline] = ()
    labels: Sequence[DimensionLabel] = ()
    icons: Sequence[ConstraintIcon] = ()


def icon_center_px(
    icon: ConstraintIcon,
    text_at_px: tuple[float, float],
    tile_along_px: float,
    icon_px: float,
    gap_px: float,
) -> tuple[float, float]:
    """Where ``icon``'s center goes in device pixels with y up, given where
    its dimension's text is centered and how wide the text's tile is along
    the line: past the tile's end, after ``slot`` icons before it,
    ``gap_px`` clear of the tile and of each other. Along the dimension's
    line: rightward for a horizontal one, upward for a vertical one, which
    the text reads toward."""
    along_px = tile_along_px / 2 + gap_px + icon_px / 2 + icon.slot * (icon_px + gap_px)
    x_px, y_px = text_at_px
    if icon.label.horizontal:
        return (x_px + along_px, y_px)
    return (x_px, y_px + along_px)


def icon_at(
    icons: Sequence[ConstraintIcon],
    project: Callable[[float, float], tuple[float, float]],
    tile_along_px: Callable[[DimensionLabel], float],
    icon_px: float,
    gap_px: float,
    x_px: float,
    y_px: float,
) -> ConstraintIcon | None:
    """The icon whose square, placed as :func:`icon_center_px` places it,
    holds the device point ``(x_px, y_px)``; ``project`` takes an elevation
    point to device pixels with y up. Of two, the one drawn later."""
    found: ConstraintIcon | None = None
    half_px = icon_px / 2
    for icon in icons:
        center_x_px, center_y_px = icon_center_px(
            icon,
            project(*icon.label.text_at_mm),
            tile_along_px(icon.label),
            icon_px,
            gap_px,
        )
        if abs(x_px - center_x_px) <= half_px and abs(y_px - center_y_px) <= half_px:
            found = icon
    return found


# The spans already taken outside the unit, per edge (the elevation axis
# across it, and whether it is the low edge) and per row counted outward
# from 1.
_OuterRows = dict[tuple[str, bool], dict[int, list[tuple[float, float]]]]


def _outer_row(
    rows: _OuterRows, edge: tuple[str, bool], low_mm: float, high_mm: float
) -> int:
    """The first row outside ``edge`` where ``low_mm`` to ``high_mm``
    overlaps no dimension already there; records the span in that row."""
    taken = rows.setdefault(edge, {})
    row = 1
    while any(
        low_mm < end_mm - _EPSILON_MM and start_mm < high_mm - _EPSILON_MM
        for start_mm, end_mm in taken.get(row, [])
    ):
        row += 1
    taken.setdefault(row, []).append((low_mm, high_mm))
    return row


def _longest_mm(unit: Unit, frame: ElevationFrame) -> float:
    """The unit's longer side in ``frame``'s elevation plane."""
    size = unit.size_mm
    return max(
        size.component_mm(frame.horizontal.component_index),
        size.component_mm(frame.vertical.component_index),
    )


@dataclass
class _Planner:
    unit: Unit
    spaces: Mapping[str, Space]
    frame: ElevationFrame
    # How far apart the rows of outer dimensions sit, the first from the
    # unit's outer face.
    outer_row_mm: float
    selected_constraints: Collection[ConstraintId] = ()
    outer_rows: _OuterRows = field(default_factory=dict)

    def rects(self) -> Iterator[tuple[Region, Rect]]:
        for node, _depth, _parent in _walk(self.unit.root):
            if not isinstance(node, Board):
                yield node, self.frame.rect(self.spaces[node.id])

    def only_boards_beyond(
        self, rect: Rect, run_is_horizontal: bool, low: bool
    ) -> bool:
        """Whether nothing but boards lies between ``rect`` and the unit's
        outside, past its low or high edge across its run."""
        if run_is_horizontal:
            start_mm, end_mm = rect.h0_mm, rect.h1_mm
            edge_mm = rect.v0_mm if low else rect.v1_mm
        else:
            start_mm, end_mm = rect.v0_mm, rect.v1_mm
            edge_mm = rect.h0_mm if low else rect.h1_mm
        for _node, other in self.rects():
            if run_is_horizontal:
                other_start_mm, other_end_mm = other.h0_mm, other.h1_mm
                other_low_mm, other_high_mm = other.v0_mm, other.v1_mm
            else:
                other_start_mm, other_end_mm = other.v0_mm, other.v1_mm
                other_low_mm, other_high_mm = other.h0_mm, other.h1_mm
            if (
                other_start_mm >= end_mm - _EPSILON_MM
                or other_end_mm <= start_mm + _EPSILON_MM
            ):
                continue
            if low and other_high_mm <= edge_mm + _EPSILON_MM:
                return False
            if not low and other_low_mm >= edge_mm - _EPSILON_MM:
                return False
        return True

    def labels(self, division: Division) -> Iterator[DimensionLabel]:
        """One label per region in ``division``'s run, spanning what its
        size measures. Thirds keep a bay's width and height apart: its line
        runs two thirds across, its text a third along. A region holding
        others gets its dimension outside the unit, where no child's line
        can land on it, when only boards lie between it and that edge;
        inside the unit that spot belongs to a neighbor, so it stays within
        its own region, a sixth across, clear of its children's lines."""
        frame = self.frame
        if division.axis not in (frame.horizontal, frame.vertical):
            return
        run_is_horizontal = division.axis == frame.horizontal
        outside_mm = self.outer_row_mm
        # From the outer face rather than the region's edge, so a thick
        # board cannot carry its own dimension onto it.
        outer = frame.rect(self.spaces[self.unit.root.id])
        for index, item in enumerate(division.items):
            if isinstance(item, Board):
                continue
            rect = frame.rect(self.spaces[item.id])
            span = rect
            measured = measure(self.unit, item.id, self.spaces)
            if measured.basis is Basis.WITH_NEXT and index + 1 < len(division.items):
                after = division.items[index + 1]
                if isinstance(after, Board):
                    after_rect = frame.rect(self.spaces[after.id])
                    span = Rect(
                        min(rect.h0_mm, after_rect.h0_mm),
                        min(rect.v0_mm, after_rect.v0_mm),
                        max(rect.h1_mm, after_rect.h1_mm),
                        max(rect.v1_mm, after_rect.v1_mm),
                    )
            if run_is_horizontal:
                low_mm, high_mm = span.h0_mm, span.h1_mm
                across_low_mm, across_high_mm = rect.v0_mm, rect.v1_mm
                outer_low_mm, outer_high_mm = outer.v0_mm, outer.v1_mm
                edge = "v"
            else:
                low_mm, high_mm = span.v0_mm, span.v1_mm
                across_low_mm, across_high_mm = rect.h0_mm, rect.h1_mm
                outer_low_mm, outer_high_mm = outer.h0_mm, outer.h1_mm
                edge = "h"
            across_mm = across_high_mm - across_low_mm
            if isinstance(item, Division):
                text_fraction = 0.5
                if self.only_boards_beyond(rect, run_is_horizontal, low=True):
                    row = _outer_row(self.outer_rows, (edge, True), low_mm, high_mm)
                    cross_mm = outer_low_mm - outside_mm * row
                elif self.only_boards_beyond(rect, run_is_horizontal, low=False):
                    row = _outer_row(self.outer_rows, (edge, False), low_mm, high_mm)
                    cross_mm = outer_high_mm + outside_mm * row
                else:
                    cross_mm = across_low_mm + across_mm / 6
            else:
                text_fraction = 1 / 3
                cross_mm = across_low_mm + 2 / 3 * across_mm
            if run_is_horizontal:
                start_mm, end_mm = (low_mm, cross_mm), (high_mm, cross_mm)
            else:
                start_mm, end_mm = (cross_mm, low_mm), (cross_mm, high_mm)
            found = region_lock(self.unit, item.id)
            role: LabelRole = "reference"
            if found is not None:
                role = "driving" if found.active else "deactivated"
            yield DimensionLabel(
                region_id=item.id,
                start_mm=start_mm,
                end_mm=end_mm,
                size_mm=measured.size_mm,
                role=role,
                text_fraction=text_fraction,
                selected=found is not None and found.id in self.selected_constraints,
                lock_id=None if found is None else found.id,
            )


def plan_overlay(
    unit: Unit,
    spaces: Mapping[str, Space],
    frame: ElevationFrame,
    selected_id: str | None,
    outer_row_mm: float,
    flagged: Collection[str] = (),
    *,
    selected_items: Collection[str] = (),
    selected_constraints: Collection[ConstraintId] = (),
    fully_constrained: Collection[str] = (),
) -> Overlay:
    """What to draw for ``unit`` solved as ``spaces`` on ``frame``'s face:
    a face per bay and void, an outline per opening and for each selected
    node, a "holding" outline for each region holding a selected board and
    for each region ``flagged`` names or a constraint it names holds, the
    dimensions :func:`drawn_dimensions` picks, and an icon for each Equal
    or Even spacing beside each of its openings' dimensions.

    ``selected_id`` is the single selection, ``selected_items`` every
    selected board and opening, and ``selected_constraints`` the selected
    constraints, whose openings take the selected outline, whose icons are
    marked selected, and whose Locks' dimensions are marked selected. A
    board is held by the constraints :func:`~freecad.Shelving.core.edit.held_by`
    names, Locks included, and their openings then take the holding
    outline. Each board ``fully_constrained`` names, as
    :func:`~freecad.Shelving.core.edit.constraint_status` finds them, takes
    a "constrained" outline. The selected outline wins over a holding one,
    and a holding one over a constrained one; an id in ``flagged`` that
    names nothing draws nothing. ``spaces`` must hold every node of
    ``unit``. A dimension outside the unit sits a whole
    number of ``outer_row_mm`` rows out from its outer face, so resizing
    the unit moves only the rows past the faces that move; each region
    keeps its place whether its dimension is drawn or not, so one
    appearing moves no other. Icons at one opening sit in a row after its
    dimension's text in the order the constraints were made."""
    planner = _Planner(unit, spaces, frame, outer_row_mm, selected_constraints)
    held: Held | None = None
    if selected_id is not None:
        held = held_by(unit, selected_id)
    by_id = {constraint.id: constraint for constraint in unit.constraints}
    holding: set[str] = set()
    if held is not None:
        for constraint_id in (*held.locks, *held.constraints):
            holding.update(constraint_regions(unit, by_id[constraint_id]))
    for flag in flagged:
        constraint = by_id.get(ConstraintId(flag))
        if constraint is None:
            holding.add(flag)
        else:
            holding.update(constraint_regions(unit, constraint))
    picked = (*selected_items, *([] if selected_id is None else [selected_id]))
    selected = set(picked)
    for constraint_id in selected_constraints:
        constraint = by_id.get(constraint_id)
        if constraint is not None:
            selected.update(constraint_regions(unit, constraint))
    faces: list[Face] = []
    outlines: list[Outline] = []
    every_label: list[DimensionLabel] = []
    for node, _depth, parent in _walk(unit.root):
        is_selected = node.id in selected
        if isinstance(node, Board):
            role: OutlineRole | None = None
            if is_selected:
                role = "selected"
            elif node.id in holding:
                role = "holding"
            elif node.id in fully_constrained:
                role = "constrained"
            if role is not None and parent is not None:
                inset = _apply_insets(parent.axis, spaces[node.id], node.insets)
                outlines.append(Outline(frame.rect(inset), role))
            continue
        rect = frame.rect(spaces[node.id])
        if isinstance(node, Bay | Void):
            kind: FaceKind = "void" if isinstance(node, Void) else "bay"
            faces.append(Face(node.id, kind, rect))
        if is_selected:
            outlines.append(Outline(rect, "selected"))
        elif node.id in holding:
            outlines.append(Outline(rect, "holding"))
        elif isinstance(node, Bay | Void):
            outlines.append(Outline(rect, "region"))
        if isinstance(node, Division):
            every_label.extend(planner.labels(node))
    drawn = drawn_dimensions(unit, frame, picked)
    labels = [label for label in every_label if label.region_id in drawn]
    label_of = {label.region_id: label for label in labels}
    slots: dict[str, int] = {}
    icons: list[ConstraintIcon] = []
    for constraint in unit.constraints:
        if isinstance(constraint, Lock):
            continue
        constraint_selected = constraint.id in selected_constraints
        kind_name: ConstraintKind = (
            "equal" if isinstance(constraint, Equal) else "even_spacing"
        )
        for region_id in constraint_regions(unit, constraint):
            label = label_of.get(region_id)
            if label is None:
                continue
            slot = slots.get(region_id, FIRST_CONSTRAINT_SLOT)
            slots[region_id] = slot + 1
            icons.append(
                ConstraintIcon(
                    constraint.id,
                    kind_name,
                    label,
                    slot,
                    active=constraint.active,
                    selected=constraint_selected,
                )
            )
    return Overlay(faces=faces, outlines=outlines, labels=labels, icons=icons)


def run_direction(
    unit: Unit, frame: ElevationFrame, region_id: str
) -> ElevationDirection | None:
    """The elevation direction the run holding ``region_id`` lies along in
    ``frame``: what Lock Width or Lock Height its Lock would be. ``None``
    for a run through the depth, which neither makes, and for the root, a
    board or an unknown id."""
    parent = parent_divisions(unit.root).get(region_id)
    if parent is None or region_id in board_ids(unit):
        return None
    if parent.axis == frame.horizontal:
        return "horizontal"
    return "vertical" if parent.axis == frame.vertical else None


def drawn_dimensions(
    unit: Unit, frame: ElevationFrame, selected: Collection[str]
) -> frozenset[str]:
    """The regions whose dimensions are drawn, as the Sketcher draws only
    its dimension constraints: every region with a Lock, active or
    deactivated, every region an Equal or Even spacing holds, active or
    deactivated, and every region in ``selected`` together with the region
    owning its size along the other elevation axis, found as
    :func:`~freecad.Shelving.core.layout.region_along` finds it but kept
    when it spans the unit between boards, so a bay in a lone column shows
    the column's width. Ids in ``selected`` naming boards or nothing add
    nothing. A region whose run lies along the depth axis is in the set but
    has no dimension to draw."""
    drawn: set[str] = set()
    for constraint in unit.constraints:
        drawn.update(constraint_regions(unit, constraint))
    parents = parent_divisions(unit.root)
    boards = board_ids(unit)
    for node_id in selected:
        parent = parents.get(node_id)
        if parent is None or node_id in boards:
            continue
        drawn.add(node_id)
        across = frame.vertical if parent.axis == frame.horizontal else frame.horizontal
        if parent.axis in (frame.horizontal, frame.vertical):
            other = owner_along(parents, node_id, across)
            if other is not None:
                drawn.add(other)
    return frozenset(drawn)


def region_at(
    unit: Unit,
    spaces: Mapping[str, Space],
    frame: ElevationFrame,
    h_mm: float,
    v_mm: float,
) -> str | None:
    """The deepest region at elevation point ``(h_mm, v_mm)``: ``None``
    outside every region but the root, and on a board."""
    best: tuple[int, str] | None = None
    for node, depth, parent in _walk(unit.root):
        if isinstance(node, Board):
            if parent is not None:
                inset = _apply_insets(parent.axis, spaces[node.id], node.insets)
                if frame.rect(inset).contains(h_mm, v_mm):
                    return None
            continue
        if frame.rect(spaces[node.id]).contains(h_mm, v_mm) and (
            best is None or depth >= best[0]
        ):
            best = (depth, node.id)
    if best is None or best[1] == unit.root.id:
        return None
    return best[1]


def label_at(
    labels: Sequence[DimensionLabel],
    project: Callable[[float, float], tuple[float, float]],
    tile_px: Callable[[DimensionLabel], tuple[float, float]],
    x_px: float,
    y_px: float,
) -> DimensionLabel | None:
    """The label whose text tile holds the device point ``(x_px, y_px)``,
    edges included; of two, the one drawn later. ``tile_px`` gives a
    label's tile as its length along the line and its height across it,
    and the tile is centered where ``project`` puts the label's text: a
    vertical dimension's text, and so its tile, stands upright."""
    found: DimensionLabel | None = None
    for label in labels:
        at_x_px, at_y_px = project(*label.text_at_mm)
        along_px, across_px = tile_px(label)
        half_x_px, half_y_px = (
            (along_px / 2, across_px / 2)
            if label.horizontal
            else (across_px / 2, along_px / 2)
        )
        if abs(x_px - at_x_px) <= half_x_px and abs(y_px - at_y_px) <= half_y_px:
            found = label
    return found


@dataclass(frozen=True)
class Arrow:
    """Where the drag arrow for a board goes, and how a drag of it maps
    back to the unit."""

    board_id: str
    # The elevation point the arrow's middle sits on.
    at_mm: tuple[float, float]
    # Whether the arrow points along the elevation's vertical.
    vertical: bool
    length_mm: float
    # The unit-frame direction a positive drag moves the board in.
    direction: Vec3
    # The board's center in the unit frame: the point a drag carries.
    grab_mm: Vec3


def arrow_for(
    unit: Unit, spaces: Mapping[str, Space], frame: ElevationFrame, board_id: str
) -> Arrow | None:
    """The arrow for ``board_id`` when a drag may move it along a run in the
    elevation plane; ``None`` for a board any constraint holds, Locks
    included, a carcass board, a board whose run runs through the depth,
    and a region. The arrow sits a third of the way across the region before
    the board, at the board's center along the run, so it stays inside any
    region wide enough to hold it and clear of that region's dimension line
    at two thirds across."""
    held = held_by(unit, board_id)
    if held is None or not held.free:
        return None
    try:
        axis = run_axis(unit, board_id)
        before_id = region_before(unit, board_id)
    except EditError:
        return None
    if axis not in (frame.horizontal, frame.vertical):
        return None
    space = board_space(unit, spaces, board_id)
    if space is None:
        return None
    rect = frame.rect(space)
    before = frame.rect(spaces[before_id])
    longest_mm = _longest_mm(unit, frame)
    vertical = axis == frame.vertical
    center_h_mm, center_v_mm = rect.center_mm
    if vertical:
        at_mm = (
            before.h0_mm + (before.h1_mm - before.h0_mm) / 3,
            center_v_mm,
        )
        direction = frame.v_dir
    else:
        at_mm = (
            center_h_mm,
            before.v0_mm + (before.v1_mm - before.v0_mm) / 3,
        )
        direction = frame.h_dir
    origin, top = space.origin, space.max_corner()
    return Arrow(
        board_id=board_id,
        at_mm=at_mm,
        vertical=vertical,
        length_mm=_ARROW_FRACTION * longest_mm,
        direction=direction,
        grab_mm=Vec3(
            (origin.x_mm + top.x_mm) / 2,
            (origin.y_mm + top.y_mm) / 2,
            (origin.z_mm + top.z_mm) / 2,
        ),
    )


def dragged_to_mm(arrow: Arrow, offset_mm: float) -> Vec3:
    """The unit-frame point a drag of ``arrow`` by ``offset_mm`` along it
    carries the board's center to."""
    return _sum(arrow.grab_mm, _scaled(arrow.direction, offset_mm))


def label_size_pt(font_px: int, device_pixel_ratio: float, logical_dpi: float) -> int:
    """The ``SoDatumLabel`` size the Sketcher gives a dimension: its font
    size in logical pixels, scaled to device pixels and converted at the
    screen's logical DPI, since the node takes points and renders device
    pixels (``EditModeCoinManager``, FreeCAD 1.1). Never below 1."""
    dpi = logical_dpi if logical_dpi > 0 else 96.0
    return max(1, round(font_px * device_pixel_ratio * 72.0 / dpi))
