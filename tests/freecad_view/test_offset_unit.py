"""Edit Unit on a unit whose boards do not start at its container's origin:
the openings are drawn on the boards, and a drag moves a board by the
distance dragged."""

from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest

from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.view_editor import ViewEditor, container_placement
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import add_board, click_task_button, edit_unit, editor_of
from tests.freecad_view.view import ViewDriver

_CORNER_MM = (100.0, -300.0, 50.0)
_WIDTH_MM = 600.0
_DEPTH_MM = 300.0
_HEIGHT_MM = 900.0
_T_MM = 18.0
_TOL_MM = 1e-6
# Coin holds the drawn coordinates in single precision.
_DRAWN_TOL_MM = 0.01


class _Placed(Protocol):
    Placement: FreeCAD.Placement


class _BoxFeature(_Placed, Protocol):
    Length: float
    Width: float
    Height: float


def _add_box(
    container: FreeCAD.DocumentObject,
    name: str,
    size_mm: tuple[float, float, float],
    offset_mm: tuple[float, float, float],
) -> None:
    doc = container.Document
    box = cast("_BoxFeature", doc.addObject("Part::Box", name))
    box.Length, box.Width, box.Height = size_mm
    box.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*(c + o for c, o in zip(_CORNER_MM, offset_mm, strict=True))),
        FreeCAD.Rotation(),
    )
    cast("FreeCAD.DocumentObjectGroup", container).addObject(
        cast("FreeCAD.DocumentObject", box)
    )


@pytest.fixture(
    params=[pytest.param("in place", marks=pytest.mark.full_only), "moved and turned"]
)
def offset_unit(
    request: pytest.FixtureRequest, driver: ViewDriver
) -> Iterator[FreeCAD.DocumentObject]:
    """A four-board carcass built by hand with its minimum corner at
    ``_CORNER_MM`` in its ``App::Part``, which is itself either at the
    document origin or moved and turned."""
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = cast("FreeCAD.Document", FreeCAD.ActiveDocument)
    doc.UndoMode = 1
    doc.openTransaction("Build Unit")
    container = cast("FreeCAD.DocumentObject", doc.addObject("App::Part", "Unit"))
    side_mm = (_T_MM, _DEPTH_MM, _HEIGHT_MM - 2 * _T_MM)
    plank_mm = (_WIDTH_MM, _DEPTH_MM, _T_MM)
    _add_box(container, "Bottom", plank_mm, (0.0, 0.0, 0.0))
    _add_box(container, "Top", plank_mm, (0.0, 0.0, _HEIGHT_MM - _T_MM))
    _add_box(container, "Left", side_mm, (0.0, 0.0, _T_MM))
    _add_box(container, "Right", side_mm, (_WIDTH_MM - _T_MM, 0.0, _T_MM))
    if request.param == "moved and turned":
        cast("_Placed", container).Placement = FreeCAD.Placement(
            FreeCAD.Vector(400.0, -250.0, 30.0),
            FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 30),
        )
    doc.commitTransaction()
    doc.recompute()
    driver.pump()
    yield container
    if FreeCADGui.Control.activeDialog():
        FreeCADGui.Control.closeDialog()
        driver.pump()


def _bays(region: Region) -> list[str]:
    if isinstance(region, Bay):
        return [region.id]
    if not isinstance(region, Division):
        return []
    return [
        found
        for item in region.items
        if not isinstance(item, Board)
        for found in _bays(item)
    ]


def _corners(space: Space) -> list[FreeCAD.Vector]:
    low, high = space.origin, space.max_corner()
    return [
        FreeCAD.Vector(x_mm, y_mm, z_mm)
        for x_mm in (low.x_mm, high.x_mm)
        for y_mm in (low.y_mm, high.y_mm)
        for z_mm in (low.z_mm, high.z_mm)
    ]


def _document_box(container: FreeCAD.DocumentObject, name: str) -> Space:
    """Where board ``name`` is in ``container``'s coordinates, read from
    the document."""
    box = cast("_BoxFeature", container.Document.getObject(name))
    base = box.Placement.Base
    return Space(
        origin=Vec3(float(base.x), float(base.y), float(base.z)),
        size=Vec3(float(box.Length), float(box.Width), float(box.Height)),
    )


def _facing_corners(
    editor: ViewEditor, container: FreeCAD.DocumentObject, space: Space
) -> list[FreeCAD.Vector]:
    """The four corners, in document coordinates, of the face of ``space``
    toward the camera. ``space`` is in ``container``'s coordinates."""
    placement = container_placement(container)
    corners = [placement.multVec(corner) for corner in _corners(space)]
    toward = editor.to_document(0.0, 0.0, editor.frame.z_sign) - editor.to_document(
        0.0, 0.0
    )
    nearest = max(corner.dot(toward) for corner in corners)
    return [c for c in corners if abs(c.dot(toward) - nearest) <= _TOL_MM]


def _assert_on_face(point: FreeCAD.Vector, corners: list[FreeCAD.Vector]) -> None:
    assert len(corners) == 4
    assert min((point - corner).Length for corner in corners) <= _TOL_MM, (
        point,
        corners,
    )


def _assert_openings_on_bays(
    container: FreeCAD.DocumentObject, panel: EditUnitPanel
) -> None:
    """Every corner of every opening the editor plans and draws lies on a
    corner of that bay's face toward the camera in document coordinates."""
    editor = editor_of(panel)
    session = panel.session
    bays = _bays(session.unit.root)
    planned = {face.region_id: face.rect for face in editor.overlay.faces}
    assert sorted(planned) == sorted(bays)
    drawn = overlay_nodes.faces(editor.root)
    assert len(drawn) == len(bays)
    for bay_id in bays:
        corners = _facing_corners(editor, container, session.spaces[bay_id])
        rect = planned[bay_id]
        planned_corners = [
            editor.to_document(h_mm, v_mm)
            for h_mm, v_mm in (
                (rect.h0_mm, rect.v0_mm),
                (rect.h1_mm, rect.v0_mm),
                (rect.h1_mm, rect.v1_mm),
                (rect.h0_mm, rect.v1_mm),
            )
        ]
        for point in planned_corners:
            _assert_on_face(point, corners)
        assert any(
            all(
                (point - got).Length <= _DRAWN_TOL_MM
                for point, got in zip(planned_corners, face, strict=True)
            )
            for face in drawn
        ), (bay_id, planned_corners, drawn)


def test_each_opening_is_drawn_on_its_boards(
    offset_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(offset_unit, driver)
    editor = editor_of(panel)
    # The one opening, against the boards as the document holds them.
    left = _document_box(offset_unit, "Left")
    right = _document_box(offset_unit, "Right")
    bottom = _document_box(offset_unit, "Bottom")
    top = _document_box(offset_unit, "Top")
    opening = Space(
        origin=Vec3(left.max_corner().x_mm, left.origin.y_mm, bottom.max_corner().z_mm),
        size=Vec3(
            right.origin.x_mm - left.max_corner().x_mm,
            _DEPTH_MM,
            top.origin.z_mm - bottom.max_corner().z_mm,
        ),
    )
    (face,) = editor.overlay.faces
    corners = _facing_corners(editor, offset_unit, opening)
    for h_mm, v_mm in (
        (face.rect.h0_mm, face.rect.v0_mm),
        (face.rect.h1_mm, face.rect.v1_mm),
    ):
        _assert_on_face(editor.to_document(h_mm, v_mm), corners)
    _assert_openings_on_bays(offset_unit, panel)
    add_board(panel, "horizontal", driver)
    add_board(panel, "vertical", driver)
    _assert_openings_on_bays(offset_unit, panel)
    click_task_button("Close", driver)


def _arrow_point(editor: ViewEditor) -> FreeCAD.Vector:
    arrow = editor.arrow
    assert arrow is not None
    return editor.to_document(*arrow.at_mm, editor.frame.z_sign * 2.0)


def test_a_drag_moves_the_shelf_by_the_distance_dragged(
    offset_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(offset_unit, driver)
    editor = editor_of(panel)
    session = panel.session
    shelf = add_board(panel, "vertical", driver)
    arrow = editor.arrow
    assert arrow is not None and arrow.board_id == shelf
    placement = container_placement(offset_unit)
    direction = arrow.direction
    up = placement.Rotation.multVec(
        FreeCAD.Vector(direction.x_mm, direction.y_mm, direction.z_mm)
    )
    distance_mm = 60.0
    start = _arrow_point(editor)
    end = start + up * distance_mm
    start_px = driver.qt_point(start)
    end_px = driver.qt_point(end)
    # The pointer lands on whole pixels, so the drag is good to a pixel.
    px_per_mm = (end_px - start_px).manhattanLength() / distance_mm
    tol_mm = 1.5 / px_per_mm
    shelf_obj = cast("_Placed", offset_unit.Document.getObject(shelf))
    before = placement.multVec(shelf_obj.Placement.Base)
    driver.drag(start_px, end_px)
    driver.pump()
    after = placement.multVec(shelf_obj.Placement.Base)
    moved = after - before
    assert abs(moved.dot(up) - distance_mm) <= tol_mm, (moved, tol_mm)
    assert (moved - up * moved.dot(up)).Length <= _TOL_MM, moved
    low = session.spaces[shelf].origin
    assert (
        shelf_obj.Placement.Base - FreeCAD.Vector(low.x_mm, low.y_mm, low.z_mm)
    ).Length <= _TOL_MM
    click_task_button("Close", driver)
