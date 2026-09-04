"""Plank solid construction, kept to a single seam.

`plank_shape` is the only place a plank's geometry is built. A later milestone
will feed this seam into a PartDesign Body base feature, so no other module calls
`Part.makeBox` for a plank; swapping the construction stays a one-file change.
"""

import Part

import FreeCAD
from freecad.shelving.vendor.shelving_core.expand import Vec3


def plank_shape(size_mm: Vec3, origin_mm: Vec3) -> Part.Shape:
    """An axis-aligned box solid of extent `size_mm` with its minimum corner at
    `origin_mm`, both in the carcass local frame.

    Raises `ValueError` when any component of `size_mm` is not strictly
    positive; the message names the offending axis and its value.
    """
    for axis, extent_mm in (
        ("x", size_mm.x_mm),
        ("y", size_mm.y_mm),
        ("z", size_mm.z_mm),
    ):
        if extent_mm <= 0:
            raise ValueError(f"plank {axis} extent must be > 0, got {extent_mm}")
    return Part.makeBox(
        size_mm.x_mm,
        size_mm.y_mm,
        size_mm.z_mm,
        FreeCAD.Vector(origin_mm.x_mm, origin_mm.y_mm, origin_mm.z_mm),
    )
