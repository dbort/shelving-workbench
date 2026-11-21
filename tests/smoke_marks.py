"""The ``smoke`` marker: its registration, the rules its marks follow, and
the list a smoke run prints of the tests it ran.

``tests/conftest.py`` registers this module as a pytest plugin. Its checks
see one pytest run's items, and the two marked suites run in separate
processes, so :func:`source_mark_problems` reads the marks from both
suites' sources to catch a path claimed in each.
"""

import ast
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TypeGuard

import pytest

from tools.smoke_limit import SMOKE_LIMIT_S

MARKER = "smoke"
# The `-m` expression tools/run-tests.sh passes to the two marked suites.
SMOKE_EXPRESSION = MARKER

_DESCRIPTION = (
    f"{MARKER}(path): one of the small set of tests that `pixi run tests -- "
    "--smoke` runs from tests/freecad_gui/ and tests/freecad_view/, which "
    "together show the workbench's GUI and 3D view are healthy. `path` names, "
    "in user vocabulary, the user path the test covers; no two smoke tests "
    "share one. Every smoke test also runs in the full suite, and the whole "
    f"smoke run must finish inside its {SMOKE_LIMIT_S} s limit."
)

_SUMMARY = pytest.StashKey[list[tuple[str, str]]]()


def mark_problem(args: Sequence[object], kwargs: Mapping[str, object]) -> str | None:
    """What is wrong with a ``smoke`` mark given ``args`` and ``kwargs``, or
    ``None`` when it names exactly one non-blank user path."""
    if kwargs:
        return "takes no keyword arguments"
    if len(args) != 1:
        return (
            f"takes exactly one argument, the user path it covers; it has {len(args)}"
        )
    (path,) = args
    if not isinstance(path, str):
        return "takes its user path as a literal string"
    if not path.strip():
        return "has an empty user path"
    return None


def duplicate_paths(
    claims: Iterable[tuple[str, str]],
) -> dict[str, list[str]]:
    """Each user path that more than one ``(owner, path)`` claim gives,
    mapped to its owners in claim order. Paths compare as exact strings."""
    owners: dict[str, list[str]] = {}
    for owner, path in claims:
        owners.setdefault(path, []).append(owner)
    return {path: names for path, names in owners.items() if len(names) > 1}


def _duplicate_messages(claims: Iterable[tuple[str, str]]) -> list[str]:
    return [
        f"smoke path {path!r} is claimed by more than one test: {', '.join(owners)}"
        for path, owners in duplicate_paths(claims).items()
    ]


def item_problems(items: Sequence[pytest.Item]) -> list[str]:
    """A message naming the test for each malformed ``smoke`` mark among
    ``items``, then one for each user path two of their marks give."""
    problems: list[str] = []
    claims: list[tuple[str, str]] = []
    for item in items:
        for mark in item.iter_markers(MARKER):
            problem = mark_problem(mark.args, mark.kwargs)
            if problem is None:
                claims.append((item.nodeid, str(mark.args[0])))
            else:
                problems.append(f"{item.nodeid}: its smoke mark {problem}")
    return problems + _duplicate_messages(claims)


def _is_smoke_attribute(node: ast.AST) -> TypeGuard[ast.Attribute]:
    """Whether ``node`` spells ``pytest.mark.smoke`` or ``mark.smoke``."""
    if not isinstance(node, ast.Attribute) or node.attr != MARKER:
        return False
    holder = node.value
    if isinstance(holder, ast.Name):
        return holder.id == "mark"
    return (
        isinstance(holder, ast.Attribute)
        and holder.attr == "mark"
        and isinstance(holder.value, ast.Name)
        and holder.value.id == "pytest"
    )


def _literal(node: ast.expr) -> object:
    # Anything but a literal stays an AST node, which no rule accepts as a
    # path: the source alone cannot say what it evaluates to.
    return node.value if isinstance(node, ast.Constant) else node


@dataclass(frozen=True)
class SourceMark:
    """A ``smoke`` mark as written in a test module."""

    line: int
    # The test function the mark decorates, or the module-level name it is
    # assigned to, when there is one.
    owner: str | None
    args: tuple[object, ...]
    kwargs: Mapping[str, object]


def _owner(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef):
        return statement.name
    if isinstance(statement, ast.Assign | ast.AnnAssign):
        targets = (
            statement.targets
            if isinstance(statement, ast.Assign)
            else [statement.target]
        )
        names = [t.id for t in targets if isinstance(t, ast.Name)]
        return names[0] if names else None
    return None


def source_marks(source: str) -> list[SourceMark]:
    """Every ``smoke`` mark written in the module ``source``, in source
    order. A mark referenced without a call counts as a mark with no
    arguments."""
    marks: list[SourceMark] = []
    for statement in ast.parse(source).body:
        owner = _owner(statement)
        called: set[int] = set()
        # Breadth first, so a call is met before the attribute it calls.
        for node in ast.walk(statement):
            if isinstance(node, ast.Call) and _is_smoke_attribute(node.func):
                called.add(id(node.func))
                args = tuple(_literal(arg) for arg in node.args)
                kwargs = {str(kw.arg): _literal(kw.value) for kw in node.keywords}
                marks.append(SourceMark(node.lineno, owner, args, kwargs))
            elif _is_smoke_attribute(node) and id(node) not in called:
                marks.append(SourceMark(node.lineno, owner, (), {}))
    return sorted(marks, key=lambda mark: mark.line)


def source_mark_problems(root: Path, directories: Sequence[Path]) -> list[str]:
    """A message naming the place for each malformed ``smoke`` mark in the
    test modules of ``directories``, then one for each user path two marks
    give, wherever in those directories they are. Locations are relative to
    ``root``."""
    problems: list[str] = []
    claims: list[tuple[str, str]] = []
    for directory in directories:
        for module in sorted(directory.glob("test_*.py")):
            label = module.relative_to(root).as_posix()
            for mark in source_marks(module.read_text()):
                location = f"{label}:{mark.line}"
                if mark.owner is not None:
                    location += f" ({mark.owner})"
                problem = mark_problem(mark.args, mark.kwargs)
                if problem is None:
                    claims.append((location, str(mark.args[0])))
                else:
                    problems.append(f"{location}: its smoke mark {problem}")
    return problems + _duplicate_messages(claims)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", _DESCRIPTION)


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    # tryfirst: before `-m` deselects anything, so a bad mark fails every
    # run that collects it, the full run included.
    problems = item_problems(items)
    if problems:
        raise pytest.UsageError("\n".join(problems))


def pytest_collection_finish(session: pytest.Session) -> None:
    config = session.config
    if config.getoption("markexpr") != SMOKE_EXPRESSION:
        return
    config.stash[_SUMMARY] = [
        (item.nodeid, str(mark.args[0]))
        for item in session.items
        for mark in item.iter_markers(MARKER)
    ]


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    ran = config.stash.get(_SUMMARY, None)
    if ran is None:
        return
    terminalreporter.write_sep("-", "smoke tests run, with the user path each covers")
    for nodeid, path in ran:
        terminalreporter.write_line(nodeid)
        terminalreporter.write_line(f"    {path}")
