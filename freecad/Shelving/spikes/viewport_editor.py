"""Spike: the elevation editor drawn and driven in FreeCAD's 3D view.

Everything this draws lives in one elevation frame: x along the
elevation's horizontal axis, y along its vertical axis, z toward the
camera, origin at the unit's minimum corner on the face nearer the camera.
``SoDatumLabel`` lays its text out in its local XY plane only, which is
what forces that frame, and it turns bay picking into a ray meeting z = 0.

Coin must not lose a node that is on the path of the event it is
handling, so every rebuild a Coin callback triggers waits for the Qt event
loop, and the dragger lives under its own holder that a rebuild during a
drag leaves alone.
"""

from __future__ import annotations

import math
import re
import time
import traceback
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeAlias, cast

import FreeCAD
import FreeCADGui
from pivy import coin
from PySide6 import QtCore, QtGui, QtWidgets
from shiboken6 import Shiboken

from freecad.Shelving.compat import override
from freecad.Shelving.core.geometry import Space, Vec3
from freecad.Shelving.core.layout import (
    Axis,
    Basis,
    Bay,
    Board,
    Division,
    Fixed,
    Region,
    Unit,
    Void,
)
from freecad.Shelving.core.scan import elevation_axes
from freecad.Shelving.editor.panel import _DimensionField
from freecad.Shelving.editor.scene import _apply_insets
from freecad.Shelving.editor.session import EditFailure, Session
from freecad.Shelving.refusals import report_error
from freecad.Shelving.spikes.spike_log import log

# pivy ships no type information, so every Coin node and field is untyped.
_Coin: TypeAlias = Any

SelectionMode = Literal["ours", "native"]

# How far in front of the front face the drawing sits, so it does not
# z-fight with the board faces it lies on.
_LIFT_MM = 0.5
# A press and release closer than this, in device pixels, is a click.
_CLICK_SLOP_PX = 4
# How close to a dimension's text a click must land to open its field.
_LABEL_HIT_PX = 24
# The datum labels' text size, in points.
_LABEL_SIZE_PT = 12
# The dragger's length as a fraction of the unit's larger elevation side.
_DRAGGER_FRACTION = 0.04

_BAY_RGB = (0.85, 0.85, 0.85)
_VOID_RGB = (0.6, 0.6, 0.6)
_OUTLINE_RGB = (0.2, 0.2, 0.2)
_SELECTED_RGB = (0.16, 0.5, 1.0)
_LABEL_RGB = (0.12, 0.31, 0.47)


class _View(Protocol):
    """The parts of FreeCAD's ``View3DInventorPy`` this spike calls; the
    stubs do not declare them."""

    def getSceneGraph(self) -> _Coin: ...
    def getCameraNode(self) -> _Coin: ...
    def getCamera(self) -> str: ...
    def setCamera(self, camera: str, /) -> None: ...
    def setCameraType(self, kind: str, /) -> None: ...
    def getSize(self) -> tuple[int, int]: ...
    def getNavigationType(self) -> str: ...
    def getObjectInfo(
        self, position: tuple[int, int], /
    ) -> Mapping[str, object] | None: ...
    def getPointOnViewport(self, point: FreeCAD.Vector, /) -> tuple[int, int]: ...
    def projectPointToLine(
        self, position: tuple[int, int], /
    ) -> tuple[FreeCAD.Vector, FreeCAD.Vector]: ...
    def graphicsView(self) -> QtWidgets.QGraphicsView: ...
    def addEventCallbackPivy(
        self, event_type: _Coin, callback: Callable[[_Coin], None], /
    ) -> Callable[[_Coin], None]: ...
    def removeEventCallbackPivy(
        self, event_type: _Coin, callback: Callable[[_Coin], None], /
    ) -> None: ...
    def addDraggerCallback(
        self, dragger: _Coin, kind: str, callback: Callable[[_Coin], None], /
    ) -> Callable[[_Coin], None]: ...
    def removeDraggerCallback(
        self, dragger: _Coin, kind: str, callback: Callable[[_Coin], None], /
    ) -> None: ...


class _GuiDocument(Protocol):
    ActiveView: _View


class _ViewObject(Protocol):
    Visibility: bool


class Host(Protocol):
    """What the editor needs from the task panel that owns it."""

    session: Session

    def select_node(self, node_id: str | None) -> None: ...
    def show_result(self, failure: EditFailure | None) -> None: ...


def _basis(axis: Axis) -> FreeCAD.Vector:
    components = [0.0, 0.0, 0.0]
    components[axis.component_index] = 1.0
    return FreeCAD.Vector(*components)


def _container_placement(container: FreeCAD.DocumentObject) -> FreeCAD.Placement:
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


@dataclass(frozen=True)
class ElevationFrame:
    horizontal: Axis
    vertical: Axis
    # Elevation coordinates (horizontal mm, vertical mm, toward-camera mm)
    # to document coordinates.
    placement: FreeCAD.Placement
    # Elevation coordinates to unit-frame coordinates, which are the
    # container's local frame.
    local: FreeCAD.Placement

    def to_global(self, h_mm: float, v_mm: float, z_mm: float = 0.0) -> FreeCAD.Vector:
        return self.placement.multVec(FreeCAD.Vector(h_mm, v_mm, z_mm))

    def from_global(self, point: FreeCAD.Vector) -> FreeCAD.Vector:
        return self.placement.inverse().multVec(point)

    def to_unit(self, h_mm: float, v_mm: float) -> Vec3:
        point = self.local.multVec(FreeCAD.Vector(h_mm, v_mm, 0.0))
        return Vec3(point.x, point.y, point.z)

    def rect(self, space: Space) -> tuple[float, float, float, float]:
        """``space`` as (h0, v0, h1, v1) in elevation millimeters."""
        h = self.horizontal.component_index
        v = self.vertical.component_index
        h0 = space.origin_mm(h)
        v0 = space.origin_mm(v)
        return (h0, v0, h0 + space.extent_mm(h), v0 + space.extent_mm(v))


def elevation_frame(unit: Unit, container: FreeCAD.DocumentObject) -> ElevationFrame:
    """The frame the overlay draws in. Raises ``ValueError`` when the unit
    has no depth axis."""
    if unit.depth_axis is None:
        raise ValueError(f"unit {unit.id!r} has no depth axis")
    horizontal, vertical = elevation_axes(unit.depth_axis)
    e_h = _basis(horizontal)
    e_v = _basis(vertical)
    toward_camera = e_h.cross(e_v)
    depth_index = unit.depth_axis.component_index
    # The camera sits on the toward_camera side, so the near face is the
    # high end of the depth axis when toward_camera points along it.
    toward_component = (toward_camera.x, toward_camera.y, toward_camera.z)[depth_index]
    front_mm = unit.size_mm.component_mm(depth_index) if toward_component > 0 else 0.0
    origin = _basis(unit.depth_axis) * front_mm
    matrix = FreeCAD.Matrix(
        e_h.x, e_v.x, toward_camera.x, origin.x,
        e_h.y, e_v.y, toward_camera.y, origin.y,
        e_h.z, e_v.z, toward_camera.z, origin.z,
        0.0, 0.0, 0.0, 1.0,
    )  # fmt: skip
    local = FreeCAD.Placement(matrix)
    return ElevationFrame(
        horizontal=horizontal,
        vertical=vertical,
        placement=_container_placement(container).multiply(local),
        local=local,
    )


def _walk(
    region: Region, depth: int = 0
) -> Iterator[tuple[Region | Board, int, Axis | None]]:
    """Every region and board under ``region`` with its nesting depth and,
    for a board, the axis of the division it sits in."""
    yield region, depth, None
    if isinstance(region, Division):
        for item in region.items:
            if isinstance(item, Board):
                yield item, depth + 1, region.axis
            else:
                yield from _walk(item, depth + 1)


def board_in_path(names: list[str], board_ids: Mapping[str, object]) -> str | None:
    """The last of ``names`` that is a board id: a pick or a selection names
    a path from a top-level object down through containers."""
    for name in reversed(names):
        if name in board_ids:
            return name
    return None


def _path_names(obj_name: str, sub_name: str) -> list[str]:
    """``obj_name`` followed by each object a sub-element path like
    ``"Board001.Face3"`` or ``"Board001."`` walks through."""
    return [obj_name, *(part for part in sub_name.split(".")[:-1] if part)]


@dataclass(frozen=True)
class _Label:
    region_id: str
    mid_h_mm: float
    mid_v_mm: float


class _FieldKeys(QtCore.QObject):
    """Closes the floating field on Escape, which would otherwise reach the
    task panel and cancel the whole edit. Focus loss only logs: the field
    stays until Escape, Return or the next click in the view."""

    def __init__(self, parent: QtCore.QObject, on_close: Callable[[str], None]) -> None:
        super().__init__(parent)
        self._on_close = on_close

    @override
    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = cast("QtGui.QKeyEvent", event).key()
            if key == QtCore.Qt.Key.Key_Escape:
                self._on_close("escape")
                return True
        elif event.type() == QtCore.QEvent.Type.FocusOut:
            focus = QtWidgets.QApplication.focusWidget()
            log(
                f"field lost focus to {type(focus).__name__ if focus else None} "
                f"{focus.objectName() if focus else ''!r}"
            )
        return False


class _BoardGate:
    """A FreeCAD selection gate that lets only the unit's boards be selected."""

    def __init__(self, editor: ViewportEditor) -> None:
        self._editor = editor

    def allow(self, _doc: object, obj: FreeCAD.DocumentObject, sub: str) -> bool:
        allowed = self._editor.board_for_path(obj.Name, sub) is not None
        log(f"gate: {obj.Name} {sub!r} -> {allowed}")
        return allowed


class _SelectionObserver:
    def __init__(self, editor: ViewportEditor) -> None:
        self._editor = editor

    def addSelection(self, _doc: str, obj: str, sub: str, _point: object) -> None:
        self._editor.native_selected(obj, sub)

    def clearSelection(self, _doc: str) -> None:
        log("native selection cleared")


class ViewportEditor:
    """The overlay, camera and input handling for one editing session in the
    active 3D view. :meth:`close` undoes every change it made to the view."""

    def __init__(self, host: Host) -> None:
        self._host = host
        session = host.session
        self._container = session.container
        gui_doc = cast("_GuiDocument", FreeCADGui.ActiveDocument)
        self.view = gui_doc.ActiveView
        self._viewer = self.view.graphicsView()
        self._frame = elevation_frame(session.unit, session.container)
        self.selection_mode: SelectionMode = "ours"
        self.on_top = False
        self._closed = False

        self._saved_camera = self.view.getCamera()
        scene_graph = self.view.getSceneGraph()
        self._selection_field: _Coin = scene_graph.getField("selectionEnabled")
        self._saved_selection_enabled = bool(self._selection_field.getValue())
        self._hidden: list[str] = []

        self._root = coin.SoSeparator()
        self._frame_transform = coin.SoTransform()
        self._root.addChild(self._frame_transform)
        self._drawing: _Coin = coin.SoSeparator()
        self._dragger_holder: _Coin = coin.SoSeparator()
        self._root.addChild(self._drawing)
        self._root.addChild(self._dragger_holder)
        scene_graph.addChild(self._root)

        self._labels: list[_Label] = []
        # One dragger for the whole session, moved and shown or hidden per
        # selection and never destroyed while the view is open: on Coin
        # before 4.0.4, destroying a dragger that has been dragged crashes
        # FreeCAD (coin3d/coin#556, see _KEPT_ALIVE).
        self._dragger: _Coin = coin.SoTranslate1Dragger()
        self._dragger_transform: _Coin = coin.SoTransform()
        self._dragger_switch: _Coin = coin.SoSwitch()
        self._dragger_switch.ref()
        pick_style = coin.SoPickStyle()
        pick_style.style = coin.SoPickStyle.SHAPE
        # A switch shows one child, so the three go in one separator.
        dragger_group = coin.SoSeparator()
        dragger_group.addChild(pick_style)
        dragger_group.addChild(self._dragger_transform)
        dragger_group.addChild(self._dragger)
        self._dragger_switch.addChild(dragger_group)
        self._dragger_switch.whichChild.setValue(coin.SO_SWITCH_NONE)
        self._dragger_holder.addChild(self._dragger_switch)
        self._dragger_callbacks: list[tuple[str, Callable[[_Coin], None]]] = []
        self._dragger_board: str | None = None
        self._dragger_scale_mm = 1.0
        self._drag_center: Vec3 | None = None
        self._dragging = False
        self._drag_failed = False
        self._run_index: int = 0
        self._last_rebuild_ms = 0.0
        self._drag_timings_ms: list[tuple[float, float]] = []
        self._press_position: tuple[int, int] | None = None
        self._field: _DimensionField | None = None
        self._field_host: QtWidgets.QFrame | None = None
        self._field_applied = False
        self._field_region: str | None = None
        self._field_anchor: tuple[float, float] | None = None
        self._camera_sensor: _Coin = None
        self._gate = _BoardGate(self)
        self._observer = _SelectionObserver(self)
        self._native_active = False

        for kind, callback in (
            ("addStartCallback", self._drag_started),
            ("addMotionCallback", self._drag_moved),
            ("addFinishCallback", self._drag_finished),
        ):
            handle = self.view.addDraggerCallback(self._dragger, kind, callback)
            self._dragger_callbacks.append((kind, handle))
        self._mouse_callback = self.view.addEventCallbackPivy(
            coin.SoMouseButtonEvent.getClassTypeId(), self._on_mouse
        )
        self._key_callback = self.view.addEventCallbackPivy(
            coin.SoKeyboardEvent.getClassTypeId(), self._on_key
        )
        self.set_selection_mode("ours")
        self._log_environment()
        self.frame_camera()
        self._check_frame()
        self.rebuild()

    @property
    def dragging(self) -> bool:
        return self._dragging

    # Setup and teardown

    def _log_environment(self) -> None:
        viewer = self._viewer
        screen = viewer.screen()
        version = ".".join(FreeCAD.Version()[:3])
        log(
            f"open: FreeCAD {version}, Qt {QtCore.qVersion()}, "
            f"platform {QtGui.QGuiApplication.platformName()}"
        )
        log(
            f"view: getSize {self.view.getSize()}, widget "
            f"{viewer.width()}x{viewer.height()}, devicePixelRatio "
            f"{viewer.devicePixelRatioF()}, screen {screen.name()} "
            f"{screen.geometry().width()}x{screen.geometry().height()} "
            f"dpr {screen.devicePixelRatio()}"
        )
        log(f"navigation style: {self.view.getNavigationType()}")
        log(
            f"Coin {coin.SoDB.getVersion()}, destroys draggers safely: "
            f"{_coin_destroys_draggers_safely()}"
        )
        unit = self._host.session.unit
        log(
            f"unit {unit.id}: size {unit.size_mm}, depth axis {unit.depth_axis}, "
            f"front_at_min {unit.front_at_min}, "
            f"horizontal {self._frame.horizontal}, vertical {self._frame.vertical}"
        )
        log(f"frame placement {self._frame.placement}")
        doc = self._container.Document
        log(f"undo names at open: {doc.UndoNames}")

    def _check_frame(self) -> None:
        """Log how far each board's real solid sits from where the overlay
        draws it, both in the container's frame (the unit frame the layout
        uses) and in the document frame (where Coin draws the overlay).
        Anything past a few hundredths of a millimeter in the document
        frame means the overlay is misplaced for this container."""
        session = self._host.session
        placement = _container_placement(self._container)
        doc = self._container.Document
        worst_local_mm = 0.0
        worst_global_mm = 0.0
        checked = 0
        for node, _depth, _axis in _walk(session.unit.root):
            if not isinstance(node, Board):
                continue
            obj = doc.getObject(node.id)
            shape = getattr(obj, "Shape", None) if obj is not None else None
            if shape is None:
                continue
            space = session.spaces[node.id]
            low = space.origin
            high = space.max_corner()
            corners = [
                FreeCAD.Vector(x, y, z)
                for x in (low.x_mm, high.x_mm)
                for y in (low.y_mm, high.y_mm)
                for z in (low.z_mm, high.z_mm)
            ]
            local_box = FreeCAD.BoundBox()
            global_box = FreeCAD.BoundBox()
            for point in corners:
                local_box.add(point)
                global_box.add(placement.multVec(point))
            # A child's Shape is in its parent's frame; this composes the
            # container's placement onto it.
            placed = shape.copy()
            placed.Placement = placement.multiply(placed.Placement)
            real_local = shape.BoundBox
            real_global = placed.BoundBox
            worst_local_mm = max(worst_local_mm, _box_error_mm(real_local, local_box))
            worst_global_mm = max(
                worst_global_mm, _box_error_mm(real_global, global_box)
            )
            checked += 1
        log(
            f"frame check: {checked} boards, worst corner error "
            f"{worst_local_mm:.4f} mm in the container frame, "
            f"{worst_global_mm:.4f} mm in the document frame"
        )

    def close(self) -> None:
        """Remove the overlay and callbacks, restore native selection, the
        hidden objects and the camera. Safe to call twice."""
        if self._closed:
            return
        self._closed = True
        self._close_field("editor closed")
        self.set_hide_others(False)
        for kind, callback in self._dragger_callbacks:
            self.view.removeDraggerCallback(self._dragger, kind, callback)
        self._dragger_callbacks = []
        self._set_native(False)
        self._selection_field.setValue(self._saved_selection_enabled)
        self.view.removeEventCallbackPivy(
            coin.SoMouseButtonEvent.getClassTypeId(), self._mouse_callback
        )
        self.view.removeEventCallbackPivy(
            coin.SoKeyboardEvent.getClassTypeId(), self._key_callback
        )
        if self._camera_sensor is not None:
            self._camera_sensor.detach()
            self._camera_sensor = None
        self.view.getSceneGraph().removeChild(self._root)
        if _coin_destroys_draggers_safely():
            self._dragger_switch.unref()
        else:
            _KEPT_ALIVE.append(self._dragger_switch)
            log(f"Coin {coin.SoDB.getVersion()}: dragger kept alive (coin3d/coin#556)")
        self.view.setCamera(self._saved_camera)
        log(f"close: camera restored, undo names {self._container.Document.UndoNames}")

    # Panel controls

    def set_selection_mode(self, mode: SelectionMode) -> None:
        self.selection_mode = mode
        self._selection_field.setValue(mode == "native")
        self._set_native(mode == "native")
        log(f"selection mode: {mode}")

    def _set_native(self, on: bool) -> None:
        if on == self._native_active:
            return
        if on:
            FreeCADGui.Selection.clearSelection()
            FreeCADGui.Selection.addSelectionGate(self._gate)
            FreeCADGui.Selection.addObserver(self._observer)
        else:
            FreeCADGui.Selection.removeSelectionGate()
            FreeCADGui.Selection.removeObserver(self._observer)
            FreeCADGui.Selection.clearSelection()
        self._native_active = on

    def set_on_top(self, on_top: bool) -> None:
        """Draw the overlay over the solids (``SoAnnotation``) or depth-tested
        against them."""
        self.on_top = on_top
        self._root.removeChild(self._drawing)
        self._root.removeChild(self._dragger_holder)
        holder_type = coin.SoAnnotation if on_top else coin.SoSeparator
        self._drawing = holder_type()
        self._dragger_holder = holder_type()
        self._dragger_holder.addChild(self._dragger_switch)
        self._root.addChild(self._drawing)
        self._root.addChild(self._dragger_holder)
        log(f"overlay on top: {on_top}")
        self.rebuild()

    def set_hide_others(self, hide: bool) -> None:
        doc = self._container.Document
        if hide and not self._hidden:
            keep = {self._container.Name}
            keep.update(o.Name for o in self._container.OutListRecursive)
            keep.update(o.Name for o in self._container.InListRecursive)
            before = list(doc.UndoNames)
            for obj in doc.Objects:
                view_object = cast(
                    "_ViewObject | None", getattr(obj, "ViewObject", None)
                )
                if obj.Name in keep or view_object is None:
                    continue
                if view_object.Visibility:
                    view_object.Visibility = False
                    self._hidden.append(obj.Name)
            log(
                f"hid {len(self._hidden)} objects; undo names before {before}, "
                f"after {doc.UndoNames}"
            )
        elif not hide and self._hidden:
            for name in self._hidden:
                obj = doc.getObject(name)
                view_object = cast(
                    "_ViewObject | None", getattr(obj, "ViewObject", None)
                )
                if view_object is not None:
                    view_object.Visibility = True
            log(f"restored {len(self._hidden)} objects; undo names {doc.UndoNames}")
            self._hidden = []

    def frame_camera(self) -> None:
        """Turn the camera to the unit's front, orthographic, framing the
        unit with a margin."""
        unit = self._host.session.unit
        width_mm = unit.size_mm.component_mm(self._frame.horizontal.component_index)
        height_mm = unit.size_mm.component_mm(self._frame.vertical.component_index)
        self.view.setCameraType("Orthographic")
        camera = self.view.getCameraNode()
        q = self._frame.placement.Rotation.Q
        camera.orientation.setValue(coin.SbRotation(q[0], q[1], q[2], q[3]))
        center = self._frame.to_global(width_mm / 2, height_mm / 2)
        toward_camera = self._frame.placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
        distance_mm = 3 * max(width_mm, height_mm)
        position = center + toward_camera * distance_mm
        camera.position.setValue(position.x, position.y, position.z)
        camera.focalDistance.setValue(distance_mm)
        size = self.view.getSize()
        aspect = size[0] / size[1] if size[1] else 1.0
        camera.height.setValue(1.15 * max(height_mm, width_mm / aspect))
        self._watch_camera(camera)
        log(f"camera framed: {self.view.getCamera().strip()!r}")

    def _watch_camera(self, camera: _Coin) -> None:
        if self._camera_sensor is not None:
            self._camera_sensor.detach()
        self._camera_sensor = coin.SoNodeSensor(self._camera_moved, None)
        self._camera_sensor.attach(camera)

    def _camera_moved(self, _data: object, _sensor: object) -> None:
        if self._field_host is not None:
            self._place_field()

    # Drawing

    def rebuild(self) -> None:
        """Redraw from the session; the dragger too unless a drag is on."""
        if self._closed:
            return
        start_s = time.perf_counter()
        frame = self._frame
        q = frame.placement.Rotation.Q
        base = frame.placement.Base
        self._frame_transform.translation.setValue(base.x, base.y, base.z)
        self._frame_transform.rotation.setValue(coin.SbRotation(q[0], q[1], q[2], q[3]))
        self._drawing.removeAllChildren()
        self._drawing.addChild(self._drawing_content())
        if not self._dragging:
            self._rebuild_dragger()
        if self._field_host is not None:
            self._place_field()
        elapsed_ms = (time.perf_counter() - start_s) * 1000
        if not self._dragging:
            log(f"overlay rebuilt in {elapsed_ms:.1f} ms")
        self._last_rebuild_ms = elapsed_ms

    def _drawing_content(self) -> _Coin:
        session = self._host.session
        frame = self._frame
        selected = session.selected_id
        content = coin.SoSeparator()
        pick_style = coin.SoPickStyle()
        pick_style.style = coin.SoPickStyle.UNPICKABLE
        content.addChild(pick_style)
        light = coin.SoLightModel()
        light.model = coin.SoLightModel.BASE_COLOR
        content.addChild(light)
        self._labels = []
        for node, depth, division_axis in _walk(session.unit.root):
            space = session.spaces.get(node.id)
            if space is None:
                continue
            z_mm = _LIFT_MM * (1 + depth * 0.01)
            if isinstance(node, Board):
                if node.id == selected and division_axis is not None:
                    inset = _apply_insets(division_axis, space, node.insets)
                    content.addChild(
                        _outline(frame.rect(inset), z_mm, _SELECTED_RGB, 3.0)
                    )
                continue
            is_selected = node.id == selected
            if isinstance(node, Bay | Void):
                rgb = _VOID_RGB if isinstance(node, Void) else _BAY_RGB
                content.addChild(
                    _face(
                        frame.rect(space), z_mm, _SELECTED_RGB if is_selected else rgb
                    )
                )
            if isinstance(node, Bay | Void) or is_selected:
                content.addChild(
                    _outline(
                        frame.rect(space),
                        z_mm,
                        _SELECTED_RGB if is_selected else _OUTLINE_RGB,
                        3.0 if is_selected else 1.0,
                    )
                )
            if isinstance(node, Division):
                self._add_dimensions(content, node, z_mm + _LIFT_MM)
        return content

    def _add_dimensions(self, content: _Coin, division: Division, z_mm: float) -> None:
        """One datum label per region in ``division``'s run, measured the way
        its rule measures it, as the panel's elevation does."""
        session = self._host.session
        frame = self._frame
        if division.axis not in (frame.horizontal, frame.vertical):
            return
        run_is_horizontal = division.axis == frame.horizontal
        along = division.axis.component_index
        across = (
            frame.vertical if run_is_horizontal else frame.horizontal
        ).component_index
        for index, item in enumerate(division.items):
            if isinstance(item, Board):
                continue
            space = session.spaces[item.id]
            low_mm = space.origin_mm(along)
            high_mm = low_mm + space.extent_mm(along)
            spacing = (
                isinstance(item.rule, Fixed) and item.rule.basis is Basis.WITH_NEXT
            )
            if spacing and index + 1 < len(division.items):
                after = division.items[index + 1]
                if isinstance(after, Board):
                    after_space = session.spaces[after.id]
                    high_mm = after_space.origin_mm(along) + after_space.extent_mm(
                        along
                    )
            fraction = 0.25 if isinstance(item, Division) else 0.5
            cross_mm = space.origin_mm(across) + fraction * space.extent_mm(across)
            if run_is_horizontal:
                p1 = (low_mm, cross_mm)
                p2 = (high_mm, cross_mm)
            else:
                p1 = (cross_mm, low_mm)
                p2 = (cross_mm, high_mm)
            selected = item.id == session.selected_id
            content.addChild(
                _datum_label(
                    p1,
                    p2,
                    z_mm,
                    f"{high_mm - low_mm:.2f}".rstrip("0").rstrip("."),
                    _SELECTED_RGB if selected else _LABEL_RGB,
                    frame.placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1)),
                )
            )
            self._labels.append(
                _Label(item.id, (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
            )

    def _hide_dragger(self) -> None:
        self._dragger_switch.whichChild.setValue(coin.SO_SWITCH_NONE)
        self._dragger_board = None

    def _rebuild_dragger(self) -> None:
        """Put the arrow on the selected board, along its run, when it has a
        region before it to resize; hide it otherwise."""
        self._hide_dragger()
        session = self._host.session
        board_id = session.selected_id
        if board_id is None or not session.can_merge():
            return
        from freecad.Shelving.core.edit import EditError, region_before, run_axis

        try:
            region_before(session.unit, board_id)
            axis = run_axis(session.unit, board_id)
        except EditError:
            return
        if axis not in (self._frame.horizontal, self._frame.vertical):
            return
        space = session.spaces[board_id]
        h0, v0, h1, v1 = self._frame.rect(space)
        unit = session.unit
        longest_mm = max(
            unit.size_mm.component_mm(self._frame.horizontal.component_index),
            unit.size_mm.component_mm(self._frame.vertical.component_index),
        )
        self._dragger_scale_mm = _DRAGGER_FRACTION * longest_mm
        placement = self._dragger_transform
        placement.translation.setValue((h0 + h1) / 2, (v0 + v1) / 2, 4 * _LIFT_MM)
        angle = math.pi / 2 if axis == self._frame.vertical else 0.0
        placement.rotation.setValue(coin.SbVec3f(0, 0, 1), angle)
        scale = self._dragger_scale_mm
        placement.scaleFactor.setValue(scale, scale, scale)
        self._dragger.translation.setValue(0, 0, 0)
        self._dragger_switch.whichChild.setValue(0)
        self._dragger_board = board_id
        center = space.origin
        self._drag_center = Vec3(
            center.x_mm + space.size.x_mm / 2,
            center.y_mm + space.size.y_mm / 2,
            center.z_mm + space.size.z_mm / 2,
        )
        self._run_index = axis.component_index

    # Dragging

    def _drag_started(self, _dragger: _Coin) -> None:
        try:
            board_id = self._dragger_board
            center = self._drag_center
            if board_id is None or center is None:
                return
            log(f"drag start on {board_id}, navigation {self.view.getNavigationType()}")
            failure = self._host.session.begin_drag(board_id, center)
            if failure is not None:
                log(f"drag refused: {failure.message}")
                report_error(failure.message)
                return
            self._dragging = True
            self._drag_timings_ms = []
            self._drag_failed = False
        except Exception:  # noqa: BLE001 - a Coin callback must not raise
            log("drag start raised:\n" + traceback.format_exc())

    def _drag_moved(self, dragger: _Coin) -> None:
        if not self._dragging or self._drag_center is None:
            return
        try:
            offset = float(dragger.translation.getValue()[0]) * self._dragger_scale_mm
            components = [
                self._drag_center.x_mm,
                self._drag_center.y_mm,
                self._drag_center.z_mm,
            ]
            components[self._run_index] += offset
            start_s = time.perf_counter()
            failure = self._host.session.drag_to(Vec3(*components))
            solved_s = time.perf_counter()
            self._host.show_result(None)
            done_s = time.perf_counter()
            self._drag_timings_ms.append(
                ((solved_s - start_s) * 1000, (done_s - solved_s) * 1000)
            )
            if failure is not None and not self._drag_failed:
                self._drag_failed = True
                log(f"drag step refused: {failure.message}")
                report_error(failure.message)
        except Exception:  # noqa: BLE001 - a Coin callback must not raise
            log("drag motion raised:\n" + traceback.format_exc())

    def _drag_finished(self, _dragger: _Coin) -> None:
        if not self._dragging:
            return
        self._host.session.end_drag()
        self._dragging = False
        timings = self._drag_timings_ms
        if timings:
            solve = [t[0] for t in timings]
            redraw = [t[1] for t in timings]
            log(
                f"drag end: {len(timings)} steps; solve+write mean "
                f"{sum(solve) / len(solve):.1f} ms max {max(solve):.1f} ms; "
                f"panel+overlay redraw mean {sum(redraw) / len(redraw):.1f} ms "
                f"max {max(redraw):.1f} ms"
            )
        else:
            log("drag end: no motion")
        # The dragger is on the path of the event that finished it.
        QtCore.QTimer.singleShot(0, self.rebuild)

    # Picking

    def board_for_path(self, obj_name: str, sub_name: str) -> str | None:
        session = self._host.session
        boards = {
            node.id: node
            for node, _d, _a in _walk(session.unit.root)
            if isinstance(node, Board)
        }
        return board_in_path(_path_names(obj_name, sub_name), boards)

    def native_selected(self, obj_name: str, sub_name: str) -> None:
        board_id = self.board_for_path(obj_name, sub_name)
        log(f"native selection: {obj_name} {sub_name!r} -> board {board_id}")
        if board_id is not None and board_id != self._host.session.selected_id:
            # The observer runs inside FreeCAD's selection change.
            QtCore.QTimer.singleShot(0, lambda: self._host.select_node(board_id))

    def _on_mouse(self, event_callback: _Coin) -> None:
        try:
            self._handle_mouse(event_callback)
        except Exception:  # noqa: BLE001 - a Coin callback must not raise
            log("mouse callback raised:\n" + traceback.format_exc())

    def _handle_mouse(self, event_callback: _Coin) -> None:
        event = event_callback.getEvent()
        position = cast("tuple[int, int]", tuple(event.getPosition().getValue()))
        button = int(event.getButton())
        state = int(event.getState())
        already = bool(event_callback.getAction().isHandled())
        direction = "down" if state == coin.SoButtonEvent.DOWN else "up"
        log(
            f"mouse button {button} {direction} "
            f"at {position}, handled before us {already}, "
            f"navigation {self.view.getNavigationType()}"
        )
        if button != coin.SoMouseButtonEvent.BUTTON1:
            return
        if state == coin.SoButtonEvent.DOWN:
            self._press_position = position
            return
        press = self._press_position
        self._press_position = None
        if press is None or already:
            return
        if (
            max(abs(press[0] - position[0]), abs(press[1] - position[1]))
            > _CLICK_SLOP_PX
        ):
            return
        event_callback.setHandled()
        # Rebuilding now would touch the scene graph mid-traversal.
        QtCore.QTimer.singleShot(0, lambda: self._click(position))

    def _click(self, position: tuple[int, int]) -> None:
        self._close_field("click in the view")
        label = self._label_at(position)
        if label is not None:
            log(f"click on the dimension of {label.region_id}")
            self._host.select_node(label.region_id)
            self._open_field(label)
            return
        if self.selection_mode == "ours":
            info = self.view.getObjectInfo(position)
            log(f"object info at {position}: {info}")
            if info is not None:
                obj_name = str(info.get("Object", ""))
                sub_name = str(info.get("SubName", "") or "")
                board_id = self.board_for_path(obj_name, sub_name)
                if board_id is not None:
                    self._host.select_node(board_id)
                    return
        node_id = self._region_at(position)
        log(f"click at {position} picks {node_id}")
        self._host.select_node(node_id)

    def _label_at(self, position: tuple[int, int]) -> _Label | None:
        best: tuple[float, _Label] | None = None
        for label in self._labels:
            screen = self.view.getPointOnViewport(
                self._frame.to_global(label.mid_h_mm, label.mid_v_mm)
            )
            distance = math.hypot(screen[0] - position[0], screen[1] - position[1])
            if distance <= _LABEL_HIT_PX and (best is None or distance < best[0]):
                best = (distance, label)
        return best[1] if best is not None else None

    def _region_at(self, position: tuple[int, int]) -> str | None:
        """The deepest bay, void or division under ``position``, read where
        the pointer's ray meets the front plane; a board too when native
        selection is off."""
        near, far = self.view.projectPointToLine(position)
        a = self._frame.from_global(near)
        b = self._frame.from_global(far)
        if abs(b.z - a.z) < 1e-9:
            return None
        t = -a.z / (b.z - a.z)
        h_mm = a.x + t * (b.x - a.x)
        v_mm = a.y + t * (b.y - a.y)
        session = self._host.session
        best: tuple[int, str] | None = None
        for node, depth, _axis in _walk(session.unit.root):
            if isinstance(node, Board) and self.selection_mode == "native":
                continue
            space = session.spaces.get(node.id)
            if space is None:
                continue
            h0, v0, h1, v1 = self._frame.rect(space)
            if h0 <= h_mm <= h1 and v0 <= v_mm <= v1:
                if best is None or depth >= best[0]:
                    best = (depth, node.id)
        root_id = session.unit.root.id
        if best is None or best[1] == root_id:
            return None
        return best[1]

    def _on_key(self, event_callback: _Coin) -> None:
        try:
            event = event_callback.getEvent()
            key = int(event.getKey())
            down = int(event.getState()) == coin.SoButtonEvent.DOWN
            log(
                f"key {key} {'down' if down else 'up'}, handled before us "
                f"{bool(event_callback.getAction().isHandled())}"
            )
            if down and key == coin.SoKeyboardEvent.DELETE:
                event_callback.setHandled()
                QtCore.QTimer.singleShot(0, self._delete_selected)
        except Exception:  # noqa: BLE001 - a Coin callback must not raise
            log("key callback raised:\n" + traceback.format_exc())

    def _delete_selected(self) -> None:
        session = self._host.session
        if session.can_merge():
            self._host.show_result(session.merge())

    # The floating size field

    def _open_field(self, label: _Label) -> None:
        self._close_field("another field opened")
        session = self._host.session
        measurement = session.selected_measurement()
        if measurement is None:
            log(f"no measurement for {label.region_id}; no field")
            return
        field = _DimensionField(
            session.probe, self._field_size, report_error, self._field_expression_done
        )
        field.show_mm(measurement.size_mm)
        # Hosted in a frame's layout: setParent on the quantity widget
        # itself destroys it at once (verified under Xvfb, FreeCAD 1.1.3),
        # while a layout reparents it safely, as the panel's rows do.
        host = QtWidgets.QFrame(self._viewer.parentWidget())
        host_layout = QtWidgets.QHBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)
        host_layout.addWidget(field.widget)
        keys = _FieldKeys(host, self._close_field_later)
        field.widget.installEventFilter(keys)
        field.line_edit.installEventFilter(keys)
        self._field = field
        self._field_applied = False
        self._field_host = host
        self._field_region = label.region_id
        self._field_anchor = (label.mid_h_mm, label.mid_v_mm)
        host.show()
        host.adjustSize()
        host.raise_()
        self._place_field()
        field.line_edit.setFocus()
        field.line_edit.selectAll()
        log(f"field opened for {label.region_id} showing {measurement.size_mm} mm")

    def _place_field(self) -> None:
        host = self._field_host
        anchor = self._field_anchor
        if host is None or anchor is None or not Shiboken.isValid(host):
            return
        raw = self.view.getPointOnViewport(self._frame.to_global(*anchor))
        ratio = self._viewer.devicePixelRatioF()
        height_px = self.view.getSize()[1]
        local = QtCore.QPoint(
            round(raw[0] / ratio), round((height_px - raw[1] - 1) / ratio)
        )
        parent = host.parentWidget()
        in_parent = self._viewer.mapTo(parent, local) if parent is not None else local
        host.move(in_parent.x() - host.width() // 2, in_parent.y() - host.height() // 2)
        log(
            f"field placed: viewport point {raw}, ratio {ratio}, widget point "
            f"({local.x()}, {local.y()}), host {host.geometry().getRect()}"
        )

    def _field_size(self, size_mm: float) -> None:
        # Return applies, then the close's focus-out finishes the same edit
        # again; after a refusal the value still differs, so without this
        # the user would see the refusal twice.
        if self._field is None or self._field_applied:
            return
        self._field_applied = True
        session = self._host.session
        log(f"field applies {size_mm} mm to {self._field_region}")
        if self._field_region is not None:
            session.select(self._field_region)
        self._host.show_result(session.set_size(size_mm))
        self._close_field_later("applied")

    def _field_expression_done(self) -> None:
        self._host.session.clear_probe_expression()
        self._host.show_result(None)

    def _close_field_later(self, reason: str) -> None:
        # Deleting the widget inside its own event handler crashes Qt.
        QtCore.QTimer.singleShot(0, lambda: self._close_field(reason))

    def _close_field(self, reason: str) -> None:
        host = self._field_host
        if self._field is None or host is None:
            return
        self._field = None
        self._field_host = None
        self._field_anchor = None
        log(f"field closed: {reason}")
        if Shiboken.isValid(host):
            host.hide()
            host.deleteLater()


# Draggers kept from destruction for the life of the process. Coin before
# 4.0.4 crashes deleting the SoCallbackAction a dragger creates the first
# time it is dragged (coin3d/coin#556, fixed in 4.0.4); FreeCAD 1.1's macOS
# bundle ships Coin 4.0.3. One small dragger per editing session.
_KEPT_ALIVE: list[_Coin] = []


def _coin_destroys_draggers_safely() -> bool:
    """Whether this Coin has the coin3d/coin#556 fix (4.0.4 or later)."""
    # The string reads like "SIM Coin 4.0.3".
    found = re.search(r"(\d+)\.(\d+)\.(\d+)", str(coin.SoDB.getVersion()))
    if found is None:
        return False
    major, minor, patch = (int(part) for part in found.groups())
    return (major, minor, patch) >= (4, 0, 4)


def _box_error_mm(a: FreeCAD.BoundBox, b: FreeCAD.BoundBox) -> float:
    return max(
        abs(a.XMin - b.XMin),
        abs(a.YMin - b.YMin),
        abs(a.ZMin - b.ZMin),
        abs(a.XMax - b.XMax),
        abs(a.YMax - b.YMax),
        abs(a.ZMax - b.ZMax),
    )


def _rgb(material: _Coin, rgb: tuple[float, float, float]) -> None:
    material.diffuseColor.setValue(*rgb)


def _face(
    rect: tuple[float, float, float, float],
    z_mm: float,
    rgb: tuple[float, float, float],
) -> _Coin:
    h0, v0, h1, v1 = rect
    group = coin.SoSeparator()
    material = coin.SoMaterial()
    _rgb(material, rgb)
    material.transparency.setValue(0.6)
    coordinates = coin.SoCoordinate3()
    coordinates.point.setValues(
        0, 4, [[h0, v0, z_mm], [h1, v0, z_mm], [h1, v1, z_mm], [h0, v1, z_mm]]
    )
    faces = coin.SoFaceSet()
    faces.numVertices.setValue(4)
    group.addChild(material)
    group.addChild(coordinates)
    group.addChild(faces)
    return group


def _outline(
    rect: tuple[float, float, float, float],
    z_mm: float,
    rgb: tuple[float, float, float],
    width_px: float,
) -> _Coin:
    h0, v0, h1, v1 = rect
    group = coin.SoSeparator()
    material = coin.SoMaterial()
    _rgb(material, rgb)
    style = coin.SoDrawStyle()
    style.lineWidth.setValue(width_px)
    coordinates = coin.SoCoordinate3()
    coordinates.point.setValues(
        0,
        5,
        [
            [h0, v0, z_mm],
            [h1, v0, z_mm],
            [h1, v1, z_mm],
            [h0, v1, z_mm],
            [h0, v0, z_mm],
        ],
    )
    lines = coin.SoLineSet()
    lines.numVertices.setValue(5)
    for node in (material, style, coordinates, lines):
        group.addChild(node)
    return group


def _datum_label(
    p1: tuple[float, float],
    p2: tuple[float, float],
    z_mm: float,
    text: str,
    rgb: tuple[float, float, float],
    normal: FreeCAD.Vector,
) -> _Coin:
    label = coin.SoType.fromName("SoDatumLabel").createInstance()
    label.getField("pnts").setValues(0, 2, [[p1[0], p1[1], z_mm], [p2[0], p2[1], z_mm]])
    # In document coordinates: the node compares it with the camera's
    # direction to decide which way its text reads.
    label.getField("norm").setValue(normal.x, normal.y, normal.z)
    label.getField("string").setValue(text)
    label.getField("textColor").setValue(*rgb)
    label.getField("size").setValue(_LABEL_SIZE_PT)
    label.getField("lineWidth").setValue(1.5)
    group = coin.SoSeparator()
    material = coin.SoMaterial()
    _rgb(material, rgb)
    group.addChild(material)
    group.addChild(label)
    return group
