"""``tools.xvfb_run``: the Xvfb launcher the 3D-view tests run under."""

import os
import stat
import sys
from pathlib import Path

import pytest

from tools import xvfb_run
from tools.xvfb_run import (
    XvfbError,
    child_environment,
    main,
    parse_display,
    run,
    xvfb_command,
)


def test_the_command_reports_its_display_and_finds_its_keymap() -> None:
    prefix = Path("/env")
    command = xvfb_command(prefix, 7)
    assert command[0] == "/env/bin/Xvfb"
    assert command[command.index("-displayfd") + 1] == "7"
    assert command[command.index("-xkbdir") + 1] == "/env/share/xkeyboard-config-2"
    assert command[command.index("-nolisten") + 1] == "tcp"


@pytest.mark.parametrize(("reported", "display"), [(b"0\n", 0), (b"12\n", 12)])
def test_a_reported_display_is_read(reported: bytes, display: int) -> None:
    assert parse_display(reported) == display


@pytest.mark.parametrize("reported", [b"", b"\n", b"x\n"])
def test_a_missing_display_is_an_error(reported: bytes) -> None:
    with pytest.raises(XvfbError):
        parse_display(reported)


def test_the_child_gets_the_display_and_qt_on_x11() -> None:
    env = child_environment({"QT_QPA_PLATFORM": "offscreen", "HOME": "/h"}, 3)
    assert env == {"QT_QPA_PLATFORM": "xcb", "HOME": "/h", "DISPLAY": ":3"}


def test_no_command_is_a_usage_error() -> None:
    assert main([]) == 2
    assert main(["--"]) == 2


def _socket(display: int) -> Path:
    return Path("/tmp/.X11-unix") / f"X{display}"


def test_a_command_runs_on_a_live_display_that_stops_afterward(
    tmp_path: Path,
) -> None:
    seen = tmp_path / "display.txt"
    script = (
        "import os, pathlib, sys\n"
        "display = os.environ['DISPLAY']\n"
        "sock = pathlib.Path('/tmp/.X11-unix') / ('X' + display.lstrip(':'))\n"
        f"pathlib.Path({str(seen)!r}).write_text(display + ' ' + str(sock.exists()))\n"
        "sys.exit(3)\n"
    )
    assert run([sys.executable, "-c", script]) == 3
    display, alive = seen.read_text().split()
    assert alive == "True"
    assert not _socket(int(display.lstrip(":"))).exists()


def test_a_server_that_fails_to_start_is_reported_with_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = tmp_path / "bin" / "Xvfb"
    fake.parent.mkdir()
    fake.write_text("#!/bin/sh\necho 'no keymap here' >&2\nexit 1\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(xvfb_run, "environment_prefix", lambda: tmp_path)
    with pytest.raises(XvfbError, match="no keymap here"):
        run([sys.executable, "-c", "pass"])
    assert main([sys.executable, "-c", "pass"]) == 1


def test_the_server_stops_when_the_command_cannot_start() -> None:
    before = (
        set(os.listdir("/tmp/.X11-unix")) if Path("/tmp/.X11-unix").exists() else set()
    )
    with pytest.raises(FileNotFoundError):
        run(["/nonexistent/command"])
    after = (
        set(os.listdir("/tmp/.X11-unix")) if Path("/tmp/.X11-unix").exists() else set()
    )
    assert after <= before
