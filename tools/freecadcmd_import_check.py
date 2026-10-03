"""Imports the workbench and its GUI-registration module under
``freecadcmd``, through FreeCAD's own startup.

The pytest suites import FreeCAD as a library and skip that startup: its
add-on discovery, and the ``freecad`` namespace package path it freezes
(``.claude/docs/freecad-notes.md``). An import bug that shows up only there,
such as a second importable copy of the core classes, would pass every
other check. ``freecadcmd`` exits 0 on an uncaught exception and runs a
script under its file stem rather than ``"__main__"``, so this catches
everything itself and ends in an unconditional ``sys.exit``.
"""

import sys
import traceback


def main() -> int:
    """0 when every import succeeds, 1 after printing the first failure."""
    try:
        import freecad.Shelving  # noqa: F401
        import freecad.Shelving.core.layout  # noqa: F401
        import freecad.Shelving.init_gui  # noqa: F401
    except Exception:  # noqa: BLE001 - any import failure is the finding
        traceback.print_exc()
        return 1
    print("freecadcmd import check OK")
    return 0


_status = main()
# freecadcmd does not flush stdout at exit, which would lose the report.
sys.stdout.flush()
sys.exit(_status)
