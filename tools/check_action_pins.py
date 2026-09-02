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
the online resolution before any network call.

A SHA-pinned ``uses:`` whose trailing comment is not a clean ``# vX.Y.Z``, or
whose SHA is not lower-case hex, is fatal too, and this check runs offline,
before ``SHELVING_OFFLINE`` is consulted: ``zizmor``'s ``unpinned-uses`` audit
guarantees the SHA, but not the release comment that the resolution below and
Dependabot both read.

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
from collections.abc import Callable, Iterator, Mapping, Sequence
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

# Any `uses:` pinned to a 40-char hex string, upper- or lower-case, whatever the
# trailing comment. A line matching this but not `_PIN_RE` is a SHA pin whose
# `# vX.Y.Z` comment is missing or malformed, or whose SHA is not the lower-case
# form the API resolution and Dependabot expect.
_SHA_USES_RE = re.compile(r"^uses:\s*[A-Za-z0-9._/-]+@[0-9a-fA-F]{40}(?:\s.*)?$")


class Pin(NamedTuple):
    """One SHA-pinned ``uses:`` entry from a workflow file."""

    repo: str
    tag: str
    sha: str
    # Path relative to the repo (``.github/workflows/ci.yml``), so a failure
    # line points at the file to edit rather than a bare basename.
    file: str


class MalformedPin(NamedTuple):
    """A ``uses:`` SHA pin that ``_PIN_RE`` rejects, kept for the failure list."""

    # Repo-relative path, as on ``Pin``.
    file: str
    # The offending line, normalised (leading ``- `` and whitespace stripped).
    line: str


class FetchResult(NamedTuple):
    """An HTTP response reduced to what pin resolution needs."""

    # ``0`` for a connection-level failure, so ``classify_status`` can treat
    # "never got an answer" as one more fatal case.
    status: int
    # ``None`` when a response arrived but its payload was not JSON (a proxy or
    # captive portal answering 200 with HTML); pin resolution reports that as
    # fatal rather than crashing on the parse.
    body: Mapping[str, object] | None


Fetch = Callable[[str], FetchResult]


class ResolveError(Exception):
    """A pin's tag could not be resolved to a commit; the message is the reason."""


class OfflineConfigError(Exception):
    """``SHELVING_OFFLINE`` held a value other than unset, empty, or ``1``."""


def _uses_lines(directory: Path) -> Iterator[tuple[str, str]]:
    """``(<repo-relative file>, <line>)`` for every ``uses:`` line under ``directory``.

    ``- uses:`` list items and bare ``uses:`` keys both yield with the leading
    ``- `` and surrounding whitespace stripped, so ``workflow_pins`` and
    ``malformed_version_comments`` match one normalised form and cannot drift
    apart. Both ``.yml`` and ``.yaml`` are read so a ``.yaml`` workflow cannot
    slip past.
    """
    rel_dir = f"{directory.parent.name}/{directory.name}"
    for path in sorted([*directory.glob("*.yml"), *directory.glob("*.yaml")]):
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("-"):
                line = line[1:].strip()
            if line.startswith("uses:"):
                yield f"{rel_dir}/{path.name}", line


def workflow_pins(directory: Path) -> tuple[Pin, ...]:
    """Every action under ``directory`` pinned as ``<sha> # vX.Y.Z``, path stripped.

    A ``uses:`` line not in that exact form is skipped;
    ``malformed_version_comments`` is what fails a SHA pin among them.
    """
    pins: list[Pin] = []
    for rel, line in _uses_lines(directory):
        match = _PIN_RE.match(line)
        if match is None:
            continue
        ref, sha, version = match.group(1), match.group(2), match.group(3)
        repo = "/".join(ref.split("/")[:2])
        pins.append(Pin(repo, f"v{version}", sha, rel))
    return tuple(pins)


def malformed_version_comments(directory: Path) -> tuple[MalformedPin, ...]:
    """SHA-pinned ``uses:`` lines under ``directory`` that ``_PIN_RE`` rejects.

    ``zizmor``'s ``unpinned-uses`` audit rejects a ``uses:`` that is not pinned
    to a full commit SHA; this covers the part it leaves alone. A SHA pin whose
    release comment is absent or malformed, or whose SHA is upper-case, drops
    out of ``workflow_pins``, goes unresolved, and leaves Dependabot without the
    tag it bumps.
    """
    return tuple(
        MalformedPin(rel, line)
        for rel, line in _uses_lines(directory)
        if _SHA_USES_RE.match(line) and not _PIN_RE.match(line)
    )


def classify_status(status: int, base: str, what: str) -> str | None:
    """Map an HTTP status to ``None`` (verified path) or a fatal reason string.

    Pure: the caller has already made the call and, for 5xx, already exhausted
    its retries. ``status == 0`` means the request never completed; ``base`` is
    named in that reason because it is the one failure that turns on a
    misconfigured or unreachable ``GITHUB_API_URL`` override.
    """
    if status == 200:
        return None
    if status == 0:
        return f"cannot reach {base} for {what}: connection failed"
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


def _require_json(result: FetchResult, what: str) -> Mapping[str, object]:
    """The parsed body; raises ``ResolveError`` when the payload was not JSON."""
    if result.body is None:
        raise ResolveError(f"unparseable response (HTTP {result.status}) for {what}")
    return result.body


def resolve_commit(fetch: Fetch, base: str, repo: str, tag: str) -> str:
    """Commit SHA that ``tag`` names for ``repo``, following an annotated tag.

    Raises ``ResolveError`` with a human-readable reason on any non-200 status,
    a connection failure, or an unexpected payload shape.
    """
    ref_result = _fetch_catching(fetch, f"{base}/repos/{repo}/git/ref/tags/{tag}")
    reason = classify_status(ref_result.status, base, f"{repo}@{tag}")
    if reason is not None:
        raise ResolveError(reason)

    fields = _object_fields(_require_json(ref_result, f"{repo}@{tag}"))
    if fields is None:
        raise ResolveError(f"unexpected API response resolving {repo} ref {tag}")
    obj_type, obj_sha = fields

    if obj_type == "commit":
        return obj_sha
    if obj_type != "tag":
        raise ResolveError(f"unexpected tag object type {obj_type!r} for {repo}@{tag}")

    tag_result = _fetch_catching(fetch, f"{base}/repos/{repo}/git/tags/{obj_sha}")
    reason = classify_status(tag_result.status, base, f"{repo} tag object for {tag}")
    if reason is not None:
        raise ResolveError(reason)
    deref = _object_fields(_require_json(tag_result, f"{repo} tag object for {tag}"))
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
            status = int(response.status)
            raw = response.read()
    except urllib.error.HTTPError as error:
        status = int(error.code)
        try:
            # json.loads' return is Any by construction (arbitrary external
            # JSON); it is pinned to `object` and narrowed by _as_mapping.
            payload: object = json.loads(error.read() or b"{}")
        except ValueError:
            payload = {}
        return FetchResult(status, _as_mapping(payload))
    try:
        payload = json.loads(raw)
    except ValueError:
        # A proxy or captive portal can answer 200 with HTML; report that as a
        # classified fatal rather than crashing on the parse.
        return FetchResult(status, None)
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
    """Return 0 only when every pin carries a ``# vX.Y.Z`` comment and resolves."""
    if list(argv):
        print(f"{NAME}: unexpected argument: {argv[0]}", file=sys.stderr)
        return 2

    malformed = malformed_version_comments(_WORKFLOW_DIR)
    if malformed:
        print(f"{NAME}: FAILED", file=sys.stderr)
        for bad in malformed:
            print(
                f"  {bad.file}: not a '<lower-case sha> # vX.Y.Z' pin: {bad.line}",
                file=sys.stderr,
            )
        return 1

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
