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
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, NamedTuple

from freecad.Shelving.core.edit import (
    EditError,
    held_by,
    is_locked,
    measure,
    region_before,
    run_axis,
    split_region,
)
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    FixedSide,
    Insets,
    Region,
    Unit,
    Void,
)
from freecad.Shelving.core.scan import elevation_axes
from freecad.Shelving.core.solver import LayoutSolveError, solve

Side = Literal["front", "back"]
FaceKind = Literal["bay", "void"]
OutlineRole = Literal["region", "selected", "holding"]
LabelColor = Literal["locked", "unlocked"]

# How far in front of the face outlines and dimensions sit, so they do not
# z-fight with the board faces they lie on. Opening faces sit on the face
# itself: the fronts of the boards around an opening never overlap it.
LIFT_MM = 0.5
# How far a click may land from a dimension's text and still open its field.
LABEL_HIT_PX = 24.0
# The drag arrow's length, as a fraction of the unit's longer elevation side.
_ARROW_FRACTION = 0.08
# How far past the dimension line of the opening it resizes the arrow sits,
# as a fraction of the unit's longer elevation side.
_ARROW_BESIDE_FRACTION = 0.04
# How far outside the unit each row of outer dimensions sits, as a fraction
# of the unit's longer elevation side.
_OUTER_ROW_FRACTION = 0.06
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
    color: LabelColor
    # Where the text's center sits along the line, as a fraction from start.
    text_fraction: float
    # Whether the region can lock or unlock: false only for an unlocked
    # region alone in its run, which could never lock.
    lockable: bool

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


@dataclass(frozen=True)
class Overlay:
    """Everything drawn over the unit, in the order Coin draws it: faces,
    then outlines, then dimensions."""

    faces: Sequence[Face] = ()
    outlines: Sequence[Outline] = ()
    labels: Sequence[DimensionLabel] = ()


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


@dataclass
class _Planner:
    unit: Unit
    spaces: Mapping[str, Space]
    frame: ElevationFrame
    outer_rows: _OuterRows = field(default_factory=dict)

    @property
    def longest_mm(self) -> float:
        size = self.unit.size_mm
        return max(
            size.component_mm(self.frame.horizontal.component_index),
            size.component_mm(self.frame.vertical.component_index),
        )

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
        outside_mm = _OUTER_ROW_FRACTION * self.longest_mm
        alone = sum(not isinstance(item, Board) for item in division.items) == 1
        for index, item in enumerate(division.items):
            if isinstance(item, Board):
                continue
            rect = frame.rect(self.spaces[item.id])
            span = rect
            spacing = (
                isinstance(item.rule, Fixed) and item.rule.basis is Basis.WITH_NEXT
            )
            if spacing and index + 1 < len(division.items):
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
                edge = "v"
            else:
                low_mm, high_mm = span.v0_mm, span.v1_mm
                across_low_mm, across_high_mm = rect.h0_mm, rect.h1_mm
                edge = "h"
            across_mm = across_high_mm - across_low_mm
            if isinstance(item, Division):
                text_fraction = 0.5
                if self.only_boards_beyond(rect, run_is_horizontal, low=True):
                    row = _outer_row(self.outer_rows, (edge, True), low_mm, high_mm)
                    cross_mm = across_low_mm - outside_mm * row
                elif self.only_boards_beyond(rect, run_is_horizontal, low=False):
                    row = _outer_row(self.outer_rows, (edge, False), low_mm, high_mm)
                    cross_mm = across_high_mm + outside_mm * row
                else:
                    cross_mm = across_low_mm + across_mm / 6
            else:
                text_fraction = 1 / 3
                cross_mm = across_low_mm + 2 / 3 * across_mm
            if run_is_horizontal:
                start_mm, end_mm = (low_mm, cross_mm), (high_mm, cross_mm)
            else:
                start_mm, end_mm = (cross_mm, low_mm), (cross_mm, high_mm)
            # A selected region keeps its lock color, as the Sketcher's
            # constraints keep theirs when their geometry is selected.
            locked = is_locked(item)
            color: LabelColor = "locked" if locked else "unlocked"
            yield DimensionLabel(
                region_id=item.id,
                start_mm=start_mm,
                end_mm=end_mm,
                size_mm=measure(self.unit, item.id, self.spaces).size_mm,
                color=color,
                text_fraction=text_fraction,
                lockable=locked or not alone,
            )


def plan_overlay(
    unit: Unit,
    spaces: Mapping[str, Space],
    frame: ElevationFrame,
    selected_id: str | None,
) -> Overlay:
    """What to draw for ``unit`` solved as ``spaces`` on ``frame``'s face:
    a face per bay and void, an outline per opening and for the selected
    node, a "holding" outline for each locked region holding a selected
    board that :func:`held_padlock` gives a padlock, and a dimension for
    every region in a run along an elevation axis. ``spaces`` must hold
    every node of ``unit``."""
    planner = _Planner(unit, spaces, frame)
    padlock = (
        None if selected_id is None else held_padlock(unit, spaces, frame, selected_id)
    )
    holding = frozenset(() if padlock is None else padlock.holders)
    faces: list[Face] = []
    outlines: list[Outline] = []
    labels: list[DimensionLabel] = []
    for node, _depth, parent in _walk(unit.root):
        selected = node.id == selected_id
        if isinstance(node, Board):
            if selected and parent is not None:
                inset = _apply_insets(parent.axis, spaces[node.id], node.insets)
                outlines.append(Outline(frame.rect(inset), "selected"))
            continue
        rect = frame.rect(spaces[node.id])
        if isinstance(node, Bay | Void):
            kind: FaceKind = "void" if isinstance(node, Void) else "bay"
            faces.append(Face(node.id, kind, rect))
        if selected:
            outlines.append(Outline(rect, "selected"))
        elif node.id in holding:
            outlines.append(Outline(rect, "holding"))
        elif isinstance(node, Bay | Void):
            outlines.append(Outline(rect, "region"))
        if isinstance(node, Division):
            labels.extend(planner.labels(node))
    return Overlay(faces=faces, outlines=outlines, labels=labels)


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
    x_px: float,
    y_px: float,
    radius_px: float = LABEL_HIT_PX,
) -> DimensionLabel | None:
    """The label whose text center ``project`` puts nearest ``(x_px, y_px)``
    and within ``radius_px`` of it; of two equally near, the one drawn
    later, since it is drawn on top."""
    best: tuple[float, DimensionLabel] | None = None
    for label in labels:
        at_x_px, at_y_px = project(*label.text_at_mm)
        distance_px = math.hypot(at_x_px - x_px, at_y_px - y_px)
        if distance_px <= radius_px and (best is None or distance_px <= best[0]):
            best = (distance_px, label)
    return best[1] if best is not None else None


def split_preview(
    unit: Unit, frame: ElevationFrame, region_id: str, axis: Axis
) -> Rect | None:
    """Where the board splitting ``region_id`` along ``axis`` would go,
    solved as the split would be; ``None`` when the split would be
    refused."""
    try:
        candidate = split_region(unit, region_id, axis)
        spaces = solve(candidate)
    except (EditError, LayoutSolveError):
        return None
    added = board_ids(candidate) - board_ids(unit)
    if len(added) != 1:
        return None
    space = board_space(candidate, spaces, next(iter(added)))
    return None if space is None else frame.rect(space)


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
    elevation plane; ``None`` for a board a locked opening holds, a carcass
    board, a board whose run runs through the depth, and a region. The
    arrow sits beside the dimension of the region before the board, just
    past its line, so a view zoomed in on that region shows both."""
    if held_by(unit, board_id) != ():
        return None
    return _arrow_place(unit, spaces, frame, board_id)


def _arrow_place(
    unit: Unit, spaces: Mapping[str, Space], frame: ElevationFrame, board_id: str
) -> Arrow | None:
    """:func:`arrow_for`'s arrow whether or not a locked opening holds the
    board."""
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
    longest_mm = _Planner(unit, spaces, frame).longest_mm
    beside_mm = _ARROW_BESIDE_FRACTION * longest_mm
    vertical = axis == frame.vertical
    center_h_mm, center_v_mm = rect.center_mm
    if vertical:
        at_mm = (
            before.h0_mm + 2 / 3 * (before.h1_mm - before.h0_mm) + beside_mm,
            center_v_mm,
        )
        direction = frame.v_dir
    else:
        at_mm = (
            center_h_mm,
            before.v0_mm + 2 / 3 * (before.v1_mm - before.v0_mm) + beside_mm,
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


@dataclass(frozen=True)
class HeldPadlock:
    """The padlock a held board shows in place of its arrow."""

    board_id: str
    # Where the board's arrow would sit.
    at_mm: tuple[float, float]
    # The locked regions holding the board, low side first: what clicking
    # the padlock unlocks.
    holders: tuple[str, ...]


def held_padlock(
    unit: Unit, spaces: Mapping[str, Space], frame: ElevationFrame, board_id: str
) -> HeldPadlock | None:
    """The padlock for ``board_id`` when locked regions hold it and unlocking
    them would give it an arrow; ``None`` for a board a drag may move, a
    carcass board, a board whose run runs through the depth, and a
    region."""
    holders = held_by(unit, board_id)
    if not holders:
        return None
    place = _arrow_place(unit, spaces, frame, board_id)
    if place is None:
        return None
    return HeldPadlock(board_id, place.at_mm, holders)


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
