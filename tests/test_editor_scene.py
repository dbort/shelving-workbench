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

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from typing import cast  # noqa: E402

import pytest  # noqa: E402
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

from freecad.Shelving.core.geometry import Vec3  # noqa: E402
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


def test_item_count_matches_regions_plus_boards(
    qapp: QtWidgets.QApplication,
) -> None:
    # Division (root) + Bay + Void = 3 regions, plus 1 board.
    scene = build_scene(_UNIT, _SPACES)
    assert len(scene.items()) == 4


def test_scene_rect_matches_the_unit_projected_extent(
    qapp: QtWidgets.QApplication,
) -> None:
    scene = build_scene(_UNIT, _SPACES)
    rect = scene.sceneRect()
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
