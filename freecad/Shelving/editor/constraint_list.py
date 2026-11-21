"""The task panel's Constraints group: one row per lock and per Equal or
even spacing, in the manner of the Sketcher's constraint list.

The widget holds no layout logic. :meth:`ConstraintList.show` takes the
session's row snapshot and selection, and every user action goes out
through a :class:`ListActions` callback, after which the panel refreshes
the list from the session again.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass

import FreeCAD
from PySide6 import QtCore, QtGui, QtWidgets

from freecad.Shelving.core.layout import ConstraintId
from freecad.Shelving.editor.elevation import ConstraintKind
from freecad.Shelving.editor.overlay import (
    TILE_PAD_PX,
    Tile,
    constraint_icon_image,
    padlock_image,
    view_style,
)
from freecad.Shelving.editor.session import ConstraintRow, ListRow, LockRow

_KIND_NAMES: dict[ConstraintKind | None, str] = {
    None: "Lock",
    "equal": "Equal",
    "even_spacing": "Even spacing",
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
    # Removes a constraint, or unlocks a lock row's opening.
    delete_row: Callable[[ListRow], None]
    delete_deactivated: Callable[[], None]
    select_constraints: Callable[[Sequence[ConstraintId]], None]
    select_openings: Callable[[Sequence[str]], None]


def _kind(row: ListRow) -> ConstraintKind | None:
    return row.kind if isinstance(row, ConstraintRow) else None


def _row_id(row: ListRow) -> str:
    return row.constraint_id if isinstance(row, ConstraintRow) else row.region_id


def row_text(row: ListRow) -> str:
    """The row's kind name, followed by its size in the user's unit system
    while it has one."""
    name = _KIND_NAMES[_kind(row)]
    if row.size_mm is None:
        return name
    size = FreeCAD.Units.Quantity(row.size_mm, FreeCAD.Units.Length).UserString
    return f"{name} ({size})"


def kind_icon(
    kind: ConstraintKind | None,
    side_px: int,
    ratio: float,
    base: QtGui.QColor,
    active: bool = True,
) -> QtGui.QIcon:
    """A row's icon, ``side_px`` logical pixels square at device pixel
    ratio ``ratio``: the 3D view's closed padlock for a lock (``None``),
    else the constraint's own icon with the view's corner X unless
    ``active``, each in the view's color for it on a tile of ``base``, the
    list's own background. ``active`` has no effect on a padlock."""
    device_px = round(side_px * ratio)
    tile = Tile(
        (base.redF(), base.greenF(), base.blueF()), round(TILE_PAD_PX * ratio), 0.0
    )
    # Only the colors are read, so the text size does not matter.
    style = view_style(0)
    if kind is None:
        image = padlock_image(True, style.locked_rgb, tile, device_px)
    else:
        image = constraint_icon_image(kind, style.icon_rgb, tile, device_px, active)
    pixmap = QtGui.QPixmap.fromImage(image)
    pixmap.setDevicePixelRatio(ratio)
    icon = QtGui.QIcon(pixmap)
    # A selected row draws its icon in Selected mode, which the style
    # otherwise generates by washing the highlight color over the glyph and
    # its tile. The view's icons are never tinted, so the list's keep their
    # colors too.
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
        self.rows: tuple[ListRow, ...] = ()
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

    def row_icon(self, row: ListRow) -> QtGui.QIcon:
        """The icon :meth:`show` gives ``row``: its kind's, marked with the
        3D view's corner X while it is a deactivated constraint. The
        Sketcher's list grays such an icon in Qt's disabled mode; the X
        keeps the list matching the view."""
        base = self.tree.palette().color(QtGui.QPalette.ColorRole.Base)
        active = not isinstance(row, ConstraintRow) or row.active
        return kind_icon(
            _kind(row),
            self._icon_side_px(),
            self.tree.devicePixelRatioF(),
            base,
            active,
        )

    def show(
        self,
        rows: Sequence[ListRow],
        constraints: Collection[ConstraintId],
        openings: Collection[str],
    ) -> None:
        """Show ``rows``, with the rows of the selected ``constraints`` and
        of the locked selected ``openings`` selected. Rebuilds the items only
        when the rows' kinds or ids changed, so a refresh during a drag or
        from inside a row's own signal keeps them."""
        rows = tuple(rows)
        self.tree.blockSignals(True)
        try:
            if [(_kind(r), _row_id(r)) for r in rows] != [
                (_kind(r), _row_id(r)) for r in self.rows
            ]:
                self._rebuild(rows)
            for index, row in enumerate(rows):
                item = self.tree.topLevelItem(index)
                if item is None:
                    continue
                self._update(item, row)
                item.setSelected(
                    row.constraint_id in constraints
                    if isinstance(row, ConstraintRow)
                    else row.region_id in openings
                )
            self.rows = rows
        finally:
            self.tree.blockSignals(False)
        self.delete_deactivated_button.setEnabled(
            any(isinstance(r, ConstraintRow) and not r.active for r in rows)
        )
        self._fit_height()

    def _rebuild(self, rows: Sequence[ListRow]) -> None:
        self.tree.clear()
        for row in rows:
            item = QtWidgets.QTreeWidgetItem()
            flags = (
                QtCore.Qt.ItemFlag.ItemIsEnabled | QtCore.Qt.ItemFlag.ItemIsSelectable
            )
            if isinstance(row, ConstraintRow):
                flags |= QtCore.Qt.ItemFlag.ItemIsUserCheckable
            item.setFlags(flags)
            self.tree.addTopLevelItem(item)
            button = QtWidgets.QToolButton()
            button.setAutoRaise(True)
            button.setIcon(QtGui.QIcon(_DELETE_ICON))
            button.setToolTip(DELETE_TIP)
            button.setAccessibleName(DELETE_TIP)
            row_id = _row_id(row)
            button.clicked.connect(lambda _checked=False, i=row_id: self._delete(i))
            self.tree.setItemWidget(item, DELETE_COLUMN, button)

    def _update(self, item: QtWidgets.QTreeWidgetItem, row: ListRow) -> None:
        item.setText(TEXT_COLUMN, row_text(row))
        item.setIcon(TEXT_COLUMN, self.row_icon(row))
        if isinstance(row, ConstraintRow):
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

    def _delete(self, row_id: str) -> None:
        row = next((r for r in self.rows if _row_id(r) == row_id), None)
        if row is not None:
            self._actions.delete_row(row)

    def _item_changed(self, item: QtWidgets.QTreeWidgetItem, column: int) -> None:
        if column != TEXT_COLUMN:
            return
        index = self.tree.indexOfTopLevelItem(item)
        if not 0 <= index < len(self.rows):
            return
        row = self.rows[index]
        if not isinstance(row, ConstraintRow):
            return
        checked = item.checkState(TEXT_COLUMN) == QtCore.Qt.CheckState.Checked
        if checked != row.active:
            self._actions.set_active(row.constraint_id, checked)

    def _selection_changed(self) -> None:
        """Select in the session what the list's selection names. The row
        clicked last decides the kind, so picking a lock row drops the
        constraint rows and the reverse, as the view never mixes them."""
        selected = [
            self.rows[index]
            for index in range(len(self.rows))
            if (item := self.tree.topLevelItem(index)) is not None and item.isSelected()
        ]
        current = self.tree.currentItem()
        index = -1 if current is None else self.tree.indexOfTopLevelItem(current)
        lead = self.rows[index] if 0 <= index < len(self.rows) else None
        if isinstance(lead, LockRow) or (
            lead is None and all(isinstance(r, LockRow) for r in selected)
        ):
            self._actions.select_openings(
                [r.region_id for r in selected if isinstance(r, LockRow)]
            )
            return
        self._actions.select_constraints(
            [r.constraint_id for r in selected if isinstance(r, ConstraintRow)]
        )
