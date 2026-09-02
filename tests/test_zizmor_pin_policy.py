"""The workflow lint rejects a GitHub Action that is not pinned to a commit SHA.

`tools/lint-workflows.sh` delegates that rule to zizmor's `unpinned-uses` audit
under `zizmor.yml`'s blanket `hash-pin` policy. zizmor 1.30.0's built-in
default already rejects a tag pin, so a broken config (wrong key path, file not
found) would produce identical output; this test drives a known-bad workflow
through the real config to pin the behaviour against that.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ZIZMOR_CONFIG = _REPO_ROOT / "zizmor.yml"

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
"""

# Hash-pinned and otherwise clean, so zizmor exits 0 on it under any working
# config; a non-zero exit can then only mean zizmor refused to load the config.
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

pytestmark = pytest.mark.skipif(
    shutil.which("zizmor") is None, reason="zizmor not on PATH (run under `pixi run`)"
)


def test_hash_pin_policy_rejects_a_tag_pinned_action(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "tag.yml").write_text(_TAG_PINNED_WORKFLOW, encoding="utf-8")

    result = subprocess.run(
        [
            "zizmor",
            "--offline",
            "--config",
            str(_ZIZMOR_CONFIG),
            str(workflows),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    assert "unpinned-uses" in result.stdout + result.stderr


def test_missing_config_is_a_hard_error_not_a_silent_default(tmp_path: Path) -> None:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "clean.yml").write_text(_CLEAN_WORKFLOW, encoding="utf-8")

    result = subprocess.run(
        [
            "zizmor",
            "--offline",
            "--config",
            str(tmp_path / "does-not-exist.yml"),
            str(workflows),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0, result.stdout + result.stderr
