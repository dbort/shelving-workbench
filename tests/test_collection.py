"""``tests.collection``: which runs may collect the FreeCAD directories."""

import pytest

from tests.collection import (
    FREECAD_DIRS,
    collectable_targets,
    reaches,
    runs_only_inside,
    skipped_freecad_dir,
)

_HEADLESS, _GUI = FREECAD_DIRS
_ROOT = _HEADLESS.parent.parent


@pytest.mark.parametrize(
    "targets",
    [
        ["tests/freecad"],
        ["tests/freecad/test_scan.py"],
        ["tests/freecad/test_scan.py::test_init_gui_imports_cleanly"],
        ["tests/freecad/test_scan.py", "tests/freecad/test_write.py"],
    ],
)
def test_a_run_aimed_inside_the_directory_collects_it(targets: list[str]) -> None:
    assert skipped_freecad_dir(_HEADLESS, targets, _ROOT) is None


@pytest.mark.parametrize(
    "targets",
    [
        ["."],
        ["tests"],
        ["freecad/Shelving/core", "tests"],
        ["tests/freecad", "tests/freecad_gui"],
        ["tests/freecad", "tests/test_collection.py"],
    ],
)
def test_a_mixed_run_skips_both_directories(targets: list[str]) -> None:
    assert skipped_freecad_dir(_HEADLESS, targets, _ROOT) == _HEADLESS
    assert skipped_freecad_dir(_GUI, targets, _ROOT) == _GUI


def test_targets_resolve_against_the_invocation_directory() -> None:
    assert skipped_freecad_dir(_GUI, ["."], _GUI) is None
    assert skipped_freecad_dir(_GUI, ["test_panel.py"], _GUI) is None
    assert skipped_freecad_dir(_GUI, [".."], _GUI) == _GUI


def test_other_paths_are_never_skipped() -> None:
    assert skipped_freecad_dir(_ROOT / "tests", ["."], _ROOT) is None
    assert skipped_freecad_dir(_HEADLESS / "test_scan.py", ["."], _ROOT) is None


def test_no_targets_counts_as_not_aimed_at_the_directory() -> None:
    assert runs_only_inside(_HEADLESS, [], _ROOT) is False


def test_a_sibling_with_a_shared_prefix_is_not_inside() -> None:
    """``tests/freecad_gui`` starts with ``tests/freecad`` as a string, but is
    not inside it."""
    assert runs_only_inside(_HEADLESS, ["tests/freecad_gui"], _ROOT) is False


@pytest.mark.parametrize(
    ("targets", "expected"),
    [
        (["."], True),
        (["tests"], True),
        (["tests/freecad"], True),
        (["tests/freecad/test_scan.py"], True),
        (["tests/test_collection.py"], False),
        (["freecad/Shelving/core"], False),
        (["tests/freecad_gui"], False),
    ],
)
def test_reaches_only_runs_that_would_enter_the_directory(
    targets: list[str], expected: bool
) -> None:
    assert reaches(_HEADLESS, targets, _ROOT) is expected


def test_named_freecad_targets_are_dropped_from_a_mixed_run() -> None:
    kept, dropped = collectable_targets(
        ["tests/freecad", "tests/freecad_gui/test_panel.py", "tests"], _ROOT
    )
    assert kept == ["tests"]
    assert dropped == [_HEADLESS, _GUI]


def test_a_run_aimed_inside_one_directory_keeps_its_targets() -> None:
    targets = ["tests/freecad_gui", "tests/freecad_gui/test_panel.py::test_a"]
    assert collectable_targets(targets, _ROOT) == (targets, [])


def test_targets_outside_the_freecad_directories_are_kept() -> None:
    assert collectable_targets(["freecad/Shelving/core", "tests"], _ROOT) == (
        ["freecad/Shelving/core", "tests"],
        [],
    )
