"""Headless import smoke test, the last step of ``pixi run tests``.

Run via ``freecadcmd tools/freecad_smoke.py``. It checks that the workbench
package, its GUI-registration module, and the vendored core import cleanly
inside a FreeCAD interpreter, then prints the OK line that
``tools/run-tests.sh`` greps for. ``freecadcmd`` does not propagate a script's
exit status, so that printed line, not an exit code, is the success signal.

The repo root is added to ``sys.path`` and merged into the already-initialised
``freecad`` namespace package's ``__path__`` here because M0 installs only
``shelving_core`` as a distribution; ``freecad.shelving`` is imported straight
from the checkout. Workbench code never does this: an installed workbench is
discovered through FreeCAD's own addon path.
"""

import os
import sys
from pkgutil import extend_path

import freecad

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
# FreeCAD imports `freecad` during start-up, freezing its `__path__` before this
# script runs; refresh it so `freecad.shelving` from the checkout resolves.
freecad.__path__ = extend_path(freecad.__path__, "freecad")

import freecad.shelving  # noqa: E402, F401
import freecad.shelving.init_gui  # noqa: E402, F401
from freecad.shelving.vendor import shelving_core  # noqa: E402

print(f"shelving workbench import OK (shelving_core {shelving_core.__version__})")
