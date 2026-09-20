"""Pure-Python layout core for the Shelving Workbench.

This package must never load FreeCAD or FreeCADGui, directly or transitively.
The boundary is what keeps the layout math testable without a GUI, and it is
enforced by ``tests/test_no_freecad.py``.
"""

__version__ = "0.0.1"
