"""Headless functional check for reading a container into the core scanner.

Run via ``freecadcmd tools/freecad_scan_smoke.py``. It builds a closed unit
in a real FreeCAD document, reads it with ``read_container``, scans it, and
asserts the geometry, the region tree, and the container's-own-frame and
solid-classification rules a unit test cannot exercise without a FreeCAD
interpreter. ``freecadcmd`` discards a script's exit status, so the final
``shelving scan OK`` line is the only success signal; ``tools/run-tests.sh``
greps for it.

The ``sys.path`` insert plus ``freecad.__path__`` refresh mirror
``tools/freecad_smoke.py``, which explains why they are needed.
"""

import math
import os
import sys
from pkgutil import extend_path
from typing import Protocol, cast

import freecad

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
freecad.__path__ = extend_path(freecad.__path__, "freecad")

import FreeCAD  # noqa: E402
import Part  # noqa: E402

from freecad.shelving.commands.export_boxes import ExportBoxesCommand  # noqa: E402
from freecad.shelving.commands.scan import ScanCommand  # noqa: E402
from freecad.shelving.container import read_container  # noqa: E402
from freecad.shelving.default_catalog import DEFAULT_CATALOG  # noqa: E402
from freecad.shelving.vendor.shelving_core.layout import (  # noqa: E402
    Bay,
    Board,
    Division,
    Region,
)
from freecad.shelving.vendor.shelving_core.scan import Box, scan  # noqa: E402

_TOL_MM = 1e-6
_THICKNESS_MM = 18.0
_SIZE_MM = 600.0
_DEPTH_MM = 300.0


class _Placeable(Protocol):
    """A ``DocumentObject`` with a settable ``Placement``: every leaf and
    container this script builds, but not the generic ``DocumentObject``
    ``freecad-stubs`` types ``Document.addObject`` as returning."""

    Placement: FreeCAD.Placement


class _BoxFeature(_Placeable, Protocol):
    """The ``Part::Box`` property surface this script writes."""

    Length: float
    Width: float
    Height: float


class _SketchFeature(Protocol):
    """The ``Sketcher::SketchObject`` property surface this script writes.
    ``AttachmentSupport`` / ``MapMode`` come from ``Part::AttachExtension``,
    mixed in at runtime and not part of any typed stub base."""

    AttachmentSupport: list[tuple[FreeCAD.DocumentObject, str]]
    MapMode: str
    Visibility: bool

    def addGeometry(self, geometry: Part.LineSegment, construction: bool) -> int: ...


class _PadFeature(Protocol):
    """The ``PartDesign::Pad`` property surface this script writes."""

    Profile: FreeCAD.DocumentObject
    Length: float


def _check_inactive_without_a_document() -> None:
    """Both commands are inactive before any document exists, and active
    once one does, regardless of whether the GUI ever registered them."""
    assert FreeCAD.ActiveDocument is None, FreeCAD.ActiveDocument
    scan_cmd = ScanCommand()
    export_cmd = ExportBoxesCommand()
    assert scan_cmd.IsActive() is False
    assert export_cmd.IsActive() is False


def _add_box(
    doc: FreeCAD.Document,
    part: FreeCAD.DocumentObject,
    name: str,
    size_mm: tuple[float, float, float],
    corner_mm: tuple[float, float, float],
    rotation: FreeCAD.Rotation | None = None,
) -> FreeCAD.DocumentObject:
    raw = doc.addObject("Part::Box", name)
    box = cast("_BoxFeature", raw)
    box.Length, box.Width, box.Height = size_mm
    box.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*corner_mm), rotation or FreeCAD.Rotation()
    )
    obj = cast("FreeCAD.DocumentObject", raw)
    cast("FreeCAD.DocumentObjectGroup", part).addObject(obj)
    return obj


def _build_shell(doc: FreeCAD.Document, part: FreeCAD.DocumentObject) -> None:
    """A closed 600 x 600 x 300 mm shell with one shelf: four walls captured
    the way ``shelving_core.tests.test_scan``'s ``_closed_box`` helper builds
    one, plus a shelf between the sides."""
    t, size, depth = _THICKNESS_MM, _SIZE_MM, _DEPTH_MM
    _add_box(doc, part, "Bottom", (size, depth, t), (0.0, 0.0, 0.0))
    _add_box(doc, part, "Top", (size, depth, t), (0.0, 0.0, size - t))
    _add_box(doc, part, "LeftSide", (t, depth, size - 2 * t), (0.0, 0.0, t))
    _add_box(doc, part, "RightSide", (t, depth, size - 2 * t), (size - t, 0.0, t))
    _add_box(doc, part, "Shelf", (size - 2 * t, depth, t), (t, 0.0, 291.0))


def _box_by_name(boxes: list[Box], name: str) -> Box:
    for box in boxes:
        if box.name == name:
            return box
    raise AssertionError(f"no box named {name!r} in {[b.name for b in boxes]}")


def _assert_close(got_mm: float, want_mm: float) -> None:
    assert abs(got_mm - want_mm) < _TOL_MM, (got_mm, want_mm)


def _assert_shelf_reads_correctly(boxes: list[Box]) -> None:
    shelf = _box_by_name(boxes, "Shelf")
    t, size, depth = _THICKNESS_MM, _SIZE_MM, _DEPTH_MM
    for got, want in zip(
        (shelf.corner_mm.x_mm, shelf.corner_mm.y_mm, shelf.corner_mm.z_mm),
        (t, 0.0, 291.0),
        strict=True,
    ):
        _assert_close(got, want)
    for got, want in zip(
        (shelf.size_mm.x_mm, shelf.size_mm.y_mm, shelf.size_mm.z_mm),
        (size - 2 * t, depth, t),
        strict=True,
    ):
        _assert_close(got, want)


def _assert_shell_tree_shape(root: Region) -> None:
    """Bottom and Top as the outer Z cuts, Left/Right captured between them
    along X, and the shelf between the sides along Z."""
    assert isinstance(root, Division)
    assert len(root.items) == 3
    bottom, middle, top = root.items
    assert isinstance(bottom, Board) and bottom.role == "Bottom"
    assert isinstance(top, Board) and top.role == "Top"
    assert isinstance(middle, Division)
    assert len(middle.items) == 3
    left, inner, right = middle.items
    assert isinstance(left, Board) and left.role == "LeftSide"
    assert isinstance(right, Board) and right.role == "RightSide"
    assert isinstance(inner, Division)
    assert len(inner.items) == 3
    below, shelf, above = inner.items
    assert isinstance(below, Bay) and isinstance(above, Bay)
    assert isinstance(shelf, Board) and shelf.role == "Shelf"


def _add_notched_body(
    doc: FreeCAD.Document, part: FreeCAD.DocumentObject
) -> FreeCAD.DocumentObject:
    """A ``PartDesign::Body`` (child of ``part``) holding a
    ``Sketcher::SketchObject`` and a ``PartDesign::Pad`` whose solid is a
    200 x 100 x 18 mm plank with a 50 x 30 mm notch cut from one corner: the
    box-minus-cutouts skip case, and proof that a body's sketch and pad are
    not read as two boards. The walk never descends into a body, so it only
    ever sees the body itself, as one leaf.
    """
    raw_body = doc.addObject("PartDesign::Body", "NotchedBody")
    body = cast("FreeCAD.DocumentObject", raw_body)
    cast("FreeCAD.DocumentObjectGroup", part).addObject(body)

    body_group = cast("FreeCAD.DocumentObjectGroup", raw_body)
    sketch = cast(
        "_SketchFeature", body_group.newObject("Sketcher::SketchObject", "NotchSketch")
    )
    xy_plane = cast("FreeCAD.DocumentObject", doc.getObject("XY_Plane"))
    sketch.AttachmentSupport = [(xy_plane, "")]
    sketch.MapMode = "FlatFace"
    # An L-shaped outline: a 200 x 100 mm rectangle with a 50 x 30 mm notch
    # removed from the top-right corner.
    points = [
        (0.0, 0.0),
        (200.0, 0.0),
        (200.0, 70.0),
        (150.0, 70.0),
        (150.0, 100.0),
        (0.0, 100.0),
    ]
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True):
        sketch.addGeometry(
            Part.LineSegment(FreeCAD.Vector(x0, y0, 0.0), FreeCAD.Vector(x1, y1, 0.0)),
            False,
        )

    pad = cast("_PadFeature", body_group.newObject("PartDesign::Pad", "NotchPad"))
    pad.Profile = cast("FreeCAD.DocumentObject", sketch)
    pad.Length = _THICKNESS_MM
    sketch.Visibility = False
    doc.recompute()
    return body


def main() -> None:
    _check_inactive_without_a_document()

    doc = FreeCAD.newDocument("shelving_scan_smoke")
    part = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    _build_shell(doc, part)
    doc.recompute()

    boxes, skipped = read_container(part)
    assert len(boxes) == 5, len(boxes)
    assert len(skipped) == 0, skipped
    _assert_shelf_reads_correctly(boxes)

    result = scan(boxes, DEFAULT_CATALOG, skipped=skipped)
    _assert_shell_tree_shape(result.unit.root)

    # Move and rotate the container: the records must not change, since
    # read_container excludes the selected container's own placement.
    before = sorted((b.name, b.corner_mm, b.size_mm) for b in boxes)
    shelf = cast("FreeCAD.GeoFeature", doc.getObject("Shelf"))
    shelf_global_before = shelf.getGlobalPlacement().Base
    new_placement = FreeCAD.Placement(
        FreeCAD.Vector(1000.0, -500.0, 250.0),
        FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 90.0),
    )
    cast("_Placeable", part).Placement = new_placement
    doc.recompute()
    # Prove the write actually moved the shelf before trusting "records
    # unchanged" below as evidence of the exclusion rule, rather than of a
    # placement write that silently had no effect.
    assert cast("_Placeable", part).Placement.Base.isEqual(new_placement.Base, _TOL_MM)
    shelf_global_after = shelf.getGlobalPlacement().Base
    assert not shelf_global_after.isEqual(shelf_global_before, _TOL_MM), (
        shelf_global_before,
        shelf_global_after,
    )
    moved_boxes, moved_skipped = read_container(part)
    after = sorted((b.name, b.corner_mm, b.size_mm) for b in moved_boxes)
    assert before == after, (before, after)
    assert len(moved_skipped) == 0, moved_skipped

    # A PartDesign::Body with a padded notched sketch: one Skipped record
    # naming the box-minus-cutouts reason, not two board records.
    body = _add_notched_body(doc, part)
    boxes, skipped = read_container(part)
    assert len(boxes) == 5, len(boxes)
    assert len(skipped) == 1, skipped
    assert skipped[0].name == body.Name
    assert "box minus 1 rectangular cutout" in skipped[0].reason, skipped[0].reason
    assert "50 x 30 x 18 mm" in skipped[0].reason, skipped[0].reason

    # The same body reachable through a second group: still one record.
    raw_alias = doc.addObject("App::DocumentObjectGroup", "AliasGroup")
    alias_group = cast("FreeCAD.DocumentObject", raw_alias)
    cast("FreeCAD.DocumentObjectGroup", part).addObject(alias_group)
    cast("FreeCAD.DocumentObjectGroup", raw_alias).addObject(body)
    doc.recompute()
    boxes, skipped = read_container(part)
    assert len(boxes) == 5, len(boxes)
    assert len(skipped) == 1, skipped

    # A box rotated a quarter turn: Length/Width swap in the bounding box,
    # and read_container has to follow the bounding box, not the properties.
    _add_box(
        doc,
        part,
        "Rotated",
        (100.0, 50.0, 20.0),
        (710.0, 5.0, 0.0),
        rotation=FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 90.0),
    )
    doc.recompute()
    boxes, skipped = read_container(part)
    assert len(boxes) == 6, len(boxes)
    rotated = _box_by_name(boxes, "Rotated")
    for got, want in zip(
        (rotated.size_mm.x_mm, rotated.size_mm.y_mm, rotated.size_mm.z_mm),
        (50.0, 100.0, 20.0),
        strict=True,
    ):
        _assert_close(got, want)
    assert math.isclose(rotated.corner_mm.x_mm, 660.0, abs_tol=_TOL_MM)
    assert math.isclose(rotated.corner_mm.y_mm, 5.0, abs_tol=_TOL_MM)

    # A box inside a nested App::Part carrying a quarter-turn rotation: the
    # walk composes the nested container's placement on top of the leaf's
    # own (only the selected top-level container's placement is excluded),
    # so the composed rotation must swap the extents the same way a
    # rotation on the leaf itself does, not just move the minimum corner.
    raw_nested = doc.addObject("App::Part", "NestedUnit")
    nested_obj = cast("FreeCAD.DocumentObject", raw_nested)
    cast("FreeCAD.DocumentObjectGroup", part).addObject(nested_obj)
    cast("_Placeable", raw_nested).Placement = FreeCAD.Placement(
        FreeCAD.Vector(500.0, 0.0, 0.0),
        FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 90.0),
    )
    _add_box(doc, nested_obj, "NestedBox", (100.0, 50.0, 20.0), (0.0, 0.0, 0.0))
    doc.recompute()
    boxes, skipped = read_container(part)
    assert len(boxes) == 7, len(boxes)
    assert len(skipped) == 1, skipped
    nested_box = _box_by_name(boxes, "NestedBox")
    for got, want in zip(
        (nested_box.size_mm.x_mm, nested_box.size_mm.y_mm, nested_box.size_mm.z_mm),
        (50.0, 100.0, 20.0),
        strict=True,
    ):
        _assert_close(got, want)
    assert math.isclose(nested_box.corner_mm.x_mm, 450.0, abs_tol=_TOL_MM)
    assert math.isclose(nested_box.corner_mm.y_mm, 0.0, abs_tol=_TOL_MM)
    assert math.isclose(nested_box.corner_mm.z_mm, 0.0, abs_tol=_TOL_MM)

    # A box skewed off-axis, directly in the selected container: no multiple
    # of 90 degrees rescues it, so _axis_aligned refuses it by name rather
    # than adopting a bounding box that does not describe the solid.
    _add_box(
        doc,
        part,
        "Skewed",
        (100.0, 50.0, 20.0),
        (0.0, 400.0, 0.0),
        rotation=FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 30.0),
    )
    doc.recompute()
    boxes, skipped = read_container(part)
    assert len(boxes) == 7, len(boxes)
    assert len(skipped) == 2, skipped
    skewed = next(s for s in skipped if s.name == "Skewed")
    assert skewed.reason == "not axis-aligned", skewed.reason

    print("shelving scan OK")


main()
