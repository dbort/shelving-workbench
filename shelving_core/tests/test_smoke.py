"""Basic import and metadata checks for :mod:`shelving_core`."""

import shelving_core


def test_version_is_nonempty_str() -> None:
    assert isinstance(shelving_core.__version__, str)
    assert shelving_core.__version__
