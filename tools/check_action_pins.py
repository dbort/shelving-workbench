#!/usr/bin/env python3
"""Verify online that every SHA-pinned GitHub Action is the commit its tag names.

For each ``uses: <owner>/<repo>[/<path>]@<40-hex> # v<maj>.<min>.<patch>`` line
under ``.github/workflows/``, resolve ``refs/tags/v<maj>.<min>.<patch>`` for
``<owner>/<repo>`` against the GitHub API, dereference an annotated-tag object to
its target commit, and assert that commit equals the pinned SHA.

There are exactly two outcomes: verified (every pin resolved and matched) or
fatal. A mismatch, a missing tag, a rate-limit response, a 5xx that persists
after retries, and a connection failure are all fatal; there is no exit-0 path
for a network failure. The one exception is ``SHELVING_OFFLINE=1``, which skips
the check before any network call.

Environment:
  SHELVING_OFFLINE          1 = skip (offline); unset/empty = run; any other
                            value is a usage error.
  GITHUB_API_URL            API base; defaults to https://api.github.com.
  GH_TOKEN / GITHUB_TOKEN   bearer token for API quota headroom, attached only
                            when the resolved API host is api.github.com so a
                            redirected base cannot harvest it.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

NAME = "check-action-pins"

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_DEFAULT_BASE = "https://api.github.com"

# A `uses:` pin with a full 40-hex commit SHA and a trailing `# vX.Y.Z` release
# comment. The reference before `@` may carry extra path segments
# (github/codeql-action/upload-sarif); the tag lives on the leading
# <owner>/<repo>, so only the first two segments are kept when resolving.
_PIN_RE = re.compile(
    r"^uses:\s*([A-Za-z0-9._/-]+)@([0-9a-f]{40})\s+#\s+v([0-9]+\.[0-9]+\.[0-9]+)$"
)


class Pin(NamedTuple):
    """One SHA-pinned ``uses:`` entry from a workflow file."""

    repo: str
    tag: str
    sha: str
    file: str


class FetchResult(NamedTuple):
    """An HTTP response reduced to what pin resolution needs.

    ``status`` is ``0`` for a connection-level failure so ``classify_status``
    can treat "never got an answer" as one more fatal case.
    """

    status: int
    body: Mapping[str, object]


Fetch = Callable[[str], FetchResult]


class ResolveError(Exception):
    """A pin's tag could not be resolved to a commit; the message is the reason."""


class OfflineConfigError(Exception):
    """``SHELVING_OFFLINE`` held a value other than unset, empty, or ``1``."""


def workflow_pins(directory: Path) -> tuple[Pin, ...]:
    """Every SHA-pinned action under ``directory``, path segment stripped.

    Both ``.yml`` and ``.yaml`` are read so a ``.yaml`` workflow cannot slip
    past. ``- uses:`` list items and bare ``uses:`` keys are both recognised.
    """
    pins: list[Pin] = []
    paths = sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")])
    for path in paths:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("-"):
                line = line[1:].strip()
            match = _PIN_RE.match(line)
            if match is None:
                continue
            ref, sha, version = match.group(1), match.group(2), match.group(3)
            repo = "/".join(ref.split("/")[:2])
            pins.append(Pin(repo, f"v{version}", sha, path.name))
    return tuple(pins)


def classify_status(status: int, what: str) -> str | None:
    """Map an HTTP status to ``None`` (verified path) or a fatal reason string.

    Pure: the caller has already made the call and, for 5xx, already exhausted
    its retries. ``status == 0`` means the request never completed.
    """
    if status == 200:
        return None
    if status == 0:
        return f"cannot reach the API for {what}: connection failed"
    if status in (403, 429):
        return (
            f"rate limited (HTTP {status}) for {what}; set GH_TOKEN or "
            "GITHUB_TOKEN to raise the API quota"
        )
    if status == 404:
        return f"tag not found (HTTP 404) for {what}"
    if 500 <= status <= 599:
        return f"server error (HTTP {status}) for {what} after retries"
    return f"unexpected HTTP {status} for {what}"


def offline_mode() -> bool:
    """Read the ``SHELVING_OFFLINE`` contract before any network call is made.

    ``1`` enables offline mode; unset or empty disables it; any other value is
    a usage error, so ``SHELVING_OFFLINE=0`` never silently enables it.
    """
    value = os.environ.get("SHELVING_OFFLINE", "")
    if value == "":
        return False
    if value == "1":
        return True
    raise OfflineConfigError(f"{NAME}: SHELVING_OFFLINE must be unset or 1")


def auth_headers(base: str, env: Mapping[str, str]) -> Mapping[str, str]:
    """Bearer header for ``base``, but only when the host is the real GitHub API.

    A redirected or misconfigured ``GITHUB_API_URL`` must never receive the
    token, so any host other than ``api.github.com`` gets no header.
    """
    token = env.get("GH_TOKEN") or env.get("GITHUB_TOKEN") or ""
    if not token:
        return {}
    if urllib.parse.urlsplit(base).hostname != "api.github.com":
        return {}
    return {"Authorization": f"Bearer {token}"}


def _object_fields(body: Mapping[str, object]) -> tuple[str, str] | None:
    """``(object.type, object.sha)`` from a ref or tag-object payload."""
    obj = body.get("object")
    if not isinstance(obj, Mapping):
        return None
    obj_type = obj.get("type")
    obj_sha = obj.get("sha")
    if not isinstance(obj_type, str) or not isinstance(obj_sha, str):
        return None
    return obj_type, obj_sha


def _fetch_catching(fetch: Fetch, url: str) -> FetchResult:
    """Call ``fetch``, turning a connection-level failure into ``status == 0``."""
    try:
        return fetch(url)
    except (urllib.error.URLError, OSError):
        return FetchResult(0, {})


def resolve_commit(fetch: Fetch, base: str, repo: str, tag: str) -> str:
    """Commit SHA that ``tag`` names for ``repo``, following an annotated tag.

    Raises ``ResolveError`` with a human-readable reason on any non-200 status,
    a connection failure, or an unexpected payload shape.
    """
    ref_result = _fetch_catching(fetch, f"{base}/repos/{repo}/git/ref/tags/{tag}")
    reason = classify_status(ref_result.status, f"{repo}@{tag}")
    if reason is not None:
        raise ResolveError(reason)

    fields = _object_fields(ref_result.body)
    if fields is None:
        raise ResolveError(f"unexpected API response resolving {repo} ref {tag}")
    obj_type, obj_sha = fields

    if obj_type == "commit":
        return obj_sha
    if obj_type != "tag":
        raise ResolveError(f"unexpected tag object type {obj_type!r} for {repo}@{tag}")

    tag_result = _fetch_catching(fetch, f"{base}/repos/{repo}/git/tags/{obj_sha}")
    reason = classify_status(tag_result.status, f"{repo} tag object for {tag}")
    if reason is not None:
        raise ResolveError(reason)
    deref = _object_fields(tag_result.body)
    if deref is None:
        raise ResolveError(
            f"unexpected API response dereferencing {repo} tag object for {tag}"
        )
    return deref[1]


def _as_mapping(payload: object) -> Mapping[str, object]:
    """Narrow a parsed JSON value to a string-keyed mapping, or an empty one."""
    if isinstance(payload, Mapping):
        return {str(key): value for key, value in payload.items()}
    return {}


def _http_fetch(url: str, headers: Mapping[str, str]) -> FetchResult:
    """Real GitHub API call. Raises ``urllib.error.URLError`` on a dead host."""
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", **headers},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            # json.load's return is Any by construction (arbitrary external
            # JSON); it is pinned to `object` here and narrowed by _as_mapping.
            payload: object = json.load(response)
            status = int(response.status)
    except urllib.error.HTTPError as error:
        try:
            payload = json.loads(error.read() or b"{}")
        except ValueError:
            payload = {}
        status = int(error.code)
    return FetchResult(status, _as_mapping(payload))


def _make_http_fetch(base: str) -> Fetch:
    """Bind the real HTTP fetch to the auth headers ``base`` is allowed to see."""
    headers = auth_headers(base, os.environ)

    def fetch(url: str) -> FetchResult:
        return _http_fetch(url, headers)

    return fetch


def _retrying_fetch(
    base_fetch: Fetch, sleep: Callable[[float], None], retry_sleep: float
) -> Fetch:
    """Wrap ``base_fetch`` so a 5xx status is retried up to twice."""

    def fetch(url: str) -> FetchResult:
        result = base_fetch(url)
        attempts = 0
        while 500 <= result.status <= 599 and attempts < 2:
            attempts += 1
            sleep(retry_sleep)
            result = base_fetch(url)
        return result

    return fetch


def main(
    argv: Sequence[str],
    *,
    fetch: Fetch | None = None,
    sleep: Callable[[float], None] = time.sleep,
    retry_sleep: float = 1.0,
) -> int:
    """Resolve every workflow pin; return 0 only when all of them verify."""
    if list(argv):
        print(f"{NAME}: unexpected argument: {argv[0]}", file=sys.stderr)
        return 2

    try:
        offline = offline_mode()
    except OfflineConfigError as error:
        print(str(error), file=sys.stderr)
        return 2
    if offline:
        print(f"{NAME}: skipped (SHELVING_OFFLINE)", file=sys.stderr)
        return 0

    base = os.environ.get("GITHUB_API_URL", _DEFAULT_BASE).rstrip("/")
    pins = workflow_pins(_WORKFLOW_DIR)
    if not pins:
        print(f"{NAME}: found no 'uses:' pins under {_WORKFLOW_DIR}", file=sys.stderr)
        return 1

    resolving_fetch = _retrying_fetch(
        fetch or _make_http_fetch(base), sleep, retry_sleep
    )

    failures: list[str] = []
    verified = 0
    for pin in pins:
        try:
            commit = resolve_commit(resolving_fetch, base, pin.repo, pin.tag)
        except ResolveError as error:
            failures.append(f"{pin.file}: {pin.repo}@{pin.tag}: {error}")
            continue
        if commit == pin.sha:
            verified += 1
        else:
            failures.append(
                f"{pin.file}: {pin.repo}@{pin.tag} is pinned at {pin.sha} "
                f"but the tag resolves to {commit}"
            )

    if failures:
        print(f"{NAME}: FAILED", file=sys.stderr)
        for line in failures:
            print(f"  {line}", file=sys.stderr)
        return 1

    print(f"{NAME}: verified {verified}/{len(pins)} pins")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
