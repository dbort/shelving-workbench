"""`ShelvingUnit`: the container that turns one serialised `Carcass` into planks.

The container is an `App::Part`, kept for `Placement`, `App::Link`, and Assembly
compatibility, holding one `App::FeaturePython` child named `ShelvingUnitDriver`.
FreeCAD 1.0 dispatches no `Proxy.execute` on a recomputing `App::Part`
(`docs/freecadcmd-notes.md` § "`App::Part` does not call a Python
`Proxy.execute`"), so the driver child carries the promoted properties, the
hidden `Layout` JSON, and the `execute` that expands the carcass and reconciles
the plank children into the `App::Part`.
"""

from typing import cast

import FreeCAD
from freecad.shelving.default_catalog import (
    DEFAULT_CATALOG,
    DEFAULT_CATALOG_IDS,
    DEFAULT_MATERIAL_ID,
)
from freecad.shelving.objects.feature_types import PlankFeature, ShelvingUnitFeature
from freecad.shelving.objects.labels import generated_label
from freecad.shelving.objects.plank import add_plank

# The vendored core's `expand.py` / `solver.py` bind their layout classes with
# `from shelving_core.layout import ...` (byte-identical to upstream), so `expand`
# type-checks its input against the top-level `shelving_core` package. A carcass
# passed to it must be built from the same package, or `isinstance` misses every
# `Split` and the dividers are silently dropped. Import the layout/solver/expand
# surface from `shelving_core.*` to match; the byte-identical vendored copy under
# `freecad.shelving.vendor` still backs `plank.py` and the label helper.
from shelving_core.expand import PlankRole, PlankSpec, expand
from shelving_core.layout import Carcass, Leaf
from shelving_core.materials import MaterialId
from shelving_core.solver import LayoutSolveError

_GROUP = "Shelving"
_DRIVER_NAME = "ShelvingUnitDriver"

_STARTER_WIDTH_MM = 900.0
_STARTER_HEIGHT_MM = 1800.0
_STARTER_DEPTH_MM = 300.0


def make_shelving_unit(doc: FreeCAD.Document) -> FreeCAD.DocumentObject:
    """Create a `ShelvingUnit` `App::Part` plus its `ShelvingUnitDriver` child in
    `doc` and return the `App::Part`.

    The driver carries the promoted `Width` / `Height` / `Depth` /
    `DefaultMaterial` properties and the hidden `Layout`, seeded with a
    single-`Leaf` 900 x 1800 x 300 mm carcass in `ply18`; the promoted scalars
    are set to match. The "Create Unit" command and the headless smoke both call
    this, so it touches no GUI. A `recompute` afterwards is what builds the
    planks.
    """
    part = cast("ShelvingUnitFeature", doc.addObject("App::Part", "ShelvingUnit"))
    driver = cast(
        "ShelvingUnitFeature", doc.addObject("App::FeaturePython", _DRIVER_NAME)
    )
    ShelvingUnit(driver)
    part.addObject(cast("FreeCAD.DocumentObject", driver))

    carcass = Carcass(
        width_mm=_STARTER_WIDTH_MM,
        height_mm=_STARTER_HEIGHT_MM,
        depth_mm=_STARTER_DEPTH_MM,
        default_material=DEFAULT_MATERIAL_ID,
        root=Leaf(),
    )
    driver.Layout = carcass.to_json()
    driver.Width = _STARTER_WIDTH_MM
    driver.Height = _STARTER_HEIGHT_MM
    driver.Depth = _STARTER_DEPTH_MM
    driver.DefaultMaterial = str(DEFAULT_MATERIAL_ID)
    return cast("FreeCAD.DocumentObject", part)


def unit_driver(part: FreeCAD.DocumentObject) -> FreeCAD.DocumentObject:
    """The `ShelvingUnitDriver` child of a unit `App::Part`: the object that
    carries the promoted properties, `Layout`, and `execute`.

    Raises `LookupError` when `part` holds no driver child.
    """
    for child in cast("ShelvingUnitFeature", part).Group:
        if hasattr(child, "Layout"):
            return child
    raise LookupError(f"{part.Name} has no {_DRIVER_NAME} child")


class ShelvingUnit:
    """Proxy for the `ShelvingUnitDriver` `App::FeaturePython`.

    `execute` parses `Layout` into a `Carcass`, overrides its four outer scalars
    from the promoted properties, expands it against `DEFAULT_CATALOG`, rewrites
    `Layout` only when the serialised form changed, and reconciles the plank
    children of the parent `App::Part` by `NodeId` (create, update in place,
    remove). A malformed `Layout`, or a solver, catalog, or validation failure,
    raises `RuntimeError` and leaves every child and `Layout` untouched, so the
    last good geometry stays on screen and FreeCAD's own error state is the only
    signal.

    All persistent state lives on the object's properties, so `dumps` / `loads`
    carry nothing.
    """

    def __init__(self, obj: ShelvingUnitFeature) -> None:
        obj.Proxy = self
        obj.addProperty("App::PropertyLength", "Width", _GROUP, "Overall width")
        obj.addProperty("App::PropertyLength", "Height", _GROUP, "Overall height")
        obj.addProperty("App::PropertyLength", "Depth", _GROUP, "Overall depth")
        obj.addProperty(
            "App::PropertyEnumeration",
            "DefaultMaterial",
            _GROUP,
            "Catalog id for the shell and any divider without its own material",
            enum_vals=list(DEFAULT_CATALOG_IDS),
        )
        obj.addProperty(
            "App::PropertyString",
            "Layout",
            _GROUP,
            "Serialised Carcass JSON; the hand-edit surface for the split tree",
        )
        # Hidden, not read-only: hand-editing Layout is the tree-structure edit
        # path until the M5 layout editor lands.
        obj.setEditorMode("Layout", ["Hidden"])

    def execute(self, obj: ShelvingUnitFeature) -> None:
        # A malformed hand-edited Layout gets the same RuntimeError translation
        # as a solver failure, so the report view shows a solver-shaped message
        # rather than a raw JSON / KeyError.
        try:
            carcass = Carcass.from_json(obj.Layout)
        except (LayoutSolveError, KeyError, ValueError) as err:
            raise RuntimeError(str(err)) from err
        # The promoted scalars win over the JSON's four outer numbers; id and
        # root come from the parsed tree unchanged.
        carcass = Carcass(
            width_mm=obj.Width.Value,
            height_mm=obj.Height.Value,
            depth_mm=obj.Depth.Value,
            default_material=MaterialId(obj.DefaultMaterial),
            root=carcass.root,
            id=carcass.id,
        )
        try:
            specs = expand(carcass, DEFAULT_CATALOG)
        except (LayoutSolveError, KeyError, ValueError) as err:
            raise RuntimeError(str(err)) from err

        new_layout = carcass.to_json()
        # An unconditional write re-touches the object and loops the recompute.
        if new_layout != obj.Layout:
            obj.Layout = new_layout

        parent = obj.getParentGeoFeatureGroup()
        if parent is None:
            return
        self._reconcile(obj, parent, specs)

    def _reconcile(
        self,
        obj: ShelvingUnitFeature,
        parent: ShelvingUnitFeature,
        specs: list[PlankSpec],
    ) -> None:
        doc = obj.Document
        existing: dict[str, PlankFeature] = {}
        for child in parent.Group:
            # A plank child is one carrying NodeId; the driver itself never is.
            if child.Name == obj.Name or not hasattr(child, "NodeId"):
                continue
            typed_child = cast("PlankFeature", child)
            existing[typed_child.NodeId] = typed_child

        spec_ids: set[str] = set()
        role_counts: dict[PlankRole, int] = {}
        # Planks the driver created or updated this pass. A plank added mid
        # recompute is not in the document's current work list, so each is
        # recomputed explicitly once its spec is applied.
        active: list[FreeCAD.DocumentObject] = []
        for spec in specs:
            role_counts[spec.role] = role_counts.get(spec.role, 0) + 1
            spec_ids.add(spec.node_id)
            size_mm = FreeCAD.Vector(spec.size.x_mm, spec.size.y_mm, spec.size.z_mm)
            corner_mm = FreeCAD.Vector(
                spec.placement.x_mm, spec.placement.y_mm, spec.placement.z_mm
            )
            plank = existing.get(spec.node_id)
            if plank is not None:
                plank.SizeMM = size_mm
                plank.CornerMM = corner_mm
                plank.Material = str(spec.material)
                plank.Role = spec.role.value
                existing_obj = cast("FreeCAD.DocumentObject", plank)
                existing_obj.touch()
                active.append(existing_obj)
                continue
            created = add_plank(doc)
            new_plank = cast("PlankFeature", created)
            new_plank.NodeId = spec.node_id
            new_plank.SizeMM = size_mm
            new_plank.CornerMM = corner_mm
            new_plank.Role = spec.role.value
            new_plank.Material = str(spec.material)
            # Label is a create-time default only: a later execute never rewrites
            # it, so a user rename sticks.
            created.Label = generated_label(spec.role, role_counts[spec.role])
            parent.addObject(created)
            active.append(created)

        for node_id, stale in existing.items():
            if node_id not in spec_ids:
                doc.removeObject(cast("FreeCAD.DocumentObject", stale).Name)

        for plank_obj in active:
            plank_obj.recompute()

    def dumps(self) -> None:
        """No proxy-side state: every persistent value is a property on the
        driver object, so there is nothing to serialize."""
        return None

    def loads(self, state: object) -> None:
        """Counterpart to `dumps`; the proxy carries no restored state."""
        return None
