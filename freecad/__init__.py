"""The ``freecad`` addon namespace.

FreeCAD ships its own ``freecad`` package; extending ``__path__`` here lets this
repo's ``freecad.shelving`` subpackage coexist with it when the workbench is
installed alongside a FreeCAD instance.
"""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)
