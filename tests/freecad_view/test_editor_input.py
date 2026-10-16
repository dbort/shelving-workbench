"""Edit Unit in the 3D view as a user works it: picking boards and
openings, the size field on a dimension, the drag arrow under each
navigation style, the add buttons and the delete key."""

from collections.abc import Iterator
from pathlib import Path
from typing import Literal, Protocol, cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from freecad.Shelving.container import unit_for_selection
from freecad.Shelving.core.layout import Basis, Board, Division, Fixed, Region
from freecad.Shelving.editor import view_editor as view_editor_module
from freecad.Shelving.editor.elevation import (
    LABEL_HIT_PX,
    DimensionLabel,
    board_space,
    label_at,
    split_preview,
)
from freecad.Shelving.editor.view_editor import ViewEditor
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import (
    add_board,
    bay_ids,
    click_region,
    click_task_button,
    edit_unit,
    editor_of,
    gui_step,
)
from tests.freecad_view.view import ViewDriver

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "freecad"
    / "fixtures"
    / "woodworking_magic_start_default.FCStd"
)
_NO_MODIFIER = QtCore.Qt.KeyboardModifier.NoModifier
_CTRL = QtCore.Qt.KeyboardModifier.ControlModifier

# Every navigation style a click and a drag must pass under, with the
# modifier it selects with: OpenInventor navigation selects on Ctrl+click.
_STYLES = (
    ("Gui::CADNavigationStyle", _NO_MODIFIER),
    ("Gui::GestureNavigationStyle", _NO_MODIFIER),
    ("Gui::TouchpadNavigationStyle", _NO_MODIFIER),
    ("Gui::OpenSCADNavigationStyle", _NO_MODIFIER),
    ("Gui::InventorNavigationStyle", _CTRL),
)


class _Placed(Protocol):
    Placement: FreeCAD.Placement


class _NavigationView(Protocol):
    def getNavigationType(self) -> str: ...
    def setNavigationType(self, name: str, /) -> None: ...


@pytest.fixture
def reported(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every message the in-view editor reports, still shown in the
    Notification Area."""
    messages: list[str] = []
    real = view_editor_module.report_error

    def record(message: str) -> None:
        messages.append(message)
        real(message)

    monkeypatch.setattr(view_editor_module, "report_error", record)
    return messages


def _selection() -> list[tuple[str, tuple[str, ...]]]:
    return [
        (cast("str", entry.ObjectName), tuple(entry.SubElementNames))
        for entry in FreeCADGui.Selection.getSelectionEx()
    ]


def _device(editor: ViewEditor, point: FreeCAD.Vector) -> tuple[int, int]:
    return editor.view.getPointOnViewport(point)


def _clear_of_labels(editor: ViewEditor, point: FreeCAD.Vector) -> bool:
    x_px, y_px = _device(editor, point)
    return (
        label_at(editor.overlay.labels, editor._project, x_px, y_px, LABEL_HIT_PX + 4)
        is None
    )


def _zoom_on(
    editor: ViewEditor, node_id: str, height_mm: float, driver: ViewDriver
) -> None:
    """Center the camera on ``node_id``, ``height_mm`` of the elevation
    tall: a board is a few pixels thick in the fitted view, inside
    FreeCAD's pick radius of its edges."""
    session = editor.session
    space = (
        board_space(session.unit, session.spaces, node_id) or session.spaces[node_id]
    )
    _zoom_at(editor, editor.frame.rect(space).center_mm, height_mm, driver)


def _zoom_at(
    editor: ViewEditor,
    at_mm: tuple[float, float],
    height_mm: float,
    driver: ViewDriver,
) -> None:
    """Center the camera on the elevation point ``at_mm``, ``height_mm`` of
    the elevation tall. The 3D view's size changes from run to run, so a
    test that needs a scale sets it."""
    center_mm = editor.to_document(*at_mm)
    camera = editor.view.getCameraNode()
    position_mm = FreeCAD.Vector(*camera.position.getValue().getValue())
    toward = editor.to_document(0, 0, 1) - editor.to_document(0, 0, 0)
    # The camera keeps its distance along the view direction.
    moved_mm = center_mm + toward * (position_mm - center_mm).dot(toward)
    camera.position.setValue(moved_mm.x, moved_mm.y, moved_mm.z)
    camera.height.setValue(height_mm)
    driver.pump()


def _picked(editor: ViewEditor, point: FreeCAD.Vector) -> tuple[str | None, str]:
    """The board FreeCAD's pick finds at ``point``, and the element kind."""
    info = editor.view.getObjectInfo(_device(editor, point))
    if info is None:
        return None, ""
    board = editor._board_in(
        str(info.get("Object", "")), str(info.get("SubName") or "")
    )
    return board, str(info.get("Component", ""))


def _board_targets(editor: ViewEditor, board_id: str) -> dict[str, FreeCAD.Vector]:
    """A point where FreeCAD picks ``board_id``'s face, one where it picks
    one of its edges and one where it picks one of its vertices, each clear
    of every dimension. Edges and vertices are found just outside the face,
    within FreeCAD's pick radius of them."""
    session = editor.session
    space = board_space(session.unit, session.spaces, board_id)
    assert space is not None
    rect = editor.frame.rect(space)
    candidates: list[tuple[float, float]] = []
    for fraction in (0.2, 0.35, 0.5, 0.65, 0.8):
        h_mm = rect.h0_mm + fraction * (rect.h1_mm - rect.h0_mm)
        candidates.append((h_mm, (rect.v0_mm + rect.v1_mm) / 2))
        for out_mm in (0.0, 0.5, 1.0, 2.0, 3.0):
            candidates.append((h_mm, rect.v1_mm + out_mm))
            candidates.append((h_mm, rect.v0_mm - out_mm))
    for h_mm, h_out in ((rect.h0_mm, -1.0), (rect.h1_mm, 1.0)):
        for v_mm, v_out in ((rect.v0_mm, -1.0), (rect.v1_mm, 1.0)):
            for out_mm in (0.0, 0.5, 1.0, 2.0):
                for h_only, v_only in ((1.0, 1.0), (1.0, 0.0), (0.0, 1.0)):
                    candidates.append(
                        (h_mm + h_out * out_mm * h_only, v_mm + v_out * out_mm * v_only)
                    )
    targets: dict[str, FreeCAD.Vector] = {}
    for h_mm, v_mm in candidates:
        point = editor.to_document(h_mm, v_mm)
        board, component = _picked(editor, point)
        kind = component.rstrip("0123456789")
        if (
            board == board_id
            and kind not in targets
            and _clear_of_labels(editor, point)
        ):
            targets[kind] = point
    return targets


def test_a_click_anywhere_on_a_board_selects_the_whole_board(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    # The top board's end, where its corners stand clear of other boards.
    _zoom_at(editor, (560.0, 880.0), 200.0, driver)
    targets = _board_targets(editor, "top")
    assert set(targets) == {"Face", "Edge", "Vertex"}, targets
    for kind, point in targets.items():
        editor.select(bay_ids(panel.session.unit.root)[0])
        assert _selection() == []
        driver.click(point)
        driver.pump()
        assert panel.session.selected_id == "top", kind
        assert _selection() == [("top", ())], kind
    click_task_button("Close", driver)


def test_a_click_on_an_opening_selects_it_and_clears_freecads_selection(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    add_board(panel, "vertical", driver)
    assert _selection() != []
    upper = bay_ids(panel.session.unit.root)[1]
    click_region(panel, upper, driver)
    assert panel.session.selected_id == upper
    assert _selection() == []
    click_task_button("Close", driver)


def test_a_click_on_an_object_outside_the_unit_selects_nothing(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    doc = unit.Document
    outside = cast("FreeCAD.DocumentObject", doc.addObject("Part::Box", "Outside"))
    for name, value_mm in (("Length", 100.0), ("Width", 100.0), ("Height", 300.0)):
        setattr(outside, name, value_mm)
    cast("_Placed", outside).Placement = FreeCAD.Placement(
        FreeCAD.Vector(700.0, 0.0, 300.0), FreeCAD.Rotation()
    )
    doc.recompute()
    panel = edit_unit(unit, driver)
    click_region(panel, bay_ids(panel.session.unit.root)[0], driver)
    assert panel.session.selected_id is not None
    target = FreeCAD.Vector(750.0, 0.0, 450.0)
    info = editor_of(panel).view.getObjectInfo(_device(editor_of(panel), target))
    assert info is not None and info.get("Object") == "Outside"
    driver.click(target)
    driver.pump()
    assert panel.session.selected_id is None
    assert _selection() == []
    click_task_button("Close", driver)


@pytest.fixture
def magic_start(
    driver: ViewDriver,
) -> Iterator[tuple[FreeCAD.DocumentObject, ViewDriver]]:
    """The Woodworking workbench's magicStart unit, whose back panel lies
    behind every opening, and a driver for its own 3D view."""
    FreeCADGui.activateWorkbench("ShelvingWorkbench")
    doc = FreeCAD.openDocument(str(_FIXTURE))
    own = ViewDriver.for_active_view()
    container = unit_for_selection(
        [cast("FreeCAD.DocumentObject", doc.getObject("LinkGroup"))]
    )
    assert container is not None
    yield container, own
    if FreeCADGui.Control.activeDialog():
        FreeCADGui.Control.closeDialog()
        own.pump()


def test_each_opening_in_front_of_a_back_panel_is_picked_and_allowed(
    magic_start: tuple[FreeCAD.DocumentObject, ViewDriver],
) -> None:
    container, driver = magic_start
    panel = edit_unit(container, driver)
    editor = editor_of(panel)
    faces = list(editor.overlay.faces)
    assert len(faces) >= 2
    behind = 0
    for face in faces:
        point = editor.to_document(*face.rect.center_mm)
        info = editor.view.getObjectInfo(_device(editor, point))
        if info is not None and info.get("Object") == "Back":
            behind += 1
        driver.hover(point)
        assert driver.viewport.cursor().shape() != QtCore.Qt.CursorShape.ForbiddenCursor
        driver.click(point)
        driver.pump()
        assert panel.session.selected_id == face.region_id
        assert _selection() == []
    # The case this guards: openings with the back panel right behind them.
    assert behind >= 2
    click_task_button("Close", driver)


def _label_of(editor: ViewEditor, region_id: str) -> DimensionLabel:
    (label,) = [x for x in editor.overlay.labels if x.region_id == region_id]
    return label


def _field_center(editor: ViewEditor) -> QtCore.QPoint:
    host = editor.field_host
    assert host is not None and host.isVisible()
    parent = host.parentWidget()
    assert parent is not None
    return editor._viewer.mapFrom(parent, host.geometry().center())


def _label_point(
    driver: ViewDriver, editor: ViewEditor, label: DimensionLabel
) -> QtCore.QPoint:
    return driver.qt_point(editor.to_document(*label.text_at_mm)).toPoint()


def _type(line_edit: QtWidgets.QLineEdit, text: str) -> None:
    line_edit.selectAll()
    QtTest.QTest.keyClicks(line_edit, text)
    QtTest.QTest.keyClick(line_edit, QtCore.Qt.Key.Key_Return)


def _rule(region: Region, region_id: str) -> object:
    if region.id == region_id:
        return region.rule
    if isinstance(region, Division):
        for item in region.items:
            if not isinstance(item, Board):
                found = _rule(item, region_id)
                if found is not None:
                    return found
    return None


def test_a_click_on_a_dimension_opens_a_field_that_sets_the_size(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, reported: list[str]
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower = bay_ids(session.unit.root)[0]
    label = _label_of(editor, lower)
    driver.click(editor.to_document(*label.text_at_mm))
    driver.pump()
    field = editor.field
    assert field is not None and field.quantity_widget is not None
    measurement = session.selected_measurement()
    assert session.selected_id == lower and measurement is not None
    assert field.quantity_widget.property("rawValue") == pytest.approx(
        measurement.size_mm
    )
    assert (
        _field_center(editor) - _label_point(driver, editor, label)
    ).manhattanLength() <= 4
    names = list(unit.Document.UndoNames)
    _type(field.line_edit, "250")
    driver.pump()
    assert editor.field is None
    assert list(unit.Document.UndoNames) == ["Set Size", *names]
    assert _rule(session.unit.root, session.selected_id or "") == Fixed(
        250.0, Basis.CLEAR
    )
    assert reported == []
    click_task_button("Close", driver)


def test_a_refused_size_is_reported_once_and_changes_nothing(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, reported: list[str]
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    lower = bay_ids(panel.session.unit.root)[0]
    driver.click(editor.to_document(*_label_of(editor, lower).text_at_mm))
    driver.pump()
    field = editor.field
    assert field is not None
    names = list(unit.Document.UndoNames)
    spaces = dict(panel.session.spaces)
    _type(field.line_edit, "5000")
    driver.pump()
    (message,) = reported
    assert message.startswith("The fixed sizes add up to"), message
    assert lower not in message
    assert editor.field is None
    assert list(unit.Document.UndoNames) == names
    assert sorted(panel.session.spaces.values(), key=repr) == sorted(
        spaces.values(), key=repr
    )
    click_task_button("Close", driver)


def test_escape_closes_the_field_and_not_the_edit(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    (label,) = [
        x
        for x in editor.overlay.labels
        if x.region_id == bay_ids(panel.session.unit.root)[0]
    ]
    driver.click(editor.to_document(*label.text_at_mm))
    driver.pump()
    field = editor.field
    assert field is not None
    QtTest.QTest.keyClick(field.line_edit, QtCore.Qt.Key.Key_Escape)
    driver.pump()
    assert editor.field is None
    assert FreeCADGui.Control.activeDialog()
    # With no field open, Escape in the view leaves the edit open too.
    driver.key(QtCore.Qt.Key.Key_Escape)
    assert FreeCADGui.Control.activeDialog()
    click_task_button("Close", driver)


def test_the_field_follows_its_dimension_when_the_camera_moves(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    label = _label_of(editor, bay_ids(panel.session.unit.root)[0])
    driver.click(editor.to_document(*label.text_at_mm))
    driver.pump()
    before = _field_center(editor)
    camera = editor.view.getCameraNode()
    x, y, z = camera.position.getValue().getValue()
    toward_right = editor.to_document(100.0, 0.0) - editor.to_document(0.0, 0.0)
    camera.position.setValue(x - toward_right.x, y - toward_right.y, z - toward_right.z)
    driver.pump()
    after = _field_center(editor)
    assert (after - before).manhattanLength() > 10
    assert (after - _label_point(driver, editor, label)).manhattanLength() <= 4
    click_task_button("Close", driver)


def test_a_dimension_over_a_board_opens_its_field_rather_than_the_board(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    """A click on a board within reach of a dimension's text opens that
    dimension's field and picks no board."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    session = panel.session
    # Far enough out that the dimension left of the unit lies within reach
    # of the side board.
    height_px = editor.view.getSize()[1]
    _zoom_at(editor, (300.0, 450.0), 4.0 * height_px, driver)
    found: tuple[DimensionLabel, FreeCAD.Vector] | None = None
    boards = [
        space
        for node_id in sorted(session.spaces)
        if (space := board_space(session.unit, session.spaces, node_id)) is not None
    ]
    for space in boards:
        rect = editor.frame.rect(space)
        for h_step in range(41):
            for v_step in range(5):
                point = editor.to_document(
                    rect.h0_mm + h_step / 40 * (rect.h1_mm - rect.h0_mm),
                    rect.v0_mm + (v_step + 0.5) / 5 * (rect.v1_mm - rect.v0_mm),
                )
                x_px, y_px = _device(editor, point)
                label = label_at(editor.overlay.labels, editor._project, x_px, y_px)
                if label is not None and _picked(editor, point)[0] is not None:
                    found = (label, point)
                    break
            if found:
                break
        if found:
            break
    assert found is not None
    label, point = found
    driver.click(point)
    driver.pump()
    assert editor.field is not None
    assert session.selected_id == label.region_id
    assert _selection() == []
    click_task_button("Close", driver)


@pytest.fixture
def navigation(
    request: pytest.FixtureRequest, driver: ViewDriver
) -> Iterator[QtCore.Qt.KeyboardModifier]:
    """The navigation style named by the test's parameter, set for the test
    and restored after it; yields the modifier that style selects with."""
    style, modifier = cast("tuple[str, QtCore.Qt.KeyboardModifier]", request.param)
    view = cast("_NavigationView", driver.view)
    previous = view.getNavigationType()
    view.setNavigationType(style)
    yield modifier
    view.setNavigationType(previous)


def _arrow_point(editor: ViewEditor) -> FreeCAD.Vector:
    arrow = editor.arrow
    assert arrow is not None
    return editor.to_document(*arrow.at_mm, editor.frame.z_sign * 2.0)


@pytest.mark.parametrize(
    "navigation", _STYLES, indirect=True, ids=[s for s, _ in _STYLES]
)
def test_a_selected_board_drags_by_its_arrow_under_each_navigation_style(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    navigation: QtCore.Qt.KeyboardModifier,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    session = panel.session
    shelf = add_board(panel, "vertical", driver)
    _zoom_on(editor, shelf, 300.0, driver)
    # Select it again by a click in the view, as the style selects.
    upper = bay_ids(session.unit.root)[1]
    driver.click(
        editor.to_document(*editor.frame.rect(session.spaces[upper]).center_mm),
        navigation,
    )
    driver.pump()
    assert session.selected_id == upper
    targets = _board_targets(editor, shelf)
    driver.click(targets["Face"], navigation)
    driver.pump()
    assert session.selected_id == shelf
    arrow = editor.arrow
    assert arrow is not None and arrow.board_id == shelf and arrow.vertical
    lower = bay_ids(session.unit.root)[0]
    lower_label = _label_of(editor, lower)
    # Beside the dimension of the opening before the board, just past it.
    assert arrow.at_mm[0] > lower_label.start_mm[0]
    z_before_mm = session.spaces[shelf].origin.z_mm
    names = list(unit.Document.UndoNames)
    start = driver.qt_point(_arrow_point(editor))
    driver.drag(start, start - QtCore.QPointF(0.0, 40.0), modifiers=navigation)
    driver.pump()
    assert session.spaces[shelf].origin.z_mm > z_before_mm + 5.0
    assert list(unit.Document.UndoNames) == ["Move Board", *names]
    assert session.selected_id == shelf
    assert _selection() == [(shelf, ())]
    assert editor.arrow is not None and editor.arrow.board_id == shelf
    click_task_button("Close", driver)


def test_a_held_board_and_a_carcass_board_show_no_arrow(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    session = panel.session
    shelf = add_board(panel, "vertical", driver)
    assert editor.arrow is not None
    assert session.set_locks([bay_ids(session.unit.root)[0]], locked=True) is None
    editor.select(shelf)
    assert editor.arrow is None
    editor.select("top")
    assert editor.arrow is None
    click_task_button("Close", driver)


def test_the_add_buttons_show_over_a_selected_bay_and_preview_their_board(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    session = panel.session
    bay = bay_ids(session.unit.root)[0]
    click_region(panel, bay, driver)
    bar = editor.add_bar
    assert bar.isVisible()
    assert sorted(b.text() for b in bar.buttons.values()) == [
        "Add divider",
        "Add shelf",
    ]
    center = driver.qt_point(
        editor.to_document(*editor.frame.rect(session.spaces[bay]).center_mm)
    ).toPoint()
    parent = bar.parentWidget()
    assert parent is not None
    at = editor._viewer.mapFrom(parent, bar.geometry().center())
    assert (at - center).manhattanLength() <= 4
    faces = len(overlay_nodes.faces(editor.root))
    shelf_button = bar.buttons["vertical"]
    QtWidgets.QApplication.sendEvent(
        shelf_button, QtCore.QEvent(QtCore.QEvent.Type.Enter)
    )
    driver.pump()
    assert editor.preview == split_preview(
        session.unit, editor.frame, bay, editor.frame.vertical
    )
    assert len(overlay_nodes.faces(editor.root)) == faces + 1
    QtWidgets.QApplication.sendEvent(
        shelf_button, QtCore.QEvent(QtCore.QEvent.Type.Leave)
    )
    driver.pump()
    assert editor.preview is None
    names = list(unit.Document.UndoNames)
    before = set(session.spaces)
    shelf_button.click()
    driver.pump()
    assert list(unit.Document.UndoNames) == ["Add Shelf", *names]
    (shelf,) = {
        node for node in set(session.spaces) - before if unit.Document.getObject(node)
    }
    assert session.selected_id == shelf
    assert editor.arrow is not None and editor.arrow.board_id == shelf
    assert not bar.isVisible()
    click_region(panel, bay_ids(session.unit.root)[0], driver)
    assert bar.isVisible()
    editor.select(None)
    assert not bar.isVisible()
    click_task_button("Close", driver)


@pytest.mark.parametrize("key", [QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace])
def test_delete_and_backspace_delete_the_selected_board(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, key: QtCore.Qt.Key
) -> None:
    panel = edit_unit(unit, driver)
    doc = unit.Document
    shelf = add_board(panel, "vertical", driver)
    names = list(doc.UndoNames)
    driver.key(key)
    driver.pump()
    assert doc.getObject(shelf) is None
    assert shelf not in panel.session.spaces
    # One edit of the editor's own, not FreeCAD's Delete.
    assert list(doc.UndoNames) == ["Delete Board", *names]
    click_task_button("Close", driver)


def test_deleting_a_carcass_board_is_refused_in_the_notification_area(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, reported: list[str]
) -> None:
    from tests.freecad_view.editor import notification_count

    panel = edit_unit(unit, driver)
    doc = unit.Document
    editor_of(panel).select("top")
    names = list(doc.UndoNames)
    count = notification_count()
    driver.key(QtCore.Qt.Key.Key_Delete)
    driver.pump()
    assert len(reported) == 1, reported
    assert notification_count() == count + 1
    assert doc.getObject("top") is not None
    assert list(doc.UndoNames) == names
    click_task_button("Close", driver)


def test_a_board_deleted_from_the_tree_rescans_and_one_undo_restores_it(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    doc = unit.Document
    shelf = add_board(panel, "vertical", driver)
    labels = len(editor.overlay.labels)
    # What Std_Delete does with focus in the tree.
    doc.openTransaction("Delete")
    doc.removeObject(shelf)
    doc.commitTransaction()
    driver.pump(300)
    assert shelf not in panel.session.spaces
    assert len(editor.overlay.labels) < labels
    gui_step("Std_Undo", driver)
    assert doc.getObject(shelf) is not None
    assert shelf in panel.session.spaces
    assert len(editor.overlay.labels) == labels
    click_task_button("Close", driver)


def _accept_formula_dialog(expression: str, driver: ViewDriver) -> None:
    (dialog,) = [
        widget
        for widget in QtWidgets.QApplication.allWidgets()
        if widget.inherits("Gui::Dialog::DlgExpressionInput") and widget.isVisible()
    ]
    assert isinstance(dialog, QtWidgets.QDialog)
    (text_edit,) = [
        child
        for child in dialog.findChildren(QtWidgets.QPlainTextEdit)
        if child.objectName() == "expression"
    ]
    text_edit.setPlainText(expression)
    driver.pump(50)
    dialog.accept()
    driver.pump()


def test_fx_in_the_size_fields_leaves_close_adding_nothing(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    doc = unit.Document
    varset = cast("FreeCAD.DocumentObject", doc.addObject("App::VarSet", "VarSet"))
    varset.addProperty("App::PropertyLength", "Len")
    setattr(varset, "Len", 300.0)  # noqa: B010 - a dynamic property
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    lower = bay_ids(panel.session.unit.root)[0]
    driver.click(editor.to_document(*_label_of(editor, lower).text_at_mm))
    driver.pump()
    field = editor.field
    assert field is not None and field.quantity_widget is not None
    field.quantity_widget.setFocus()
    QtTest.QTest.keyClick(field.quantity_widget, QtCore.Qt.Key.Key_Equal)
    driver.pump()
    _accept_formula_dialog("VarSet.Len - 20 mm", driver)
    assert _rule(panel.session.unit.root, lower) == Fixed(280.0, Basis.CLEAR)
    height = panel.unit_fields["height"].quantity_widget
    assert height is not None
    height.setFocus()
    QtTest.QTest.keyClick(height, QtCore.Qt.Key.Key_Equal)
    driver.pump()
    _accept_formula_dialog("VarSet.Len * 3 + 100 mm", driver)
    assert panel.session.unit_dimension_mm("height") == pytest.approx(1000.0)
    names = list(doc.UndoNames)
    assert names[:2] == ["Resize Unit", "Set Size"]
    objects = len(doc.Objects)
    click_task_button("Close", driver)
    assert list(doc.UndoNames) == names
    assert len(doc.Objects) == objects
    top = cast("_Placed", doc.getObject("top"))
    gui_step("Std_Undo", driver)
    assert list(doc.UndoNames) == names[1:]
    assert top.Placement.Base.z == pytest.approx(900.0 - 18.0)


def _as_plain_group(container: FreeCAD.DocumentObject) -> FreeCAD.DocumentObject:
    doc = container.Document
    boards = list(cast("FreeCAD.DocumentObjectGroup", container).Group)
    group = cast(
        "FreeCAD.DocumentObjectGroup",
        doc.addObject("App::DocumentObjectGroup", "Plain"),
    )
    for board in boards:
        cast("FreeCAD.DocumentObjectGroup", container).removeObject(board)
        group.addObject(board)
    doc.removeObject(container.Name)
    doc.recompute()
    return cast("FreeCAD.DocumentObject", group)


@pytest.mark.parametrize("kind", ["plain group", "placed by an expression"])
def test_the_dimension_field_works_on_every_container(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    kind: Literal["plain group", "placed by an expression"],
) -> None:
    doc = unit.Document
    varset = cast("FreeCAD.DocumentObject", doc.addObject("App::VarSet", "VarSet"))
    varset.addProperty("App::PropertyLength", "Len")
    setattr(varset, "Len", 300.0)  # noqa: B010 - a dynamic property
    if kind == "plain group":
        container = _as_plain_group(unit)
    else:
        container = unit
        container.setExpression("Placement.Base.x", "VarSet.Len")
        doc.recompute()
    panel = edit_unit(container, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    bay = bay_ids(panel.session.unit.root)[0]
    driver.click(editor.to_document(*_label_of(editor, bay).text_at_mm))
    driver.pump()
    field = editor.field
    assert field is not None and field.quantity_widget is not None
    assert not field.line_edit.isReadOnly()
    field.quantity_widget.setFocus()
    QtTest.QTest.keyClick(field.quantity_widget, QtCore.Qt.Key.Key_Equal)
    driver.pump()
    _accept_formula_dialog("VarSet.Len", driver)
    assert _rule(panel.session.unit.root, panel.session.selected_id or "") == Fixed(
        300.0, Basis.CLEAR
    )
    assert list(doc.UndoNames)[0] == "Set Size"
    click_task_button("Close", driver)
