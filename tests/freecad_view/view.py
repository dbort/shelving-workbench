"""Driving FreeCAD's 3D view the way a user does, for the view tier.

Events go to the view's viewport widget through ``QApplication.sendEvent``,
so they pass through FreeCAD's navigation style and Coin's event traversal
exactly as a real click does (``.claude/docs/xvfb-gui-testing.md``).
"""

import time
from dataclasses import dataclass, field
from typing import Protocol, cast

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtGui, QtTest, QtWidgets

_LEFT = QtCore.Qt.MouseButton.LeftButton
_NO_BUTTON = QtCore.Qt.MouseButton.NoButton
_NO_MODIFIER = QtCore.Qt.KeyboardModifier.NoModifier
# CAD navigation holds back a left press that comes sooner than the
# double-click interval after the previous one and replays it only at the
# release (NavigationStyle::processClickEvent), so a scripted gesture waits
# out the interval plus this margin.
_GESTURE_MARGIN_MS = 100
# How long FreeCAD gets to finish what a press, a move or a release set off.
_SETTLE_MS = 30


class View3D(Protocol):
    """The part of FreeCAD's ``View3DInventorPy`` these tests use."""

    def getPointOnViewport(self, point: FreeCAD.Vector, /) -> tuple[int, int]: ...
    def getSize(self) -> tuple[int, int]: ...
    def graphicsView(self) -> QtWidgets.QGraphicsView: ...
    def viewFront(self) -> None: ...
    def fitAll(self) -> None: ...


class _GuiDocument(Protocol):
    ActiveView: View3D


Point = FreeCAD.Vector | QtCore.QPointF


def _pump(app: QtWidgets.QApplication, ms: int) -> None:
    end_s = time.monotonic() + ms / 1000
    while time.monotonic() < end_s:
        app.processEvents()
        time.sleep(0.005)


@dataclass
class ViewDriver:
    """Clicks, drags and keys sent to one 3D view, in document coordinates
    or in the viewport's own logical pixels."""

    view: View3D
    app: QtWidgets.QApplication
    # Held for the driver's life: once the wrapper graphicsView() returns is
    # collected, the viewport's wrapper reads as deleted.
    graphics_view: QtWidgets.QGraphicsView
    _last_press_s: float = field(default=0.0)

    @staticmethod
    def for_active_view() -> "ViewDriver":
        """The driver for the active document's 3D view, once Qt has laid
        it out. Raises ``RuntimeError`` when there is no 3D view."""
        app = cast("QtWidgets.QApplication", QtWidgets.QApplication.instance())
        # A new document's view appears only once Qt has run; read before
        # that, ActiveView is the previous view, already deleted.
        _pump(app, 200)
        gui_document = cast("_GuiDocument | None", FreeCADGui.ActiveDocument)
        if gui_document is None or not hasattr(gui_document.ActiveView, "graphicsView"):
            raise RuntimeError("the active document has no 3D view")
        view = gui_document.ActiveView
        return ViewDriver(view, app, view.graphicsView())

    @property
    def viewport(self) -> QtWidgets.QWidget:
        return self.graphics_view.viewport()

    def pump(self, ms: int = 150) -> None:
        """Run Qt's event loop for ``ms``: layout, focus, rendering and
        deferred ``QTimer.singleShot(0, ...)`` work all need it."""
        _pump(self.app, ms)

    def qt_point(self, point: Point) -> QtCore.QPointF:
        """``point`` in the viewport's logical pixels, y down.
        ``getPointOnViewport`` answers in device pixels, y up."""
        if isinstance(point, QtCore.QPointF):
            return point
        x_px, y_px = self.view.getPointOnViewport(point)
        ratio = self.viewport.devicePixelRatioF()
        height_px = self.view.getSize()[1]
        return QtCore.QPointF(x_px / ratio, (height_px - y_px - 1) / ratio)

    def _send(
        self,
        kind: QtCore.QEvent.Type,
        at: QtCore.QPointF,
        button: QtCore.Qt.MouseButton,
        buttons: QtCore.Qt.MouseButton,
        modifiers: QtCore.Qt.KeyboardModifier,
    ) -> None:
        viewport = self.viewport
        event = QtGui.QMouseEvent(
            kind,
            at,
            QtCore.QPointF(viewport.mapToGlobal(at.toPoint())),
            button,
            buttons,
            modifiers,
        )
        QtWidgets.QApplication.sendEvent(viewport, event)

    def _press(self, at: QtCore.QPointF, modifiers: QtCore.Qt.KeyboardModifier) -> None:
        gap_s = (
            QtWidgets.QApplication.doubleClickInterval() + _GESTURE_MARGIN_MS
        ) / 1000
        wait_s = self._last_press_s + gap_s - time.monotonic()
        if wait_s > 0:
            self.pump(round(wait_s * 1000))
        self._send(QtCore.QEvent.Type.MouseButtonPress, at, _LEFT, _LEFT, modifiers)
        self._last_press_s = time.monotonic()
        self.pump(_SETTLE_MS)

    def click(
        self, at: Point, modifiers: QtCore.Qt.KeyboardModifier = _NO_MODIFIER
    ) -> None:
        """A left click at ``at``, a document point or a viewport point."""
        point = self.qt_point(at)
        self._press(point, modifiers)
        self._send(
            QtCore.QEvent.Type.MouseButtonRelease, point, _LEFT, _NO_BUTTON, modifiers
        )
        self.pump()

    def drag(
        self,
        start: Point,
        end: Point,
        steps: int = 8,
        modifiers: QtCore.Qt.KeyboardModifier = _NO_MODIFIER,
    ) -> None:
        """A left-button drag from ``start`` to ``end`` in ``steps`` moves,
        each carrying the held button as a real move event does."""
        first = self.qt_point(start)
        last = self.qt_point(end)
        self._press(first, modifiers)
        for step in range(1, steps + 1):
            point = first + (last - first) * (step / steps)
            self._send(
                QtCore.QEvent.Type.MouseMove, point, _NO_BUTTON, _LEFT, modifiers
            )
            self.pump(_SETTLE_MS)
        self._send(
            QtCore.QEvent.Type.MouseButtonRelease, last, _LEFT, _NO_BUTTON, modifiers
        )
        self.pump()

    def key(
        self, key: QtCore.Qt.Key, modifiers: QtCore.Qt.KeyboardModifier = _NO_MODIFIER
    ) -> None:
        """A key press and release with the viewport focused."""
        viewport = self.viewport
        viewport.setFocus()
        QtTest.QTest.keyClick(viewport, key, modifiers)
        self.pump()

    def grab(self) -> QtGui.QImage:
        """The view as drawn on screen, in device pixels."""
        self.pump()
        return self.viewport.grab().toImage()

    def color_at(self, image: QtGui.QImage, point: FreeCAD.Vector) -> QtGui.QColor:
        """The color ``image``, a :meth:`grab`, shows at document point
        ``point``."""
        x_px, y_px = self.view.getPointOnViewport(point)
        return image.pixelColor(x_px, self.view.getSize()[1] - y_px - 1)
