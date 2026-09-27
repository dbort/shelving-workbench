"""Coverage of ``tools/task_status.py``: pure helpers, then a throwaway git repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tools.task_status import (
    Frontmatter,
    TaskParseError,
    build_backlog,
    compute_next_id,
    derive_status,
    last_review_round,
    layered_topological_order,
    main,
    parse_frontmatter,
)


def _task_text(
    task_id: str, blocked_by: list[str] | None = None, review_log: str = ""
) -> str:
    blocked = f"blocked_by: [{', '.join(blocked_by)}]\n" if blocked_by else ""
    return (
        f'---\nid: {task_id}\ntitle: "Title {task_id}"\n{blocked}---\n\n'
        f"# {task_id}: Title\n\n## Review log\n{review_log}"
    )


def test_parse_frontmatter() -> None:
    assert parse_frontmatter(_task_text("sh-003", ["sh-001"])) == Frontmatter(
        "sh-003", "Title sh-003", ("sh-001",)
    )


def test_parse_frontmatter_ignores_legacy_keys() -> None:
    text = '---\nid: sh-001\ntitle: "T"\ncurrent_phase: planning\n---\n'
    assert parse_frontmatter(text) == Frontmatter("sh-001", "T")


@pytest.mark.parametrize(
    "text",
    [
        "no frontmatter\n",
        "---\n- a list\n---\n",
        '---\ntitle: "T"\n---\n',
        "---\nid: sh-1\ntitle: T\nblocked_by: sh-2\n---\n",
    ],
)
def test_parse_frontmatter_rejects_malformed(text: str) -> None:
    with pytest.raises(TaskParseError):
        parse_frontmatter(text)


def test_last_review_round_takes_the_last_heading() -> None:
    log = "### Round 1: REJECTED\n- F1\n### Round 2: APPROVED\n"
    assert last_review_round(_task_text("sh-001", review_log=log)) == (2, "APPROVED")
    assert last_review_round(_task_text("sh-001")) is None


@pytest.mark.parametrize(
    ("branch_exists", "log", "expected"),
    [
        (False, "", "planned"),
        (True, "", "in progress"),
        (True, "### Round 1: REJECTED\n", "in progress, round 1 rejected"),
        (True, "### Round 1: REJECTED\n### Round 2: APPROVED\n", "awaiting /ship"),
    ],
)
def test_derive_status(branch_exists: bool, log: str, expected: str) -> None:
    assert (
        derive_status(branch_exists, _task_text("sh-001", review_log=log)) == expected
    )


@pytest.mark.parametrize(
    ("ids", "expected"),
    [([], "sh-001"), (["sh-009", "sh-010", "junk"], "sh-011"), (["sh-999"], "sh-1000")],
)
def test_compute_next_id(ids: list[str], expected: str) -> None:
    assert compute_next_id(ids) == expected


def test_layered_topological_order() -> None:
    graph = {
        "sh-3": ["sh-1", "sh-2"],
        "sh-2": ["sh-1", "sh-0"],
        "sh-1": [],
        "sh-8": ["sh-9"],
        "sh-9": ["sh-8"],
    }
    assert layered_topological_order(graph) == (
        [["sh-1"], ["sh-2"], ["sh-3"]],
        ["sh-8", "sh-9"],
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _write(tmp_path, "tasks/completed/sh-001-done.md", _task_text("sh-001"))
    _write(
        tmp_path, "tasks/active/sh-002-approved.md", _task_text("sh-002", ["sh-001"])
    )
    _write(tmp_path, "tasks/active/sh-003-planned.md", _task_text("sh-003", ["sh-002"]))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "init")
    _git(tmp_path, "checkout", "-q", "-b", "sh-002")
    _write(
        tmp_path,
        "tasks/active/sh-002-approved.md",
        _task_text("sh-002", ["sh-001"], "### Round 1: APPROVED\n"),
    )
    _write(tmp_path, "tasks/active/sh-005-elsewhere.md", _task_text("sh-005"))
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "work")
    _git(tmp_path, "checkout", "-q", "main")
    return tmp_path


def test_build_backlog_reads_status_from_the_branch(repo: Path) -> None:
    entries, errors = build_backlog(repo)
    assert errors == []
    assert [(e.id, e.status, e.unmet_blockers) for e in entries] == [
        ("sh-002", "awaiting /ship", ()),
        ("sh-003", "planned", ("sh-002",)),
    ]


def test_build_backlog_reports_unreadable_files(repo: Path) -> None:
    _write(repo, "tasks/active/sh-004-broken.md", "no frontmatter\n")
    entries, errors = build_backlog(repo)
    assert len(entries) == 2
    assert errors == ["tasks/active/sh-004-broken.md: no leading --- frontmatter block"]


def test_next_id_counts_other_branches(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--next-id"], repo_root=repo) == 0
    assert capsys.readouterr().out == "sh-006\n"


def test_main_renders_backlog(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([], repo_root=repo) == 0
    out = capsys.readouterr().out
    assert out.startswith("Next id: sh-006\n")
    assert "- sh-003 [planned; blocked by sh-002]: Title sh-003" in out
