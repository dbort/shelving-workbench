"""smoke_limit: run a command, stopping it and everything it started once it
passes the smoke run's time limit.

    python -m tools.smoke_limit tools/run-tests.sh --smoke

``tools/run-tests.sh`` runs itself this way for ``--smoke``. The command
runs in a process group of its own, so the stop reaches pytest, FreeCAD and
Xvfb as well as the shell that started them.
"""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

# How long a whole `pixi run tests -- --smoke` may take: about three times
# the measured run, so an overloaded machine still passes a healthy one.
SMOKE_LIMIT_S = 90
# coreutils `timeout`'s status for a command it stopped.
TIMED_OUT_STATUS = 124
# How long the group has to exit on SIGTERM before it is killed. Long
# enough for tools/xvfb_run.py to stop its server.
_GRACE_S = 15.0
_POLL_S = 0.05


def limit_message(limit_s: float) -> str:
    """The stderr line for a run stopped at ``limit_s``."""
    return (
        f"smoke run stopped: still running at its {limit_s:g} s smoke limit "
        "(tools/smoke_limit.py)"
    )


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Only a member still running can refuse the probe.
        return True
    return True


def _signal_group(pgid: int, signum: int) -> None:
    try:
        os.killpg(pgid, signum)
    except ProcessLookupError:
        pass


def stop_group(process: subprocess.Popen[bytes], grace_s: float = _GRACE_S) -> None:
    """End ``process`` and every process left in its group: SIGTERM, then
    SIGKILL for whatever is still there after ``grace_s``. Returns once the
    group leader is reaped and no member remains, or ``grace_s`` after the
    SIGKILL at the latest."""
    pgid = process.pid
    _signal_group(pgid, signal.SIGTERM)
    deadline_s = time.monotonic() + grace_s
    while time.monotonic() < deadline_s:
        process.poll()
        if process.returncode is not None and not _group_alive(pgid):
            return
        time.sleep(_POLL_S)
    _signal_group(pgid, signal.SIGKILL)
    process.wait()
    # Killed members are reaped by their parents or init, not here. The
    # bound keeps an init that never reaps from hanging the run.
    deadline_s = time.monotonic() + grace_s
    while _group_alive(pgid) and time.monotonic() < deadline_s:
        time.sleep(_POLL_S)


def run_with_limit(
    command: Sequence[str], limit_s: float, grace_s: float = _GRACE_S
) -> int:
    """Run ``command`` and return its exit status, or stop its whole process
    group once ``limit_s`` passes, print :func:`limit_message` to stderr and
    return :data:`TIMED_OUT_STATUS`. An interrupt stops the group too, then
    propagates."""
    process = subprocess.Popen(list(command), process_group=0)
    try:
        status = process.wait(timeout=limit_s)
    except subprocess.TimeoutExpired:
        stop_group(process, grace_s)
        print(limit_message(limit_s), file=sys.stderr, flush=True)
        return TIMED_OUT_STATUS
    except BaseException:
        # The group is not the terminal's foreground group, so Ctrl-C
        # reaches only this process.
        stop_group(process, grace_s)
        raise
    return status


def _interrupt(signum: int, frame: object) -> None:
    raise KeyboardInterrupt(f"signal {signum}")


def main(argv: Sequence[str] | None = None) -> int:
    # As in tools/xvfb_run.py: SIGTERM as an interrupt unwinds through
    # run_with_limit's cleanup instead of orphaning the group.
    signal.signal(signal.SIGTERM, _interrupt)
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--"]:
        args = args[1:]
    if not args:
        print("usage: python -m tools.smoke_limit COMMAND [ARG...]", file=sys.stderr)
        return 2
    return run_with_limit(args, SMOKE_LIMIT_S)


if __name__ == "__main__":
    raise SystemExit(main())
