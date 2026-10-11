"""The manual QA wizard: a dock that walks a person through the cases in
``cases/``, with a button for each step's setup and a recorded verdict.

Developer tooling, on by default for now; toggle from the FreeCAD Python
console with ``from freecad.Shelving import qa; qa.enabled = False`` before
the workbench loads. Every check reads :func:`is_enabled`, so a preference
can replace the module variable later without touching callers. The
contract that keeps the wizard small is ``.claude/docs/qa-wizard.md``.
"""

import getpass
import os
import re
from pathlib import Path

enabled = True


def is_enabled() -> bool:
    return enabled


def temp_dir() -> Path:
    """The folder for this user's QA run: progress, report, and the
    documents setup buttons save. Under FreeCAD's temp directory, which the
    system cleans up, and named for the user, so two people on one machine
    do not share a run. Not created here."""
    import FreeCAD

    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = str(os.getuid()) if hasattr(os, "getuid") else "user"
    # A user name can hold characters a folder name cannot.
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", user) or "user"
    return Path(FreeCAD.getTempPath()) / f"shelving-qa-{safe}"
