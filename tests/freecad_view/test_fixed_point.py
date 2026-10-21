"""The fixed point's marker in Edit Unit's 3D view: drawn at the point that
stays put, over the boards, facing the camera from any side, and never in
the way of a click."""

from typing import Protocol, cast

import FreeCAD
import pytest
from PySide6 import QtCore, QtGui

from freecad.Shelving.core.edit import fixed_point_mm
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import UnitDimension
from freecad.Shelving.editor.view_editor import View3D, ViewEditor, container_placement
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import (
    add_board,
    click_task_button,
    edit_unit,
    editor_of,
    gui_step,
    picked,
)
from tests.freecad_view.view import ViewDriver

# Coin holds the marker's point in single precision.
_NODE_TOL_MM = 1e-3
# How far from the marker's center, in logical pixels, its hub is solid
# whichever way: past the hole's antialiased edge, short of the hub's.
_HUB_PX = 4.0


class _Placed(Protocol):
    Placement: FreeCAD.Placement


def _turn(container: FreeCAD.DocumentObject) -> None:
    cast("_Placed", container).Placement = FreeCAD.Placement(
        FreeCAD.Vector(400.0, -250.0, 30.0),
        FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 30),
    )
    container.Document.recompute()


def _expected(panel: EditUnitPanel) -> FreeCAD.Vector:
    """The fixed point in document coordinates, composed here rather than
    taken from the editor."""
    point = fixed_point_mm(panel.session.unit)
    return container_placement(panel.session.container).multVec(
        FreeCAD.Vector(point.x_mm, point.y_mm, point.z_mm)
    )


def _marker(editor: ViewEditor) -> FreeCAD.Vector:
    (at,) = overlay_nodes.markers(editor.root)
    return at


def _assert_marker_on_fixed_point(panel: EditUnitPanel) -> None:
    at = _marker(editor_of(panel))
    assert (at - _expected(panel)).Length < _NODE_TOL_MM, (at, _expected(panel))


def _choose(panel: EditUnitPanel, dimension: UnitDimension, index: int) -> None:
    panel.fixed_combos[dimension].setCurrentIndex(index)


def _look_from(view: View3D, rotation: FreeCAD.Rotation, driver: ViewDriver) -> None:
    view.setCameraOrientation(rotation)
    for _ in range(60):
        driver.pump(50)
        if view.getCameraOrientation().isSame(rotation, 1e-6):
            break
    driver.pump()


def _is_marker_rgb(editor: ViewEditor, color: QtGui.QColor) -> bool:
    rgb = (color.redF(), color.greenF(), color.blueF())
    return all(
        abs(got - want) < 3 / 255
        for got, want in zip(rgb, editor.style.marker_rgb, strict=True)
    )


def _shows_marker(driver: ViewDriver, editor: ViewEditor) -> bool:
    """Whether the screen shows the marker's color on its hub left, right,
    above and below the hole at its center. Each sample may land a pixel
    off: the projected point is rounded to a whole pixel, and the image's
    16-pixel side has no center pixel."""
    image = driver.grab()
    ratio = editor.viewport.devicePixelRatioF()
    x_px, y_px = editor.view.getPointOnViewport(_marker(editor))
    row_px = editor.view.getSize()[1] - y_px - 1
    reach_px = round(_HUB_PX * ratio)
    for dx_px, dy_px in ((reach_px, 0), (-reach_px, 0), (0, reach_px), (0, -reach_px)):
        if not any(
            _is_marker_rgb(
                editor,
                image.pixelColor(x_px + dx_px + slop_x, row_px + dy_px + slop_y),
            )
            for slop_x in (-1, 0, 1)
            for slop_y in (-1, 0, 1)
        ):
            return False
    return True


def test_the_marker_follows_the_fixed_point(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    """On a moved and turned unit, the marker starts on the minimum corner
    and moves with each choice, stays on the fixed point through a resize,
    and goes back and forth with Undo and Redo."""
    _turn(unit)
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    _assert_marker_on_fixed_point(panel)
    corner = _marker(editor)
    assert (corner - container_placement(unit).Base).Length < _NODE_TOL_MM

    _choose(panel, "width", 1)
    _choose(panel, "height", 2)
    _choose(panel, "depth", 2)
    driver.pump()
    assert panel.session.unit.fixed_point.x == "center"
    _assert_marker_on_fixed_point(panel)
    moved = _marker(editor)
    assert (moved - corner).Length > 100.0

    assert panel.session.resize("height", 1100.0) is None
    panel._refresh()
    driver.pump()
    _assert_marker_on_fixed_point(panel)
    assert (_marker(editor) - moved).Length < _NODE_TOL_MM
    assert panel.session.resize("width", 800.0) is None
    panel._refresh()
    driver.pump()
    _assert_marker_on_fixed_point(panel)
    assert (_marker(editor) - moved).Length < _NODE_TOL_MM

    for _ in range(3):
        gui_step("Std_Undo", driver)
    _assert_marker_on_fixed_point(panel)
    assert panel.session.unit.fixed_point.x == "center"
    assert panel.session.unit.fixed_point.y == "min"
    assert panel.session.unit.fixed_point.z == "max"
    gui_step("Std_Undo", driver)
    _assert_marker_on_fixed_point(panel)
    assert panel.session.unit.fixed_point.z == "min"
    gui_step("Std_Redo", driver)
    _assert_marker_on_fixed_point(panel)
    assert panel.session.unit.fixed_point.z == "max"
    click_task_button("Close", driver)


def test_the_marker_shows_over_the_boards_from_either_side_and_clicks_pass_through(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    """Fixed at the unit's center, the marker lies inside the shelf added
    across the middle: it is drawn over the shelf's faces from the front
    and from behind, and a click on it picks and selects the shelf."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    shelf = add_board(panel, "vertical", driver)
    for dimension in ("width", "height", "depth"):
        _choose(panel, cast("UnitDimension", dimension), 1)
    driver.pump()
    at = _marker(editor)
    space = panel.session.spaces[shelf]
    assert space.origin.z_mm < at.z < space.max_corner().z_mm
    assert _shows_marker(driver, editor)

    board, component = picked(editor, at)
    assert board == shelf, (board, component)
    editor.select(None)
    driver.pump()
    assert panel.session.selected_id is None
    driver.click(at)
    assert panel.session.selected_id == shelf

    view = cast("View3D", driver.view)
    front = view.getCameraOrientation()
    _look_from(
        view, front.multiply(FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 180)), driver
    )
    assert editor.frame.side == "back"
    _assert_marker_on_fixed_point(panel)
    assert _shows_marker(driver, editor)
    # Turned off square, the image still faces the camera, unskewed.
    _look_from(
        view, front.multiply(FreeCAD.Rotation(FreeCAD.Vector(1, 1, 0), 50)), driver
    )
    _assert_marker_on_fixed_point(panel)
    assert _shows_marker(driver, editor)
    click_task_button("Close", driver)


def test_the_marker_redraws_for_a_screen_of_another_pixel_ratio(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    viewer = editor._viewer
    first = round(16 * viewer.devicePixelRatioF())
    assert editor.marker_image.size() == QtCore.QSize(first, first)
    ratio = 2 * viewer.devicePixelRatioF()
    monkeypatch.setattr(viewer, "devicePixelRatioF", lambda: ratio)
    QtCore.QCoreApplication.sendEvent(
        editor.viewport, QtCore.QEvent(QtCore.QEvent.Type.DevicePixelRatioChange)
    )
    driver.pump()
    device_px = round(16 * ratio)
    assert editor.marker_image.size() == QtCore.QSize(device_px, device_px)
    monkeypatch.undo()
    click_task_button("Close", driver)
