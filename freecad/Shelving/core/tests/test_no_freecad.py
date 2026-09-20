"""Enforce the core invariant: :mod:`freecad.Shelving.core` never pulls in FreeCAD.

Two independent checks:

1. A textual scan of every ``.py`` file in the package for the import
   statements that would breach the boundary. This is the real enforcement
   mechanism.
2. Importing every submodule and asserting ``FreeCADGui`` (the GUI-heavy
   module, never needed headlessly) never landed in :data:`sys.modules` as a
   side effect. ``FreeCAD`` itself is deliberately not checked here: living
   under the `freecad.` namespace-package portion means resolving
   `freecad.Shelving.core` first resolves the installed FreeCAD
   distribution's own `freecad/__init__.py` (a regular package always wins
   over a namespace-portion directory of the same name), and that file
   unconditionally imports the ``FreeCAD`` App module as part of its own
   namespace-path bookkeeping. That happens before this test's body ever
   runs, as a
   structural consequence of the package layout, not of anything `core`
   itself imports, so it is not a signal check 2 can meaningfully give
   (verified this session: `sys.modules` already carries `FreeCAD` from
   this file's own module-level import above, before `walk_packages` below
   runs at all).

The forbidden patterns are assembled at runtime from fragments so that this
test file does not itself trip the scan in check 1.
"""

import importlib
import pkgutil
import sys
from pathlib import Path

from freecad.Shelving import core

_FORBIDDEN_PATTERNS = (
    "import " + "FreeCAD",
    "from " + "FreeCAD",
    "import " + "FreeCADGui",
    "from " + "FreeCADGui",
)

_PACKAGE_DIR = Path(core.__file__).parent


def test_no_freecad_import_statements_in_source() -> None:
    offenders: list[str] = []
    for py_file in sorted(_PACKAGE_DIR.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern in text:
                offenders.append(f"{py_file}: {pattern!r}")
    msg = "FreeCAD imports found in freecad.Shelving.core:\n" + "\n".join(offenders)
    assert not offenders, msg


def test_importing_every_submodule_does_not_load_freecadgui() -> None:
    for mod in pkgutil.walk_packages(core.__path__, prefix="freecad.Shelving.core."):
        importlib.import_module(mod.name)
    assert "FreeCADGui" not in sys.modules
