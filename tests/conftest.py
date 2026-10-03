"""Keeps the FreeCAD test directories out of runs that are not aimed at
exactly one of them (:mod:`tests.collection`), and says so at the end."""

from pathlib import Path

import pytest

from tests.collection import collectable_targets, reaches, skipped_freecad_dir

_SKIPPED = pytest.StashKey[list[Path]]()


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    skipped = skipped_freecad_dir(
        collection_path, config.args, config.invocation_params.dir
    )
    if skipped is None:
        return None
    # pytest also asks about directories next to a target it is walking
    # past; only a directory the run would otherwise have entered is worth
    # reporting. Nor one the command line already leaves out with --ignore, as
    # tools/run-tests.sh does before running each on its own.
    ignored = {
        (config.invocation_params.dir / path).resolve()
        for path in config.getoption("ignore") or []
    }
    if skipped not in ignored and reaches(
        skipped, config.args, config.invocation_params.dir
    ):
        config.stash.setdefault(_SKIPPED, []).append(skipped)
    return True


@pytest.hookimpl(tryfirst=True)
def pytest_collection(session: pytest.Session) -> None:
    config = session.config
    kept, dropped = collectable_targets(config.args, config.invocation_params.dir)
    if dropped:
        config.args = kept
        config.stash.setdefault(_SKIPPED, []).extend(dropped)


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    root = config.rootpath
    skipped = config.stash[_SKIPPED] if _SKIPPED in config.stash else []
    for directory in dict.fromkeys(skipped):
        relative = directory.relative_to(root)
        terminalreporter.write_line(
            f"skipped {relative}/: FreeCAD tests run only on their own, "
            f"as `pixi run pytest {relative}`"
        )
