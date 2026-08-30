---
id: sh-001
title: "Scaffold shelving-workbench monorepo (M0)"
current_agent: user
current_phase: user_signoff
review_rejections: 0
---

# sh-001: Scaffold shelving-workbench monorepo (M0)

## Summary
Stand up the empty project skeleton for the Shelving Workbench: a pure-Python
`shelving_core` package, a FreeCAD 1.0 namespace-package workbench that vendors a
synced copy of that core, the `test.sh` two-tier harness, and GitHub Actions CI.
No domain logic ships in this task; it exists so every later milestone starts
from a repo that lints, type-checks, tests, and loads in FreeCAD.

## Status
- [x] Planning
- [x] Implementation
- [x] Review
- [ ] User sign-off

## Must Have
- [x] `./test.sh --fast` exits 0 and runs, in order: `ruff check .`, `ruff format --check .`, `mypy` (strict, `shelving_core` only), the vendor-drift check, `pytest`.
- [x] `./test.sh --full` exits non-zero with a clear message when `freecadcmd` is not on `PATH`; when it is present, it runs a `freecadcmd` script that imports `freecad.shelving` and the vendored core and exits 0.
- [x] `ruff check .` and `ruff format --check .` report no issues.
- [x] `mypy` in strict mode over `shelving_core` reports no errors; `freecad/` is excluded from type-checking.
- [x] `pytest` collects at least two tests and all pass.
- [x] No file under `shelving_core/` contains `import FreeCAD`, `from FreeCAD`, `import FreeCADGui`, or `from FreeCADGui`; a pytest asserts this by scanning source and by importing every `shelving_core` submodule and checking `FreeCAD`/`FreeCADGui` never entered `sys.modules`.
- [x] `freecad/shelving/vendor/shelving_core/` exists and its contents byte-match `shelving_core/` with `tests/` and `__pycache__/` excluded; `tools/vendor-core.sh` regenerates it and a drift-check step (used by `--fast`) fails when it is stale.
- [x] `freecad/shelving/__init__.py` and `freecad/shelving/init_gui.py` exist; `init_gui.py` defines a `Gui.Workbench` subclass (`MenuText`, `ToolTip`, `Icon`, `Initialize`, `GetClassName` returning `"Gui::PythonWorkbench"`) and calls `Gui.addWorkbench(...)`, guarded so module import under `freecadcmd` (no GUI) does not raise.
- [x] `package.xml` is valid XML, Addon Manager `content` type `workbench`, `name` Shelving, `version` 0.0.1, `maintainer` email `freecad@dbort.com`, `license` MIT, repository url `https://github.com/dbort/shelving-workbench`, and declares `freecadmin` 1.0.
- [x] `LICENSE` is the MIT license text, holder `Dave Bort`, year 2026; `pyproject.toml` license and author metadata match.
- [x] `pyproject.toml` sets `requires-python = ">=3.11"`, builds `shelving_core`, and defines a `dev` extra with `ruff`, `mypy`, `pytest`.
- [x] `README.md` documents the dev setup (`pip install -e .[dev]`, `./test.sh --fast`) and an explicit `freecadcmd` (FreeCAD 1.0+) dependency for `./test.sh --full`, with a link to FreeCAD install instructions.
- [x] `.github/workflows/ci.yml` defines two jobs: one runs `./test.sh --fast` on a plain Python 3.11 setup; the other installs FreeCAD 1.0 from conda-forge (providing `freecadcmd`) and runs `./test.sh --full`.
- [x] No `ShelvingUnit`, solver, expansion, catalog, or task-panel code exists anywhere in the tree.
- [x] `docs/roadmap.md` M0 **Status** line still reads `Task sh-001`; this task does not flip it to `Done` (that happens at merge).

## Frontier Advice

CRITICAL scope guard: this task creates STRUCTURE ONLY. Do not implement the
split-tree, spacing solver, carcass expansion, material catalog, scripted
objects, or the 2.5D editor. Any Python module you add under `shelving_core/`
beyond `__init__.py` must be empty of domain logic. If a step seems to call for
domain code, stop: it is out of scope for M0.

Target: FreeCAD 1.0+, PySide6, Python 3.11+. Single root `pyproject.toml`,
`hatchling` build backend, one distributed package `shelving_core`. Add
`shelving_core/py.typed`.

`shelving_core` PURITY: the package must never import FreeCAD. This is the
project's core invariant and is enforced by a test in this task. Do not add a
convenience shim that imports FreeCAD conditionally. The test scans every `.py`
under `shelving_core/` for the four import forms listed in Must Have AND imports
each submodule then asserts `"FreeCAD" not in sys.modules and "FreeCADGui" not in
sys.modules`.

VENDORING: source of truth is top-level `shelving_core/`. `tools/vendor-core.sh`
copies it to `freecad/shelving/vendor/shelving_core/`, excluding `tests/` and
`__pycache__/`. Implement the drift check as: re-run the copy into a temp
directory and `diff -r` against the committed vendored tree; non-empty diff =
exit 1 with a message telling the developer to run `tools/vendor-core.sh` and
commit. Wire this check into `--fast` BEFORE `pytest`. The workbench imports the
core as `from freecad.shelving.vendor import shelving_core` (or equivalent
relative import); it must not add the repo root or top-level `shelving_core/` to
`sys.path`.

`test.sh`: must start with `set -euo pipefail`, accept exactly one of `--fast`
or `--full`, and error on anything else. `--fast` runs the five steps in the
Must Have order; a non-zero from any step fails the tier immediately (pipefail +
explicit checks). `--full` first checks `command -v freecadcmd`; if absent, print
`ERROR: freecadcmd not found on PATH. FreeCAD 1.0+ is required for the full test
tier; see README.md.` and `exit 1`. If present, run
`freecadcmd <path-to-smoke-script>` where the smoke script does
`import freecad.shelving` and `from freecad.shelving.vendor import shelving_core`
and prints an OK line; `freecadcmd` propagates a non-zero exit on ImportError.
Do NOT make `--full` skip gracefully: hard-fail is the chosen behavior (the
review and CI environments are expected to provide `freecadcmd`; see README).

`init_gui.py`: `freecadcmd` runs headless and does not execute `InitGui` logic
automatically, and `FreeCADGui` is unavailable there. Structure the module so
that `import freecad.shelving.init_gui` under `freecadcmd` does not raise: guard
the `Gui.addWorkbench(...)` call and any `FreeCADGui` access behind a
`try: import FreeCADGui as Gui except ImportError: Gui = None` and an
`if Gui is not None:` block, or equivalent. The full-tier smoke test only needs
`import freecad.shelving` to succeed; importing `init_gui` is not required but
must not crash if it happens.

CI: `.github/workflows/ci.yml`. Job `fast`: `actions/setup-python` at 3.11,
`pip install -e .[dev]`, `./test.sh --fast`. Job `full`: use
`mamba-org/setup-micromamba` (or `conda-incubator/setup-miniconda`) to install
`freecad=1.0.*` from `conda-forge` so `freecadcmd` is on `PATH`, then
`pip install -e .` and `./test.sh --full`. Pin action versions to a released
major.

`package.xml`: follow the FreeCAD Addon Manager `package.xml` schema
(`xmlns="https://wiki.freecad.org/Package_Metadata"`, `format="1"`). Include
`content/workbench` with `classname`, `subdirectory` `freecad/shelving/`, and an
`icon` path (a placeholder SVG under `freecad/shelving/resources/` is fine).
Include `url` entries for `repository` and `bugtracker`, and
`<freecadmin>1.0</freecadmin>`.

`ruff`: configure in `pyproject.toml` (`[tool.ruff]`), target `py311`, a small
sensible rule set (`E`, `F`, `I`, `UP`, `B`). `ruff format` owns formatting.
`mypy`: `[tool.mypy]`, `strict = true`, `files = ["shelving_core"]`,
`exclude = ["freecad/"]`.

CLAUDE.md § Standing task-planning obligations lists no active entries; nothing
to satisfy or opt out of here.

Friction log: if the FreeCAD conda-forge package name, the `freecadcmd` entry
point, or the `package.xml` schema differ from what is stated here, fix the code
to reality and record the correction in `.claude/docs/friction-log.md` per
CLAUDE.md.

## Execution Plan

- [x] **Step 1** (`pyproject.toml`, `LICENSE`, `README.md`, `.gitignore`): Create root project metadata. `pyproject.toml`: `hatchling` backend, `[project]` with `name = "shelving-workbench"`, `version = "0.0.1"`, `requires-python = ">=3.11"`, author `Dave Bort <freecad@dbort.com>`, `license = {text = "MIT"}`, `[project.optional-dependencies] dev = ["ruff", "mypy", "pytest"]`, `[tool.hatch.build.targets.wheel] packages = ["shelving_core"]`, plus `[tool.ruff]` (target `py311`, select `E`,`F`,`I`,`UP`,`B`) and `[tool.mypy]` (`strict = true`, `files = ["shelving_core"]`, `exclude = ["freecad/"]`). `LICENSE`: MIT text, `Copyright (c) 2026 Dave Bort`. `README.md`: one-paragraph project intro linking `docs/architecture.md` and `docs/roadmap.md`; a Development section (`pip install -e .[dev]`, `./test.sh --fast`); a Dependencies section stating `./test.sh --full` requires `freecadcmd` from FreeCAD 1.0+ with a link to `https://www.freecad.org/downloads.php` and a note that conda-forge `freecad` also provides it. `.gitignore`: standard Python (`__pycache__/`, `*.egg-info/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `dist/`, `build/`, `.venv/`).

- [x] **Step 2** (`shelving_core/__init__.py`, `shelving_core/py.typed`, `shelving_core/tests/__init__.py`, `shelving_core/tests/test_smoke.py`, `shelving_core/tests/test_no_freecad.py`): `__init__.py` sets `__version__ = "0.0.1"` and a module docstring stating the no-FreeCAD invariant; no other logic. Add empty `py.typed`. `test_smoke.py`: `import shelving_core` and assert `shelving_core.__version__` is a non-empty `str`. `test_no_freecad.py`: (a) walk every `*.py` under the `shelving_core` package directory and assert none contains `import FreeCAD`, `from FreeCAD`, `import FreeCADGui`, or `from FreeCADGui`; (b) `importlib.import_module` every submodule found by `pkgutil.walk_packages`, then assert `"FreeCAD" not in sys.modules` and `"FreeCADGui" not in sys.modules`.

- [x] **Step 3** (`freecad/__init__.py`, `freecad/shelving/__init__.py`, `freecad/shelving/init_gui.py`, `freecad/shelving/resources/shelving.svg`): `freecad/__init__.py` and `freecad/shelving/__init__.py` make importable packages (the latter with a docstring; no logic). `init_gui.py`: `try: import FreeCADGui as Gui / except ImportError: Gui = None`; define `class ShelvingWorkbench(Gui.Workbench if Gui else object)` with class attrs `MenuText = "Shelving"`, `ToolTip = "Parametric shelving layout"`, `Icon` pointing at the resources SVG, methods `Initialize(self)` (pass), `Activated`/`Deactivated` (pass), `GetClassName(self)` returning `"Gui::PythonWorkbench"`; then `if Gui is not None: Gui.addWorkbench(ShelvingWorkbench())`. `shelving.svg`: minimal placeholder icon.

- [x] **Step 4** (`tools/vendor-core.sh`, `freecad/shelving/vendor/__init__.py`, `freecad/shelving/vendor/shelving_core/**`): `vendor-core.sh` starts `set -euo pipefail`, resolves repo root, removes `freecad/shelving/vendor/shelving_core/`, and copies `shelving_core/` into it excluding `tests/` and `__pycache__/` (`rsync -a --delete --exclude tests --exclude __pycache__` or `find`+`cp`). Add `--check` mode: copy into a `mktemp -d` and `diff -r` against the committed tree; on any diff, print the "run tools/vendor-core.sh and commit" message and `exit 1`. Run the script once to generate the committed vendored tree. Add `freecad/shelving/vendor/__init__.py`.

- [x] **Step 5** (`test.sh`, `tools/freecad_smoke.py`): Replace the placeholder `test.sh`. `set -euo pipefail`; parse `$1` as `--fast` | `--full`, else print usage and `exit 2`. `--fast`: run `ruff check .`, `ruff format --check .`, `mypy`, `bash tools/vendor-core.sh --check`, `pytest shelving_core`, in that order, each failure aborting. `--full`: `command -v freecadcmd >/dev/null || { echo "ERROR: freecadcmd not found on PATH. FreeCAD 1.0+ is required for the full test tier; see README.md."; exit 1; }` then `freecadcmd tools/freecad_smoke.py`. `tools/freecad_smoke.py`: `import freecad.shelving`, `from freecad.shelving.vendor import shelving_core`, `print("shelving workbench import OK")`.

- [x] **Step 6** (`package.xml`): Author the Addon Manager metadata per the schema referenced in Frontier Advice: `name` Shelving, `version` 0.0.1, `description`, `maintainer` `Dave Bort` / `freecad@dbort.com`, `license` MIT (file `LICENSE`), `url` `repository` `https://github.com/dbort/shelving-workbench` and a `bugtracker` url, `content/workbench` with `classname` `ShelvingWorkbench`, `subdirectory` `freecad/shelving/`, `icon` `freecad/shelving/resources/shelving.svg`, and `<freecadmin>1.0</freecadmin>`.

- [x] **Step 7** (`.github/workflows/ci.yml`): Two jobs on `push` and `pull_request`. `fast`: checkout, `actions/setup-python` 3.11, `pip install -e .[dev]`, `./test.sh --fast`. `full`: checkout, `mamba-org/setup-micromamba` installing `freecad=1.0.*` and `python=3.11` from `conda-forge`, `pip install -e .`, `./test.sh --full` (run inside the micromamba shell so `freecadcmd` is on `PATH`). Pin action versions.

- [x] **Step 8** (`docs/roadmap.md`): Verify the M0 **Status** line reads `Task sh-001` and leave it unchanged. Do not set it to `Done` — `approve-task` makes that flip when the branch merges to `main`.
