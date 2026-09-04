"""Headless functional check for the shelving object layer.

Run via ``freecadcmd tools/freecad_object_smoke.py``. It builds the `Plank` and
`ShelvingUnit` scripted objects and their helpers inside a real FreeCAD
interpreter and asserts their geometry, labels, catalog, and the unit's
plank reconciliation. ``freecadcmd`` discards a script's exit
status, so the final ``shelving object layer OK`` line is the only success
signal; ``tools/run-tests.sh`` greps for it.

The ``sys.path`` insert plus ``freecad.__path__`` refresh mirror
``tools/freecad_smoke.py``: FreeCAD freezes the ``freecad`` namespace package's
``__path__`` at start-up, so a checkout-resident ``freecad.shelving`` needs the
path merged back in before it imports.
"""

import json
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
from freecad.shelving.objects.feature_types import (  # noqa: E402
    PlankFeature,
    ShelvingUnitFeature,
)
from freecad.shelving.objects.geometry import plank_shape  # noqa: E402
from freecad.shelving.objects.labels import generated_label  # noqa: E402
from freecad.shelving.objects.plank import add_plank  # noqa: E402
from freecad.shelving.objects.shelving_unit import (  # noqa: E402
    make_shelving_unit,
    unit_driver,
)

# The carcasses below are built from the vendored core, while `shelving_unit`
# works in the top-level `shelving_core` package (see its module comment). Every
# carcass crosses to the driver as JSON through `driver.Layout`, and that round
# trip launders the class identity, so the mix is safe. Do not compare a core
# object or enum member from this module against one the driver produced.
from freecad.shelving.vendor.shelving_core.expand import (  # noqa: E402
    PlankRole,
    Vec3,
)
from freecad.shelving.vendor.shelving_core.layout import (  # noqa: E402
    Carcass,
    Divider,
    Fill,
    Fixed,
    Leaf,
    Orientation,
    Split,
)
from freecad.shelving.vendor.shelving_core.materials import MaterialId  # noqa: E402

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


def _assert_vec(
    got: FreeCAD.Vector,
    expected: tuple[float, float, float],
    tol_mm: float = 1e-6,
) -> None:
    observed = (got.x, got.y, got.z)
    for got_mm, want_mm in zip(observed, expected, strict=True):
        assert abs(got_mm - want_mm) <= tol_mm, (observed, expected)


def _plank_children(part: object) -> list[PlankFeature]:
    """The unit `App::Part`'s plank children: every group member carrying a
    `NodeId`, which excludes the `ShelvingUnitDriver`."""
    group = cast("ShelvingUnitFeature", part).Group
    return [cast("PlankFeature", c) for c in group if hasattr(c, "NodeId")]


def _union_bbox(
    planks: list[PlankFeature],
) -> tuple[float, float, float, float, float, float]:
    boxes = [p.Shape.BoundBox for p in planks]
    return (
        min(b.XMin for b in boxes),
        min(b.YMin for b in boxes),
        min(b.ZMin for b in boxes),
        max(b.XMax for b in boxes),
        max(b.YMax for b in boxes),
        max(b.ZMax for b in boxes),
    )


def _by_role(planks: list[PlankFeature]) -> dict[str, PlankFeature]:
    return {p.Role: p for p in planks}


def _in_error_state(driver: ShelvingUnitFeature) -> bool:
    """Whether the driver's last recompute failed inside the proxy `execute`.

    FreeCAD 1.0 headless swallows the raised `RuntimeError` and marks the object
    `Invalid` instead of propagating it (`docs/freecadcmd-notes.md` § "A proxy
    `execute` that raises marks the object `Invalid`"). "Touched" alone is not an
    error signal: a recompute the driver was never visited on also carries it.
    """
    return "Invalid" in driver.State or not driver.isValid()


def _check_unit_end_to_end() -> None:
    doc = FreeCAD.newDocument("shelving_unit_smoke")
    try:
        part = make_shelving_unit(doc)
        driver = cast("ShelvingUnitFeature", unit_driver(part))
        doc.recompute()

        t_mm = DEFAULT_CATALOG["ply18"].thickness_mm

        planks = _plank_children(part)
        assert len(planks) == 4, len(planks)
        assert {p.Role for p in planks} == {
            "bottom",
            "top",
            "left_side",
            "right_side",
        }, {p.Role for p in planks}
        _assert_box_tuple(_union_bbox(planks), (0.0, 0.0, 0.0), (900.0, 300.0, 1800.0))

        shell = _by_role(planks)
        _assert_vec(shell["bottom"].SizeMM, (900.0, 300.0, t_mm))
        _assert_vec(shell["bottom"].CornerMM, (0.0, 0.0, 0.0))
        _assert_vec(shell["top"].SizeMM, (900.0, 300.0, t_mm))
        _assert_vec(shell["top"].CornerMM, (0.0, 0.0, 1800.0 - t_mm))
        _assert_vec(shell["left_side"].SizeMM, (t_mm, 300.0, 1800.0 - 2.0 * t_mm))
        _assert_vec(shell["left_side"].CornerMM, (0.0, 0.0, t_mm))
        _assert_vec(shell["right_side"].SizeMM, (t_mm, 300.0, 1800.0 - 2.0 * t_mm))
        _assert_vec(shell["right_side"].CornerMM, (900.0 - t_mm, 0.0, t_mm))

        # Property reflow: widen the unit, recompute, and confirm the solved
        # geometry and the rewritten Layout both follow.
        driver.Width = 1000
        doc.recompute()
        planks = _plank_children(part)
        union = _union_bbox(planks)
        assert abs((union[3] - union[0]) - 1000.0) <= 1e-6, union
        _assert_vec(_by_role(planks)["right_side"].CornerMM, (1000.0 - t_mm, 0.0, t_mm))
        assert json.loads(driver.Layout)["carcass"]["width_mm"] == 1000.0, driver.Layout

        # Structural relayout by hand-edited Layout: a HORIZONTAL split with two
        # shelves. Reuse the unit's carcass id so the shell node ids stay
        # matched and only the two shelves are added. Reset Width to 900 first:
        # the previous block left the promoted property at 1000, and `execute`
        # lets that win over the carcass JSON, which would contradict this
        # 900-wide relayout and break the `900 - 2t` shelf-size assertion below.
        carcass_id = json.loads(driver.Layout)["carcass"]["id"]
        driver.Width = 900
        relayout = Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_material=MaterialId("ply18"),
            root=Split(
                orientation=Orientation.HORIZONTAL,
                children=[Leaf(), Leaf(), Leaf()],
                rules=[Fixed(size_mm=400.0), Fixed(size_mm=400.0), Fill()],
                dividers=[Divider(), Divider()],
            ),
            id=carcass_id,
        )
        driver.Layout = relayout.to_json()
        doc.recompute()
        planks = _plank_children(part)
        assert len(planks) == 6, len(planks)
        shelves = [p for p in planks if p.Role == "shelf"]
        assert len(shelves) == 2, len(shelves)
        for shelf in shelves:
            _assert_vec(shelf.SizeMM, (900.0 - 2.0 * t_mm, 300.0, t_mm))

        # Reconciliation remove branch: collapse back to a single Leaf. Both
        # shelf node ids leave the spec set, so `execute` must removeObject the
        # two shelves and keep the four shell planks in place, not rebuild them.
        shelf_node_ids = {s.NodeId for s in shelves}
        shelf_names = {cast("FreeCAD.DocumentObject", s).Name for s in shelves}
        shell_names_by_role = {
            p.Role: cast("FreeCAD.DocumentObject", p).Name
            for p in planks
            if p.Role != "shelf"
        }
        driver.Layout = Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_material=MaterialId("ply18"),
            root=Leaf(),
            id=carcass_id,
        ).to_json()
        doc.recompute()
        planks = _plank_children(part)
        assert len(planks) == 4, len(planks)
        assert {p.NodeId for p in planks}.isdisjoint(shelf_node_ids), [
            p.NodeId for p in planks
        ]
        for name in shelf_names:
            assert doc.getObject(name) is None, name
        assert {
            p.Role: cast("FreeCAD.DocumentObject", p).Name for p in planks
        } == shell_names_by_role, shell_names_by_role

        good_layout = driver.Layout
        good_count = len(planks)

        # Over-constraint: two Fixed openings that cannot fit the interior. The
        # driver must raise, leave the plank count and Layout at their last good
        # values (good_count / good_layout, captured above). FreeCAD logs the
        # proxy RuntimeError traceback to stderr on the recompute below; that
        # noise is the expected shape of the error path.
        overfull = Carcass(
            width_mm=900.0,
            height_mm=1800.0,
            depth_mm=300.0,
            default_material=MaterialId("ply18"),
            root=Split(
                orientation=Orientation.HORIZONTAL,
                children=[Leaf(), Leaf()],
                rules=[Fixed(size_mm=5000.0), Fixed(size_mm=5000.0)],
                dividers=[Divider()],
            ),
            id=carcass_id,
        )
        bad_layout = overfull.to_json()
        driver.Layout = bad_layout
        try:
            doc.recompute()
        except Exception:  # noqa: BLE001  a raised recompute also satisfies the check
            pass
        assert _in_error_state(driver), driver.State
        assert len(_plank_children(part)) == good_count, len(_plank_children(part))
        assert driver.Layout == bad_layout, "execute rewrote Layout on failure"
        assert bad_layout != good_layout
    finally:
        FreeCAD.closeDocument(doc.Name)


def _assert_box_tuple(
    got: tuple[float, float, float, float, float, float],
    min_corner_mm: tuple[float, float, float],
    max_corner_mm: tuple[float, float, float],
    tol_mm: float = 1e-6,
) -> None:
    expected = min_corner_mm + max_corner_mm
    for got_mm, want_mm in zip(got, expected, strict=True):
        assert abs(got_mm - want_mm) <= tol_mm, (got, expected)


def main() -> None:
    _check_labels()
    _check_catalog()
    _check_plank_shape()
    _check_plank_recompute()
    _check_unit_end_to_end()
    print("shelving object layer OK")


main()
