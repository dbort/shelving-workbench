"""The workflow lint rejects a GitHub Action that is not pinned to a commit SHA.

`tools/lint-workflows.sh` delegates that rule to zizmor's `unpinned-uses` audit
under `zizmor.yml`'s blanket `hash-pin` policy. zizmor 1.30.0's built-in
default already rejects a tag pin, so a broken config (wrong key path, file not
found) would produce identical output on the repo's own workflows; these tests
drive purpose-built inputs through the real config to tell the two apart.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ZIZMOR_CONFIG = _REPO_ROOT / "zizmor.yml"

# Tag-pinned, so hash-pin rejects it; `persist-credentials: false` keeps
# zizmor's artipacked finding away, leaving `unpinned-uses` as the only
# variable between policies.
_TAG_PINNED_WORKFLOW = """\
name: tag
on: [push]
permissions: {}
jobs:
  build:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
"""

# Hash-pinned and clean: zizmor exits 0 under any working config, so a non-zero
# exit can only mean zizmor refused to load the config it was handed.
_CLEAN_WORKFLOW = """\
name: clean
on: [push]
permissions: {}
jobs:
  build:
    runs-on: ubuntu-24.04
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
"""

_ANY_POLICY_CONFIG = """\
rules:
  unpinned-uses:
    config:
      policies:
        "*": any
"""

pytestmark = pytest.mark.skipif(
    shutil.which("zizmor") is None, reason="zizmor not on PATH (run under `pixi run`)"
)


def _run_zizmor(config: Path, workflow_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["zizmor", "--offline", "--config", str(config), str(workflow_dir)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _workflows(tmp_path: Path, name: str, body: str) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True, exist_ok=True)
    (workflows / name).write_text(body, encoding="utf-8")
    return workflows


def test_hash_pin_policy_rejects_a_tag_pinned_action(tmp_path: Path) -> None:
    result = _run_zizmor(
        _ZIZMOR_CONFIG, _workflows(tmp_path, "tag.yml", _TAG_PINNED_WORKFLOW)
    )
    assert result.returncode != 0, result.stdout + result.stderr
    assert "unpinned-uses" in result.stdout + result.stderr


def test_the_policy_body_is_honored_not_just_the_file(tmp_path: Path) -> None:
    # The same tag pin under a config that flips the policy to `any`: the
    # `unpinned-uses` finding disappears only if zizmor actually reads
    # `rules.unpinned-uses.config.policies`. Guards against a mistyped key path
    # leaving the committed config inert while 1.30.0's default masks it.
    config = tmp_path / "any.yml"
    config.write_text(_ANY_POLICY_CONFIG, encoding="utf-8")
    result = _run_zizmor(config, _workflows(tmp_path, "tag.yml", _TAG_PINNED_WORKFLOW))
    assert result.returncode == 0, result.stdout + result.stderr
    assert "unpinned-uses" not in result.stdout + result.stderr


def test_missing_config_is_a_hard_error_not_a_silent_default(tmp_path: Path) -> None:
    workflows = _workflows(tmp_path, "clean.yml", _CLEAN_WORKFLOW)

    # Positive control: the clean workflow passes under the real config, so a
    # failure below is the missing config, not the workflow.
    assert _run_zizmor(_ZIZMOR_CONFIG, workflows).returncode == 0

    result = _run_zizmor(tmp_path / "does-not-exist.yml", workflows)
    assert result.returncode != 0, result.stdout + result.stderr
    assert "no audit was performed" in result.stdout + result.stderr
