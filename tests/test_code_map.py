"""``.claude/docs/code-map.md`` stays a short, accurate index.

Its value is pointing at code, so a path that no longer exists or a
top-level module it does not list makes it wrong, and growth past the word
cap means it has started restating docstrings.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE_MAP = ROOT / ".claude" / "docs" / "code-map.md"
PACKAGE = ROOT / "freecad" / "Shelving"
MAX_WORDS = 300

_PATH_SPAN = re.compile(r"`([\w./-]+/[\w./-]*)`")


def mentioned_paths(text: str) -> list[str]:
    """Return every path-like code span in ``text``, in order."""
    return _PATH_SPAN.findall(text)


def unlisted_entries(text: str, package: Path) -> list[str]:
    """Return the top-level files and directories under ``package`` that
    ``text`` never names, sorted. ``__init__.py`` and caches are exempt."""
    entries = sorted(
        child.name
        for child in package.iterdir()
        if child.name not in {"__init__.py", "__pycache__"}
    )
    return [name for name in entries if f"freecad/Shelving/{name}" not in text]


def test_every_path_exists() -> None:
    text = CODE_MAP.read_text()
    missing = [path for path in mentioned_paths(text) if not (ROOT / path).exists()]
    assert missing == []


def test_every_top_level_entry_is_listed() -> None:
    assert unlisted_entries(CODE_MAP.read_text(), PACKAGE) == []


def test_the_map_stays_an_index() -> None:
    words = len(CODE_MAP.read_text().split())
    assert words <= MAX_WORDS, (
        f"code-map.md has {words} words (cap {MAX_WORDS}); move detail into "
        "the module docstrings it points at"
    )


def test_unlisted_entries_are_found(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").touch()
    (tmp_path / "listed.py").touch()
    (tmp_path / "new_layer").mkdir()
    text = "`freecad/Shelving/listed.py`"
    assert unlisted_entries(text, tmp_path) == ["new_layer"]
