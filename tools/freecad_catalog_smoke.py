"""Headless functional check for the material catalog: the document object
layer in ``freecad.Shelving.catalog`` and the reflow that makes a changed
entry reach the boards using it.

Run via ``freecadcmd tools/freecad_catalog_smoke.py``. Not a self-invoking
pytest module like ``tools/freecad_scan_smoke.py`` and
``tools/freecad_write_smoke.py``: a straight-line script of assertions that
prints ``shelving catalog OK`` on success, in the shape
``tools/freecad_smoke.py`` used before it was folded into
``freecad_scan_smoke.py`` (``git log`` still has it). ``freecadcmd`` does
not propagate an uncaught exception's exit status
(``docs/freecadcmd-notes.md``), so the printed marker line, which
``tools/run-tests.sh`` greps for, is the success signal, not the process
exit code.

Each case builds its own document, closed before the next one starts,
except the milestone case (``_case_reflow_all_rewrites_the_changed_material``),
which needs two containers in one document, matching the Must Have's own
wording ("a document holding two units").
"""

import os
import sys
import tempfile
import zipfile
from typing import cast

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import FreeCAD  # noqa: E402

from freecad.Shelving import properties  # noqa: E402
from freecad.Shelving.catalog import (  # noqa: E402
    add_entry,
    ensure_catalog,
    find_catalog,
    read_catalog,
    seed_catalog,
)
from freecad.Shelving.container import read_container, write_container  # noqa: E402
from freecad.Shelving.core.geometry import Vec3  # noqa: E402
from freecad.Shelving.core.layout import Axis, Bay, Board, Division, Unit  # noqa: E402
from freecad.Shelving.core.materials import MaterialId  # noqa: E402
from freecad.Shelving.core.scan import Box, ScanError, scan  # noqa: E402
from freecad.Shelving.default_catalog import DEFAULT_CATALOG  # noqa: E402
from freecad.Shelving.unit_ops import create_unit, reflow_all  # noqa: E402

_TOL_MM = 1e-6


def _new_document(name: str) -> FreeCAD.Document:
    return FreeCAD.newDocument(name)


def _thin_axis_mm(box: Box) -> float:
    return min(box.size_mm.x_mm, box.size_mm.y_mm, box.size_mm.z_mm)


def _bounding_extent_mm(boxes: list[Box]) -> Vec3:
    x0_mm = min(b.corner_mm.x_mm for b in boxes)
    x1_mm = max(b.corner_mm.x_mm + b.size_mm.x_mm for b in boxes)
    y0_mm = min(b.corner_mm.y_mm for b in boxes)
    y1_mm = max(b.corner_mm.y_mm + b.size_mm.y_mm for b in boxes)
    z0_mm = min(b.corner_mm.z_mm for b in boxes)
    z1_mm = max(b.corner_mm.z_mm + b.size_mm.z_mm for b in boxes)
    return Vec3(x1_mm - x0_mm, y1_mm - y0_mm, z1_mm - z0_mm)


def _closed_box_unit(size_mm: Vec3, material_id: MaterialId) -> Unit:
    """The same closed single-bay shape ``unit_ops._default_unit`` builds,
    except every board carries ``material_id`` explicitly rather than
    inheriting ``Unit.default_material`` silently: a stored id is what lets
    a rescan resolve a board by preference over thickness matching (see
    ``freecad.Shelving.core.scan._resolve_material``), which is the whole
    mechanism this smoke's milestone case depends on.
    """
    return Unit(
        size_mm=size_mm,
        default_material=material_id,
        root=Division(
            axis=Axis.Z,
            items=[
                Board(role="bottom", material=material_id),
                Division(
                    axis=Axis.X,
                    items=[
                        Board(role="left_side", material=material_id),
                        Bay(),
                        Board(role="right_side", material=material_id),
                    ],
                ),
                Board(role="top", material=material_id),
            ],
        ),
        depth_axis=Axis.Y,
        front_at_min=None,
    )


def _catalog_groups_in(doc: FreeCAD.Document) -> list[FreeCAD.DocumentObject]:
    return [
        obj
        for obj in doc.Objects
        if obj.isDerivedFrom("App::DocumentObjectGroup")
        and properties.has_catalog_marker(obj)
    ]


def _entry_by_material_id(
    group: FreeCAD.DocumentObject, material_id: MaterialId
) -> FreeCAD.DocumentObject:
    for obj in cast("FreeCAD.DocumentObjectGroup", group).Group:
        if properties.read_entry_material_id(obj) == material_id:
            return obj
    raise AssertionError(f"no catalog entry {material_id!r} in {group.Name!r}")


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


def _case_ensure_catalog_seeds_and_is_idempotent() -> None:
    doc = _new_document("catalog_smoke_seed")
    try:
        assert find_catalog(doc) is None
        group = ensure_catalog(doc)
        assert group.TypeId == "App::DocumentObjectGroup"
        assert properties.has_catalog_marker(group)
        entries = cast("FreeCAD.DocumentObjectGroup", group).Group
        assert len(entries) == len(DEFAULT_CATALOG.entries), entries
        for entry in entries:
            assert entry.TypeId == "App::VarSet", entry.TypeId
        ids = {properties.read_entry_material_id(e) for e in entries}
        assert ids == set(DEFAULT_CATALOG.entries.keys()), ids

        again = ensure_catalog(doc)
        assert again.Name == group.Name
        assert len(_catalog_groups_in(doc)) == 1
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_seed_catalog_is_found_by_find_catalog() -> None:
    doc = _new_document("catalog_smoke_seed_direct")
    try:
        group = seed_catalog(doc)
        assert find_catalog(doc) is group
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_read_catalog_reproduces_the_default() -> None:
    doc = _new_document("catalog_smoke_read")
    try:
        catalog = read_catalog(ensure_catalog(doc))
        assert dict(catalog.entries) == dict(DEFAULT_CATALOG.entries)
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_two_marked_groups_make_find_catalog_raise() -> None:
    doc = _new_document("catalog_smoke_two_groups")
    try:
        first = ensure_catalog(doc)
        second = cast(
            "FreeCAD.DocumentObject",
            doc.addObject("App::DocumentObjectGroup", "SecondCatalog"),
        )
        properties.ensure_catalog_group_properties(second)
        try:
            find_catalog(doc)
        except ValueError as err:
            assert first.Name in str(err), err
            assert second.Name in str(err), err
        else:
            raise AssertionError("expected find_catalog to raise on two catalogs")
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_duplicate_material_id_raises() -> None:
    """A copied entry, the realistic way a duplicate arises (the mirror of
    the board copy problem sh-018 handles): ``doc.copyObject`` duplicates
    the entry's ``MaterialId`` verbatim along with everything else."""
    doc = _new_document("catalog_smoke_duplicate_id")
    try:
        group = ensure_catalog(doc)
        original = _entry_by_material_id(group, MaterialId("ply18"))
        raw_copy = cast("FreeCAD.DocumentObject", doc.copyObject(original, False))
        cast("FreeCAD.DocumentObjectGroup", group).addObject(raw_copy)
        try:
            read_catalog(group)
        except ValueError as err:
            assert original.Name in str(err), err
            assert raw_copy.Name in str(err), err
        else:
            raise AssertionError("expected read_catalog to raise on a duplicate id")
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_add_entry_is_blank_and_blocks_read_catalog_until_edited() -> None:
    doc = _new_document("catalog_smoke_add_entry")
    try:
        group = ensure_catalog(doc)
        before = len(cast("FreeCAD.DocumentObjectGroup", group).Group)
        new_entry = add_entry(group)
        after = len(cast("FreeCAD.DocumentObjectGroup", group).Group)
        assert after == before + 1
        assert properties.read_entry_material_id(new_entry) is not None
        assert properties.read_entry_thickness_mm(new_entry) == 0.0
        try:
            read_catalog(group)
        except ValueError as err:
            assert new_entry.Name in str(err), err
        else:
            raise AssertionError("expected read_catalog to raise on a zero Thickness")

        # Editing it the way a user would, through the property editor,
        # clears the refusal.
        properties.write_entry_thickness_mm(
            cast("properties.CatalogEntryObject", new_entry), 6.0
        )
        catalog = read_catalog(group)
        new_id = properties.read_entry_material_id(new_entry)
        assert new_id is not None
        assert catalog[new_id].thickness_mm == 6.0
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_create_unit_seeds_catalog_and_uses_it() -> None:
    doc = _new_document("catalog_smoke_create_unit")
    try:
        assert find_catalog(doc) is None
        container = create_unit(doc)
        doc.recompute()
        group = find_catalog(doc)
        assert group is not None
        catalog = read_catalog(group)
        boxes, skipped, _record = read_container(container)
        assert len(boxes) == 4, boxes
        assert len(skipped) == 0, skipped
        ply18_thickness_mm = catalog[MaterialId("ply18")].thickness_mm
        for box in boxes:
            assert abs(_thin_axis_mm(box) - ply18_thickness_mm) < _TOL_MM
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_unknown_material_refuses_at_scan() -> None:
    doc = _new_document("catalog_smoke_unknown_material")
    try:
        container = create_unit(doc)
        doc.recompute()
        bottom = doc.getObject("bottom")
        tagged = properties.ensure_board_properties(bottom)
        properties.write_board_material(tagged, MaterialId("doesnotexist"))
        doc.recompute()

        boxes, skipped, record = read_container(container)
        assert len(skipped) == 0, skipped
        catalog_group = find_catalog(doc)
        assert catalog_group is not None
        catalog = read_catalog(catalog_group)
        try:
            scan(
                boxes,
                catalog,
                skipped=skipped,
                depth_axis=record.depth_axis,
                front_at_min=record.front_at_min,
            )
        except ScanError as err:
            assert "bottom" in err.objects, err.objects
        else:
            raise AssertionError("expected scan to refuse an unknown material id")
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_reflow_all_rewrites_the_changed_material() -> None:
    """The milestone's point: a document with two units, one of which
    cannot absorb the growth, checked against catalog.py's ``PLY18`` entry
    growing from 18 mm to 25 mm."""
    doc = _new_document("catalog_smoke_reflow")
    try:
        group = ensure_catalog(doc)
        catalog_before = read_catalog(group)
        ply18 = MaterialId("ply18")

        container_ok = cast(
            "FreeCAD.DocumentObject", doc.addObject("App::Part", "UnitOK")
        )
        write_container(
            container_ok,
            _closed_box_unit(Vec3(600.0, 300.0, 900.0), ply18),
            catalog_before,
        )
        # 40mm wide: two 18mm sides leave a 4mm bay, valid; two 25mm sides
        # would need 50mm, which does not fit, so this one refuses to reflow.
        container_tight = cast(
            "FreeCAD.DocumentObject", doc.addObject("App::Part", "UnitTight")
        )
        write_container(
            container_tight,
            _closed_box_unit(Vec3(40.0, 200.0, 200.0), ply18),
            catalog_before,
        )
        doc.recompute()

        boxes_ok_before, skipped_ok_before, _r = read_container(container_ok)
        assert len(skipped_ok_before) == 0, skipped_ok_before
        extent_before = _bounding_extent_mm(boxes_ok_before)
        for box in boxes_ok_before:
            assert abs(_thin_axis_mm(box) - 18.0) < _TOL_MM

        boxes_tight_before, _s, _r = read_container(container_tight)
        for box in boxes_tight_before:
            assert abs(_thin_axis_mm(box) - 18.0) < _TOL_MM

        entry = _entry_by_material_id(group, ply18)
        properties.write_entry_thickness_mm(
            cast("properties.CatalogEntryObject", entry), 25.0
        )
        catalog_after = read_catalog(group)
        assert catalog_after[ply18].thickness_mm == 25.0

        result = reflow_all(doc, catalog_after)
        doc.recompute()

        succeeded_names = {name for name, _write_result in result.succeeded}
        failed_by_name = dict(result.failed)
        assert container_ok.Name in succeeded_names, result.succeeded
        assert container_tight.Name in failed_by_name, result.failed
        assert failed_by_name[container_tight.Name]

        boxes_ok_after, skipped_ok_after, _r = read_container(container_ok)
        assert len(skipped_ok_after) == 0, skipped_ok_after
        for box in boxes_ok_after:
            assert abs(_thin_axis_mm(box) - 25.0) < _TOL_MM
        extent_after = _bounding_extent_mm(boxes_ok_after)
        assert abs(extent_after.x_mm - extent_before.x_mm) < _TOL_MM
        assert abs(extent_after.y_mm - extent_before.y_mm) < _TOL_MM
        assert abs(extent_after.z_mm - extent_before.z_mm) < _TOL_MM

        # The refused unit's boards are untouched: write_container's own
        # expand() call raises before any board object is mutated.
        boxes_tight_after, _s, _r = read_container(container_tight)
        for box in boxes_tight_after:
            assert abs(_thin_axis_mm(box) - 18.0) < _TOL_MM
    finally:
        FreeCAD.closeDocument(doc.Name)


def _case_saved_document_has_no_proxy_and_reopens() -> None:
    doc = _new_document("catalog_smoke_reopen")
    tmp_dir = tempfile.mkdtemp(prefix="shelving_catalog_smoke_")
    path = os.path.join(tmp_dir, "catalog_smoke_reopen.FCStd")
    try:
        create_unit(doc)
        doc.recompute()
        doc.saveAs(path)
    finally:
        FreeCAD.closeDocument(doc.Name)

    with zipfile.ZipFile(path) as archive:
        xml = archive.read("Document.xml").decode("utf-8")
    for forbidden in ("Proxy", "FeaturePython", "PythonObject"):
        assert forbidden not in xml, forbidden

    reopened = FreeCAD.openDocument(path)
    try:
        group = find_catalog(reopened)
        assert group is not None
        catalog = read_catalog(group)
        assert dict(catalog.entries) == dict(DEFAULT_CATALOG.entries)
        container = cast("FreeCAD.DocumentObject", reopened.getObject("ShelvingUnit"))
        boxes, skipped, _record = read_container(container)
        assert len(boxes) == 4, boxes
        assert len(skipped) == 0, skipped
    finally:
        FreeCAD.closeDocument(reopened.Name)


_CASES = (
    _case_ensure_catalog_seeds_and_is_idempotent,
    _case_seed_catalog_is_found_by_find_catalog,
    _case_read_catalog_reproduces_the_default,
    _case_two_marked_groups_make_find_catalog_raise,
    _case_duplicate_material_id_raises,
    _case_add_entry_is_blank_and_blocks_read_catalog_until_edited,
    _case_create_unit_seeds_catalog_and_uses_it,
    _case_unknown_material_refuses_at_scan,
    _case_reflow_all_rewrites_the_changed_material,
    _case_saved_document_has_no_proxy_and_reopens,
)


def main() -> None:
    for case in _CASES:
        print(f"-- {case.__name__}")
        case()
    print("shelving catalog OK")
    sys.stdout.flush()


main()
