"""QA cases read from the TOML files in ``cases/``.

A file holds one or more ``[[case]]`` tables, each with ``id``, ``title``
and ``[[case.step]]`` tables; a step has ``id``, ``instruction`` (a list
of lines, one action each) and ``expected``, and may name a setup
``action`` and an advisory ``check`` from
:mod:`freecad.Shelving.qa.registry`. A step with an ``action`` may omit
``instruction`` when its button is the whole step. Every other key is
refused, so a case gains a field only when this loader learns it.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CASES_DIR = Path(__file__).parent / "cases"

_CASE_KEYS = frozenset({"id", "title", "step"})
_STEP_KEYS = frozenset({"id", "instruction", "expected", "action", "check"})


class CaseFileError(ValueError):
    """A case file that does not match the format; the message names the
    file and the offending key or table."""


@dataclass(frozen=True)
class Step:
    # Stable within its case: saved progress and reports key on it.
    id: str
    # One action per line, shown in order below the step's setup button.
    # Empty only on a step whose button is the whole instruction.
    instruction: tuple[str, ...]
    expected: str
    # A registry action name, shown as a button; None when the step needs
    # no setup.
    action: str | None = None
    # A registry check name: run on demand from the step's Run check button,
    # and again when a verdict is recorded.
    check: str | None = None


@dataclass(frozen=True)
class Case:
    # Stable across files: saved progress and reports key on it.
    id: str
    title: str
    steps: tuple[Step, ...]


def _text(table: Mapping[str, object], key: str, where: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CaseFileError(f"{where}: '{key}' must be non-empty text")
    return value.strip()


def _lines(table: Mapping[str, object], key: str, where: str) -> tuple[str, ...]:
    value = table.get(key)
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(line, str) and line.strip() for line in value)
    ):
        raise CaseFileError(f"{where}: '{key}' must be a list of non-empty lines")
    return tuple(line.strip() for line in value)


def _optional_text(table: Mapping[str, object], key: str, where: str) -> str | None:
    return _text(table, key, where) if key in table else None


def _closed(table: Mapping[str, object], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        raise CaseFileError(f"{where}: unknown key '{unknown[0]}'")


def _tables(value: object, where: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not value:
        raise CaseFileError(f"{where}: needs at least one table")
    tables: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise CaseFileError(f"{where}: every entry must be a table")
        tables.append(item)
    return tables


def parse_cases(data: Mapping[str, object], source: str) -> list[Case]:
    """The cases in one parsed TOML document. Raises :class:`CaseFileError`
    naming ``source`` on a missing or empty field, an unknown key, or a
    repeated step id."""
    _closed(data, frozenset({"case"}), source)
    cases: list[Case] = []
    for table in _tables(data.get("case"), f"{source}: [[case]]"):
        case_id = _text(table, "id", f"{source}: [[case]]")
        where = f"{source}: case '{case_id}'"
        _closed(table, _CASE_KEYS, where)
        steps: list[Step] = []
        for step_table in _tables(table.get("step"), f"{where}: [[case.step]]"):
            step_id = _text(step_table, "id", f"{where}: [[case.step]]")
            step_where = f"{where}, step '{step_id}'"
            _closed(step_table, _STEP_KEYS, step_where)
            if any(step.id == step_id for step in steps):
                raise CaseFileError(f"{step_where}: repeated step id")
            action = _optional_text(step_table, "action", step_where)
            instruction = (
                ()
                if action is not None and "instruction" not in step_table
                else _lines(step_table, "instruction", step_where)
            )
            steps.append(
                Step(
                    id=step_id,
                    instruction=instruction,
                    expected=_text(step_table, "expected", step_where),
                    action=action,
                    check=_optional_text(step_table, "check", step_where),
                )
            )
        cases.append(
            Case(id=case_id, title=_text(table, "title", where), steps=tuple(steps))
        )
    return cases


def load_cases(paths: Sequence[Path] | None = None) -> list[Case]:
    """Every case in ``paths``, or in ``CASES_DIR``'s ``*.toml`` files in
    name order, in file order. Raises :class:`CaseFileError` on a file that
    does not parse or match the format, and on a case id used twice."""
    files = sorted(CASES_DIR.glob("*.toml")) if paths is None else list(paths)
    cases: list[Case] = []
    for path in files:
        try:
            # tomllib returns untyped parsed data; parse_cases checks every
            # field it reads, so Any stops here.
            data: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as err:
            raise CaseFileError(f"{path.name}: {err}") from err
        for case in parse_cases(data, path.name):
            if any(seen.id == case.id for seen in cases):
                raise CaseFileError(f"{path.name}: case '{case.id}' is repeated")
            cases.append(case)
    return cases
