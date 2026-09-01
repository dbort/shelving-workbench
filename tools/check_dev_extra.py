"""check_dev_extra: fail when the active environment is missing a [dev] name.

``./test.sh --fast`` runs this before ruff/mypy/pytest. A ``.venv`` provisioned
before a name was added to ``pyproject.toml``'s
``[project.optional-dependencies].dev`` still imports unrelated code fine, so
without this gate a stale environment first surfaces as a pytest collection
error deep in the run instead of as one actionable message. Distribution
metadata only: the packages are never imported and no network is touched.
"""

import importlib.metadata as metadata
import pathlib
import re
import sys
import tomllib
from collections.abc import Sequence

# Shared with test.sh's tool preflight: exit 3 means "dev environment not ready".
_EXIT_ENV_OUT_OF_SYNC = 3

# First match ends the distribution name inside a PEP 508 requirement string.
# ``@`` is in the class so a future ``name @ https://...`` direct reference
# yields the bare name rather than the whole URL.
_NAME_END = re.compile(r"[<>=!~;\[@\s]")


def dev_extra_names(pyproject_path: pathlib.Path) -> list[str]:
    """Bare distribution names from ``[project.optional-dependencies].dev``."""
    # tomllib.load types the document as ``dict[str, Any]``; the [dev] extra is
    # an array of PEP 508 strings by the pyproject spec, pinned to list[str] here.
    with pyproject_path.open("rb") as handle:
        document = tomllib.load(handle)
    dev: list[str] = document["project"]["optional-dependencies"]["dev"]
    return [_NAME_END.split(spec, maxsplit=1)[0].strip() for spec in dev]


def missing_distributions(names: Sequence[str]) -> list[str]:
    """Subset of ``names`` with no installed distribution, in the given order."""
    missing: list[str] = []
    for name in names:
        try:
            metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.append(name)
    return missing


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    pyproject_path = pathlib.Path(args[0]) if args else pathlib.Path("pyproject.toml")
    missing = missing_distributions(dev_extra_names(pyproject_path))
    if missing:
        print(
            "dev environment is out of sync with the [dev] extra: "
            f"{', '.join(missing)}. Run tools/install-deps.sh.",
            file=sys.stderr,
        )
        return _EXIT_ENV_OUT_OF_SYNC
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
