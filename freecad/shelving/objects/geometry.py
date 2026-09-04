"""Plank solid construction, kept to a single seam.

`plank_shape` is the only place a plank's geometry is built. A later milestone
will feed this seam into a PartDesign Body base feature, so no other module calls
`Part.makeBox` for a plank; swapping the construction stays a one-file change.
"""

import FreeCAD
import Part

from freecad.shelving.vendor.shelving_core.expand import Vec3


def plank_shape(size: Vec3, origin: Vec3) -> Part.Shape:
    """An axis-aligned box solid of extent `size` with its minimum corner at
    `origin`, both in the carcass local frame.

    Raises `ValueError` when any component of `size` is not strictly positive;
    the message names the offending axis and its value.
    """
    for axis, extent_mm in (
        ("x", size.x_mm),
        ("y", size.y_mm),
        ("z", size.z_mm),
    ):
        if extent_mm <= 0:
            raise ValueError(f"plank {axis} extent must be > 0, got {extent_mm}")
    return Part.makeBox(
        size.x_mm,
        size.y_mm,
        size.z_mm,
        FreeCAD.Vector(origin.x_mm, origin.y_mm, origin.z_mm),
    )
