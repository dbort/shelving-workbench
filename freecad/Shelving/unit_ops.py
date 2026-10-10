"""Plain functions behind the create and resize commands, and a rescan.

Kept out of the command classes, not merely called by them, so
``tests/freecad/test_write.py`` can call each operation directly without
going through ``Gui``: the commands register only where FreeCAD's GUI does
(see ``freecad/Shelving/init_gui.py``), and testing the behavior only
through them would mean it is never tested headless. Each of
``create_unit``, ``resize_unit``, and ``rescan_unit`` calls
``freecad.Shelving.container.write_container`` exactly once and returns its
``WriteResult`` so a caller (a command's ``Activated``, or a test) can
report what happened.

``resize_unit`` and ``rescan_unit`` never cache a model between calls: both
start from :func:`_rescanned_unit`, which reads the container fresh and
scans it. A cached tree goes stale the moment a user moves a board by hand
between commands, and applying a stale tree is how apply would delete
something added since the last read.
"""

import dataclasses
from typing import cast

import FreeCAD

from freecad.Shelving import properties
from freecad.Shelving.container import WriteResult, read_container, write_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Axis, Bay, Board, Division, Unit
from freecad.Shelving.core.record import rules_from_json, with_stored_rules
from freecad.Shelving.core.scan import scan

# Shelving_CreateUnit's starting point: a single enclosed bay, closed on
# every side, that Shelving_ResizeUnit reshapes from there. The values
# themselves carry no significance beyond being a plausible starting size.
_DEFAULT_WIDTH_MM = 600.0
_DEFAULT_DEPTH_MM = 300.0
_DEFAULT_HEIGHT_MM = 900.0
# The Woodworking workbench's Magic Start look: its board thickness and its
# default board color. The boards keep the material FreeCAD gives a new
# object, the same Default material Magic Start's boards carry.
_DEFAULT_THICKNESS_MM = 18.0
_DEFAULT_RGB = (247, 185, 108)


def _default_unit() -> Unit:
    """A closed single-bay unit at :func:`create_unit`'s fixed defaults: a
    bottom and top running the full width, two sides captured between them,
    one open bay. The carcass shell is not a distinguished rule in the core
    model, so this is an ordinary four-board ``Division`` tree, the
    same shape ``freecad.Shelving.core.tests.test_expand``'s ``_closed_box``
    fixture builds."""
    return Unit(
        size_mm=Vec3(_DEFAULT_WIDTH_MM, _DEFAULT_DEPTH_MM, _DEFAULT_HEIGHT_MM),
        root=Division(
            axis=Axis.Z,
            items=[
                Board(thickness_mm=_DEFAULT_THICKNESS_MM, role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(thickness_mm=_DEFAULT_THICKNESS_MM, role="left_side"),
                        Bay(),
                        Board(thickness_mm=_DEFAULT_THICKNESS_MM, role="right_side"),
                    ],
                ),
                Board(thickness_mm=_DEFAULT_THICKNESS_MM, role="top"),
            ],
        ),
        depth_axis=Axis.Y,
        # Unknown, not guessed: a freshly created unit has nothing in the
        # room to tell front from back, and a wrong guess baked into every
        # future label would be worse than "undetermined".
        front_at_min=None,
    )


def create_unit(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    """Build a new ``App::Part``, seed it with a closed single-bay unit of
    18 mm boards at fixed defaults, and return the container. With a GUI,
    every board is painted Magic Start's default board color."""
    container = cast(
        "FreeCAD.DocumentObject", doc.addObject("App::Part", "ShelvingUnit")
    )
    result = write_container(container, _default_unit())
    for name in result.created:
        properties.paint(doc.getObject(name), _DEFAULT_RGB)
    return container


def _rescanned_unit(container: FreeCAD.DocumentObject) -> Unit:
    """``container`` read fresh and scanned, with its stored rules and unit
    id reapplied: the common starting point for :func:`resize_unit` and
    :func:`rescan_unit`, a resize being a rescan that also substitutes the
    outer size."""
    boxes, skipped, record = read_container(container)
    scan_result = scan(
        boxes,
        skipped=skipped,
        depth_axis=record.depth_axis,
        front_at_min=record.front_at_min,
    )
    unit = scan_result.unit
    if record.rules_json is not None:
        unit = with_stored_rules(unit, rules_from_json(record.rules_json))
    if record.unit_id is not None:
        unit = dataclasses.replace(unit, id=record.unit_id)
    return unit


def unit_size_mm(container: FreeCAD.DocumentObject) -> Vec3:
    """``container``'s outer size as the scan grid measures it, leaving out
    every part the scan sets aside, such as a back panel. Raises
    ``ScanError`` when the container does not scan, and ``ValueError`` when
    its stored rule record is malformed."""
    return _rescanned_unit(container).size_mm


def resize_unit(container: FreeCAD.DocumentObject, size_mm: Vec3) -> WriteResult:
    """Rescan ``container``, substitute ``size_mm`` for its outer size, and
    write the result back."""
    unit = dataclasses.replace(_rescanned_unit(container), size_mm=size_mm)
    return write_container(container, unit)


def rescan_unit(container: FreeCAD.DocumentObject) -> WriteResult:
    """Rescan ``container`` and write the result straight back: the reflow
    a hand edit needs, with no size change of its own."""
    return write_container(container, _rescanned_unit(container))
