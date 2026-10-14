"""The view tier's own footing: a real 3D view, and helpers whose events
FreeCAD treats as a user's."""

from typing import Any, Protocol, cast

import FreeCAD
import FreeCADGui
from pivy import coin

from tests.freecad_view.view import ViewDriver

# pivy ships no type information.
_Coin = Any


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float


def _box(name: str, size_mm: float) -> FreeCAD.DocumentObject:
    doc = cast("FreeCAD.Document", FreeCAD.ActiveDocument)
    box = cast("_BoxFeature", doc.addObject("Part::Box", name))
    box.Length = box.Width = box.Height = size_mm
    doc.recompute()
    return cast("FreeCAD.DocumentObject", box)


def test_the_view_is_a_real_3d_view(driver: ViewDriver) -> None:
    width_px, height_px = driver.view.getSize()
    assert width_px > 0 and height_px > 0
    assert driver.viewport.isVisible()


def test_a_click_on_a_face_selects_its_box(driver: ViewDriver) -> None:
    _box("Box", 100.0)
    driver.view.viewFront()
    driver.view.fitAll()
    driver.pump()
    # The middle of the front face (y = 0), which faces the camera.
    driver.click(FreeCAD.Vector(50, 0, 50))
    picked = FreeCADGui.Selection.getSelectionEx()
    assert [entry.ObjectName for entry in picked] == ["Box"]


def test_a_drag_along_a_draggers_axis_moves_it(driver: ViewDriver) -> None:
    _box("Box", 100.0)
    driver.view.viewFront()
    driver.view.fitAll()
    driver.pump()
    # In front of the box, so its arrow is what the pointer meets; scaled so
    # the arrow is many pixels long. The arrow runs along its local x, which
    # the front view shows left to right.
    holder: _Coin = coin.SoSeparator()
    transform: _Coin = coin.SoTransform()
    transform.translation.setValue(50, -20, 50)
    transform.scaleFactor.setValue(20, 20, 20)
    dragger: _Coin = coin.SoTranslate1Dragger()
    holder.addChild(transform)
    holder.addChild(dragger)
    scene: _Coin = cast("_Coin", FreeCADGui.ActiveDocument).ActiveView.getSceneGraph()
    scene.addChild(holder)
    try:
        driver.pump()
        driver.drag(FreeCAD.Vector(60, -20, 50), FreeCAD.Vector(80, -20, 50))
        moved = float(dragger.translation.getValue()[0])
        assert moved > 0.1, moved
    finally:
        scene.removeChild(holder)


def test_std_undo_reaches_the_document_through_the_view(driver: ViewDriver) -> None:
    doc = cast("FreeCAD.Document", FreeCAD.ActiveDocument)
    doc.UndoMode = 1
    doc.openTransaction("Add box")
    _box("Box", 10.0)
    doc.commitTransaction()
    assert doc.getObject("Box") is not None
    FreeCADGui.runCommand("Std_Undo")
    driver.pump()
    assert doc.getObject("Box") is None
