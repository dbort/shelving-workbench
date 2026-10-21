"""Edit Unit in the 3D view: what opening it does to the view and what
every way out puts back, the camera's turn, and the openings and
dimensions drawn over the boards."""

import sys
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore

from freecad.Shelving.core.edit import is_locked, measure
from freecad.Shelving.core.layout import Board, Division, Region
from freecad.Shelving.editor import view_editor as view_editor_module
from freecad.Shelving.editor.elevation import (
    ElevationFrame,
    board_space,
    elevation_frame,
    label_size_pt,
)
from freecad.Shelving.editor.overlay import label_string, length_text
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.view_editor import label_metrics
from freecad.Shelving.qa import actions as qa_actions
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import (
    add_board,
    bay_ids,
    click_task_button,
    edit_unit,
    editor_of,
    gui_step,
    press_task_button,
    run_command,
)
from tests.freecad_view.view import ViewDriver

_TOL_MM = 0.01
_VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
_SKETCHER_PARAMS = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"
_UNITS_PARAMS = "User parameter:BaseApp/Preferences/Units"


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


@pytest.fixture
def placed_unit(
    request: pytest.FixtureRequest, unit: FreeCAD.DocumentObject
) -> FreeCAD.DocumentObject:
    """The unit moved and turned, or left at the origin when a test
    parametrizes it indirectly with "at the origin"."""
    # A moved and turned unit exercises every transform an unmoved one
    # does, so only a test or two also runs at the origin.
    if getattr(request, "param", "moved and turned") == "moved and turned":
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


@pytest.mark.parametrize(
    "placed_unit",
    [pytest.param("at the origin", marks=pytest.mark.full_only), "moved and turned"],
    indirect=True,
)
def test_opening_turns_the_camera_to_the_units_front(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    driver.view.viewIsometric()
    driver.pump()
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
        driver.pump()
        view = cast("view_editor_module.View3D", driver.view)
        before = view.getCameraOrientation()
        edit_unit(unit, driver)
        editing = view.getCameraOrientation()
        click_task_button("Close", driver)
        return before, editing, view.getCameraOrientation()
    finally:
        params.RemBool("RestoreCamera")


def test_close_restores_the_camera_as_the_sketcher_does(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    # Unset, the Sketcher's preference defaults to restoring.
    before, editing, after = _camera_after_close(unit, driver, restore=None)
    assert not editing.isSame(before, 1e-6)
    assert after.isSame(before, 1e-6)


def test_close_leaves_the_camera_when_the_sketcher_would(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    before, editing, after = _camera_after_close(unit, driver, restore=False)
    assert not editing.isSame(before, 1e-6)
    assert after.isSame(editing, 1e-6)


@pytest.mark.full_only
def test_a_restore_still_turning_leaves_the_next_session_alone(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, slow_turns: None
) -> None:
    driver.view.viewIsometric()
    driver.pump()
    edit_unit(unit, driver)
    press_task_button("Close")
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
    driver.pump()


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
    assert session.set_lock(lower, locked=True) is None
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
                if is_locked(item):
                    rgb = _rgb("ConstrainedDimColor", 0)
                else:
                    rgb = _rgb("NonDrivingConstrDimColor", 0)
                size_mm = measure(session.unit, item.id, session.spaces).size_mm
                found.append((length_text(size_mm), rgb))
                walk(item)

        walk(session.unit.root)
        return found

    def check() -> None:
        drawn = overlay_nodes.labels(editor_of(panel).root)
        wanted = expected()
        assert len(drawn) == len(wanted)
        for text, rgb in wanted:
            assert any(
                label.text.strip() == text and _close_rgb(label.rgb, rgb)
                for label in drawn
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


@contextmanager
def _unit_system(schema: str) -> Iterator[None]:
    """FreeCAD's unit system set to ``schema``, a name from
    ``Units.listSchemas()``, and restored on exit."""
    before = FreeCAD.Units.getSchema()
    FreeCAD.Units.setSchema(FreeCAD.Units.listSchemas().index(schema))
    try:
        yield
    finally:
        FreeCAD.Units.setSchema(before)


@pytest.mark.parametrize(
    ("schema", "length_mm", "text"),
    [
        ("Internal", 346.0, "346 mm"),
        ("Internal", 218.5, "218.5 mm"),
        ("ImperialDecimal", 25.4, "1 in"),
        ("Centimeter", 205.0, "20.5 cm"),
        ("ImperialBuilding", 218.5, '8" + 5/8"'),
    ],
)
def test_a_length_reads_in_the_users_unit_system(
    schema: str, length_mm: float, text: str
) -> None:
    with _unit_system(schema):
        assert length_text(length_mm) == text


@pytest.mark.parametrize(
    ("length_mm", "text"), [(218.5, "218,5 mm"), (1500.0, "1500 mm")]
)
def test_a_length_trims_its_zeros_after_a_decimal_comma(
    length_mm: float, text: str
) -> None:
    """FreeCAD's default number format follows the operating system's
    locale, so the decimal point can be a comma."""
    before = QtCore.QLocale()
    QtCore.QLocale.setDefault(QtCore.QLocale(QtCore.QLocale.Language.German))
    try:
        with _unit_system("Internal"):
            assert length_text(length_mm) == text
    finally:
        QtCore.QLocale.setDefault(before)


def test_dimensions_follow_the_users_unit_system(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    # The active document's own unit system decides the schema, so setting
    # only the global one would be undone when the document activates.
    with _unit_system("ImperialDecimal"):
        placed_unit.Document.UnitSystem = "Imperial decimal (in, lb)"
        panel = edit_unit(placed_unit, driver)
        add_board(panel, "vertical", driver)
        drawn = overlay_nodes.labels(editor_of(panel).root)
        assert drawn
        assert all(label.text.endswith(" in") for label in drawn), drawn
        click_task_button("Close", driver)


@pytest.mark.parametrize("route", ["status bar", "preferences"])
def test_dimensions_follow_a_unit_change_while_the_editor_is_open(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver, route: str
) -> None:
    """Each route sets what FreeCAD's own code sets, in its order: the status
    bar's unit menu sets the document's unit system and then the schema;
    Preferences saves the Units group and then sets the schema."""
    params = FreeCAD.ParamGet(_UNITS_PARAMS)
    panel = edit_unit(placed_unit, driver)
    add_board(panel, "vertical", driver)
    assert all(
        label.text.endswith(" mm")
        for label in overlay_nodes.labels(editor_of(panel).root)
    )
    imperial = FreeCAD.Units.listSchemas().index("ImperialDecimal")
    with _unit_system("Internal"):
        try:
            if route == "status bar":
                placed_unit.Document.UnitSystem = "Imperial decimal (in, lb)"
            else:
                params.SetBool("IgnoreProjectSchema", True)
                params.SetInt("UserSchema", imperial)
            FreeCAD.Units.setSchema(imperial)
            driver.pump()
            drawn = overlay_nodes.labels(editor_of(panel).root)
            assert drawn
            assert all(label.text.endswith(" in") for label in drawn), drawn
        finally:
            params.RemBool("IgnoreProjectSchema")
            params.RemInt("UserSchema")
    click_task_button("Close", driver)


def _layered(placed_unit: FreeCAD.DocumentObject, driver: ViewDriver) -> EditUnitPanel:
    """Edit Unit open on the unit split four times, which stacks two rows
    of dimensions left of it and two below it."""
    panel = edit_unit(placed_unit, driver)
    for direction in ("horizontal", "vertical", "horizontal", "vertical"):
        add_board(panel, direction, driver)
    editor_of(panel).select(None)
    panel._refresh()
    driver.pump()
    return panel


def test_rows_of_dimensions_outside_the_unit_clear_it_and_each_other(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    """Each outer dimension's text, its padlock's room included, measured as
    SoDatumLabel lays it out, at the view the editor opens to."""
    panel = _layered(placed_unit, driver)
    editor = editor_of(panel)
    session = panel.session
    metrics = label_metrics(editor.style.label_size_pt)
    ratio = editor._label_ratio

    def screen_rect(
        h0_mm: float, v0_mm: float, h1_mm: float, v1_mm: float
    ) -> QtCore.QRectF:
        a = driver.qt_point(editor.to_document(h0_mm, v0_mm))
        b = driver.qt_point(editor.to_document(h1_mm, v1_mm))
        return QtCore.QRectF(a, b).normalized()

    outer = screen_rect(*editor.frame.rect(session.spaces[session.unit.root.id]))
    texts: list[tuple[str, QtCore.QRectF]] = []
    for label in editor.overlay.labels:
        center = driver.qt_point(editor.to_document(*label.text_at_mm))
        if outer.contains(center):
            continue
        long_px = metrics.horizontalAdvance(label_string(label, editor.style)) / ratio
        short_px = metrics.height() / ratio
        w_px, h_px = (long_px, short_px) if label.horizontal else (short_px, long_px)
        texts.append(
            (
                label.region_id,
                QtCore.QRectF(center.x() - w_px / 2, center.y() - h_px / 2, w_px, h_px),
            )
        )
    left = [rect for _id, rect in texts if rect.right() < outer.left()]
    below = [rect for _id, rect in texts if rect.top() > outer.bottom()]
    assert len(left) >= 2 and len(below) >= 2, texts
    for region_id, rect in texts:
        assert not rect.intersects(outer), (region_id, rect, outer)
    for i, (first_id, first) in enumerate(texts):
        for second_id, second in texts[i + 1 :]:
            assert not first.intersects(second), (first_id, second_id)
    click_task_button("Close", driver)


def test_resizing_the_unit_moves_only_the_rows_past_a_moving_face(
    placed_unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    """The fixed point stays at the unit's low corner, so a taller or wider
    unit keeps the rows left of it and below it where they were and only
    lengthens their lines."""
    panel = _layered(placed_unit, driver)
    editor = editor_of(panel)

    def lines() -> dict[str, tuple[tuple[float, float], tuple[float, float]]]:
        return {x.region_id: (x.start_mm, x.end_mm) for x in editor.overlay.labels}

    before = lines()
    for dimension, size_mm in (("height", 1400.0), ("width", 1600.0)):
        assert panel.session.resize(dimension, size_mm) is None
        panel._refresh()
        driver.pump()
    after = lines()
    for region_id, ((h0_mm, v0_mm), (h1_mm, v1_mm)) in before.items():
        if h0_mm < 0 and h0_mm == h1_mm:
            assert after[region_id][0][0] == pytest.approx(h0_mm), region_id
        if v0_mm < 0 and v0_mm == v1_mm:
            assert after[region_id][0][1] == pytest.approx(v0_mm), region_id
    assert any(h0_mm < 0 for (h0_mm, _v), _end in before.values())
    assert any(v0_mm < 0 for (_h, v0_mm), _end in before.values())
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


@pytest.mark.full_only
def test_closing_the_document_while_the_camera_turns_back_raises_nothing(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
    slow_turns: None,
) -> None:
    errors: list[BaseException] = []

    def record(
        _kind: type[BaseException], value: BaseException, _trace: TracebackType | None
    ) -> None:
        errors.append(value)

    monkeypatch.setattr(sys, "excepthook", record)
    driver.view.viewIsometric()
    driver.pump()
    edit_unit(unit, driver)
    press_task_button("Close")
    FreeCAD.closeDocument(unit.Document.Name)
    # As long as the rest of the turn back would have taken.
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
    driver.pump()
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


def test_a_qa_setup_closes_the_panel_the_last_case_left_open(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    qa_actions.fresh_unit()
    driver.pump()
    assert editor.closed
    assert panel.editor is None
    assert not FreeCADGui.Control.activeDialog()
    doc = cast("FreeCAD.Document", FreeCAD.ActiveDocument)
    container = cast("FreeCAD.DocumentObject", doc.getObject("ShelvingUnit"))
    reopened = edit_unit(container, ViewDriver.for_active_view())
    assert reopened.editor is not None


def test_closing_the_3d_view_under_the_edit_leaves_the_panel_working(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the view it edits in closed and the document open in another,
    the editor stands down at the next redraw: the panel keeps editing the
    unit's size and following Undo until its Close, and nothing raises."""
    errors: list[BaseException] = []

    def record(
        _kind: type[BaseException], value: BaseException, _trace: TracebackType | None
    ) -> None:
        errors.append(value)

    monkeypatch.setattr(sys, "excepthook", record)
    doc = unit.Document
    FreeCADGui.runCommand("Std_ViewCreate")
    extra = ViewDriver.for_active_view()
    panel = edit_unit(unit, extra)
    editor = editor_of(panel)
    outside = _outside_box(doc, "Outside", 2000.0)
    # Closing the extra view leaves the document its first one, so FreeCAD
    # asks nothing.
    FreeCADGui.runCommand("Std_CloseActiveWindow")
    driver = ViewDriver.for_active_view()

    panel._resize("width", 700.0)
    driver.pump()
    assert editor.closed
    assert panel.session.unit_dimension_mm("width") == pytest.approx(700.0)
    assert list(doc.UndoNames)[0] == "Resize Unit"
    gui_step("Std_Undo", driver)
    width = panel.unit_fields["width"].quantity_widget
    assert width is not None
    assert width.property("rawValue") == pytest.approx(600.0)
    assert FreeCADGui.Control.activeDialog()
    # No gate is left to refuse a pick.
    FreeCADGui.Selection.clearSelection()
    FreeCADGui.Selection.addSelection(doc.Name, outside.Name)
    assert FreeCADGui.Selection.getSelection()
    click_task_button("Close", driver)
    assert not FreeCADGui.Control.activeDialog()
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
