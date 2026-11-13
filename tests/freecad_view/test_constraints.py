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
    IconNode,
    label_string,
    load_sketcher_resources,
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


def _painted_rgbs(image: QtGui.QImage) -> list[tuple[int, int, int]]:
    """The color of every pixel of ``image`` at least half covered: at the
    Sketcher's default 12 px icon side, antialiasing leaves few pixels fully
    covered."""
    colors: list[tuple[int, int, int]] = []
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() >= 128:
                colors.append((color.red(), color.green(), color.blue()))
    return colors


def _all_near(
    colors: list[tuple[int, int, int]], expected: tuple[int, int, int]
) -> bool:
    return bool(colors) and all(
        all(abs(got - want) <= 3 for got, want in zip(color, expected, strict=True))
        for color in colors
    )


def _packed_rgb(packed: int) -> tuple[int, int, int]:
    return ((packed >> 24) & 0xFF, (packed >> 16) & 0xFF, (packed >> 8) & 0xFF)


def test_the_sketcher_icons_load_once_its_gui_module_is_imported() -> None:
    """What the editor relies on: on FreeCAD 1.1 the Sketcher's constraint
    icons are a resource only after ``SketcherGui`` is imported."""
    load_sketcher_resources()
    assert QtCore.QFile.exists(ICON_SOURCES["equal"])
    assert os.path.isfile(ICON_SOURCES["even_spacing"])


def test_icon_sources_are_the_sketchers_equal_and_the_workbenchs_even_spacing() -> None:
    assert ICON_SOURCES["equal"] == ":/icons/constraints/Constraint_EqualLength.svg"
    resources = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "freecad",
        "Shelving",
        "resources",
    )
    assert os.path.dirname(ICON_SOURCES["even_spacing"]) == os.path.normpath(resources)


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


def test_the_icons_are_drawn_from_their_svgs_in_the_sketchers_way(
    unit: FreeCAD.DocumentObject, driver: ViewDriver
) -> None:
    panel, (a, b, c) = _column_panel(unit, driver)
    _constrain(panel, "equal", [a, b])
    _constrain(panel, "even_spacing", [a, c])
    driver.pump()
    editor = editor_of(panel)
    side_px, _gap_px = editor._icon_metrics_px()
    for kind in ("equal", "even_spacing"):
        node = next(n for n in editor.icon_nodes if n.icon.kind == kind)
        drawn = _icon_part(node, side_px)
        expected = QtGui.QImage(side_px, side_px, QtGui.QImage.Format.Format_RGBA8888)
        expected.fill(QtCore.Qt.GlobalColor.transparent)
        painter = QtGui.QPainter(expected)
        QtSvg.QSvgRenderer(ICON_SOURCES[kind]).render(painter)
        painter.end()
        for y in range(side_px):
            for x in range(side_px):
                assert drawn.pixelColor(x, y).alpha() == pytest.approx(
                    expected.pixelColor(x, y).alpha(), abs=1
                ), (kind, x, y)
        painted = _painted_rgbs(drawn)
        assert _all_near(painted, painted[0])
    click_task_button("Close", driver)


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
        ("ConstrainedIcoColor", "DeactivatedConstrDimColor"), colors, strict=True
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
    active, deactivated, selected = (_packed_rgb(packed) for packed in icon_colors)
    side_px, _gap_px = editor._icon_metrics_px()
    by_constraint: dict[ConstraintId, list[tuple[int, int, int]]] = {}
    for node in editor.icon_nodes:
        by_constraint.setdefault(node.icon.constraint_id, []).extend(
            _painted_rgbs(_icon_part(node, side_px))
        )
    ids = [c.id for c in panel.session.constraints]
    assert _all_near(by_constraint[ids[0]], active)
    assert _all_near(by_constraint[ids[1]], deactivated)
    assert _all_near(by_constraint[ids[2]], selected)
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
