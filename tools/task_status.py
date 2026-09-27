"""task_status: the `tasks/active/` backlog in dependency order, and the next free id.

Status is derived from where a task file lives, whether its `sh-XXX` branch
exists, and the last `## Review log` round on that branch
(`.claude/docs/pipeline.md` § Status). The tool only reads the repository.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import yaml


class TaskParseError(Exception):
    """A task file's frontmatter is missing or malformed."""


@dataclass(frozen=True)
class Frontmatter:
    """The frontmatter fields the pipeline reads; other keys are ignored."""

    id: str
    title: str
    blocked_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskEntry:
    """One active task's derived status."""

    id: str
    title: str
    path: str
    status: str
    # Blockers not yet in the working tree's tasks/completed/.
    unmet_blockers: tuple[str, ...]


_FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_ROUND_RE = re.compile(r"^### Round (\d+): (APPROVED|REJECTED)\s*$", re.MULTILINE)
_ID_RE = re.compile(r"^sh-(\d+)$")
_PATH_ID_RE = re.compile(r"(?:^|/)(sh-\d+)-[^/]+\.md$")
_TASK_SUBDIRS = ("active", "completed", "abandoned")


def parse_frontmatter(text: str) -> Frontmatter:
    """The task's frontmatter; raises `TaskParseError` if `id` or `title` is absent."""
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise TaskParseError("no leading --- frontmatter block")
    loaded: object = yaml.safe_load(match.group(1))
    if not isinstance(loaded, dict):
        raise TaskParseError("frontmatter is not a mapping")
    task_id, title, blocked_by = (
        loaded.get("id"),
        loaded.get("title"),
        loaded.get("blocked_by", []),
    )
    if not isinstance(task_id, str) or not isinstance(title, str):
        raise TaskParseError("frontmatter needs string `id` and `title`")
    if not isinstance(blocked_by, list) or not all(
        isinstance(b, str) for b in blocked_by
    ):
        raise TaskParseError("`blocked_by` must be a list of task ids")
    return Frontmatter(task_id, title, tuple(blocked_by))


def last_review_round(text: str) -> tuple[int, str] | None:
    """`(round, verdict)` of the last `### Round N: VERDICT` heading, if any."""
    rounds = _ROUND_RE.findall(text)
    if not rounds:
        return None
    number, verdict = rounds[-1]
    return int(number), verdict


def derive_status(branch_exists: bool, task_text_on_branch: str | None) -> str:
    """The pipeline status label for an active task (`pipeline.md` § Status)."""
    if not branch_exists:
        return "planned"
    last = last_review_round(task_text_on_branch or "")
    if last is None:
        return "in progress"
    number, verdict = last
    if verdict == "APPROVED":
        return "awaiting /ship"
    return f"in progress, round {number} rejected"


def compute_next_id(existing_ids: Sequence[str]) -> str:
    """One past the highest `sh-NNN` id at its zero-padded width; `sh-001` if none."""
    parsed = [
        (int(m.group(1)), len(m.group(1)))
        for i in existing_ids
        if (m := _ID_RE.match(i))
    ]
    if not parsed:
        return "sh-001"
    value, width = max(parsed)
    return f"sh-{value + 1:0{width}d}"


def layered_topological_order(
    blocked_by_by_id: Mapping[str, Sequence[str]],
) -> tuple[list[list[str]], list[str]]:
    """`(layers, cyclic_ids)`: each layer's blockers all sit in earlier layers.

    Blockers outside `blocked_by_by_id`'s keys are ignored. Layers and
    `cyclic_ids` are sorted by id.
    """
    remaining = {
        k: {b for b in v if b in blocked_by_by_id} for k, v in blocked_by_by_id.items()
    }
    layers: list[list[str]] = []
    while ready := sorted(k for k, blockers in remaining.items() if not blockers):
        layers.append(ready)
        for task_id in ready:
            del remaining[task_id]
        for blockers in remaining.values():
            blockers.difference_update(ready)
    return layers, sorted(remaining)


def _git(repo_root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout if result.returncode == 0 else None


def _ids_in(paths: Sequence[str]) -> set[str]:
    return {m.group(1) for p in paths if (m := _PATH_ID_RE.search(p))}


def all_task_ids(repo_root: Path) -> set[str]:
    """Every task id in the working tree's or any local branch's `tasks/*/`."""
    ids = _ids_in(
        [str(p) for d in _TASK_SUBDIRS for p in (repo_root / "tasks" / d).glob("*.md")]
    )
    for branch in (
        _git(repo_root, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
        or ""
    ).split():
        listing = _git(
            repo_root, "ls-tree", "-r", "--name-only", branch, "--", "tasks/"
        )
        ids |= _ids_in((listing or "").splitlines())
    return ids


def _task_text_on_branch(repo_root: Path, branch: str, filename: str) -> str | None:
    for subdir in ("active", "completed"):
        text = _git(repo_root, "show", f"{branch}:tasks/{subdir}/{filename}")
        if text is not None:
            return text
    return None


def build_backlog(repo_root: Path) -> tuple[list[TaskEntry], list[str]]:
    """`(entries, errors)`: active tasks in dependency order, and unreadable files.

    Tasks in a `blocked_by` cycle come last.
    """
    completed = _ids_in(
        [p.name for p in (repo_root / "tasks" / "completed").glob("*.md")]
    )
    tasks: dict[str, tuple[Frontmatter, Path]] = {}
    errors: list[str] = []
    for path in sorted((repo_root / "tasks" / "active").glob("sh-*.md")):
        try:
            fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        except TaskParseError as exc:
            errors.append(f"{path.relative_to(repo_root)}: {exc}")
            continue
        tasks[fm.id] = (fm, path)

    layers, cyclic = layered_topological_order(
        {k: fm.blocked_by for k, (fm, _) in tasks.items()}
    )
    entries: list[TaskEntry] = []
    for task_id in [i for layer in layers for i in layer] + cyclic:
        fm, path = tasks[task_id]
        branch_exists = (
            _git(repo_root, "rev-parse", "--verify", "--quiet", f"refs/heads/{task_id}")
            is not None
        )
        text = (
            _task_text_on_branch(repo_root, task_id, path.name)
            if branch_exists
            else None
        )
        entries.append(
            TaskEntry(
                id=task_id,
                title=fm.title,
                path=str(path.relative_to(repo_root)),
                status=derive_status(branch_exists, text),
                unmet_blockers=tuple(b for b in fm.blocked_by if b not in completed),
            )
        )
    return entries, errors


def render(entries: Sequence[TaskEntry], errors: Sequence[str], next_id: str) -> str:
    """The backlog as Markdown, one bullet per task in dependency order."""
    lines = [f"Next id: {next_id}", ""]
    for e in entries:
        blocked = (
            f"; blocked by {', '.join(e.unmet_blockers)}" if e.unmet_blockers else ""
        )
        lines.append(f"- {e.id} [{e.status}{blocked}]: {e.title} (`{e.path}`)")
    lines += [f"- unreadable: {err}" for err in errors]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None, repo_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--next-id", action="store_true", help="print only the next free task id"
    )
    args = parser.parse_args(argv)
    repo_root = repo_root or Path(__file__).resolve().parent.parent
    next_id = compute_next_id(sorted(all_task_ids(repo_root)))
    if args.next_id:
        print(next_id)
        return 0
    entries, errors = build_backlog(repo_root)
    print(render(entries, errors, next_id))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
