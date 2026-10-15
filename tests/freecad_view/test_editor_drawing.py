"""Edit Unit in the 3D view: what opening it does to the view and what
every way out puts back, the camera's turn, and the openings and
dimensions drawn over the boards."""

import sys
from collections.abc import Iterator
from types import TracebackType
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest

from freecad.Shelving.core.edit import is_locked, measure
from freecad.Shelving.core.layout import Board, Division, Region
from freecad.Shelving.editor import view_editor as view_editor_module
from freecad.Shelving.editor.elevation import (
    ElevationFrame,
    board_space,
    elevation_frame,
    label_size_pt,
)
from freecad.Shelving.editor.panel import EditUnitPanel
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import (
    add_board,
    bay_ids,
    click_task_button,
    edit_unit,
    editor_of,
    gui_step,
    run_command,
)
from tests.freecad_view.view import ViewDriver

_TOL_MM = 0.01
_VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
_SKETCHER_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"


class _Placed(Protocol):
    Placement: FreeCAD.Placement


class _ViewObject(Protocol):
    Visibility: bool


def _turn(container: FreeCAD.DocumentObject) -> None:
    """Move the unit off the origin and turn it 30 degrees about Z."""
    cast("_Placed", container).Placement = FreeCAD.Placement(
        FreeCAD.Vector(400.0, -250.0, 30.0),
        FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 30),
    )
    container.Document.recompute()


@pytest.fixture(params=["at the origin", "moved and turned"])
def placed_unit(
    request: pytest.FixtureRequest, unit: FreeCAD.DocumentObject
) -> FreeCAD.DocumentObject:
    if request.param == "moved and turned":
        _turn(unit)
    return unit


def _document_placement(
    container: FreeCAD.DocumentObject, frame: ElevationFrame
) -> FreeCAD.Placement:
    """``frame`` in document coordinates, composed here rather than taken
    from the editor."""
    local = FreeCAD.Placement(FreeCAD.Matrix(*frame.matrix()))
    return cast("_Placed", container).Placement.multiply(local)


def _outside_box(
    doc: FreeCAD.Document, name: str, x_mm: float
) -> FreeCAD.DocumentObject:
    box = cast("FreeCAD.DocumentObject", doc.addObject("Part::Box", name))
    cast("_Placed", box).Placement = FreeCAD.Placement(
        FreeCAD.Vector(x_mm, 0, 0), FreeCAD.Rotation()
    )
    doc.recompute()
    return box


def _scene_graph(driver: ViewDriver) -> object:
    from pivy import coin  # noqa: F401 - getSceneGraph needs pivy loaded

    return cast("view_editor_module.View3D", driver.view).getSceneGraph()


class _Exits:
    """What every way out of the editor must leave as it found it."""

    def __init__(self, unit: FreeCAD.DocumentObject, driver: ViewDriver) -> None:
        self.doc = unit.Document
        self.driver = driver
        self.outside = _outside_box(self.doc, "Outside", 2000.0)
        self.scene_graph = _scene_graph(driver)
        self.children = cast("_Group", self.scene_graph).getNumChildren()

    def check(self, root: object) -> None:
        graph = cast("_Group", self.scene_graph)
        assert not overlay_nodes.in_scene(graph, root)
        assert graph.getNumChildren() == self.children
        view_object = cast("_ViewObject", self.outside.ViewObject)
        assert view_object.Visibility
        # No gate is left to refuse it.
        FreeCADGui.Selection.clearSelection()
        FreeCADGui.Selection.addSelection(self.doc.Name, self.outside.Name)
        selected = cast(
            "list[FreeCAD.DocumentObject]", FreeCADGui.Selection.getSelection()
        )
        assert [obj.Name for obj in selected] == ["Outside"]
        FreeCADGui.Selection.clearSelection()


class _Group(Protocol):
    def getNumChildren(self) -> int: ...
    def getChild(self, index: int, /) -> object: ...


def test_edit_unit_adds_one_overlay_node_and_close_removes_it(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    exits = _Exits(unit, driver)
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    graph = cast("_Group", exits.scene_graph)
    assert graph.getNumChildren() == exits.children + 1
    assert overlay_nodes.in_scene(graph, editor.root)
    panel.hide_others_check.setChecked(True)
    assert not cast("_ViewObject", exits.outside.ViewObject).Visibility
    add_board(panel, "vertical", driver)
    names = list(unit.Document.UndoNames)
    click_task_button("Close", driver)
    exits.check(editor.root)
    assert list(unit.Document.UndoNames) == names
    assert names[0] == "Add Shelf"


def test_an_undo_that_removes_the_unit_ends_the_editor(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    exits = _Exits(unit, driver)
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    panel.hide_others_check.setChecked(True)
    gui_step("Std_Undo", driver)
    assert unit.Document.getObject("ShelvingUnit") is None
    assert not FreeCADGui.Control.activeDialog()
    assert editor.closed
    exits.check(editor.root)


def test_a_failure_building_the_editor_leaves_the_view_as_it_was(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exits = _Exits(unit, driver)
    built: list[view_editor_module.ViewEditor] = []

    def fail(self: view_editor_module.ViewEditor) -> None:
        built.append(self)
        raise RuntimeError("the camera would not turn")

    monkeypatch.setattr(view_editor_module.ViewEditor, "_turn_camera", fail)
    names = list(unit.Document.UndoNames)
    run_command("Shelving_EditUnit", unit, driver)
    assert not FreeCADGui.Control.activeDialog()
    (editor,) = built
    assert editor.closed
    exits.check(editor.root)
    assert list(unit.Document.UndoNames) == names


def _front_rotation(
    container: FreeCAD.DocumentObject, panel: EditUnitPanel
) -> FreeCAD.Rotation:
    return _document_placement(container, elevation_frame(panel.session.unit)).Rotation


def test_opening_turns_the_camera_to_the_units_front(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    driver.view.viewIsometric()
    driver.pump(800)
    panel = edit_unit(placed_unit, driver)
    view = cast("view_editor_module.View3D", driver.view)
    assert view.getCameraOrientation().isSame(_front_rotation(placed_unit, panel), 1e-6)
    assert "OrthographicCamera" in view.getCamera()
    session = panel.session
    front = _document_placement(placed_unit, elevation_frame(session.unit))
    width_px, height_px = view.getSize()
    for node_id in session.spaces:
        space = board_space(session.unit, session.spaces, node_id)
        if space is None:
            continue
        rect = elevation_frame(session.unit).rect(space)
        for h_mm in (rect.h0_mm, rect.h1_mm):
            for v_mm in (rect.v0_mm, rect.v1_mm):
                x_px, y_px = view.getPointOnViewport(
                    front.multVec(FreeCAD.Vector(h_mm, v_mm, 0))
                )
                assert 0 <= x_px < width_px and 0 <= y_px < height_px, node_id
    click_task_button("Close", driver)


def _camera_after_close(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, restore: bool | None
) -> tuple[FreeCAD.Rotation, FreeCAD.Rotation, FreeCAD.Rotation]:
    """The camera's orientation before Edit Unit, while it is open, and once
    Close has had time to turn it back, with the Sketcher's preference
    ``restore``, or unset for ``None``."""
    params = FreeCAD.ParamGet(_SKETCHER_PARAMS)
    params.RemBool("RestoreCamera")
    if restore is not None:
        params.SetBool("RestoreCamera", restore)
    try:
        driver.view.viewIsometric()
        driver.pump(800)
        view = cast("view_editor_module.View3D", driver.view)
        before = view.getCameraOrientation()
        edit_unit(unit, driver)
        editing = view.getCameraOrientation()
        click_task_button("Close", driver)
        driver.pump(1500)
        return before, editing, view.getCameraOrientation()
    finally:
        params.RemBool("RestoreCamera")


@pytest.mark.parametrize("restore", [True, None], ids=["set", "default"])
def test_close_restores_the_camera_as_the_sketcher_does(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, restore: bool | None
) -> None:
    before, editing, after = _camera_after_close(unit, driver, restore)
    assert not editing.isSame(before, 1e-6)
    assert after.isSame(before, 1e-6)


def test_close_leaves_the_camera_when_the_sketcher_would(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    before, editing, after = _camera_after_close(unit, driver, restore=False)
    assert not editing.isSame(before, 1e-6)
    assert after.isSame(editing, 1e-6)


def test_a_restore_still_turning_leaves_the_next_session_alone(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    driver.view.viewIsometric()
    driver.pump(800)
    edit_unit(unit, driver)
    click_task_button("Close", driver)
    panel = edit_unit(unit, driver)
    # Past the time a restore may wait for its turn before it jumps.
    driver.pump(3500)
    view = cast("view_editor_module.View3D", driver.view)
    assert view.getCameraOrientation().isSame(_front_rotation(unit, panel), 1e-6)
    click_task_button("Close", driver)


def _region_front(
    container: FreeCAD.DocumentObject, panel: EditUnitPanel, region_id: str, side: str
) -> list[FreeCAD.Vector]:
    """The corners of ``region_id``'s face on ``side`` of the unit, in
    document coordinates."""
    unit = panel.session.unit
    frame = elevation_frame(unit, "back" if side == "back" else "front")
    rect = frame.rect(panel.session.spaces[region_id])
    placement = _document_placement(container, frame)
    return [
        placement.multVec(FreeCAD.Vector(h_mm, v_mm, 0))
        for h_mm, v_mm in (
            (rect.h0_mm, rect.v0_mm),
            (rect.h1_mm, rect.v0_mm),
            (rect.h1_mm, rect.v1_mm),
            (rect.h0_mm, rect.v1_mm),
        )
    ]


def _openings(region: Region) -> list[str]:
    if not isinstance(region, Division):
        return [region.id]
    return [
        found
        for item in region.items
        if not isinstance(item, Board)
        for found in _openings(item)
    ]


def _assert_faces_on(
    container: FreeCAD.DocumentObject, panel: EditUnitPanel, side: str
) -> None:
    drawn = overlay_nodes.faces(editor_of(panel).root)
    expected = [
        _region_front(container, panel, region_id, side)
        for region_id in _openings(panel.session.unit.root)
    ]
    assert len(drawn) == len(expected)
    for corners in expected:
        assert any(
            all(
                (corner - got).Length < _TOL_MM
                for corner, got in zip(corners, face, strict=True)
            )
            for face in drawn
        ), (side, corners, drawn)


def _look_from(
    view: view_editor_module.View3D, rotation: FreeCAD.Rotation, driver: ViewDriver
) -> None:
    view.setCameraOrientation(rotation)
    for _ in range(60):
        driver.pump(50)
        if view.getCameraOrientation().isSame(rotation, 1e-6):
            break
    driver.pump(300)


def test_each_opening_is_a_face_on_the_side_the_camera_sees(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(placed_unit, driver)
    add_board(panel, "vertical", driver)
    add_board(panel, "horizontal", driver)
    _assert_faces_on(placed_unit, panel, "front")
    view = cast("view_editor_module.View3D", driver.view)
    front = _front_rotation(placed_unit, panel)
    behind = front.multiply(FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 180))
    _look_from(view, behind, driver)
    assert editor_of(panel).frame.side == "back"
    _assert_faces_on(placed_unit, panel, "back")
    _look_from(view, front, driver)
    assert editor_of(panel).frame.side == "front"
    _assert_faces_on(placed_unit, panel, "front")
    click_task_button("Close", driver)


def _rgb(name: str, default: int) -> tuple[float, float, float]:
    packed = FreeCAD.ParamGet(_VIEW_PARAMS).GetUnsigned(name, default)
    return (
        ((packed >> 24) & 0xFF) / 255,
        ((packed >> 16) & 0xFF) / 255,
        ((packed >> 8) & 0xFF) / 255,
    )


@pytest.fixture
def dimension_style() -> Iterator[None]:
    """Dimension colors and a text size of their own, so a test sees them
    read. The selection color stays FreeCAD's: the 3D view keeps a changed
    one after the preference is removed."""
    params = FreeCAD.ParamGet(_VIEW_PARAMS)
    params.SetUnsigned("ConstrainedDimColor", 0xC01020FF)
    params.SetUnsigned("NonDrivingConstrDimColor", 0x1020C0FF)
    params.SetInt("EditSketcherFontSize", 21)
    yield
    for name in ("ConstrainedDimColor", "NonDrivingConstrDimColor"):
        params.RemUnsigned(name)
    params.RemInt("EditSketcherFontSize")


def _close_rgb(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(x - y) < 1e-3 for x, y in zip(a, b, strict=True))


def test_each_region_in_a_run_has_a_sketcher_dimension(
    placed_unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
) -> None:
    panel = edit_unit(placed_unit, driver)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower = bay_ids(session.unit.root)[0]
    assert session.set_locks([lower], locked=True) is None
    upper = bay_ids(session.unit.root)[1]
    session.select(upper)
    panel._refresh()
    viewer = driver.graphics_view
    size_pt = label_size_pt(
        21, viewer.devicePixelRatioF(), viewer.screen().logicalDotsPerInchX()
    )
    front_normal = _front_rotation(placed_unit, panel).multVec(FreeCAD.Vector(0, 0, 1))

    def expected() -> list[tuple[str, tuple[float, float, float]]]:
        found: list[tuple[str, tuple[float, float, float]]] = []

        def walk(region: Region) -> None:
            if not isinstance(region, Division):
                return
            for item in region.items:
                if isinstance(item, Board):
                    continue
                if item.id == session.selected_id:
                    rgb = _rgb("SelectionColor", 0x1CAD1CFF)
                elif is_locked(item):
                    rgb = _rgb("ConstrainedDimColor", 0)
                else:
                    rgb = _rgb("NonDrivingConstrDimColor", 0)
                size_mm = measure(session.unit, item.id, session.spaces).size_mm
                found.append((f"{size_mm:.2f}".rstrip("0").rstrip("."), rgb))
                walk(item)

        walk(session.unit.root)
        return found

    def check() -> None:
        drawn = overlay_nodes.labels(editor_of(panel).root)
        wanted = expected()
        assert len(drawn) == len(wanted)
        for text, rgb in wanted:
            assert any(
                label.text == text and _close_rgb(label.rgb, rgb) for label in drawn
            ), (text, rgb, drawn)
        for label in drawn:
            assert label.size == size_pt
            assert (label.norm - front_normal).Length < 1e-6

    check()
    view = cast("view_editor_module.View3D", driver.view)
    front = _front_rotation(placed_unit, panel)
    _look_from(
        view, front.multiply(FreeCAD.Rotation(FreeCAD.Vector(0, 1, 0), 180)), driver
    )
    assert editor_of(panel).frame.side == "back"
    check()
    click_task_button("Close", driver)


def test_the_scene_bounds_reach_every_dimension(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    """FreeCAD's orthographic camera clips just in front of the scene's
    bounding box, and ``SoDatumLabel`` gives its own box no depth: unless
    the overlay's box reaches the dimensions, a camera square on to the unit
    can clip their lines and text."""
    panel = edit_unit(placed_unit, driver)
    add_board(panel, "vertical", driver)
    editor = editor_of(panel)
    # An opening shows no drag arrow, which stands higher than the
    # dimensions and would stretch the box over them.
    editor.select(bay_ids(panel.session.unit.root)[0])
    root = editor.root
    low, high = overlay_nodes.bounds(root)
    tolerance_mm = 1e-3
    for label in overlay_nodes.labels(root):
        for point in label.points:
            for axis in ("x", "y", "z"):
                value = getattr(point, axis)
                assert getattr(low, axis) - tolerance_mm <= value, (label, axis)
                assert value <= getattr(high, axis) + tolerance_mm, (label, axis)
    click_task_button("Close", driver)


def test_closing_the_document_while_the_camera_turns_back_raises_nothing(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    errors: list[BaseException] = []

    def record(
        _kind: type[BaseException], value: BaseException, _trace: TracebackType | None
    ) -> None:
        errors.append(value)

    monkeypatch.setattr(sys, "excepthook", record)
    driver.view.viewIsometric()
    driver.pump(800)
    edit_unit(unit, driver)
    click_task_button("Close", driver)
    FreeCAD.closeDocument(unit.Document.Name)
    driver.pump(1000)
    assert errors == []


def test_closing_the_document_ends_the_edit(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FreeCAD closes the task dialog with its document, as Assembly asks it
    to, and the editor lets go of the view's widgets: a dead editor left
    open would hold the view's widget wrapper, which PySide hands back,
    dead, for the next view made at the same address."""
    errors: list[BaseException] = []

    def record(
        _kind: type[BaseException], value: BaseException, _trace: TracebackType | None
    ) -> None:
        errors.append(value)

    monkeypatch.setattr(sys, "excepthook", record)
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    FreeCAD.closeDocument(unit.Document.Name)
    driver.pump(500)
    assert editor.closed
    assert panel.editor is None
    assert not FreeCADGui.Control.activeDialog()
    assert errors == []

    # Edit Unit works again, and no gate of the old edit refuses a pick.
    fresh = FreeCAD.newDocument("Fresh")
    fresh.UndoMode = 1
    from freecad.Shelving.unit_ops import create_unit

    container = create_unit(fresh)
    fresh.recompute()
    fresh_driver = ViewDriver.for_active_view()
    other = _outside_box(fresh, "Other", 2000.0)
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(fresh.Name, other.Name)
    assert FreeCADGui.Selection.getSelection()
    reopened = edit_unit(container, fresh_driver)
    assert editor_of(reopened).viewport.isVisible()
    click_task_button("Close", fresh_driver)
    assert errors == []


def test_hide_other_objects_hides_and_restores_exactly_those_it_hid(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    doc = unit.Document
    shown = [
        _outside_box(doc, name, x_mm) for name, x_mm in (("A", 2000.0), ("B", 2500.0))
    ]
    already_hidden = _outside_box(doc, "C", 3000.0)
    cast("_ViewObject", already_hidden.ViewObject).Visibility = False
    names = list(doc.UndoNames)
    panel = edit_unit(unit, driver)
    assert not panel.hide_others_check.isChecked()
    board = doc.getObject("top")
    assert board is not None

    def visible(obj: FreeCAD.DocumentObject) -> bool:
        return cast("_ViewObject", obj.ViewObject).Visibility

    panel.hide_others_check.setChecked(True)
    driver.pump()
    assert not any(visible(obj) for obj in shown)
    assert visible(board) and visible(unit)
    panel.hide_others_check.setChecked(False)
    driver.pump()
    assert all(visible(obj) for obj in shown)
    assert not visible(already_hidden)
    panel.hide_others_check.setChecked(True)
    driver.pump()
    click_task_button("Close", driver)
    assert all(visible(obj) for obj in shown)
    assert not visible(already_hidden)
    assert list(doc.UndoNames) == names


def test_one_dragger_per_session_kept_on_an_old_coin(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        view_editor_module, "coin_destroys_draggers_safely", lambda: False
    )
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    dragger = editor.dragger
    shelf = add_board(panel, "vertical", driver)
    add_board(panel, "horizontal", driver)
    panel.session.select(shelf)
    panel._refresh()
    assert editor.dragger is dragger
    assert overlay_nodes.draggers(editor.root) == 1
    kept = len(view_editor_module.KEPT_ALIVE)
    click_task_button("Close", driver)
    assert len(view_editor_module.KEPT_ALIVE) == kept + 1
