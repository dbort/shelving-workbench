"""Headless FreeCAD for the tests in this directory, against throwaway
settings."""

import pytest

from tests.freecad_settings import isolate_freecad_settings, remove_settings

# Before FreeCAD loads: it reads its settings location only at startup.
_SETTINGS_ROOT = isolate_freecad_settings()

# The conda-forge FreeCAD package's own ``freecad`` package loads FreeCAD's
# libraries, after which ``import FreeCAD`` works from plain Python.
import freecad  # noqa: E402, F401


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    remove_settings(_SETTINGS_ROOT)
