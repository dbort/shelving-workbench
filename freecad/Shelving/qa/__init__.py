"""The manual QA wizard: a dock that walks a person through the cases in
``cases/``, with a button for each step's setup and a recorded verdict.

Developer tooling, on by default for now; toggle from the FreeCAD Python
console with ``from freecad.Shelving import qa; qa.enabled = False`` before
the workbench loads. Every check reads :func:`is_enabled`, so a preference
can replace the module variable later without touching callers. The
contract that keeps the wizard small is ``.claude/docs/qa-wizard.md``.
"""

from pathlib import Path

enabled = True


def is_enabled() -> bool:
    return enabled


def temp_dir() -> Path:
    """The folder for this user's QA run: progress, report, and the
    documents setup buttons save. Not created here."""
    from freecad.Shelving.temp_dirs import user_temp_dir

    return user_temp_dir("qa")
