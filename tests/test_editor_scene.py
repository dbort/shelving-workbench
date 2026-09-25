"""Headless coverage for ``freecad.Shelving.editor.scene``.

Runs under plain ``pytest`` (the conda-forge ``pyside6`` build works outside
``freecadcmd`` too, verified directly), not ``freecadcmd``: ``scene.py``
imports no FreeCAD, so nothing here needs it either. ``QT_QPA_PLATFORM`` is
forced to ``offscreen`` before ``PySide6`` is imported, per this repo's
sh-020 Frontier Advice, and the module-scoped ``qapp`` fixture reuses an
existing ``QApplication`` rather than creating a second one, which aborts
the process.
"""

import os

# A plain assignment, not setdefault: a developer's shell may already export
# QT_QPA_PLATFORM (wayland, xcb) for interactive use elsewhere, and honoring
# that here would make this suite try to open a real window instead of
# running headless.
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from collections.abc import Iterator, Mapping  # noqa: E402
from typing import cast  # noqa: E402

import pytest  # noqa: E402
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

from freecad.Shelving.core.geometry import Space, Vec3  # noqa: E402
from freecad.Shelving.core.layout import (  # noqa: E402
    Axis,
    Bay,
    Board,
    Division,
    Unit,
    Void,
    Weighted,
)
from freecad.Shelving.core.materials import (  # noqa: E402
    Catalog,
    MaterialEntry,
    MaterialId,
)
from freecad.Shelving.core.solver import solve  # noqa: E402
from freecad.Shelving.editor.scene import (  # noqa: E402
    _ID_DATA_ROLE,
    build_scene,
    hit_test,
)

PLY = MaterialId("ply18")
CATALOG = Catalog(
    entries={
        PLY: MaterialEntry(
            id=PLY, name="18mm plywood", thickness_mm=18.0, material_type="plywood"
        )
    }
)

# One horizontal run: a weighted Bay, an 18mm divider board, and a Fill Void,
# each given an explicit id so a test can address it directly rather than
# searching the tree for it.
_UNIT = Unit(
    size_mm=Vec3(900.0, 300.0, 600.0),
    default_material=PLY,
    root=Division(
        axis=Axis.X,
        items=[
            Bay(id="bay1", rule=Weighted(1.0)),
            Board(id="board1", role="divider"),
            Void(id="void1"),
        ],
    ),
    depth_axis=Axis.Y,
)
_SPACES = solve(_UNIT, CATALOG)

# The same run, rotated a quarter turn: depth is X, not Y, so the elevation's
# horizontal axis is Y and its vertical axis is Z (unchanged, since Z is
# never the depth axis here). Exercises _rect_for's projection along an axis
# pair other than the X/Z default every other fixture in this module uses.
_ROTATED_UNIT = Unit(
    size_mm=Vec3(300.0, 900.0, 600.0),
    default_material=PLY,
    root=Division(
        axis=Axis.Y,
        items=[
            Bay(id="rbay1", rule=Weighted(1.0)),
            Board(id="rboard1", role="divider"),
            Void(id="rvoid1"),
        ],
    ),
    depth_axis=Axis.X,
)
_ROTATED_SPACES = solve(_ROTATED_UNIT, CATALOG)

# Scene (mm) coordinates known to land inside each named item, and one known
# to land outside the unit entirely; derived from _SPACES above (bay1 spans
# x in [0, 441], board1 [441, 459], void1 [459, 900], every item spanning
# the full 600mm vertical extent).
_POINT_IN_BAY = QtCore.QPointF(220.0, 300.0)
_POINT_IN_BOARD = QtCore.QPointF(450.0, 300.0)
_POINT_IN_VOID = QtCore.QPointF(680.0, 300.0)
_POINT_OUTSIDE = QtCore.QPointF(-10.0, -10.0)


@pytest.fixture(scope="module")
def qapp() -> Iterator[QtWidgets.QApplication]:
    # QApplication.instance() is typed as the QCoreApplication base class
    # (PySide6-stubs does not narrow a classmethod's return by the class it
    # was called on); this process never constructs any QCoreApplication
    # that is not a QApplication, so the cast is safe.
    existing = cast("QtWidgets.QApplication | None", QtWidgets.QApplication.instance())
    yield existing or QtWidgets.QApplication([])


class _RecordingView(QtWidgets.QGraphicsView):
    """A ``QGraphicsView`` that remembers the scene position of its last
    mouse press, so a test can confirm a simulated click actually reached
    the view rather than only that ``hit_test`` works in isolation."""

    def __init__(self, scene: QtWidgets.QGraphicsScene) -> None:
        super().__init__(scene)
        self.last_scene_pos: QtCore.QPointF | None = None

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        self.last_scene_pos = self.mapToScene(event.position().toPoint())
        super().mousePressEvent(event)


def _union_of_item_rects(scene: QtWidgets.QGraphicsScene) -> QtCore.QRectF:
    """The union of every item's own ``rect()``, the geometry ``build_scene``
    actually placed each item at. Every item here has no transform beyond
    its position in ``addRect``'s own coordinates, so this is the drawn
    extent; unlike ``itemsBoundingRect()``, it is not inflated by the
    boundary items' pen width."""
    union = QtCore.QRectF()
    for item in scene.items():
        assert isinstance(item, QtWidgets.QGraphicsRectItem)
        union = union.united(item.rect())
    return union


def test_item_count_matches_regions_plus_boards(
    qapp: QtWidgets.QApplication,
) -> None:
    # Division (root) + Bay + Void = 3 regions, plus 1 board.
    scene = build_scene(_UNIT, _SPACES)
    assert len(scene.items()) == 4


@pytest.mark.parametrize(
    ("unit", "spaces"), [(_UNIT, _SPACES), (_ROTATED_UNIT, _ROTATED_SPACES)]
)
def test_scene_items_fill_the_unit_projected_extent(
    qapp: QtWidgets.QApplication, unit: Unit, spaces: Mapping[str, Space]
) -> None:
    # The union of the drawn items' own rects, not sceneRect: sceneRect is
    # exactly what build_scene sets from unit.size_mm directly, so it would
    # pass even if _rect_for drew every item at the wrong place or size.
    # Both a default unit (depth_axis Y) and a rotated one (depth_axis X) so
    # a projection bug that only shows up off the X/Z axis pair would fail
    # here.
    scene = build_scene(unit, spaces)
    rect = _union_of_item_rects(scene)
    assert rect.width() == pytest.approx(900.0)
    assert rect.height() == pytest.approx(600.0)


def test_hit_test_finds_the_bay_the_board_and_the_void(
    qapp: QtWidgets.QApplication,
) -> None:
    scene = build_scene(_UNIT, _SPACES)
    assert hit_test(scene, _POINT_IN_BAY) == "bay1"
    assert hit_test(scene, _POINT_IN_BOARD) == "board1"
    assert hit_test(scene, _POINT_IN_VOID) == "void1"


def test_hit_test_outside_the_unit_returns_none(
    qapp: QtWidgets.QApplication,
) -> None:
    scene = build_scene(_UNIT, _SPACES)
    assert hit_test(scene, _POINT_OUTSIDE) is None


def test_void_brush_differs_from_bay_brush(qapp: QtWidgets.QApplication) -> None:
    scene = build_scene(_UNIT, _SPACES)
    items_by_id = {item.data(_ID_DATA_ROLE): item for item in scene.items()}
    bay_item = items_by_id["bay1"]
    void_item = items_by_id["void1"]
    assert isinstance(bay_item, QtWidgets.QGraphicsRectItem)
    assert isinstance(void_item, QtWidgets.QGraphicsRectItem)
    assert bay_item.brush() != void_item.brush()


def test_selected_item_pen_differs_from_unselected(
    qapp: QtWidgets.QApplication,
) -> None:
    scene = build_scene(_UNIT, _SPACES, selected_id="bay1")
    items_by_id = {item.data(_ID_DATA_ROLE): item for item in scene.items()}
    bay_item = items_by_id["bay1"]
    void_item = items_by_id["void1"]
    assert isinstance(bay_item, QtWidgets.QGraphicsRectItem)
    assert isinstance(void_item, QtWidgets.QGraphicsRectItem)
    assert bay_item.pen() != void_item.pen()


def test_simulated_click_reaches_the_scene(qapp: QtWidgets.QApplication) -> None:
    scene = build_scene(_UNIT, _SPACES)
    view = _RecordingView(scene)
    try:
        view.setFixedSize(950, 650)
        view.show()
        qapp.processEvents()
        viewport_point = view.mapFromScene(_POINT_IN_BAY)
        QtTest.QTest.mouseClick(
            view.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=viewport_point
        )
        assert view.last_scene_pos is not None
        assert hit_test(scene, view.last_scene_pos) == "bay1"
    finally:
        view.close()
