"""Per-user folders under FreeCAD's temp directory, for files the workbench
writes that are not part of a document: Export Boxes output and the QA
wizard's run.

The system cleans the temp directory up, and the user name in each folder's
name keeps two people on one machine from writing into the same one.
"""

import getpass
import os
import re
from pathlib import Path

import FreeCAD


def _safe_name(text: str, fallback: str) -> str:
    # A user name or label can hold characters a file name cannot.
    return re.sub(r"[^A-Za-z0-9._-]", "_", text).strip("_") or fallback


def user_temp_dir(purpose: str) -> Path:
    """``shelving-<purpose>-<user>`` under FreeCAD's temp directory. Not
    created here."""
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = str(os.getuid()) if hasattr(os, "getuid") else "user"
    return (
        Path(FreeCAD.getTempPath()) / f"shelving-{purpose}-{_safe_name(user, 'user')}"
    )


def export_path(container: FreeCAD.DocumentObject) -> Path:
    """Where Export Boxes writes ``container``: ``<label>.boxes.json`` in a
    folder named for its document, under the user's exports folder, whether
    or not the document has been saved. Not created here."""
    folder = user_temp_dir("exports") / _safe_name(container.Document.Name, "document")
    return folder / f"{_safe_name(container.Label, 'boxes')}.boxes.json"
