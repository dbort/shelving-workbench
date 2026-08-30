"""Headless import smoke test for the full test tier.

Run by ``./test.sh --full`` via ``freecadcmd tools/freecad_smoke.py``. It only
checks that the workbench package and its vendored core import cleanly inside a
FreeCAD interpreter; ``freecadcmd`` propagates a non-zero exit on ImportError.

The repo root is prepended to ``sys.path`` here because M0 installs only
``shelving_core`` as a distribution; ``freecad.shelving`` is imported straight
from the checkout. Workbench code never does this.
"""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

import freecad.shelving  # noqa: E402, F401
from freecad.shelving.vendor import shelving_core  # noqa: E402

print(f"shelving workbench import OK (shelving_core {shelving_core.__version__})")
