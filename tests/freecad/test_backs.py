"""A back follows the unit's boards through every write: the Woodworking
workbench's Magic Start unit and hand-built units, through ``unit_ops`` and
through the editor's session."""

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal, Protocol, cast

import FreeCAD
import Part
import pytest

from freecad.Shelving import properties
from freecad.Shelving.container import read_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.editor.session import EditFailure, Session, UnitDimension
from freecad.Shelving.unit_ops import (
    create_unit,
    rescan_unit,
    resize_unit,
    unit_size_mm,
)

_TOL_MM = 1e-6
_MAGIC_START = (
    Path(__file__).parent / "fixtures" / "woodworking_magic_start_default.FCStd"
)


class _Placeable(Protocol):
    Placement: FreeCAD.Placement
    Label: str


class _BoxFeature(_Placeable, Protocol):
    Length: float
    Width: float
    Height: float


class _CutFeature(_Placeable, Protocol):
    Base: FreeCAD.DocumentObject
    Tool: FreeCAD.DocumentObject


class _ShapeFeature(Protocol):
    Shape: Part.Shape


class _LinkGroupObject(Protocol):
    ElementList: list[FreeCAD.DocumentObject]


_Bound = tuple[float, float, float, float, float, float]


def _bound(doc: FreeCAD.Document, name: str) -> _Bound:
    """``name``'s bounding box as (min x, max x, min y, max y, min z, max
    z), after a recompute."""
    doc.recompute()
    obj = doc.getObject(name)
    assert obj is not None, name
    box = cast("_ShapeFeature", obj).Shape.BoundBox
    return (box.XMin, box.XMax, box.YMin, box.YMax, box.ZMin, box.ZMax)


def _placement(doc: FreeCAD.Document, name: str) -> FreeCAD.Placement:
    obj = doc.getObject(name)
    assert obj is not None, name
    return FreeCAD.Placement(cast("_Placeable", obj).Placement)


def _assert_bound(actual: _Bound, expected: _Bound) -> None:
    assert actual == pytest.approx(expected, abs=_TOL_MM), (actual, expected)


@pytest.fixture
def magic_start(tmp_path: Path) -> Iterator[FreeCAD.DocumentObject]:
    path = tmp_path / _MAGIC_START.name
    shutil.copyfile(_MAGIC_START, path)
    doc = FreeCAD.openDocument(str(path))
    container = doc.getObject("LinkGroup")
    assert container is not None
    yield container
    FreeCAD.closeDocument(doc.Name)


_Via = Literal["unit_ops", "session"]

# Each dimension's delta, and the model axis it runs along.
_DELTAS_MM: dict[UnitDimension, tuple[float, int]] = {
    "width": (120.0, 0),
    "depth": (50.0, 1),
    "height": (40.0, 2),
}


def _resize(
    container: FreeCAD.DocumentObject, via: _Via, dimension: UnitDimension
) -> None:
    delta_mm, axis = _DELTAS_MM[dimension]
    if via == "session":
        session = Session(container)
        session.open()
        try:
            size_mm = session.unit_dimension_mm(dimension) + delta_mm
            assert session.resize(dimension, size_mm) is None
        finally:
            session.close()
        return
    size = unit_size_mm(container)
    components_mm = [size.x_mm, size.y_mm, size.z_mm]
    components_mm[axis] += delta_mm
    resize_unit(container, Vec3(*components_mm))


@pytest.mark.parametrize("via", ["unit_ops", "session"])
@pytest.mark.parametrize("dimension", ["width", "depth", "height"])
def test_a_magic_start_back_follows_a_resize(
    magic_start: FreeCAD.DocumentObject, via: _Via, dimension: UnitDimension
) -> None:
    doc = magic_start.Document
    rotation_before = _placement(doc, "Back").Rotation

    _resize(magic_start, via, dimension)

    back = _bound(doc, "Back")
    left = _bound(doc, "Left")
    right = _bound(doc, "Right")
    floor = _bound(doc, "Floor")
    # Its front face on the sides' rear face, 3 mm thick; across both
    # sides' outer faces; from the floor's underside to the sides' top.
    _assert_bound(back, (left[0], right[1], left[3], left[3] + 3.0, floor[4], left[5]))
    assert _placement(doc, "Back").Rotation.isSame(rotation_before, 1e-9)

    rescan_unit(magic_start)
    _assert_bound(_bound(doc, "Back"), back)


def test_moving_the_floor_moves_the_backs_bottom_edge_only(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    doc = magic_start.Document
    back_before = _bound(doc, "Back")
    session = Session(magic_start)
    session.open()
    try:
        # The plinth below the floor reads as locked.
        assert session.unlock_holders("Floor") is None
        assert session.begin_drag("Floor", Vec3(250.0, 100.0, 105.0)) is None
        assert session.drag_to(Vec3(250.0, 100.0, 125.0)) is None
        session.end_drag()
    finally:
        session.close()

    back = _bound(doc, "Back")
    assert _bound(doc, "Floor")[4] == pytest.approx(120.0, abs=_TOL_MM)
    _assert_bound(back, (*back_before[:4], 120.0, back_before[5]))

    rescan_unit(magic_start)
    _assert_bound(_bound(doc, "Back"), back)


def test_one_undo_takes_back_the_boards_and_the_back_together(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    doc = magic_start.Document
    names = ("Back", "Floor", "Left", "Right", "Top", "Shelf")
    before = [_bound(doc, name) for name in names]
    session = Session(magic_start)
    session.open()
    try:
        assert (
            session.resize("depth", session.unit_dimension_mm("depth") + 50.0) is None
        )
    finally:
        session.close()
    after = [_bound(doc, name) for name in names]
    assert after[0] != before[0]

    doc.undo()
    assert [_bound(doc, name) for name in names] == before
    doc.redo()
    assert [_bound(doc, name) for name in names] == after


def _snapshot(obj: FreeCAD.DocumentObject) -> dict[str, str]:
    """Every property's value but the ones a write may change and the shape
    they produce."""
    written = {"Placement", "Length", "Width", "Height", "Shape"}
    return {
        name: str(obj.getPropertyByName(name))
        for name in obj.PropertiesList
        if name not in written
    }


def test_a_write_changes_nothing_on_a_back_but_its_placement_and_size(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    doc = magic_start.Document
    back = doc.getObject("Back")
    assert back is not None
    before = _snapshot(back)
    material_before = properties.read_material_name(back)

    _resize(magic_start, "unit_ops", "depth")
    _resize(magic_start, "session", "width")
    rescan_unit(magic_start)

    assert doc.getObject("Back") is back
    assert not properties.has_board_properties(back)
    assert _snapshot(back) == before
    assert properties.read_material_name(back) == material_before
    assert cast("_Placeable", back).Label == "Furniture - Back board"


def test_the_unit_size_leaves_out_the_back(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    assert unit_size_mm(magic_start) == Vec3(500.0, 397.0, 760.0)


def test_the_session_lists_the_back_as_following_the_boards(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    session = Session(magic_start)
    session.open()
    try:
        (entry,) = session.untagged
        assert entry.name == "Back"
        assert "follows the unit's boards" in entry.reason
        assert session.resize("width", 600.0) is None
        assert [e.name for e in session.untagged] == ["Back"]
        assert "follows the unit's boards" in session.untagged[0].reason
    finally:
        session.close()


def _replace_back_with_a_notched_one(container: FreeCAD.DocumentObject) -> None:
    """Swap Magic Start's back for a ``Part::Cut`` of the same outline with a
    corner notched out, as an irregular back."""
    doc = container.Document
    blank = cast("_BoxFeature", doc.addObject("Part::Box", "BackBlank"))
    blank.Length, blank.Width, blank.Height = 500.0, 3.0, 660.0
    notch = cast("_BoxFeature", doc.addObject("Part::Box", "BackNotch"))
    notch.Length, notch.Width, notch.Height = 50.0, 3.0, 50.0
    notch.Placement = FreeCAD.Placement(
        FreeCAD.Vector(450.0, 0.0, 610.0), FreeCAD.Rotation()
    )
    cut = cast("_CutFeature", doc.addObject("Part::Cut", "NotchedBack"))
    cut.Base = cast("FreeCAD.DocumentObject", blank)
    cut.Tool = cast("FreeCAD.DocumentObject", notch)
    cut.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0.0, 397.0, 100.0), FreeCAD.Rotation()
    )
    link_group = cast("_LinkGroupObject", container)
    link_group.ElementList = [
        *(obj for obj in link_group.ElementList if obj.Name != "Back"),
        cast("FreeCAD.DocumentObject", cut),
    ]
    doc.removeObject("Back")
    doc.recompute()


def _volume_mm3(doc: FreeCAD.Document, name: str) -> float:
    obj = doc.getObject(name)
    assert obj is not None
    return cast("_ShapeFeature", obj).Shape.Volume


@pytest.mark.parametrize("via", ["unit_ops", "session"])
def test_an_irregular_back_moves_and_keeps_its_shape(
    magic_start: FreeCAD.DocumentObject, via: _Via
) -> None:
    doc = magic_start.Document
    _replace_back_with_a_notched_one(magic_start)
    volume_before_mm3 = _volume_mm3(doc, "NotchedBack")
    before = _bound(doc, "NotchedBack")

    _resize(magic_start, via, "depth")

    after = _bound(doc, "NotchedBack")
    assert _volume_mm3(doc, "NotchedBack") == pytest.approx(
        volume_before_mm3, abs=_TOL_MM
    )
    _assert_bound(after, (before[0], before[1], 447.0, 450.0, before[4], before[5]))

    rescan_unit(magic_start)
    _assert_bound(_bound(doc, "NotchedBack"), after)


def _add_box(
    container: FreeCAD.DocumentObject,
    name: str,
    size_mm: tuple[float, float, float],
    corner_mm: tuple[float, float, float],
    rotation: FreeCAD.Rotation | None = None,
) -> FreeCAD.DocumentObject:
    doc = container.Document
    box = cast("_BoxFeature", doc.addObject("Part::Box", name))
    box.Length, box.Width, box.Height = size_mm
    box.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*corner_mm), rotation or FreeCAD.Rotation()
    )
    obj = cast("FreeCAD.DocumentObject", box)
    if container.isDerivedFrom("App::LinkGroup"):
        link_group = cast("_LinkGroupObject", container)
        link_group.ElementList = [*link_group.ElementList, obj]
    else:
        cast("FreeCAD.DocumentObjectGroup", container).addObject(obj)
    return obj


def _carcass(name: str) -> FreeCAD.DocumentObject:
    """A hand-built 600 x 300 x 900 unit of 18 mm boards, with a divider at
    the middle and no back yet."""
    doc = FreeCAD.newDocument(name)
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    _add_box(container, "Bottom", (600.0, 300.0, 18.0), (0.0, 0.0, 0.0))
    _add_box(container, "Top", (600.0, 300.0, 18.0), (0.0, 0.0, 882.0))
    _add_box(container, "Left", (18.0, 300.0, 864.0), (0.0, 0.0, 18.0))
    _add_box(container, "Right", (18.0, 300.0, 864.0), (582.0, 0.0, 18.0))
    _add_box(container, "Divider", (18.0, 300.0, 864.0), (291.0, 0.0, 18.0))
    doc.recompute()
    return container


def test_removing_the_board_an_edge_follows_leaves_it_at_its_outer_distance() -> None:
    """A per-opening back's right edge lies on the divider; merging the
    divider away succeeds and leaves the edge where it was, and a resize
    then keeps it 309 mm inside the right outer face."""
    container = _carcass("backs_lost_face")
    doc = container.Document
    try:
        _add_box(container, "Back", (273.0, 6.0, 864.0), (18.0, 280.0, 18.0))
        # Adopts the hand-built boards, so a merge deletes the divider.
        rescan_unit(container)
        session = Session(container)
        session.open()
        try:
            session.select("Divider")
            assert session.merge() is None
            assert doc.getObject("Divider") is None
            _assert_bound(_bound(doc, "Back"), (18.0, 291.0, 280.0, 286.0, 18.0, 882.0))
            assert session.resize("width", 700.0) is None
        finally:
            session.close()
        _assert_bound(_bound(doc, "Back"), (18.0, 391.0, 280.0, 286.0, 18.0, 882.0))
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_an_edge_on_no_board_keeps_its_distance_to_the_outer_face() -> None:
    container = _carcass("backs_outer_face")
    doc = container.Document
    try:
        _add_box(container, "Back", (580.0, 3.0, 900.0), (10.0, 300.0, 0.0))
        result = resize_unit(container, Vec3(700.0, 300.0, 900.0))
        assert result.backs == ("Back",)
        _assert_bound(_bound(doc, "Back"), (10.0, 690.0, 300.0, 303.0, 0.0, 900.0))
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_back_left_no_width_refuses_the_edit_by_name() -> None:
    """The back's right edge keeps 300 mm to the right outer face, so a unit
    narrower than that would leave it nothing; the session refuses, naming
    it, and writes nothing."""
    container = _carcass("backs_refused")
    doc = container.Document
    try:
        back = _add_box(container, "Back", (300.0, 3.0, 900.0), (0.0, 300.0, 0.0))
        cast("_Placeable", back).Label = "Plywood back"
        session = Session(container)
        session.open()
        try:
            before = [_bound(doc, n) for n in ("Back", "Right", "Divider")]
            failure = session.resize("width", 280.0)
            assert isinstance(failure, EditFailure), failure
            assert failure.node_id == "Back"
            assert "Plywood back" in failure.message
            assert [_bound(doc, n) for n in ("Back", "Right", "Divider")] == before
        finally:
            session.close()
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_door_and_an_unreadable_part_stay_put_through_every_write(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    doc = magic_start.Document
    link_group = cast("_LinkGroupObject", magic_start)
    door = _add_box(magic_start, "Door", (500.0, 18.0, 660.0), (0.0, -18.0, 100.0))
    skewed = _add_box(
        magic_start,
        "Skewed",
        (100.0, 50.0, 20.0),
        (0.0, 1000.0, 0.0),
        rotation=FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 30.0),
    )
    assert door in link_group.ElementList
    assert skewed in link_group.ElementList
    doc.recompute()
    before = {name: _bound(doc, name) for name in ("Door", "Skewed")}
    edits: list[Callable[[], object]] = [
        lambda: resize_unit(magic_start, Vec3(600.0, 447.0, 800.0)),
        lambda: _resize(magic_start, "session", "height"),
        lambda: rescan_unit(magic_start),
    ]

    for edit in edits:
        edit()
        assert {name: _bound(doc, name) for name in before} == before

    result = rescan_unit(magic_start)
    assert set(result.left_alone) == {"Door", "Skewed"}
    assert result.backs == ("Back",)


def test_with_the_facing_unknown_no_panel_moves() -> None:
    """A thin panel proud of each face: they vote opposite ways and the
    members are flush at both ends, so no front is known and neither
    panel is a back."""
    doc = FreeCAD.newDocument("backs_facing_unknown")
    try:
        container = create_unit(doc)
        _add_box(container, "FrontPanel", (600.0, 3.0, 900.0), (0.0, -3.0, 0.0))
        _add_box(container, "RearPanel", (600.0, 3.0, 900.0), (0.0, 300.0, 0.0))
        doc.recompute()
        before = {n: _bound(doc, n) for n in ("FrontPanel", "RearPanel")}

        result = resize_unit(container, Vec3(700.0, 350.0, 1000.0))

        assert result.backs == ()
        assert set(result.left_alone) == {"FrontPanel", "RearPanel"}
        assert {n: _bound(doc, n) for n in before} == before
    finally:
        FreeCAD.closeDocument(doc.Name)


def _unit_bound(container: FreeCAD.DocumentObject, name: str) -> _Bound:
    """``name``'s bounding box in the unit's frame, nested containers'
    placements included, as ``read_container`` reads it."""
    container.Document.recompute()
    boxes, _skipped, _record = read_container(container)
    (box,) = (box for box in boxes if box.name == name)
    corner, size = box.corner_mm, box.size_mm
    return (
        corner.x_mm,
        corner.x_mm + size.x_mm,
        corner.y_mm,
        corner.y_mm + size.y_mm,
        corner.z_mm,
        corner.z_mm + size.z_mm,
    )


def _assert_back_follows_then_rescans(
    container: FreeCAD.DocumentObject, name: str, size_mm: Vec3, expected: _Bound
) -> None:
    doc = container.Document
    rotation_before = _placement(doc, name).Rotation
    result = resize_unit(container, size_mm)
    assert result.backs == (name,)
    after = _unit_bound(container, name)
    _assert_bound(after, expected)
    assert _placement(doc, name).Rotation.isSame(rotation_before, 1e-9)
    rescan_unit(container)
    _assert_bound(_unit_bound(container, name), after)


def test_a_rotated_box_back_is_resized_along_the_model_axes(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    """Turned a quarter about X, the back's Width runs up the unit and its
    Height runs toward the front, from the Placement's corner at the rear."""
    doc = magic_start.Document
    back = cast("_BoxFeature", doc.getObject("Back"))
    back.Length, back.Width, back.Height = 500.0, 660.0, 3.0
    back.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0.0, 400.0, 100.0),
        FreeCAD.Rotation(FreeCAD.Vector(1.0, 0.0, 0.0), 90.0),
    )
    _assert_bound(_bound(doc, "Back"), (0.0, 500.0, 397.0, 400.0, 100.0, 760.0))

    _assert_back_follows_then_rescans(
        magic_start,
        "Back",
        Vec3(620.0, 447.0, 800.0),
        (0.0, 620.0, 447.0, 450.0, 100.0, 800.0),
    )
    assert (float(back.Length), float(back.Width), float(back.Height)) == pytest.approx(
        (620.0, 700.0, 3.0), abs=_TOL_MM
    )


def test_a_back_in_a_nested_placed_container_lands_in_the_units_frame() -> None:
    container = _carcass("backs_nested")
    doc = container.Document
    try:
        holder = cast(
            "FreeCAD.DocumentObject", doc.addObject("App::Part", "BackHolder")
        )
        cast("_Placeable", holder).Placement = FreeCAD.Placement(
            FreeCAD.Vector(600.0, 400.0, 0.0),
            FreeCAD.Rotation(FreeCAD.Vector(0.0, 0.0, 1.0), 180.0),
        )
        cast("FreeCAD.DocumentObjectGroup", container).addObject(holder)
        _add_box(holder, "Back", (600.0, 3.0, 900.0), (0.0, 97.0, 0.0))
        doc.recompute()
        _assert_bound(
            _unit_bound(container, "Back"), (0.0, 600.0, 300.0, 303.0, 0.0, 900.0)
        )

        _assert_back_follows_then_rescans(
            container,
            "Back",
            Vec3(700.0, 350.0, 1000.0),
            (0.0, 700.0, 350.0, 353.0, 0.0, 1000.0),
        )
        assert _placement(doc, "BackHolder").Base.isEqual(
            FreeCAD.Vector(600.0, 400.0, 0.0), _TOL_MM
        )
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_a_plain_back_that_is_no_part_box_is_moved_and_not_resized() -> None:
    container = _carcass("backs_part_feature")
    doc = container.Document
    try:
        feature = cast("_ShapeFeature", doc.addObject("Part::Feature", "Back"))
        feature.Shape = Part.makeBox(600.0, 3.0, 900.0)
        cast("_Placeable", feature).Placement = FreeCAD.Placement(
            FreeCAD.Vector(0.0, 300.0, 0.0), FreeCAD.Rotation()
        )
        cast("FreeCAD.DocumentObjectGroup", container).addObject(
            cast("FreeCAD.DocumentObject", feature)
        )
        doc.recompute()

        _assert_back_follows_then_rescans(
            container,
            "Back",
            Vec3(700.0, 350.0, 1000.0),
            (0.0, 600.0, 350.0, 353.0, 0.0, 900.0),
        )
    finally:
        FreeCAD.closeDocument(doc.Name)


def test_an_irregular_backs_low_corner_follows_the_floor(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    doc = magic_start.Document
    _replace_back_with_a_notched_one(magic_start)
    volume_before_mm3 = _volume_mm3(doc, "NotchedBack")
    before = _bound(doc, "NotchedBack")
    session = Session(magic_start)
    session.open()
    try:
        assert session.unlock_holders("Floor") is None
        assert session.begin_drag("Floor", Vec3(250.0, 100.0, 105.0)) is None
        assert session.drag_to(Vec3(250.0, 100.0, 125.0)) is None
        session.end_drag()
    finally:
        session.close()

    after = _bound(doc, "NotchedBack")
    _assert_bound(after, (*before[:4], 120.0, before[5] + 20.0))
    assert _volume_mm3(doc, "NotchedBack") == pytest.approx(
        volume_before_mm3, abs=_TOL_MM
    )
    rescan_unit(magic_start)
    _assert_bound(_bound(doc, "NotchedBack"), after)


def test_a_tagged_back_is_listed_before_and_after_a_write(
    magic_start: FreeCAD.DocumentObject,
) -> None:
    """A back carrying board properties is kept by every write, so the
    list shows it from the start, not only once a write has run."""
    back = magic_start.Document.getObject("Back")
    assert back is not None
    properties.ensure_board_properties(back)
    session = Session(magic_start)
    session.open()
    try:
        assert [e.name for e in session.untagged] == ["Back"]
        assert session.resize("width", 600.0) is None
        assert [e.name for e in session.untagged] == ["Back"]
        assert magic_start.Document.getObject("Back") is back
    finally:
        session.close()
