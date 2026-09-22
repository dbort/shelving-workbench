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

import re
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field

import yaml


class TaskParseError(Exception):
    """A task file's frontmatter failed to parse or validate."""


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
