"""The "Resize Unit" command: rescan the selected container, prompt for a
new outer size, and reapply.

The command id is ``Shelving_ResizeUnit``. ``Gui.addCommand`` runs behind a
headless guard so ``import freecad.Shelving.commands.resize_unit`` succeeds
under ``freecadcmd``; the functional smoke calls
``freecad.Shelving.unit_ops.resize_unit`` directly instead of the command,
which does nothing beyond the selection check, the size prompt, and
wrapping the call in a transaction.
"""

import os
from typing import TYPE_CHECKING, TypedDict, cast

import FreeCAD

from freecad.Shelving.container import WriteResult, read_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.scan import Box
from freecad.Shelving.default_catalog import DEFAULT_CATALOG
from freecad.Shelving.unit_ops import resize_unit

_RESOURCE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources")
_ICON = os.path.join(_RESOURCE_DIR, "shelving.svg")

_CONTAINERS = ("App::Part", "App::LinkGroup", "App::DocumentObjectGroup")

# Loose bounds on the resize dialog's fields, guarding against a stray zero
# or negative entry reaching the solver as an opaque LayoutSolveError
# instead of an obvious dialog-level rejection.
_MIN_DIMENSION_MM = 1.0
_MAX_DIMENSION_MM = 100_000.0
_DIALOG_DECIMALS = 1


class _CommandResources(TypedDict):
    MenuText: str
    ToolTip: str
    Pixmap: str


def _selected_container() -> FreeCAD.DocumentObject | None:
    """The one selected container to resize, or ``None`` when the selection
    is not exactly one ``App::Part``, ``App::LinkGroup``, or group."""
    import FreeCADGui as Gui

    selection = cast("list[FreeCAD.DocumentObject]", Gui.Selection.getSelection())
    if len(selection) == 1 and any(
        selection[0].isDerivedFrom(kind) for kind in _CONTAINERS
    ):
        return selection[0]
    return None


def _measured_extent_mm(boxes: list[Box]) -> Vec3:
    """The outer bounding size across every box in ``boxes``: what the
    resize dialog seeds its fields from, in the same x/y/z = width/depth/
    height convention ``Unit.size_mm`` uses everywhere else."""
    x0_mm = min(b.corner_mm.x_mm for b in boxes)
    x1_mm = max(b.corner_mm.x_mm + b.size_mm.x_mm for b in boxes)
    y0_mm = min(b.corner_mm.y_mm for b in boxes)
    y1_mm = max(b.corner_mm.y_mm + b.size_mm.y_mm for b in boxes)
    z0_mm = min(b.corner_mm.z_mm for b in boxes)
    z1_mm = max(b.corner_mm.z_mm + b.size_mm.z_mm for b in boxes)
    return Vec3(x1_mm - x0_mm, y1_mm - y0_mm, z1_mm - z0_mm)


def _prompt_dimension_mm(label: str, current_mm: float) -> float | None:
    """``label``'s value from a modal number dialog seeded at ``current_mm``,
    or ``None`` when the user cancels. PySide has no type stubs in this
    project's environment, so ``getDouble``'s return is coerced to
    ``float``/``bool`` immediately rather than left as ``Any``."""
    import FreeCADGui as Gui
    from PySide import QtWidgets  # type: ignore[import-not-found]

    raw_value, raw_ok = QtWidgets.QInputDialog.getDouble(
        Gui.getMainWindow(),
        "Resize Unit",
        f"{label} (mm)",
        current_mm,
        _MIN_DIMENSION_MM,
        _MAX_DIMENSION_MM,
        _DIALOG_DECIMALS,
    )
    if not bool(raw_ok):
        return None
    return float(raw_value)


def _prompt_size_mm(current_mm: Vec3) -> Vec3 | None:
    """The three-field width/depth/height prompt, or ``None`` if the user
    cancels any one of them."""
    width_mm = _prompt_dimension_mm("Width", current_mm.x_mm)
    if width_mm is None:
        return None
    depth_mm = _prompt_dimension_mm("Depth", current_mm.y_mm)
    if depth_mm is None:
        return None
    height_mm = _prompt_dimension_mm("Height", current_mm.z_mm)
    if height_mm is None:
        return None
    return Vec3(width_mm, depth_mm, height_mm)


def _report(result: WriteResult) -> None:
    print(
        f"updated {len(result.updated)}, created {len(result.created)}, "
        f"deleted {len(result.deleted)}, left alone {len(result.left_alone)}"
    )
    if result.left_alone:
        print("left alone: " + ", ".join(result.left_alone))


class ResizeUnitCommand:
    """`Gui.Command` that rescans the selected container, prompts for a new
    outer size, and applies it, in one undo transaction."""

    def GetResources(self) -> _CommandResources:
        return {
            "MenuText": "Resize Unit",
            "ToolTip": "Rescan the selected unit and apply a new outer size",
            "Pixmap": _ICON,
        }

    def IsActive(self) -> bool:
        return bool(FreeCAD.ActiveDocument) and _selected_container() is not None

    def Activated(self) -> None:
        container = _selected_container()
        if container is None:
            print(
                "REFUSED: select exactly one App::Part, App::LinkGroup, or "
                "group to resize"
            )
            return
        boxes, _skipped, _record = read_container(container)
        if not boxes:
            print("REFUSED: the selected container holds no readable boards")
            return
        size_mm = _prompt_size_mm(_measured_extent_mm(boxes))
        if size_mm is None:
            return
        doc = container.Document
        doc.openTransaction("Resize Shelving Unit")  # type: ignore[no-untyped-call]
        try:
            result = resize_unit(container, size_mm, DEFAULT_CATALOG)
            doc.recompute()
        except Exception as err:  # noqa: BLE001 - report, don't crash the GUI
            doc.abortTransaction()  # type: ignore[no-untyped-call]
            print(f"REFUSED: {err}")
            return
        doc.commitTransaction()  # type: ignore[no-untyped-call]
        _report(result)


if not TYPE_CHECKING:
    try:
        import FreeCADGui as Gui
    except ImportError:
        Gui = None
    else:
        # freecadcmd exposes a FreeCADGui stub without the command registry.
        if not hasattr(Gui, "addCommand"):
            Gui = None
    if Gui is not None:
        Gui.addCommand("Shelving_ResizeUnit", ResizeUnitCommand())
