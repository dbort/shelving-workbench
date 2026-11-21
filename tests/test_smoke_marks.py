"""The ``smoke`` marker's rules (:mod:`tests.smoke_marks`), over the
repository's own marks and in real pytest runs."""

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.smoke_marks import mark_problem, source_mark_problems

_ROOT = Path(__file__).resolve().parent.parent
_MARKED_DIRS = (_ROOT / "tests" / "freecad_gui", _ROOT / "tests" / "freecad_view")
_TIMEOUT_S = 60


def test_every_smoke_mark_names_one_path_no_other_mark_gives() -> None:
    assert source_mark_problems(_ROOT, _MARKED_DIRS) == []


@pytest.mark.parametrize(
    ("args", "kwargs", "problem"),
    [
        (("open a unit",), {}, None),
        ((), {}, "takes exactly one argument, the user path it covers; it has 0"),
        (
            ("a", "b"),
            {},
            "takes exactly one argument, the user path it covers; it has 2",
        ),
        (("",), {}, "has an empty user path"),
        (("  ",), {}, "has an empty user path"),
        ((3,), {}, "takes its user path as a literal string"),
        ((), {"path": "open a unit"}, "takes no keyword arguments"),
    ],
)
def test_a_mark_needs_exactly_one_non_blank_path(
    args: tuple[object, ...], kwargs: dict[str, object], problem: str | None
) -> None:
    assert mark_problem(args, kwargs) == problem


def _write(path: Path, source: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source))


_GOOD = """\
    import pytest

    @pytest.mark.smoke("open a unit")
    def test_open() -> None:
        pass
    """


@pytest.mark.parametrize(
    ("source", "problem"),
    [
        (
            """\
            import pytest

            @pytest.mark.smoke
            def test_bare() -> None:
                pass
            """,
            "gui/test_b.py:3 (test_bare): its smoke mark takes exactly one "
            "argument, the user path it covers; it has 0",
        ),
        (
            """\
            import pytest

            @pytest.mark.smoke()
            def test_no_path() -> None:
                pass
            """,
            "gui/test_b.py:3 (test_no_path): its smoke mark takes exactly one "
            "argument, the user path it covers; it has 0",
        ),
        (
            """\
            import pytest

            @pytest.mark.smoke("")
            def test_empty() -> None:
                pass
            """,
            "gui/test_b.py:3 (test_empty): its smoke mark has an empty user path",
        ),
        (
            """\
            import pytest

            @pytest.mark.smoke("close a unit", "and more")
            def test_two() -> None:
                pass
            """,
            "gui/test_b.py:3 (test_two): its smoke mark takes exactly one "
            "argument, the user path it covers; it has 2",
        ),
        (
            """\
            import pytest

            PATH = "close a unit"

            @pytest.mark.smoke(PATH)
            def test_named() -> None:
                pass
            """,
            "gui/test_b.py:5 (test_named): its smoke mark takes its user path "
            "as a literal string",
        ),
        (
            """\
            import pytest

            _STYLES = (pytest.param(1, marks=pytest.mark.smoke("open a unit")),)
            """,
            "smoke path 'open a unit' is claimed by more than one test: "
            "gui/test_a.py:3 (test_open), gui/test_b.py:3 (_STYLES)",
        ),
    ],
)
def test_the_source_check_names_each_bad_mark(
    tmp_path: Path, source: str, problem: str
) -> None:
    _write(tmp_path / "gui" / "test_a.py", _GOOD)
    _write(tmp_path / "gui" / "test_b.py", source)
    assert source_mark_problems(tmp_path, [tmp_path / "gui"]) == [problem]


def test_the_source_check_sees_a_path_claimed_in_each_suite(tmp_path: Path) -> None:
    _write(tmp_path / "gui" / "test_a.py", _GOOD)
    _write(
        tmp_path / "view" / "test_c.py",
        """\
        from pytest import mark

        @mark.smoke("open a unit")
        def test_open_too() -> None:
            pass
        """,
    )
    assert source_mark_problems(tmp_path, [tmp_path / "gui", tmp_path / "view"]) == [
        "smoke path 'open a unit' is claimed by more than one test: "
        "gui/test_a.py:3 (test_open), view/test_c.py:3 (test_open_too)"
    ]


def _pytest(
    tmp_path: Path, source: str, *args: str
) -> subprocess.CompletedProcess[str]:
    """Run pytest with the smoke plugin over a test module holding
    ``source``, outside this repository's conftest."""
    _write(tmp_path / "test_marked.py", source)
    env = dict(os.environ, PYTHONPATH=str(_ROOT))
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.smoke_marks",
            "-p",
            "no:cacheprovider",
            "--rootdir",
            str(tmp_path),
            str(tmp_path),
            *args,
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        check=False,
    )


_BAD_MARKS = """\
    import pytest

    @pytest.mark.smoke
    def test_bare() -> None:
        pass

    @pytest.mark.smoke("")
    def test_empty() -> None:
        pass

    @pytest.mark.smoke("a", "b")
    def test_two() -> None:
        pass

    @pytest.mark.parametrize("n", [1, 2])
    @pytest.mark.smoke("count")
    def test_each(n: int) -> None:
        pass
    """


def test_a_run_that_collects_a_bad_mark_fails_naming_each_test(
    tmp_path: Path,
) -> None:
    result = _pytest(tmp_path, _BAD_MARKS)
    assert result.returncode == pytest.ExitCode.USAGE_ERROR, result.stdout
    for message in (
        "test_marked.py::test_bare: its smoke mark takes exactly one argument",
        "test_marked.py::test_empty: its smoke mark has an empty user path",
        "test_marked.py::test_two: its smoke mark takes exactly one argument",
        "smoke path 'count' is claimed by more than one test: "
        "test_marked.py::test_each[1], test_marked.py::test_each[2]",
    ):
        assert message in result.stderr, result.stderr


_SUITE = """\
    import pytest

    @pytest.mark.parametrize(
        "n", [pytest.param(1, marks=pytest.mark.smoke("count to one")), 2]
    )
    def test_count(n: int) -> None:
        pass

    def test_other() -> None:
        pass
    """


def test_a_smoke_run_ends_listing_its_tests_with_their_paths(tmp_path: Path) -> None:
    result = _pytest(tmp_path, _SUITE, "-m", "smoke")
    assert result.returncode == 0, result.stdout + result.stderr
    lines = result.stdout.splitlines()
    heading = next(
        i
        for i, line in enumerate(lines)
        if "smoke tests run, with the user path" in line
    )
    assert lines[heading + 1 : heading + 3] == [
        "test_marked.py::test_count[1]",
        "    count to one",
    ]
    assert "1 passed, 2 deselected" in lines[heading + 3]


def test_a_full_run_lists_no_smoke_tests(tmp_path: Path) -> None:
    result = _pytest(tmp_path, _SUITE)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "3 passed" in result.stdout
    assert "smoke tests run" not in result.stdout
