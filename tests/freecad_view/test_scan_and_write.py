"""The scan and write manual QA cases, run through the toolbar commands and
the task panel's own buttons with FreeCAD's 3D view up."""

from collections.abc import Iterator
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtGui, QtTest

from freecad.Shelving.core.layout import Bay, Board, Division, Region
from freecad.Shelving.qa import actions as qa_actions
from freecad.Shelving.temp_dirs import export_path
from freecad.Shelving.unit_ops import create_unit
from tests.freecad_view.editor import (
    click_task_button,
    edit_unit,
    notification_count,
    run_command,
)
from tests.freecad_view.view import ViewDriver

# How far a highlighted board's color moves from its plain one, summed over
# red, green and blue; shading moves an untouched board by a few units.
_HIGHLIGHT_SHIFT = 60
_STILL = 10


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


def _add_skewed_box(container: FreeCAD.DocumentObject) -> None:
    """A box turned 30 degrees about z, which Edit Unit leaves alone."""
    doc = _document()
    box = cast("_BoxFeature", doc.addObject("Part::Box", "Skewed"))
    box.Length, box.Width, box.Height = 100.0, 50.0, 20.0
    box.Placement = FreeCAD.Placement(
        FreeCAD.Vector(0.0, 400.0, 0.0), FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 30.0)
    )
    cast("FreeCAD.DocumentObjectGroup", container).addObject(
        cast("FreeCAD.DocumentObject", box)
    )
    doc.recompute()


def _test_unit() -> tuple[FreeCAD.DocumentObject, ViewDriver]:
    """The QA wizard's TestUnit, in the new document its action opens, and a
    driver for that document's 3D view."""
    qa_actions.test_unit()
    view = ViewDriver.for_active_view()
    return cast("FreeCAD.DocumentObject", _document().getObject("TestUnit")), view


def _snapshot() -> Snapshot:
    return [
        (obj.Name, box.Length, box.Width, box.Height, box.Placement)
        for obj in _document().Objects
        if obj.isDerivedFrom("Part::Box")
        for box in [cast("_BoxFeature", obj)]
    ]


def _nodes(region: Region) -> list[Region | Board]:
    found: list[Region | Board] = [region]
    if isinstance(region, Division):
        for item in region.items:
            found.extend(_nodes(item) if not isinstance(item, Board) else [item])
    return found


def _shift(a: QtGui.QColor, b: QtGui.QColor) -> int:
    return (
        abs(a.red() - b.red()) + abs(a.green() - b.green()) + abs(a.blue() - b.blue())
    )


def test_edit_unit_reads_a_hand_built_unit_and_close_changes_nothing(
    driver: ViewDriver,
) -> None:
    container, _ = _test_unit()
    before = _snapshot()
    undo_before = _document().UndoNames
    panel = edit_unit(container, driver)
    nodes = _nodes(panel.session.unit.root)
    assert sum(isinstance(node, Bay) for node in nodes) == 2
    assert "Shelf" in {node.id for node in nodes if isinstance(node, Board)}
    assert panel.session.untagged == ()
    click_task_button("Close", driver)
    assert not FreeCADGui.Control.activeDialog()
    assert _snapshot() == before
    assert _document().UndoNames == undo_before


def test_a_part_turned_off_axis_is_left_alone_with_its_reason(
    driver: ViewDriver,
) -> None:
    container, _ = _test_unit()
    _add_skewed_box(container)
    panel = edit_unit(container, driver)
    assert list(panel.untagged_checks) == ["Skewed"]
    assert (
        panel.untagged_checks["Skewed"].accessibleName().endswith(": not axis-aligned")
    )
    click_task_button("Close", driver)
    skewed = _document().getObject("Skewed")
    assert (
        skewed is not None
        and skewed in cast("FreeCAD.DocumentObjectGroup", container).Group
    )


def test_export_boxes_writes_the_file_and_reports_where(
    driver: ViewDriver, capsys: pytest.CaptureFixture[str]
) -> None:
    container, _ = _test_unit()
    _add_skewed_box(container)
    path = export_path(container)
    path.unlink(missing_ok=True)
    run_command("Shelving_ExportBoxes", container, driver)
    assert path.is_file()
    # FreeCAD shows Python's printed output in the Report view; pytest
    # captures it first.
    assert f"exported 5 box(es), skipped 1: {path}" in capsys.readouterr().out


def test_a_refusal_notifies_selects_and_highlights_the_overlap(
    driver: ViewDriver,
) -> None:
    container, unit_view = _test_unit()
    qa_actions.add_overlap_box()
    unit_view.view.viewFront()
    unit_view.view.fitAll()
    # Both camera moves animate when navigation animations are on.
    driver.pump()
    FreeCADGui.Selection.clearSelection()
    left = FreeCAD.Vector(9.0, 0.0, 300.0)
    right = FreeCAD.Vector(591.0, 0.0, 300.0)
    plain = unit_view.grab()
    notifications = notification_count()

    run_command("Shelving_EditUnit", container, driver)

    assert not FreeCADGui.Control.activeDialog()
    assert notification_count() == notifications + 1
    selected = cast("list[FreeCAD.DocumentObject]", FreeCADGui.Selection.getSelection())
    assert {obj.Name for obj in selected} == {"Overlap", "LeftSide"}
    shown = unit_view.grab()
    highlighted = unit_view.color_at(shown, left)
    left_shift = _shift(unit_view.color_at(plain, left), highlighted)
    right_shift = _shift(
        unit_view.color_at(plain, right), unit_view.color_at(shown, right)
    )
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

    height = edit_unit(container, driver).unit_fields["height"].line_edit
    height.setFocus()
    height.selectAll()
    QtTest.QTest.keyClicks(height, "1010")
    QtTest.QTest.keyClick(height, QtCore.Qt.Key.Key_Return)
    driver.pump()
    click_task_button("Close", driver)

    assert not FreeCADGui.Control.activeDialog()
    assert abs(side.Placement.Base.x) < 1e-6
    shape = cast("_Shaped", side).Shape
    assert abs(shape.BoundBox.ZLength - 974.0) < 1e-6
