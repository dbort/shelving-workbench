"""Coverage of ``tools/task_status.py``, the tasks/ pipeline status report.

The pure core (frontmatter parsing, id allocation, blocker resolution, and
the layered topological sort) is exercised here against synthetic strings
and mappings with no filesystem or git involved; the git/filesystem layer
built on top of it is exercised separately, against a throwaway temporary
git repository this module's own fixtures create.
"""

from __future__ import annotations

from tools.task_status import (
    TaskFrontmatter,
    TaskParseError,
    compute_next_id,
    layered_topological_order,
    parse_frontmatter,
    resolve_blocking,
)

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
