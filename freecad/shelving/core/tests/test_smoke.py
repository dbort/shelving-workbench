"""Basic import and metadata checks for :mod:`freecad.shelving.core`."""

from freecad.shelving import core


def test_version_is_nonempty_str() -> None:
    assert isinstance(core.__version__, str)
    assert core.__version__
