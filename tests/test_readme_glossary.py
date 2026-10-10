"""The README glossary is user vocabulary: it names no code.

Function, class and module names belong in docstrings, which change with
the code; a glossary entry naming them goes stale silently. FreeCAD type
names such as ``Part::Box`` are allowed, because a user sees them in the
tree.
"""

from __future__ import annotations

import re
from pathlib import Path

README = Path(__file__).resolve().parent.parent / "README.md"

_FREECAD_TYPE = re.compile(r"[A-Za-z]+::[A-Za-z]+")
_CODE_SPAN = re.compile(r"`([^`]+)`")
_CODE_SHAPES = (
    (re.compile(r"\b[a-z]+_[a-z0-9_]+\b"), "snake_case identifier"),
    (re.compile(r"\b\w+\.\w+\.\w+"), "dotted module path"),
    (re.compile(r"\b\w+\("), "call"),
)


def glossary_section(readme_text: str) -> str:
    """Return the text under ``## Glossary`` up to the next level-2 heading.

    Raises ``ValueError`` when the README has no glossary.
    """
    match = re.search(r"^## Glossary\n(.*?)(?=^## |\Z)", readme_text, re.M | re.S)
    if match is None:
        raise ValueError("README.md has no '## Glossary' section")
    return match.group(1)


def glossary_violations(glossary: str) -> list[str]:
    """Describe every code-level name in ``glossary``, in order of kind."""
    violations = [
        f"code span `{span}`"
        for span in _CODE_SPAN.findall(glossary)
        if not _FREECAD_TYPE.fullmatch(span)
    ]
    prose = _CODE_SPAN.sub("", glossary)
    for pattern, kind in _CODE_SHAPES:
        violations.extend(f"{kind} {hit!r}" for hit in pattern.findall(prose))
    return violations


def test_the_glossary_names_no_code() -> None:
    assert glossary_violations(glossary_section(README.read_text())) == []


def test_code_level_names_are_caught() -> None:
    glossary = (
        "- **Session**: `freecad.Shelving.editor.session.Session` answers\n"
        "  can_split for a `Part::Box`, via build_scene(unit).\n"
    )
    assert glossary_violations(glossary) == [
        "code span `freecad.Shelving.editor.session.Session`",
        "snake_case identifier 'can_split'",
        "snake_case identifier 'build_scene'",
        "call 'build_scene('",
    ]
