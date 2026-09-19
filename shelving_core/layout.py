"""Region-tree data model for a shelving unit.

A ``Unit`` is an outer size, a default material, and a root ``Region``. A
``Region`` is a ``Bay`` (an open compartment), a ``Void`` (space inside the
unit's bounding box that is not part of the unit), or a ``Division`` (a
region cut into an ordered run of boards and sub-regions along one
``Axis``). The carcass shell is not a distinguished rule here: it is the
outermost boards of the outermost divisions, built from the same items an
interior division uses.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field

from .geometry import Vec3
from .materials import MaterialId


def new_id() -> str:
    """Fresh node identifier: the string form of a random UUID4."""
    return str(uuid.uuid4())


class Axis(enum.StrEnum):
    """Which of a unit's three dimensions a ``Division`` cuts along."""

    X = "x"
    Y = "y"
    Z = "z"


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
    always fills its region's extent along that axis with its own
    thickness. Only the pair on each of the two cross-section axes applies.
    """

    x_min_mm: float = 0.0
    x_max_mm: float = 0.0
    y_min_mm: float = 0.0
    y_max_mm: float = 0.0
    z_min_mm: float = 0.0
    z_max_mm: float = 0.0


@dataclass
class Board:
    """One physical member, sized along its division's axis by its thickness."""

    # ``None`` inherits ``Unit.default_material``; the solver resolves the id
    # to a thickness, this model keeps the ``None`` verbatim.
    material: MaterialId | None = None
    insets: Insets = Insets()
    # Free-form, set by the caller: the tree has no closed set of positions,
    # and a stepped outline has several tops, none of them *the* top.
    # Deriving a role from tree position is M7's problem.
    role: str = ""
    id: str = field(default_factory=new_id)


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


@dataclass
class Unit:
    """A shelving unit: outer size, a default material, and a root region.

    Every board is a ``Board`` item somewhere in the tree, so a closed box, a
    stepped outline, and a framed wall differ only in the shape of that tree.
    """

    size_mm: Vec3
    default_material: MaterialId
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
    id: str = field(default_factory=new_id)

    def __post_init__(self) -> None:
        if self.size_mm.x_mm <= 0:
            raise ValueError(f"Unit.size_mm.x_mm must be > 0, got {self.size_mm.x_mm}")
        if self.size_mm.y_mm <= 0:
            raise ValueError(f"Unit.size_mm.y_mm must be > 0, got {self.size_mm.y_mm}")
        if self.size_mm.z_mm <= 0:
            raise ValueError(f"Unit.size_mm.z_mm must be > 0, got {self.size_mm.z_mm}")
        if not self.default_material:
            raise ValueError("Unit.default_material must be non-empty")
