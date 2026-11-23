"""The task panel's Constraints group: one row per constraint, Locks
included, in the order they were made, in the manner of the Sketcher's
constraint list.

The widget holds no layout logic. :meth:`ConstraintList.show` takes the
session's row snapshot and selection, and every user action goes out
through a :class:`ListActions` callback, after which the panel refreshes
the list from the session again.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

import FreeCAD
from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.core.layout import ConstraintId
from freecad.Shelving.editor.elevation import ConstraintKind, ElevationDirection
from freecad.Shelving.editor.overlay import (
    TILE_PAD_PX,
    Tile,
    constraint_icon_image,
    lock_icon_image,
    text_tile_image,
    view_style,
)
from freecad.Shelving.editor.session import ConstraintRow, RowKind

_KIND_NAMES: dict[RowKind, str] = {
    "lock_width": "Lock Width",
    "lock_height": "Lock Height",
    "lock": "Lock",
    "equal_width": "Equal Width",
    "equal_height": "Equal Height",
    "equal": "Equal",
    "even_width": "Even Width",
    "even_height": "Even Height",
    "even_spacing": "Even spacing",
}
# The constraint and direction of each Equal or Even spacing row on widths
# or heights, for its icon.
_AXIS_KINDS: Mapping[RowKind, tuple[ConstraintKind, ElevationDirection]] = {
    "equal_width": ("equal", "horizontal"),
    "equal_height": ("equal", "vertical"),
    "even_width": ("even_spacing", "horizontal"),
    "even_height": ("even_spacing", "vertical"),
}
REDUNDANT_TIP = (
    "Redundant: other locks and constraints already fix what this one fixes."
)
DELETE_TIP = "Delete"
_DELETE_ICON = ":/icons/edit-delete.svg"
# The most rows the list grows to before it scrolls.
_MAX_VISIBLE_ROWS = 8

# The columns: the row's checkbox, icon and text; its redundancy mark; its
# delete button.
TEXT_COLUMN = 0
MARK_COLUMN = 1
DELETE_COLUMN = 2


@dataclass(frozen=True)
class ListActions:
    """What the list asks of the panel; each call is followed by a
    :meth:`ConstraintList.show` with the session's new state."""

    set_active: Callable[[ConstraintId, bool], None]
    delete_constraint: Callable[[ConstraintId], None]
    delete_deactivated: Callable[[], None]
    select_constraints: Callable[[Sequence[ConstraintId]], None]


def row_text(row: ConstraintRow) -> str:
    """The row's kind name, followed by its size in the user's unit system
    while it has one."""
    name = _KIND_NAMES[row.kind]
    if row.size_mm is None:
        return name
    size = FreeCAD.Units.Quantity(row.size_mm, FreeCAD.Units.Length).UserString
    return f"{name} ({size})"


def kind_icon(
    kind: RowKind,
    side_px: int,
    ratio: float,
    base: QtGui.QColor,
    active: bool = True,
) -> QtGui.QIcon:
    """A row's icon, ``side_px`` logical pixels square at device pixel
    ratio ``ratio``, on a tile of ``base``, the list's own background: for
    a Lock, the icon of the command that makes it, grayed in Qt's disabled
    mode unless ``active``, and the bare tile for a Lock through the depth,
    which no command makes; for another constraint its width or height
    icon, or its axis-free icon through the depth, with the view's corner X
    unless ``active``. Each glyph takes the view's constraint icon
    color."""
    device_px = round(side_px * ratio)
    tile = Tile(
        (base.redF(), base.greenF(), base.blueF()), round(TILE_PAD_PX * ratio), 0.0
    )
    # Only the colors are read, so the text size does not matter.
    style = view_style(0)
    is_lock = kind in ("lock_width", "lock_height", "lock")
    if kind == "lock":
        image = text_tile_image(tile, device_px, device_px)
    elif kind in ("lock_width", "lock_height"):
        direction: ElevationDirection = (
            "horizontal" if kind == "lock_width" else "vertical"
        )
        image = lock_icon_image(direction, style.icon_rgb, tile, device_px)
    elif kind in ("equal", "even_spacing"):
        image = constraint_icon_image(kind, style.icon_rgb, tile, device_px, active)
    else:
        constraint, direction = _AXIS_KINDS[kind]
        image = constraint_icon_image(
            constraint, style.icon_rgb, tile, device_px, active, direction
        )
    pixmap = QtGui.QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    if is_lock and not active:
        # The Sketcher grays a deactivated constraint's icon this way. The
        # view draws a deactivated Lock as a gray dimension, never as an
        # icon with an X, so the list follows the Sketcher here.
        pixmap = QtGui.QIcon(pixmap).pixmap(
            QtCore.QSize(side_px, side_px), ratio, QtGui.QIcon.Mode.Disabled
        )
    icon = QtGui.QIcon(pixmap)
    # A selected row draws its icon in Selected mode, which the style
    # otherwise generates by washing the highlight color over the glyph and
    # its tile. The row highlight already shows the selection, so the icon
    # keeps its colors, leaving the glyph and any corner X as legible as on
    # an unselected row.
    icon.addPixmap(pixmap, QtGui.QIcon.Mode.Selected)
    return icon


class ConstraintList:
    """The Constraints group box and its rows."""

    def __init__(self, actions: ListActions) -> None:
        self._actions = actions
        self.box = QtWidgets.QGroupBox("Constraints")
        layout = QtWidgets.QVBoxLayout(self.box)
        self.tree = QtWidgets.QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(
            QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.tree.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(
            TEXT_COLUMN, QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        for column in (MARK_COLUMN, DELETE_COLUMN):
            header.setSectionResizeMode(
                column, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
            )
        layout.addWidget(self.tree)
        self.delete_deactivated_button = QtWidgets.QPushButton("Delete Deactivated")
        layout.addWidget(self.delete_deactivated_button)
        # The rows the items show, in item order.
        self.rows: tuple[ConstraintRow, ...] = ()
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.delete_deactivated_button.clicked.connect(
            lambda: self._actions.delete_deactivated()
        )
        self._fit_height()

    def _icon_side_px(self) -> int:
        return self.tree.style().pixelMetric(
            QtWidgets.QStyle.PixelMetric.PM_SmallIconSize
        )

    def row_icon(self, row: ConstraintRow) -> QtGui.QIcon:
        """The icon :meth:`show` gives ``row``: its kind's, marked while it
        is deactivated. The Sketcher's list grays such an icon in Qt's
        disabled mode, as a lock row's is; an Equal or even spacing carries
        the 3D view's corner X instead, keeping the list matching the
        view."""
        base = self.tree.palette().color(QtGui.QPalette.ColorRole.Base)
        return kind_icon(
            row.kind,
            self._icon_side_px(),
            self.tree.devicePixelRatioF(),
            base,
            row.active,
        )

    def show(
        self, rows: Sequence[ConstraintRow], constraints: Collection[ConstraintId]
    ) -> None:
        """Show ``rows``, with the rows of the selected ``constraints``
        selected. Rebuilds the items only when the rows' kinds or ids
        changed, so a refresh during a drag or from inside a row's own
        signal keeps them."""
        rows = tuple(rows)
        self.tree.blockSignals(True)
        try:
            if [(r.kind, r.constraint_id) for r in rows] != [
                (r.kind, r.constraint_id) for r in self.rows
            ]:
                self._rebuild(rows)
            for index, row in enumerate(rows):
                item = self.tree.topLevelItem(index)
                if item is None:
                    continue
                self._update(item, row)
                item.setSelected(row.constraint_id in constraints)
            self.rows = rows
        finally:
            self.tree.blockSignals(False)
        self.delete_deactivated_button.setEnabled(any(not r.active for r in rows))
        self._fit_height()

    def _rebuild(self, rows: Sequence[ConstraintRow]) -> None:
        self.tree.clear()
        for row in rows:
            item = QtWidgets.QTreeWidgetItem()
            item.setFlags(
                QtCore.Qt.ItemFlag.ItemIsEnabled
                | QtCore.Qt.ItemFlag.ItemIsSelectable
                | QtCore.Qt.ItemFlag.ItemIsUserCheckable
            )
            self.tree.addTopLevelItem(item)
            button = QtWidgets.QToolButton()
            button.setAutoRaise(True)
            button.setIcon(QtGui.QIcon(_DELETE_ICON))
            button.setToolTip(DELETE_TIP)
            button.setAccessibleName(DELETE_TIP)
            row_id = row.constraint_id
            button.clicked.connect(
                lambda _checked=False, i=row_id: self._actions.delete_constraint(i)
            )
            self.tree.setItemWidget(item, DELETE_COLUMN, button)

    def _update(self, item: QtWidgets.QTreeWidgetItem, row: ConstraintRow) -> None:
        item.setText(TEXT_COLUMN, row_text(row))
        item.setIcon(TEXT_COLUMN, self.row_icon(row))
        item.setCheckState(
            TEXT_COLUMN,
            QtCore.Qt.CheckState.Checked
            if row.active
            else QtCore.Qt.CheckState.Unchecked,
        )
        if row.redundant:
            warning = self.tree.style().standardIcon(
                QtWidgets.QStyle.StandardPixmap.SP_MessageBoxWarning
            )
            item.setIcon(MARK_COLUMN, warning)
            item.setToolTip(TEXT_COLUMN, REDUNDANT_TIP)
            item.setToolTip(MARK_COLUMN, REDUNDANT_TIP)
        else:
            item.setIcon(MARK_COLUMN, QtGui.QIcon())
            item.setToolTip(TEXT_COLUMN, "")
            item.setToolTip(MARK_COLUMN, "")

    def _fit_height(self) -> None:
        """Size the tree to its rows, up to :data:`_MAX_VISIBLE_ROWS`, and to
        one empty row's height when it has none."""
        row_px = self.tree.sizeHintForRow(0)
        if row_px <= 0:
            row_px = (
                max(self._icon_side_px(), self.tree.fontMetrics().height())
                + 2 * TILE_PAD_PX
            )
        visible = min(max(len(self.rows), 1), _MAX_VISIBLE_ROWS)
        frame_px = 2 * self.tree.frameWidth()
        self.tree.setFixedHeight(visible * row_px + frame_px)

    def _item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if column != TEXT_COLUMN:
            return
        index = self.tree.indexOfTopLevelItem(item)
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        checked = item.checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Checked
        if checked != row.active:
            self._actions.set_active(row.constraint_id, checked)

    def _selection_changed(self) -> None:
        """Select in the session the constraints the list's selection
        names."""
        self._actions.select_constraints(
            [
                self.rows[index].constraint_id
                for index in range(len(self.rows))
                if (item := self.tree.topLevelItem(index)) is not None
                and item.isSelected()
            ]
        )
