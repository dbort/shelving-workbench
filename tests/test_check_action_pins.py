"""Behavioural coverage of ``tools/check-action-pins.sh``.

The script resolves each SHA-pinned action's ``# vX.Y.Z`` tag against the
GitHub API. Running it against the live API would make the suite depend on
GitHub being reachable and on the live tag graph, so these tests point
``GITHUB_API_URL`` at a local mock of the two endpoints it calls
(``/repos/<owner>/<repo>/git/ref/tags/<tag>`` and ``.../git/tags/<sha>``) and
assert the script's outcome for each shape of response. The mock counts
requests so the offline case can prove no call was made.

Every case builds its own subprocess environment. ``pixi run tests --
--offline`` exports ``SHELVING_OFFLINE=1`` into pytest's own environment, so a
case that needs the check to run must drop that variable rather than inherit
it.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import re
import subprocess
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Literal, NamedTuple, Protocol

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "tools" / "check-action-pins.sh"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"

ZERO_SHA = "0" * 40


def _tag_object_sha(repo: str, tag: str) -> str:
    """Stand-in SHA for an annotated tag's tag object, unique per ``(repo, tag)``.

    Keeping it distinct per pin means the dereference endpoint can map a tag
    object back to exactly one commit, so two pins of the same ``owner/repo``
    at different tags cannot answer with a shared SHA.
    """
    return hashlib.sha1(f"{repo}@{tag}".encode()).hexdigest()


# Mirrors the script's own line filter: a `uses:` pin with a full commit SHA
# and a `# vX.Y.Z` release comment.
_PIN_RE = re.compile(
    r"uses:\s*([A-Za-z0-9._/-]+)@([0-9a-f]{40})\s+#\s+v([0-9]+\.[0-9]+\.[0-9]+)\s*$"
)

MockMode = Literal["lightweight", "annotated", "mismatch", "not_found", "server_error"]


class Pin(NamedTuple):
    """One resolved ``uses:`` pin from a workflow file."""

    workflow: str
    repo: str
    tag: str
    sha: str


def workflow_pins() -> tuple[Pin, ...]:
    """Every SHA-pinned action across ``.github/workflows/``, path segment stripped."""
    pins: list[Pin] = []
    paths = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip().lstrip("-").strip()
            match = _PIN_RE.match(line)
            if match is None:
                continue
            ref, sha, version = match.group(1), match.group(2), match.group(3)
            repo = "/".join(ref.split("/")[:2])
            pins.append(Pin(path.name, repo, f"v{version}", sha))
    return tuple(pins)


def _expected_commits() -> Mapping[tuple[str, str], str]:
    return {(pin.repo, pin.tag): pin.sha for pin in workflow_pins()}


class _MockServer(http.server.HTTPServer):
    """HTTP server that answers the tag endpoints and counts requests."""

    def __init__(
        self,
        address: tuple[str, int],
        mode: MockMode,
        commits: Mapping[tuple[str, str], str],
    ) -> None:
        super().__init__(address, _Handler)
        self.mode: MockMode = mode
        self.commits: Mapping[tuple[str, str], str] = commits
        self.request_count: int = 0
        # Every ``Authorization`` header value the mock has received, in order
        # (``None`` when a request carried none). The token-host guard test
        # asserts this stays all-``None`` for a non-github API base.
        self.authorizations: list[str | None] = []

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """Silence the per-request stderr logging (matches the base signature)."""

    def _reply(self, status: int, payload: Mapping[str, object]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # http.server dispatches on this exact name
        server = self.server
        assert isinstance(server, _MockServer)
        server.request_count += 1
        server.authorizations.append(self.headers.get("Authorization"))

        parts = self.path.strip("/").split("/")
        # /repos/<owner>/<repo>/git/ref/tags/<tag>
        if (
            len(parts) == 7
            and parts[0] == "repos"
            and parts[3:6] == ["git", "ref", "tags"]
        ):
            repo = f"{parts[1]}/{parts[2]}"
            tag = parts[6]
            commit = server.commits.get((repo, tag), ZERO_SHA)
            self._reply_ref(server.mode, repo, tag, commit)
            return
        # /repos/<owner>/<repo>/git/tags/<sha>
        if len(parts) == 6 and parts[0] == "repos" and parts[3:5] == ["git", "tags"]:
            repo = f"{parts[1]}/{parts[2]}"
            object_sha = parts[5]
            commit = next(
                (
                    sha
                    for (pin_repo, pin_tag), sha in server.commits.items()
                    if pin_repo == repo
                    and _tag_object_sha(pin_repo, pin_tag) == object_sha
                ),
                ZERO_SHA,
            )
            self._reply(
                200,
                {"sha": object_sha, "object": {"sha": commit, "type": "commit"}},
            )
            return
        self._reply(404, {"message": "unhandled path"})

    def _reply_ref(self, mode: MockMode, repo: str, tag: str, commit: str) -> None:
        if mode == "not_found":
            self._reply(404, {"message": "Not Found"})
            return
        if mode == "server_error":
            self._reply(500, {"message": "server error"})
            return
        ref = f"refs/tags/{tag}"
        if mode == "annotated":
            self._reply(
                200,
                {
                    "ref": ref,
                    "object": {"sha": _tag_object_sha(repo, tag), "type": "tag"},
                },
            )
            return
        sha = ZERO_SHA if mode == "mismatch" else commit
        self._reply(200, {"ref": ref, "object": {"sha": sha, "type": "commit"}})


class StartMock(Protocol):
    def __call__(self, mode: MockMode) -> _MockServer: ...


@pytest.fixture
def start_mock() -> Iterator[StartMock]:
    servers: list[_MockServer] = []

    def _start(mode: MockMode) -> _MockServer:
        server = _MockServer(("127.0.0.1", 0), mode, _expected_commits())
        # serve_forever's default 0.5s poll_interval is what server.shutdown()
        # waits on at teardown; a short interval keeps each test from paying it.
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.01), daemon=True
        )
        thread.start()
        servers.append(server)
        return server

    yield _start

    for server in servers:
        server.shutdown()
        server.server_close()


def _run(
    *,
    api_url: str,
    offline: bool = False,
    shelving_offline: str | None = None,
    gh_token: str | None = None,
    github_token: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Drive the script as a subprocess with an explicit environment.

    ``SHELVING_OFFLINE``, ``GH_TOKEN``, and ``GITHUB_TOKEN`` are stripped from
    the inherited environment by default so ``pixi run tests -- --offline``
    cannot leak ``SHELVING_OFFLINE=1`` in and no ambient token reaches the
    mock. A case opts back in through ``shelving_offline`` (any raw value, for
    the value-guard test) or ``gh_token`` / ``github_token`` (for the
    token-host guard test).
    """
    env: dict[str, str] = {
        key: value
        for key, value in os.environ.items()
        if key not in {"SHELVING_OFFLINE", "GH_TOKEN", "GITHUB_TOKEN"}
    }
    env["GITHUB_API_URL"] = api_url
    env["CHECK_ACTION_PINS_RETRY_SLEEP"] = "0"
    if offline:
        env["SHELVING_OFFLINE"] = "1"
    if shelving_offline is not None:
        env["SHELVING_OFFLINE"] = shelving_offline
    if gh_token is not None:
        env["GH_TOKEN"] = gh_token
    if github_token is not None:
        env["GITHUB_TOKEN"] = github_token
    return subprocess.run(
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def test_all_pins_verified_against_lightweight_tags(start_mock: StartMock) -> None:
    server = start_mock("lightweight")
    result = _run(api_url=server.base_url)

    assert result.returncode == 0, result.stderr
    count = len(workflow_pins())
    assert f"check-action-pins: verified {count}/{count} pins" in result.stdout
    assert server.request_count == count


def test_annotated_tag_is_dereferenced_to_its_commit(start_mock: StartMock) -> None:
    server = start_mock("annotated")
    result = _run(api_url=server.base_url)

    assert result.returncode == 0, result.stderr
    count = len(workflow_pins())
    assert f"verified {count}/{count} pins" in result.stdout
    # One ref lookup plus one tag-object dereference per pin.
    assert server.request_count == 2 * count


def test_mismatched_sha_is_fatal_and_names_the_offender(
    start_mock: StartMock,
) -> None:
    server = start_mock("mismatch")
    result = _run(api_url=server.base_url)

    assert result.returncode != 0
    # Every pin fails in this mode; the run must report them all, not just the
    # first, so each pin's repo and pinned SHA has to appear on stderr.
    for pin in workflow_pins():
        assert pin.repo in result.stderr, pin
        assert pin.sha in result.stderr, pin
    assert ZERO_SHA in result.stderr
    assert "verified" not in result.stdout


def test_missing_tag_is_fatal(start_mock: StartMock) -> None:
    server = start_mock("not_found")
    result = _run(api_url=server.base_url)

    assert result.returncode != 0
    assert "404" in result.stderr
    assert "verified" not in result.stdout


def test_persistent_server_error_is_fatal_after_retries(
    start_mock: StartMock,
) -> None:
    server = start_mock("server_error")
    result = _run(api_url=server.base_url)

    assert result.returncode != 0
    assert "500" in result.stderr
    # Initial attempt plus two retries for every pin.
    assert server.request_count == 3 * len(workflow_pins())


def test_unreachable_api_is_fatal() -> None:
    result = _run(api_url="http://127.0.0.1:1")

    assert result.returncode != 0
    assert "check-action-pins: FAILED" in result.stderr
    assert "verified" not in result.stdout


def test_offline_skips_before_any_network_call(start_mock: StartMock) -> None:
    server = start_mock("lightweight")
    result = _run(api_url=server.base_url, offline=True)

    assert result.returncode == 0
    assert "check-action-pins: skipped (SHELVING_OFFLINE)" in result.stderr
    assert server.request_count == 0


def test_shelving_offline_zero_is_a_usage_error(start_mock: StartMock) -> None:
    """``SHELVING_OFFLINE=0`` must fail loudly, never silently enable offline mode."""
    server = start_mock("lightweight")
    result = _run(api_url=server.base_url, shelving_offline="0")

    assert result.returncode != 0
    assert "check-action-pins: SHELVING_OFFLINE must be unset or 1" in result.stderr
    # The value guard is the script's first action, so it fires before any pin
    # is resolved.
    assert server.request_count == 0


def test_gh_token_is_never_sent_to_a_non_github_host(start_mock: StartMock) -> None:
    """A token set in the environment must not reach a redirected API base."""
    server = start_mock("lightweight")
    result = _run(api_url=server.base_url, gh_token="gh-secret-value")

    assert result.returncode == 0, result.stderr
    assert server.request_count == len(workflow_pins())
    assert server.authorizations
    assert all(value is None for value in server.authorizations), server.authorizations


def test_github_token_is_never_sent_to_a_non_github_host(
    start_mock: StartMock,
) -> None:
    server = start_mock("lightweight")
    result = _run(api_url=server.base_url, github_token="github-secret-value")

    assert result.returncode == 0, result.stderr
    assert server.authorizations
    assert all(value is None for value in server.authorizations), server.authorizations
