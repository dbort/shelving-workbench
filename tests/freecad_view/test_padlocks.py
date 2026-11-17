"""The padlocks of Edit Unit's 3D view: one at the head of the icon row
after each opening's dimension, which locks or unlocks that opening, and
one in place of a held board's arrow, which unlocks the openings holding
it. Also the tile under each dimension's text, which opens its size
field."""

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from freecad.Shelving.core.edit import is_locked
from freecad.Shelving.core.geometry import Space
from freecad.Shelving.core.layout import Board, Division, Region
from freecad.Shelving.editor import overlay
from freecad.Shelving.editor import view_editor as view_editor_module
from freecad.Shelving.editor.elevation import (
    FIRST_CONSTRAINT_SLOT,
    LIFT_MM,
    PADLOCK_SLOT,
    DimensionLabel,
    PadlockIcon,
    RowIcon,
    icon_center_px,
)
from freecad.Shelving.editor.overlay import RGB, TILE_PAD_PX, IconNode, ViewParams
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import EditFailure
from freecad.Shelving.editor.view_editor import ViewEditor
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import (
    add_board,
    bay_ids,
    click_task_button,
    edit_unit,
    editor_of,
    gui_step,
    notification_count,
    selection,
)
from tests.freecad_view.view import ViewDriver

_VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
_TOL_MM = 1e-6
# The tile color the tests give the view's background reading: far from
# every fill, board and dimension color, so a pixel of it is a tile's.
_TILE_RGB: RGB = (0.2, 0.4, 0.3)


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


def _padlock(editor: ViewEditor, region_id: str) -> PadlockIcon:
    (padlock,) = [p for p in editor.overlay.padlocks if p.label.region_id == region_id]
    return padlock


def _node(editor: ViewEditor, region_id: str) -> IconNode[PadlockIcon]:
    (node,) = [n for n in editor.padlock_nodes if n.icon.label.region_id == region_id]
    return node


def _press(editor: ViewEditor, region_id: str, driver: ViewDriver) -> None:
    """Press ``region_id``'s padlock where the view draws it."""
    driver.click(editor.icon_center(_padlock(editor, region_id)))


def _glyph(editor: ViewEditor, image: QtGui.QImage) -> QtGui.QImage:
    """The padlock at the far end of a row icon's padded ``image``, or all
    of a held padlock's."""
    side_px, _gap_px = editor._icon_metrics_px()
    if image.width() > side_px:
        return image.copy(image.width() - side_px, 0, side_px, side_px)
    # A vertical dimension's padding runs below the icon.
    return image.copy(0, 0, side_px, side_px)


def _assert_drawn(editor: ViewEditor, image: QtGui.QImage, locked: bool) -> None:
    """``image`` shows a closed padlock in the locked dimension color, or an
    open one in the unlocked color, on a rounded tile of the view's
    background."""
    glyph = _glyph(editor, image)
    side_px = glyph.width()
    pad_px = editor.icon_tile().pad_px
    inner_px = side_px - 2 * pad_px
    ink = editor.style.label_rgb("locked" if locked else "unlocked")

    def at(x: float, y: float) -> QtGui.QColor:
        """The pixel holding ``(x, y)`` in the glyph's own 0-to-1 square."""
        return glyph.pixelColor(pad_px + int(x * inner_px), pad_px + int(y * inner_px))

    body = at(0.5, 0.72)
    assert _close_rgb(_color_rgb(body), ink), _color_rgb(body)
    # The shackle closes over the body's left side; open, it swings clear.
    inked = _inked_share(_color_rgb(at(4.1 / 14, 4.5 / 14)), ink, editor)
    assert inked > 0.5 if locked else inked < 0.2, inked
    edge = glyph.pixelColor(side_px // 2, 0)
    assert edge.alpha() == 255 and _close_rgb(_color_rgb(edge), editor.style.tile_rgb)
    assert glyph.pixelColor(0, 0).alpha() < 255


def _inked_share(drawn: RGB, ink: RGB, editor: ViewEditor) -> float:
    """How far ``drawn`` lies from the tile color toward ``ink``: a pixel's
    ink coverage."""
    tile = editor.style.tile_rgb
    return max(
        abs(d - t) / abs(i - t)
        for d, i, t in zip(drawn, ink, tile, strict=True)
        if abs(i - t) > 0.1
    )


def _same_spaces(a: Mapping[str, Space], b: Mapping[str, Space]) -> bool:
    return a.keys() == b.keys() and all(
        abs(a[key].origin.component_mm(i) - b[key].origin.component_mm(i)) < _TOL_MM
        and abs(a[key].size.component_mm(i) - b[key].size.component_mm(i)) < _TOL_MM
        for key in a
        for i in (0, 1, 2)
    )


def _locked(region: Region, region_id: str) -> bool:
    if region.id == region_id:
        return is_locked(region)
    if isinstance(region, Division):
        return any(
            _locked(item, region_id)
            for item in region.items
            if not isinstance(item, Board)
        )
    return False


def _rounded(point: FreeCAD.Vector) -> tuple[float, float, float]:
    return (round(point.x, 3), round(point.y, 3), round(point.z, 3))


def _lone_regions(region: Region) -> set[str]:
    """Every region alone in its run: the only one that is not a board."""
    if not isinstance(region, Division):
        return set()
    children = [item for item in region.items if not isinstance(item, Board)]
    lone = {children[0].id} if len(children) == 1 else set()
    for child in children:
        lone |= _lone_regions(child)
    return lone


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
    """The corners of each outline drawn in the locked dimension color,
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


def _three_bays(panel: EditUnitPanel, driver: ViewDriver) -> tuple[str, str]:
    """Split the lowest bay twice; returns the two shelves, lowest first."""
    added = [add_board(panel, "vertical", driver) for _ in range(2)]
    spaces = panel.session.spaces
    low, high = sorted(added, key=lambda shelf: spaces[shelf].origin.z_mm)
    return low, high


def _slot_center(editor: ViewEditor, icon: RowIcon) -> QtCore.QPointF:
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


def _padlocks_misplaced(driver: ViewDriver, editor: ViewEditor) -> list[str]:
    """Why each padlock on the viewport is not drawn at slot 0 of its row."""
    image = driver.grab()
    problems: list[str] = []
    assert [node.icon for node in editor.padlock_nodes] == list(editor.overlay.padlocks)
    for padlock in editor.overlay.padlocks:
        center = _slot_center(editor, padlock)
        if _visible(editor, center):
            problem = _tile_misplaced(editor, image, center)
            if problem is not None:
                problems.append(f"{padlock.label.region_id}: {problem}")
    return problems


@pytest.mark.parametrize(
    "unit_system", ["Standard (mm, kg, s, °)", "Building US (ft-in, sqft, cft)"]
)
def test_every_dimension_shows_its_padlock_after_its_text(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
    unit_system: str,
) -> None:
    """Building US writes the longest labels, such as ``8" + 5/8"``."""
    schema = FreeCAD.Units.getSchema()
    unit.Document.UnitSystem = unit_system
    try:
        _check_padlocks_after_their_text(unit, driver)
    finally:
        FreeCAD.Units.setSchema(schema)


def _check_padlocks_after_their_text(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower = bay_ids(session.unit.root)[0]
    assert session.set_lock(lower, locked=True) is None
    panel._refresh()
    driver.pump()
    # The fresh unit's single column of bays sits alone in its row, and
    # still shows a padlock.
    lone = _lone_regions(session.unit.root)
    assert lone & {x.region_id for x in editor.overlay.labels}
    assert len(editor.padlock_nodes) == len(editor.overlay.labels)
    for label in editor.overlay.labels:
        node = _node(editor, label.region_id)
        _assert_drawn(editor, node.drawn, label.color == "locked")
    assert _padlocks_misplaced(driver, editor) == []
    # The padlocks follow their labels when the camera pans and zooms.
    camera = editor.view.getCameraNode()
    x_mm, y_mm, z_mm = camera.position.getValue().getValue()
    camera.position.setValue(x_mm + 40.0, y_mm, z_mm + 30.0)
    camera.height.setValue(float(camera.height.getValue()) * 0.8)
    driver.pump()
    assert _padlocks_misplaced(driver, editor) == []
    click_task_button("Close", driver)


def test_the_padlock_leads_the_row_and_the_constraint_icons_follow_it(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
) -> None:
    """One placement places both kinds: the padlock's tile where it puts
    slot 0, the first constraint icon's where it puts slot 1."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    _three_bays(panel, driver)
    session = panel.session
    bottom, _middle, top = bay_ids(session.unit.root)
    session.select_items([bottom, top])
    panel.constrain("equal")
    editor.select(None)
    driver.pump()
    image = driver.grab()
    for region_id in (bottom, top):
        padlock = _padlock(editor, region_id)
        (icon,) = [i for i in editor.overlay.icons if i.label.region_id == region_id]
        assert (padlock.slot, icon.slot) == (PADLOCK_SLOT, FIRST_CONSTRAINT_SLOT)
        for entry in (padlock, icon):
            center = _slot_center(editor, entry)
            assert _tile_misplaced(editor, image, center) is None, entry
    click_task_button("Close", driver)


def test_padlocks_follow_their_labels_when_the_view_resizes(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
) -> None:
    """A resize moves every projected point without moving the camera, as
    moving the window to another display can."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    window = cast("QtWidgets.QMainWindow", FreeCADGui.getMainWindow())
    size = window.size()
    viewport_size = editor.viewport.size()
    try:
        window.resize(size.width() - 300, size.height() - 200)
        driver.pump()
        assert editor.viewport.size() != viewport_size
        problems = _padlocks_misplaced(driver, editor)
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
    lower_shelf, _upper_shelf = _three_bays(panel, driver)
    bottom = bay_ids(panel.session.unit.root)[0]
    session = panel.session
    session.select_items([bottom, bay_ids(session.unit.root)[2]])
    panel.constrain("equal")
    _press(editor, bottom, driver)
    _press(editor, bay_ids(session.unit.root)[1], driver)
    editor.select(lower_shelf)
    driver.pump()
    assert editor.held_marker.shown
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
    assert editor.padlock_nodes and editor.icon_nodes
    for node in (*editor.padlock_nodes, *editor.icon_nodes):
        across_px = (
            node.drawn.height() if node.icon.label.horizontal else node.drawn.width()
        )
        assert across_px == new_side_px, node.icon
    assert editor.held_marker.drawn.size() == QtCore.QSize(new_side_px, new_side_px)
    pad_px = round(TILE_PAD_PX * ratio)
    metrics = editor._label_metrics
    assert editor.text_tiles
    for tile in editor.text_tiles:
        across_px = tile.drawn.height() if tile.label.horizontal else tile.drawn.width()
        assert across_px == metrics.height() + 2 * pad_px
    for button in editor.add_bar.buttons.values():
        device_px = round(24 * ratio)
        assert QtCore.QSize(device_px, device_px) in button.icon().availableSizes()
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
            labels = list(editor.overlay.labels)
            if [node.icon.label for node in editor.padlock_nodes] != labels:
                self.problems.append(f"step {self.steps}: padlocks")
            if [tile.label for tile in editor.text_tiles] != labels:
                self.problems.append(f"step {self.steps}: text tiles")

        return rebuilt


def test_padlocks_and_text_tiles_follow_a_drag(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    shelf = add_board(panel, "vertical", driver)
    session = panel.session
    watch = _DragWatch(editor)
    monkeypatch.setattr(editor, "rebuild", watch.wrap(editor.rebuild))
    arrow = editor.arrow
    assert arrow is not None and arrow.board_id == shelf
    z_before_mm = session.spaces[shelf].origin.z_mm
    start = driver.qt_point(editor.to_document(*arrow.at_mm, editor.frame.z_sign * 2.0))
    driver.drag(start, start - QtCore.QPointF(0.0, 60.0), steps=16)
    driver.pump()
    assert session.spaces[shelf].origin.z_mm > z_before_mm + 5.0
    assert watch.steps >= 16
    assert watch.problems == []
    assert _padlocks_misplaced(driver, editor) == []
    click_task_button("Close", driver)


def test_a_padlock_locks_and_unlocks_its_opening_moving_nothing(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    reported: list[str],
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    shelf = add_board(panel, "vertical", driver)
    session = panel.session
    doc = unit.Document
    lower, upper = bay_ids(session.unit.root)
    spaces = dict(session.spaces)
    names = list(doc.UndoNames)
    picked = selection()
    _press(editor, lower, driver)
    assert _locked(session.unit.root, lower)
    assert list(doc.UndoNames) == ["Lock Opening", *names]
    assert _same_spaces(session.spaces, spaces)
    assert session.selected_id == shelf
    assert selection() == picked
    assert editor.field is None
    _assert_drawn(editor, _node(editor, lower).drawn, locked=True)
    assert _label_of(editor, lower).color == "locked"

    # The column's last unlocked bay locks too, with no report, and makes
    # the unit's height a reference.
    count = notification_count()
    _press(editor, upper, driver)
    assert reported == []
    assert notification_count() == count
    assert _locked(session.unit.root, upper)
    assert list(doc.UndoNames) == ["Lock Opening", "Lock Opening", *names]
    assert _same_spaces(session.spaces, spaces)
    _assert_drawn(editor, _node(editor, upper).drawn, locked=True)
    assert panel.unit_fields["height"].read_only
    _press(editor, upper, driver)
    assert not _locked(session.unit.root, upper)
    assert not panel.unit_fields["height"].read_only
    assert list(doc.UndoNames) == [
        "Unlock Opening",
        "Lock Opening",
        "Lock Opening",
        *names,
    ]
    names = list(doc.UndoNames)

    _press(editor, lower, driver)
    assert not _locked(session.unit.root, lower)
    assert list(doc.UndoNames) == ["Unlock Opening", *names]
    assert _same_spaces(session.spaces, spaces)
    assert editor.field is None
    _assert_drawn(editor, _node(editor, lower).drawn, locked=False)

    gui_step("Std_Undo", driver)
    # Undo rescans the unit, which names its regions afresh.
    lower = bay_ids(session.unit.root)[0]
    assert _locked(session.unit.root, lower)
    _assert_drawn(editor, _node(editor, lower).drawn, locked=True)
    click_task_button("Close", driver)


def test_a_refused_lock_reaches_the_notification_area(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    reported: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    lower = bay_ids(panel.session.unit.root)[0]

    def refuse(region_id: str, _locked: bool) -> EditFailure:
        return EditFailure("refused for the test", region_id)

    monkeypatch.setattr(panel.session, "set_lock", refuse)
    count = notification_count()
    _press(editor, lower, driver)
    assert reported == ["refused for the test"]
    assert notification_count() == count + 1
    monkeypatch.undo()
    click_task_button("Close", driver)


def test_a_padlock_wins_a_press_over_a_text_tile(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Text tiles grown over every padlock, for the press's hit test alone,
    still leave a press on a padlock to it."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    lower = bay_ids(panel.session.unit.root)[0]
    center = editor.icon_center(_padlock(editor, lower))
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
    assert _locked(panel.session.unit.root, lower)
    assert editor.field is None
    monkeypatch.undo()
    click_task_button("Close", driver)


def test_a_refused_edit_outlines_its_locks_until_the_next_edit_or_selection(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    """With both bays of the column locked, a new height is refused, and
    the two locks its failure names carry the holding outline, as the
    Sketcher highlights the constraints in a conflict."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower, upper = bay_ids(session.unit.root)
    _press(editor, lower, driver)
    _press(editor, upper, driver)
    editor.select(None)
    driver.pump()
    assert _holding_outlines(editor) == set()
    expected = {_corners(editor, lower), _corners(editor, upper)}

    def refuse() -> None:
        failure = session.resize("height", 1000.0)
        assert failure is not None
        assert failure.region_ids == (lower, upper)
        panel._refresh()
        driver.pump()
        assert _holding_outlines(editor) == expected

    refuse()
    editor.select(upper)
    driver.pump()
    assert _holding_outlines(editor) == set()
    editor.select(None)
    refuse()
    assert session.resize("width", 700.0) is None
    panel._refresh()
    driver.pump()
    assert _holding_outlines(editor) == set()
    click_task_button("Close", driver)


def test_a_redundant_lock_warns_and_outlines_the_locks_it_repeats(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    """With both bays of the column locked, the padlock of the row holding
    the column repeats them: it locks, a warning reaches the Notification
    Area, and the two bays carry the holding outline."""
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower, upper = bay_ids(session.unit.root)
    _press(editor, lower, driver)
    _press(editor, upper, driver)
    editor.select(None)
    driver.pump()
    root = session.unit.root
    assert isinstance(root, Division)
    row = next(item for item in root.items if isinstance(item, Division))
    count = notification_count()
    _press(editor, row.id, driver)
    assert _locked(session.unit.root, row.id)
    assert notification_count() == count + 1
    assert session.flagged == (lower, upper)
    assert _holding_outlines(editor) == {
        _corners(editor, lower),
        _corners(editor, upper),
    }
    click_task_button("Close", driver)


def test_typing_a_size_closes_the_padlock(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    upper = bay_ids(session.unit.root)[1]
    _assert_drawn(editor, _node(editor, upper).drawn, locked=False)
    editor.open_field(_label_of(editor, upper))
    field_ = editor.field
    assert field_ is not None
    field_.line_edit.selectAll()
    QtTest.QTest.keyClicks(field_.line_edit, "250")
    QtTest.QTest.keyClick(field_.line_edit, QtCore.Qt.Key.Key_Return)
    driver.pump()
    assert _locked(session.unit.root, upper)
    _assert_drawn(editor, _node(editor, upper).drawn, locked=True)
    click_task_button("Close", driver)


def test_a_held_board_shows_a_padlock_that_unlocks_the_openings_holding_it(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    tile_background: None,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    lower_shelf, _upper_shelf = _three_bays(panel, driver)
    session = panel.session
    doc = unit.Document
    bottom, middle, _top = bay_ids(session.unit.root)
    _press(editor, bottom, driver)
    _press(editor, middle, driver)
    editor.select(lower_shelf)
    driver.pump()
    assert editor.arrow is None
    held = editor.held
    assert held is not None and held.holders == (bottom,)
    assert editor.held_marker.shown
    _assert_drawn(editor, editor.held_marker.drawn, locked=True)
    (at,) = overlay_nodes.markers(editor.root, editor.held_marker.root)
    assert (at - editor.to_document(*held.at_mm)).Length < 1e-3
    center = driver.qt_point(editor.to_document(*held.at_mm))
    # The holder's outline in the locked dimension color, and no other.
    locked_rgb = _rgb("ConstrainedDimColor")
    holding = [
        outline
        for outline in overlay_nodes.outlines(editor.root)
        if _close_rgb(outline.rgb, locked_rgb)
    ]
    assert len(holding) == 1
    lift_mm = editor.to_document(
        0, 0, editor.frame.z_sign * LIFT_MM
    ) - editor.to_document(0, 0, 0)
    drawn = frozenset(_rounded(point - lift_mm) for point in holding[0].points)
    assert drawn == _corners(editor, bottom)

    spaces = dict(session.spaces)
    names = list(doc.UndoNames)
    driver.click(center)
    assert list(doc.UndoNames) == ["Unlock Board", *names]
    assert not _locked(session.unit.root, bottom)
    assert _locked(session.unit.root, middle)
    assert _same_spaces(session.spaces, spaces)
    assert session.selected_id == lower_shelf
    assert editor.arrow is not None and editor.arrow.board_id == lower_shelf
    assert not editor.held_marker.shown
    assert overlay_nodes.markers(editor.root, editor.held_marker.root) == []
    assert not any(
        _close_rgb(outline.rgb, locked_rgb)
        for outline in overlay_nodes.outlines(editor.root)
    )
    click_task_button("Close", driver)


def test_every_padlock_sits_on_a_rounded_tile_of_the_view_background(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, tile_background: None
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    lower_shelf, _upper_shelf = _three_bays(panel, driver)
    bottom, _middle, _top = bay_ids(panel.session.unit.root)
    _press(editor, bottom, driver)
    editor.select(lower_shelf)
    driver.pump()
    assert _close_rgb(editor.style.tile_rgb, _TILE_RGB)
    assert editor.padlock_nodes and editor.held_marker.shown
    for node in editor.padlock_nodes:
        _assert_drawn(editor, node.drawn, node.icon.locked)
    _assert_drawn(editor, editor.held_marker.drawn, locked=True)
    click_task_button("Close", driver)


def test_a_carcass_board_shows_neither_arrow_nor_padlock(
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
        assert editor.held is None
        assert not editor.held_marker.shown
    click_task_button("Close", driver)


@pytest.mark.parametrize(
    "dragged", ["lower", pytest.param("upper", marks=pytest.mark.full_only)]
)
def test_a_drag_carries_both_shelves_around_a_locked_opening(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dragged: str
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    shelves = _three_bays(panel, driver)
    session = panel.session
    middle = bay_ids(session.unit.root)[1]
    _press(editor, middle, driver)
    assert _locked(session.unit.root, middle)
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
    assert _locked(session.unit.root, middle)
    click_task_button("Close", driver)


# --- text tiles ----------------------------------------------------------


def _wide(unit: FreeCAD.DocumentObject, driver: ViewDriver) -> EditUnitPanel:
    """Edit Unit on ``unit`` widened so its width dimensions have room too,
    reopened so the view fits it, and split four ways."""
    panel = edit_unit(unit, driver)
    assert panel.session.resize("width", 1500.0) is None
    click_task_button("Close", driver)
    panel = edit_unit(unit, driver)
    for direction in ("horizontal", "vertical", "horizontal", "vertical"):
        add_board(panel, direction, driver)
    editor_of(panel).select(None)
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
    rgb = editor.style.label_rgb(label.color)
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


def _longest(editor: ViewEditor) -> DimensionLabel:
    return max(editor.overlay.labels, key=lambda x: editor.text_tile_px(x)[0])


@pytest.fixture
def us_units(unit: FreeCAD.DocumentObject) -> Iterator[None]:
    """Building US, which writes the longest labels."""
    schema = FreeCAD.Units.getSchema()
    unit.Document.UnitSystem = "Building US (ft-in, sqft, cft)"
    yield
    FreeCAD.Units.setSchema(schema)


def test_a_press_anywhere_on_a_text_tile_opens_its_field_and_nowhere_else(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    us_units: None,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    editor.select(None)
    driver.pump()
    label = _longest(editor)
    rect = editor.text_tile_rect(label)
    # Clear of the padlock, which follows the text's end.
    if label.horizontal:
        corner, out = rect.topLeft(), QtCore.QPointF(-1.0, -1.0)
    else:
        corner, out = rect.bottomLeft(), QtCore.QPointF(-1.0, 1.0)
    driver.click(corner + out * 2.0)
    assert editor.field is None
    driver.click(corner - out * 1.0)
    assert editor.field is not None
    assert panel.session.selected_id == label.region_id
    click_task_button("Close", driver)
