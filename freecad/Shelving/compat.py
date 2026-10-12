"""Standard-library names newer than the oldest Python a supported FreeCAD
ships. FreeCAD 1.1's macOS bundle runs Python 3.11, and ``typing.override``
arrived in 3.12; importing it from ``typing`` there stops the workbench from
loading at all. Pyrefly checks at 3.11 (``pyproject.toml``), so a new
3.12-only import fails the gate instead.
"""

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Pyrefly enforces @override, and recognizes this one at any version.
    from typing_extensions import override
elif sys.version_info >= (3, 12):
    from typing import override
else:

    def override(method):
        """Returns ``method`` unchanged; only a type checker reads it."""
        return method
