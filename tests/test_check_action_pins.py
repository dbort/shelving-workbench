"""Unit coverage of ``tools/check_action_pins.py``.

The module is built from small, injectable pieces so its behaviour can be
pinned without a network round-trip or a mock HTTP server: ``resolve_commit``
and ``main`` take a ``fetch`` callable, ``offline_mode`` reads one environment
variable, and ``classify_status`` / ``auth_headers`` are pure. ``pixi run tests``
still makes the live GitHub call on a networked host; these tests never touch the
network and finish in well under a second.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path

import pytest

from tools.check_action_pins import (
    FetchResult,
    MalformedPin,
    OfflineConfigError,
    Pin,
    ResolveError,
    auth_headers,
    classify_status,
    main,
    malformed_version_comments,
    offline_mode,
    resolve_commit,
    workflow_pins,
)

WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"

SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the variables the module reads so ``--offline`` cannot leak in.

    ``pixi run tests -- --offline`` exports ``SHELVING_OFFLINE=1`` into the
    pytest process; a token may sit in the ambient environment too. Every case
    that wants one sets it explicitly.
    """
    for name in ("SHELVING_OFFLINE", "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_API_URL"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- #
# workflow_pins
# --------------------------------------------------------------------------- #


def test_workflow_pins_parses_both_extensions_and_strips_path_segments(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{SHA_A} # v4.2.2\n"
        f"      - uses: github/codeql-action/upload-sarif@{SHA_B} # v3.28.1\n"
        "      - uses: actions/setup-python@v5\n"
        "      - name: not a uses line\n",
        encoding="utf-8",
    )
    (workflows / "release.yaml").write_text(
        f"      - uses: step-security/harden-runner@{SHA_C} # v2.10.4\n",
        encoding="utf-8",
    )

    pins = workflow_pins(workflows)

    assert isinstance(pins, tuple)
    # `file` carries the workflow path, not the bare basename, so a failure
    # line points at the file to edit.
    assert pins == (
        Pin("actions/checkout", "v4.2.2", SHA_A, ".github/workflows/ci.yml"),
        Pin("github/codeql-action", "v3.28.1", SHA_B, ".github/workflows/ci.yml"),
        Pin(
            "step-security/harden-runner",
            "v2.10.4",
            SHA_C,
            ".github/workflows/release.yaml",
        ),
    )


def test_workflow_pins_ignores_unpinned_and_mis_commented_lines(tmp_path: Path) -> None:
    (tmp_path / "wf.yml").write_text(
        f"      - uses: actions/checkout@{SHA_A}  # pinned but no version\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: echo uses: not/a@pin\n",
        encoding="utf-8",
    )

    assert workflow_pins(tmp_path) == ()


# --------------------------------------------------------------------------- #
# malformed_version_comments
# --------------------------------------------------------------------------- #


def test_malformed_version_comments_flags_only_sha_pins_that_pin_re_rejects(
    tmp_path: Path,
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        f"      - uses: actions/checkout@{SHA_A} # v4.2.2\n"  # fine
        f"      - uses: actions/setup-python@{SHA_B}\n"  # no comment
        f"      - uses: actions/cache@{SHA_C}  # pinned, no version\n"  # malformed
        f"      - uses: actions/lint@{SHA_A.upper()} # v1.0.0\n"  # upper-case SHA
        "      - uses: actions/upload-artifact@v4\n"  # tag pin: zizmor's job
        "      - uses: ./.github/actions/local\n"
        "      - run: echo uses: not/a@pin\n",
        encoding="utf-8",
    )

    assert malformed_version_comments(workflows) == (
        MalformedPin(".github/workflows/ci.yml", f"uses: actions/setup-python@{SHA_B}"),
        MalformedPin(
            ".github/workflows/ci.yml",
            f"uses: actions/cache@{SHA_C}  # pinned, no version",
        ),
        MalformedPin(
            ".github/workflows/ci.yml", f"uses: actions/lint@{SHA_A.upper()} # v1.0.0"
        ),
    )


def test_malformed_version_comments_clean_for_the_repo_workflows() -> None:
    assert malformed_version_comments(WORKFLOW_DIR) == ()


def test_main_fails_before_any_fetch_on_a_malformed_version_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        f"      - uses: actions/checkout@{SHA_A} # not a version\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("tools.check_action_pins._WORKFLOW_DIR", workflows)

    # `_exploding_fetch` raises if called, so a pass here proves the check
    # fails before any network call.
    assert main([], fetch=_exploding_fetch, retry_sleep=0.0) == 1

    captured = capsys.readouterr()
    assert "verified" not in captured.out
    assert "# vX.Y.Z" in captured.err
    assert ".github/workflows/ci.yml" in captured.err


def test_main_fails_a_malformed_comment_even_when_offline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHELVING_OFFLINE", "1")
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        f"      - uses: actions/checkout@{SHA_A} # not a version\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("tools.check_action_pins._WORKFLOW_DIR", workflows)

    # The comment check sits ahead of the SHELVING_OFFLINE guard, so a bad
    # comment is fatal rather than skipped.
    assert main([], fetch=_exploding_fetch, retry_sleep=0.0) == 1

    captured = capsys.readouterr()
    assert "skipped (SHELVING_OFFLINE)" not in captured.err
    assert "# vX.Y.Z" in captured.err


# --------------------------------------------------------------------------- #
# classify_status
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("status", "needle"),
    [
        (0, "connection failed"),
        (403, "rate limited"),
        (429, "rate limited"),
        (404, "tag not found"),
        (500, "server error"),
        (503, "server error"),
        (418, "unexpected HTTP 418"),
    ],
)
def test_classify_status_returns_a_reason_for_every_failure_class(
    status: int, needle: str
) -> None:
    reason = classify_status(status, "https://api.example", "owner/repo@v1.0.0")
    assert reason is not None
    assert needle in reason
    assert "owner/repo@v1.0.0" in reason


def test_classify_status_200_is_the_verified_path() -> None:
    assert classify_status(200, "https://api.example", "owner/repo@v1.0.0") is None


def test_classify_status_connection_failure_names_the_api_base() -> None:
    # The base is the one detail that matters when GITHUB_API_URL is overridden
    # to an unreachable host.
    reason = classify_status(0, "https://ghe.internal", "owner/repo@v1.0.0")
    assert reason is not None
    assert "https://ghe.internal" in reason


def test_classify_status_rate_limit_names_the_token_fix() -> None:
    reason = classify_status(403, "https://api.example", "owner/repo@v1.0.0")
    assert reason is not None
    assert "GH_TOKEN" in reason
    assert "GITHUB_TOKEN" in reason


# --------------------------------------------------------------------------- #
# resolve_commit
# --------------------------------------------------------------------------- #


def test_resolve_commit_reads_a_lightweight_tag_directly() -> None:
    calls: list[str] = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        return FetchResult(200, {"object": {"type": "commit", "sha": SHA_A}})

    assert resolve_commit(fetch, "https://api", "actions/checkout", "v4.2.2") == SHA_A
    assert calls == ["https://api/repos/actions/checkout/git/ref/tags/v4.2.2"]


def test_resolve_commit_follows_an_annotated_tag_to_its_commit() -> None:
    calls: list[str] = []

    def fetch(url: str) -> FetchResult:
        calls.append(url)
        if "/git/ref/tags/" in url:
            return FetchResult(200, {"object": {"type": "tag", "sha": "TAGOBJ"}})
        return FetchResult(200, {"object": {"type": "commit", "sha": SHA_B}})

    result = resolve_commit(fetch, "https://api", "ossf/scorecard-action", "v2.4.0")

    assert result == SHA_B
    assert calls == [
        "https://api/repos/ossf/scorecard-action/git/ref/tags/v2.4.0",
        "https://api/repos/ossf/scorecard-action/git/tags/TAGOBJ",
    ]


def test_resolve_commit_turns_a_404_into_a_fatal_reason() -> None:
    def fetch(url: str) -> FetchResult:
        return FetchResult(404, {"message": "Not Found"})

    with pytest.raises(ResolveError) as caught:
        resolve_commit(fetch, "https://api", "actions/checkout", "v9.9.9")
    assert "404" in str(caught.value)


def test_resolve_commit_turns_a_connection_error_into_a_fatal_reason() -> None:
    def fetch(url: str) -> FetchResult:
        raise urllib.error.URLError("connection refused")

    with pytest.raises(ResolveError) as caught:
        resolve_commit(fetch, "https://api", "actions/checkout", "v4.2.2")
    assert "connection failed" in str(caught.value)


def test_resolve_commit_rejects_an_unexpected_payload_shape() -> None:
    def fetch(url: str) -> FetchResult:
        return FetchResult(200, {"unexpected": True})

    with pytest.raises(ResolveError) as caught:
        resolve_commit(fetch, "https://api", "actions/checkout", "v4.2.2")
    assert "unexpected API response" in str(caught.value)


def test_resolve_commit_turns_a_non_json_200_into_a_fatal_reason() -> None:
    # A proxy or captive portal answering 200 with HTML: body is None, and the
    # module classifies it rather than letting a parse error escape.
    def fetch(url: str) -> FetchResult:
        return FetchResult(200, None)

    with pytest.raises(ResolveError) as caught:
        resolve_commit(fetch, "https://api", "actions/checkout", "v4.2.2")
    assert "unparseable response (HTTP 200)" in str(caught.value)


# --------------------------------------------------------------------------- #
# offline_mode  (and the guard's effect inside main)
# --------------------------------------------------------------------------- #


def test_offline_mode_runs_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SHELVING_OFFLINE", raising=False)
    assert offline_mode() is False


def test_offline_mode_runs_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELVING_OFFLINE", "")
    assert offline_mode() is False


def test_offline_mode_skips_when_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SHELVING_OFFLINE", "1")
    assert offline_mode() is True


@pytest.mark.parametrize("value", ["0", "true"])
def test_offline_mode_rejects_any_other_value(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SHELVING_OFFLINE", value)
    with pytest.raises(OfflineConfigError) as caught:
        offline_mode()
    assert "SHELVING_OFFLINE must be unset or 1" in str(caught.value)


def _exploding_fetch(url: str) -> FetchResult:
    raise AssertionError(f"fetch must not be called: {url}")


def test_main_skips_without_fetching_when_offline(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHELVING_OFFLINE", "1")

    assert main([], fetch=_exploding_fetch, retry_sleep=0.0) == 0

    captured = capsys.readouterr()
    assert "check-action-pins: skipped (SHELVING_OFFLINE)" in captured.err


def test_main_errors_without_fetching_on_an_illegal_offline_value(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("SHELVING_OFFLINE", "0")

    assert main([], fetch=_exploding_fetch, retry_sleep=0.0) == 2

    captured = capsys.readouterr()
    assert "SHELVING_OFFLINE must be unset or 1" in captured.err


# --------------------------------------------------------------------------- #
# auth_headers
# --------------------------------------------------------------------------- #


def test_auth_headers_sends_the_bearer_only_to_the_real_github_api() -> None:
    env: Mapping[str, str] = {"GH_TOKEN": "secret"}
    assert auth_headers("https://api.github.com", env) == {
        "Authorization": "Bearer secret"
    }


def test_auth_headers_falls_back_to_github_token() -> None:
    env: Mapping[str, str] = {"GITHUB_TOKEN": "secret"}
    assert auth_headers("https://api.github.com", env) == {
        "Authorization": "Bearer secret"
    }


@pytest.mark.parametrize(
    "base",
    [
        "http://127.0.0.1:8080",
        "https://ghe.example.com",
        "https://api.github.com.evil.com",
        # urlsplit() puts the real host after the `@`; the userinfo prefix must
        # not be mistaken for api.github.com.
        "https://api.github.com@evil/",
    ],
)
def test_auth_headers_withholds_the_bearer_from_any_other_host(base: str) -> None:
    env: Mapping[str, str] = {"GH_TOKEN": "secret", "GITHUB_TOKEN": "secret"}
    assert auth_headers(base, env) == {}


def test_auth_headers_empty_without_a_token() -> None:
    assert auth_headers("https://api.github.com", {}) == {}


# --------------------------------------------------------------------------- #
# main  (end to end against a stub fetch, over the repo's real workflow pins)
# --------------------------------------------------------------------------- #


def _ref_url_repo_and_tag(url: str) -> tuple[str, str]:
    parts = urllib.parse.urlsplit(url).path.strip("/").split("/")
    return f"{parts[1]}/{parts[2]}", parts[6]


def test_main_reports_verified_n_of_n_when_every_pin_matches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {(pin.repo, pin.tag): pin.sha for pin in workflow_pins(WORKFLOW_DIR)}

    def stub(url: str) -> FetchResult:
        repo, tag = _ref_url_repo_and_tag(url)
        commit = expected[(repo, tag)]
        return FetchResult(200, {"object": {"type": "commit", "sha": commit}})

    assert main([], fetch=stub, retry_sleep=0.0) == 0

    # A repo pinned at the same tag in two workflows is two pins but one
    # (repo, tag) key, so count pins, not the lookup table.
    total = len(workflow_pins(WORKFLOW_DIR))
    line = f"check-action-pins: verified {total}/{total} pins"
    assert line in capsys.readouterr().out


def test_main_fails_and_names_every_offender_when_no_pin_matches(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def stub(url: str) -> FetchResult:
        return FetchResult(200, {"object": {"type": "commit", "sha": "f" * 40}})

    assert main([], fetch=stub, retry_sleep=0.0) != 0

    captured = capsys.readouterr()
    assert "verified" not in captured.out
    for pin in workflow_pins(WORKFLOW_DIR):
        assert pin.repo in captured.err, pin
        assert pin.sha in captured.err, pin
        # The failure line carries the workflow path, not the bare basename.
        assert pin.file in captured.err, pin


def test_main_names_the_api_base_when_the_connection_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("GITHUB_API_URL", "https://ghe.invalid")

    def stub(url: str) -> FetchResult:
        raise urllib.error.URLError("no route to host")

    assert main([], fetch=stub, retry_sleep=0.0) != 0

    captured = capsys.readouterr()
    assert "https://ghe.invalid" in captured.err
    assert "connection failed" in captured.err


def test_main_flags_a_non_json_200_without_a_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def stub(url: str) -> FetchResult:
        return FetchResult(200, None)

    assert main([], fetch=stub, retry_sleep=0.0) != 0

    captured = capsys.readouterr()
    assert "verified" not in captured.out
    assert "unparseable response (HTTP 200)" in captured.err


# --------------------------------------------------------------------------- #
# main  (the 5xx retry loop: bound pinned from both sides)
# --------------------------------------------------------------------------- #


Responder = Callable[[str, int], FetchResult]


class _CountingFetch:
    """A fetch stub that records how many HTTP calls ``main`` drives through it."""

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.calls = 0

    def __call__(self, url: str) -> FetchResult:
        self.calls += 1
        return self._responder(url, self.calls)


def test_main_retries_a_persistent_5xx_exactly_twice_per_pin(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def always_500(url: str, _call: int) -> FetchResult:
        return FetchResult(500, {})

    fetch = _CountingFetch(always_500)
    pin_count = len(workflow_pins(WORKFLOW_DIR))

    assert main([], fetch=fetch, retry_sleep=0.0) != 0

    # One initial attempt plus two retries, and no more, for every pin.
    assert fetch.calls == 3 * pin_count

    captured = capsys.readouterr()
    assert "server error (HTTP 500)" in captured.err
    assert "after retries" in captured.err


def test_main_stops_retrying_once_a_5xx_call_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = {(pin.repo, pin.tag): pin.sha for pin in workflow_pins(WORKFLOW_DIR)}

    def flaky_first_pin(url: str, call: int) -> FetchResult:
        # The first pin's first two attempts 5xx, the third succeeds; every
        # later call succeeds outright.
        if call <= 2:
            return FetchResult(500, {})
        repo, tag = _ref_url_repo_and_tag(url)
        return FetchResult(
            200, {"object": {"type": "commit", "sha": expected[(repo, tag)]}}
        )

    fetch = _CountingFetch(flaky_first_pin)
    pin_count = len(workflow_pins(WORKFLOW_DIR))

    assert main([], fetch=fetch, retry_sleep=0.0) == 0

    # Two retries on the first pin, then one clean call per remaining pin: the
    # loop never fires again once a retry lands.
    assert fetch.calls == pin_count + 2

    assert f"verified {pin_count}/{pin_count} pins" in capsys.readouterr().out
