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
    from freecad.Shelving.core.edit import _locate, run_axis
    from freecad.Shelving.core.layout import Bay, Board
    from freecad.Shelving.properties import has_board_properties, paint
    from freecad.Shelving.spikes import command
    from freecad.Shelving.spikes.local_move import holders, is_locked
    from freecad.Shelving.spikes.spike_log import LOG_PATH
    from freecad.Shelving.spikes.viewport_editor import _walk, elevation_frame
    from freecad.Shelving.spikes.viewport_panel import SpikePanel
    from freecad.Shelving.unit_ops import create_unit

    assert command  # imported for its Gui.addCommand
    LOG_PATH.unlink(missing_ok=True)
    # FreeCAD keeps 20 steps by default, fewer than this run's session
    # makes; past the limit the session's start falls off the history and
    # Cancel cannot reach it (research/viewport-editing.md).
    FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Document").SetInt(
        "MaxUndoSize", 100
    )
    doc = FreeCAD.newDocument("Spike")
    bystander = doc.addObject("Part::Box", "Bystander")
    bystander.Placement.Base = FreeCAD.Vector(3000, 0, 0)
    # A step before the session, as the GUI's Create Unit leaves, for an
    # Undo past the session's start to reach.
    doc.UndoMode = 1
    doc.openTransaction("Create Shelving Unit")
    container = create_unit(doc)
    doc.commitTransaction()
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

    def document_boards() -> int:
        return sum(1 for o in doc.Objects if has_board_properties(o))

    boards_at_start = document_boards()
    undo_at_start = doc.UndoCount
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

    def arrow_point() -> QtCore.QPointF:
        x, y, z = editor._dragger_transform.translation.getValue().getValue()
        return qt_point(editor._frame.to_global(x, y, z))

    def draggable(board) -> bool:
        return board.id not in outer and holders(session.unit, board.id) == ()

    # A divider and a shelf, so there are inner boards and several regions.
    session.select(nodes_of(Bay)[0].id)
    panel.run_edit("Add divider", lambda: session.split("horizontal"))
    session.select(nodes_of(Bay)[0].id)
    panel.run_edit("Add shelf", lambda: session.split("vertical"))
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
    start = arrow_point()
    drag(start, start + delta)
    after = session.spaces[board.id].origin
    pump(300)
    check(
        "board and arrow stay selected after a drag",
        session.selected_id == board.id and editor._dragger_board == board.id,
        str(session.selected_id),
    )
    # Up and down again on the same arrow, with no reselecting.
    for back_and_forth in range(4):
        pump(GESTURE_GAP_MS)
        start = arrow_point()
        drag(start, start + delta * (-1 if back_and_forth % 2 == 0 else 1))
    drags = LOG_PATH.read_text().count("drag end:")
    check("repeated drags all ran", drags == 5, f"{drags} drags")
    moved_mm = (
        abs(after.x_mm - before.x_mm)
        + abs(after.y_mm - before.y_mm)
        + abs(after.z_mm - before.z_mm)
    )
    check("dragger drag moves board", moved_mm > 1, f"moved {moved_mm:.1f} mm")

    # Two shelves in one run, as in the user's note: dragging the second
    # moves no other board.
    def added_by(edit_name: str, bay_id: str, direction: str) -> str:
        ids = {b.id for b in nodes_of(Board)}
        session.select(bay_id)
        panel.run_edit(edit_name, lambda: session.split(direction))
        (new_id,) = {b.id for b in nodes_of(Board)} - ids
        return new_id

    first = added_by("Add shelf", nodes_of(Bay)[0].id, "vertical")
    run_parent, first_index = _locate(session.unit.root, first)
    second = added_by("Add shelf", run_parent.items[first_index + 1].id, "vertical")
    others = {
        b.id: session.spaces[b.id].origin for b in nodes_of(Board) if b.id != second
    }
    second_before = session.spaces[second].origin
    session.select(second)
    panel._refresh()
    editor.frame_camera()
    pump(GESTURE_GAP_MS)
    start = arrow_point()
    drag(start, start + QtCore.QPointF(0, -30))
    pump(300)
    shifted = [
        board_id
        for board_id, origin in others.items()
        if board_id in session.spaces and session.spaces[board_id].origin != origin
    ]
    check(
        "dragging a shelf moves no other board",
        not shifted and session.spaces[second].origin != second_before,
        f"moved {shifted}; {second_before} -> {session.spaces[second].origin}",
    )

    # A locked opening carries the boards beside it along with a drag; a
    # board is held only when locks reach the end of its row, and its
    # padlock then unlocks the nearest one.
    check(
        "a drag leaves its neighbors unlocked",
        holders(session.unit, second) == (),
        str(holders(session.unit, second)),
    )

    def padlock_for(region_id: str):
        for button, label in zip(editor._padlocks, editor._labels, strict=False):
            if label.region_id == region_id:
                return button
        return None

    def run_regions() -> list:
        parent, _index = _locate(session.unit.root, second)
        return [item for item in parent.items if not isinstance(item, Board)]

    def click_padlocks(region_ids, lock: bool) -> None:
        for region in run_regions():
            button = padlock_for(region.id)
            if region.id in region_ids and is_locked(region) != lock and button:
                QtTest.QTest.mouseClick(button, LEFT)
                pump(300)

    parent, second_index = _locate(session.unit.root, second)
    below_id = parent.items[second_index - 1].id
    carried = parent.items[second_index - 2]
    pump(GESTURE_GAP_MS)
    button = padlock_for(below_id)
    visible = [b for b in editor._padlocks if b.isVisible()]
    check(
        "a padlock beside each dimension",
        button is not None
        and len(visible) == sum(1 for label in editor._labels if label.lockable),
        f"{len(visible)} padlocks, {len(editor._labels)} labels",
    )
    click_padlocks({below_id}, True)
    check(
        "a lock between two shelves leaves both draggable",
        isinstance(carried, Board)
        and holders(session.unit, second) == ()
        and holders(session.unit, carried.id) == ()
        and editor._dragger_board == second,
        f"{holders(session.unit, second)}, arrow on {editor._dragger_board}",
    )
    run_index = run_axis(session.unit, second).component_index
    locked_before_mm = session.spaces[below_id].extent_mm(run_index)
    carried_before_mm = session.spaces[carried.id].origin_mm(run_index)
    pump(GESTURE_GAP_MS)
    start = arrow_point()
    drag(start, start + QtCore.QPointF(0, -30))
    carried_after_mm = session.spaces[carried.id].origin_mm(run_index)
    check(
        "a drag carries the shelf beyond a locked opening",
        abs(session.spaces[below_id].extent_mm(run_index) - locked_before_mm) < 1e-6
        and abs(carried_after_mm - carried_before_mm) > 1,
        f"locked {locked_before_mm:.2f} -> "
        f"{session.spaces[below_id].extent_mm(run_index):.2f}, carried "
        f"{carried_before_mm:.2f} -> {carried_after_mm:.2f}",
    )
    parent, second_index = _locate(session.unit.root, second)
    low_side = {item.id for item in parent.items[:second_index]}
    click_padlocks(low_side, True)
    check(
        "locks reaching the row's end hold the board",
        holders(session.unit, second) == (below_id,),
        str(holders(session.unit, second)),
    )
    check(
        "a held board shows a padlock in place of its arrow",
        editor._board_lock.isVisible() and editor._dragger_board is None,
        f"selected {session.selected_id}",
    )
    QtTest.QTest.mouseClick(editor._board_lock, LEFT)
    pump(300)
    parent, second_index = _locate(session.unit.root, second)
    check(
        "the board's padlock unlocks the nearest lock holding it",
        holders(session.unit, second) == ()
        and not is_locked(parent.items[second_index - 1])
        and editor._dragger_board == second,
        str(holders(session.unit, second)),
    )
    click_padlocks({region.id for region in run_regions()}, True)
    locked = [region.id for region in run_regions() if is_locked(region)]
    check(
        "the last unlocked opening in a row cannot be locked",
        len(locked) == len(run_regions()) - 1
        and "edit refused: One opening in each row" in LOG_PATH.read_text(),
        f"{len(locked)} of {len(run_regions())} locked",
    )
    click_padlocks(set(locked), False)
    check(
        "padlocks unlock again",
        not any(is_locked(region) for region in run_regions()),
    )
    if os.environ.get("SPIKE_SHOT"):
        stem, ext = os.path.splitext(os.environ["SPIKE_SHOT"])
        grab = main_window.grab()
        grab.save(f"{stem}-padlocks{ext}")
    session.select("top")
    panel._refresh()
    pump(300)
    check(
        "a carcass board shows neither arrow nor padlock",
        editor._dragger_board is None and not editor._board_lock.isVisible(),
    )

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
    picked = Gui.Selection.getSelectionEx()
    check(
        "native picking selects the whole board",
        len(picked) == 1 and not picked[0].SubElementNames,
        str([(p.ObjectName, p.SubElementNames) for p in picked]),
    )
    pump(GESTURE_GAP_MS)
    bay = nodes_of(Bay)[0]
    click(qt_point(point_in(bay.id, frac=(0.2, 0.8))))
    check("native picking selects bay", session.selected_id == bay.id)
    check(
        "clicking an opening clears FreeCAD's selection",
        not Gui.Selection.getSelectionEx(),
    )
    if os.environ.get("SPIKE_SHOT"):
        stem, ext = os.path.splitext(os.environ["SPIKE_SHOT"])
        view.saveImage(f"{stem}-native{ext}", 480, 360, "White")
    panel.mode_combo.setCurrentIndex(0)

    # From behind, the overlay moves to the back face and its arrow drags.
    board = [b for b in nodes_of(Board) if draggable(b)][0]
    pump(GESTURE_GAP_MS)
    click(qt_point(point_in(board.id, frac=(0.08, 0.5))))
    camera = view.getCameraNode()
    behind = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), 180).multiply(
        editor._front_frame.placement.Rotation
    )
    camera.orientation.setValue(*behind.Q)
    center = editor._front_frame.to_global(300, 450)
    toward = behind.multVec(FreeCAD.Vector(0, 0, 1)) * 2700
    camera.position.setValue(
        center.x + toward.x, center.y + toward.y, center.z + toward.z
    )
    pump(500)
    check("overlay on the back face from behind", editor._z_sign == -1)
    if os.environ.get("SPIKE_SHOT_BACK"):
        view.saveImage(os.environ["SPIKE_SHOT_BACK"], 480, 360, "White")
    # A new depth moves the back face, and the overlay with it.
    depth_mm = session.unit_dimension_mm("depth")
    panel._resize("depth", depth_mm - 20)
    pump(300)
    back_base = editor._frame.placement.Base
    expected = elevation_frame(session.unit, session.container, back=True)
    check(
        "overlay follows a new depth to the back face",
        (back_base - expected.placement.Base).Length < 1e-6
        and session.unit_dimension_mm("depth") == depth_mm - 20,
        f"{back_base} vs {expected.placement.Base}",
    )
    panel._resize("depth", depth_mm)
    pump(300)
    drags_before = LOG_PATH.read_text().count("drag end:")
    before = session.spaces[board.id].origin
    pump(GESTURE_GAP_MS)
    start = arrow_point()
    drag(start, start + QtCore.QPointF(0, -40))
    after = session.spaces[board.id].origin
    check(
        "arrow drags from behind",
        LOG_PATH.read_text().count("drag end:") == drags_before + 1 and after != before,
        f"{before} -> {after}",
    )
    editor.frame_camera()
    pump(300)
    check("front view puts the overlay back", editor._z_sign == 1)

    if os.environ.get("SPIKE_SHOT"):
        # A bay selected and a board's arrow shown, as a user sees them.
        session.select(nodes_of(Bay)[0].id)
        panel._refresh()
        pump(200)
        view.saveImage(os.environ["SPIKE_SHOT"], 480, 360, "White")
        board = [b for b in nodes_of(Board) if draggable(b)][0]
        session.select(board.id)
        panel._refresh()
        pump(200)
        stem, ext = os.path.splitext(os.environ["SPIKE_SHOT"])
        view.saveImage(f"{stem}-arrow{ext}", 480, 360, "White")
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
    # A Mac's delete key.
    QtTest.QTest.keyClick(viewport, QtCore.Qt.Key.Key_Backspace)
    pump(400)
    boards_after = len(nodes_of(Board))
    check(
        "Backspace merges the board",
        boards_after == boards_before - 1,
        f"{boards_before} -> {boards_after}",
    )

    # With FreeCAD's selection on, its Delete command would take the key.
    panel.mode_combo.setCurrentIndex(1)
    pump(GESTURE_GAP_MS)
    boards_before = len(nodes_of(Board))
    inner = [b for b in nodes_of(Board) if draggable(b)][0]
    click(qt_point(point_in(inner.id, frac=(0.08, 0.5))))
    pump(300)
    QtTest.QTest.keyClick(viewport, QtCore.Qt.Key.Key_Delete)
    pump(400)
    boards_after = len(nodes_of(Board))
    check(
        "Delete merges the board under FreeCAD picking",
        boards_after == boards_before - 1 and "Delete" not in doc.UndoNames,
        f"{boards_before} -> {boards_after}, undo {doc.UndoNames}",
    )
    panel.mode_combo.setCurrentIndex(0)

    # Undo and Redo as Cmd-Z and the Edit menu run them.
    boards_before = len(nodes_of(Board))
    undo_count = doc.UndoCount
    Gui.runCommand("Std_Undo")
    pump(300)
    check(
        "Undo takes back the last delete",
        len(nodes_of(Board)) == boards_before + 1
        and document_boards() == len(nodes_of(Board))
        and doc.UndoCount == undo_count - 1
        and bool(Gui.Control.activeDialog()),
        f"{boards_before} -> {len(nodes_of(Board))}, undo {doc.UndoNames}",
    )
    Gui.runCommand("Std_Redo")
    pump(300)
    check(
        "Redo deletes it again",
        len(nodes_of(Board)) == boards_before and document_boards() == boards_before,
        f"{len(nodes_of(Board))} boards, undo {doc.UndoNames}",
    )
    history = panel.history
    assert history is not None
    for _ in range(doc.UndoCount + 2):
        Gui.runCommand("Std_Undo")
    pump(400)
    check(
        "Undo past the start stops at the start",
        doc.UndoCount == history._start_count
        and doc.getObject(container.Name) is container
        and len(nodes_of(Board)) == boards_at_start
        and document_boards() == boards_at_start
        and bool(Gui.Control.activeDialog()),
        f"undo {doc.UndoNames}, redo {doc.RedoNames}, {len(nodes_of(Board))} boards",
    )

    # The in-view buttons over a selected bay.
    bay = nodes_of(Bay)[0]
    click(qt_point(point_in(bay.id, frac=(0.2, 0.2))))
    pump(300)
    bar = editor._add_bar
    check("add buttons over the selected bay", bar.isVisible(), str(bar.geometry()))
    shelf_button = bar.buttons["vertical"]
    QtTest.QTest.mouseMove(shelf_button)
    pump(300)
    if editor._preview is None:
        print("no Enter event under Xvfb; previewing directly", flush=True)
        editor._preview_add("vertical")
    check("hovering previews the shelf", editor._split_preview() is not None)
    if os.environ.get("SPIKE_SHOT"):
        stem, ext = os.path.splitext(os.environ["SPIKE_SHOT"])
        view.graphicsView().parentWidget().grab().save(f"{stem}-add{ext}")
    boards_before = len(nodes_of(Board))
    QtTest.QTest.mouseClick(shelf_button, LEFT)
    pump(300)
    selected = session.selected_id
    check(
        "shelf button adds a shelf and selects it",
        len(nodes_of(Board)) == boards_before + 1
        and editor._dragger_board == selected
        and doc.UndoNames[0] == "Add shelf"
        and doc.RedoCount == 0,
        f"selected {selected}, undo {doc.UndoNames}",
    )

    if os.environ.get("SPIKE_SHOT"):
        # A column with regions above and below it: its width belongs
        # inside the unit, clear of its neighbors.
        def split(bay_id: str, direction: str) -> None:
            session.select(bay_id)
            panel.run_edit("Split", lambda: session.split(direction))

        def bays_by(key):
            return sorted(nodes_of(Bay), key=lambda b: key(session.spaces[b.id].origin))

        left = [
            b
            for b in bays_by(lambda o: o.z_mm)
            if session.spaces[b.id].origin.x_mm < 100
        ]
        split(left[-1].id, "vertical")
        left = [
            b
            for b in bays_by(lambda o: o.z_mm)
            if session.spaces[b.id].origin.x_mm < 100
        ]
        middle_z_mm = session.spaces[left[1].id].origin.z_mm
        split(left[1].id, "horizontal")
        row = [
            b
            for b in bays_by(lambda o: o.x_mm)
            if abs(session.spaces[b.id].origin.z_mm - middle_z_mm) < 1e-6
        ]
        split(row[-1].id, "vertical")
        session.select(None)
        panel._refresh()
        pump(200)
        stem, ext = os.path.splitext(os.environ["SPIKE_SHOT"])
        view.saveImage(f"{stem}-nested{ext}", 480, 360, "White")

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
    check(
        "Cancel restores the document and clears Redo",
        doc.UndoCount == undo_at_start
        and doc.RedoCount == 0
        and document_boards() == boards_at_start,
        f"undo {doc.UndoNames}, redo {doc.RedoNames}, {document_boards()} boards",
    )

    # A second session, kept with OK: one history step for all of it.
    painted_rgb = (200, 30, 30)
    for obj in doc.Objects:
        if has_board_properties(obj):
            paint(obj, painted_rgb)
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(container)
    Gui.runCommand("Shelving_SpikeViewport")
    pump(500)
    first_panel = panel
    panel = [
        o
        for o in gc.get_objects()
        if isinstance(o, SpikePanel) and o is not first_panel
    ][-1]
    session = panel.session
    for direction in ("vertical", "horizontal"):
        session.select(nodes_of(Bay)[0].id)
        panel.run_edit("Split", lambda d=direction: session.split(d))
    # The read back after these drops what the new boards copied from.
    Gui.runCommand("Std_Undo")
    pump(300)
    Gui.runCommand("Std_Redo")
    pump(300)
    kept_boards = len(nodes_of(Board))
    panel.accept()
    Gui.Control.closeDialog()
    pump(300)
    check(
        "OK keeps one history step",
        doc.UndoNames == ["Edit Shelving Unit", "Create Shelving Unit"]
        and document_boards() == kept_boards
        and doc.RedoCount == 0,
        f"undo {doc.UndoNames}, {document_boards()} of {kept_boards} boards",
    )
    unpainted = [
        obj.Name
        for obj in doc.Objects
        if has_board_properties(obj)
        and tuple(
            round(c * 255) for c in obj.ViewObject.ShapeAppearance[0].DiffuseColor[:3]
        )
        != painted_rgb
    ]
    check(
        "added boards keep the copied color through Undo, Redo and OK",
        not unpainted,
        f"unpainted {unpainted}",
    )
    Gui.runCommand("Std_Undo")
    pump(300)
    check(
        "one Undo after OK takes back the session",
        document_boards() == boards_at_start,
        f"{document_boards()} boards",
    )


try:
    main()
except Exception:
    traceback.print_exc()
finally:
    sys.stdout.flush()
    # FreeCAD's GUI teardown can hang a scripted run.
    os._exit(0)
