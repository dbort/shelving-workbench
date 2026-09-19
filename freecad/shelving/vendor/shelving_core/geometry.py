"""3D geometry primitives shared by the region model, the solver, and expansion.

Every length here is a float millimetre in the unit's local frame: origin at
the front-bottom-left corner, ``+X`` right (width), ``+Y`` back (depth), ``+Z``
up (height).
"""

from dataclasses import dataclass
from typing import Literal

# 0, 1, 2 index a ``Vec3``'s ``x_mm``, ``y_mm``, ``z_mm`` fields respectively;
# kept as a plain index here rather than importing ``Axis`` from ``.layout``,
# which itself imports ``Vec3`` from this module.
AxisIndex = Literal[0, 1, 2]


@dataclass(frozen=True)
class Vec3:
    """A point or an extent in the unit's local frame, millimetres."""

    x_mm: float
    y_mm: float
    z_mm: float


@dataclass(frozen=True)
class Space:
    """An axis-aligned box: a minimum corner ``origin`` plus an ``size`` extent."""

    origin: Vec3
    size: Vec3

    def extent_mm(self, axis_index: AxisIndex) -> float:
        """This box's extent along the axis at ``axis_index`` (0=x, 1=y, 2=z)."""
        return (self.size.x_mm, self.size.y_mm, self.size.z_mm)[axis_index]

    def max_corner(self) -> Vec3:
        """This box's maximum corner: ``origin`` plus ``size`` on each axis."""
        return Vec3(
            self.origin.x_mm + self.size.x_mm,
            self.origin.y_mm + self.size.y_mm,
            self.origin.z_mm + self.size.z_mm,
        )
