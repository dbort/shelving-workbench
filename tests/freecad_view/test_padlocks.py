"""The padlocks of Edit Unit's 3D view: one past each opening's dimension,
which locks or unlocks that opening, and one in place of a held board's
arrow, which unlocks the openings holding it."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import cast

import FreeCAD
import FreeCADGui
import pytest
from PySide6 import QtCore, QtTest, QtWidgets

from freecad.Shelving.core.edit import is_locked
from freecad.Shelving.core.geometry import Space
from freecad.Shelving.core.layout import Board, Division, Region
from freecad.Shelving.editor.elevation import LIFT_MM, DimensionLabel
from freecad.Shelving.editor.overlay import length_text
from freecad.Shelving.editor.panel import EditUnitPanel
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
)
from tests.freecad_view.view import ViewDriver

_VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"
# The font size dimension_style sets, in logical pixels.
_FONT_PX = 21
_PLACE_TOL_PX = 2.0
_TOL_MM = 1e-6
_LOCK = "Lock this opening"
_UNLOCK = "Unlock this opening"
_UNLOCK_BOARD = "Unlock the openings holding this board"


def _rgb(name: str) -> tuple[float, float, float]:
    packed = FreeCAD.ParamGet(_VIEW_PARAMS).GetUnsigned(name, 0)
    return (
        ((packed >> 24) & 0xFF) / 255,
        ((packed >> 16) & 0xFF) / 255,
        ((packed >> 8) & 0xFF) / 255,
    )


def _close_rgb(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(x - y) < 2.5 / 255 for x, y in zip(a, b, strict=True))


def _label_of(editor: ViewEditor, region_id: str) -> DimensionLabel:
    (label,) = [x for x in editor.overlay.labels if x.region_id == region_id]
    return label


def _padlock(editor: ViewEditor, region_id: str) -> QtWidgets.QToolButton:
    button = editor.padlock_for(region_id)
    assert button is not None, region_id
    return button


def _geometry(editor: ViewEditor, button: QtWidgets.QWidget) -> QtCore.QRectF:
    """``button``'s rectangle in the viewport's logical pixels."""
    parent = button.parentWidget()
    assert parent is not None
    top_left = editor.viewport.mapFrom(parent, button.geometry().topLeft())
    return QtCore.QRectF(QtCore.QPointF(top_left), QtCore.QSizeF(button.size()))


def _anchor(
    driver: ViewDriver, editor: ViewEditor, at_mm: tuple[float, float]
) -> QtCore.QPointF:
    return driver.qt_point(editor.to_document(*at_mm))


def _misplaced(
    driver: ViewDriver, editor: ViewEditor, label: DimensionLabel
) -> str | None:
    """Why ``label``'s padlock is not where it belongs, just past its text
    along its line and clear of its anchor, or ``None`` when it is."""
    button = editor.padlock_for(label.region_id)
    if button is None or not button.isVisible():
        return f"{label.region_id}: no padlock shown"
    rect = _geometry(editor, button)
    anchor = _anchor(driver, editor, label.text_at_mm)
    reach_px = (
        len(length_text(label.size_mm)) * 0.6 * _FONT_PX / 2 + 4 + button.width() / 2
    )
    expected = anchor + (
        QtCore.QPointF(reach_px, 0.0)
        if label.horizontal
        else QtCore.QPointF(0.0, -reach_px)
    )
    if (rect.center() - expected).manhattanLength() > _PLACE_TOL_PX:
        return f"{label.region_id}: at {rect.center()}, expected {expected}"
    if rect.contains(anchor):
        return f"{label.region_id}: covers its anchor {anchor}"
    return None


def _icon_pixel_alpha(button: QtWidgets.QToolButton, x_px: float, y_px: float) -> int:
    pixmap = button.icon().pixmap(QtCore.QSize(14, 14), button.devicePixelRatioF())
    ratio = pixmap.devicePixelRatio()
    return pixmap.toImage().pixelColor(round(x_px * ratio), round(y_px * ratio)).alpha()


def _icon_rgb(button: QtWidgets.QToolButton) -> tuple[float, float, float]:
    """The color of the padlock's body."""
    pixmap = button.icon().pixmap(QtCore.QSize(14, 14), button.devicePixelRatioF())
    ratio = pixmap.devicePixelRatio()
    color = pixmap.toImage().pixelColor(round(7 * ratio), round(10 * ratio))
    return (color.redF(), color.greenF(), color.blueF())


def _assert_shows(button: QtWidgets.QToolButton, locked: bool) -> None:
    """``button`` is an opening's padlock whose tooltip and drawing, as
    :func:`_assert_drawn` checks it, match ``locked``."""
    text = _UNLOCK if locked else _LOCK
    assert button.toolTip() == text
    assert button.accessibleName() == text
    _assert_drawn(button, locked)


def _assert_drawn(button: QtWidgets.QToolButton, locked: bool) -> None:
    """``button`` shows a closed padlock in the locked dimension color, or
    an open one in the unlocked color."""
    assert button.isVisible()
    name = "ConstrainedDimColor" if locked else "NonDrivingConstrDimColor"
    assert _close_rgb(_icon_rgb(button), _rgb(name)), _icon_rgb(button)
    # The shackle closes over the body's left side; open, it swings clear.
    left_leg_alpha = _icon_pixel_alpha(button, 4.1, 4.5)
    assert (left_leg_alpha > 100) == locked, left_leg_alpha


def _click(button: QtWidgets.QToolButton, driver: ViewDriver) -> None:
    QtTest.QTest.mouseClick(button, QtCore.Qt.MouseButton.LeftButton)
    driver.pump()


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


def _three_bays(panel: EditUnitPanel, driver: ViewDriver) -> tuple[str, str]:
    """Split the lowest bay twice; returns the two shelves, lowest first."""
    added = [add_board(panel, "vertical", driver) for _ in range(2)]
    spaces = panel.session.spaces
    low, high = sorted(added, key=lambda shelf: spaces[shelf].origin.z_mm)
    return low, high


def test_each_lockable_dimension_shows_its_padlock_past_its_text(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    lower = bay_ids(session.unit.root)[0]
    assert session.set_lock(lower, locked=True) is None
    panel._refresh()
    driver.pump()
    lone = [x for x in editor.overlay.labels if not x.lockable]
    # The fresh unit's single column of bays sits alone in its row.
    assert lone and all(x.color == "unlocked" for x in lone)
    for label in editor.overlay.labels:
        if not label.lockable:
            assert editor.padlock_for(label.region_id) is None
            continue
        _assert_shows(_padlock(editor, label.region_id), label.color == "locked")
        assert _misplaced(driver, editor, label) is None
    shown = [b for b in editor.padlocks if b.isVisible()]
    assert len(shown) == len(editor.overlay.labels) - len(lone)
    # The padlocks follow their labels when the camera pans and zooms.
    camera = editor.view.getCameraNode()
    x_mm, y_mm, z_mm = camera.position.getValue().getValue()
    camera.position.setValue(x_mm + 40.0, y_mm, z_mm + 30.0)
    camera.height.setValue(float(camera.height.getValue()) * 0.8)
    driver.pump()
    for label in editor.overlay.labels:
        if label.lockable:
            assert _misplaced(driver, editor, label) is None
    click_task_button("Close", driver)


def test_padlocks_follow_their_labels_when_the_view_resizes(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
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
        lockable = [x for x in editor.overlay.labels if x.lockable]
        assert lockable
        problems = [_misplaced(driver, editor, label) for label in lockable]
    finally:
        window.resize(size)
        driver.pump()
    assert problems == [None] * len(lockable)
    click_task_button("Close", driver)


def test_icons_redraw_for_a_screen_of_another_pixel_ratio(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    shown = [b for b in editor.padlocks if b.isVisible()]
    assert shown
    viewer = editor._viewer
    ratio = 2 * viewer.devicePixelRatioF()
    monkeypatch.setattr(viewer, "devicePixelRatioF", lambda: ratio)
    QtCore.QCoreApplication.sendEvent(
        editor.viewport, QtCore.QEvent(QtCore.QEvent.Type.DevicePixelRatioChange)
    )
    driver.pump()
    icons = [
        *((button, 14) for button in (*shown, editor.board_padlock)),
        *((button, 24) for button in editor.add_bar.buttons.values()),
    ]
    for button, side_px in icons:
        device_px = round(side_px * ratio)
        assert QtCore.QSize(device_px, device_px) in button.icon().availableSizes()
    monkeypatch.undo()
    click_task_button("Close", driver)


@dataclass
class _DragWatch:
    """What every placement of the in-view widgets during a drag left."""

    driver: ViewDriver
    editor: ViewEditor
    most_labels: int = 0
    most_padlocks: int = 0
    steps: int = 0
    problems: list[str] = field(default_factory=list)
    # Every padlock button seen, held so no id is reused for a new one.
    seen: dict[int, QtWidgets.QToolButton] = field(default_factory=dict)

    def wrap(self, place: Callable[[], None]) -> Callable[[], None]:
        def placed() -> None:
            place()
            editor = self.editor
            self.steps += 1
            self.most_labels = max(self.most_labels, len(editor.overlay.labels))
            self.most_padlocks = max(self.most_padlocks, len(editor.padlocks))
            for button in editor.padlocks:
                self.seen.setdefault(id(button), button)
            for label in editor.overlay.labels:
                if label.lockable:
                    problem = _misplaced(self.driver, editor, label)
                    if problem is not None:
                        self.problems.append(problem)

        return placed


def test_padlocks_follow_a_drag_from_a_pool_that_never_outgrows_the_labels(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    shelf = add_board(panel, "vertical", driver)
    session = panel.session
    watch = _DragWatch(driver, editor)
    monkeypatch.setattr(editor, "_place_widgets", watch.wrap(editor._place_widgets))
    arrow = editor.arrow
    assert arrow is not None and arrow.board_id == shelf
    z_before_mm = session.spaces[shelf].origin.z_mm
    start = driver.qt_point(editor.to_document(*arrow.at_mm, editor.frame.z_sign * 2.0))
    driver.drag(start, start - QtCore.QPointF(0.0, 60.0), steps=16)
    driver.pump()
    assert session.spaces[shelf].origin.z_mm > z_before_mm + 5.0
    assert watch.steps >= 16
    assert watch.problems == []
    assert 0 < watch.most_padlocks <= watch.most_labels
    # Distinct buttons over the whole drag, so a pool rebuilt with fresh
    # buttons at each step fails even when the list keeps its length.
    assert len(watch.seen) <= watch.most_labels
    parent = editor.padlocks[0].parentWidget()
    assert parent is not None
    made = [
        button
        for button in parent.findChildren(QtWidgets.QToolButton)
        if button.toolTip() in (_LOCK, _UNLOCK)
    ]
    assert len(made) == len(editor.padlocks)
    click_task_button("Close", driver)


def test_a_padlock_locks_and_unlocks_its_opening_moving_nothing(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    dimension_style: None,
    reported: list[str],
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    doc = unit.Document
    lower, upper = bay_ids(session.unit.root)
    spaces = dict(session.spaces)
    names = list(doc.UndoNames)
    _click(_padlock(editor, lower), driver)
    assert _locked(session.unit.root, lower)
    assert list(doc.UndoNames) == ["Lock Opening", *names]
    assert _same_spaces(session.spaces, spaces)
    _assert_shows(_padlock(editor, lower), locked=True)
    assert _label_of(editor, lower).color == "locked"

    # The column's last unlocked bay refuses to lock, in the Notification
    # Area, changing nothing.
    count = notification_count()
    _click(_padlock(editor, upper), driver)
    assert len(reported) == 1, reported
    assert "stays unlocked" in reported[0]
    assert notification_count() == count + 1
    assert not _locked(session.unit.root, upper)
    assert list(doc.UndoNames) == ["Lock Opening", *names]
    assert _same_spaces(session.spaces, spaces)
    _assert_shows(_padlock(editor, upper), locked=False)

    _click(_padlock(editor, lower), driver)
    assert not _locked(session.unit.root, lower)
    assert list(doc.UndoNames) == ["Unlock Opening", "Lock Opening", *names]
    assert _same_spaces(session.spaces, spaces)
    _assert_shows(_padlock(editor, lower), locked=False)

    gui_step("Std_Undo", driver)
    # Undo rescans the unit, which names its regions afresh.
    lower = bay_ids(session.unit.root)[0]
    assert _locked(session.unit.root, lower)
    _assert_shows(_padlock(editor, lower), locked=True)
    click_task_button("Close", driver)


def test_typing_a_size_closes_the_padlock(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    add_board(panel, "vertical", driver)
    session = panel.session
    upper = bay_ids(session.unit.root)[1]
    _assert_shows(_padlock(editor, upper), locked=False)
    editor.open_field(_label_of(editor, upper))
    field_ = editor.field
    assert field_ is not None
    field_.line_edit.selectAll()
    QtTest.QTest.keyClicks(field_.line_edit, "250")
    QtTest.QTest.keyClick(field_.line_edit, QtCore.Qt.Key.Key_Return)
    driver.pump()
    assert _locked(session.unit.root, upper)
    _assert_shows(_padlock(editor, upper), locked=True)
    click_task_button("Close", driver)


def test_a_held_board_shows_a_padlock_that_unlocks_the_openings_holding_it(
    unit: FreeCAD.DocumentObject, driver: ViewDriver, dimension_style: None
) -> None:
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    lower_shelf, _upper_shelf = _three_bays(panel, driver)
    session = panel.session
    doc = unit.Document
    bottom, middle, _top = bay_ids(session.unit.root)
    _click(_padlock(editor, bottom), driver)
    _click(_padlock(editor, middle), driver)
    editor.select(lower_shelf)
    driver.pump()
    assert editor.arrow is None
    held = editor.held
    assert held is not None and held.holders == (bottom,)
    padlock = editor.board_padlock
    assert padlock.isVisible()
    assert padlock.toolTip() == _UNLOCK_BOARD
    assert padlock.accessibleName() == _UNLOCK_BOARD
    _assert_drawn(padlock, locked=True)
    rect = _geometry(editor, padlock)
    assert (
        rect.center() - _anchor(driver, editor, held.at_mm)
    ).manhattanLength() <= _PLACE_TOL_PX
    # The holder's outline in the locked dimension color, and no other.
    locked_rgb = _rgb("ConstrainedDimColor")
    holding = [
        outline
        for outline in overlay_nodes.outlines(editor.root)
        if _close_rgb(outline.rgb, locked_rgb)
    ]
    assert len(holding) == 1
    bottom_rect = editor.frame.rect(session.spaces[bottom])
    corners = {
        _rounded(editor.to_document(h_mm, v_mm, 0.0))
        for h_mm in (bottom_rect.h0_mm, bottom_rect.h1_mm)
        for v_mm in (bottom_rect.v0_mm, bottom_rect.v1_mm)
    }
    lift_mm = editor.to_document(
        0, 0, editor.frame.z_sign * LIFT_MM
    ) - editor.to_document(0, 0, 0)
    drawn = {_rounded(point - lift_mm) for point in holding[0].points}
    assert drawn == corners

    spaces = dict(session.spaces)
    names = list(doc.UndoNames)
    _click(padlock, driver)
    assert list(doc.UndoNames) == ["Unlock Board", *names]
    assert not _locked(session.unit.root, bottom)
    assert _locked(session.unit.root, middle)
    assert _same_spaces(session.spaces, spaces)
    assert session.selected_id == lower_shelf
    assert editor.arrow is not None and editor.arrow.board_id == lower_shelf
    assert not padlock.isVisible()
    assert not any(
        _close_rgb(outline.rgb, locked_rgb)
        for outline in overlay_nodes.outlines(editor.root)
    )
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
        assert not editor.board_padlock.isVisible()
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
    _click(_padlock(editor, middle), driver)
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
