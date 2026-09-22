"""Coverage of ``tools/task_status.py``, the tasks/ pipeline status report.

The pure core (frontmatter parsing, id allocation, blocker resolution, and
the layered topological sort) is exercised here against synthetic strings
and mappings with no filesystem or git involved; the git/filesystem layer
built on top of it is exercised separately, against a throwaway temporary
git repository this module's own fixtures create.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.task_status import (
    Anomaly,
    ErrorTaskReportEntry,
    NormalTaskReportEntry,
    Report,
    TaskFrontmatter,
    TaskParseError,
    TaskStatusError,
    build_report,
    compute_next_id,
    gather_next_id_input,
    layered_topological_order,
    main,
    parse_frontmatter,
    read_authoritative_task_text,
    render_human_report,
    report_to_json,
    resolve_blocking,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
HELPER = REPO_ROOT / "tools" / "task_status.py"

# ---------------------------------------------------------------------------
# parse_frontmatter
# ---------------------------------------------------------------------------


def _frontmatter_text(body: str) -> str:
    return f"---\n{body}\n---\n\n# sh-001: A title\n"


def test_parse_frontmatter_minimal() -> None:
    text = _frontmatter_text(
        "id: sh-001\n"
        'title: "A title"\n'
        "current_agent: implementer\n"
        "current_phase: implementation\n"
        "review_rejections: 0\n"
    )
    assert parse_frontmatter(text) == TaskFrontmatter(
        id="sh-001",
        title="A title",
        current_agent="implementer",
        current_phase="implementation",
        review_rejections=0,
        blocked_by=[],
    )


def test_parse_frontmatter_with_blocked_by() -> None:
    text = _frontmatter_text(
        "id: sh-020\n"
        'title: "Has a colon: right here"\n'
        "current_agent: implementer\n"
        "current_phase: planning\n"
        "review_rejections: 2\n"
        "blocked_by: [sh-018, sh-019]\n"
    )
    parsed = parse_frontmatter(text)
    assert parsed.title == "Has a colon: right here"
    assert parsed.blocked_by == ["sh-018", "sh-019"]
    assert parsed.review_rejections == 2


def test_parse_frontmatter_missing_delimiter_raises() -> None:
    try:
        parse_frontmatter("id: sh-001\ntitle: x\n")
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


def test_parse_frontmatter_unclosed_block_raises() -> None:
    try:
        parse_frontmatter("---\nid: sh-001\n")
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


def test_parse_frontmatter_missing_required_key_raises() -> None:
    text = _frontmatter_text(
        "id: sh-001\ntitle: x\ncurrent_agent: implementer\ncurrent_phase: planning\n"
    )
    try:
        parse_frontmatter(text)
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


def test_parse_frontmatter_extra_key_raises() -> None:
    text = _frontmatter_text(
        "id: sh-001\n"
        "title: x\n"
        "current_agent: implementer\n"
        "current_phase: planning\n"
        "review_rejections: 0\n"
        "unexpected_field: 1\n"
    )
    try:
        parse_frontmatter(text)
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


def test_parse_frontmatter_not_a_mapping_raises() -> None:
    text = "---\n- one\n- two\n---\n"
    try:
        parse_frontmatter(text)
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


def test_parse_frontmatter_malformed_yaml_raises() -> None:
    text = "---\nid: [unclosed\n---\n"
    try:
        parse_frontmatter(text)
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


def test_parse_frontmatter_wrong_field_type_raises() -> None:
    text = _frontmatter_text(
        "id: sh-001\n"
        "title: x\n"
        "current_agent: implementer\n"
        "current_phase: planning\n"
        'review_rejections: "zero"\n'
    )
    try:
        parse_frontmatter(text)
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


def test_parse_frontmatter_bool_review_rejections_raises() -> None:
    # bool is an int subclass in Python; must not silently pass as 0/1.
    text = _frontmatter_text(
        "id: sh-001\n"
        "title: x\n"
        "current_agent: implementer\n"
        "current_phase: planning\n"
        "review_rejections: true\n"
    )
    try:
        parse_frontmatter(text)
    except TaskParseError:
        pass
    else:
        raise AssertionError("expected TaskParseError")


# ---------------------------------------------------------------------------
# compute_next_id
# ---------------------------------------------------------------------------


def test_compute_next_id_basic() -> None:
    assert compute_next_id(["sh-001", "sh-007", "sh-003"]) == "sh-008"


def test_compute_next_id_ignores_non_matching_entries() -> None:
    assert compute_next_id(["sh-001", "not-a-task-id", "sh-002"]) == "sh-003"


def test_compute_next_id_empty_input_starts_at_one() -> None:
    assert compute_next_id([]) == "sh-001"


def test_compute_next_id_widens_padding_on_overflow() -> None:
    assert compute_next_id(["sh-998", "sh-999"]) == "sh-1000"


def test_compute_next_id_preserves_padding_width() -> None:
    assert compute_next_id(["sh-007"]) == "sh-008"


# ---------------------------------------------------------------------------
# resolve_blocking
# ---------------------------------------------------------------------------


def test_resolve_blocking_unblocked() -> None:
    assert resolve_blocking([], {"sh-001"}) == ([], False)


def test_resolve_blocking_single_unmet_blocker() -> None:
    assert resolve_blocking(["sh-005"], {"sh-001"}) == (["sh-005"], True)


def test_resolve_blocking_single_met_blocker() -> None:
    assert resolve_blocking(["sh-001"], {"sh-001"}) == ([], False)


def test_resolve_blocking_multiple_mixed_blockers() -> None:
    unmet, blocked = resolve_blocking(
        ["sh-001", "sh-002", "sh-003"], {"sh-001", "sh-003"}
    )
    assert unmet == ["sh-002"]
    assert blocked is True


# ---------------------------------------------------------------------------
# layered_topological_order
# ---------------------------------------------------------------------------


def test_layered_topological_order_chain() -> None:
    layers, cycle = layered_topological_order(
        {"sh-001": [], "sh-002": ["sh-001"], "sh-003": ["sh-002"]}
    )
    assert layers == [["sh-001"], ["sh-002"], ["sh-003"]]
    assert cycle == []


def test_layered_topological_order_diamond() -> None:
    # sh-002 and sh-003 both block sh-004; sh-001 blocks both of them.
    layers, cycle = layered_topological_order(
        {
            "sh-001": [],
            "sh-002": ["sh-001"],
            "sh-003": ["sh-001"],
            "sh-004": ["sh-002", "sh-003"],
        }
    )
    assert layers == [["sh-001"], ["sh-002", "sh-003"], ["sh-004"]]
    assert cycle == []


def test_layered_topological_order_ties_sort_by_id() -> None:
    layers, _ = layered_topological_order({"sh-003": [], "sh-001": [], "sh-002": []})
    assert layers == [["sh-001", "sh-002", "sh-003"]]


def test_layered_topological_order_ignores_blockers_outside_the_set() -> None:
    # sh-099 is not itself a key (e.g. already completed): contributes no edge.
    layers, cycle = layered_topological_order({"sh-001": ["sh-099"]})
    assert layers == [["sh-001"]]
    assert cycle == []


def test_layered_topological_order_cycle_is_reported_not_hung() -> None:
    layers, cycle = layered_topological_order(
        {"sh-001": ["sh-002"], "sh-002": ["sh-001"], "sh-003": []}
    )
    assert layers == [["sh-003"]]
    assert cycle == ["sh-001", "sh-002"]


# ---------------------------------------------------------------------------
# The git/filesystem layer, against a throwaway temporary git repository.
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for subdir in ("active", "completed", "abandoned"):
        (repo / "tasks" / subdir).mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "tasks" / "active" / ".gitkeep").write_text("")
    (repo / "tasks" / "completed" / ".gitkeep").write_text("")
    (repo / "tasks" / "abandoned" / ".gitkeep").write_text("")
    _commit_all(repo, "init")
    return repo


def _task_frontmatter_text(
    task_id: str,
    title: str = "A title",
    current_agent: str = "implementer",
    current_phase: str = "implementation",
    review_rejections: int = 0,
    blocked_by: list[str] | None = None,
) -> str:
    lines = [
        "---",
        f"id: {task_id}",
        f'title: "{title}"',
        f"current_agent: {current_agent}",
        f"current_phase: {current_phase}",
        f"review_rejections: {review_rejections}",
    ]
    if blocked_by is not None:
        lines.append("blocked_by: [" + ", ".join(blocked_by) + "]")
    lines.append("---")
    return "\n".join(lines) + f"\n\n# {task_id}: {title}\n"


def _write_task(
    repo: Path,
    subdir: str,
    task_id: str,
    slug: str,
    title: str = "A title",
    current_agent: str = "implementer",
    current_phase: str = "implementation",
    review_rejections: int = 0,
    blocked_by: list[str] | None = None,
) -> Path:
    path = repo / "tasks" / subdir / f"{task_id}-{slug}.md"
    path.write_text(
        _task_frontmatter_text(
            task_id,
            title=title,
            current_agent=current_agent,
            current_phase=current_phase,
            review_rejections=review_rejections,
            blocked_by=blocked_by,
        )
    )
    return path


def test_gather_next_id_input_includes_uncommitted_working_tree_file(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "active", "sh-001", "one")
    _commit_all(repo, "add sh-001")
    _write_task(repo, "active", "sh-002", "two-uncommitted")  # never committed
    ids = gather_next_id_input(repo)
    assert "sh-001" in ids
    assert "sh-002" in ids


def test_gather_next_id_input_includes_ids_only_on_a_non_checked_out_branch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "active", "sh-001", "one")
    _commit_all(repo, "add sh-001")
    _git(repo, "checkout", "-q", "-b", "sh-002")
    _write_task(repo, "active", "sh-002", "two")
    _commit_all(repo, "add sh-002 on its own branch")
    _git(repo, "checkout", "-q", "main")
    # main's own working tree never saw sh-002; only the branch's tip has it.
    assert "sh-002" not in {p.name for p in (repo / "tasks" / "active").glob("*.md")}
    ids = gather_next_id_input(repo)
    assert "sh-002" in ids
    assert compute_next_id(ids) == "sh-003"


def test_read_authoritative_task_text_working_tree_when_no_branch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    path = _write_task(repo, "active", "sh-005", "five", current_phase="planning")
    _commit_all(repo, "add sh-005")
    text, source = read_authoritative_task_text(repo, "sh-005", path)
    assert source == "working_tree"
    assert "current_phase: planning" in text


def test_read_authoritative_task_text_reads_from_branch_when_stale_in_working_tree(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    path = _write_task(repo, "active", "sh-005", "five", current_phase="implementation")
    _commit_all(repo, "add sh-005")
    _git(repo, "checkout", "-q", "-b", "sh-005")
    _write_task(repo, "active", "sh-005", "five", current_phase="review")
    _commit_all(repo, "advance sh-005 to review")
    _git(repo, "checkout", "-q", "main")
    # main's working-tree copy is stale (still says "implementation").
    text, source = read_authoritative_task_text(repo, "sh-005", path)
    assert source == "branch:sh-005"
    assert "current_phase: review" in text


def test_read_authoritative_task_text_falls_back_to_completed_on_branch(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    path = _write_task(repo, "active", "sh-005", "five", current_phase="implementation")
    _commit_all(repo, "add sh-005")
    _git(repo, "checkout", "-q", "-b", "sh-005")
    # approve-task finished finalizing (moved the file) but hasn't merged yet.
    _git(repo, "mv", "tasks/active/sh-005-five.md", "tasks/completed/sh-005-five.md")
    completed_text = _task_frontmatter_text(
        "sh-005", current_agent="user", current_phase="done"
    )
    (repo / "tasks" / "completed" / "sh-005-five.md").write_text(completed_text)
    _commit_all(repo, "finalize sh-005")
    _git(repo, "checkout", "-q", "main")
    text, source = read_authoritative_task_text(repo, "sh-005", path)
    assert source == "branch:sh-005"
    assert "current_phase: done" in text


def test_build_report_empty_active_still_computes_next_id(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "completed", "sh-004", "four", current_phase="done")
    _commit_all(repo, "add completed sh-004")
    report = build_report(repo)
    assert report.tasks == []
    assert report.next_id == "sh-005"


def test_build_report_malformed_task_becomes_an_error_entry(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "active", "sh-001", "good")
    (repo / "tasks" / "active" / "sh-002-bad.md").write_text("---\nid: sh-002\n---\n")
    _commit_all(repo, "add one good, one malformed task")
    report = build_report(repo)
    by_id = {entry.id: entry for entry in report.tasks}
    assert isinstance(by_id["sh-001"], NormalTaskReportEntry)
    assert isinstance(by_id["sh-002"], ErrorTaskReportEntry)
    assert report.errors == ["sh-002"]


def test_build_report_skips_review_file_alongside_its_task(tmp_path: Path) -> None:
    # The rejection loop (`.claude/docs/pipeline.md` § The rejection loop)
    # leaves both `sh-XXX-<slug>.md` and `sh-XXX-REVIEW.md` in `tasks/active/`
    # on the task's own `sh-XXX` branch; `REVIEW` sorts before every real
    # slug in `git ls-tree` order, so this also pins that the authoritative
    # branch read finds the real task file rather than the review file.
    repo = _init_repo(tmp_path)
    _write_task(repo, "active", "sh-005", "five", current_phase="implementation")
    _commit_all(repo, "add sh-005")
    _git(repo, "checkout", "-q", "-b", "sh-005")
    (repo / "tasks" / "active" / "sh-005-REVIEW.md").write_text(
        "# sh-005 Review — Round 1\n\n**Verdict:** REJECTED\n"
    )
    _commit_all(repo, "reject sh-005, round 1")

    report = build_report(repo)

    matches = [entry for entry in report.tasks if entry.id == "sh-005"]
    assert len(matches) == 1
    entry = matches[0]
    assert isinstance(entry, NormalTaskReportEntry)
    assert entry.path == "tasks/active/sh-005-five.md"
    assert entry.source == "branch:sh-005"
    assert report.errors == []


def test_build_report_done_in_active_is_flagged_as_an_anomaly(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "active", "sh-001", "stranded", current_phase="done")
    _commit_all(repo, "add a done task stranded in active")
    report = build_report(repo)
    assert Anomaly(id="sh-001", reason="done_in_active") in report.anomalies


def test_build_report_circular_blocked_by_is_flagged_as_an_anomaly(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "active", "sh-006", "cycle-a", blocked_by=["sh-007"])
    _write_task(repo, "active", "sh-007", "cycle-b", blocked_by=["sh-006"])
    _commit_all(repo, "add a sh-006/sh-007 blocked_by cycle")
    report = build_report(repo)
    assert Anomaly(id="sh-006", reason="circular_blocked_by") in report.anomalies
    assert Anomaly(id="sh-007", reason="circular_blocked_by") in report.anomalies


def test_build_report_populates_blocked_and_branch_fields(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "completed", "sh-001", "done-one", current_phase="done")
    _write_task(
        repo, "active", "sh-002", "blocked-one", blocked_by=["sh-001", "sh-003"]
    )
    _commit_all(repo, "add sh-001 (completed) and sh-002 (active, blocked)")
    _git(repo, "branch", "sh-002")
    report = build_report(repo)
    entry = next(e for e in report.tasks if e.id == "sh-002")
    assert isinstance(entry, NormalTaskReportEntry)
    assert entry.blocked_by == ["sh-001", "sh-003"]
    assert entry.unmet_blockers == ["sh-003"]
    assert entry.blocked is True
    assert entry.branch_exists is True
    assert entry.in_progress is True


def test_build_report_raises_task_status_error_when_active_dir_missing(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "not-a-repo"
    repo.mkdir()
    with pytest.raises(TaskStatusError):
        build_report(repo)


# ---------------------------------------------------------------------------
# render_human_report, end to end against a small synthetic repo.
# ---------------------------------------------------------------------------


def test_render_human_report_ordering_and_fields(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "completed", "sh-001", "already-done", current_phase="done")
    _write_task(
        repo,
        "active",
        "sh-002",
        "mixed-blockers",
        title="Blocked on one done one active",
        blocked_by=["sh-001", "sh-003"],
    )
    _write_task(repo, "active", "sh-003", "no-blockers", title="No blockers")
    _write_task(
        repo,
        "active",
        "sh-004",
        "blocked-on-three",
        title="Blocked on sh-003",
        blocked_by=["sh-003"],
    )
    _write_task(
        repo, "active", "sh-006", "cycle-a", title="Cycle A", blocked_by=["sh-007"]
    )
    _write_task(
        repo, "active", "sh-007", "cycle-b", title="Cycle B", blocked_by=["sh-006"]
    )
    _commit_all(repo, "add synthetic repo for --human rendering")
    _git(repo, "branch", "sh-003")

    report = build_report(repo)
    rendered = render_human_report(report)

    # Layer 1 is sh-003, the only task with zero unresolved *active* blockers:
    # sh-001 is completed and contributes no edge, even though it appears in
    # sh-002's raw blocked_by. Layer 2 is sh-002 and sh-004, both freed once
    # sh-003 resolves, sorted by id. The sh-006/sh-007 cycle is appended
    # last, sorted by id, since neither task ever reaches zero remaining
    # blockers.
    assert rendered == (
        "Next id: sh-008\n"
        "\n"
        "- sh-003: No blockers\n"
        "  - path: tasks/active/sh-003-no-blockers.md\n"
        "  - branch: sh-003\n"
        "  - phase: implementation\n"
        "  - blocked by: (none)\n"
        "- sh-002: Blocked on one done one active\n"
        "  - path: tasks/active/sh-002-mixed-blockers.md\n"
        "  - phase: implementation\n"
        "  - blocked by: sh-003\n"
        "- sh-004: Blocked on sh-003\n"
        "  - path: tasks/active/sh-004-blocked-on-three.md\n"
        "  - phase: implementation\n"
        "  - blocked by: sh-003\n"
        "- sh-006: Cycle A\n"
        "  - path: tasks/active/sh-006-cycle-a.md\n"
        "  - phase: implementation\n"
        "  - blocked by: sh-007\n"
        "- sh-007: Cycle B\n"
        "  - path: tasks/active/sh-007-cycle-b.md\n"
        "  - phase: implementation\n"
        "  - blocked by: sh-006"
    )


def test_render_human_report_includes_error_entries_without_crashing(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path)
    _write_task(repo, "active", "sh-001", "good")
    (repo / "tasks" / "active" / "sh-002-bad.md").write_text("---\nid: sh-002\n---\n")
    _commit_all(repo, "add one good, one malformed task")
    report = build_report(repo)
    rendered = render_human_report(report)
    assert "- sh-002: ERROR:" in rendered
    assert "- sh-001: A title" in rendered


# ---------------------------------------------------------------------------
# report_to_json
# ---------------------------------------------------------------------------


def test_report_to_json_top_level_keys() -> None:
    report = Report(next_id="sh-001", tasks=[], errors=[], anomalies=[])
    assert set(report_to_json(report)) == {"next_id", "tasks", "errors", "anomalies"}


def test_report_to_json_normal_entry_full_key_set() -> None:
    entry = NormalTaskReportEntry(
        id="sh-002",
        title="A title",
        path="tasks/active/sh-002-a-title.md",
        current_phase="implementation",
        current_agent="implementer",
        review_rejections=1,
        blocked_by=["sh-001"],
        unmet_blockers=["sh-001"],
        blocked=True,
        in_progress=True,
        branch_exists=True,
        source="branch:sh-002",
    )
    report = Report(
        next_id="sh-003",
        tasks=[entry],
        errors=[],
        anomalies=[Anomaly(id="sh-002", reason="done_in_active")],
    )
    json_report = report_to_json(report)
    assert json_report["next_id"] == "sh-003"
    assert json_report["tasks"] == [
        {
            "id": "sh-002",
            "title": "A title",
            "path": "tasks/active/sh-002-a-title.md",
            "current_phase": "implementation",
            "current_agent": "implementer",
            "review_rejections": 1,
            "blocked_by": ["sh-001"],
            "unmet_blockers": ["sh-001"],
            "blocked": True,
            "in_progress": True,
            "branch_exists": True,
            "source": "branch:sh-002",
        }
    ]
    assert json_report["errors"] == []
    assert json_report["anomalies"] == [{"id": "sh-002", "reason": "done_in_active"}]


def test_report_to_json_error_entry_is_id_and_error_only() -> None:
    entry = ErrorTaskReportEntry(id="sh-004", error="malformed frontmatter YAML")
    report = Report(next_id="sh-005", tasks=[entry], errors=["sh-004"], anomalies=[])
    json_report = report_to_json(report)
    assert json_report["tasks"] == [
        {"id": "sh-004", "error": "malformed frontmatter YAML"}
    ]
    assert set(json_report["tasks"][0]) == {"id", "error"}
    assert json_report["errors"] == ["sh-004"]


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def test_main_default_prints_parseable_json_and_returns_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])
    assert exit_code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert set(parsed) == {"next_id", "tasks", "errors", "anomalies"}


def test_main_human_prints_markdown_and_returns_0(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main(["--human"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert out.startswith("Next id: sh-")
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_cli_entrypoint_prints_json_and_exits_0() -> None:
    result = subprocess.run(
        [sys.executable, str(HELPER)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert set(parsed) == {"next_id", "tasks", "errors", "anomalies"}
