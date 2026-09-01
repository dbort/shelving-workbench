# Shelving Workbench

A FreeCAD 1.0 workbench for parametric shelving. A unit is designed as a flat
front elevation and expands into individually editable 3D plank solids; editing
the elevation reflows the 3D. The layout math lives in a pure-Python core
(`shelving_core`) that never imports FreeCAD, so it is testable without a GUI.
See [`docs/architecture.md`](docs/architecture.md) for the design of record and
[`docs/roadmap.md`](docs/roadmap.md) for the milestone breakdown.

To eyeball a solved layout, run `pixi run demo` (or `python tools/layout_demo.py`
from an activated environment): it builds a sample nested carcass, runs the
spacing solver, and prints the resulting rectangle for every bay and divider.
Add `pixi run demo -- --svg layout.svg` (or `python tools/layout_demo.py --svg
layout.svg`) to also write the solved layout as an SVG elevation, which opens
with Quick Look (spacebar in Finder) or any browser.

## Setup

### Recommended: `tools/install-deps.sh`

```sh
tools/install-deps.sh
```

The script is idempotent and provisions both environments:

- **`.venv/`**: a bare virtualenv with the `dev` extra (`ruff`, `mypy`,
  `pytest`). This is the FreeCAD-free path for working on `shelving_core`, and
  the local equivalent of CI's fast leg.
- **the pixi environment**: the dev toolchain plus FreeCAD 1.0, pinned by
  `pixi.lock`. This is what the full test tier needs. If `pixi` is not already
  on `PATH`, the script downloads a pinned release for the host architecture,
  verifies its published `.sha256`, installs it into `~/.local/bin`, and adds
  that directory to `~/.bashrc` and `~/.profile`. See the
  [pixi documentation](https://pixi.sh) for the tool itself.

Activate one environment before running the tests:

```sh
source .venv/bin/activate   # core-only
pixi shell                  # FreeCAD included
```

Repo-root scripts such as `tools/layout_demo.py` also need an activated
environment (or a `pixi run` prefix): they import `shelving_core` from the
environment and carry no `sys.path` shim of their own.

If the script just installed pixi, open a new shell (or `source ~/.profile`)
so `~/.local/bin` is on `PATH`.

### Minimal: core-only virtualenv

If you only need `shelving_core` and already have Python 3.11+:

```sh
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
source .venv/bin/activate
```

This skips pixi and FreeCAD entirely, so the full test tier is unavailable.

## Tests

The harness is `./test.sh`, with two tiers:

```sh
./test.sh --full    # run everything          (alias: pixi run full)
./test.sh --fast    # the FreeCAD-free subset  (alias: pixi run fast)
```

`./test.sh --full` (equivalently `pixi run full`) is the single "run
everything" command. It is a strict superset of `--fast`: it runs the entire
`--fast` sequence, then the workflow-hardening lint, then the FreeCAD smoke
test, aborting at the first failure.

- **`--fast`** runs a toolchain preflight, then `ruff check`,
  `ruff format --check`, `mypy` (strict, over `shelving_core`), the
  vendored-core drift check, and `pytest`. No FreeCAD. If `ruff`, `mypy`, or
  `pytest` is missing it names them, points at `tools/install-deps.sh`, and
  exits 3.
- **`--full`** runs the `--fast` sequence, then `tools/lint-workflows.sh`,
  then a headless smoke test through `freecadcmd`. Its preflight additionally
  requires `actionlint`, `zizmor`, `check-jsonschema`, and `shellcheck` on
  `PATH` (exit 3 if any is missing). It needs FreeCAD 1.0 or later on `PATH`
  (the pixi environment provides it; a standalone FreeCAD install also works)
  and hard-fails with a non-zero exit when `freecadcmd` is not found rather
  than skipping.

`pixi run lint-workflows` (`tools/lint-workflows.sh`) is a granular shortcut
that runs just the workflow-hardening lint over `.github/workflows/`:
`actionlint`, `zizmor`, a `uses:`-pin format check, and the Dependabot schema.
It needs the pixi environment. `./test.sh --full` runs the same script, and CI
reaches it through the `full` job. See
[`docs/github-actions-hardening.md`](docs/github-actions-hardening.md).

`pixi run fast` / `pixi run full` are thin wrappers that call `./test.sh` with
the same flag from inside the pixi environment.
