"""The QA wizard's case files, registry, report and progress file, without
FreeCAD."""

import json
from pathlib import Path

import pytest

import freecad.Shelving.qa.actions  # noqa: F401 - registers every action
from freecad.Shelving.qa.model import CaseFileError, load_cases, parse_cases
from freecad.Shelving.qa.registry import ACTIONS, CHECKS, CheckResult
from freecad.Shelving.qa.report import (
    Progress,
    StepResult,
    build_report,
    load_progress,
    save_progress,
)


def test_every_case_file_loads() -> None:
    cases = load_cases()
    assert [case.id for case in cases][:2] == [
        "scan.refusal",
        "editor.camera",
    ]
    assert len(cases) == 9
    assert all(case.steps for case in cases)


def test_cases_name_only_registered_actions_and_checks() -> None:
    cases = load_cases()
    actions = {step.action for case in cases for step in case.steps if step.action}
    checks = {step.check for case in cases for step in case.steps if step.check}
    assert actions <= set(ACTIONS), actions - set(ACTIONS)
    assert checks <= set(CHECKS), checks - set(CHECKS)


def test_every_registered_action_and_check_is_used() -> None:
    cases = load_cases()
    actions = {step.action for case in cases for step in case.steps if step.action}
    checks = {step.check for case in cases for step in case.steps if step.check}
    assert set(ACTIONS) <= actions, set(ACTIONS) - actions
    assert set(CHECKS) <= checks, set(CHECKS) - checks


def test_a_missing_field_and_a_repeated_id_are_refused(tmp_path: Path) -> None:
    with pytest.raises(CaseFileError, match="'expected'"):
        parse_cases(
            {
                "case": [
                    {
                        "id": "c",
                        "title": "C",
                        "step": [{"id": "s", "instruction": ["Do."]}],
                    }
                ]
            },
            "x.toml",
        )
    text = (
        '[[case]]\nid = "c"\ntitle = "C"\n[[case.step]]\nid = "s"\n'
        'instruction = ["Do."]\nexpected = "Done."\n'
    )
    first = tmp_path / "a.toml"
    second = tmp_path / "b.toml"
    first.write_text(text, encoding="utf-8")
    second.write_text(text, encoding="utf-8")
    with pytest.raises(CaseFileError, match="'c' is repeated"):
        load_cases([first, second])


def _progress() -> Progress:
    return Progress(
        started="2026-10-10 09:00:00",
        results={
            "editor.undo": {
                "start": StepResult(
                    "pass", "", None, "", presses=("done", "failed: no unit")
                ),
                "keyboard-undo": StepResult(
                    "fail",
                    "The unit stayed taller",
                    CheckResult(passed=False, detail="600 x 300 x 1000 mm"),
                    "[shelving] edit unit\n",
                ),
                "add-shelves": StepResult("pass", "", None, "grew\n"),
            }
        },
    )


def test_the_report_holds_each_recorded_step_and_the_run() -> None:
    report = json.loads(
        build_report(
            load_cases(), _progress(), "1.1.3", "abc1234", "2026-10-10 09:05:00"
        )
    )
    assert report["freecad_version"] == "1.1.3"
    assert report["commit"] == "abc1234"
    assert report["started"] == "2026-10-10 09:00:00"
    assert report["finished"] == "2026-10-10 09:05:00"
    (case,) = report["cases"]
    assert case["id"] == "editor.undo"
    assert [step["id"] for step in case["steps"]] == [
        "start",
        "add-shelves",
        "keyboard-undo",
    ]
    assert case["steps"][0]["action"] == "fresh_unit"
    assert case["steps"][0]["presses"] == ["done", "failed: no unit"]
    assert case["steps"][2]["action"] is None
    failed = case["steps"][2]
    assert failed["verdict"] == "fail"
    assert failed["comment"] == "The unit stayed taller"
    assert failed["check"] == {"passed": False, "detail": "600 x 300 x 1000 mm"}
    assert failed["log"] == "[shelving] edit unit\n"


def test_progress_survives_a_save_and_load(tmp_path: Path) -> None:
    path = tmp_path / "shelving-qa-user" / "progress.json"
    save_progress(_progress(), path)
    assert load_progress(path) == _progress()


def test_a_file_that_is_not_progress_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "qa-progress.json"
    path.write_text('{"cases": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a QA progress file"):
        load_progress(path)


def test_a_repeated_step_id_is_refused() -> None:
    step = {"id": "s", "instruction": ["Do."], "expected": "Done."}
    with pytest.raises(CaseFileError, match="step 's': repeated step id"):
        parse_cases({"case": [{"id": "c", "title": "C", "step": [step, step]}]}, "x")


def test_the_camera_start_step_carries_the_fresh_unit_check() -> None:
    (case,) = [c for c in load_cases() if c.id == "editor.camera"]
    (step,) = [s for s in case.steps if s.id == "start"]
    assert step.check == "fresh_unit_size"


def test_only_a_step_with_a_button_may_omit_its_instruction() -> None:
    step: dict[str, object] = {"id": "s", "action": "fresh_unit", "expected": "Done."}
    (case,) = parse_cases({"case": [{"id": "c", "title": "C", "step": [step]}]}, "x")
    assert case.steps[0].instruction == ()
    del step["action"]
    with pytest.raises(CaseFileError, match="'instruction' must be a list"):
        parse_cases({"case": [{"id": "c", "title": "C", "step": [step]}]}, "x")
