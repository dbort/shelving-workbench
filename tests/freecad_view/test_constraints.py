"""Equal and even spacing in Edit Unit's 3D view: the icons the Sketcher's
style draws beside each opening's dimension, selecting constraints by their
icons, Ctrl-click on openings, Delete, and a board an even spacing holds."""

import dataclasses
import os
from collections.abc import Iterator
from typing import cast

import FreeCAD
import pytest
from PySide6 import QtCore, QtGui, QtSvg

from freecad.Shelving.container import write_container
from freecad.Shelving.editor import overlay
from freecad.Shelving.editor.constraint_list import TEXT_COLUMN
from freecad.Shelving.editor.elevation import ICON_SOURCES, ConstraintIcon
from freecad.Shelving.editor.overlay import (
    RGB,
    IconNode,
    ViewParams,
    background_rgb,
)
from freecad.Shelving.editor.panel import EditUnitPanel
from freecad.Shelving.editor.session import ConstraintRow
from freecad.Shelving.editor.view_editor import ViewEditor
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


def test_icons_sit_at_each_constrained_opening_clear_of_text_and_each_other(
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
    rects = [_icon_rect(editor, icon) for icon in editor.overlay.icons]
    taken = [editor.text_tile_rect(label) for label in editor.overlay.labels]
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


def test_icons_sit_on_tiles_of_the_view_background(
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
    assert editor.icon_nodes
    for node in editor.icon_nodes:
        assert _near(_icon_part(node, side_px).pixelColor(side_px // 2, 0), tile_rgb)
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
        ({}, {}, (111, 111, 147)),
        ({"Gradient": False}, {}, (234, 229, 220)),
        ({"Simple": True, "Gradient": False}, _ENDS, (16, 32, 48)),
        ({"Simple": True}, {**_ENDS, "BackgroundColor3": 0x406080FF}, (48, 80, 112)),
        (
            {"Gradient": False, "RadialGradient": True, "UseBackgroundColorMid": True},
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
def icon_colors(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[int, int]]:
    """Distinct icon and selection colors, packed. The icon color goes into
    the View preferences. The selection color reaches only the editor's own
    reading of ``SelectionColor``: the 3D view keeps a changed preference
    after it is removed, and every later test's selection highlight would
    take it (bug-022)."""
    params = FreeCAD.ParamGet(_VIEW_PARAMS)
    colors = (0xC01020FF, 0x7020D0FF)
    params.SetUnsigned("ConstrainedIcoColor", colors[0])
    real_view_color = overlay._view_color

    def view_color(name: str, default: int) -> tuple[float, float, float]:
        if name == "SelectionColor":
            red, green, blue = _packed_rgb(colors[1])
            return (red / 255, green / 255, blue / 255)
        return real_view_color(name, default)

    monkeypatch.setattr(overlay, "_view_color", view_color)
    yield colors
    params.RemUnsigned("ConstrainedIcoColor")


def _blend_of(
    color: QtGui.QColor, rgb: tuple[int, int, int], tile_rgb: tuple[int, int, int]
) -> bool:
    """Whether ``color`` is opaque and ``rgb`` over ``tile_rgb`` at one
    coverage in every channel."""
    if color.alpha() != 255:
        return False
    channels = (color.red(), color.green(), color.blue())
    spans = [(c - t, g - t) for c, g, t in zip(channels, rgb, tile_rgb, strict=True)]
    weights = [got / span for got, span in spans if abs(span) > 24]
    if not weights or not all(-0.02 <= w <= 1.02 for w in weights):
        return False
    weight = sum(weights) / len(weights)
    return all(abs(got - weight * span) <= 4 for got, span in spans)


def _assert_marked_as(
    editor: ViewEditor,
    node: IconNode,
    rgb: tuple[int, int, int],
    active: bool,
) -> None:
    """Assert that ``node`` is its SVG in ``rgb``, and that a deactivated
    one differs from it only in its glyph's top-right corner, there in
    ``rgb`` over the tile at some coverage."""
    mismatches = _glyph_mismatches(editor, node, rgb)
    if active:
        assert mismatches == [], node.icon
        return
    assert mismatches, node.icon
    side_px, _gap_px = editor._icon_metrics_px()
    tile = editor.icon_tile()
    glyph_px = side_px - 2 * tile.pad_px
    # Antialiasing spreads the mark's edge by up to a pixel.
    extent_px = overlay.corner_x_extent_px(glyph_px) + 1
    assert extent_px < 2 * glyph_px / 3, extent_px
    drawn = _icon_part(node, side_px)
    tile_rgb = _rgb_255(tile.rgb)
    for x, y in mismatches:
        assert x >= glyph_px - extent_px and y < extent_px, (node.icon, x, y)
        got = drawn.pixelColor(x + tile.pad_px, y + tile.pad_px)
        assert _blend_of(got, rgb, tile_rgb), (node.icon, x, y, got.name())
    # A gap cleared with no X painted on it would pass the checks above.
    assert any(
        _near(drawn.pixelColor(x + tile.pad_px, y + tile.pad_px), rgb)
        for x, y in mismatches
    ), node.icon


def test_icons_take_their_selections_color_and_deactivated_ones_a_corner_x(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    icon_colors: tuple[int, int],
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, b])
    _constrain(panel, "equal", [b, c])
    _constrain(panel, "even_spacing", [a, c])
    session = panel.session
    first, second, third = session.constraints
    off = dataclasses.replace(
        session.unit,
        constraints=(
            first,
            dataclasses.replace(second, active=False),
            dataclasses.replace(third, active=False),
        ),
    )
    click_task_button("Close", driver)
    write_container(unit, off)
    unit.Document.recompute()
    panel = edit_unit(unit, driver)
    editor = editor_of(panel)
    ids = [c.id for c in panel.session.constraints]
    # One of each: selected and active, selected and deactivated, neither.
    first_icon, second_icon = (
        next(i for i in _icons(editor) if i.constraint_id == constraint_id)
        for constraint_id in ids[:2]
    )
    driver.click(editor.icon_center(first_icon))
    driver.click(editor.icon_center(second_icon), _CTRL)
    assert panel.session.selected_constraints == (ids[0], ids[1])
    icon_rgb, selected_rgb = (_packed_rgb(packed) for packed in icon_colors)
    assert {node.icon.constraint_id for node in editor.icon_nodes} == set(ids)
    for node in editor.icon_nodes:
        selected = node.icon.constraint_id in ids[:2]
        active = node.icon.constraint_id == ids[0]
        assert (node.icon.selected, node.icon.active) == (selected, active)
        rgb = selected_rgb if selected else icon_rgb
        _assert_marked_as(editor, node, rgb, active)
    click_task_button("Close", driver)


def test_toggling_a_selected_rows_box_marks_its_icons_in_the_selection_color(
    unit: FreeCAD.DocumentObject,
    driver: ViewDriver,
    icon_colors: tuple[int, int],
) -> None:
    panel, (a, _b, c) = _column_panel(unit, driver)
    _constrain(panel, "even_spacing", [a, c])
    (spacing,) = panel.session.constraints
    editor = editor_of(panel)
    tree = panel.constraint_list.tree
    index = next(
        i
        for i, row in enumerate(panel.constraint_list.rows)
        if isinstance(row, ConstraintRow) and row.constraint_id == spacing.id
    )
    item = tree.topLevelItem(index)
    assert item is not None
    # Under Xvfb no mouse event reaches the hidden task panel (bug-011), so
    # the row is selected and its box toggled as a press on the box does.
    flag = QtCore.QItemSelectionModel.SelectionFlag
    tree.setCurrentItem(item, 0, flag.ClearAndSelect | flag.Rows)
    driver.pump()
    _icon_rgb, selected_rgb = (_packed_rgb(packed) for packed in icon_colors)
    for state, active in (
        (QtCore.Qt.CheckState.Unchecked, False),
        (QtCore.Qt.CheckState.Checked, True),
    ):
        item = tree.topLevelItem(index)
        assert item is not None
        item.setCheckState(TEXT_COLUMN, state)
        driver.pump()
        item = tree.topLevelItem(index)
        assert item is not None
        assert item.isSelected(), state
        assert panel.session.selected_constraints == (spacing.id,)
        nodes = [n for n in editor.icon_nodes if n.icon.constraint_id == spacing.id]
        assert nodes
        for node in nodes:
            assert (node.icon.selected, node.icon.active) == (True, active)
            _assert_marked_as(editor, node, selected_rgb, active)
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
    holding = editor.style.driving_rgb
    for region in (a, b, c):
        assert any(_close_rgb(rgb, holding) for rgb in _outline_rgbs(editor, region))
    click_task_button("Close", driver)
