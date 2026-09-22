"""task_status: a deterministic report of `tasks/active/`'s pipeline state.

Every skill that touches `tasks/active/*.md` (`dispatch-tasks`, `approve-task`,
`new-task`) re-derives the same facts by hand: which tasks are unblocked,
which are mid-pipeline and whether their branch exists yet, and the next free
`sh-XXX` id. This module computes all three once, deterministically, so a
skill or a human can call `pixi run task-status` instead of re-deriving
pipeline state with ad hoc `git`/`grep`/`ls` commands.

This is a reporting tool only: it never writes a task file, creates a
branch, or otherwise changes repository state (`.claude/docs/pipeline.md` §
Phase transitions reserves that to `new-task`/`dispatch-tasks`/
`approve-task`).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

import yaml


class TaskParseError(Exception):
    """A task file's frontmatter failed to parse or validate."""


class TaskStatusError(Exception):
    """The tool itself could not produce a report (not a single task's error).

    Reserved for `tasks/active/` not existing or `git` not being on `PATH`;
    a malformed or anomalous individual task never raises this (Frontier
    Advice: anomalies and errors are data, not failures).
    """


@dataclass(frozen=True)
class TaskFrontmatter:
    """The validated, flat frontmatter of one `tasks/*/sh-XXX-*.md` file."""

    id: str
    title: str
    current_agent: str
    current_phase: str
    review_rejections: int
    blocked_by: list[str] = field(default_factory=list)


_REQUIRED_FRONTMATTER_KEYS = frozenset(
    {"id", "title", "current_agent", "current_phase", "review_rejections"}
)
_OPTIONAL_FRONTMATTER_KEYS = frozenset({"blocked_by"})
_ALL_FRONTMATTER_KEYS = _REQUIRED_FRONTMATTER_KEYS | _OPTIONAL_FRONTMATTER_KEYS

_FRONTMATTER_DELIMITER = "---"


def _extract_frontmatter_block(text: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIMITER:
        raise TaskParseError(
            "task file does not open with a '---' frontmatter delimiter"
        )
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_DELIMITER:
            return "\n".join(lines[1:index])
    raise TaskParseError("task file's frontmatter block is never closed with '---'")


def _as_mapping(loaded: object) -> dict[str, object]:
    """Narrow a `yaml.safe_load` result into a flat `str`-keyed mapping.

    Every real task file's frontmatter is exactly a flat mapping (see
    `tools/task_status.py` module docstring context in the task's Frontier
    Advice); anything else (a list, a scalar, a non-string key) is a parse
    error rather than something later code tries to interpret.
    """
    if not isinstance(loaded, dict):
        raise TaskParseError("frontmatter is not a flat mapping")
    result: dict[str, object] = {}
    for key, value in loaded.items():
        if not isinstance(key, str):
            raise TaskParseError(f"frontmatter has a non-string key: {key!r}")
        result[key] = value
    return result


def _expect_str(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TaskParseError(f"frontmatter field {field_name!r} is not a string")
    return value


def _expect_int(value: object, field_name: str) -> int:
    # bool is an int subclass; a YAML `true`/`false` here is a type error,
    # not a 1/0 review_rejections count.
    if not isinstance(value, int) or isinstance(value, bool):
        raise TaskParseError(f"frontmatter field {field_name!r} is not an integer")
    return value


def _expect_str_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise TaskParseError(f"frontmatter field {field_name!r} is not a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise TaskParseError(
                f"frontmatter field {field_name!r} contains a non-string entry"
            )
        result.append(item)
    return result


def parse_frontmatter(text: str) -> TaskFrontmatter:
    """Parse and validate one task file's `---`-delimited frontmatter block.

    Raises `TaskParseError` on malformed YAML, a non-flat-mapping shape, an
    unexpected or missing key, or a field whose value has the wrong type.
    Does not know the file's own path, so it cannot check the frontmatter
    `id` against a `sh-XXX` filename; that is the caller's job.
    """
    block = _extract_frontmatter_block(text)
    try:
        loaded: object = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise TaskParseError(f"malformed frontmatter YAML: {exc}") from exc

    fields = _as_mapping(loaded)
    present_keys = set(fields)
    extra_keys = present_keys - _ALL_FRONTMATTER_KEYS
    missing_keys = _REQUIRED_FRONTMATTER_KEYS - present_keys
    if extra_keys or missing_keys:
        raise TaskParseError(
            "frontmatter keys do not match the expected shape "
            f"(extra={sorted(extra_keys)}, missing={sorted(missing_keys)})"
        )

    return TaskFrontmatter(
        id=_expect_str(fields["id"], "id"),
        title=_expect_str(fields["title"], "title"),
        current_agent=_expect_str(fields["current_agent"], "current_agent"),
        current_phase=_expect_str(fields["current_phase"], "current_phase"),
        review_rejections=_expect_int(fields["review_rejections"], "review_rejections"),
        blocked_by=_expect_str_list(fields.get("blocked_by", []), "blocked_by"),
    )


_ID_NUMERAL_RE = re.compile(r"^sh-(\d+)$")


def compute_next_id(existing_ids: Sequence[str]) -> str:
    """The next unused `sh-NNN` id, one past the highest id in `existing_ids`.

    Zero-padded to match the numeral width of the id it increments from
    (`new-task`'s Task ID Allocation algorithm, `.claude/skills/new-task/
    SKILL.md`), widening automatically rather than truncating when
    incrementing overflows that width (`sh-999` -> `sh-1000`). Non-`sh-NNN`
    entries in `existing_ids` are ignored; an input with no `sh-NNN` entries
    at all yields `sh-001`.
    """
    parsed: list[tuple[int, int]] = []
    for raw in existing_ids:
        match = _ID_NUMERAL_RE.match(raw)
        if match is not None:
            numeral = match.group(1)
            parsed.append((int(numeral), len(numeral)))
    if not parsed:
        return "sh-001"
    max_value, matched_width = max(parsed, key=lambda item: item[0])
    next_value = max_value + 1
    width = max(matched_width, len(str(next_value)))
    return f"sh-{next_value:0{width}d}"


def resolve_blocking(
    blocked_by: Sequence[str], completed_ids: AbstractSet[str]
) -> tuple[list[str], bool]:
    """`(unmet_blockers, blocked)` for one task's `blocked_by` list.

    `unmet_blockers` preserves `blocked_by`'s order, keeping only ids not in
    `completed_ids`; `blocked` is whether that list is non-empty.
    """
    unmet_blockers = [task_id for task_id in blocked_by if task_id not in completed_ids]
    return unmet_blockers, bool(unmet_blockers)


def layered_topological_order(
    blocked_by_by_id: Mapping[str, Sequence[str]],
) -> tuple[list[list[str]], list[str]]:
    """Kahn's algorithm, layered, over `blocked_by_by_id`'s DAG.

    Returns `(layers, cyclic_ids)`. Each layer is every id whose remaining
    unresolved blockers (restricted to ids that are themselves keys of
    `blocked_by_by_id` — a blocker outside that set contributes no edge) are
    all in a prior layer, sorted by id; completing the layers in order
    resolves every blocker before the id it blocks is reached. `cyclic_ids`
    (sorted by id) lists every id that never reaches zero remaining
    blockers because it sits in a `blocked_by` cycle.
    """
    active_ids = set(blocked_by_by_id)
    in_degree: dict[str, int] = {}
    dependents: dict[str, list[str]] = {task_id: [] for task_id in active_ids}
    for task_id, blockers in blocked_by_by_id.items():
        relevant_blockers = [b for b in blockers if b in active_ids]
        in_degree[task_id] = len(relevant_blockers)
        for blocker in relevant_blockers:
            dependents[blocker].append(task_id)

    remaining = set(active_ids)
    layers: list[list[str]] = []
    while True:
        ready = sorted(task_id for task_id in remaining if in_degree[task_id] == 0)
        if not ready:
            break
        layers.append(ready)
        for task_id in ready:
            remaining.discard(task_id)
            for dependent in dependents[task_id]:
                if dependent in remaining:
                    in_degree[dependent] -= 1

    return layers, sorted(remaining)


# ---------------------------------------------------------------------------
# The git/filesystem layer.
# ---------------------------------------------------------------------------

_PATH_ID_RE = re.compile(r"(?:^|/)(sh-\d+)-[^/]+\.md$")

_TASK_SUBDIRS = ("active", "completed", "abandoned")


def _task_id_from_path(path: str) -> str | None:
    """The `sh-NNN` id a `tasks/*/sh-NNN-slug.md`-shaped path names, if any."""
    match = _PATH_ID_RE.search(path)
    return match.group(1) if match is not None else None


def _run_git(repo_root: Path, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise TaskStatusError("git is not available on PATH") from exc


def local_branch_exists(repo_root: Path, branch: str) -> bool:
    """Whether a local branch named exactly `branch` exists."""
    result = _run_git(
        repo_root, ["rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"]
    )
    return result.returncode == 0


def list_local_branches(repo_root: Path) -> list[str]:
    """Every local branch name, in `git for-each-ref`'s own order."""
    result = _run_git(
        repo_root, ["for-each-ref", "--format=%(refname:short)", "refs/heads/"]
    )
    if result.returncode != 0:
        raise TaskStatusError(f"git for-each-ref failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line]


def branch_task_ids(repo_root: Path, branch: str) -> list[str]:
    """Every task id present under `tasks/*/` at `branch`'s own tip.

    Reads the tree at the branch's tip directly (`git ls-tree`), never
    checking it out, so this is safe to call for a branch other than the
    one currently checked out.
    """
    result = _run_git(
        repo_root,
        [
            "ls-tree",
            "-r",
            "--name-only",
            branch,
            "--",
            *(f"tasks/{subdir}/" for subdir in _TASK_SUBDIRS),
        ],
    )
    if result.returncode != 0:
        raise TaskStatusError(
            f"git ls-tree failed for branch {branch!r}: {result.stderr.strip()}"
        )
    ids: list[str] = []
    for line in result.stdout.splitlines():
        task_id = _task_id_from_path(line)
        if task_id is not None:
            ids.append(task_id)
    return ids


def working_tree_task_ids(
    repo_root: Path, subdirs: Sequence[str] = _TASK_SUBDIRS
) -> list[str]:
    """Every task id present under the given `tasks/*/` subdirectories on disk.

    Globs the working directory directly rather than `git ls-files`, so an
    uncommitted new task file is still counted (Frontier Advice: multi-branch
    `next_id` scanning).
    """
    ids: list[str] = []
    for subdir in subdirs:
        for entry in sorted((repo_root / "tasks" / subdir).glob("*.md")):
            task_id = _task_id_from_path(entry.name)
            if task_id is not None:
                ids.append(task_id)
    return ids


def gather_next_id_input(repo_root: Path) -> list[str]:
    """The union of every task id `compute_next_id` must consider.

    Unions the working directory's own `tasks/*/` listing (including
    anything uncommitted) with, for every local branch, that same listing as
    it exists at that branch's own tip — so a task created on one branch, or
    accumulated on `main` while another branch was checked out, can't
    collide with an id this tool hands out from a different, stale-relative-
    to-it branch.
    """
    ids = set(working_tree_task_ids(repo_root))
    for branch in list_local_branches(repo_root):
        ids.update(branch_task_ids(repo_root, branch))
    return sorted(ids)


def working_tree_completed_ids(repo_root: Path) -> set[str]:
    """Task ids present in the working directory's own `tasks/completed/`.

    This, not the multi-branch union `gather_next_id_input` computes, is
    what `blocked_by` resolution is checked against (`dispatch-tasks`'s own
    Step 1 logic).
    """
    return set(working_tree_task_ids(repo_root, subdirs=("completed",)))


def _find_branch_path(
    repo_root: Path, branch: str, subdir: str, task_id: str
) -> str | None:
    """The exact `tasks/<subdir>/<task_id>-*.md` path at `branch`'s tip, if any."""
    result = _run_git(
        repo_root, ["ls-tree", "-r", "--name-only", branch, "--", f"tasks/{subdir}/"]
    )
    if result.returncode != 0:
        return None
    prefix = f"tasks/{subdir}/{task_id}-"
    for line in result.stdout.splitlines():
        if line.startswith(prefix) and line.endswith(".md"):
            return line
    return None


def read_authoritative_task_text(
    repo_root: Path, task_id: str, working_tree_path: Path
) -> tuple[str, str]:
    """`(text, source)` for `task_id`'s authoritative frontmatter/body text.

    `source` is `"working_tree"` when no local branch named exactly
    `task_id` exists (the task hasn't reached `implementation` yet, so
    nothing has branched off `main`), or `"branch:<task_id>"` when the
    text was read from that branch's own tip instead, since a branch's
    phase-transition commits never land on the working tree's checked-out
    branch (`.claude/docs/pipeline.md` § Git branching). On a branch, tries
    `tasks/active/` first, then `tasks/completed/` (a task whose
    `approve-task` run finished finalizing but hasn't merged yet). Raises
    `TaskParseError` if the branch exists but neither location has the file
    at its tip.
    """
    if not local_branch_exists(repo_root, task_id):
        return working_tree_path.read_text(encoding="utf-8"), "working_tree"
    for subdir in ("active", "completed"):
        path = _find_branch_path(repo_root, task_id, subdir, task_id)
        if path is None:
            continue
        result = _run_git(repo_root, ["show", f"{task_id}:{path}"])
        if result.returncode == 0:
            return result.stdout, f"branch:{task_id}"
    raise TaskParseError(
        f"branch {task_id} exists but neither tasks/active/ nor tasks/completed/ "
        f"has a {task_id}-*.md file at its tip"
    )


@dataclass(frozen=True)
class NormalTaskReportEntry:
    """One `tasks/active/` entry whose frontmatter parsed and validated cleanly."""

    id: str
    title: str
    path: str
    current_phase: str
    current_agent: str
    review_rejections: int
    blocked_by: list[str]
    unmet_blockers: list[str]
    blocked: bool
    in_progress: bool
    branch_exists: bool
    source: str


@dataclass(frozen=True)
class ErrorTaskReportEntry:
    """One `tasks/active/` entry whose frontmatter failed to parse or validate."""

    id: str
    error: str


TaskReportEntry = NormalTaskReportEntry | ErrorTaskReportEntry

AnomalyReason = Literal["done_in_active", "circular_blocked_by"]


@dataclass(frozen=True)
class Anomaly:
    id: str
    reason: AnomalyReason


@dataclass(frozen=True)
class Report:
    next_id: str
    tasks: list[TaskReportEntry]
    errors: list[str]
    anomalies: list[Anomaly]


def build_report(repo_root: Path) -> Report:
    """Assemble the full `tasks/active/` status report for `repo_root`.

    Iterates `tasks/active/`'s working-directory listing in `ls` order
    (never `tasks/completed/`/`tasks/abandoned/` themselves, which are
    consulted only to resolve `unmet_blockers` and `next_id`); a task whose
    frontmatter fails to parse or whose id disagrees with its filename
    becomes an `ErrorTaskReportEntry` instead of aborting the whole report.
    Raises `TaskStatusError` only when the report itself cannot be produced
    (`tasks/active/` missing, `git` unavailable), never for a single
    anomalous or malformed task.
    """
    active_dir = repo_root / "tasks" / "active"
    if not active_dir.is_dir():
        raise TaskStatusError(f"{active_dir} does not exist")

    next_id = compute_next_id(gather_next_id_input(repo_root))
    completed_ids = working_tree_completed_ids(repo_root)

    entries: list[TaskReportEntry] = []
    errors: list[str] = []
    anomalies: list[Anomaly] = []
    blocked_by_by_id: dict[str, list[str]] = {}

    for task_path in sorted(active_dir.glob("*.md")):
        expected_id = _task_id_from_path(task_path.name) or task_path.stem
        try:
            if _task_id_from_path(task_path.name) is None:
                raise TaskParseError(
                    f"{task_path.name!r} is not a sh-NNN-slug.md task filename"
                )
            text, source = read_authoritative_task_text(
                repo_root, expected_id, task_path
            )
            parsed = parse_frontmatter(text)
            if parsed.id != expected_id:
                raise TaskParseError(
                    f"frontmatter id {parsed.id!r} does not match "
                    f"filename-derived id {expected_id!r}"
                )
        except TaskParseError as exc:
            entries.append(ErrorTaskReportEntry(id=expected_id, error=str(exc)))
            errors.append(expected_id)
            blocked_by_by_id[expected_id] = []
            continue

        unmet_blockers, blocked = resolve_blocking(parsed.blocked_by, completed_ids)
        entry = NormalTaskReportEntry(
            id=expected_id,
            title=parsed.title,
            path=task_path.relative_to(repo_root).as_posix(),
            current_phase=parsed.current_phase,
            current_agent=parsed.current_agent,
            review_rejections=parsed.review_rejections,
            blocked_by=list(parsed.blocked_by),
            unmet_blockers=unmet_blockers,
            blocked=blocked,
            in_progress=parsed.current_phase != "planning",
            branch_exists=local_branch_exists(repo_root, expected_id),
            source=source,
        )
        entries.append(entry)
        blocked_by_by_id[expected_id] = list(parsed.blocked_by)
        if parsed.current_phase == "done":
            anomalies.append(Anomaly(id=expected_id, reason="done_in_active"))

    _, cyclic_ids = layered_topological_order(blocked_by_by_id)
    for cyclic_id in cyclic_ids:
        anomalies.append(Anomaly(id=cyclic_id, reason="circular_blocked_by"))

    return Report(next_id=next_id, tasks=entries, errors=errors, anomalies=anomalies)


# ---------------------------------------------------------------------------
# JSON output shape and the CLI entry point.
# ---------------------------------------------------------------------------


class JsonNormalTaskEntry(TypedDict):
    id: str
    title: str
    path: str
    current_phase: str
    current_agent: str
    review_rejections: int
    blocked_by: list[str]
    unmet_blockers: list[str]
    blocked: bool
    in_progress: bool
    branch_exists: bool
    source: str


class JsonErrorTaskEntry(TypedDict):
    id: str
    error: str


JsonTaskEntry = JsonNormalTaskEntry | JsonErrorTaskEntry


class JsonAnomaly(TypedDict):
    id: str
    reason: AnomalyReason


class JsonReport(TypedDict):
    next_id: str
    tasks: list[JsonTaskEntry]
    errors: list[str]
    anomalies: list[JsonAnomaly]


def _entry_to_json(entry: TaskReportEntry) -> JsonTaskEntry:
    if isinstance(entry, ErrorTaskReportEntry):
        return {"id": entry.id, "error": entry.error}
    return {
        "id": entry.id,
        "title": entry.title,
        "path": entry.path,
        "current_phase": entry.current_phase,
        "current_agent": entry.current_agent,
        "review_rejections": entry.review_rejections,
        "blocked_by": list(entry.blocked_by),
        "unmet_blockers": list(entry.unmet_blockers),
        "blocked": entry.blocked,
        "in_progress": entry.in_progress,
        "branch_exists": entry.branch_exists,
        "source": entry.source,
    }


def report_to_json(report: Report) -> JsonReport:
    """The exact on-the-wire shape `main()` serializes with `json.dumps`."""
    return {
        "next_id": report.next_id,
        "tasks": [_entry_to_json(entry) for entry in report.tasks],
        "errors": list(report.errors),
        "anomalies": [{"id": a.id, "reason": a.reason} for a in report.anomalies],
    }


def _render_task_bullet(entry: TaskReportEntry) -> list[str]:
    if isinstance(entry, ErrorTaskReportEntry):
        return [f"- {entry.id}: ERROR: {entry.error}"]
    lines = [f"- {entry.id}: {entry.title}", f"  - path: {entry.path}"]
    if entry.branch_exists:
        lines.append(f"  - branch: {entry.id}")
    lines.append(f"  - phase: {entry.current_phase}")
    blocked_by_text = (
        ", ".join(entry.unmet_blockers) if entry.unmet_blockers else "(none)"
    )
    lines.append(f"  - blocked by: {blocked_by_text}")
    return lines


def render_human_report(report: Report) -> str:
    """A Markdown summary of `report`: next id, then one nested bullet per task.

    Tasks are ordered by a layered topological sort over the `blocked_by`
    DAG restricted to edges between two tasks both in `report.tasks`
    (`layered_topological_order`); a task caught in a `circular_blocked_by`
    cycle is appended last, sorted by id. An `ErrorTaskReportEntry` is
    treated as having no blockers for ordering purposes (its real
    `blocked_by` failed to parse) and renders as a single error line instead
    of the normal nested-bullet fields.
    """
    entry_by_id = {entry.id: entry for entry in report.tasks}
    blocked_by_by_id = {
        entry.id: list(entry.blocked_by)
        if isinstance(entry, NormalTaskReportEntry)
        else []
        for entry in report.tasks
    }
    layers, cyclic_ids = layered_topological_order(blocked_by_by_id)
    ordered_ids = [task_id for layer in layers for task_id in layer] + cyclic_ids

    lines = [f"Next id: {report.next_id}", ""]
    for task_id in ordered_ids:
        lines.extend(_render_task_bullet(entry_by_id[task_id]))
    return "\n".join(lines)


def _repo_root() -> Path:
    # tools/task_status.py -> repo root, same convention as
    # tests/test_check_lock_paths.py's REPO_ROOT.
    return Path(__file__).resolve().parent.parent


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="task_status",
        description="Deterministic report of tasks/active/'s pipeline state.",
    )
    # -h/--help is argparse's own; -H is this tool's short form for --human.
    parser.add_argument(
        "-H",
        "--human",
        action="store_true",
        help="print a Markdown summary instead of JSON",
    )
    args = parser.parse_args(argv)

    try:
        report = build_report(_repo_root())
    except TaskStatusError as exc:
        print(f"task_status: {exc}", file=sys.stderr)
        return 1

    if args.human:
        print(render_human_report(report))
    else:
        print(json.dumps(report_to_json(report), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
