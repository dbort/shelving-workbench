"""Enforce the core invariant: `shelving_core` imports its own siblings
relatively, never through its own top-level package name.

The FreeCAD workbench vendors a byte-identical copy of this package under
`freecad/shelving/vendor/shelving_core/` (`tools/vendor-core.sh`). An absolute
self-import (`from shelving_core.layout import Board`) resolves against
whichever `shelving_core` happens to be first on `sys.path`, not against the
copy the importing file itself lives in. When both the top-level package and
the vendored copy are importable, as they are in this dev environment, that
makes the vendored copy's own functions build objects from the *top-level*
package's classes: `isinstance` checks against the vendored classes then fail
silently (`.claude/docs/friction-log.md` `friction-001`, before it is swept).
A relative import (`from .layout import Board`) always resolves against the
importing file's own package, so the vendored copy stays self-consistent
regardless of what else is on `sys.path`.

Scoped to non-test files only: a test module is meant to exercise the
top-level package the way an external caller would, and is never vendored.
"""

from pathlib import Path

import shelving_core

_FORBIDDEN_PATTERNS = (
    "from " + "shelving_core.",
    "import " + "shelving_core.",
)

_PACKAGE_DIR = Path(shelving_core.__file__).parent
_TESTS_DIR = Path(__file__).parent


def test_no_absolute_self_imports_in_source() -> None:
    offenders: list[str] = []
    for py_file in sorted(_PACKAGE_DIR.rglob("*.py")):
        if _TESTS_DIR in py_file.parents or py_file.parent == _TESTS_DIR:
            continue
        for line in py_file.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if any(stripped.startswith(pattern) for pattern in _FORBIDDEN_PATTERNS):
                offenders.append(f"{py_file}: {stripped!r}")
    assert not offenders, (
        "shelving_core module(s) import a sibling by absolute path; use a "
        "relative import (see this test's module docstring):\n" + "\n".join(offenders)
    )
