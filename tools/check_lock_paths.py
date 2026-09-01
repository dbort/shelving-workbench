"""check_lock_paths: fail when pixi.lock pins a package by an absolute path.

pixi records the ``[pypi-dependencies]`` path entry for the project's editable
self-install in ``pixi.lock``. Seeded incrementally by ``pixi add``, pixi 0.78
writes that entry as the absolute path of the machine it ran on
(``- pypi: /workspace``); regenerating the lock from a clean state
(``rm pixi.lock && pixi lock``) writes it repo-relative (``- pypi: ./``). CI
installs with ``frozen: true`` and replays the lock without re-solving, so an
absolute path that exists only on the author's machine breaks every other
checkout. ``./test.sh --fast`` runs this so the next ``pixi install`` that
reintroduces one fails immediately instead of in CI.
"""

import pathlib
import re
import sys
from collections.abc import Sequence

# Lock keys whose value is a package location. Text scan rather than a YAML
# parse: the fast tier's environments (an activated ``.venv`` built from the
# [dev] extra, or the pixi env) are not guaranteed a YAML library.
_LOCATION_KEY = re.compile(
    r"^\s*(?:- )?(pypi|conda|url|path|source|git):\s*(\S.*?)\s*$"
)

# file:// embeds an absolute path; a leading slash or a drive letter is one.
_ABSOLUTE = re.compile(r"^(?:file://|/|[A-Za-z]:[\\/])")


def absolute_location_lines(lock_text: str) -> list[tuple[int, str]]:
    """``(line number, stripped line)`` for each entry pinned to an absolute path."""
    hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(lock_text.splitlines(), start=1):
        match = _LOCATION_KEY.match(line)
        if match is not None and _ABSOLUTE.match(match.group(2)):
            hits.append((lineno, line.strip()))
    return hits


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    lock_path = pathlib.Path(args[0]) if args else pathlib.Path("pixi.lock")
    hits = absolute_location_lines(lock_path.read_text(encoding="utf-8"))
    if hits:
        print(
            f"{lock_path} pins packages by absolute filesystem path, so the lock "
            "resolves only on the machine that wrote it and CI's frozen install "
            "fails on it. Regenerate with `rm pixi.lock && pixi lock`. Offending "
            "lines:",
            file=sys.stderr,
        )
        for lineno, text in hits:
            print(f"  {lock_path}:{lineno}: {text}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
