"""Verbose diagnostic logging for the workbench, printed to the Report view.

Toggle from the FreeCAD Python console with
``from freecad.Shelving import debug_log; debug_log.enabled = False``.
Every check reads :func:`is_enabled` rather than ``enabled`` directly, so a
preferences option can replace the module variable later without touching
callers.

Output for one command run is bracketed by ``BEGIN`` and ``END`` lines that
carry the same ``#N`` id and a wall-clock timestamp; every line logged while
that run is open repeats the id, so one run can be cut out of a long log.
"""

import itertools
import time
from datetime import datetime

enabled = True

_PREFIX = "[shelving]"
_next_id = itertools.count(1)
# The FreeCAD GUI runs commands on one thread, so a module-level "current
# run" is enough; a nested Stopwatch picks up the id of whatever run is open.
_current: "Invocation | None" = None


def is_enabled() -> bool:
    return enabled


def _tag() -> str:
    return f"{_PREFIX} #{_current.id}" if _current is not None else _PREFIX


def log(message: str) -> None:
    """Print ``message`` tagged with the open run's id; no-op when disabled."""
    if is_enabled():
        print(f"{_tag()} {message}")


def timestamp() -> str:
    """The current wall-clock time in the format the BEGIN/END markers use."""
    return datetime.now().isoformat(sep=" ", timespec="milliseconds")


class Stopwatch:
    """Logs each :meth:`lap` with that stage's elapsed time and the running
    total since construction, prefixed by ``label``."""

    def __init__(self, label: str) -> None:
        self.label = label
        self._start_s = time.perf_counter()
        self._last_s = self._start_s

    def lap(self, stage: str) -> None:
        now_s = time.perf_counter()
        self._emit(
            f"{self.label}: {stage}: {(now_s - self._last_s) * 1000:.1f} ms "
            f"(total {(now_s - self._start_s) * 1000:.1f} ms)"
        )
        self._last_s = now_s

    def _emit(self, message: str) -> None:
        log(message)

    def total_ms(self) -> float:
        return (time.perf_counter() - self._start_s) * 1000


class Invocation(Stopwatch):
    """One command run, opened by :func:`begin` and closed by :meth:`end`.

    ``end`` is separate from the scope that called ``begin`` because a
    run can outlive its command's ``Activated``: the Edit Unit panel's first
    paint happens on a later pass of the event loop. Calling ``end`` twice,
    or on a run that a newer ``begin`` already replaced, logs no further
    ``END`` line; a ``lap`` after that still prints, under this run's id.
    """

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self.id = next(_next_id)
        self._open = True

    def _emit(self, message: str) -> None:
        # A lap can arrive after this run ended or a newer run replaced it
        # (a late paint), so it carries its own id rather than the current one.
        if is_enabled():
            print(f"{_PREFIX} #{self.id} {message}")

    def end(self, outcome: str = "done") -> None:
        global _current
        if not self._open:
            return
        self._open = False
        if _current is self:
            if is_enabled():
                print(
                    f"{_PREFIX} #{self.id} ===== END {self.label} ({outcome}) "
                    f"{timestamp()}, total {self.total_ms():.1f} ms ====="
                )
            _current = None


def begin(label: str) -> Invocation:
    """Open a run named ``label`` and log its ``BEGIN`` marker. A run still
    open from before is closed as ``abandoned`` first, so markers always pair."""
    global _current
    if _current is not None:
        _current.end("abandoned")
    run = Invocation(label)
    _current = run
    if is_enabled():
        print(f"{_PREFIX} #{run.id} ===== BEGIN {label} {timestamp()} =====")
    return run
