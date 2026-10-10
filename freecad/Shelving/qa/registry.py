"""The setup actions and advisory checks QA cases name.

Registered by decorator in :mod:`freecad.Shelving.qa.actions`. This module
imports no FreeCAD, so the case files can be checked against it in the
FreeCAD-free suite.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import FreeCAD


@dataclass(frozen=True)
class CheckResult:
    passed: bool
    # What the check read, in words for the person and the report.
    detail: str


# Returns a line to show under the button (a saved file's path, say), or
# None.
ActionFn = Callable[[], "str | None"]
CheckFn = Callable[["FreeCAD.Document | None"], CheckResult]


@dataclass(frozen=True)
class Action:
    # The button text.
    label: str
    run: ActionFn


ACTIONS: dict[str, Action] = {}
CHECKS: dict[str, CheckFn] = {}


def action(name: str, label: str) -> Callable[[ActionFn], ActionFn]:
    """Register the decorated function as setup action ``name``, shown as a
    button reading ``label``. Raises ``ValueError`` on a repeated name."""

    def register(run: ActionFn) -> ActionFn:
        if name in ACTIONS:
            raise ValueError(f"action '{name}' is registered twice")
        ACTIONS[name] = Action(label=label, run=run)
        return run

    return register


def check(name: str) -> Callable[[CheckFn], CheckFn]:
    """Register the decorated function as advisory check ``name``; it reads
    the active document, ``None`` when there is none. Raises ``ValueError``
    on a repeated name."""

    def register(run: CheckFn) -> CheckFn:
        if name in CHECKS:
            raise ValueError(f"check '{name}' is registered twice")
        CHECKS[name] = run
        return run

    return register
