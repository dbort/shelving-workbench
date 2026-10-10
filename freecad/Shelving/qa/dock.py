"""The QA Wizard dock: a case list, then one step at a time with its setup
button, advisory check, verdict buttons and comment.

A verdict is final and moves to the next step; Restart case clears a
case's verdicts. Every verdict is saved at once, so the run survives a
FreeCAD restart. Lives in a dock rather than the Tasks panel because Edit
Unit holds that panel, which takes one dialog at a time.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path

import FreeCAD
import FreeCADGui
from PySide6 import QtCore, QtWidgets

from freecad.Shelving.qa import actions as _register_actions  # noqa: F401
from freecad.Shelving.qa.model import Case, Step, load_cases
from freecad.Shelving.qa.registry import ACTIONS, CHECKS, CheckResult
from freecad.Shelving.qa.report import (
    Progress,
    StepResult,
    Verdict,
    build_report,
    load_progress,
    save_progress,
)

_FAIL_PROMPT = (
    "Add a comment on what you saw, or press Fail again to record it without one."
)


def _now() -> str:
    return datetime.now().isoformat(sep=" ", timespec="seconds")


def report_view_text() -> str:
    """Everything the Report view shows, or ``""`` when it cannot be found."""
    found = FreeCADGui.getMainWindow().findChild(QtWidgets.QTextEdit, "Report view")
    return found.toPlainText() if isinstance(found, QtWidgets.QTextEdit) else ""


def _commit() -> str:
    try:
        run = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return run.stdout.strip() or "unknown"


def _status(case: Case, progress: Progress) -> str:
    recorded = progress.results.get(case.id, {})
    verdicts = {result.verdict for result in recorded.values()}
    if not recorded:
        return "not run"
    if "fail" in verdicts:
        return "failed"
    if len(recorded) < len(case.steps):
        return "in progress"
    return "passed" if "pass" in verdicts else "skipped"


class QAWizard(QtWidgets.QDockWidget):
    """The dock. ``ask_resume`` is asked whether to continue saved progress
    found at ``progress_path``; ``read_log`` returns the Report view's text,
    whose growth while a step is current becomes that step's log."""

    def __init__(
        self,
        cases: Sequence[Case],
        progress_path: Path,
        report_path: Path,
        ask_resume: Callable[[], bool],
        read_log: Callable[[], str] = report_view_text,
    ) -> None:
        super().__init__("QA Wizard")
        self.setObjectName("ShelvingQAWizard")
        self.cases = list(cases)
        self._progress_path = progress_path
        self._report_path = report_path
        self._read_log = read_log
        self.progress = Progress(started=_now())
        if progress_path.exists():
            try:
                saved = load_progress(progress_path)
            except (OSError, ValueError):
                saved = None
            if saved is not None and ask_resume():
                self.progress = saved
        self._case: Case | None = None
        self._log_start = 0
        self._fail_prompted = False

        self.pages = QtWidgets.QStackedWidget()
        self.setWidget(self.pages)
        self.pages.addWidget(self._build_list_page())
        self.pages.addWidget(self._build_step_page())
        self._show_list()

    def _build_list_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        self.case_list = QtWidgets.QListWidget()
        layout.addWidget(self.case_list)
        self.start_button = QtWidgets.QPushButton("Start next case")
        self.open_button = QtWidgets.QPushButton("Open selected case")
        self.copy_button = QtWidgets.QPushButton("Copy report")
        self.report_label = QtWidgets.QLabel("")
        self.report_label.setWordWrap(True)
        for widget in (
            self.start_button,
            self.open_button,
            self.copy_button,
            self.report_label,
        ):
            layout.addWidget(widget)
        self.start_button.clicked.connect(self._start_next)
        self.open_button.clicked.connect(self._open_selected)
        self.copy_button.clicked.connect(self.copy_report)
        return page

    def _build_step_page(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        self.title_label = QtWidgets.QLabel("")
        self.position_label = QtWidgets.QLabel("")
        self.instruction_label = QtWidgets.QLabel("")
        self.expected_label = QtWidgets.QLabel("")
        self.action_button = QtWidgets.QPushButton("")
        self.action_label = QtWidgets.QLabel("")
        self.check_button = QtWidgets.QPushButton("Run check")
        self.check_label = QtWidgets.QLabel("")
        self.comment_edit = QtWidgets.QPlainTextEdit()
        self.comment_edit.setPlaceholderText("Comment (optional)")
        self.prompt_label = QtWidgets.QLabel("")
        verdict_row = QtWidgets.QHBoxLayout()
        self.verdict_buttons: dict[Verdict, QtWidgets.QPushButton] = {}
        choices: tuple[tuple[Verdict, str], ...] = (
            ("pass", "Pass"),
            ("fail", "Fail"),
            ("skip", "Skip"),
        )
        for verdict, text in choices:
            button = QtWidgets.QPushButton(text)
            button.clicked.connect(lambda _=False, v=verdict: self.record(v))
            verdict_row.addWidget(button)
            self.verdict_buttons[verdict] = button
        self.restart_button = QtWidgets.QPushButton("Restart case")
        self.back_button = QtWidgets.QPushButton("Back to cases")
        for widget in (
            self.title_label,
            self.position_label,
            self.instruction_label,
            self.expected_label,
            self.action_button,
            self.action_label,
            self.check_button,
            self.check_label,
            self.comment_edit,
            self.prompt_label,
        ):
            if isinstance(widget, QtWidgets.QLabel):
                widget.setWordWrap(True)
            layout.addWidget(widget)
        layout.addLayout(verdict_row)
        layout.addWidget(self.restart_button)
        layout.addWidget(self.back_button)
        self.action_button.clicked.connect(self.run_action)
        self.check_button.clicked.connect(self._show_check)
        self.restart_button.clicked.connect(self._restart_case)
        self.back_button.clicked.connect(self._show_list)
        return page

    def _show_list(self) -> None:
        self._case = None
        self.case_list.clear()
        for case in self.cases:
            self.case_list.addItem(f"{case.title}: {_status(case, self.progress)}")
        self.pages.setCurrentIndex(0)

    def _start_next(self) -> None:
        for case in self.cases:
            if case.id not in self.progress.results:
                self.open_case(case.id)
                return

    def _open_selected(self) -> None:
        row = self.case_list.currentRow()
        if 0 <= row < len(self.cases):
            self.open_case(self.cases[row].id)

    def open_case(self, case_id: str) -> None:
        self._case = next(case for case in self.cases if case.id == case_id)
        self.pages.setCurrentIndex(1)
        self._show_step()

    def _current_step(self) -> Step | None:
        if self._case is None:
            return None
        recorded = self.progress.results.get(self._case.id, {})
        return next((s for s in self._case.steps if s.id not in recorded), None)

    def _show_step(self) -> None:
        assert self._case is not None
        step = self._current_step()
        self.title_label.setText(self._case.title)
        self.action_label.setText("")
        self.check_label.setText("")
        self.prompt_label.setText("")
        self.comment_edit.clear()
        self._fail_prompted = False
        for button in self.verdict_buttons.values():
            button.setEnabled(step is not None)
        if step is None:
            self.position_label.setText("Every step is recorded.")
            for widget in (
                self.instruction_label,
                self.expected_label,
            ):
                widget.setText("")
            self.action_button.hide()
            self.check_button.hide()
            return
        index = self._case.steps.index(step) + 1
        self.position_label.setText(f"Step {index} of {len(self._case.steps)}")
        self.instruction_label.setText(step.instruction)
        self.expected_label.setText(f"Expected: {step.expected}")
        self.action_button.setVisible(step.action is not None)
        if step.action is not None:
            self.action_button.setText(ACTIONS[step.action].label)
        self.check_button.setVisible(step.check is not None)
        self._log_start = len(self._read_log())

    def run_action(self) -> None:
        step = self._current_step()
        if step is None or step.action is None:
            return
        try:
            message = ACTIONS[step.action].run()
        except Exception as err:  # noqa: BLE001 - shown, the step carries on
            message = f"The action failed: {err}"
        self.action_label.setText(message or "Done.")

    def _run_check(self, step: Step) -> CheckResult | None:
        if step.check is None:
            return None
        try:
            return CHECKS[step.check](FreeCAD.ActiveDocument)
        except Exception as err:  # noqa: BLE001 - a broken check is a result
            return CheckResult(passed=False, detail=f"the check raised: {err}")

    def _show_check(self) -> None:
        step = self._current_step()
        result = None if step is None else self._run_check(step)
        if result is not None:
            mark = "passes" if result.passed else "does not pass"
            self.check_label.setText(f"Check {mark}: {result.detail}")

    def record(self, verdict: Verdict) -> None:
        """Record ``verdict`` and the comment for the current step, save, and
        move on. The first Fail with no comment only prompts for one."""
        step = self._current_step()
        if self._case is None or step is None:
            return
        comment = self.comment_edit.toPlainText().strip()
        if verdict == "fail" and not comment and not self._fail_prompted:
            self._fail_prompted = True
            self.prompt_label.setText(_FAIL_PROMPT)
            return
        text = self._read_log()
        log = text[self._log_start :] if len(text) >= self._log_start else text
        self.progress.results.setdefault(self._case.id, {})[step.id] = StepResult(
            verdict=verdict, comment=comment, check=self._run_check(step), log=log
        )
        save_progress(self.progress, self._progress_path)
        self._show_step()

    def _restart_case(self) -> None:
        if self._case is None:
            return
        self.progress.results.pop(self._case.id, None)
        save_progress(self.progress, self._progress_path)
        self._show_step()

    def copy_report(self) -> str:
        """Build the report, save it to the report path, put it on the
        clipboard, and return it."""
        version = ".".join(str(part) for part in FreeCAD.Version()[:3])
        report = build_report(self.cases, self.progress, version, _commit(), _now())
        self._report_path.parent.mkdir(parents=True, exist_ok=True)
        self._report_path.write_text(report, encoding="utf-8")
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(report)
        self.report_label.setText(f"Copied, and saved to {self._report_path}")
        return report


_open: QAWizard | None = None


def _ask_resume() -> bool:
    answer = QtWidgets.QMessageBox.question(
        FreeCADGui.getMainWindow(),
        "QA Wizard",
        "Resume the saved QA run? No starts a new one.",
    )
    return answer == QtWidgets.QMessageBox.StandardButton.Yes


def show() -> QAWizard:
    """Show the wizard docked in FreeCAD's main window, creating it the
    first time, and return it."""
    global _open
    if _open is None:
        data_dir = Path(FreeCAD.getUserAppDataDir()) / "Shelving"
        _open = QAWizard(
            load_cases(),
            data_dir / "qa-progress.json",
            data_dir / "qa-report.json",
            _ask_resume,
        )
        FreeCADGui.getMainWindow().addDockWidget(
            QtCore.Qt.DockWidgetArea.RightDockWidgetArea, _open
        )
    _open.show()
    _open.raise_()
    return _open
