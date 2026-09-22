"""Headless functional check for the write path: create, rescan, resize,
and the identity/provenance/label rules that make repeated applies safe.

A real pytest module, not a hand-rolled assert-and-marker script, for the
same reasons ``tools/freecad_scan_smoke.py`` is one; see that module's
docstring for the ``freecadcmd`` mechanics (self-invoking ``pytest.main``,
the recursion guard, the ``sys.stdout.flush()`` before ``sys.exit``, why
``if __name__ == "__main__":`` does not work here) rather than repeating
them, and ``docs/freecadcmd-notes.md`` for the underlying findings both
modules rely on.

Each scenario below builds its own document rather than sharing one across
the whole file: the cases cover enough structurally different starting
points (a bare closed box, one with hand-added irregular or untagged
geometry, one with a copied board, one with an explicit ``Fixed`` rule)
that a single shared document would mean each test also carrying the
side effects of every test before it, which is harder to read than one
document per scenario is to afford.
"""

import os
import sys
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, cast

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import FreeCAD  # noqa: E402
import Part  # noqa: E402
import pytest  # noqa: E402

from freecad.Shelving import properties  # noqa: E402
from freecad.Shelving.commands.create_unit import CreateUnitCommand  # noqa: E402
from freecad.Shelving.commands.resize_unit import ResizeUnitCommand  # noqa: E402
from freecad.Shelving.container import read_container, write_container  # noqa: E402
from freecad.Shelving.core.geometry import Vec3  # noqa: E402
from freecad.Shelving.core.layout import (  # noqa: E402
    Axis,
    Bay,
    Board,
    Division,
    Fixed,
    Unit,
)
from freecad.Shelving.core.materials import MaterialId  # noqa: E402
from freecad.Shelving.default_catalog import (  # noqa: E402
    DEFAULT_CATALOG,
    DEFAULT_MATERIAL_ID,
)
from freecad.Shelving.unit_ops import (  # noqa: E402
    create_unit,
    rescan_unit,
    resize_unit,
)

_TOL_MM = 1e-6
_THICKNESS_MM = 18.0


class _Placeable(Protocol):
    """A ``DocumentObject`` with a settable ``Placement``: every leaf and
    container this script builds."""

    Placement: FreeCAD.Placement
    Label: str


class _BoxFeature(_Placeable, Protocol):
    """The ``Part::Box`` property surface this script writes and reads."""

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


class _ShapeFeature(Protocol):
    """A ``DocumentObject`` with a readable solid ``Shape``, such as a
    ``PartDesign::Body``; ``freecad-stubs`` types only the generic
    ``DocumentObject``, which carries no such attribute."""

    Shape: Part.Shape


def _new_document(name: str) -> FreeCAD.Document:
    return FreeCAD.newDocument(name)


def _add_box(
    doc: FreeCAD.Document,
    container: FreeCAD.DocumentObject,
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
    cast("FreeCAD.DocumentObjectGroup", container).addObject(obj)
    return obj


def _add_notched_shelf(
    doc: FreeCAD.Document,
    container: FreeCAD.DocumentObject,
    name: str,
    footprint_mm: tuple[float, float],
    corner_mm: tuple[float, float, float],
    thickness_mm: float = _THICKNESS_MM,
    notch_mm: tuple[float, float] = (60.0, 40.0),
) -> FreeCAD.DocumentObject:
    """A ``PartDesign::Body`` shaped like a board of ``footprint_mm`` with a
    rectangular notch cut from one corner, padded ``thickness_mm``, and
    moved to ``corner_mm``: the same box-minus-cutouts shape
    ``tools/freecad_scan_smoke.py``'s ``_add_notched_body`` builds, sized
    and positioned here to slot into a real bay rather than sit on its own.
    ``read_container`` reads it as an irregular ``Box``, never a plain one.
    """
    width_mm, depth_mm = footprint_mm
    notch_w_mm, notch_d_mm = notch_mm
    raw_body = doc.addObject("PartDesign::Body", name)
    body = cast("FreeCAD.DocumentObject", raw_body)
    cast("FreeCAD.DocumentObjectGroup", container).addObject(body)
    body_group = cast("FreeCAD.DocumentObjectGroup", raw_body)
    sketch = cast(
        "_SketchFeature",
        body_group.newObject("Sketcher::SketchObject", f"{name}Sketch"),
    )
    xy_plane = cast("FreeCAD.DocumentObject", doc.getObject("XY_Plane"))
    sketch.AttachmentSupport = [(xy_plane, "")]
    sketch.MapMode = "FlatFace"
    points = [
        (0.0, 0.0),
        (width_mm, 0.0),
        (width_mm, depth_mm - notch_d_mm),
        (width_mm - notch_w_mm, depth_mm - notch_d_mm),
        (width_mm - notch_w_mm, depth_mm),
        (0.0, depth_mm),
    ]
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1], strict=True):
        sketch.addGeometry(
            Part.LineSegment(FreeCAD.Vector(x0, y0, 0.0), FreeCAD.Vector(x1, y1, 0.0)),
            False,
        )
    pad = cast("_PadFeature", body_group.newObject("PartDesign::Pad", f"{name}Pad"))
    pad.Profile = cast("FreeCAD.DocumentObject", sketch)
    pad.Length = thickness_mm
    sketch.Visibility = False
    doc.recompute()
    cast("_Placeable", body).Placement = FreeCAD.Placement(
        FreeCAD.Vector(*corner_mm), FreeCAD.Rotation()
    )
    doc.recompute()
    return body


def _closed_box_unit(front_at_min: bool | None) -> Unit:
    """The same closed single-bay shape ``unit_ops._default_unit`` builds,
    parameterized on facing so the label tests can compare "unknown" against
    "known" without duplicating the tree."""
    return Unit(
        size_mm=Vec3(600.0, 300.0, 900.0),
        default_material=DEFAULT_MATERIAL_ID,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[Board(role="left_side"), Bay(), Board(role="right_side")],
                ),
                Board(role="top"),
            ],
        ),
        depth_axis=Axis.Y,
        front_at_min=front_at_min,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_init_gui_imports_cleanly() -> None:
    """Both new commands import cleanly under ``freecadcmd``, where
    ``FreeCADGui`` is a stub without ``addCommand``
    (``docs/freecadcmd-notes.md``); nothing else here imports them as a
    side effect of anything but their own module-level registration guard."""
    import freecad.Shelving.commands.create_unit  # noqa: F401
    import freecad.Shelving.commands.resize_unit  # noqa: F401
    import freecad.Shelving.init_gui  # noqa: F401


def test_inactive_without_a_document() -> None:
    """Both commands are inactive before any document exists. Runs before
    any test below creates one."""
    assert FreeCAD.ActiveDocument is None, FreeCAD.ActiveDocument
    assert CreateUnitCommand().IsActive() is False
    assert ResizeUnitCommand().IsActive() is False


def test_create_unit_seeds_a_tagged_closed_box() -> None:
    """``create_unit`` produces a container of plain ``Part::Box`` objects,
    each carrying the four board properties, the container carrying its own
    four, and a label per board naming its role. Facing is unknown (a fresh
    unit has no evidence either way), so the two sides are labelled "Side 1"
    / "Side 2", containing neither "left" nor "right"."""
    doc = _new_document("write_smoke_create")
    try:
        container = create_unit(doc)
        doc.recompute()
        assert container.TypeId == "App::Part"
        assert properties.has_container_properties(container)
        assert properties.read_container_depth_axis(container) is Axis.Y
        assert properties.read_container_facing(container) is None
        assert properties.read_container_unit_id(container) is not None
        assert properties.read_container_rules_json(container) is not None

        boxes, skipped, record = read_container(container)
        assert len(boxes) == 4, [b.name for b in boxes]
        assert len(skipped) == 0, skipped
        assert record.front_at_min is None

        names = {b.name for b in boxes}
        assert names == {"bottom", "left_side", "right_side", "top"}
        for name in names:
            obj = doc.getObject(name)
            assert obj.TypeId == "Part::Box"
            assert properties.has_board_properties(obj)
            assert properties.read_board_born_as(obj) == name
            assert properties.read_board_born_in(obj) == doc.Uid

        assert doc.getObject("bottom").Label == "Bottom"
        assert doc.getObject("top").Label == "Top"
        left_label = doc.getObject("left_side").Label
        right_label = doc.getObject("right_side").Label
        assert {left_label, right_label} == {"Side 1", "Side 2"}
        for label in (left_label, right_label):
            assert "left" not in label.lower()
            assert "right" not in label.lower()
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_known_facing_labels_contain_left_and_right() -> None:
    """The same closed-box shape, written with an explicit facing, labels
    its sides "Left Side" / "Right Side", and the assignment mirrors when
    the facing flips: the end that reads "right" at one facing reads "left"
    at the other, never the same physical end both times."""
    labels_by_facing: dict[bool, tuple[str, str]] = {}
    for front_at_min in (True, False):
        doc = _new_document("write_smoke_facing")
        try:
            container = cast(
                "FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit")
            )
            write_container(container, _closed_box_unit(front_at_min), DEFAULT_CATALOG)
            doc.recompute()
            left_label = doc.getObject("left_side").Label
            right_label = doc.getObject("right_side").Label
            assert {left_label, right_label} == {"Left Side", "Right Side"}
            labels_by_facing[front_at_min] = (left_label, right_label)
        finally:
            FreeCAD.closeDocument(doc.Name)
    assert labels_by_facing[True] != labels_by_facing[False]


@pytest.fixture
def create_unit_doc() -> Iterator[tuple[FreeCAD.Document, FreeCAD.DocumentObject]]:
    doc = _new_document("write_smoke_lifecycle")
    container = create_unit(doc)
    doc.recompute()
    yield doc, container
    FreeCAD.closeDocument(doc.Name)


def test_rescan_recovers_the_same_tree(
    create_unit_doc: tuple[FreeCAD.Document, FreeCAD.DocumentObject],
) -> None:
    """Reading a just-created container back and scanning it recovers the
    same four-board closed-box tree that ``create_unit`` wrote."""
    doc, container = create_unit_doc
    boxes, skipped, _record = read_container(container)
    assert {b.name for b in boxes} == {"bottom", "left_side", "right_side", "top"}
    assert len(skipped) == 0, skipped
    result = rescan_unit(container, DEFAULT_CATALOG)
    assert result.created == ()
    assert result.deleted == ()
    assert sorted(result.updated) == ["bottom", "left_side", "right_side", "top"]


def test_resize_updates_existing_boards_rather_than_recreating(
    create_unit_doc: tuple[FreeCAD.Document, FreeCAD.DocumentObject],
) -> None:
    """Resizing to a larger size updates the same document objects, checked
    by ``Name``, and a renamed board's ``Label`` survives it. Colour is the
    other survivor this task's Must Haves name, but ``ViewObject`` is
    ``None`` under ``freecadcmd`` (no GUI, ``docs/freecadcmd-notes.md``), so
    that half is a manual-qa.md case (M7 #2) instead."""
    doc, container = create_unit_doc
    group = cast("FreeCAD.DocumentObjectGroup", container)
    names_before = {o.Name for o in group.Group}
    bottom = cast("_Placeable", doc.getObject("bottom"))
    bottom.Label = "MyBottom"

    result = resize_unit(container, Vec3(900.0, 300.0, 900.0), DEFAULT_CATALOG)
    doc.recompute()

    assert result.created == ()
    assert result.deleted == ()
    assert result.left_alone == ()
    names_after = {o.Name for o in group.Group}
    assert names_after == names_before

    bottom_box = cast("_BoxFeature", doc.getObject("bottom"))
    assert bottom_box.Length == pytest.approx(900.0)
    assert bottom_box.Label == "MyBottom"


def test_left_alone_objects_are_never_touched() -> None:
    """A hand-added box thin along the depth axis (set aside as a panel
    rather than placed in the tree) and a skewed box (unreadable, so always
    ``Skipped``) never match anything in the scanned tree, so
    ``write_container`` leaves both exactly where they are and names them in
    ``WriteResult.left_alone``."""
    doc = _new_document("write_smoke_left_alone")
    try:
        container = create_unit(doc)
        doc.recompute()
        panel = _add_box(
            doc, container, "BackPanel", (400.0, 5.0, 400.0), (100.0, 0.0, 200.0)
        )
        skewed = _add_box(
            doc,
            container,
            "Skewed",
            (100.0, 50.0, 20.0),
            (0.0, 1000.0, 0.0),
            rotation=FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 30.0),
        )
        doc.recompute()
        panel_placement_before = cast("_Placeable", panel).Placement.Base
        skewed_placement_before = cast("_Placeable", skewed).Placement.Base

        result = rescan_unit(container, DEFAULT_CATALOG)
        doc.recompute()

        assert set(result.left_alone) == {"BackPanel", "Skewed"}
        assert not properties.has_board_properties(panel)
        assert not properties.has_board_properties(skewed)
        assert cast("_Placeable", panel).Placement.Base.isEqual(
            panel_placement_before, _TOL_MM
        )
        assert cast("_Placeable", skewed).Placement.Base.isEqual(
            skewed_placement_before, _TOL_MM
        )
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_irregular_board_moves_without_rewriting_its_shape() -> None:
    """A hand-built notched board slotted into a real bay is read as an
    irregular ``Box``, adopted (tagged, not relabelled) on the next rescan,
    then moved, never resized or recreated, by a resize that shifts its
    region: its solid volume is unchanged, and only its ``Placement``
    differs."""
    doc = _new_document("write_smoke_irregular")
    try:
        container = create_unit(doc)
        doc.recompute()
        # 600mm wide, 300mm deep, ply18 sides: interior clear width is
        # 600 - 2*18 = 564mm, matching a shelf spanning between the sides.
        shelf = _add_notched_shelf(
            doc, container, "NotchedShelf", (564.0, 300.0), (18.0, 0.0, 441.0)
        )
        cast("_Placeable", shelf).Label = "My Notched Shelf"
        doc.recompute()
        boxes, skipped, _record = read_container(container)
        notched = next(b for b in boxes if b.name == "NotchedShelf")
        assert notched.irregular is True
        assert len(skipped) == 0, skipped

        adopt_result = rescan_unit(container, DEFAULT_CATALOG)
        doc.recompute()
        assert "NotchedShelf" in adopt_result.created
        assert properties.has_board_properties(shelf)
        assert properties.read_board_irregular(shelf) is True
        # First adoption tags provenance but must not overwrite a Label the
        # user already set by hand: nothing asks for that, and it is the
        # one Label most likely to have been deliberately authored.
        assert cast("_Placeable", shelf).Label == "My Notched Shelf"
        volume_before = cast("_ShapeFeature", shelf).Shape.Volume
        placement_before = cast("_Placeable", shelf).Placement.Base

        # Height only: the shelf's own footprint (564 x 300) is unaffected,
        # so its pinned size still matches and only its Z position moves.
        move_result = resize_unit(
            container, Vec3(600.0, 300.0, 1200.0), DEFAULT_CATALOG
        )
        doc.recompute()
        assert "NotchedShelf" in move_result.updated
        volume_after = cast("_ShapeFeature", shelf).Shape.Volume
        placement_after = cast("_Placeable", shelf).Placement.Base
        assert abs(volume_before - volume_after) < _TOL_MM
        assert not placement_before.isEqual(placement_after, _TOL_MM)
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_copied_board_is_adopted_as_new_on_rescan() -> None:
    """A board copied within the document carries the original's
    ``ShelvingBornAs``, which no longer matches its own ``Name``: the next
    rescan detects the mismatch, drops the stale provenance, and adopts the
    copy as a new board (a fresh ``Label``, ``ShelvingBornAs`` reset to its
    own ``Name``) rather than treating it as a continuation of the
    original."""
    doc = _new_document("write_smoke_copy")
    try:
        container = create_unit(doc)
        doc.recompute()
        original = doc.getObject("bottom")
        raw_copy = cast("FreeCAD.DocumentObject", doc.copyObject(original, False))
        copy = cast("_Placeable", raw_copy)
        # Clear of the unit's own footprint, so it forms its own trivial
        # elevation slab rather than overlapping an existing board.
        copy.Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 0.0, 2000.0), FreeCAD.Rotation()
        )
        cast("FreeCAD.DocumentObjectGroup", container).addObject(raw_copy)
        doc.recompute()
        assert properties.read_board_born_as(raw_copy) == "bottom"
        assert raw_copy.Name != "bottom"

        result = rescan_unit(container, DEFAULT_CATALOG)
        doc.recompute()

        assert raw_copy.Name in result.created
        assert "bottom" not in result.created
        assert properties.read_board_born_as(raw_copy) == raw_copy.Name
        assert properties.read_board_born_in(raw_copy) == doc.Uid
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_stored_material_survives_a_thickness_mismatch() -> None:
    """A board tagged ``ShelvingMaterial="mdf19"`` still resolves to
    ``mdf19`` even after its measured thickness is hand-edited away from
    19mm to a value no catalog entry matches within the snap tolerance: the
    stored id bypasses thickness matching, which is what lets a
    catalog entry's thickness change later (M8) without stranding every
    board already written against the old one."""
    doc = _new_document("write_smoke_material")
    try:
        container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
        unit = _closed_box_unit(front_at_min=None)
        assert isinstance(unit.root, Division)
        bottom = unit.root.items[0]
        assert isinstance(bottom, Board)
        bottom.material = MaterialId("mdf19")
        write_container(container, unit, DEFAULT_CATALOG)
        doc.recompute()

        bottom_box = cast("_BoxFeature", doc.getObject("bottom"))
        assert bottom_box.Height == pytest.approx(19.0)
        # No catalog entry sits within the 0.5mm default snap tolerance of
        # 15mm, so thickness matching alone would refuse this board.
        bottom_box.Height = 15.0
        doc.recompute()

        boxes, skipped, _record = read_container(container)
        assert len(skipped) == 0, skipped
        rescanned_bottom = next(b for b in boxes if b.name == "bottom")
        assert rescanned_bottom.material == MaterialId("mdf19")
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_fixed_rule_survives_apply_rescan_and_reapply() -> None:
    """A ``Fixed`` bay sized to exactly match its sibling's slack-absorbed
    size, so a naive rescan's equal-siblings heuristic would recover both as
    ``Fill``, keeps its stored, non-recoverable size across two rescans and
    a resize: the shelf between them stays at its fixed offset rather than
    drifting to an even split of the new available space."""
    doc = _new_document("write_smoke_fixed_rule")
    try:
        container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
        # Z-span inside bottom/top/mid_shelf: 900 - 18*3 = 846mm; a fixed
        # 423mm bay leaves exactly 423mm for the Fill sibling, so the two
        # read back as equal-sized siblings on a plain rescan.
        unit = Unit(
            size_mm=Vec3(600.0, 300.0, 900.0),
            default_material=DEFAULT_MATERIAL_ID,
            root=Division(
                axis=Axis.Z,
                items=[
                    Board(role="bottom"),
                    Division(
                        axis=Axis.X,
                        items=[
                            Board(role="left_side"),
                            Division(
                                axis=Axis.Z,
                                items=[
                                    Bay(rule=Fixed(423.0)),
                                    Board(role="mid_shelf"),
                                    Bay(),
                                ],
                            ),
                            Board(role="right_side"),
                        ],
                    ),
                    Board(role="top"),
                ],
            ),
            depth_axis=Axis.Y,
            front_at_min=None,
        )
        write_container(container, unit, DEFAULT_CATALOG)
        doc.recompute()
        expected_z_mm = _THICKNESS_MM + 423.0

        rescan_unit(container, DEFAULT_CATALOG)
        doc.recompute()
        z_after_first_rescan = doc.getObject("mid_shelf").Placement.Base.z

        rescan_unit(container, DEFAULT_CATALOG)
        doc.recompute()
        z_after_second_rescan = doc.getObject("mid_shelf").Placement.Base.z

        resize_unit(container, Vec3(600.0, 300.0, 1200.0), DEFAULT_CATALOG)
        doc.recompute()
        z_after_resize = doc.getObject("mid_shelf").Placement.Base.z

        for got in (z_after_first_rescan, z_after_second_rescan, z_after_resize):
            assert got == pytest.approx(expected_z_mm), (got, expected_z_mm)
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_document_reopens_without_the_workbench(tmp_path: Path) -> None:
    """A saved document reopens, off this test's own import of the
    workbench having nothing to do with the reopen itself, with every board
    present and correctly sized and carrying its properties; the archive's
    ``Document.xml`` holds no ``Proxy``, ``FeaturePython``, or
    ``PythonObject`` entry, which is what lets it open without the workbench
    installed at all (plain ``Part::Box`` objects need no scripted type to
    regenerate their shape)."""
    doc = _new_document("write_smoke_reopen")
    path = str(tmp_path / "write_smoke_reopen.FCStd")
    try:
        create_unit(doc)
        doc.recompute()
        doc.saveAs(path)
    finally:
        FreeCAD.closeDocument(doc.Name)

    with zipfile.ZipFile(path) as archive:
        xml = archive.read("Document.xml").decode("utf-8")
    for forbidden in ("Proxy", "FeaturePython", "PythonObject"):
        assert forbidden not in xml, forbidden

    reopened = FreeCAD.openDocument(path)
    try:
        reopened_container = cast(
            "FreeCAD.DocumentObject", reopened.getObject("ShelvingUnit")
        )
        boxes, skipped, record = read_container(reopened_container)
        assert {b.name for b in boxes} == {"bottom", "left_side", "right_side", "top"}
        assert len(skipped) == 0, skipped
        assert record.unit_id is not None
        for name in ("bottom", "left_side", "right_side", "top"):
            obj = reopened.getObject(name)
            assert obj.TypeId == "Part::Box"
            assert properties.has_board_properties(obj)
        bottom_box = cast("_BoxFeature", reopened.getObject("bottom"))
        assert bottom_box.Length == pytest.approx(600.0)
        assert bottom_box.Width == pytest.approx(300.0)
        assert bottom_box.Height == pytest.approx(_THICKNESS_MM)
    finally:
        FreeCAD.closeDocument(reopened.Name)


# See tools/freecad_scan_smoke.py's matching block for why this is neither
# an `if __name__ == "__main__":` guard nor an unconditional call.
if os.environ.get("_FREECAD_WRITE_SMOKE_RUNNING") != "1":
    os.environ["_FREECAD_WRITE_SMOKE_RUNNING"] = "1"
    _exit_code = pytest.main([__file__, "-v"])
    sys.stdout.flush()
    sys.exit(_exit_code)
