"""Unit coverage of ``tools/check_action_pins.py``.

The module is built from small, injectable pieces so its behaviour can be
pinned without a network round-trip or a mock HTTP server: ``resolve_commit``
and ``main`` take a ``fetch`` callable, ``offline_mode`` reads one environment
variable, and ``classify_status`` / ``auth_headers`` are pure. The live GitHub
call still happens for real when ``pixi run tests`` runs on a networked host;
these tests never touch the network and finish in well under a second.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
from collections.abc import Mapping
from pathlib import Path

import pytest

from tools.check_action_pins import (
    FetchResult,
    OfflineConfigError,
    Pin,
    ResolveError,
    auth_headers,
    classify_status,
    main,
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
    for name in ("SHELVING_OFFLINE", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- #
# workflow_pins
# --------------------------------------------------------------------------- #


def test_workflow_pins_parses_both_extensions_and_strips_path_segments(
    tmp_path: Path,
) -> None:
    (tmp_path / "ci.yml").write_text(
        "jobs:\n"
        "  build:\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{SHA_A} # v4.2.2\n"
        f"      - uses: github/codeql-action/upload-sarif@{SHA_B} # v3.28.1\n"
        "      - uses: actions/setup-python@v5\n"
        "      - name: not a uses line\n",
        encoding="utf-8",
    )
    (tmp_path / "release.yaml").write_text(
        f"      - uses: step-security/harden-runner@{SHA_C} # v2.10.4\n",
        encoding="utf-8",
    )

    pins = workflow_pins(tmp_path)

    assert isinstance(pins, tuple)
    assert pins == (
        Pin("actions/checkout", "v4.2.2", SHA_A, "ci.yml"),
        Pin("github/codeql-action", "v3.28.1", SHA_B, "ci.yml"),
        Pin("step-security/harden-runner", "v2.10.4", SHA_C, "release.yaml"),
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
    reason = classify_status(status, "owner/repo@v1.0.0")
    assert reason is not None
    assert needle in reason
    assert "owner/repo@v1.0.0" in reason


def test_classify_status_200_is_the_verified_path() -> None:
    assert classify_status(200, "owner/repo@v1.0.0") is None


def test_classify_status_rate_limit_names_the_token_fix() -> None:
    reason = classify_status(403, "owner/repo@v1.0.0")
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
