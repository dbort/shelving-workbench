"""xvfb_run: run a command against a private Xvfb display, then stop it.

    python -m tools.xvfb_run pytest tests/freecad_view

The 3D-view tests need a real X server: offscreen Qt cannot create
FreeCAD's 3D view. The server is conda-forge's ``Xvfb`` from the pixi
environment, never a system one, so CI and the dev VM run the same build.
Xvfb picks its own free display and reports it through ``-displayfd``
once it accepts connections, so two runs on one machine never race for a
display number and nothing polls for a socket.
"""

import os
import select
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path

# Wide enough for FreeCAD's main window with its panels docked.
SCREEN = "1600x1000x24"
_STARTUP_TIMEOUT_S = 30.0
_STOP_TIMEOUT_S = 10.0


class XvfbError(RuntimeError):
    """Xvfb could not be started."""


def environment_prefix() -> Path:
    """The pixi environment this interpreter belongs to."""
    return Path(sys.prefix)


def xvfb_command(prefix: Path, display_fd: int) -> list[str]:
    """The Xvfb command line for the environment at ``prefix``, reporting
    its display number on ``display_fd``.

    conda-forge's xkeyboard-config installs its data under
    ``share/xkeyboard-config-2``, while its Xvfb looks in ``share/X11/xkb``
    and refuses to start without a keymap, so the data directory is passed
    explicitly.
    """
    return [
        str(prefix / "bin" / "Xvfb"),
        "-displayfd",
        str(display_fd),
        "-screen",
        "0",
        SCREEN,
        "-nolisten",
        "tcp",
        "-xkbdir",
        str(prefix / "share" / "xkeyboard-config-2"),
    ]


def parse_display(reported: bytes) -> int:
    """The display number Xvfb wrote to its ``-displayfd``. Raises
    :class:`XvfbError` when it wrote nothing usable, which it does when it
    exits during startup."""
    text = reported.decode("ascii", errors="replace").strip()
    if not text.isdigit():
        raise XvfbError(f"Xvfb reported no display number (got {text!r})")
    return int(text)


def child_environment(base: Mapping[str, str], display: int) -> dict[str, str]:
    """``base`` with ``DISPLAY`` pointing at ``display`` and Qt on X11.

    ``QT_QPA_PLATFORM`` is set outright: a developer's shell may export
    ``offscreen`` or ``wayland``, and either would keep FreeCAD off the
    display."""
    env = dict(base)
    env["DISPLAY"] = f":{display}"
    env["QT_QPA_PLATFORM"] = "xcb"
    return env


def _read_display(
    read_fd: int, server: subprocess.Popen[bytes], timeout_s: float
) -> int:
    """Block until Xvfb reports its display, exits, or ``timeout_s``
    passes. Xvfb writes the number and a newline once, then keeps the fd
    open; once it exits, the pipe reads as closed."""
    received = b""
    deadline_s = time.monotonic() + timeout_s
    poller = select.poll()
    poller.register(read_fd, select.POLLIN)
    with os.fdopen(read_fd, "rb", buffering=0) as pipe:
        while not received.endswith(b"\n"):
            remaining_s = deadline_s - time.monotonic()
            if remaining_s <= 0:
                raise XvfbError(f"Xvfb reported no display within {timeout_s:.0f} s")
            if not poller.poll(remaining_s * 1000):
                continue
            chunk = pipe.read(64)
            if not chunk:
                break
            received += chunk
    if server.poll() is not None:
        raise XvfbError(f"Xvfb exited during startup with status {server.returncode}")
    return parse_display(received)


def _stop(server: subprocess.Popen[bytes]) -> None:
    if server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=_STOP_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait()


def run(command: Sequence[str]) -> int:
    """Run ``command`` against a new Xvfb display and return its exit
    status. The server is stopped on every exit path, including an
    exception or an interrupt while the command runs. Raises
    :class:`XvfbError`, with the end of Xvfb's own output, when it does not
    start."""
    with tempfile.TemporaryFile() as server_log:
        read_fd, write_fd = os.pipe()
        try:
            server = subprocess.Popen(
                xvfb_command(environment_prefix(), write_fd),
                pass_fds=(write_fd,),
                stdout=server_log,
                stderr=server_log,
            )
        except BaseException:
            os.close(read_fd)
            raise
        finally:
            os.close(write_fd)
        try:
            try:
                display = _read_display(read_fd, server, _STARTUP_TIMEOUT_S)
            except XvfbError as err:
                server_log.seek(0)
                tail = server_log.read()[-2000:].decode("utf-8", errors="replace")
                raise XvfbError(f"{err}; its output ends:\n{tail}") from err
            child = subprocess.run(
                list(command), env=child_environment(os.environ, display), check=False
            )
            return child.returncode
        finally:
            _stop(server)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: python -m tools.xvfb_run COMMAND [ARG...]", file=sys.stderr)
        return 2
    try:
        return run(args)
    except XvfbError as err:
        print(f"xvfb_run: {err}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
