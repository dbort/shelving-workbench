"""Unit tests for freecad.Shelving.debug_log."""

import re

import pytest

from freecad.Shelving import debug_log


@pytest.fixture(autouse=True)
def _enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(debug_log, "enabled", True)


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    return capsys.readouterr().out.splitlines()


def test_a_run_is_bracketed_by_markers_sharing_its_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    run = debug_log.begin("edit unit")
    run.lap("resolve unit")
    debug_log.Stopwatch("session").lap("solve")
    debug_log.log("free-form note")
    run.end()

    lines = _lines(capsys)
    tag = f"[shelving] #{run.id} "
    assert all(line.startswith(tag) for line in lines), lines
    assert re.search(r"===== BEGIN edit unit \d{4}-\d\d-\d\d ", lines[0])
    assert "edit unit: resolve unit:" in lines[1]
    assert "session: solve:" in lines[2]
    assert lines[3].endswith("free-form note")
    assert re.search(r"===== END edit unit \(done\) .*total [\d.]+ ms =====", lines[4])
    assert len(lines) == 5


def test_runs_get_distinct_ids(capsys: pytest.CaptureFixture[str]) -> None:
    first = debug_log.begin("a")
    first.end()
    second = debug_log.begin("b")
    second.end()
    assert first.id != second.id


def test_a_new_run_closes_one_left_open_as_abandoned(
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = debug_log.begin("stale")
    fresh = debug_log.begin("fresh")
    stale.end()
    fresh.end("refused")

    lines = _lines(capsys)
    ends = [line for line in lines if "===== END" in line]
    assert len(ends) == 2, lines
    assert f"#{stale.id} ===== END stale (abandoned)" in ends[0]
    assert f"#{fresh.id} ===== END fresh (refused)" in ends[1]


def test_ending_twice_logs_one_end(capsys: pytest.CaptureFixture[str]) -> None:
    run = debug_log.begin("once")
    run.end()
    run.end()
    assert sum("===== END" in line for line in _lines(capsys)) == 1


def test_lines_outside_a_run_carry_no_id(capsys: pytest.CaptureFixture[str]) -> None:
    debug_log.log("loose")
    assert _lines(capsys) == ["[shelving] loose"]


def test_disabled_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(debug_log, "enabled", False)
    run = debug_log.begin("quiet")
    run.lap("stage")
    debug_log.Stopwatch("nested").lap("stage")
    debug_log.log("note")
    run.end()
    assert _lines(capsys) == []


def test_a_late_lap_keeps_its_own_runs_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    old = debug_log.begin("old")
    new = debug_log.begin("new")
    old.lap("late paint")
    new.end()
    late = [line for line in _lines(capsys) if "late paint" in line]
    assert late and late[0].startswith(f"[shelving] #{old.id} "), late
