"""Region-tree data model for a shelving unit.

A ``Unit`` is an outer size and a root ``Region``. A ``Region`` is a
``Bay`` (an open compartment), a ``Void`` (space inside the unit's bounding
box that is not part of the unit), or a ``Division`` (a region cut into an
ordered run of boards and sub-regions along one ``Axis``). The carcass
shell is not a distinguished rule here: it is the outermost boards of the
outermost divisions, built from the same items an interior division uses.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field, replace
from typing import Literal

from freecad.Shelving.core.geometry import AxisIndex, Vec3


def new_id() -> str:
    """Fresh node identifier: the string form of a random UUID4."""
    return str(uuid.uuid4())


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
    """What a ``Fixed`` region's ``size_mm`` measures.

    ``CLEAR`` is the region's own extent along its division's axis.
    ``WITH_NEXT`` is the region plus the item immediately after it in the
    run, the way a shelf spacing is usually quoted top face to top face.
    There is no ``WITH_PREVIOUS``: that member would sit unimplemented,
    the reserved-and-dead pattern ``Divider.lap`` already burned this repo
    on once.
    """

    CLEAR = "clear"
    WITH_NEXT = "with_next"


@dataclass
class Fixed:
    """Rule: the region takes exactly ``size_mm``, measured per ``basis``."""

    size_mm: float
    basis: Basis = Basis.CLEAR

    def __post_init__(self) -> None:
        if self.size_mm <= 0:
            raise ValueError(f"Fixed.size_mm must be > 0, got {self.size_mm}")


@dataclass
class Weighted:
    """Rule: the region takes a share of slack proportional to ``weight``."""

    weight: float

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError(f"Weighted.weight must be > 0, got {self.weight}")


@dataclass
class Fill:
    """Rule: weight-1 shorthand for ``Weighted(1.0)``."""


SizeRule = Fixed | Weighted | Fill


@dataclass(frozen=True)
class Insets:
    """How far a ``Board`` is set back from its region on each of six faces.

    The pair on a division's own axis (for example ``x_min_mm`` /
    ``x_max_mm`` on a board in an ``Axis.X`` division) is ignored: a board
    fills its region's extent along that axis with its own thickness only
    when the board's ``rule`` is ``None``; when it is set, that rule
    determines the division-axis extent instead. Only the pair on each of
    the two cross-section axes applies, in either case.
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
    or by ``rule`` when that is set.
    """

    # The board's own thickness. A scanned board without a rule takes its
    # slot width in the scan's snapped grid, so its run adds up exactly; one
    # with a rule keeps its measured size across its thin axis. A new board
    # copies the thickness of the board it takes its stock from.
    thickness_mm: float
    # ``None`` means the board is regenerable: the solver derives its extent
    # from the layout, same as any other item. A value means the workbench
    # cannot reproduce this part, a notched panel say, and carries the shape
    # it is pinned at; the solver then verifies the derived extent against
    # this rather than deriving it standalone.
    pinned_size_mm: Vec3 | None = None
    insets: Insets = Insets()
    # ``None`` means the division-axis extent is ``thickness_mm``. A value
    # overrides that, for a board whose measured size along its containing
    # division's axis is not its thickness, a divider shorter than its
    # neighbors say. Reuses the same ``SizeRule`` every
    # ``Bay``/``Void``/``Division`` carries as its own ``rule`` so a caller
    # never needs to know which axis this board's containing ``Division``
    # cuts along to set it correctly.
    rule: SizeRule | None = None
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


@dataclass
class Bay:
    """An enclosed compartment: open, and part of the unit."""

    rule: SizeRule = field(default_factory=Fill)
    id: str = field(default_factory=new_id)


@dataclass
class Void:
    """Space inside the unit's bounding box that is not part of the unit.

    What makes an outline stepped. A ``Void`` holds no boards and is not a
    compartment.
    """

    rule: SizeRule = field(default_factory=Fill)
    id: str = field(default_factory=new_id)


@dataclass
class Division:
    """A region cut into an ordered run of boards and sub-regions along ``axis``.

    Items run in order along ``axis`` and need not alternate: two adjacent
    ``Board`` items are two boards face to face.
    """

    axis: Axis
    items: list[Item]
    rule: SizeRule = field(default_factory=Fill)
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


# Which end of a model axis a unit's size change leaves where it is.
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
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.size_mm.x_mm <= 0:
            raise ValueError(f"Unit.size_mm.x_mm must be > 0, got {self.size_mm.x_mm}")
        if self.size_mm.y_mm <= 0:
            raise ValueError(f"Unit.size_mm.y_mm must be > 0, got {self.size_mm.y_mm}")
        if self.size_mm.z_mm <= 0:
            raise ValueError(f"Unit.size_mm.z_mm must be > 0, got {self.size_mm.z_mm}")
