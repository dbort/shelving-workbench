"""Which pytest runs may collect the FreeCAD test directories.

``tests/freecad/`` starts FreeCAD headless and ``tests/freecad_gui/``
starts its GUI, each from its ``conftest.py``'s ``pytest_sessionstart``.
Neither can share a process with the other or with the FreeCAD-free core
suite: the core tests that check ``FreeCADGui`` stays unloaded fail once
either has started, and a running GUI changes the headless tests' FreeCAD
(``ViewObject`` stops being ``None``). So each is collected only by a run
aimed entirely inside it; ``tests/conftest.py`` applies that rule.
"""

from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

FREECAD_DIRS: tuple[Path, ...] = (
    _REPO_ROOT / "tests" / "freecad",
    _REPO_ROOT / "tests" / "freecad_gui",
)


def _target_path(arg: str, invocation_dir: Path) -> Path:
    """The filesystem path of a pytest target, which may carry a node id
    suffix (``path::test``)."""
    return (invocation_dir / arg.split("::", 1)[0]).resolve()


def runs_only_inside(
    directory: Path, targets: Sequence[str], invocation_dir: Path
) -> bool:
    """Whether every target lies in ``directory`` or below it.

    ``targets`` are pytest's resolved collection arguments, relative to
    ``invocation_dir``; pytest supplies a default, so an empty sequence does
    not occur in practice and counts as not aimed at ``directory``.
    """
    if not targets:
        return False
    resolved = directory.resolve()
    return all(
        _target_path(arg, invocation_dir).is_relative_to(resolved) for arg in targets
    )


def reaches(directory: Path, targets: Sequence[str], invocation_dir: Path) -> bool:
    """Whether any target would collect something in ``directory``: it is
    the directory, lies inside it, or contains it."""
    resolved = directory.resolve()
    for arg in targets:
        target = _target_path(arg, invocation_dir)
        if target.is_relative_to(resolved) or resolved.is_relative_to(target):
            return True
    return False


def skipped_freecad_dir(
    path: Path, targets: Sequence[str], invocation_dir: Path
) -> Path | None:
    """The FreeCAD test directory ``path`` is, when this run must leave it
    out because not every target lies inside it; ``None`` for any other path
    or for a run aimed entirely at that directory."""
    resolved = path.resolve()
    for directory in FREECAD_DIRS:
        if resolved == directory and not runs_only_inside(
            directory, targets, invocation_dir
        ):
            return directory
    return None


def collectable_targets(
    targets: Sequence[str], invocation_dir: Path
) -> tuple[list[str], list[Path]]:
    """``targets`` minus any inside a FreeCAD directory that the run is not
    aimed entirely at, and those directories, in :data:`FREECAD_DIRS` order.

    pytest never consults the ``pytest_ignore_collect`` hook (which uses
    :func:`skipped_freecad_dir`) about a path named on its command line, so
    such a target has to be dropped from the targets instead.
    """
    kept = list(targets)
    dropped: list[Path] = []
    for directory in FREECAD_DIRS:
        if runs_only_inside(directory, targets, invocation_dir):
            continue
        resolved = directory.resolve()
        inside = [
            arg
            for arg in kept
            if _target_path(arg, invocation_dir).is_relative_to(resolved)
        ]
        if inside:
            dropped.append(directory)
            kept = [arg for arg in kept if arg not in inside]
    return kept, dropped
