"""Recorded QA results: the progress file that survives a restart, and the
JSON report a person pastes back into an LLM session.

Imports no FreeCAD; the dock supplies the version, commit and times.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict, cast

from freecad.Shelving.qa.model import Case
from freecad.Shelving.qa.registry import CheckResult

Verdict = Literal["pass", "fail", "skip"]
_VERDICTS: tuple[Verdict, ...] = ("pass", "fail", "skip")


@dataclass(frozen=True)
class StepResult:
    verdict: Verdict
    comment: str
    check: CheckResult | None
    # The Report view text printed while the step was current.
    log: str
    # One entry per press of the step's setup button, in order: what the
    # action printed, "done" when it printed nothing, or "failed: <error>".
    presses: tuple[str, ...] = ()


@dataclass
class Progress:
    # When the wizard began this run: built without resuming, or the saved
    # run's own start when resumed. ``YYYY-MM-DD HH:MM:SS``, local time.
    started: str
    # Case id to step id to result, in recording order.
    results: dict[str, dict[str, StepResult]] = field(default_factory=dict)


class _CheckJson(TypedDict):
    passed: bool
    detail: str


class _StepJson(TypedDict):
    verdict: Verdict
    comment: str
    check: _CheckJson | None
    log: str
    presses: list[str]


def _step_json(result: StepResult) -> _StepJson:
    check: _CheckJson | None = (
        None
        if result.check is None
        else {"passed": result.check.passed, "detail": result.check.detail}
    )
    return {
        "verdict": result.verdict,
        "comment": result.comment,
        "check": check,
        "log": result.log,
        "presses": list(result.presses),
    }


def save_progress(progress: Progress, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "started": progress.started,
        "results": {
            case_id: {step_id: _step_json(r) for step_id, r in steps.items()}
            for case_id, steps in progress.results.items()
        },
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _step_result(data: object, where: str) -> StepResult:
    if not isinstance(data, dict):
        raise ValueError(f"{where}: not an object")
    verdict = data.get("verdict")
    comment = data.get("comment")
    log = data.get("log")
    check = data.get("check")
    if verdict not in _VERDICTS or not isinstance(comment, str):
        raise ValueError(f"{where}: bad verdict or comment")
    if not isinstance(log, str):
        raise ValueError(f"{where}: bad log")
    presses = data.get("presses", [])
    if not isinstance(presses, list) or not all(isinstance(p, str) for p in presses):
        raise ValueError(f"{where}: bad presses")
    check_result: CheckResult | None = None
    if check is not None:
        if not isinstance(check, dict):
            raise ValueError(f"{where}: bad check")
        passed = check.get("passed")
        detail = check.get("detail")
        if not isinstance(passed, bool) or not isinstance(detail, str):
            raise ValueError(f"{where}: bad check")
        check_result = CheckResult(passed=passed, detail=detail)
    return StepResult(
        verdict=cast("Verdict", verdict),
        comment=comment,
        check=check_result,
        log=log,
        presses=tuple(presses),
    )


def load_progress(path: Path) -> Progress:
    """The progress saved at ``path``. Raises ``OSError`` when it cannot be
    read and ``ValueError`` when it is not progress this module wrote."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("started"), str):
        raise ValueError(f"{path}: not a QA progress file")
    results_data = data.get("results")
    if not isinstance(results_data, dict):
        raise ValueError(f"{path}: no results")
    results: dict[str, dict[str, StepResult]] = {}
    for case_id, steps in results_data.items():
        if not isinstance(steps, dict):
            raise ValueError(f"{path}: case '{case_id}' is not an object")
        results[case_id] = {
            step_id: _step_result(step, f"{path}: {case_id}/{step_id}")
            for step_id, step in steps.items()
        }
    return Progress(started=data["started"], results=results)


def build_report(
    cases: Sequence[Case],
    progress: Progress,
    freecad_version: str,
    commit: str,
    finished: str,
) -> str:
    """The run as indented JSON: the FreeCAD version, the checkout's commit,
    start and end times, and every case with at least one recorded step, in
    ``cases`` order, each step in its case's order with its setup action's
    name (null when it has none), verdict, comment, check result, log and
    button presses. Steps not yet recorded are left out."""
    report_cases = []
    for case in cases:
        recorded = progress.results.get(case.id, {})
        if not recorded:
            continue
        report_cases.append(
            {
                "id": case.id,
                "title": case.title,
                "steps": [
                    {
                        "id": step.id,
                        "action": step.action,
                        **_step_json(recorded[step.id]),
                    }
                    for step in case.steps
                    if step.id in recorded
                ],
            }
        )
    return json.dumps(
        {
            "freecad_version": freecad_version,
            "commit": commit,
            "started": progress.started,
            "finished": finished,
            "cases": report_cases,
        },
        indent=2,
    )
