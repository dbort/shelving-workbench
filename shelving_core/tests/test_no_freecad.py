"""Enforce the core invariant: :mod:`shelving_core` never pulls in FreeCAD.

Two independent checks:

1. A textual scan of every ``.py`` file in the package for the import
   statements that would breach the boundary.
2. Importing every submodule and asserting the FreeCAD GUI/app modules never
   landed in :data:`sys.modules` as a side effect.

The forbidden patterns are assembled at runtime from fragments so that this
test file does not itself trip the scan in check 1.
"""

import importlib
import pkgutil
import sys
from pathlib import Path

import shelving_core

_FORBIDDEN_PATTERNS = (
    "import " + "FreeCAD",
    "from " + "FreeCAD",
    "import " + "FreeCADGui",
    "from " + "FreeCADGui",
)

_PACKAGE_DIR = Path(shelving_core.__file__).parent


def test_no_freecad_import_statements_in_source() -> None:
    offenders: list[str] = []
    for py_file in sorted(_PACKAGE_DIR.rglob("*.py")):
        text = py_file.read_text(encoding="utf-8")
        for pattern in _FORBIDDEN_PATTERNS:
            if pattern in text:
                offenders.append(f"{py_file}: {pattern!r}")
    assert not offenders, "FreeCAD imports found in shelving_core:\n" + "\n".join(
        offenders
    )


def test_importing_every_submodule_does_not_load_freecad() -> None:
    for mod in pkgutil.walk_packages(shelving_core.__path__, prefix="shelving_core."):
        importlib.import_module(mod.name)
    assert "FreeCAD" not in sys.modules
    assert "FreeCADGui" not in sys.modules
