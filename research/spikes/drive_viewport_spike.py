"""Drives the viewport spike under Xvfb and prints PASS/FAIL lines.

Temporary, like the spike itself. It is also the worked example for
``.claude/docs/xvfb-gui-testing.md``. Run from the repo root:

    xvfb-run -a -s "-screen 0 1600x1000x24" \\
        env QT_QPA_PLATFORM=xcb PYTHONUNBUFFERED=1 \\
        SPIKE_NAV=Gui::GestureNavigationStyle \\
        pixi run python research/spikes/drive_viewport_spike.py > drive.out 2>&1

``SPIKE_NAV`` picks a navigation style (CAD when unset); ``SPIKE_CTRL=1``
holds Ctrl on every click, which OpenInventor navigation needs to select;
``SPIKE_SHOT`` names a PNG to save of the front view; ``SPIKE_ROTATE_DEG``
moves the unit and turns it about Z by that many degrees. It reads the
editor's private attributes freely: it is a probe, not a test.
"""

import gc
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.freecad_env import isolate_freecad_settings, load_freecad  # noqa: E402

isolate_freecad_settings()
load_freecad()

import FreeCAD  # noqa: E402
import FreeCADGui as Gui  # noqa: E402
from PySide6 import QtCore, QtGui, QtTest, QtWidgets  # noqa: E402

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
Gui.showMainWindow()
main_window = Gui.getMainWindow()
main_window.resize(1400, 900)
main_window.show()

LEFT = QtCore.Qt.MouseButton.LeftButton
NO_BUTTON = QtCore.Qt.MouseButton.NoButton
MODIFIERS = (
    QtCore.Qt.KeyboardModifier.ControlModifier
    if os.environ.get("SPIKE_CTRL")
    else QtCore.Qt.KeyboardModifier.NoModifier
)
# Longer than QApplication.doubleClickInterval: CAD navigation holds back a
# press that follows the previous one sooner than that, as a possible
# double click, and replays it only at the release.
GESTURE_GAP_MS = 700


def pump(ms: int = 150) -> None:
    end_s = time.time() + ms / 1000
    while time.time() < end_s:
        app.processEvents()
        time.sleep(0.01)


def check(name: str, ok: bool, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    print(("PASS " if ok else "FAIL ") + name + suffix, flush=True)


def main() -> None:
    from freecad.Shelving.core.edit import EditError, region_before, run_axis
    from freecad.Shelving.core.layout import Bay, Board
    from freecad.Shelving.spikes import command
    from freecad.Shelving.spikes.spike_log import LOG_PATH
    from freecad.Shelving.spikes.viewport_editor import _walk
    from freecad.Shelving.spikes.viewport_panel import SpikePanel
    from freecad.Shelving.unit_ops import create_unit

    assert command  # imported for its Gui.addCommand
    LOG_PATH.unlink(missing_ok=True)
    doc = FreeCAD.newDocument("Spike")
    bystander = doc.addObject("Part::Box", "Bystander")
    bystander.Placement.Base = FreeCAD.Vector(3000, 0, 0)
    container = create_unit(doc)
    if os.environ.get("SPIKE_ROTATE_DEG"):
        container.Placement = FreeCAD.Placement(
            FreeCAD.Vector(500, 200, 100),
            FreeCAD.Rotation(
                FreeCAD.Vector(0, 0, 1), float(os.environ["SPIKE_ROTATE_DEG"])
            ),
        )
    doc.recompute()
    pump(300)
    view = Gui.ActiveDocument.ActiveView
    if os.environ.get("SPIKE_NAV"):
        view.setNavigationType(os.environ["SPIKE_NAV"])
    print("navigation", view.getNavigationType(), flush=True)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(container)
    camera_before = view.getCamera()
    Gui.runCommand("Shelving_SpikeViewport")
    pump(500)
    check("dialog open", bool(Gui.Control.activeDialog()))
    panel = [o for o in gc.get_objects() if isinstance(o, SpikePanel)][-1]
    editor = panel.editor
    assert editor is not None
    session = panel.session
    viewport = view.graphicsView().viewport()
    main_window.activateWindow()
    pump(300)
    print("view size", view.getSize(), flush=True)

    def qt_point(point: FreeCAD.Vector) -> QtCore.QPointF:
        # getPointOnViewport is y-up device pixels; Qt is y-down.
        x, y = view.getPointOnViewport(point)
        return QtCore.QPointF(x, view.getSize()[1] - y - 1)

    def send(kind: QtCore.QEvent.Type, pos: QtCore.QPointF, button, buttons) -> None:
        event = QtGui.QMouseEvent(
            kind,
            pos,
            viewport.mapToGlobal(pos.toPoint()),
            button,
            buttons,
            MODIFIERS,
        )
        QtWidgets.QApplication.sendEvent(viewport, event)

    def click(pos: QtCore.QPointF) -> None:
        send(QtCore.QEvent.Type.MouseButtonPress, pos, LEFT, LEFT)
        pump(30)
        send(QtCore.QEvent.Type.MouseButtonRelease, pos, LEFT, NO_BUTTON)
        pump(250)

    def drag(start: QtCore.QPointF, end: QtCore.QPointF, steps: int = 8) -> None:
        send(QtCore.QEvent.Type.MouseButtonPress, start, LEFT, LEFT)
        pump(30)
        for i in range(1, steps + 1):
            point = start + (end - start) * (i / steps)
            send(QtCore.QEvent.Type.MouseMove, point, NO_BUTTON, LEFT)
            pump(30)
        send(QtCore.QEvent.Type.MouseButtonRelease, end, LEFT, NO_BUTTON)
        pump(300)

    frame = editor._frame
    outer = {"bottom", "left_side", "right_side", "top"}

    def nodes_of(kind):
        return [n for n, _d, _a in _walk(session.unit.root) if isinstance(n, kind)]

    def point_in(node_id: str, frac=(0.5, 0.5), z_mm: float = 0.0) -> FreeCAD.Vector:
        h0, v0, h1, v1 = frame.rect(session.spaces[node_id])
        return frame.to_global(h0 + frac[0] * (h1 - h0), v0 + frac[1] * (v1 - v0), z_mm)

    def draggable(board) -> bool:
        try:
            region_before(session.unit, board.id)
        except EditError:
            return False
        return board.id not in outer

    # A divider and a shelf, so there are inner boards and several regions.
    session.select(nodes_of(Bay)[0].id)
    panel.show_result(session.split("horizontal"))
    session.select(nodes_of(Bay)[0].id)
    panel.show_result(session.split("vertical"))
    pump(300)

    bay = nodes_of(Bay)[0]
    click(qt_point(point_in(bay.id, frac=(0.2, 0.8))))
    check("click selects bay", session.selected_id == bay.id, str(session.selected_id))

    board = [b for b in nodes_of(Board) if draggable(b)][0]
    # Near the board's end: its middle sits under a dimension label.
    click(qt_point(point_in(board.id, frac=(0.08, 0.5))))
    check("click selects board", session.selected_id == board.id)
    check("dragger shown on the board", editor._dragger_board == board.id)

    editor.frame_camera()
    pump(GESTURE_GAP_MS)
    before = session.spaces[board.id].origin
    run = run_axis(session.unit, board.id)
    delta = (
        QtCore.QPointF(-40, 0) if run == frame.horizontal else QtCore.QPointF(0, -40)
    )
    start = qt_point(point_in(board.id, z_mm=2.0))
    drag(start, start + delta)
    after = session.spaces[board.id].origin
    # Up and down again, reselecting the board each time as a user does:
    # the drag selects the region before it.
    for back_and_forth in range(4):
        pump(GESTURE_GAP_MS)
        click(qt_point(point_in(board.id, frac=(0.08, 0.5))))
        pump(GESTURE_GAP_MS)
        start = qt_point(point_in(board.id, z_mm=2.0))
        drag(start, start + delta * (-1 if back_and_forth % 2 == 0 else 1))
    drags = LOG_PATH.read_text().count("drag end:")
    check("repeated drags all ran", drags == 5, f"{drags} drags")
    moved_mm = (
        abs(after.x_mm - before.x_mm)
        + abs(after.y_mm - before.y_mm)
        + abs(after.z_mm - before.z_mm)
    )
    check("dragger drag moves board", moved_mm > 1, f"moved {moved_mm:.1f} mm")

    pump(GESTURE_GAP_MS)
    label = editor._labels[0]
    label_point = qt_point(frame.to_global(label.mid_h_mm, label.mid_v_mm))
    click(label_point)
    field = editor._field
    check("label click opens field", field is not None)
    if field is not None:
        field.line_edit.setFocus()
        field.line_edit.selectAll()
        QtTest.QTest.keyClicks(field.line_edit, "234")
        QtTest.QTest.keyClick(field.line_edit, QtCore.Qt.Key.Key_Return)
        pump(400)
        applies = LOG_PATH.read_text().count("field applies 234.0")
        check("Return applies the size once", applies == 1, f"{applies} applies")
        check("dialog open after Return", bool(Gui.Control.activeDialog()))
    pump(GESTURE_GAP_MS)
    click(label_point)
    field = editor._field
    if field is not None:
        QtTest.QTest.keyClick(field.line_edit, QtCore.Qt.Key.Key_Escape)
        pump(400)
        check("Escape closes the field", editor._field is None)
        check("dialog open after Escape", bool(Gui.Control.activeDialog()))

    panel.mode_combo.setCurrentIndex(1)
    pump(GESTURE_GAP_MS)
    target = nodes_of(Board)[0]
    click(qt_point(point_in(target.id, frac=(0.5, 0.3))))
    pump(300)
    check("native picking selects board", session.selected_id == target.id)
    pump(GESTURE_GAP_MS)
    bay = nodes_of(Bay)[0]
    click(qt_point(point_in(bay.id, frac=(0.2, 0.8))))
    check("native picking selects bay", session.selected_id == bay.id)
    panel.mode_combo.setCurrentIndex(0)

    if os.environ.get("SPIKE_SHOT"):
        view.saveImage(os.environ["SPIKE_SHOT"], 480, 360, "White")
    panel.on_top_check.setChecked(True)
    panel.hide_check.setChecked(True)
    pump(200)
    check("bystander hidden", not bystander.ViewObject.Visibility)
    panel.hide_check.setChecked(False)
    pump(200)
    check("bystander restored", bystander.ViewObject.Visibility)

    boards_before = len(nodes_of(Board))
    pump(GESTURE_GAP_MS)
    inner = [b for b in nodes_of(Board) if draggable(b)][0]
    click(qt_point(point_in(inner.id, frac=(0.08, 0.5))))
    QtTest.QTest.keyClick(viewport, QtCore.Qt.Key.Key_Delete)
    pump(400)
    boards_after = len(nodes_of(Board))
    check(
        "Delete merges the board",
        boards_after == boards_before - 1,
        f"{boards_before} -> {boards_after}",
    )

    panel.reject()
    Gui.Control.closeDialog()
    pump(300)

    def without_clipping(camera: str) -> list[str]:
        # Coin recomputes the near and far planes on every render.
        return [line for line in camera.splitlines() if "Distance" not in line]

    check(
        "camera restored",
        without_clipping(view.getCamera()) == without_clipping(camera_before),
    )
    check("overlay removed", view.getSceneGraph().findChild(editor._root) == -1)


try:
    main()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    # FreeCAD's GUI teardown can hang a scripted run.
    os._exit(0)
