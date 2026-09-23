"""Plain functions behind the create/resize/rescan/reflow commands.

Kept out of the command classes, not merely called by them, so
``tools/freecad_write_smoke.py`` can call each operation directly without
going through ``Gui``: command modules are guarded from import under
``freecadcmd`` (see ``freecad/Shelving/init_gui.py``), and testing the
actual behavior through that guard would mean the smoke never runs
headless. Each of ``create_unit``, ``resize_unit``, and ``rescan_unit``
calls ``freecad.Shelving.container.write_container`` exactly once and
returns its ``WriteResult`` so a caller (a command's ``Activated``, or a
test) can report what happened; ``reflow_all`` calls ``rescan_unit`` once
per tagged container and collects the results.

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
from freecad.Shelving.catalog import ensure_catalog, read_usable_catalog
from freecad.Shelving.container import WriteResult, read_container, write_container
from freecad.Shelving.core.geometry import Vec3
from freecad.Shelving.core.layout import Axis, Bay, Board, Division, Unit
from freecad.Shelving.core.materials import Catalog
from freecad.Shelving.core.record import rules_from_json, with_stored_rules
from freecad.Shelving.core.scan import scan
from freecad.Shelving.default_catalog import DEFAULT_MATERIAL_ID

# Shelving_CreateUnit's starting point: a single enclosed bay, closed on
# every side, that Shelving_ResizeUnit reshapes from there. The values
# themselves carry no significance beyond being a plausible starting size.
_DEFAULT_WIDTH_MM = 600.0
_DEFAULT_DEPTH_MM = 300.0
_DEFAULT_HEIGHT_MM = 900.0


def _default_unit() -> Unit:
    """A closed single-bay unit at :func:`create_unit`'s fixed defaults: a
    bottom and top running the full width, two sides captured between them,
    one open bay. The carcass shell is not a distinguished rule in the core
    model, so this is an ordinary four-board ``Division`` tree, the
    same shape ``freecad.Shelving.core.tests.test_expand``'s ``_closed_box``
    fixture builds."""
    return Unit(
        size_mm=Vec3(_DEFAULT_WIDTH_MM, _DEFAULT_DEPTH_MM, _DEFAULT_HEIGHT_MM),
        default_material=DEFAULT_MATERIAL_ID,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom"),
                Division(
                    axis=Axis.X,
                    items=[Board(role="left_side"), Bay(), Board(role="right_side")],
                ),
                Board(role="top"),
            ],
        ),
        depth_axis=Axis.Y,
        # Unknown, not guessed: a freshly created unit has nothing in the
        # room to tell front from back, and a wrong guess baked into every
        # future label would be worse than "undetermined".
        front_at_min=None,
    )


def create_unit(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    """Build a new ``App::Part``, seed it with a closed single-bay unit at
    fixed defaults, and return the container. Against ``ensure_catalog(doc)``,
    seeding the document's catalog from ``freecad.Shelving.default_catalog``
    the first time this runs, which is what makes Create Unit work on an
    empty document with no setup. There is no per-call catalog parameter
    because there is only ever one catalog per document to build the
    starting point from."""
    container = cast(
        "FreeCAD.DocumentObject", doc.addObject("App::Part", "ShelvingUnit")
    )
    # read_usable_catalog, not read_catalog: an unrelated incomplete entry
    # elsewhere in the document must not stop a brand-new unit that never
    # references it (see catalog.py's docstring).
    catalog, _skipped_catalog_entries = read_usable_catalog(ensure_catalog(doc))
    write_container(container, _default_unit(), catalog)
    return container


def _rescanned_unit(container: FreeCAD.DocumentObject, catalog: Catalog) -> Unit:
    """``container`` read fresh, scanned against ``catalog``, with its
    stored rules and unit id reapplied: the common starting point for
    :func:`resize_unit` and :func:`rescan_unit`, a resize being a rescan
    that also substitutes the outer size."""
    boxes, skipped, record = read_container(container)
    scan_result = scan(
        boxes,
        catalog,
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


def resize_unit(
    container: FreeCAD.DocumentObject, size_mm: Vec3, catalog: Catalog
) -> WriteResult:
    """Rescan ``container``, substitute ``size_mm`` for its outer size, and
    write the result back."""
    unit = dataclasses.replace(_rescanned_unit(container, catalog), size_mm=size_mm)
    return write_container(container, unit, catalog)


def rescan_unit(container: FreeCAD.DocumentObject, catalog: Catalog) -> WriteResult:
    """Rescan ``container`` and write the result straight back: the reflow
    a hand edit needs, with no size change of its own."""
    return write_container(container, _rescanned_unit(container, catalog), catalog)


@dataclasses.dataclass(frozen=True)
class ReflowResult:
    """What :func:`reflow_all` did across every unit in one document.

    A unit that fails is absent from ``succeeded`` and present in
    ``failed``, never both.
    """

    # Each succeeded container's own Name paired with its WriteResult.
    succeeded: tuple[tuple[str, WriteResult], ...]
    # Each failed container's own Name paired with its refusal message.
    failed: tuple[tuple[str, str], ...]


def reflow_all(doc: FreeCAD.Document, catalog: Catalog) -> ReflowResult:
    """Rescan and rewrite every container in ``doc`` that carries a
    ``ShelvingUnitId`` against ``catalog``, which is what makes a changed
    catalog entry (a thickness edit, most commonly) reach the boards using
    it.

    A unit whose layout refuses does not stop the others: its error is
    collected into ``ReflowResult.failed`` and the scan moves on, so one bad
    unit never hides every other unit's report. Opens no transaction; the
    caller owns that, the same as :func:`rescan_unit`.
    """
    succeeded: list[tuple[str, WriteResult]] = []
    failed: list[tuple[str, str]] = []
    for obj in doc.Objects:
        if properties.read_container_unit_id(obj) is None:
            continue
        try:
            result = rescan_unit(obj, catalog)
        except Exception as err:  # noqa: BLE001 - collected per unit, not fatal
            failed.append((obj.Name, str(err)))
            continue
        succeeded.append((obj.Name, result))
    return ReflowResult(succeeded=tuple(succeeded), failed=tuple(failed))
