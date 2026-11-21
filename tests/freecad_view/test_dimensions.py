"""Edit Unit's 3D view draws sizes as the Sketcher draws dimensions: a
Lock as a driving dimension in the Sketcher's colors, and a selected or
constrained opening's size as a reference dimension in parentheses. A click
on a dimension's text selects its Lock or its opening, a double-click opens
its size field, and the constraint icons and text tiles each dimension
carries stay where they belong as the view moves."""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from freecad.Shelving.core.edit import measure
from freecad.Shelving.core.geometry import Space
from freecad.Shelving.core.layout import (
    Board,
    ConstraintId,
    Division,
    Region,
    Unit,
    is_locked,
    region_lock,
)
from freecad.Shelving.editor import overlay
from freecad.Shelving.editor import view_editor as view_editor_module
from freecad.Shelving.editor.elevation import (
    LIFT_MM,
    ConstraintIcon,
    DimensionLabel,
    icon_center_px,
)
from freecad.Shelving.editor.overlay import RGB, TILE_PAD_PX, ViewParams, length_text
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.view_editor import ViewEditor
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import (
    add_board,
    bay_ids,
    click_task_button,
    edit_unit,
    editor_of,
    notification_count,
    press_delete,
    selection,
)
from tests.freecad_view.view import ViewDriver

_VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
_TOL_MM = 1e-6
# The tile color the tests give the view's background reading: far from
# every fill, board and dimension color, so a pixel of it is a tile's.
_TILE_RGB: RGB = (0.2, 0.4, 0.3)
_CTRL = QtCore.Qt.KeyboardModifier.ControlModifier


def _rgb(name: str) -> tuple[float, float, float]:
    packed = FreeCAD.ParamGet(_VIEW_PARAMS).GetUnsigned(name, 0)
    return (
        ((packed >> 24) & 0xFF) / 255,
        ((packed >> 16) & 0xFF) / 255,
        ((packed >> 8) & 0xFF) / 255,
    )


def _close_rgb(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(x - y) < 2.5 / 255 for x, y in zip(a, b, strict=True))


def _color_rgb(color: QtGui.QColor) -> RGB:
    return (color.redF(), color.greenF(), color.blueF())


@pytest.fixture
def tile_background(monkeypatch: pytest.MonkeyPatch) -> None:
    """The editor reads :data:`_TILE_RGB` as the view's background; FreeCAD's
    view keeps its own."""

    def background(_params: ViewParams) -> RGB:
        return _TILE_RGB

    monkeypatch.setattr(overlay, "background_rgb", background)


def _label_of(editor: ViewEditor, region_id: str) -> DimensionLabel:
    (label,) = [x for x in editor.overlay.labels if x.region_id == region_id]
    return label


def _drawn(editor: ViewEditor) -> dict[str, overlay_nodes.Label]:
    """Each drawn dimension node, by the region its planned label names:
    the drawing adds them in the plan's order."""
    nodes = overlay_nodes.labels(editor.root)
    labels = editor.overlay.labels
    assert len(nodes) == len(labels)
    return {label.region_id: node for label, node in zip(labels, nodes, strict=True)}


def _tile_center(editor: ViewEditor, region_id: str) -> QtCore.QPointF:
    return editor.text_tile_rect(_label_of(editor, region_id)).center()


def _lock_id(unit: Unit, region_id: str) -> ConstraintId:
    """The id of the Lock on the region named ``region_id``."""
    found = region_lock(unit, region_id)
    assert found is not None
    return found.id


def _three_bays(panel: EditUnitPanel, driver: ViewDriver) -> tuple[str, str]:
    """Split the lowest bay twice; returns the two shelves, lowest first."""
    added = [add_board(panel, "vertical", driver) for _ in range(2)]
    spaces = panel.session.spaces
    low, high = sorted(added, key=lambda shelf: spaces[shelf].origin.z_mm)
    return low, high


def _refreshed(panel: EditUnitPanel, driver: ViewDriver) -> None:
    panel._refresh()
    driver.pump()


def _same_spaces(a: Mapping[str, Space], b: Mapping[str, Space]) -> bool:
    return a.keys() == b.keys() and all(
        abs(a[key].origin.component_mm(i) - b[key].origin.component_mm(i)) < _TOL_MM
        and abs(a[key].size.component_mm(i) - b[key].size.component_mm(i)) < _TOL_MM
        for key in a
        for i in (0, 1, 2)
    )


def _rounded(point: FreeCAD.Vector) -> tuple[float, float, float]:
    return (round(point.x, 3), round(point.y, 3), round(point.z, 3))


_Corners = frozenset[tuple[float, float, float]]


def _corners(editor: ViewEditor, region_id: str) -> _Corners:
    """The document points of ``region_id``'s four corners on the drawn face."""
    rect = editor.frame.rect(editor.session.spaces[region_id])
    return frozenset(
        _rounded(editor.to_document(h_mm, v_mm, 0.0))
        for h_mm in (rect.h0_mm, rect.h1_mm)
        for v_mm in (rect.v0_mm, rect.v1_mm)
    )


def _holding_outlines(editor: ViewEditor) -> set[_Corners]:
    """The corners of each outline drawn in the driving dimension color,
    brought back onto the face from the lift outlines sit at."""
    locked_rgb = _rgb("ConstrainedDimColor")
    lift_mm = editor.to_document(
        0, 0, editor.frame.z_sign * LIFT_MM
    ) - editor.to_document(0, 0, 0)
    return {
        frozenset(_rounded(point - lift_mm) for point in outline.points)
        for outline in overlay_nodes.outlines(editor.root)
        if _close_rgb(outline.rgb, locked_rgb)
    }


# --- what is drawn, in which color and text ------------------------------


def test_dimensions_take_the_sketchers_colors_and_reference_parentheses(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower, upper = bay_ids(session.unit.root)
    editor.select(None)
    driver.pump()
    assert editor.overlay.labels == []
    assert session.set_lock(lower, locked=True) is None
    _refreshed(panel, driver)
    lower_size = length_text(measure(session.unit, lower, session.spaces).size_mm)
    drawn = _drawn(editor)
    assert set(drawn) == {lower}
    assert _close_rgb(drawn[lower].rgb, _rgb("ConstrainedDimColor"))
    assert drawn[lower].text == lower_size
    lock_id = _lock_id(session.unit, lower)
    assert session.set_constraint_active(lock_id, False) is None
    _refreshed(panel, driver)
    assert _close_rgb(_drawn(editor)[lower].rgb, _rgb("DeactivatedConstrDimColor"))
    assert session.set_constraint_active(lock_id, True) is None
    editor.select_constraints([lock_id])
    driver.pump()
    assert _close_rgb(_drawn(editor)[lower].rgb, _rgb("SelectionColor"))
    # A selected opening shows its size as a reference, and its Lock keeps
    # the driving color: selecting geometry recolors no dimension.
    editor.select(upper)
    driver.pump()
    drawn = _drawn(editor)
    # With the upper bay, its lone column's width, the unit's own.
    assert len(drawn) == 3 and {lower, upper} <= set(drawn)
    assert _close_rgb(drawn[lower].rgb, _rgb("ConstrainedDimColor"))
    assert _close_rgb(drawn[upper].rgb, _rgb("NonDrivingConstrDimColor"))
    upper_size = length_text(measure(session.unit, upper, session.spaces).size_mm)
    assert drawn[upper].text == f"({upper_size})"
    click_task_button("Close", driver)


# --- clicks on a dimension's text ----------------------------------------


def test_a_click_on_a_driving_dimension_selects_its_lock_for_delete(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    doc = unit.Document
    lower, upper = bay_ids(session.unit.root)
    assert session.set_lock(lower, locked=True) is None
    assert session.set_lock(upper, locked=True) is None
    editor.select(None)
    driver.pump()
    lower_lock = _lock_id(session.unit, lower)
    upper_lock = _lock_id(session.unit, upper)
    spaces = dict(session.spaces)
    driver.click(_tile_center(editor, lower))
    assert session.selected_constraints == (lower_lock,)
    assert session.selected_items == ()
    assert selection() == []
    assert editor.field is None
    driver.click(_tile_center(editor, upper), _CTRL)
    assert session.selected_constraints == (lower_lock, upper_lock)
    names = list(doc.UndoNames)
    press_delete(driver)
    assert session.constraints == ()
    assert list(doc.UndoNames) == ["Delete Constraints", *names]
    assert _same_spaces(session.spaces, spaces)
    assert editor.overlay.labels == []
    click_task_button("Close", driver)


def test_a_click_on_a_reference_dimension_selects_its_opening(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower, upper = bay_ids(session.unit.root)
    session.select_items([lower, upper])
    panel.constrain("equal_height")
    editor.select(None)
    driver.pump()
    assert {x.role for x in editor.overlay.labels} == {"reference"}
    driver.click(_tile_center(editor, lower))
    assert session.selected_id == lower
    assert selection() == []
    assert editor.field is None
    driver.click(_tile_center(editor, upper), _CTRL)
    assert session.selected_items == (lower, upper)
    driver.click(_tile_center(editor, upper), _CTRL)
    assert session.selected_items == (lower,)
    click_task_button("Close", driver)


@pytest.mark.smoke("double-click a size in the view and type a new one")
def test_a_double_click_opens_the_size_field_and_typing_locks_the_size(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    """Both presses are the editor's: FreeCAD's selection sees neither, so
    no board behind the text is picked."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower = bay_ids(session.unit.root)[0]
    editor.select(lower)
    driver.pump()
    assert _label_of(editor, lower).role == "reference"
    driver.double_click(_tile_center(editor, lower))
    field_ = editor.field
    assert field_ is not None
    assert session.selected_id == lower
    assert selection() == []
    field_.line_edit.selectAll()
    QtTest.QTest.keyClicks(field_.line_edit, "250")
    QtTest.QTest.keyClick(field_.line_edit, QtCore.Qt.Key.Key_Return)
    driver.pump()
    found = region_lock(session.unit, lower)
    assert found is not None and found.active
    assert measure(session.unit, lower, session.spaces).size_mm == pytest.approx(250.0)
    assert _label_of(editor, lower).role == "driving"
    # A driving dimension opens its field the same way.
    editor.select(None)
    driver.pump()
    driver.double_click(_tile_center(editor, lower))
    assert editor.field is not None
    assert selection() == []
    click_task_button("Close", driver)


def test_an_icon_wins_a_press_over_a_text_tile(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text tiles grown over every icon, for the press's hit test alone,
    still leave a press on an icon to it."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower, upper = bay_ids(session.unit.root)
    session.select_items([lower, upper])
    panel.constrain("equal_height")
    editor.select(None)
    driver.pump()
    (equal,) = session.constraints
    icon = next(i for i in editor.overlay.icons if i.label.region_id == lower)
    center = editor.icon_center(icon)
    real_label_at = view_editor_module.label_at

    def huge(_label: DimensionLabel) -> tuple[float, float]:
        return (4000.0, 4000.0)

    def label_on_huge_tiles(
        labels: Sequence[DimensionLabel],
        project: Callable[[float, float], tuple[float, float]],
        _tile_px: Callable[[DimensionLabel], tuple[float, float]],
        x_px: float,
        y_px: float,
    ) -> DimensionLabel | None:
        return real_label_at(labels, project, huge, x_px, y_px)

    x_px, y_px = editor._device_point(center)
    assert label_on_huge_tiles(editor.overlay.labels, editor._project, huge, x_px, y_px)
    monkeypatch.setattr(view_editor_module, "label_at", label_on_huge_tiles)
    driver.click(center)
    assert session.selected_constraints == (equal.id,)
    assert editor.field is None
    monkeypatch.undo()
    click_task_button("Close", driver)


def _longest(editor: ViewEditor) -> DimensionLabel:
    return max(editor.overlay.labels, key=lambda x: editor.text_tile_px(x)[0])


@pytest.fixture
def us_units(unit: FreeCAD.DocumentObject) -> Iterator[None]:
    """Building US, which writes the longest labels."""
    schema = FreeCAD.Units.getSchema()
    unit.Document.UnitSystem = "Building US (ft-in, sqft, cft)"
    yield
    FreeCAD.Units.setSchema(schema)


def test_a_press_anywhere_on_a_text_tile_is_taken_and_nowhere_else(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    us_units: None,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower = bay_ids(session.unit.root)[0]
    assert session.set_lock(lower, locked=True) is None
    editor.select(None)
    driver.pump()
    label = _longest(editor)
    rect = editor.text_tile_rect(label)
    # Clear of the icon row, which follows the text's end.
    if label.horizontal:
        corner, out = rect.topLeft(), QtCore.QPointF(-1.0, -1.0)
    else:
        corner, out = rect.bottomLeft(), QtCore.QPointF(-1.0, 1.0)
    driver.click(corner + out * 2.0)
    assert session.selected_constraints == ()
    driver.click(corner - out * 1.0)
    assert session.selected_constraints == (_lock_id(session.unit, label.region_id),)
    assert editor.field is None
    click_task_button("Close", driver)


# --- held boards -----------------------------------------------------------


def test_a_shelf_held_only_by_locks_shows_no_arrow_and_outlines_its_holders(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    lower_shelf, _upper_shelf = _three_bays(panel, driver)
    session = panel.session
    bottom, middle, _top = bay_ids(session.unit.root)
    assert session.set_lock(bottom, locked=True) is None
    assert session.set_lock(middle, locked=True) is None
    editor.select(lower_shelf)
    driver.pump()
    assert editor.arrow is None
    # Nothing takes the arrow's place: the only images are the fixed point
    # marker, the text tiles and the constraint icons.
    images = overlay_nodes.markers(editor.root)
    assert len(images) == 1 + len(editor.text_tiles) + len(editor.icon_nodes)
    assert _holding_outlines(editor) == {_corners(editor, bottom)}
    click_task_button("Close", driver)


def test_a_carcass_board_shows_no_arrow(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    assert session.set_lock(bay_ids(session.unit.root)[0], locked=True) is None
    for carcass in ("top", "bottom"):
        editor.select(carcass)
        driver.pump()
        assert editor.arrow is None
    click_task_button("Close", driver)


@pytest.mark.parametrize("dragged", ["lower", "upper"])
def test_a_drag_carries_both_shelves_around_a_locked_opening(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dragged: str
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    shelves = _three_bays(panel, driver)
    session = panel.session
    middle = bay_ids(session.unit.root)[1]
    assert session.set_lock(middle, locked=True) is None
    middle_mm = session.spaces[middle].size.z_mm
    before_mm = [session.spaces[shelf].origin.z_mm for shelf in shelves]
    shelf = shelves[0] if dragged == "lower" else shelves[1]
    editor.select(shelf)
    driver.pump()
    arrow = editor.arrow
    assert arrow is not None and arrow.board_id == shelf
    start = driver.qt_point(editor.to_document(*arrow.at_mm, editor.frame.z_sign * 2.0))
    step = QtCore.QPointF(0.0, -30.0 if dragged == "lower" else 30.0)
    driver.drag(start, start + step)
    driver.pump()
    moved_mm = [
        session.spaces[shelf].origin.z_mm - z_mm
        for shelf, z_mm in zip(shelves, before_mm, strict=True)
    ]
    assert abs(moved_mm[0]) > 5.0, moved_mm
    assert moved_mm[0] == pytest.approx(moved_mm[1], abs=_TOL_MM)
    assert session.spaces[middle].size.z_mm == pytest.approx(middle_mm, abs=_TOL_MM)
    assert is_locked(session.unit, middle)
    click_task_button("Close", driver)


# --- refusals and warnings -------------------------------------------------


def test_a_refused_edit_outlines_its_locks_until_the_next_edit_or_selection(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    """With both bays of the column locked, a new height is refused, and
    the two Locks its failure names carry the holding outline, as the
    Sketcher highlights the constraints in a conflict."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower, upper = bay_ids(session.unit.root)
    assert session.set_lock(lower, locked=True) is None
    assert session.set_lock(upper, locked=True) is None
    editor.select(None)
    driver.pump()
    assert _holding_outlines(editor) == set()
    expected = {_corners(editor, lower), _corners(editor, upper)}

    def refuse() -> None:
        failure = session.resize("height", 1000.0)
        assert failure is not None
        assert failure.constraint_ids == (
            _lock_id(session.unit, lower),
            _lock_id(session.unit, upper),
        )
        _refreshed(panel, driver)
        assert _holding_outlines(editor) == expected

    refuse()
    editor.select(upper)
    driver.pump()
    assert _holding_outlines(editor) == set()
    editor.select(None)
    refuse()
    assert session.resize("width", 700.0) is None
    _refreshed(panel, driver)
    assert _holding_outlines(editor) == set()
    click_task_button("Close", driver)


def test_a_redundant_lock_warns_and_outlines_the_locks_it_repeats(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    """With both bays of the column locked, a Lock on the row holding the
    column repeats them: it locks, a warning reaches the Notification Area,
    and the two bays carry the holding outline."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower, upper = bay_ids(session.unit.root)
    assert session.set_lock(lower, locked=True) is None
    assert session.set_lock(upper, locked=True) is None
    editor.select(None)
    driver.pump()
    root = session.unit.root
    assert isinstance(root, Division)
    row = next(item for item in root.items if isinstance(item, Division))
    count = notification_count()
    assert session.set_lock(row.id, locked=True) is None
    _refreshed(panel, driver)
    assert is_locked(session.unit, row.id)
    assert notification_count() == count + 1
    assert session.flagged == (
        _lock_id(session.unit, lower),
        _lock_id(session.unit, upper),
    )
    assert _holding_outlines(editor) == {
        _corners(editor, lower),
        _corners(editor, upper),
    }
    click_task_button("Close", driver)


# --- icons and text tiles follow the view ----------------------------------


def _slot_center(editor: ViewEditor, icon: ConstraintIcon) -> QtCore.QPointF:
    """Where :func:`icon_center_px` puts ``icon``, in logical pixels."""
    side_px, gap_px = editor._icon_metrics_px()
    x_px, y_px = icon_center_px(
        icon,
        editor._project(*icon.label.text_at_mm),
        editor.text_tile_px(icon.label)[0],
        side_px,
        gap_px,
    )
    ratio = editor.viewport.devicePixelRatioF()
    height_px = editor.view.getSize()[1]
    return QtCore.QPointF(x_px / ratio, (height_px - y_px - 1) / ratio)


def _on_tile(image: QtGui.QImage, point: QtCore.QPointF) -> bool:
    ratio = image.devicePixelRatio()
    color = image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))
    return _close_rgb(_color_rgb(color), _TILE_RGB)


# How far a drawn image may sit from where its center is computed: Coin
# rounds an image's anchor to whole pixels, and aligns it by a pixel or so.
_PLACE_TOL_PX = 2.5


def _tile_box(
    image: QtGui.QImage, center: QtCore.QPointF, half_px: float
) -> QtCore.QRect | None:
    """The device-pixel box of the tile-colored pixels joined to the pad of
    a row icon's tile expected at ``center``, ``half_px`` device pixels
    from each edge; ``None`` when no pad pixel is found."""
    ratio = image.devicePixelRatio()
    cx, cy = center.x() * ratio, center.y() * ratio
    reach = round(2 * half_px)
    seeds = [
        (round(cx + dx * (half_px - 1.5)), round(cy + dy * (half_px - 1.5)))
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
    ]

    def tiled(x: int, y: int) -> bool:
        return (
            abs(x - cx) <= reach
            and abs(y - cy) <= reach
            and _close_rgb(_color_rgb(image.pixelColor(x, y)), _TILE_RGB)
        )

    todo = [seed for seed in seeds if tiled(*seed)]
    seen = set(todo)
    while todo:
        x, y = todo.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) not in seen and tiled(nx, ny):
                seen.add((nx, ny))
                todo.append((nx, ny))
    if not seen:
        return None
    xs = [x for x, _y in seen]
    ys = [y for _x, y in seen]
    return QtCore.QRect(
        QtCore.QPoint(min(xs), min(ys)), QtCore.QPoint(max(xs), max(ys))
    )


def _tile_misplaced(
    editor: ViewEditor, image: QtGui.QImage, center: QtCore.QPointF
) -> str | None:
    """Why the view, grabbed as ``image``, shows no row icon's tile, a
    square of the row icons' side, centered on ``center``; ``None`` when it
    does."""
    side_px, _gap_px = editor._icon_metrics_px()
    box = _tile_box(image, center, side_px / 2)
    if box is None:
        return f"no tile near {center}"
    if abs(box.width() - side_px) > 1 or abs(box.height() - side_px) > 1:
        return f"tile {box} near {center} is not {side_px} square"
    ratio = image.devicePixelRatio()
    # The box's pixel indices run to its last pixel, not past it.
    found = QtCore.QPointF(
        (box.left() + box.right() + 1) / 2, (box.top() + box.bottom() + 1) / 2
    )
    if (found - center * ratio).manhattanLength() > 2 * _PLACE_TOL_PX * ratio:
        return f"tile centered on {found}, expected {center}"
    return None


def _visible(editor: ViewEditor, point: QtCore.QPointF) -> bool:
    return editor.viewport.rect().adjusted(20, 20, -20, -20).contains(point.toPoint())


def _icons_misplaced(driver: ViewDriver, editor: ViewEditor) -> list[str]:
    """Why each constraint icon on the viewport is not drawn at its slot."""
    image = driver.grab()
    problems: list[str] = []
    assert [node.icon for node in editor.icon_nodes] == list(editor.overlay.icons)
    for icon in editor.overlay.icons:
        center = _slot_center(editor, icon)
        if _visible(editor, center):
            problem = _tile_misplaced(editor, image, center)
            if problem is not None:
                problems.append(f"{icon.label.region_id} {icon.slot}: {problem}")
    return problems


def _equal_pair(panel: EditUnitPanel, driver: ViewDriver) -> None:
    """Two bays with an Equal on them, nothing selected: one icon at the
    head of each row, as far from the neighboring dimension as a row
    gets."""
    add_board(panel, "vertical", driver)
    session = panel.session
    session.select_items(bay_ids(session.unit.root))
    panel.constrain("equal_height")
    editor_of(panel).select(None)
    driver.pump()


def _equal_ends(panel: EditUnitPanel, driver: ViewDriver) -> tuple[str, str]:
    """Three bays with an Equal on the bottom and top ones and an even
    spacing over all three, nothing selected; returns the two shelves."""
    shelves = _three_bays(panel, driver)
    session = panel.session
    bottom, _middle, top = bay_ids(session.unit.root)
    session.select_items([bottom, top])
    panel.constrain("equal_height")
    session.select_items([bottom, top])
    panel.constrain("even_height")
    editor_of(panel).select(None)
    driver.pump()
    return shelves


@pytest.mark.parametrize(
    "unit_system", ["Standard (mm, kg, s, °)", "Building US (ft-in, sqft, cft)"]
)
def test_every_icon_sits_in_its_slot_after_its_dimensions_text(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
    unit_system: str,
) -> None:
    """Building US writes the longest labels, such as ``8" + 5/8"``, and a
    reference dimension's parentheses lengthen them further."""
    schema = FreeCAD.Units.getSchema()
    unit.Document.UnitSystem = unit_system
    try:
        panel = edit_unit(unit, driver)
        editor = editor_of(panel)
        _equal_pair(panel, driver)
        assert {icon.slot for icon in editor.overlay.icons} == {0}
        assert _icons_misplaced(driver, editor) == []
        # The icons follow their labels when the camera pans and zooms.
        camera = editor.view.getCameraNode()
        x_mm, y_mm, z_mm = camera.position.getValue().getValue()
        camera.position.setValue(x_mm + 40.0, y_mm, z_mm + 30.0)
        camera.height.setValue(float(camera.height.getValue()) * 0.8)
        driver.pump()
        assert _icons_misplaced(driver, editor) == []
        click_task_button("Close", driver)
    finally:
        FreeCAD.Units.setSchema(schema)


def test_a_second_icon_follows_the_first_one_place_on(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
) -> None:
    """One placement places both slots: the first icon's tile right after
    the text, the second's one place on."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    _equal_ends(panel, driver)
    assert {icon.slot for icon in editor.overlay.icons} == {0, 1}
    assert _icons_misplaced(driver, editor) == []
    click_task_button("Close", driver)


def test_icons_follow_their_labels_when_the_view_resizes(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
) -> None:
    """A resize moves every projected point without moving the camera, as
    moving the window to another display can."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    _equal_pair(panel, driver)
    window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    size = window.size()
    viewport_size = editor.viewport.size()
    try:
        window.resize(size.width() - 300, size.height() - 200)
        driver.pump()
        assert editor.viewport.size() != viewport_size
        problems = _icons_misplaced(driver, editor)
    finally:
        window.resize(size)
        driver.pump()
    assert problems == []
    click_task_button("Close", driver)


def test_images_redraw_for_a_screen_of_another_pixel_ratio(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    _equal_ends(panel, driver)
    viewer = editor._viewer
    ratio = 2 * viewer.devicePixelRatioF()
    side_px, _gap_px = editor._icon_metrics_px()
    monkeypatch.setattr(viewer, "devicePixelRatioF", lambda: ratio)
    QtCore.QCoreApplication.sendEvent(
        editor.viewport, QtCore.QEvent(QtCore.QEvent.Type.DevicePixelRatioChange)
    )
    driver.pump()
    new_side_px, _gap_px = editor._icon_metrics_px()
    assert new_side_px > side_px
    assert editor.icon_nodes
    for node in editor.icon_nodes:
        across_px = (
            node.drawn.height() if node.icon.label.horizontal else node.drawn.width()
        )
        assert across_px == new_side_px, node.icon
    pad_px = round(TILE_PAD_PX * ratio)
    metrics = editor._label_metrics
    assert editor.text_tiles
    for tile in editor.text_tiles:
        across_px = tile.drawn.height() if tile.label.horizontal else tile.drawn.width()
        assert across_px == metrics.height() + 2 * pad_px
    monkeypatch.undo()
    click_task_button("Close", driver)


@dataclass
class _DragWatch:
    """What every redraw during a drag left."""

    editor: ViewEditor
    steps: int = 0
    problems: list[str] = field(default_factory=list)

    def wrap(self, rebuild: Callable[[], None]) -> Callable[[], None]:
        def rebuilt() -> None:
            rebuild()
            editor = self.editor
            self.steps += 1
            if [node.icon for node in editor.icon_nodes] != list(editor.overlay.icons):
                self.problems.append(f"step {self.steps}: icons")
            labels = list(editor.overlay.labels)
            if not labels:
                self.problems.append(f"step {self.steps}: no dimension")
            if [tile.label for tile in editor.text_tiles] != labels:
                self.problems.append(f"step {self.steps}: text tiles")

        return rebuilt


def test_text_tiles_follow_a_drag(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The top bay's Lock keeps a dimension drawn while the lower shelf
    moves."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    lower_shelf, _upper_shelf = _three_bays(panel, driver)
    session = panel.session
    assert session.set_lock(bay_ids(session.unit.root)[2], locked=True) is None
    editor.select(lower_shelf)
    driver.pump()
    watch = _DragWatch(editor)
    monkeypatch.setattr(editor, "rebuild", watch.wrap(editor.rebuild))
    arrow = editor.arrow
    assert arrow is not None and arrow.board_id == lower_shelf
    z_before_mm = session.spaces[lower_shelf].origin.z_mm
    start = driver.qt_point(editor.to_document(*arrow.at_mm, editor.frame.z_sign * 2.0))
    driver.drag(start, start - QtCore.QPointF(0.0, 60.0), steps=16)
    driver.pump()
    assert session.spaces[lower_shelf].origin.z_mm > z_before_mm + 5.0
    assert watch.steps >= 16
    assert watch.problems == []
    click_task_button("Close", driver)


# --- text tiles ------------------------------------------------------------


def _region_ids(region: Region) -> list[str]:
    """Every region below ``region``."""
    if not isinstance(region, Division):
        return []
    found: list[str] = []
    for item in region.items:
        if not isinstance(item, Board):
            found.append(item.id)
            found.extend(_region_ids(item))
    return found


def _wide(unit: FreeCAD.DocumentObject, driver: ViewDriver) -> EditUnitPanel:
    """Edit Unit on ``unit`` widened so its width dimensions have room too,
    reopened so the view fits it, split four ways, and with every region
    selected."""
    panel = edit_unit(unit, driver)
    assert panel.session.resize("width", 1500.0) is None
    click_task_button("Close", driver)
    panel = edit_unit(unit, driver)
    for direction in ("horizontal", "vertical", "horizontal", "vertical"):
        add_board(panel, direction, driver)
    # Every opening selected draws every dimension.
    session = panel.session
    session.select_items(_region_ids(session.unit.root))
    panel._refresh()
    driver.pump()
    return panel


def test_every_dimensions_text_sits_on_a_rounded_tile_of_the_view_background(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
) -> None:
    """In the pad across the text from its line, the tile's color; just
    past the tile, another."""
    panel = _wide(unit, driver)
    editor = editor_of(panel)
    image = driver.grab()
    read = []
    for label in editor.overlay.labels:
        rect = editor.text_tile_rect(label)
        if not _visible(editor, rect.center()):
            continue
        read.append(label.horizontal)
        # Past the pad into the font's height, which the digits leave blank,
        # and as far out: a drawn image sits within a pixel or two of where
        # its center is computed.
        if label.horizontal:
            pad = QtCore.QPointF(rect.center().x(), rect.top() + 3.0)
            past = QtCore.QPointF(rect.center().x(), rect.top() - 3.0)
        else:
            pad = QtCore.QPointF(rect.left() + 3.0, rect.center().y())
            past = QtCore.QPointF(rect.left() - 3.0, rect.center().y())
        assert _on_tile(image, pad), (label.region_id, pad)
        assert not _on_tile(image, past), (label.region_id, past)
    assert set(read) == {True, False}
    for tile in editor.text_tiles:
        drawn = tile.drawn
        # The rounded corners leave the corner pixels off the tile.
        assert drawn.pixelColor(0, 0).alpha() < 255
        middle = drawn.pixelColor(drawn.width() // 2, 0)
        assert middle.alpha() == 255 and _close_rgb(_color_rgb(middle), _TILE_RGB)
    click_task_button("Close", driver)


def _ink(image: QtGui.QImage, point: QtCore.QPointF, rgb: RGB) -> bool:
    ratio = image.devicePixelRatio()
    color = image.pixelColor(round(point.x() * ratio), round(point.y() * ratio))
    return all(abs(a - b) < 0.35 for a, b in zip(_color_rgb(color), rgb, strict=True))


def test_a_short_dimension_shows_its_arrowheads_over_its_text_tile(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
) -> None:
    """A dimension too short to hold its text clear of its arrowheads draws
    them under the text, as the Sketcher does, and over the tile."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower = bay_ids(session.unit.root)[0]
    session.select(lower)
    assert session.set_size(30.0) is None
    session.select(None)
    panel._refresh()
    driver.pump()
    label = _label_of(editor, lower)
    rect = editor.text_tile_rect(label)
    tips = [
        driver.qt_point(editor.to_document(*end))
        for end in (label.start_mm, label.end_mm)
    ]
    assert all(rect.contains(tip) for tip in tips), (rect, tips)
    image = driver.grab()
    rgb = editor.style.label_rgb(label)
    middle = (tips[0] + tips[1]) * 0.5
    for tip in tips:
        # Two pixels in from the tip toward the line's middle, where the
        # arrowhead is a few pixels across.
        toward = middle - tip
        length = (toward.x() ** 2 + toward.y() ** 2) ** 0.5
        inward = tip + toward * (2.0 / length)
        across = QtCore.QPointF(-toward.y(), toward.x()) * (1.0 / length)
        assert any(_ink(image, inward + across * d, rgb) for d in (-1.0, 0.0, 1.0)), (
            tip,
            inward,
        )
    click_task_button("Close", driver)
