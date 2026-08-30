"""Pure-Python layout core for the Shelving Workbench.

This package must never load FreeCAD or FreeCADGui, directly or transitively.
The boundary is what keeps the layout math testable without a GUI, and it is
enforced by ``tests/test_no_freecad.py``. The FreeCAD workbench consumes a
vendored copy of this package under ``freecad/shelving/vendor/shelving_core/``.
"""

__version__ = "0.0.1"
