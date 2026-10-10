"""FreeCAD's material library, for tests that give a board a material other
than the Default one every new object starts with."""

from collections.abc import Mapping
from typing import Protocol, cast

from freecad.Shelving.properties import FreeCADMaterial


class _MaterialManager(Protocol):
    # Keyed by UUID.
    Materials: Mapping[str, FreeCADMaterial]


def library_material(name: str) -> FreeCADMaterial:
    """The material named ``name`` in FreeCAD's library. Raises
    ``StopIteration`` when the library has none of that name."""
    # freecad-stubs has no stub for the Materials module; the Protocol cast
    # below types the one attribute read from it.
    import Materials  # type: ignore[import-not-found]

    manager = cast("_MaterialManager", Materials.MaterialManager())
    return next(m for m in manager.Materials.values() if m.Name == name)
