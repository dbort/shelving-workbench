"""Fast-tier coverage of ``tools/check_dev_extra.py``, the [dev]-extra preflight.

``./test.sh --fast`` calls this helper before ruff/mypy/pytest and treats its
exit 3 plus fixed message as a contract: a stale environment must produce one
actionable line, not a pytest collection error. Agents branch on that exit code,
so the message text and status are pinned here instead of re-derived by hand
each review round. The name-extraction rules (version specifiers, markers,
extras, ``@`` direct references) are exercised directly.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tools.check_dev_extra import dev_extra_names, main, missing_distributions

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "tools" / "check_dev_extra.py"

MESSAGE_TEMPLATE = (
    "dev environment is out of sync with the [dev] extra: {names}. "
    "Run tools/install-deps.sh."
)

# Names that will never resolve as installed distributions in the test env.
ABSENT_ONE = "shelving-workbench-no-such-dist-1"
ABSENT_TWO = "shelving-workbench-no-such-dist-2"


def _write_pyproject(tmp_path: Path, dev: list[str]) -> Path:
    entries = ", ".join(f'"{item}"' for item in dev)
    path = tmp_path / "pyproject.toml"
    path.write_text(
        textwrap.dedent(f"""\
            [project]
            name = "sample"
            version = "0"

            [project.optional-dependencies]
            dev = [{entries}]
            """),
        encoding="utf-8",
    )
    return path


def test_dev_extra_names_strips_every_specifier_form(tmp_path: Path) -> None:
    path = _write_pyproject(
        tmp_path,
        [
            "ruff",
            "mypy>=1.0",
            "pytest [cov]",
            "typing-extensions ; python_version < '3.13'",
            "pkg @ https://example.invalid/pkg-1.0-py3-none-any.whl",
        ],
    )
    assert dev_extra_names(path) == [
        "ruff",
        "mypy",
        "pytest",
        "typing-extensions",
        "pkg",
    ]


def test_missing_distributions_keeps_input_order(tmp_path: Path) -> None:
    names = ["pytest", ABSENT_ONE, "ruff", ABSENT_TWO]
    assert missing_distributions(names) == [ABSENT_ONE, ABSENT_TWO]


def test_missing_distributions_empty_when_all_present() -> None:
    assert missing_distributions(["pytest", "ruff"]) == []


def test_main_exits_3_with_exact_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_pyproject(tmp_path, ["pytest", ABSENT_ONE, ABSENT_TWO])
    status = main([str(path)])
    assert status == 3
    assert capsys.readouterr().err.strip() == MESSAGE_TEMPLATE.format(
        names=f"{ABSENT_ONE}, {ABSENT_TWO}"
    )


def test_main_exits_0_when_synced(tmp_path: Path) -> None:
    path = _write_pyproject(tmp_path, ["pytest", "ruff"])
    assert main([str(path)]) == 0


def test_cli_entrypoint_exits_3_and_prints_message(tmp_path: Path) -> None:
    path = _write_pyproject(tmp_path, [ABSENT_ONE])
    result = subprocess.run(
        [sys.executable, str(HELPER), str(path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 3
    assert result.stderr.strip() == MESSAGE_TEMPLATE.format(names=ABSENT_ONE)
