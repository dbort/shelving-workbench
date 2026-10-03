"""Throwaway FreeCAD user settings for test runs.

FreeCAD reads its settings location from the XDG directories once, at
startup, so :func:`isolate_freecad_settings` has to run before anything
imports FreeCAD. A developer's real settings would otherwise be read and
written by every test run, and FreeCAD 1.1's GUI would stop at a modal
offer to migrate older settings (``.claude/docs/freecad-notes.md``).
"""

import os
import shutil
import tempfile
from pathlib import Path

_TEST_USER_CFG = (
    Path(__file__).resolve().parent.parent / "tools" / "freecad-test-user.cfg"
)

# FreeCAD 1.1 keeps its settings in a directory named after its minor version.
_VERSION_DIR = "v1-1"


def isolate_freecad_settings() -> Path:
    """Point FreeCAD at a new, empty settings tree holding only
    ``tools/freecad-test-user.cfg``, and return the tree's root.

    Sets ``XDG_CONFIG_HOME``, ``XDG_DATA_HOME`` and ``XDG_CACHE_HOME`` for
    this process and its children; ``HOME`` is untouched. Has no effect on a
    FreeCAD already imported. The caller removes the root with
    :func:`remove_settings` when done.
    """
    root = Path(tempfile.mkdtemp(prefix="shelving-freecad-"))
    config = root / "config" / "FreeCAD" / _VERSION_DIR
    config.mkdir(parents=True)
    shutil.copyfile(_TEST_USER_CFG, config / "user.cfg")
    os.environ["XDG_CONFIG_HOME"] = str(root / "config")
    os.environ["XDG_DATA_HOME"] = str(root / "data")
    os.environ["XDG_CACHE_HOME"] = str(root / "cache")
    return root


def remove_settings(root: Path) -> None:
    """Delete a tree :func:`isolate_freecad_settings` made; a missing one is
    not an error."""
    shutil.rmtree(root, ignore_errors=True)
