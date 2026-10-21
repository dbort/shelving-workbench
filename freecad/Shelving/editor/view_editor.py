"""The in-view editor: the overlay, camera, picking and in-view controls of
one editing session in a FreeCAD 3D view.

The container cannot enter FreeCAD's edit mode without putting workbench
state in the document, so the session is shaped like a Draft command's:
opening adds an overlay subgraph, callbacks and filters to the view, and
:meth:`ViewEditor.close` removes every one of them. Navigation stays
FreeCAD's own.

Coin must not lose a node on the path of the event it is handling, so
every rebuild a Coin callback triggers waits for the Qt event loop, and the
dragger lives under its own holder that a rebuild leaves alone.

FreeCAD's ``SoFCUnifiedSelection`` takes a click on any object before an
event callback sees it, even one the selection gate refuses, so clicks on
dimensions and openings are read from a Qt event filter on the view's
viewport, which sees every press and release before navigation does.
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import FreeCAD
import FreeCADGui
from pivy import coin
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from freecad.Shelving.compat import override
from freecad.Shelving.core.edit import fixed_point_mm
from freecad.Shelving.core.layout import Unit
from freecad.Shelving.editor.elevation import (
    LIFT_MM,
    Arrow,
    DimensionLabel,
    ElevationFrame,
    HeldPadlock,
    Overlay,
    Rect,
    arrow_for,
    board_ids,
    dragged_to_mm,
    elevation_frame,
    held_padlock,
    label_at,
    label_size_pt,
    plan_overlay,
    region_at,
    split_preview,
)
from freecad.Shelving.editor.fields import DimensionField
from freecad.Shelving.editor.overlay import (
    RGB,
    Coin,
    PointMarker,
    Style,
    arrow_geometry,
    coin_destroys_draggers_safely,
    drawing_node,
    label_string,
    view_style,
)
from freecad.Shelving.editor.session import (
    FIELD_PROPERTIES,
    Session,
    SplitDirection,
)
from freecad.Shelving.refusals import report_error

# The add buttons' icon side, in logical pixels.
_ICON_PX = 24
# A padlock's icon side, its body's inset from the icon's left and right
# edges, and the gap between the icon's edge and its dimension's text, in
# logical pixels. The shackle reaches the icon's top edge, and the right
# edge too when open.
_PADLOCK_PX = 14
_PADLOCK_INSET_PX = 2
_PADLOCK_GAP_PX = 4
# The clear gap between the text of neighboring rows of dimensions outside
# the unit, and between the first row's text and the unit, in logical
# pixels at the fitted view.
_ROW_GAP_PX = 8
# The fixed point marker's side, in logical pixels.
_MARKER_PX = 16
# Inkscape's rotation-center marker on its 8.81 mm square: a plus whose arms
# meet in a chamfered hub, with a round hole at the center.
_MARKER_SIDE_MM = 8.8134
_MARKER_OUTLINE_MM = (
    (3.3507, 0.0),
    (3.3507, 1.7601),
    (1.7601, 3.3507),
    (0.0, 3.3507),
    (0.0, 5.4622),
    (1.7601, 5.4622),
    (3.3507, 7.0528),
    (3.3507, 8.8129),
    (5.4622, 8.8129),
    (5.4622, 7.0528),
    (7.0528, 5.4622),
    (8.8134, 5.4622),
    (8.8134, 3.3507),
    (7.0528, 3.3507),
    (5.4622, 1.7601),
    (5.4622, 0.0),
)
_MARKER_HOLE_CENTER_MM = (4.40645, 4.40645)
_MARKER_HOLE_RADIUS_MM = 1.47218
# SoDatumLabel's font when its name field is left at its default, as the
# Sketcher leaves it. Qt substitutes the same face for SoDatumLabel's
# drawing and for the measurement here, so the two agree.
_LABEL_FONT = "Helvetica"
_UNITS_PARAMS = "User parameter:BaseApp/Preferences/Units"
# How long the turn toward the unit may animate before the fit goes ahead.
_TURN_TIMEOUT_S = 3.0
_POLL_MS = 20
# How far around the unit the fit leaves room, for the dimensions outside
# it, as a fraction of its longer elevation side.
_FIT_MARGIN_FRACTION = 0.2
# How close a press must come to the drag arrow, in device pixels, to be
# left to the dragger.
_ARROW_HIT_PX = 10.0
_RESTORE_CAMERA_PARAM = "User parameter:BaseApp/Preferences/Mod/Sketcher/General"


class View3D(Protocol):
    """The parts of FreeCAD's ``View3DInventorPy`` the editor calls; the
    stubs do not declare them."""

    def getSceneGraph(self) -> Coin: ...
    def getCameraNode(self) -> Coin: ...
    def getCamera(self) -> str: ...
    def setCamera(self, camera: str, /) -> None: ...
    def setCameraType(self, kind: str, /) -> None: ...
    def getCameraOrientation(self) -> FreeCAD.Rotation: ...
    def setCameraOrientation(self, rotation: FreeCAD.Rotation, /) -> None: ...
    def getSize(self) -> tuple[int, int]: ...
    def getObjectInfo(
        self, position: tuple[int, int], /
    ) -> Mapping[str, object] | None: ...
    def getPointOnViewport(self, point: FreeCAD.Vector, /) -> tuple[int, int]: ...
    def projectPointToLine(
        self, position: tuple[int, int], /
    ) -> tuple[FreeCAD.Vector, FreeCAD.Vector]: ...
    def graphicsView(self) -> QtWidgets.QGraphicsView: ...
    def addDraggerCallback(
        self, dragger: Coin, kind: str, callback: Callable[[Coin], None], /
    ) -> Callable[[Coin], None]: ...
    def removeDraggerCallback(
        self, dragger: Coin, kind: str, callback: Callable[[Coin], None], /
    ) -> None: ...


class _ViewObject(Protocol):
    Visibility: bool


def container_placement(container: FreeCAD.DocumentObject) -> FreeCAD.Placement:
    """``container``'s placement in the document. ``getGlobalPlacement``
    covers an ``App::Part`` nested in others; a top-level link group falls
    back to its own ``Placement``."""
    get_global = getattr(container, "getGlobalPlacement", None)
    if callable(get_global):
        placement = get_global()
        if isinstance(placement, FreeCAD.Placement):
            return placement
    own = getattr(container, "Placement", None)
    return own if isinstance(own, FreeCAD.Placement) else FreeCAD.Placement()


def _path_names(obj_name: str, sub_name: str) -> list[str]:
    """``obj_name`` followed by each object a sub-element path such as
    ``"Board001.Face3"`` or ``"Board001."`` walks through."""
    return [obj_name, *(part for part in sub_name.split(".")[:-1] if part)]


def _sbrotation(rotation: FreeCAD.Rotation) -> Coin:
    x, y, z, w = rotation.Q
    return coin.SbRotation(x, y, z, w)


def _bind(
    callback: Callable[[SplitDirection], None], direction: SplitDirection
) -> Callable[[], None]:
    """A slot taking no arguments: PySide passes ``clicked``'s checked flag
    to any callable that accepts one, such as a ``partial``."""
    return lambda: callback(direction)


def _board_icon(
    direction: SplitDirection, ratio: float, rgb: tuple[float, float, float]
) -> QtGui.QIcon:
    """An opening with the board ``direction``'s split adds across it: a
    shelf for "vertical", a divider for "horizontal"."""
    pixmap = QtGui.QPixmap(round(_ICON_PX * ratio), round(_ICON_PX * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    pen = QtGui.QPen(
        QtWidgets.QApplication.palette().color(QtGui.QPalette.ColorRole.ButtonText)
    )
    pen.setWidthF(1.5)
    painter.setPen(pen)
    side_px = _ICON_PX - 6
    painter.drawRect(QtCore.QRectF(3, 3, side_px, side_px))
    bar = (
        QtCore.QRectF(3, _ICON_PX / 2 - 1.5, side_px, 3)
        if direction == "vertical"
        else QtCore.QRectF(_ICON_PX / 2 - 1.5, 3, 3, side_px)
    )
    painter.fillRect(bar, QtGui.QColor.fromRgbF(*rgb))
    painter.end()
    return QtGui.QIcon(pixmap)


def _padlock_icon(locked: bool, ratio: float, rgb: RGB) -> QtGui.QIcon:
    """A padlock in ``rgb``: a filled body under a shackle, closed when
    ``locked``, swung open off the body's left side otherwise."""
    side_px = _PADLOCK_PX
    pixmap = QtGui.QPixmap(round(side_px * ratio), round(side_px * ratio))
    pixmap.setDevicePixelRatio(ratio)
    pixmap.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    color = QtGui.QColor.fromRgbF(*rgb)
    pen = QtGui.QPen(color)
    pen.setWidthF(1.6)
    painter.setPen(pen)
    body = QtCore.QRectF(
        _PADLOCK_INSET_PX,
        side_px * 0.45,
        side_px - 2 * _PADLOCK_INSET_PX,
        side_px * 0.5,
    )
    shackle = QtCore.QRectF(4, 1.5, side_px - 8, side_px * 0.6)
    if not locked:
        shackle.translate(side_px * 0.18, -1)
    painter.drawArc(shackle, 0, 180 * 16)
    painter.drawLine(
        QtCore.QPointF(shackle.right(), shackle.center().y()),
        QtCore.QPointF(shackle.right(), body.top()),
    )
    if locked:
        painter.drawLine(
            QtCore.QPointF(shackle.left(), shackle.center().y()),
            QtCore.QPointF(shackle.left(), body.top()),
        )
    painter.fillRect(body, color)
    painter.end()
    return QtGui.QIcon(pixmap)


def marker_path(side_px: float) -> QtGui.QPainterPath:
    """The fixed point marker's outline and hole, filling the square from
    the origin to ``side_px`` on each axis; its odd-even fill leaves the
    hole open."""
    path = QtGui.QPainterPath()
    path.setFillRule(QtCore.Qt.FillRule.OddEvenFill)
    path.addPolygon(
        QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in _MARKER_OUTLINE_MM])
    )
    path.closeSubpath()
    path.addEllipse(
        QtCore.QPointF(*_MARKER_HOLE_CENTER_MM),
        _MARKER_HOLE_RADIUS_MM,
        _MARKER_HOLE_RADIUS_MM,
    )
    scale = side_px / _MARKER_SIDE_MM
    return QtGui.QTransform.fromScale(scale, scale).map(path)


def marker_image(ratio: float, rgb: RGB) -> QtGui.QImage:
    """The fixed point marker in ``rgb``, :data:`_MARKER_PX` logical pixels
    square at the device pixel ratio ``ratio``, transparent around it and
    in its hole."""
    side_px = round(_MARKER_PX * ratio)
    image = QtGui.QImage(side_px, side_px, QtGui.QImage.Format.Format_RGBA8888)
    image.fill(QtCore.Qt.GlobalColor.transparent)
    painter = QtGui.QPainter(image)
    painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
    painter.fillPath(marker_path(side_px), QtGui.QColor.fromRgbF(*rgb))
    painter.end()
    return image


def _padlock_button(
    parent: QtWidgets.QWidget | None, on_click: Callable[[], None]
) -> QtWidgets.QToolButton:
    button = QtWidgets.QToolButton(parent)
    button.setAutoRaise(True)
    button.setIconSize(QtCore.QSize(_PADLOCK_PX, _PADLOCK_PX))
    button.setFixedSize(_PADLOCK_PX + 4, _PADLOCK_PX + 4)
    button.setStyleSheet("QToolButton { border: none; padding: 0; }")
    # As the add buttons do: keyboard focus stays in the 3D view.
    button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
    button.clicked.connect(on_click)
    button.hide()
    return button


def _bind_index(on_click: Callable[[int], None], index: int) -> Callable[[], None]:
    """:func:`_bind` for a padlock's place in the pool."""
    return lambda: on_click(index)


class AddBar(QtWidgets.QFrame):
    """The Add shelf and Add divider buttons over the selected bay.
    Hovering one reports its split to ``on_hover``; leaving reports
    ``None``."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        rgb: tuple[float, float, float],
        on_add: Callable[[SplitDirection], None],
        on_hover: Callable[[SplitDirection | None], None],
    ) -> None:
        super().__init__(parent)
        self._on_hover = on_hover
        self._rgb = rgb
        self.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        self.setAutoFillBackground(True)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.buttons: dict[SplitDirection, QtWidgets.QToolButton] = {}
        directions: tuple[tuple[SplitDirection, str], ...] = (
            ("vertical", "Add shelf"),
            ("horizontal", "Add divider"),
        )
        for direction, text in directions:
            button = QtWidgets.QToolButton(self)
            button.setIconSize(QtCore.QSize(_ICON_PX, _ICON_PX))
            button.setText(text)
            button.setToolTip(text)
            button.setAccessibleName(text)
            # As a toolbar button does: keyboard focus stays in the 3D view,
            # where Delete and FreeCAD's Undo shortcuts reach the edit.
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            button.clicked.connect(_bind(on_add, direction))
            button.installEventFilter(self)
            layout.addWidget(button)
            self.buttons[direction] = button
        self.draw_icons(self.devicePixelRatioF())
        self.hide()

    def draw_icons(self, ratio: float) -> None:
        """Give each button its icon drawn at the device pixel ratio
        ``ratio``."""
        for direction, button in self.buttons.items():
            button.setIcon(_board_icon(direction, ratio, self._rgb))

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.Enter:
            for direction, button in self.buttons.items():
                if watched is button:
                    self._on_hover(direction)
        elif event.type() == QtCore.QEvent.Type.Leave:
            self._on_hover(None)
        return False


class _FieldKeys(QtCore.QObject):
    """Closes the floating field on Escape, which would otherwise reach the
    task dialog and close the whole edit."""

    def __init__(self, parent: QtCore.QObject, on_escape: Callable[[], None]) -> None:
        super().__init__(parent)
        self._on_escape = on_escape

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.KeyPress:
            if cast("QtGui.QKeyEvent", event).key() == QtCore.Qt.Key.Key_Escape:
                self._on_escape()
                return True
        return False


class _DeleteKeys(QtCore.QObject):
    """Claims Delete and Backspace (a Mac's delete key) while focus is in
    the 3D view, ahead of FreeCAD's Delete command, which would remove a
    selected board's object from the document behind the session. A
    claimed shortcut arrives as a plain key press, which this filter
    turns into ``on_delete``."""

    _KEYS = (QtCore.Qt.Key.Key_Delete, QtCore.Qt.Key.Key_Backspace)

    def __init__(
        self, viewer: QtWidgets.QWidget, on_delete: Callable[[], None]
    ) -> None:
        # The viewer is reached through parent() rather than kept: a kept
        # wrapper can outlive its widget (_ViewWidgets).
        super().__init__(viewer)
        self._on_delete = on_delete

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        kind = event.type()
        if kind not in (
            QtCore.QEvent.Type.ShortcutOverride,
            QtCore.QEvent.Type.KeyPress,
        ):
            return False
        viewer = self.parent()
        if (
            not isinstance(watched, QtWidgets.QWidget)
            or not isinstance(viewer, QtWidgets.QWidget)
            or not (watched is viewer or viewer.isAncestorOf(watched))
        ):
            return False
        if cast("QtGui.QKeyEvent", event).key() not in self._KEYS:
            return False
        event.accept()
        if kind == QtCore.QEvent.Type.KeyPress:
            self._on_delete()
        return True


class _UnitsObserver:
    """Reports a change to the unit system lengths are shown in: the
    document's ``UnitSystem``, which the status bar's unit menu sets, or
    Preferences' Units group. Either changes before FreeCAD applies the new
    schema, so ``on_change`` must run later."""

    def __init__(self, doc: FreeCAD.Document, on_change: Callable[[], None]) -> None:
        self._doc = doc
        self._on_change = on_change

    def slotChangedDocument(self, doc: FreeCAD.Document, prop: str) -> None:
        if doc is self._doc and prop == "UnitSystem":
            self._on_change()

    def onChange(self, _group: object, _reason: str) -> None:
        self._on_change()


def label_metrics(size_pt: int) -> QtGui.QFontMetrics:
    """The metrics SoDatumLabel lays out a ``size_pt`` label with, in
    device pixels (FreeCAD 1.1's ``SoDatumLabel::drawImage``)."""
    return QtGui.QFontMetrics(QtGui.QFont(_LABEL_FONT, size_pt))


def padlock_spaces(size_pt: int, ratio: float) -> int:
    """How many spaces leave room in a ``size_pt`` label, drawn at device
    pixel ratio ``ratio``, for a padlock with a gap on each side."""
    space_px = max(1, label_metrics(size_pt).horizontalAdvance(" "))
    return math.ceil((_PADLOCK_PX + 2 * _PADLOCK_GAP_PX) * ratio / space_px)


class _ViewportGeometry(QtCore.QObject):
    """Reports, on the next event-loop pass, a resize of the 3D view's
    viewport or a move to a screen of another device pixel ratio. Both move
    every projected point without moving the camera, as moving the window
    to another display does. The pass lets Coin take the new size first."""

    _KINDS = (QtCore.QEvent.Type.Resize, QtCore.QEvent.Type.DevicePixelRatioChange)

    def __init__(
        self, viewport: QtWidgets.QWidget, on_change: Callable[[], None]
    ) -> None:
        super().__init__(viewport)
        self._on_change = on_change
        self._queued = False

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        # A resizing window sends a stream of these; one pass serves them all.
        if event.type() in self._KINDS and not self._queued:
            self._queued = True
            QtCore.QTimer.singleShot(0, self._report)
        return False

    def _report(self) -> None:
        self._queued = False
        self._on_change()


# What a left press on the viewport is: one the editor takes for itself
# with its release, one it leaves to the dragger and navigation entirely,
# or one whose click it reads after FreeCAD has handled it.
PressKind = Literal["take", "leave", "click"]

# FreeCAD's add-to-selection modifier, which Qt reports for Command on a Mac.
_ADD_MODIFIER = QtCore.Qt.KeyboardModifier.ControlModifier


class _ViewportClicks(QtCore.QObject):
    """Reads left clicks on the 3D view's viewport before navigation and
    FreeCAD's selection see them. ``on_press`` sorts each press; a press
    taken is consumed with its release, so no board beneath it is picked,
    and a click is reported to ``on_click`` once FreeCAD has handled it,
    with whether it carried FreeCAD's add-to-selection modifier."""

    def __init__(
        self,
        viewport: QtWidgets.QWidget,
        on_press: Callable[[QtCore.QPointF], PressKind],
        on_click: Callable[[QtCore.QPointF, bool], None],
    ) -> None:
        super().__init__(viewport)
        self._on_press = on_press
        self._on_click = on_click
        self._press: QtCore.QPointF | None = None
        self._consumed = False

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        kind = event.type()
        if kind not in (
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QEvent.Type.MouseButtonRelease,
        ):
            return False
        mouse = cast("QtGui.QMouseEvent", event)
        if mouse.button() != QtCore.Qt.MouseButton.LeftButton:
            return False
        position = mouse.position()
        if kind == QtCore.QEvent.Type.MouseButtonPress:
            press_kind = self._on_press(position)
            self._consumed = press_kind == "take"
            self._press = position if press_kind == "click" else None
            return self._consumed
        if self._consumed:
            self._consumed = False
            return True
        press, self._press = self._press, None
        if press is None:
            return False
        moved_px = (position - press).manhattanLength()
        if moved_px < QtWidgets.QApplication.startDragDistance():
            adding = bool(mouse.modifiers() & _ADD_MODIFIER)
            # FreeCAD's selection handles this release after the filter.
            QtCore.QTimer.singleShot(0, lambda: self._on_click(position, adding))
        return False


class _BoardGate:
    """A FreeCAD selection gate admitting the unit's boards, and the parts
    it sets aside: refused, a back panel behind every opening shows the
    forbidden cursor over each one. The editor turns a set-aside part's
    pick into the opening under the pointer."""

    def __init__(self, editor: ViewEditor) -> None:
        self._editor = editor

    def allow(self, _doc: object, obj: FreeCAD.DocumentObject, sub: str) -> bool:
        return self._editor.admits(obj.Name, sub)


class _SelectionObserver:
    def __init__(self, editor: ViewEditor) -> None:
        self._editor = editor

    def addSelection(self, doc: str, _obj: str, _sub: str, _point: object) -> None:
        self._editor.freecad_selection_changed(doc)

    def removeSelection(self, doc: str, _obj: str, _sub: str) -> None:
        self._editor.freecad_selection_changed(doc)

    def setSelection(self, doc: str) -> None:
        self._editor.freecad_selection_changed(doc)

    def clearSelection(self, doc: str) -> None:
        self._editor.freecad_selection_changed(doc)


class _SelectionEntry(Protocol):
    """One object of ``FreeCADGui.Selection.getSelectionEx``; the stubs do
    not declare its attributes."""

    ObjectName: str
    SubElementNames: Sequence[str]


@dataclass(frozen=True)
class _Picked:
    """One entry of FreeCAD's selection."""

    # The object it was picked through, and the path below it.
    obj: str
    sub: str
    # The unit's board it names, if any.
    board: str | None
    # Whether it is the whole object rather than one of its elements.
    whole: bool


def select_in_freecad(doc_name: str, names: Sequence[str]) -> None:
    """Make FreeCAD's selection in ``doc_name`` exactly the whole objects
    ``names``, touching it only when it differs."""
    entries = cast(
        "list[_SelectionEntry]", FreeCADGui.Selection.getSelectionEx(doc_name, 0, True)
    )
    current = [
        (entry.ObjectName, tuple(sub for sub in entry.SubElementNames if sub))
        for entry in entries
    ]
    if current == [(name, ()) for name in names]:
        return
    FreeCADGui.Selection.clearSelection()
    for name in names:
        FreeCADGui.Selection.addSelection(doc_name, name)


# How many editors have opened in this process. A camera restore still
# animating after Close gives up once another has opened, so it never moves
# the camera out from under the new editor's turn.
_editors_opened = 0


# Draggers kept from destruction for the life of the process: Coin before
# 4.0.4 crashes deleting the SoCallbackAction a dragger creates the first
# time it is dragged (coin3d/coin#556). One small dragger per session.
KEPT_ALIVE: list[Coin] = []


@dataclass
class _ViewWidgets:
    """The 3D view's Qt widgets, held only while the editor is open: a
    PySide wrapper that outlives its widget is handed back, dead, for the
    next widget made at the same address, and the next Edit Unit then fails
    on it."""

    viewer: QtWidgets.QGraphicsView
    viewport: QtWidgets.QWidget


class ViewEditor:
    """The overlay, camera and input handling of one editing session in
    ``view``. ``on_change`` runs after every edit or selection the editor
    makes, and is expected to call :meth:`rebuild`. :meth:`close` undoes
    every change the editor made to the view, the selection and the
    visibility of objects; a failure while the editor is built closes it
    before the exception propagates."""

    def __init__(
        self, session: Session, view: View3D, on_change: Callable[[], None]
    ) -> None:
        self.session = session
        self.view = view
        self._on_change = on_change
        self._closed = False
        self._doc = session.container.Document
        self._doc_name = self._doc.Name
        viewer = view.graphicsView()
        self._widgets: _ViewWidgets | None = _ViewWidgets(viewer, viewer.viewport())
        self._front = elevation_frame(session.unit)
        self.frame = self._front
        self.overlay = Overlay()
        self._boards: frozenset[str] = frozenset()
        self._aside: frozenset[str] = frozenset()
        self._hidden: list[str] = []
        # What close() undoes, latest first, each with whether it touches the
        # view, which may be gone by then with its document.
        self._installed: list[tuple[Callable[[], object], bool]] = []
        self._camera_sensor: Coin = None
        self._turn_target: FreeCAD.Rotation | None = None
        self._turn_started_s = 0.0
        self._refresh_queued = False
        self._side_queued = False
        self._follow_queued = False
        self.arrow: Arrow | None = None
        self._dragging = False
        self._drag_failure_reported = False
        self.preview: Rect | None = None
        self._preview_direction: SplitDirection | None = None
        self.field: DimensionField | None = None
        self._field_host: QtWidgets.QFrame | None = None
        self._field_anchor: tuple[float, float] | None = None
        self._field_region: str | None = None
        self._field_applied = False
        self._add_anchor: tuple[float, float] | None = None
        # One padlock per lockable dimension, reused across rebuilds, which a
        # drag runs at every step; never shrunk, so it holds as many as were
        # ever shown at once. Button i is the padlock of _padlock_labels[i].
        self.padlocks: list[QtWidgets.QToolButton] = []
        self._padlock_labels: list[DimensionLabel] = []
        self.held: HeldPadlock | None = None
        self.saved_camera = view.getCamera()
        self._saved_orientation = view.getCameraOrientation()
        global _editors_opened
        _editors_opened += 1
        try:
            self._open()
        except BaseException:
            self.close(restore_camera=False)
            raise

    @property
    def _viewer(self) -> QtWidgets.QGraphicsView:
        widgets = self._widgets
        assert widgets is not None, "the editor is closed"
        return widgets.viewer

    @property
    def viewport(self) -> QtWidgets.QWidget:
        widgets = self._widgets
        assert widgets is not None, "the editor is closed"
        return widgets.viewport

    def _view_gone(self) -> bool:
        """Whether the 3D view was closed under the editor. FreeCAD's view
        object raises once its view is deleted; the view's widget wrapper
        cannot tell, since PySide does not learn of a widget FreeCAD
        destroys."""
        try:
            self.view.getSize()
        except RuntimeError:
            return True
        return False

    def _stood_down(self) -> bool:
        """Close the editor when its 3D view was closed under it, as an extra
        view of the document can be, and say whether it did. The panel
        stays open, editing the unit's size, until its Close."""
        if not self._view_gone():
            return False
        self.close(restore_camera=False)
        return True

    # Setup and teardown

    def _open(self) -> None:
        ratio = self._viewer.devicePixelRatioF()
        font_px = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/View").GetInt(
            "EditSketcherFontSize",
            QtGui.QFontInfo(QtWidgets.QApplication.font()).pixelSize(),
        )
        size_pt = label_size_pt(
            font_px, ratio, self._viewer.screen().logicalDotsPerInchX()
        )
        self.style: Style = view_style(size_pt, padlock_spaces(size_pt, ratio))
        self._label_metrics = label_metrics(size_pt)
        # The ratio the labels were sized for, which their measured text
        # divides back out.
        self._label_ratio = ratio
        self._outer_row_mm = self._outer_row_spacing_mm()
        self._padlock_icons = self._draw_padlock_icons(ratio)
        self.root: Coin = coin.SoSeparator()
        self._frame_transform: Coin = coin.SoTransform()
        self._drawing: Coin = coin.SoSeparator()
        self.root.addChild(self._frame_transform)
        self.root.addChild(self._drawing)
        self._build_dragger()
        self.marker = PointMarker()
        self.root.addChild(self.marker.root)
        self._draw_marker(ratio)
        scene_graph = self.view.getSceneGraph()
        scene_graph.addChild(self.root)
        self._installed.append((lambda: scene_graph.removeChild(self.root), True))

        parent = self._viewer.parentWidget()
        self.add_bar = AddBar(
            parent, self.style.selected_rgb, self._add_board, self._hover_add
        )
        self._installed.append((self.add_bar.deleteLater, True))
        self._installed.append((self.add_bar.hide, True))
        self.board_padlock = _padlock_button(parent, self._unlock_held)
        self.board_padlock.setIcon(self._padlock_icons[True])
        text = "Unlock the openings holding this board"
        self.board_padlock.setToolTip(text)
        self.board_padlock.setAccessibleName(text)
        self._installed.append((self.board_padlock.deleteLater, True))
        self._installed.append((self.board_padlock.hide, True))

        viewport = self.viewport
        clicks = _ViewportClicks(viewport, self._sort_press, self._click)
        viewport.installEventFilter(clicks)
        self._installed.append((clicks.deleteLater, True))
        self._installed.append((lambda: viewport.removeEventFilter(clicks), True))
        geometry = _ViewportGeometry(viewport, self._refit)
        viewport.installEventFilter(geometry)
        self._installed.append((geometry.deleteLater, True))
        self._installed.append((lambda: viewport.removeEventFilter(geometry), True))
        app = cast("QtCore.QCoreApplication", QtCore.QCoreApplication.instance())
        keys = _DeleteKeys(
            self._viewer, lambda: QtCore.QTimer.singleShot(0, self._delete_selected)
        )
        app.installEventFilter(keys)
        self._installed.append((keys.deleteLater, True))
        self._installed.append((lambda: app.removeEventFilter(keys), False))

        units = _UnitsObserver(
            self._doc, lambda: QtCore.QTimer.singleShot(0, self._units_changed)
        )
        FreeCAD.addDocumentObserver(units)
        self._installed.append((lambda: FreeCAD.removeDocumentObserver(units), False))
        units_params = FreeCAD.ParamGet(_UNITS_PARAMS)
        units_params.Attach(units)
        self._installed.append((lambda: units_params.Detach(units), False))

        FreeCADGui.Selection.clearSelection()
        gate = _BoardGate(self)
        observer = _SelectionObserver(self)
        FreeCADGui.Selection.addSelectionGate(gate)
        self._installed.append((FreeCADGui.Selection.removeSelectionGate, False))
        FreeCADGui.Selection.addObserver(observer)
        self._installed.append(
            (lambda: FreeCADGui.Selection.removeObserver(observer), False)
        )
        self._installed.append((FreeCADGui.Selection.clearSelection, False))

        self.rebuild()
        self._turn_camera()

    def _build_dragger(self) -> None:
        """The one dragger of the session, moved and shown or hidden per
        selection and never rebuilt (see :data:`KEPT_ALIVE`)."""
        self.dragger: Coin = coin.SoTranslate1Dragger()
        # A node may fill only one part of a dragger.
        for part in ("translator", "translatorActive"):
            self.dragger.setPartAsDefault(part, arrow_geometry(self.style.selected_rgb))
        self._dragger_transform: Coin = coin.SoTransform()
        self._dragger_switch: Coin = coin.SoSwitch()
        self._dragger_switch.ref()
        group = coin.SoSeparator()
        pick_style = coin.SoPickStyle()
        pick_style.style = coin.SoPickStyle.SHAPE
        group.addChild(pick_style)
        group.addChild(self._dragger_transform)
        group.addChild(self.dragger)
        self._dragger_switch.addChild(group)
        self._dragger_switch.whichChild.setValue(coin.SO_SWITCH_NONE)
        holder = coin.SoSeparator()
        holder.addChild(self._dragger_switch)
        self.root.addChild(holder)
        for kind, callback in (
            ("addStartCallback", self._drag_started),
            ("addMotionCallback", self._drag_moved),
            ("addFinishCallback", self._drag_finished),
        ):
            handle = self.view.addDraggerCallback(self.dragger, kind, callback)
            self._installed.append(
                (
                    lambda kind=kind, handle=handle: self.view.removeDraggerCallback(
                        self.dragger, kind, handle
                    ),
                    True,
                )
            )
        self._installed.append((self._release_dragger, False))

    def _release_dragger(self) -> None:
        if coin_destroys_draggers_safely():
            self._dragger_switch.unref()
        else:
            KEPT_ALIVE.append(self._dragger_switch)

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def turning(self) -> bool:
        """Whether the camera is still turning toward the unit, before the
        fit that ends the turn."""
        return self._turn_target is not None

    def close(self, restore_camera: bool = True) -> None:
        """Remove the overlay, callbacks, filters, selection gate and
        observer, put back every object the editor hid, and, when
        ``restore_camera`` and the Sketcher's "Restore camera position after
        editing" preference are both set, turn the camera back. Safe to call
        twice."""
        if self._closed:
            return
        self._closed = True
        view_alive = not self._view_gone()
        self._close_field()
        if self._doc_name in FreeCAD.listDocuments():
            self.set_hide_others(False)
        if self._camera_sensor is not None:
            self._camera_sensor.detach()
            self._camera_sensor = None
        while self._installed:
            undo, touches_view = self._installed.pop()
            if touches_view and not view_alive:
                continue
            try:
                undo()
            except RuntimeError:
                # A widget it would touch went with the view's window.
                pass
        self._widgets = None
        restore = FreeCAD.ParamGet(_RESTORE_CAMERA_PARAM).GetBool("RestoreCamera", True)
        if restore_camera and restore and view_alive:
            _restore_camera(self.view, self._saved_orientation, self.saved_camera)

    # The camera

    def _turn_camera(self) -> None:
        """Turn the camera to face the unit's front as the Sketcher turns it
        to a sketch (``ViewProviderSketch::setEditViewer``): orthographic,
        pulled back first when the face would land in front of it, rotating
        about the focal point, animated when FreeCAD animates navigation;
        then fit the unit, which jumps."""
        self.view.setCameraType("Orthographic")
        target = self._placement(self._front).Rotation
        camera = self.view.getCameraNode()
        orientation = FreeCAD.Rotation(*camera.orientation.getValue().getValue())
        current_dir = orientation.multVec(FreeCAD.Vector(0, 0, -1))
        new_dir = target.multVec(FreeCAD.Vector(0, 0, -1))
        position_mm = FreeCAD.Vector(*camera.position.getValue().getValue())
        focal_mm = float(camera.focalDistance.getValue())
        focal_point_mm = position_mm + current_dir * focal_mm
        turned_position_mm = focal_point_mm - new_dir * focal_mm
        face_mm = self._placement(self._front).Base
        distance_mm = (face_mm - turned_position_mm).dot(new_dir)
        if distance_mm < 0:
            focal_mm = focal_mm - distance_mm + 5
            pulled_mm = focal_point_mm - current_dir * focal_mm
            camera.position.setValue(pulled_mm.x, pulled_mm.y, pulled_mm.z)
            camera.focalDistance.setValue(focal_mm)
        self._turn_target = target
        self._turn_started_s = time.monotonic()
        # Followed from the start, so the in-view widgets keep to their
        # anchors through the turn.
        self._watch_camera()
        self.view.setCameraOrientation(target)
        QtCore.QTimer.singleShot(_POLL_MS, self._poll_turn)

    def _poll_turn(self) -> None:
        target = self._turn_target
        if self._closed or target is None or self._stood_down():
            return
        reached = self.view.getCameraOrientation().isSame(target, 1e-6)
        if not reached and time.monotonic() - self._turn_started_s < _TURN_TIMEOUT_S:
            QtCore.QTimer.singleShot(_POLL_MS, self._poll_turn)
            return
        self._turn_target = None
        self._fit(target)

    def _fit(self, orientation: FreeCAD.Rotation) -> None:
        unit = self.session.unit
        frame = self._front
        width_mm = unit.size_mm.component_mm(frame.horizontal.component_index)
        height_mm = unit.size_mm.component_mm(frame.vertical.component_index)
        placement = self._placement(frame)
        center_mm = placement.multVec(FreeCAD.Vector(width_mm / 2, height_mm / 2, 0))
        toward = placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
        camera = self.view.getCameraNode()
        size = unit.size_mm
        # Far enough back that the whole unit lies in front of the camera.
        distance_mm = max(
            float(camera.focalDistance.getValue()),
            2 * math.hypot(size.x_mm, size.y_mm, size.z_mm),
        )
        position_mm = center_mm + toward * distance_mm
        camera.orientation.setValue(_sbrotation(orientation))
        camera.position.setValue(position_mm.x, position_mm.y, position_mm.z)
        camera.focalDistance.setValue(distance_mm)
        camera.height.setValue(self._fit_height_mm(unit, frame))
        # Only now does the view have the size the panel opening left it.
        spacing_mm = self._outer_row_spacing_mm()
        if spacing_mm != self._outer_row_mm:
            self._outer_row_mm = spacing_mm
            self.rebuild()

    def _outer_row_spacing_mm(self) -> float:
        """How far apart the rows of dimensions outside the unit sit: at the
        fitted view's scale, a row of text clears the next. Held from the fit
        on, so resizing the unit moves its outer dimensions only with the
        faces they stand off from."""
        row_px = self._label_metrics.height() / self._label_ratio + _ROW_GAP_PX
        unit = self.session.unit
        return (
            row_px
            * self._fit_height_mm(unit, elevation_frame(unit))
            / max(1, self.viewport.height())
        )

    def _fit_height_mm(self, unit: Unit, frame: ElevationFrame) -> float:
        """The camera height that shows ``unit``'s face in ``frame`` with
        room around it for the dimensions outside it."""
        width_mm = unit.size_mm.component_mm(frame.horizontal.component_index)
        height_mm = unit.size_mm.component_mm(frame.vertical.component_index)
        margin_mm = _FIT_MARGIN_FRACTION * max(width_mm, height_mm)
        width_px, height_px = self.view.getSize()
        aspect = width_px / height_px if height_px else 1.0
        return max(height_mm + 2 * margin_mm, (width_mm + 2 * margin_mm) / aspect)

    def _watch_camera(self) -> None:
        if self._camera_sensor is not None:
            self._camera_sensor.detach()
        self._camera_sensor = coin.SoNodeSensor(self._camera_moved, None)
        self._camera_sensor.attach(self.view.getCameraNode())

    def _camera_moved(self, _data: object, _sensor: object) -> None:
        if self._closed:
            return
        self._place_widgets()
        if self._dragging or self._side_queued:
            return
        camera = self.view.getCameraNode()
        orientation = FreeCAD.Rotation(*camera.orientation.getValue().getValue())
        toward_camera = orientation.multVec(FreeCAD.Vector(0, 0, 1))
        back = toward_camera.dot(self._front_normal()) < 0
        if back != (self.frame.side == "back"):
            # The sensor fires mid-render; the scene changes afterward.
            self._side_queued = True
            QtCore.QTimer.singleShot(0, self._switch_side)

    def _switch_side(self) -> None:
        self._side_queued = False
        if self._closed or self._dragging:
            return
        self._close_field()
        self.rebuild()

    def _camera_back(self) -> bool:
        camera = self.view.getCameraNode()
        orientation = FreeCAD.Rotation(*camera.orientation.getValue().getValue())
        toward_camera = orientation.multVec(FreeCAD.Vector(0, 0, 1))
        return toward_camera.dot(self._front_normal()) < 0

    # Frames

    def _placement(self, frame: ElevationFrame) -> FreeCAD.Placement:
        """``frame`` as a placement in document coordinates."""
        local = FreeCAD.Placement(FreeCAD.Matrix(*frame.matrix()))
        return container_placement(self.session.container).multiply(local)

    def _front_normal(self) -> FreeCAD.Vector:
        return self._placement(self._front).Rotation.multVec(FreeCAD.Vector(0, 0, 1))

    def to_document(
        self, h_mm: float, v_mm: float, z_mm: float = 0.0
    ) -> FreeCAD.Vector:
        """The document point at elevation ``(h, v, z)`` on the face the
        overlay is drawn on."""
        return self._placement(self.frame).multVec(FreeCAD.Vector(h_mm, v_mm, z_mm))

    def _device_point(self, position: QtCore.QPointF) -> tuple[int, int]:
        """A viewport position in the device pixels, y up, that FreeCAD's
        view takes."""
        ratio = self._viewer.devicePixelRatioF()
        height_px = self.view.getSize()[1]
        return (
            round(position.x() * ratio),
            round(height_px - position.y() * ratio - 1),
        )

    def _logical_point(self, point_mm: FreeCAD.Vector) -> QtCore.QPointF:
        x_px, y_px = self.view.getPointOnViewport(point_mm)
        ratio = self._viewer.devicePixelRatioF()
        height_px = self.view.getSize()[1]
        return QtCore.QPointF(x_px / ratio, (height_px - y_px - 1) / ratio)

    # Drawing

    def rebuild(self) -> None:
        """Redraw from the session on the face the camera sees, and place the
        arrow, the add buttons and the field; the arrow stays put during a
        drag."""
        if self._closed or self._stood_down():
            return
        session = self.session
        unit = session.unit
        self._front = elevation_frame(unit)
        back = self._camera_sensor is not None and self._camera_back()
        self.frame = elevation_frame(unit, "back" if back else "front")
        self._boards = board_ids(unit)
        self._aside = frozenset(entry.name for entry in session.untagged)
        placement = self._placement(self.frame)
        base_mm = placement.Base
        self._frame_transform.translation.setValue(base_mm.x, base_mm.y, base_mm.z)
        self._frame_transform.rotation.setValue(_sbrotation(placement.Rotation))
        selected = session.selected_id
        self.overlay = plan_overlay(
            unit, session.spaces, self.frame, selected, self._outer_row_mm
        )
        self._update_preview()
        self._drawing.removeAllChildren()
        self._drawing.addChild(
            drawing_node(
                self.overlay, self.frame, self.style, self._front_normal(), self.preview
            )
        )
        self.marker.place(self.frame.from_unit(fixed_point_mm(unit)))
        if not self._dragging:
            self._place_arrow()
            self._place_add_bar()
        self._update_padlocks()
        self._place_widgets()

    def _update_preview(self) -> None:
        direction = self._preview_direction
        selected = self.session.selected_id
        if direction is None or selected is None or not self.session.can_split():
            self.preview = None
            return
        axis = (
            self.frame.horizontal if direction == "horizontal" else self.frame.vertical
        )
        self.preview = split_preview(self.session.unit, self.frame, selected, axis)

    def _place_arrow(self) -> None:
        session = self.session
        selected = session.selected_id
        arrow = (
            arrow_for(session.unit, session.spaces, self.frame, selected)
            if selected is not None and session.can_merge()
            else None
        )
        self.arrow = arrow
        self.held = (
            held_padlock(session.unit, session.spaces, self.frame, selected)
            if selected is not None and session.can_merge()
            else None
        )
        if self.held is None:
            self.board_padlock.hide()
        else:
            self.board_padlock.show()
            self.board_padlock.raise_()
        if arrow is None:
            self._dragger_switch.whichChild.setValue(coin.SO_SWITCH_NONE)
            return
        h_mm, v_mm = arrow.at_mm
        self._dragger_transform.translation.setValue(
            h_mm, v_mm, self.frame.z_sign * 4 * LIFT_MM
        )
        angle = math.pi / 2 if arrow.vertical else 0.0
        self._dragger_transform.rotation.setValue(coin.SbVec3f(0, 0, 1), angle)
        scale = arrow.length_mm / 2
        self._dragger_transform.scaleFactor.setValue(scale, scale, scale)
        self.dragger.translation.setValue(0, 0, 0)
        self._dragger_switch.whichChild.setValue(0)

    def _place_add_bar(self) -> None:
        session = self.session
        selected = session.selected_id
        if selected is None or not session.can_split() or self._dragging:
            self.add_bar.hide()
            self._add_anchor = None
            self._preview_direction = None
            return
        self._add_anchor = self.frame.rect(session.spaces[selected]).center_mm
        self.add_bar.show()
        self.add_bar.adjustSize()
        self.add_bar.raise_()

    def _place_widgets(self) -> None:
        if self._add_anchor is not None:
            self._move_to(self.add_bar, self._add_anchor)
        if self._field_host is not None and self._field_anchor is not None:
            if Shiboken.isValid(self._field_host):
                self._move_to(self._field_host, self._field_anchor)
        metrics = self._label_metrics
        lead_px = metrics.horizontalAdvance(" " * self.style.padlock_spaces)
        for button, label in zip(self.padlocks, self._padlock_labels, strict=False):
            text = label_string(label, self.style)
            width_px = metrics.horizontalAdvance(text)
            # From the first digit's ink rather than its origin: a "1" stands
            # well clear of its own.
            bearing_px = metrics.leftBearing(text.lstrip()[:1] or " ")
            # The text reads left to right, or upward along a vertical line,
            # so its first digit faces the padlock's right edge or its top.
            before_px = (
                (width_px / 2 - lead_px - bearing_px) / self._label_ratio
                + _PADLOCK_GAP_PX
                + _PADLOCK_PX / 2
            )
            shift_px = (
                QtCore.QPointF(-before_px, 0.0)
                if label.horizontal
                else QtCore.QPointF(0.0, before_px)
            )
            # A padlock off the viewport hides rather than float over the
            # panels around the view.
            button.setVisible(self._move_to(button, label.text_at_mm, shift_px))
        if self.held is not None:
            self.board_padlock.setVisible(
                self._move_to(self.board_padlock, self.held.at_mm)
            )

    def _move_to(
        self,
        widget: QtWidgets.QWidget,
        anchor_mm: tuple[float, float],
        shift_px: QtCore.QPointF | None = None,
    ) -> bool:
        """Center ``widget``, a child of the view's parent, on the elevation
        point ``anchor_mm``, moved by ``shift_px`` logical pixels. Returns
        whether that center lies on the viewport."""
        point = self._logical_point(self.to_document(*anchor_mm))
        if shift_px is not None:
            point += shift_px
        local = point.toPoint()
        parent = widget.parentWidget()
        # From the viewport, whose coordinates _logical_point gives: the
        # QGraphicsView's frame can offset it.
        at = self.viewport.mapTo(parent, local) if parent is not None else local
        widget.move(at.x() - widget.width() // 2, at.y() - widget.height() // 2)
        return self.viewport.rect().contains(local)

    def _queue_change(self) -> None:
        """Run :attr:`on_change` once the Coin callback being handled has
        returned."""
        if not self._refresh_queued:
            self._refresh_queued = True
            QtCore.QTimer.singleShot(0, self._run_queued_change)

    def _run_queued_change(self) -> None:
        self._refresh_queued = False
        if not self._closed:
            self._on_change()

    def history_moved(self) -> None:
        """Drop what an Undo, a Redo or a change made elsewhere left stale,
        before the redraw that follows."""
        if self._closed or self._stood_down():
            return
        self._close_field()
        self._preview_direction = None

    # Hiding other objects

    def set_hide_others(self, hide: bool) -> None:
        """Hide every visible object outside the unit, or show again exactly
        those this hid. Through the view objects, so neither the undo
        history nor the objects' saved visibility changes."""
        doc = self._doc
        if hide and self._closed:
            return
        if hide and not self._hidden:
            container = self.session.container
            keep = {container.Name}
            keep.update(obj.Name for obj in container.OutListRecursive)
            keep.update(obj.Name for obj in container.InListRecursive)
            for obj in doc.Objects:
                view_object = cast(
                    "_ViewObject | None", getattr(obj, "ViewObject", None)
                )
                if obj.Name in keep or view_object is None:
                    continue
                if view_object.Visibility:
                    view_object.Visibility = False
                    self._hidden.append(obj.Name)
        elif not hide and self._hidden:
            for name in self._hidden:
                obj = doc.getObject(name)
                view_object = cast(
                    "_ViewObject | None", getattr(obj, "ViewObject", None)
                )
                if view_object is not None:
                    view_object.Visibility = True
            self._hidden = []

    # Picking

    def admits(self, obj_name: str, sub_name: str) -> bool:
        """Whether FreeCAD may select or preselect what ``obj_name`` and
        ``sub_name`` name: one of the unit's boards or set-aside parts."""
        names = _path_names(obj_name, sub_name)
        return any(name in self._boards or name in self._aside for name in names)

    def _board_in(self, obj_name: str, sub_name: str) -> str | None:
        for name in reversed(_path_names(obj_name, sub_name)):
            if name in self._boards:
                return name
        return None

    def freecad_selection_changed(self, doc_name: str) -> None:
        """FreeCAD's selection changed, in the tree, the view or a script.
        Runs inside FreeCAD's selection change, so following it waits."""
        if self._closed or doc_name not in (self._doc_name, ""):
            return
        if not self._follow_queued:
            self._follow_queued = True
            QtCore.QTimer.singleShot(0, self._follow_freecad)

    def _freecad_entries(self) -> list[_Picked]:
        """Each object and each element in FreeCAD's selection in the unit's
        document, one per entry: a whole object selected beside one of its
        own faces is two."""
        # Single entries: grouped by object, a whole object's own entry
        # disappears behind its elements'.
        entries = cast(
            "list[_SelectionEntry]",
            FreeCADGui.Selection.getSelectionEx(self._doc_name, 0, True),
        )
        picked: list[_Picked] = []
        for entry in entries:
            for sub in entry.SubElementNames or ("",):
                picked.append(
                    _Picked(
                        entry.ObjectName,
                        sub,
                        self._board_in(entry.ObjectName, sub),
                        not sub.rsplit(".", 1)[-1],
                    )
                )
        return picked

    def _follow_freecad(self) -> None:
        """Make the session's selection FreeCAD's whenever FreeCAD's holds
        only the unit's boards, and hold each of them in FreeCAD whole.

        A board held whole beside one of its own elements was Ctrl-clicked
        while selected: FreeCAD adds the element it does not find selected
        rather than removing the whole board, so that board leaves the
        selection. An emptied selection drops a board selection; a region
        selection stays, since FreeCAD's selection never holds a region.
        """
        self._follow_queued = False
        if self._closed:
            return
        entries = self._freecad_entries()
        if any(entry.board is None for entry in entries):
            # A part the unit sets aside: _click turns it into the opening.
            return
        whole = {entry.board for entry in entries if entry.whole}
        parts = {entry.board for entry in entries if not entry.whole}
        boards = [
            board
            for board in dict.fromkeys(entry.board for entry in entries)
            if board is not None and board not in whole & parts
        ]
        session = self.session
        if parts:
            select_in_freecad(self._doc_name, boards)
        if not boards:
            if session.selected_boards:
                self.select(None)
            return
        if len(boards) == 1:
            if boards[0] != session.selected_id:
                self.select(boards[0])
            return
        if tuple(boards) != session.selected_boards:
            session.select_boards(boards)
            self._on_change()

    def select(self, node_id: str | None) -> None:
        """Select ``node_id`` in the session, and in FreeCAD's selection when
        it is a board, whole; anything else clears FreeCAD's selection."""
        if self._closed:
            return
        self.session.select(node_id)
        board = node_id if node_id in self._boards else None
        select_in_freecad(self._doc_name, [] if board is None else [board])
        self._on_change()

    def select_boards(self, board_ids: Sequence[str]) -> None:
        """Select exactly the boards ``board_ids``, in the session and, whole,
        in FreeCAD's selection."""
        if self._closed:
            return
        self.session.select_boards(board_ids)
        select_in_freecad(self._doc_name, list(dict.fromkeys(board_ids)))
        self._on_change()

    def _click(self, position: QtCore.QPointF, adding: bool) -> None:
        """A click FreeCAD has handled. On a board the session takes
        FreeCAD's selection, so an add-to-selection gesture adds the board.
        Elsewhere, an ``adding`` click keeps a board selection, as FreeCAD
        keeps it for one on empty space, and only takes a part the unit sets
        aside back out of FreeCAD's selection; any other click selects the
        opening there, or nothing. FreeCAD knows no openings, so this is the
        one place the editor reads a modifier: under Inventor navigation,
        where FreeCAD selects only on Ctrl-click, a plain click is what
        reaches an opening."""
        if self._closed:
            return
        self._close_field()
        device = self._device_point(position)
        info = self.view.getObjectInfo(device)
        if info is not None:
            board = self._board_in(
                str(info.get("Object", "")), str(info.get("SubName", "") or "")
            )
            if board is not None:
                self._follow_freecad()
                return
        entries = self._freecad_entries()
        if adding and any(entry.board is not None for entry in entries):
            for entry in entries:
                if entry.board is None:
                    FreeCADGui.Selection.removeSelection(
                        self._doc_name, entry.obj, entry.sub
                    )
            return
        self.select(self._region_at(device))

    def _region_at(self, device: tuple[int, int]) -> str | None:
        near_mm, far_mm = self.view.projectPointToLine(device)
        inverse = self._placement(self.frame).inverse()
        # The pointer's ray in elevation coordinates, met with z = 0.
        a_mm = inverse.multVec(near_mm)
        b_mm = inverse.multVec(far_mm)
        if abs(b_mm.z - a_mm.z) < 1e-9:
            return None
        t = -a_mm.z / (b_mm.z - a_mm.z)
        h_mm = a_mm.x + t * (b_mm.x - a_mm.x)
        v_mm = a_mm.y + t * (b_mm.y - a_mm.y)
        return region_at(self.session.unit, self.session.spaces, self.frame, h_mm, v_mm)

    def _project(self, h_mm: float, v_mm: float) -> tuple[float, float]:
        x_px, y_px = self.view.getPointOnViewport(self.to_document(h_mm, v_mm))
        return (float(x_px), float(y_px))

    def _on_arrow(self, device: tuple[int, int]) -> bool:
        arrow = self.arrow
        if arrow is None:
            return False
        h_mm, v_mm = arrow.at_mm
        half_mm = arrow.length_mm / 2
        ends = (
            ((h_mm, v_mm - half_mm), (h_mm, v_mm + half_mm))
            if arrow.vertical
            else ((h_mm - half_mm, v_mm), (h_mm + half_mm, v_mm))
        )
        (x0_px, y0_px), (x1_px, y1_px) = (self._project(*end) for end in ends)
        x_px, y_px = device
        dx_px, dy_px = x1_px - x0_px, y1_px - y0_px
        length_sq_px2 = dx_px * dx_px + dy_px * dy_px
        # How far along the arrow the point nearest the press lies.
        t = (
            0.0
            if length_sq_px2 == 0
            else max(
                0.0,
                min(
                    1.0,
                    ((x_px - x0_px) * dx_px + (y_px - y0_px) * dy_px) / length_sq_px2,
                ),
            )
        )
        return (
            math.hypot(x_px - (x0_px + t * dx_px), y_px - (y0_px + t * dy_px))
            <= _ARROW_HIT_PX
        )

    def _sort_press(self, position: QtCore.QPointF) -> PressKind:
        """A press on the drag arrow is the dragger's; one on a dimension's
        text opens that dimension's field."""
        if self._closed:
            return "leave"
        device = self._device_point(position)
        if self._on_arrow(device):
            return "leave"
        label = label_at(self.overlay.labels, self._project, *device)
        if label is None:
            return "click"
        QtCore.QTimer.singleShot(0, lambda: self.open_field(label))
        return "take"

    # The floating size field

    def open_field(self, label: DimensionLabel) -> None:
        """Select ``label``'s region and open a size field on its text."""
        if self._closed:
            return
        self._close_field()
        self.select(label.region_id)
        measurement = self.session.selected_measurement()
        if measurement is None:
            return
        field = DimensionField(
            self.session.container,
            FIELD_PROPERTIES["opening"],
            self._field_size,
            report_error,
        )
        field.show_mm(measurement.size_mm)
        # A layout reparents the quantity widget safely; setParent on the
        # widget itself destroys it at once.
        host = QtWidgets.QFrame(self._viewer.parentWidget())
        layout = QtWidgets.QHBoxLayout(host)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(field.widget)
        keys = _FieldKeys(host, lambda: QtCore.QTimer.singleShot(0, self._close_field))
        field.widget.installEventFilter(keys)
        field.line_edit.installEventFilter(keys)
        self.field = field
        self._field_host = host
        self._field_region = label.region_id
        self._field_anchor = label.text_at_mm
        self._field_applied = False
        host.show()
        host.adjustSize()
        host.raise_()
        self._place_widgets()
        field.line_edit.setFocus()
        field.line_edit.selectAll()

    def _field_size(self, size_mm: float) -> None:
        # Return applies, then closing's focus-out finishes the same edit
        # again; after a refusal the value still differs, so without this
        # the refusal would be reported twice.
        if self.field is None or self._field_applied:
            return
        self._field_applied = True
        region = self._field_region
        if region is not None:
            self.session.select(region)
        failure = self.session.set_size(size_mm)
        if failure is not None:
            report_error(failure.message)
        # Deleting the widget inside its own event handler crashes Qt.
        QtCore.QTimer.singleShot(0, self._close_field)
        self._on_change()

    def _close_field(self) -> None:
        host = self._field_host
        self.field = None
        self._field_host = None
        self._field_anchor = None
        self._field_region = None
        if host is not None and Shiboken.isValid(host):
            host.hide()
            host.deleteLater()

    @property
    def field_host(self) -> QtWidgets.QFrame | None:
        return self._field_host

    # Padlocks

    def _draw_padlock_icons(self, ratio: float) -> dict[bool, QtGui.QIcon]:
        """The closed and open padlock icons, keyed by locked, drawn at the
        device pixel ratio ``ratio``."""
        self._icon_ratio = ratio
        return {
            locked: _padlock_icon(
                locked,
                ratio,
                self.style.label_rgb("locked" if locked else "unlocked"),
            )
            for locked in (True, False)
        }

    def _draw_marker(self, ratio: float) -> None:
        """Give the fixed point marker its image drawn at the device pixel
        ratio ``ratio``: Coin draws an image's pixels one to one."""
        image = marker_image(ratio, self.style.marker_rgb)
        self.marker_image = image
        pixels = bytes(image.constBits())
        stride = image.bytesPerLine()
        # Coin's rows run bottom to top, Qt's top to bottom.
        rows = [
            pixels[start : start + stride] for start in range(0, len(pixels), stride)
        ]
        self.marker.set_image(image.width(), image.height(), b"".join(reversed(rows)))

    def _units_changed(self) -> None:
        if self._closed or self._stood_down():
            return
        self.rebuild()

    def _refit(self) -> None:
        """Place the widgets over the view again, after its viewport resized
        or moved to another screen, redrawing their icons when the device
        pixel ratio they were drawn at is no longer the view's."""
        if self._closed or self._stood_down():
            return
        ratio = self._viewer.devicePixelRatioF()
        if ratio != self._icon_ratio:
            self._padlock_icons = self._draw_padlock_icons(ratio)
            self.board_padlock.setIcon(self._padlock_icons[True])
            self.add_bar.draw_icons(ratio)
            self._update_padlocks()
            self._draw_marker(ratio)
        self._place_widgets()

    def _update_padlocks(self) -> None:
        """Give each lockable dimension a padlock from the pool, growing it
        only when more are shown at once than ever before, and hide the
        rest."""
        labels = [label for label in self.overlay.labels if label.lockable]
        parent = self._viewer.parentWidget()
        while len(self.padlocks) < len(labels):
            button = _padlock_button(
                parent, _bind_index(self._toggle_lock, len(self.padlocks))
            )
            self.padlocks.append(button)
            self._installed.append((button.deleteLater, True))
            self._installed.append((button.hide, True))
        self._padlock_labels = labels
        for button, label in zip(self.padlocks, labels, strict=False):
            locked = label.color == "locked"
            text = "Unlock this opening" if locked else "Lock this opening"
            icon = self._padlock_icons[locked]
            if button.icon().cacheKey() != icon.cacheKey():
                button.setIcon(icon)
            if button.toolTip() != text:
                button.setToolTip(text)
                button.setAccessibleName(text)
            button.show()
            button.raise_()
        for button in self.padlocks[len(labels) :]:
            button.hide()

    def padlock_for(self, region_id: str) -> QtWidgets.QToolButton | None:
        """The padlock on ``region_id``'s dimension, or ``None`` when its
        dimension has none or is not drawn."""
        for button, label in zip(self.padlocks, self._padlock_labels, strict=False):
            if label.region_id == region_id:
                return button
        return None

    def _toggle_lock(self, index: int) -> None:
        if self._closed or index >= len(self._padlock_labels):
            return
        label = self._padlock_labels[index]
        self._close_field()
        failure = self.session.set_lock(label.region_id, label.color == "unlocked")
        if failure is not None:
            report_error(failure.message)
        self._on_change()

    def _unlock_held(self) -> None:
        held = self.held
        if self._closed or held is None:
            return
        self._close_field()
        failure = self.session.unlock_holders(held.board_id)
        if failure is not None:
            report_error(failure.message)
        self._on_change()

    # The add buttons

    def _hover_add(self, direction: SplitDirection | None) -> None:
        if direction != self._preview_direction:
            self._preview_direction = direction
            self.rebuild()

    def _add_board(self, direction: SplitDirection) -> None:
        """Split the selected bay, then select the new board, so its arrow
        is ready to move it."""
        self._preview_direction = None
        before = board_ids(self.session.unit)
        failure = self.session.split(direction)
        if failure is not None:
            report_error(failure.message)
            self._on_change()
            return
        added = board_ids(self.session.unit) - before
        self._boards = board_ids(self.session.unit)
        self.select(next(iter(added)) if len(added) == 1 else None)

    # Delete

    def _delete_selected(self) -> None:
        """Delete the selected board, or every one of several as one step,
        refusing them all when any is refused, as ``Std_Delete`` does."""
        if self._closed:
            return
        session = self.session
        if len(session.selected_boards) > 1:
            failure = session.delete_boards()
        elif session.can_merge():
            failure = session.merge()
        else:
            return
        if failure is not None:
            report_error(failure.message)
            # The selection is as it was; the redraw shows nothing changed.
            self._on_change()
            return
        self._boards = board_ids(session.unit)
        self.select(session.selected_id)

    # Dragging

    def _drag_started(self, _dragger: Coin) -> None:
        arrow = self.arrow
        if arrow is None or self._closed:
            return
        failure = self.session.begin_drag(arrow.board_id, arrow.grab_mm)
        if failure is not None:
            report_error(failure.message)
            return
        self._dragging = True
        self._drag_failure_reported = False
        self.add_bar.hide()

    def _drag_moved(self, dragger: Coin) -> None:
        arrow = self.arrow
        if not self._dragging or arrow is None or not self.session.dragging:
            return
        offset_mm = float(dragger.translation.getValue()[0]) * arrow.length_mm / 2
        failure = self.session.drag_to(dragged_to_mm(arrow, offset_mm))
        if failure is not None and not self._drag_failure_reported:
            self._drag_failure_reported = True
            report_error(failure.message)
        self._queue_change()

    def _drag_finished(self, _dragger: Coin) -> None:
        if not self._dragging:
            return
        self._dragging = False
        self.session.end_drag()
        self._queue_change()

    @property
    def dragging(self) -> bool:
        return self._dragging


def _restore_camera(view: View3D, orientation: FreeCAD.Rotation, camera: str) -> None:
    """Turn the camera back to ``orientation``, animated as the opening turn
    is, then put it exactly where ``camera`` describes, which jumps. Gives
    up once another editor opens or the view is gone."""
    try:
        view.setCameraOrientation(orientation)
    except RuntimeError:
        # FreeCAD's view object raises once its view is deleted.
        return
    started_s = time.monotonic()
    opened = _editors_opened

    def poll() -> None:
        if _editors_opened != opened:
            return
        try:
            reached = view.getCameraOrientation().isSame(orientation, 1e-6)
            if not reached and time.monotonic() - started_s < _TURN_TIMEOUT_S:
                QtCore.QTimer.singleShot(_POLL_MS, poll)
                return
            view.setCamera(camera)
        except RuntimeError:
            # The view closed during the turn: FreeCAD's view object raises
            # once its view is deleted.
            return

    QtCore.QTimer.singleShot(_POLL_MS, poll)
