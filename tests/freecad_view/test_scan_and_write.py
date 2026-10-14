"""The scan and write manual QA cases, run through the toolbar commands and
the task panel's own buttons with FreeCAD's 3D view up."""

import gc
from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.temp_dirs import export_path
from freecad.Shelving.unit_ops import create_unit
from tests.freecad_view.view import ViewDriver

# How far a highlighted board's color moves from its plain one, summed over
# red, green and blue; shading moves an untouched board by a few units.
_HIGHLIGHT_SHIFT = 60
_STILL = 10
_CAMERA_SETTLE_MS = 1500


class _BoxFeature(Protocol):
    Length: float
    Width: float
    Height: float
    Placement: FreeCAD.Placement


class _Shaped(Protocol):
    Shape: "_Shape"


class _Shape(Protocol):
    BoundBox: FreeCAD.BoundBox


Snapshot = list[tuple[str, float, float, float, FreeCAD.Placement]]


@pytest.fixture(autouse=True)
def _shelving_commands(driver: ViewDriver) -> Iterator[None]:
    """The workbench active, as a user's toolbar click needs: its commands
    register when it first activates."""
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    driver.pump()
    yield
    if FreeCADGui.Control.activeDialog():
        FreeCADGui.Control.closeDialog()
        driver.pump()


def _document() -> FreeCAD.Document:
    return cast("FreeCAD.Document", FreeCAD.ActiveDocument)


def _add_box(
    container: FreeCAD.DocumentObject,
    name: str,
    size_mm: tuple[float, float, float],
    corner_mm: tuple[float, float, float],
    angle_deg: float = 0.0,
) -> None:
    doc = _document()
    box = cast("_BoxFeature", doc.addObject("Part::Box", name))
    box.Length, box.Width, box.Height = size_mm
    box.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*corner_mm), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), angle_deg)
    )
    cast("FreeCAD.DocumentObjectGroup", container).addObject(
        cast("FreeCAD.DocumentObject", box)
    )
    doc.recompute()


def _test_unit() -> FreeCAD.DocumentObject:
    """The QA wizard's TestUnit: a hand-built closed unit with one shelf."""
    container = cast(
        "FreeCAD.DocumentObject", _document().addObject("App::Part", "TestUnit")
    )
    _add_box(container, "Bottom", (600.0, 300.0, 18.0), (0.0, 0.0, 0.0))
    _add_box(container, "Top", (600.0, 300.0, 18.0), (0.0, 0.0, 582.0))
    _add_box(container, "LeftSide", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
    _add_box(container, "RightSide", (18.0, 300.0, 564.0), (582.0, 0.0, 18.0))
    _add_box(container, "Shelf", (564.0, 300.0, 18.0), (18.0, 0.0, 291.0))
    return container


def _snapshot() -> Snapshot:
    return [
        (obj.Name, box.Length, box.Width, box.Height, box.Placement)
        for obj in _document().Objects
        if obj.isDerivedFrom("Part::Box")
        for box in [cast("_BoxFeature", obj)]
    ]


def _run(command: str, selected: FreeCAD.DocumentObject, driver: ViewDriver) -> None:
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(selected)
    FreeCADGui.runCommand(command)
    driver.pump(400)


def _edit_unit(container: FreeCAD.DocumentObject, driver: ViewDriver) -> EditUnitPanel:
    """Run Edit Unit on ``container`` and return the panel it opened."""
    earlier = {id(obj) for obj in gc.get_objects() if isinstance(obj, EditUnitPanel)}
    _run("Shelving_EditUnit", container, driver)
    (panel,) = [
        obj
        for obj in gc.get_objects()
        if isinstance(obj, EditUnitPanel) and id(obj) not in earlier
    ]
    assert FreeCADGui.Control.activeDialog()
    return panel


def _click_task_button(text: str, driver: ViewDriver) -> None:
    """Press the open task dialog's ``text`` button. In a fresh profile
    FreeCAD 1.1 docks Tasks in the right-hand overlay panel, which stays
    hidden until hovered, so the button is pressed with ``click``, the
    signal a mouse click on it emits."""
    main_window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    (button,) = [
        button
        for box in main_window.findChildren(QtWidgets.QDialogButtonBox)
        for button in box.buttons()
        if button.text() == text
    ]
    button.click()
    driver.pump(400)


def _nodes(region: Region) -> list[Region | Board]:
    found: list[Region | Board] = [region]
    if isinstance(region, Division):
        for item in region.items:
            found.extend(_nodes(item) if not isinstance(item, Board) else [item])
    return found


def _notification_count() -> int:
    main_window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    button = main_window.statusBar().findChild(
        QtWidgets.QPushButton, "notificationArea"
    )
    assert button is not None
    text = button.text()
    return int(text) if text.isdigit() else 0


def _shift(a: QtGui.QColor, b: QtGui.QColor) -> int:
    return (
        abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
    )


def test_edit_unit_reads_a_hand_built_unit_and_cancel_changes_nothing(
    driver: ViewDriver,
) -> None:
    container = _test_unit()
    before = _snapshot()
    undo_before = _document().UndoNames
    panel = _edit_unit(container, driver)
    nodes = _nodes(panel.session.unit.root)
    assert sum(isinstance(node, Bay) for node in nodes) == 2
    assert "Shelf" in {node.id for node in nodes if isinstance(node, Board)}
    assert panel.session.left_alone == ()
    _click_task_button("Cancel", driver)
    assert not FreeCADGui.Control.activeDialog()
    assert _snapshot() == before
    assert _document().UndoNames == undo_before


def test_a_part_turned_off_axis_is_left_alone_with_its_reason(
    driver: ViewDriver,
) -> None:
    container = _test_unit()
    _add_box(container, "Skewed", (100.0, 50.0, 20.0), (0.0, 400.0, 0.0), 30.0)
    panel = _edit_unit(container, driver)
    assert list(panel.untagged_checks) == ["Skewed"]
    assert (
        panel.untagged_checks["Skewed"].accessibleName().endswith(": not axis-aligned")
    )
    _click_task_button("Cancel", driver)
    skewed = _document().getObject("Skewed")
    assert (
        skewed is not None
        and skewed in cast("FreeCAD.DocumentObjectGroup", container).Group
    )


def test_export_boxes_writes_the_file_and_reports_where(
    driver: ViewDriver, capsys: pytest.CaptureFixture[str]
) -> None:
    container = _test_unit()
    _add_box(container, "Skewed", (100.0, 50.0, 20.0), (0.0, 400.0, 0.0), 30.0)
    path = export_path(container)
    path.unlink(missing_ok=True)
    _run("Shelving_ExportBoxes", container, driver)
    assert path.is_file()
    # FreeCAD shows Python's printed output in the Report view; pytest
    # captures it first.
    assert f"exported 5 box(es), skipped 1: {path}" in capsys.readouterr().out


def test_a_refusal_notifies_selects_and_highlights_the_overlap(
    driver: ViewDriver,
) -> None:
    container = _test_unit()
    _add_box(container, "Overlap", (18.0, 300.0, 564.0), (0.0, 0.0, 18.0))
    driver.view.viewFront()
    driver.view.fitAll()
    # Both camera moves animate when navigation animations are on.
    driver.pump(_CAMERA_SETTLE_MS)
    FreeCADGui.Selection.clearSelection()
    left = FreeCAD.Vector(9.0, 0.0, 300.0)
    right = FreeCAD.Vector(591.0, 0.0, 300.0)
    plain = driver.grab()
    notifications = _notification_count()

    _run("Shelving_EditUnit", container, driver)

    assert not FreeCADGui.Control.activeDialog()
    assert _notification_count() == notifications + 1
    selected = cast("list[FreeCAD.DocumentObject]", FreeCADGui.Selection.getSelection())
    assert {obj.Name for obj in selected} == {"Overlap", "LeftSide"}
    shown = driver.grab()
    highlighted = driver.color_at(shown, left)
    left_shift = _shift(driver.color_at(plain, left), highlighted)
    right_shift = _shift(driver.color_at(plain, right), driver.color_at(shown, right))
    assert left_shift > _HIGHLIGHT_SHIFT, left_shift
    # FreeCAD 1.1's default selection color is a blue; a board that merely
    # vanished or turned gray would not lean blue.
    assert highlighted.blue() > highlighted.red() + 20, highlighted.name()
    assert right_shift < _STILL, right_shift


def test_a_board_moved_within_the_clearance_is_corrected(driver: ViewDriver) -> None:
    container = create_unit(_document())
    side = cast("_BoxFeature", _document().getObject("left_side"))
    placement = side.Placement
    placement.Base.x = 2.0
    side.Placement = placement
    _document().recompute()

    height = _edit_unit(container, driver).unit_fields["height"].line_edit
    height.setFocus()
    height.selectAll()
    QtTest.QTest.keyClicks(height, "1010")
    QtTest.QTest.keyClick(height, QtCore.Qt.Key.Key_Return)
    driver.pump()
    _click_task_button("OK", driver)

    assert not FreeCADGui.Control.activeDialog()
    assert abs(side.Placement.Base.x) < 1e-6
    shape = cast("_Shaped", side).Shape
    assert abs(shape.BoundBox.ZLength - 974.0) < 1e-6
