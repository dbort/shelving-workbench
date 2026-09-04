"""Headless functional check for the shelving object layer.

Run via ``freecadcmd tools/freecad_object_smoke.py``. It builds the `Plank`
scripted object and its helpers inside a real FreeCAD interpreter and asserts
their geometry, labels, and catalog. ``freecadcmd`` discards a script's exit
status, so the final ``shelving object layer OK`` line is the only success
signal; ``tools/run-tests.sh`` greps for it.

The ``sys.path`` insert plus ``freecad.__path__`` refresh mirror
``tools/freecad_smoke.py``: FreeCAD freezes the ``freecad`` namespace package's
``__path__`` at start-up, so a checkout-resident ``freecad.shelving`` needs the
path merged back in before it imports.
"""

import os
import sys
from pkgutil import extend_path
from typing import cast

import FreeCAD
import freecad

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
freecad.__path__ = extend_path(freecad.__path__, "freecad")

from freecad.shelving.default_catalog import (  # noqa: E402
    DEFAULT_CATALOG,
    DEFAULT_CATALOG_IDS,
    DEFAULT_MATERIAL_ID,
)
from freecad.shelving.objects.feature_types import PlankFeature  # noqa: E402
from freecad.shelving.objects.geometry import plank_shape  # noqa: E402
from freecad.shelving.objects.labels import generated_label  # noqa: E402
from freecad.shelving.objects.plank import add_plank  # noqa: E402
from freecad.shelving.vendor.shelving_core.expand import (  # noqa: E402
    PlankRole,
    Vec3,
)

_CATALOG_ORDER = ["ply18", "ply12", "mdf19", "hardwood20"]


def _assert_box(
    bound_box: FreeCAD.BoundBox,
    min_corner_mm: tuple[float, float, float],
    max_corner_mm: tuple[float, float, float],
    tol_mm: float = 1e-6,
) -> None:
    observed = (
        bound_box.XMin,
        bound_box.YMin,
        bound_box.ZMin,
        bound_box.XMax,
        bound_box.YMax,
        bound_box.ZMax,
    )
    expected = min_corner_mm + max_corner_mm
    for got_mm, want_mm in zip(observed, expected, strict=True):
        assert abs(got_mm - want_mm) <= tol_mm, (observed, expected)


def _check_labels() -> None:
    assert generated_label(PlankRole.BOTTOM, 0) == "Bottom"
    assert generated_label(PlankRole.TOP, 0) == "Top"
    assert generated_label(PlankRole.LEFT_SIDE, 0) == "Left Side"
    assert generated_label(PlankRole.RIGHT_SIDE, 0) == "Right Side"
    assert generated_label(PlankRole.SHELF, 2) == "Shelf 2"
    assert generated_label(PlankRole.DIVIDER, 3) == "Divider 3"


def _check_catalog() -> None:
    ids = [str(entry.id) for entry in DEFAULT_CATALOG]
    assert ids == _CATALOG_ORDER, ids
    assert DEFAULT_CATALOG_IDS == _CATALOG_ORDER, DEFAULT_CATALOG_IDS
    ply18 = DEFAULT_CATALOG["ply18"]
    assert ply18.thickness_mm == 18.0, ply18.thickness_mm
    assert ply18.name == "18 mm birch plywood", ply18.name
    assert DEFAULT_MATERIAL_ID == "ply18", DEFAULT_MATERIAL_ID


def _check_plank_shape() -> None:
    shape = plank_shape(Vec3(700.0, 300.0, 18.0), Vec3(10.0, 0.0, 5.0))
    assert shape.ShapeType == "Solid", shape.ShapeType
    _assert_box(shape.BoundBox, (10.0, 0.0, 5.0), (710.0, 300.0, 23.0))
    try:
        plank_shape(Vec3(0.0, 1.0, 1.0), Vec3(0.0, 0.0, 0.0))
    except ValueError:
        pass
    else:
        raise AssertionError("plank_shape accepted a zero extent")


def _check_plank_recompute() -> None:
    doc = FreeCAD.newDocument("shelving_smoke")
    try:
        obj = cast("PlankFeature", add_plank(doc))
        obj.SizeMM = FreeCAD.Vector(700.0, 300.0, 18.0)
        obj.CornerMM = FreeCAD.Vector(10.0, 0.0, 5.0)
        doc.recompute()
        _assert_box(obj.Shape.BoundBox, (10.0, 0.0, 5.0), (710.0, 300.0, 23.0))
        assert obj.Dimensions == "700 x 300 x 18 mm", obj.Dimensions
    finally:
        FreeCAD.closeDocument(doc.Name)


def main() -> None:
    _check_labels()
    _check_catalog()
    _check_plank_shape()
    _check_plank_recompute()
    print("shelving object layer OK")


main()
