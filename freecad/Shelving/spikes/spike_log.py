"""The spike's text log: one file under ``/tmp`` the user copies back into
the dev VM, so a test session on their machine reaches the agent without
screenshots."""

import tempfile
from datetime import datetime
from pathlib import Path

# Directly under /tmp, as the user asked, where that exists; Windows has no
# /tmp, so it falls back to the platform's temp directory there.
LOG_PATH = (
    Path("/tmp") if Path("/tmp").is_dir() else Path(tempfile.gettempdir())
) / "shelving-viewport-spike.log"


def log(message: str) -> None:
    """Append ``message`` to :data:`LOG_PATH` with a millisecond timestamp.
    A failed write is ignored: the log must never break the editor."""
    stamp = datetime.now().isoformat(sep=" ", timespec="milliseconds")
    try:
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(f"{stamp} {message}\n")
    except OSError:
        pass
