"""Region-tree data model for a shelving unit.

A ``Unit`` is an outer size and a root ``Region``. A ``Region`` is a
``Bay`` (an open compartment), a ``Void`` (space inside the unit's bounding
box that is not part of the unit), or a ``Division`` (a region cut into an
ordered run of boards and sub-regions along one ``Axis``). The carcass
shell is not a distinguished rule here: it is the outermost boards of the
outermost divisions, built from the same items an interior division uses.
A unit also carries the constraints on its openings, ``Lock``, ``Equal``
and ``EvenSpacing``, which name the tree's regions and boards by id.
"""

from __future__ import annotations

import enum
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Literal, NewType

from freecad.Shelving.core.geometry import AxisIndex, Vec3


def new_id() -> str:
    """Fresh node identifier: the string form of a random UUID4."""
    return str(uuid.uuid4())


ConstraintId = NewType("ConstraintId", str)


def new_constraint_id() -> ConstraintId:
    """Fresh constraint identifier, minted as :func:`new_id` mints a node's."""
    return ConstraintId(new_id())


class Axis(enum.StrEnum):
    """Which of a unit's three dimensions a ``Division`` cuts along."""

    X = "x"
    Y = "y"
    Z = "z"

    @property
    def component_index(self) -> AxisIndex:
        """This axis's index into a ``Vec3``'s components (0=x, 1=y, 2=z)."""
        match self:
            case Axis.X:
                return 0
            case Axis.Y:
                return 1
            case Axis.Z:
                return 2


class Basis(enum.StrEnum):
    """What a held size measures.

    ``CLEAR`` is the region's own extent along its division's axis.
    ``WITH_NEXT`` is the region plus the item immediately after it in the
    run, the way a shelf spacing is usually quoted top face to top face.
    There is no ``WITH_PREVIOUS``: that member would sit unimplemented,
    the reserved-and-dead pattern ``Divider.lap`` already burned this repo
    on once.
    """

    CLEAR = "clear"
    WITH_NEXT = "with_next"


@dataclass(frozen=True)
class Insets:
    """How far a ``Board`` is set back from its region on each of six faces.

    The pair on a division's own axis (for example ``x_min_mm`` /
    ``x_max_mm`` on a board in an ``Axis.X`` division) is ignored: a board
    fills its slot along that axis with its thickness, or with its
    ``extent_mm`` when that is set. Only the pair on each of the two
    cross-section axes applies.
    """

    x_min_mm: float = 0.0
    x_max_mm: float = 0.0
    y_min_mm: float = 0.0
    y_max_mm: float = 0.0
    z_min_mm: float = 0.0
    z_max_mm: float = 0.0


@dataclass
class Board:
    """One physical member, sized along its division's axis by its thickness,
    or by ``extent_mm`` when that is set.
    """

    # The board's own thickness. A scanned board without an ``extent_mm``
    # takes its slot width in the scan's snapped grid, so its run adds up
    # exactly; one with an ``extent_mm`` keeps its measured size across its
    # thin axis. A new board copies the thickness of the board it takes its
    # stock from.
    thickness_mm: float
    # ``None`` means the board is regenerable: the solver derives its extent
    # from the layout, same as any other item. A value means the workbench
    # cannot reproduce this part, a notched panel say, and carries the shape
    # it is pinned at; the solver then verifies the derived extent against
    # this rather than deriving it standalone.
    pinned_size_mm: Vec3 | None = None
    insets: Insets = Insets()
    # ``None`` means the division-axis extent is ``thickness_mm``. A value
    # overrides that with a fixed size, for a board whose measured size along
    # its containing division's axis is not its thickness, a divider shorter
    # than its neighbors say.
    extent_mm: float | None = None
    # Free-form, set by the caller: the tree has no closed set of positions,
    # and a stepped outline has several tops, none of them *the* top.
    role: str = ""
    # The id of the existing board whose material, appearance and grain a
    # board the editor creates copies. The write path reads it only when
    # creating the board's object, so it need not survive a scan.
    stock_from: str | None = None
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.thickness_mm <= 0:
            raise ValueError(f"Board.thickness_mm must be > 0, got {self.thickness_mm}")
        if self.extent_mm is not None and self.extent_mm <= 0:
            raise ValueError(f"Board.extent_mm must be > 0, got {self.extent_mm}")


@dataclass
class Bay:
    """An enclosed compartment: open, and part of the unit."""

    # The region's current clear size along its parent division's axis. The
    # root has no parent run and keeps 0.
    size_mm: float = 0.0
    id: str = field(default_factory=new_id)


@dataclass
class Void:
    """Space inside the unit's bounding box that is not part of the unit.

    What makes an outline stepped. A ``Void`` holds no boards and is not a
    compartment.
    """

    # The region's current clear size along its parent division's axis. The
    # root has no parent run and keeps 0.
    size_mm: float = 0.0
    id: str = field(default_factory=new_id)


@dataclass
class Division:
    """A region cut into an ordered run of boards and sub-regions along ``axis``.

    Items run in order along ``axis`` and need not alternate: two adjacent
    ``Board`` items are two boards face to face.
    """

    axis: Axis
    items: list[Item]
    # The region's current clear size along its parent division's axis. The
    # root has no parent run and keeps 0.
    size_mm: float = 0.0
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if not self.items:
            raise ValueError("Division.items must not be empty")


Region = Bay | Void | Division
Item = Board | Region


class Face(enum.StrEnum):
    """Which of a board's two faces along one axis: the one at the axis's
    minimum or the one at its maximum."""

    MIN = "min"
    MAX = "max"


@dataclass(frozen=True)
class FollowedFace:
    """A board face one edge of a ``Back`` lies on."""

    board_id: str
    # Along the axis the edge is a position on.
    face: Face


@dataclass(frozen=True)
class BackEdge:
    """What one elevation edge of a ``Back`` follows."""

    # How far the edge lies inside the unit's outer face on its own side,
    # measured at the read. The edge keeps this distance when ``follows`` is
    # ``None`` or names a board the unit no longer has.
    outer_offset_mm: float
    follows: FollowedFace | None = None


@dataclass(frozen=True)
class Back:
    """A panel thin through the unit's depth that moves and resizes with
    the boards around it, though it is no ``Board`` of the tree.

    Its four elevation edges each follow a board face or the unit's outer
    face; through the depth it keeps its thickness and its distance from
    the carcass's rear face.
    """

    # The document object's ``Name``.
    name: str
    # A part that is not a plain box keeps its shape and only moves, with
    # its low corner on its two ``*_min`` edges.
    irregular: bool
    # The edges at the minimum and maximum of the elevation's horizontal
    # axis, then of its vertical axis (``scan.elevation_axes``).
    h_min: BackEdge
    h_max: BackEdge
    v_min: BackEdge
    v_max: BackEdge
    # The panel's minimum along the depth axis less the carcass's rear face
    # there: the depth axis's maximum when the front is at its minimum, and
    # its minimum otherwise.
    rear_offset_mm: float
    # The extent the read measured; the depth component is the panel's
    # thickness, and an irregular panel keeps all three.
    size_mm: Vec3


# Which end of a model axis, or its midpoint, a unit's size change leaves
# where it is.
FixedSide = Literal["min", "center", "max"]


@dataclass(frozen=True)
class FixedPoint:
    """The spot on a unit's bounding box that stays put when its size
    changes, one side per model axis."""

    x: FixedSide = "min"
    y: FixedSide = "min"
    z: FixedSide = "min"

    def side(self, axis: Axis) -> FixedSide:
        match axis:
            case Axis.X:
                return self.x
            case Axis.Y:
                return self.y
            case Axis.Z:
                return self.z

    def with_side(self, axis: Axis, side: FixedSide) -> FixedPoint:
        """This fixed point with ``axis``'s side replaced by ``side``."""
        match axis:
            case Axis.X:
                return replace(self, x=side)
            case Axis.Y:
                return replace(self, y=side)
            case Axis.Z:
                return replace(self, z=side)


class RunEnd(enum.Enum):
    """One end of a ``Division``'s run, where an ``EvenSpacing`` group ends
    with no board."""

    START = "start"
    END = "end"


# Where an EvenSpacing group ends: a board of its run, by id, or the run's
# own end.
SpacingEnd = str | RunEnd


@dataclass(frozen=True)
class Equal:
    """Two openings whose runs lie along one model axis, held the same size."""

    # The two regions' ids, in the order they were selected.
    region_ids: tuple[str, str]
    # What both sizes measure.
    basis: Basis = Basis.CLEAR
    # A deactivated constraint is kept and drawn but never solved.
    active: bool = True
    id: ConstraintId = field(default_factory=new_constraint_id)


@dataclass(frozen=True)
class EvenSpacing:
    """Every opening of one run between two ends, held the same size.

    The group is read from the tree at each use, so a board added inside
    the span adds an opening to it and one deleted there removes one.
    """

    # The Division whose run the group lies in.
    run_id: str
    # The low end and the high end, in run order.
    start: SpacingEnd
    end: SpacingEnd
    # What every opening's size measures.
    basis: Basis = Basis.CLEAR
    # A deactivated constraint is kept and drawn but never solved.
    active: bool = True
    id: ConstraintId = field(default_factory=new_constraint_id)


@dataclass(frozen=True)
class Lock:
    """One opening held at its size through edits.

    It records no size: turning it on holds the opening at the size the
    boards give it then, so it moves nothing and never conflicts.
    """

    region_id: str
    # What the held size measures. The solve holds the clear size either
    # way; a spacing keeps its number when the board after it changes
    # thickness.
    basis: Basis = Basis.CLEAR
    # A deactivated constraint is kept and drawn but never solved.
    active: bool = True
    id: ConstraintId = field(default_factory=new_constraint_id)


Constraint = Equal | EvenSpacing | Lock


@dataclass
class Unit:
    """A shelving unit: an outer size, a position, and a root region.

    Every board is a ``Board`` item somewhere in the tree, so a closed box, a
    stepped outline, and a framed wall differ only in the shape of that tree.
    """

    size_mm: Vec3
    root: Region
    # The axis a reader projects along to see the unit as a flat elevation.
    # Affects presentation only: the model divides along any axis
    # regardless of this.
    depth_axis: Axis | None = None
    # Whether the low or the high end of depth_axis faces the viewer.
    # ``None`` means undetermined, and facing is undetermined more often
    # than not, so code deriving a left or a right from this must handle
    # not knowing.
    front_at_min: bool | None = None
    # The minimum corner of the box ``size_mm`` measures, in the frame its
    # boards are written in: a scan reads it from the same boards it reads
    # the size from, so the two always describe one box, and nothing
    # stores it.
    position_mm: Vec3 = Vec3(0.0, 0.0, 0.0)
    # The backs a scan recognized, each placed from the solved boards on
    # every write and never part of ``size_mm``. Derived at each read and
    # stored nowhere, so a back moved by hand is followed from where it now
    # is.
    backs: tuple[Back, ...] = ()
    # Per model axis rather than per elevation side, so a facing found or
    # corrected later renames the choice but keeps the physical side.
    fixed_point: FixedPoint = FixedPoint()
    # The geometric constraints on openings, in the order they were made.
    # Each names regions and boards of this tree, and no region holds more
    # than one Lock.
    constraints: tuple[Constraint, ...] = ()
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.size_mm.x_mm <= 0:
            raise ValueError(f"Unit.size_mm.x_mm must be > 0, got {self.size_mm.x_mm}")
        if self.size_mm.y_mm <= 0:
            raise ValueError(f"Unit.size_mm.y_mm must be > 0, got {self.size_mm.y_mm}")
        if self.size_mm.z_mm <= 0:
            raise ValueError(f"Unit.size_mm.z_mm must be > 0, got {self.size_mm.z_mm}")


def _span_items(
    run: Division, start: SpacingEnd, end: SpacingEnd
) -> tuple[int, int] | None:
    """The indices in ``run.items`` just past ``start`` and just before
    ``end``; ``None`` when a board end is not in ``run`` or the ends are out
    of order."""
    index = {item.id: position for position, item in enumerate(run.items)}
    if isinstance(start, RunEnd):
        if start is not RunEnd.START:
            return None
        first = 0
    else:
        if start not in index or not isinstance(run.items[index[start]], Board):
            return None
        first = index[start] + 1
    if isinstance(end, RunEnd):
        if end is not RunEnd.END:
            return None
        last = len(run.items) - 1
    else:
        if end not in index or not isinstance(run.items[index[end]], Board):
            return None
        last = index[end] - 1
    if first > last + 1:
        return None
    return first, last


def find_division(region: Region, division_id: str) -> Division | None:
    """The ``Division`` named ``division_id`` in ``region``'s subtree,
    ``region`` included; ``None`` when there is none."""
    if not isinstance(region, Division):
        return None
    if region.id == division_id:
        return region
    for item in region.items:
        if not isinstance(item, Board):
            found = find_division(item, division_id)
            if found is not None:
                return found
    return None


def spacing_group(unit: Unit, spacing: EvenSpacing) -> tuple[str, ...] | None:
    """The ids of the regions of ``spacing``'s run between its ends, in run
    order; ``None`` when its run or an end board is no longer in ``unit``,
    or the ends are out of order. An empty or one-region group is
    returned as it is."""
    run = find_division(unit.root, spacing.run_id)
    if run is None:
        return None
    span = _span_items(run, spacing.start, spacing.end)
    if span is None:
        return None
    first, last = span
    return tuple(
        item.id for item in run.items[first : last + 1] if not isinstance(item, Board)
    )


def constraint_regions(unit: Unit, constraint: Constraint) -> tuple[str, ...]:
    """The regions ``constraint`` holds in ``unit``, in its own order: a
    ``Lock``'s one, an ``Equal``'s two, or an ``EvenSpacing``'s group, empty
    when the group no longer resolves."""
    if isinstance(constraint, Lock):
        return (constraint.region_id,)
    if isinstance(constraint, Equal):
        return constraint.region_ids
    return spacing_group(unit, constraint) or ()


def region_lock(unit: Unit, region_id: str) -> Lock | None:
    """The ``Lock``, active or deactivated, naming the region ``region_id``
    in ``unit``; ``None`` when none does."""
    return next(
        (
            c
            for c in unit.constraints
            if isinstance(c, Lock) and c.region_id == region_id
        ),
        None,
    )


def is_locked(unit: Unit, region_id: str) -> bool:
    """Whether an active ``Lock`` holds the region ``region_id``."""
    found = region_lock(unit, region_id)
    return found is not None and found.active


def renamed_constraint_boards(
    constraints: tuple[Constraint, ...], renames: Mapping[str, str]
) -> tuple[Constraint, ...]:
    """``constraints`` with every board end ``renames`` maps renamed, as a
    board created by a write takes its object's ``Name``; regions keep their
    ids."""
    if not renames:
        return constraints
    renamed: list[Constraint] = []
    for constraint in constraints:
        if isinstance(constraint, EvenSpacing):
            start, end = constraint.start, constraint.end
            constraint = replace(
                constraint,
                start=start if isinstance(start, RunEnd) else renames.get(start, start),
                end=end if isinstance(end, RunEnd) else renames.get(end, end),
            )
        renamed.append(constraint)
    return tuple(renamed)
