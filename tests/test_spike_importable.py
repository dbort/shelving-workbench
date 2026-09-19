"""Guards that ``spikes/plain_planks/`` stays importable.

``docs/roadmap.md`` (M4, M5) commits to keeping the spike running as the
fallback for looking at a layout until M6 deletes ``spikes/`` outright, so a
`shelving_core` rename or deletion that breaks its imports is a regression,
not a free pass because nothing runs its own test suite here (``pixi run
tests`` does not run ``pytest spikes``; ``python -m pytest spikes`` from the
repo root does). Importing each module is enough to catch that: a broken
import raises at collection, before any test body runs.

``export_boxes.py``, ``inspect_object.py``, and ``freecad_spike.py`` import
the ``FreeCAD`` C extension, unavailable outside ``freecadcmd``; the workbench
import there is already covered by ``tools/freecad_smoke.py``, and importing
``freecad_spike.py`` runs its goals as a side effect of import, not something
this guard should trigger on every ``pixi run tests``.
"""

import importlib

import pytest

_IMPORTABLE_MODULE_NAMES = [
    "spikes.plain_planks.carcass_model",
    "spikes.plain_planks.general_model",
    "spikes.plain_planks.report",
    "spikes.plain_planks.scan",
    "spikes.plain_planks.test_general_model",
    "spikes.plain_planks.test_scan",
]


@pytest.mark.parametrize("module_name", _IMPORTABLE_MODULE_NAMES)
def test_spike_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)
