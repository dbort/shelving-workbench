"""Headless FreeCAD for the tests in this directory, against throwaway
settings.

FreeCAD starts in :func:`pytest_sessionstart`, not when this module is
imported: pytest imports the conftest of every directory named on its
command line before any collection decision, and a run that also names
other tests must not start FreeCAD here (:mod:`tests.collection`).
"""

from pathlib import Path

import pytest

from tests.collection import runs_only_inside
from tests.freecad_env import (
    isolate_freecad_settings,
    load_freecad,
    remove_settings,
)

_HERE = Path(__file__).resolve().parent
_SETTINGS = pytest.StashKey[Path]()


def pytest_sessionstart(session: pytest.Session) -> None:
    config = session.config
    if not runs_only_inside(_HERE, config.args, config.invocation_params.dir):
        return
    # Before FreeCAD loads: it reads its settings location only at startup.
    config.stash[_SETTINGS] = isolate_freecad_settings()
    load_freecad()


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    root = session.config.stash.get(_SETTINGS, None)
    if root is not None:
        remove_settings(root)
