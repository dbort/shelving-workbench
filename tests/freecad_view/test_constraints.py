"""Equal and even spacing in Edit Unit's 3D view: the icons the Sketcher's
style draws beside each opening's dimension, selecting constraints by their
icons, Ctrl-click on openings, Delete, and a board an even spacing holds."""

import dataclasses
import os
from collections.abc import Iterator
from typing import cast

import FreeCAD
import pytest
from PySide6 import QtCore, QtGui, QtSvg, QtWidgets

from freecad.Shelving.container import write_container
from freecad.Shelving.core.layout import ConstraintId
from freecad.Shelving.editor import overlay
from freecad.Shelving.editor.elevation import ConstraintIcon, DimensionLabel
from freecad.Shelving.editor.overlay import (
    ICON_SOURCES,
    RGB,
    IconNode,
    ViewParams,
    background_rgb,
    label_string,
)
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.view_editor import ViewEditor, label_metrics
from tests.freecad_view import overlay_nodes
from tests.freecad_view.editor import (
    bay_ids,
    board_targets,
    clear_of_labels,
    click_task_button,
    edit_unit,
    editor_of,
    press_delete,
    zoom_on,
)
from tests.freecad_view.view import ViewDriver

_CTRL = QtCore.Qt.KeyboardModifier.ControlModifier
_VIEW_PARAMS = "User parameter:BaseApp/Preferences/View"


def _column_panel(
    container: FreeCAD.DocumentObject, driver: ViewDriver
) -> tuple[EditUnitPanel, list[str]]:
    """Edit Unit on ``container`` with its bay split into a column of three
    by two shelves, and the three bays bottom to top."""
    panel = edit_unit(container, driver)
    session = panel.session
    session.select(bay_ids(session.unit.root)[0])
    assert session.split("vertical") is None
    session.select(bay_ids(session.unit.root)[1])
    assert session.split("vertical") is None
    session.select(None)
    panel._refresh()
    driver.pump()
    return panel, bay_ids(session.unit.root)


def _constrain(panel: EditUnitPanel, kind: str, items: list[str]) -> None:
    panel.session.select_items(items)
    panel.constrain("equal" if kind == "equal" else "even_spacing")


def _icons(editor: ViewEditor) -> list[ConstraintIcon]:
    return [node.icon for node in editor.icon_nodes]


def _icon_rect(editor: ViewEditor, icon: ConstraintIcon) -> QtCore.QRectF:
    side_px, _gap_px = editor._icon_metrics_px()
    side_px /= editor.viewport.devicePixelRatioF()
    center = editor.icon_center(icon)
    return QtCore.QRectF(
        center - QtCore.QPointF(side_px / 2, side_px / 2),
        QtCore.QSizeF(side_px, side_px),
    )


def _text_rect(editor: ViewEditor, label: DimensionLabel) -> QtCore.QRectF:
    """The dimension's text, padlock room included, in logical pixels."""
    metrics = label_metrics(editor.style.label_size_pt)
    ratio = editor.viewport.devicePixelRatioF()
    width_px = metrics.horizontalAdvance(label_string(label, editor.style)) / ratio
    height_px = metrics.height() / ratio
    center = editor._logical_point(editor.to_document(*label.text_at_mm))
    if not label.horizontal:
        width_px, height_px = height_px, width_px
    return QtCore.QRectF(
        center - QtCore.QPointF(width_px / 2, height_px / 2),
        QtCore.QSizeF(width_px, height_px),
    )


def _padlock_rect(editor: ViewEditor, button: QtWidgets.QWidget) -> QtCore.QRectF:
    parent = button.parentWidget()
    assert parent is not None
    top_left = editor.viewport.mapFrom(parent, button.geometry().topLeft())
    return QtCore.QRectF(QtCore.QPointF(top_left), QtCore.QSizeF(button.size()))


def _icon_part(node: IconNode, side_px: int) -> QtGui.QImage:
    """The icon at the far end of ``node``'s padded image."""
    image = node.drawn
    if node.icon.label.horizontal:
        return image.copy(image.width() - side_px, 0, side_px, side_px)
    return image.copy(0, 0, side_px, side_px)


def _glyph_mismatches(
    editor: ViewEditor, node: IconNode, rgb: tuple[int, int, int]
) -> list[tuple[int, int]]:
    """The pixels of ``node``'s glyph that differ from its SVG drawn in
    ``rgb`` over the editor's tile, each pixel blended by the SVG's own
    coverage there, as the Sketcher's source-in recolor leaves it."""
    side_px, _gap_px = editor._icon_metrics_px()
    tile = editor.icon_tile()
    glyph_px = side_px - 2 * tile.pad_px
    coverage = QtGui.QImage(glyph_px, glyph_px, QtGui.QImage.Format.Format_RGBA8888)
    coverage.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(coverage)
    QtSvg.QSvgRenderer(ICON_SOURCES[node.icon.kind]).render(painter)
    painter.end()
    drawn = _icon_part(node, side_px)
    tile_rgb = _rgb_255(tile.rgb)
    mismatches: list[tuple[int, int]] = []
    for y in range(glyph_px):
        for x in range(glyph_px):
            weight = coverage.pixelColor(x, y).alpha() / 255
            got = drawn.pixelColor(x + tile.pad_px, y + tile.pad_px)
            want = [b + weight * (g - b) for g, b in zip(rgb, tile_rgb, strict=True)]
            channels = (got.red(), got.green(), got.blue())
            if got.alpha() != 255 or any(
                abs(c - w) > 3 for c, w in zip(channels, want, strict=True)
            ):
                mismatches.append((x, y))
    return mismatches


def _rgb_255(rgb: RGB) -> tuple[int, int, int]:
    red, green, blue = (round(255 * channel) for channel in rgb)
    return (red, green, blue)


def _near(color: QtGui.QColor, rgb: tuple[int, int, int]) -> bool:
    channels = (color.red(), color.green(), color.blue())
    return all(abs(c - w) <= 3 for c, w in zip(channels, rgb, strict=True))


def _packed_rgb(packed: int) -> tuple[int, int, int]:
    return ((packed >> 24) & 0xFF, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF)


def test_both_icons_are_the_workbenchs_own_svgs() -> None:
    resources = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "freecad",
        "Shelving",
        "resources",
    )
    for kind in ("equal", "even_spacing"):
        source = ICON_SOURCES[kind]
        assert os.path.dirname(source) == os.path.normpath(resources), kind
        assert QtSvg.QSvgRenderer(source).isValid(), kind


def _open_point(editor: ViewEditor, region_id: str) -> FreeCAD.Vector:
    """A point in the opening ``region_id`` clear of every dimension."""
    rect = editor.frame.rect(editor.session.spaces[region_id])
    for h_fraction in (0.25, 0.5, 0.75):
        for v_fraction in (0.75, 0.5, 0.25):
            point = editor.to_document(
                rect.h0_mm + h_fraction * (rect.h1_mm - rect.h0_mm),
                rect.v0_mm + v_fraction * (rect.v1_mm - rect.v0_mm),
            )
            if clear_of_labels(editor, point):
                return point
    raise AssertionError(f"no point in {region_id} clear of the dimensions")


def test_ctrl_click_adds_openings_in_order(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    editor = editor_of(panel)
    driver.click(_open_point(editor, a))
    assert panel.session.selected_items == (a,)
    for region in (c, b):
        driver.click(_open_point(editor, region), _CTRL)
    assert panel.session.selected_items == (a, c, b)
    driver.click(_open_point(editor, c), _CTRL)
    assert panel.session.selected_items == (a, b)
    assert not panel.basis_combo.isEnabled()
    click_task_button("Close", driver)


def test_icons_sit_at_each_constrained_opening_clear_of_text_padlocks_and_each_other(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, c])
    _constrain(panel, "even_spacing", [a, c])
    driver.pump()
    editor = editor_of(panel)
    icons = _icons(editor)
    equal, spacing = panel.session.constraints
    assert sorted(i.label.region_id for i in icons if i.constraint_id == equal.id) == (
        sorted([a, c])
    )
    assert sorted(
        i.label.region_id for i in icons if i.constraint_id == spacing.id
    ) == sorted([a, b, c])
    rects = [_icon_rect(editor, icon) for icon in icons]
    taken = [_text_rect(editor, label) for label in editor.overlay.labels]
    taken += [
        _padlock_rect(editor, button)
        for button in editor.padlocks
        if button.isVisible()
    ]
    for index, rect in enumerate(rects):
        for other in rects[index + 1 :] + taken:
            assert not rect.intersects(other), (rect, other)
    click_task_button("Close", driver)


def test_the_icons_are_drawn_from_their_svgs_in_the_sketchers_way_on_a_tile(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, b])
    _constrain(panel, "even_spacing", [a, c])
    driver.pump()
    editor = editor_of(panel)
    side_px, _gap_px = editor._icon_metrics_px()
    tile_rgb = _rgb_255(editor.style.tile_rgb)
    icon_rgb = _rgb_255(editor.style.icon_rgb)
    for kind in ("equal", "even_spacing"):
        node = next(n for n in editor.icon_nodes if n.icon.kind == kind)
        assert _glyph_mismatches(editor, node, icon_rgb) == [], kind
        drawn = _icon_part(node, side_px)
        edge = drawn.pixelColor(side_px // 2, 0)
        assert edge.alpha() == 255 and _near(edge, tile_rgb), kind
        assert drawn.pixelColor(0, 0).alpha() < 255, kind
    click_task_button("Close", driver)


def test_icons_and_padlocks_sit_on_tiles_of_the_view_background(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def background(_params: ViewParams) -> RGB:
        return (0.2, 0.4, 0.3)

    # The editor's own reading, so FreeCAD's view keeps its background.
    monkeypatch.setattr(overlay, "background_rgb", background)
    panel, (a, b, _c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, b])
    driver.pump()
    editor = editor_of(panel)
    tile_rgb = _rgb_255((0.2, 0.4, 0.3))
    side_px, _gap_px = editor._icon_metrics_px()
    for node in editor.icon_nodes:
        assert _near(_icon_part(node, side_px).pixelColor(side_px // 2, 0), tile_rgb)
    buttons = [button for button in editor.padlocks if button.isVisible()]
    assert buttons
    for button in buttons:
        face = button.grab().toImage()
        assert _near(face.pixelColor(face.width() // 2, 1), tile_rgb)
    click_task_button("Close", driver)


class _Params:
    def __init__(self, bools: dict[str, bool], colors: dict[str, int]) -> None:
        self.bools = bools
        self.colors = colors

    def GetBool(self, name: str, default: bool, /) -> bool:
        return self.bools.get(name, default)

    def GetUnsigned(self, name: str, default: int, /) -> int:
        return self.colors.get(name, default)


_ENDS = {"BackgroundColor": 0x102030FF, "BackgroundColor2": 0x204060FF}


@pytest.mark.parametrize(
    ("bools", "colors", "expected"),
    [
        ({}, {}, (247, 247, 247)),
        ({"Simple": True}, _ENDS, (16, 32, 48)),
        (
            {"Simple": False, "Gradient": True},
            {**_ENDS, "BackgroundColor3": 0x406080FF},
            (48, 80, 112),
        ),
        (
            {"Simple": False, "RadialGradient": True, "UseBackgroundColorMid": True},
            {**_ENDS, "BackgroundColor4": 0x0A0B0CFF},
            (10, 11, 12),
        ),
    ],
)
def test_the_background_is_the_plain_color_or_a_gradients_middle(
    bools: dict[str, bool], colors: dict[str, int], expected: tuple[int, int, int]
) -> None:
    assert _rgb_255(background_rgb(_Params(bools, colors))) == expected


def test_clicking_icons_selects_constraints_and_a_click_on_an_opening_drops_them(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, b])
    _constrain(panel, "even_spacing", [a, c])
    driver.pump()
    editor = editor_of(panel)
    session = panel.session
    equal, spacing = session.constraints
    equal_icon = next(i for i in _icons(editor) if i.constraint_id == equal.id)
    driver.click(editor.icon_center(equal_icon))
    assert session.selected_constraints == (equal.id,)
    assert session.selected_items == ()
    spacing_icon = next(i for i in _icons(editor) if i.constraint_id == spacing.id)
    driver.click(editor.icon_center(spacing_icon), _CTRL)
    assert session.selected_constraints == (equal.id, spacing.id)
    driver.click(editor.icon_center(spacing_icon))
    assert session.selected_constraints == (spacing.id,)
    driver.click(_open_point(editor, b))
    assert session.selected_constraints == ()
    assert session.selected_items == (b,)
    equal_icon = next(i for i in _icons(editor) if i.constraint_id == equal.id)
    driver.click(editor.icon_center(equal_icon))
    assert session.selected_constraints == (equal.id,)
    shelf = _shelf_above(panel, a)
    zoom_on(editor, shelf, 300.0, driver)
    driver.click(board_targets(editor, shelf)["Face"])
    assert session.selected_constraints == ()
    assert session.selected_items == (shelf,)
    click_task_button("Close", driver)


def _shelf_above(panel: EditUnitPanel, region_id: str) -> str:
    """The board whose low face is the opening ``region_id``'s top."""
    spaces = panel.session.spaces
    top_mm = spaces[region_id].max_corner().z_mm
    return next(
        board
        for board in editor_of(panel)._boards
        if spaces[board].origin.z_mm == pytest.approx(top_mm)
    )


def _outline_rgbs(
    editor: ViewEditor, region_id: str
) -> list[tuple[float, float, float]]:
    rect = editor.frame.rect(editor.session.spaces[region_id])
    corners = {
        (round(rect.h0_mm, 3), round(rect.v0_mm, 3)),
        (round(rect.h1_mm, 3), round(rect.v1_mm, 3)),
    }
    found: list[tuple[float, float, float]] = []
    inverse = editor._placement(editor.frame).inverse()
    for outline in overlay_nodes.outlines(editor.root):
        points = set()
        for point in outline.points:
            local = inverse.multVec(point)
            points.add((round(local.x, 3), round(local.y, 3)))
        if corners <= points:
            found.append(outline.rgb)
    return found


def _close_rgb(a: tuple[float, float, float], b: tuple[float, float, float]) -> bool:
    return all(abs(x - y) < 2.5 / 255 for x, y in zip(a, b, strict=True))


def test_a_selected_constraint_outlines_its_openings_in_the_selection_color(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, c])
    editor = editor_of(panel)
    (equal,) = panel.session.constraints
    icon = next(i for i in _icons(editor) if i.constraint_id == equal.id)
    driver.click(editor.icon_center(icon))
    selected = editor.style.selected_rgb
    for region in (a, c):
        assert any(_close_rgb(rgb, selected) for rgb in _outline_rgbs(editor, region))
    assert not any(_close_rgb(rgb, selected) for rgb in _outline_rgbs(editor, b))
    click_task_button("Close", driver)


def test_delete_removes_the_selected_constraints(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, b])
    _constrain(panel, "equal", [b, c])
    editor = editor_of(panel)
    first, second = panel.session.constraints
    for constraint, modifiers in ((first, None), (second, _CTRL)):
        icon = next(i for i in _icons(editor) if i.constraint_id == constraint.id)
        if modifiers is None:
            driver.click(editor.icon_center(icon))
        else:
            driver.click(editor.icon_center(icon), modifiers)
    boards = {name: _z(unit, name) for name in editor._boards}
    driver.viewport.setFocus()
    press_delete(driver)
    assert panel.session.constraints == ()
    assert editor.icon_nodes == []
    assert {name: _z(unit, name) for name in editor._boards} == boards
    click_task_button("Close", driver)


def _z(unit: FreeCAD.DocumentObject, name: str) -> float:
    obj = unit.Document.getObject(name)
    return float(cast("FreeCAD.Placement", obj.Placement).Base.z)


@pytest.fixture
def icon_colors(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, int, int]]:
    """Distinct active, deactivated and selection colors, packed. The two
    icon colors go into the View preferences. The selection color reaches
    only the editor's own reading of ``SelectionColor``: the 3D view keeps
    a changed preference after it is removed, and every later test's
    selection highlight would take it (bug-022)."""
    params = FreeCAD.ParamGet(_VIEW_PARAMS)
    colors = (0xC01020FF, 0x30A0B0FF, 0x7020D0FF)
    for name, packed in zip(
        ("ConstrainedIcoColor", "DeactivatedConstrDimColor"), colors[:2], strict=True
    ):
        params.SetUnsigned(name, packed)
    real_view_color = overlay._view_color

    def view_color(name: str, default: int) -> tuple[float, float, float]:
        if name == "SelectionColor":
            red, green, blue = _packed_rgb(colors[2])
            return (red / 255, green / 255, blue / 255)
        return real_view_color(name, default)

    monkeypatch.setattr(overlay, "_view_color", view_color)
    yield colors
    for name in ("ConstrainedIcoColor", "DeactivatedConstrDimColor"):
        params.RemUnsigned(name)


def test_active_deactivated_and_selected_icons_take_their_colors(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    icon_colors: tuple[int, int, int],
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, b])
    _constrain(panel, "equal", [b, c])
    _constrain(panel, "even_spacing", [a, c])
    session = panel.session
    first, second, third = session.constraints
    off = dataclasses.replace(
        session.unit,
        constraints=(first, dataclasses.replace(second, active=False), third),
    )
    click_task_button("Close", driver)
    write_container(unit, off)
    unit.Document.recompute()
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    selected_id = panel.session.constraints[2].id
    icon = next(i for i in _icons(editor) if i.constraint_id == selected_id)
    driver.click(editor.icon_center(icon))
    ids = [c.id for c in panel.session.constraints]
    expected: dict[ConstraintId, tuple[int, int, int]] = {
        constraint_id: _packed_rgb(packed)
        for constraint_id, packed in zip(ids, icon_colors, strict=True)
    }
    assert {node.icon.constraint_id for node in editor.icon_nodes} == set(ids)
    for node in editor.icon_nodes:
        rgb = expected[node.icon.constraint_id]
        assert _glyph_mismatches(editor, node, rgb) == [], node.icon
    click_task_button("Close", driver)


def test_a_shelf_an_even_spacing_holds_shows_no_arrow_and_outlines_the_group(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "even_spacing", [a, c])
    editor = editor_of(panel)
    panel.session.select(_shelf_above(panel, a))
    panel._refresh()
    driver.pump()
    assert editor.arrow is None
    assert editor.held is None
    holding = editor.style.locked_rgb
    for region in (a, b, c):
        assert any(_close_rgb(rgb, holding) for rgb in _outline_rgbs(editor, region))
    click_task_button("Close", driver)
