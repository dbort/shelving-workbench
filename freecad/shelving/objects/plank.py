"""`Plank`: the scripted-object proxy for one physical panel.

A `Plank` drives a `Part::FeaturePython` solid, one per `PlankSpec`. All
persistent state lives on the FreeCAD object's properties, so the proxy
serializes to nothing (`dumps`/`loads` are no-ops). No GUI import and no
`ViewProvider`: a headless `Part::FeaturePython` needs none, and the GUI
supplies a default when it is present. Colour-by-material is M6.
"""

from typing import cast

import FreeCAD
from freecad.shelving.objects.feature_types import PlankFeature
from freecad.shelving.objects.geometry import plank_shape
from freecad.shelving.vendor.shelving_core.expand import Vec3

_GROUP = "Shelving"


def _vec3(v: FreeCAD.Vector) -> Vec3:
    """The core `Vec3` for a `FreeCAD.Vector`, the form the geometry seam expects."""
    return Vec3(v.x, v.y, v.z)


def add_plank(doc: FreeCAD.Document, name: str = "Plank") -> FreeCAD.DocumentObject:
    """Create a `Part::FeaturePython` plank in `doc`, attach a `Plank` proxy, and
    return the new object. Needs no GUI, so both the sh-012 container and the
    functional smoke call it directly.
    """
    # The stub types `addObject` as returning the GUI proxy; headless it is an
    # `App::DocumentObject` carrying the scripted-object properties the Protocol
    # names.
    obj = cast("PlankFeature", doc.addObject("Part::FeaturePython", name))
    # Plank.__init__ registers itself as obj.Proxy and adds the properties; the
    # FreeCAD object owns the proxy from then on, so there is nothing to bind.
    Plank(obj)
    return cast("FreeCAD.DocumentObject", obj)


class Plank:
    """Proxy for a `Part::FeaturePython` plank solid.

    `execute` rebuilds `Shape` from the `SizeMM` / `CornerMM` vector properties
    through the `plank_shape` seam and refreshes the `Dimensions` string.
    `Placement` is left at identity in M3: the unit's `App::Part.Placement`
    moves the whole assembly, and per-plank `Placement` positioning is a
    later-milestone change the `plank_shape` seam isolates.
    """

    def __init__(self, obj: PlankFeature) -> None:
        obj.Proxy = self
        obj.addProperty(
            "App::PropertyString", "NodeId", _GROUP, "Reconciliation match key"
        )
        obj.addProperty("App::PropertyString", "Role", _GROUP, "PlankRole value")
        obj.addProperty(
            "App::PropertyString", "Material", _GROUP, "MaterialId from the spec"
        )
        obj.addProperty(
            "App::PropertyVector", "SizeMM", _GROUP, "Plank extent, millimetres"
        )
        obj.addProperty(
            "App::PropertyVector",
            "CornerMM",
            _GROUP,
            "Plank minimum corner in the carcass local frame, millimetres",
        )
        obj.addProperty(
            "App::PropertyString", "Dimensions", _GROUP, "Formatted plank size"
        )
        # Editor mode only gates the GUI property editor; code still assigns
        # these freely. NodeId is also hidden and stays read-only once the
        # container sets its key.
        obj.setEditorMode("NodeId", ["ReadOnly", "Hidden"])
        obj.setEditorMode("Role", ["ReadOnly"])
        obj.setEditorMode("Material", ["ReadOnly"])
        obj.setEditorMode("Dimensions", ["ReadOnly"])
        obj.setEditorMode("SizeMM", ["Hidden"])
        obj.setEditorMode("CornerMM", ["Hidden"])

    def execute(self, obj: PlankFeature) -> None:
        obj.Shape = plank_shape(_vec3(obj.SizeMM), _vec3(obj.CornerMM))
        size_mm = obj.SizeMM
        obj.Dimensions = f"{size_mm.x:g} x {size_mm.y:g} x {size_mm.z:g} mm"

    def dumps(self) -> None:
        """No proxy-side state: every persistent value is a property on the
        object, so there is nothing to serialize."""
        return None

    def loads(self, state: object) -> None:
        """Counterpart to `dumps`; the proxy carries no restored state."""
        return None
