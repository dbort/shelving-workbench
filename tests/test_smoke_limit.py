"""``tools.smoke_limit``: the hard time limit on ``pixi run tests --
--smoke``, driven with a short limit against stand-in commands."""

import os
import time
from pathlib import Path

import pytest

from tools.smoke_limit import (
    SMOKE_LIMIT_S,
    TIMED_OUT_STATUS,
    limit_message,
    main,
    run_with_limit,
)


def _gone(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _spawning(pid_file: Path, *, ignore_term: bool = False) -> list[str]:
    """A shell that starts a long-running child, records its pid, and
    waits on it."""
    trap = "trap '' TERM; " if ignore_term else ""
    return ["bash", "-c", f"{trap}sleep 60 & echo $! > {pid_file}; wait"]


def test_the_message_names_the_90_s_smoke_limit() -> None:
    assert SMOKE_LIMIT_S == 90
    assert "90 s smoke limit" in limit_message(SMOKE_LIMIT_S)


def test_a_command_inside_its_limit_returns_its_own_status() -> None:
    assert run_with_limit(["bash", "-c", "exit 3"], limit_s=10.0) == 3


def test_a_command_past_its_limit_is_stopped_with_its_child(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pid_file = tmp_path / "child.pid"
    started_s = time.monotonic()
    status = run_with_limit(_spawning(pid_file), limit_s=0.5, grace_s=5.0)
    assert status == TIMED_OUT_STATUS == 124
    assert capsys.readouterr().err == limit_message(0.5) + "\n"
    assert "0.5 s smoke limit" in limit_message(0.5)
    assert _gone(int(pid_file.read_text()))
    assert time.monotonic() - started_s < 3.0


def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    pid_file = tmp_path / "child.pid"
    status = run_with_limit(
        _spawning(pid_file, ignore_term=True), limit_s=0.5, grace_s=0.3
    )
    assert status == TIMED_OUT_STATUS
    assert limit_message(0.5) in capsys.readouterr().err
    assert _gone(int(pid_file.read_text()))


def test_no_command_is_a_usage_error() -> None:
    assert main([]) == 2
    assert main(["--"]) == 2
