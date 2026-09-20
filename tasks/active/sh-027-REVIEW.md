# sh-027 Review — Round 1

**Verdict:** REJECTED

The move itself is clean and `pixi run tests` is green on `d29f2b8` (exit 0;
173 passed, mypy strict over all 38 files under `freecad/`, `tools/`,
`tests/`, plus the 9 `freecadcmd` smoke tests). The package now lives at
`freecad/shelving/core/` with fully-qualified intra-package imports and no
relative ones, `test_relative_intra_package_imports.py` is gone,
`test_no_freecad.py` is retargeted, `freecad/shelving/vendor/` and
`tools/vendor-core.sh` are gone, and the packaging/mypy retargeting is
correct. The `tools/layout_demo.py` `sys.path` pin is also correct and,
contrary to the Frontier Advice's worry that only a hand-run would catch it,
it is genuinely covered by an existing automated check: `tests/test_layout_demo.py`
runs the script as a subprocess under `sys.executable` from the repo root and
asserts exit 0, which is exactly the invocation shape that would fail if the
conda environment's `freecad` package shadowed this checkout's. That test is
in `pixi run tests` via `pytest freecad/shelving/core tests`, so friction-013's
regression has durable coverage; no new test is needed for it.

What blocks approval is residue: the task deleted the vendoring concept from
the code but left live prose in three places still asserting it, including an
agent-contract file that will misdirect the next Implementer.

## Blocking findings

- **F1: agent-contract files still instruct running the deleted
  `tools/vendor-core.sh`** (`.claude/agents/implementer.md:25`,
  `.claude/skills/new-task/SKILL.md:26`, `.claude/docs/pipeline.md:27-28`):
  `implementer.md:25` is a standing Constraint telling every future
  Implementer "After any step that edits `shelving_core/`, run
  `tools/vendor-core.sh` (no `--check`) and `git add freecad/shelving/vendor/`
  before running the checks — the `vendor-core.sh --check` drift gate in
  `pixi run tests` stays red until the vendored copy is re-synced." All four
  named things (`shelving_core/`, the script, the vendor dir, the drift gate)
  were deleted by this branch, so the next task's Implementer is directed to
  run a nonexistent script and `git add` a nonexistent path.
  `new-task/SKILL.md:26` restates it for the Planner ("Do not author a
  `tools/vendor-core.sh` step: the Implementer re-syncs the vendored core
  after every step that edits `shelving_core/`"). `pipeline.md:27-28` still
  describes what `pixi run tests` covers as "static analysis, the
  `shelving_core` unit suite, repository-consistency checks, ..." — the
  package is no longer named that and the plural "checks" counted the drift
  gate that is now gone (`README.md` was already corrected to "the `pixi.lock`
  path guard" in this same diff, so the two now disagree). `CLAUDE.md` makes
  this sync mandatory, not optional: "When pipeline behavior changes, update
  `pipeline.md` first, then grep `CLAUDE.md`, `.claude/agents/`,
  `.claude/skills/`, and `docs/agent-usage.md` for one-line restatements to
  keep in sync." Removing a step from the repo's single check command is such
  a change. (`docs/agent-usage.md` and the `doc-hygiene` skill are already
  clean; only these three need edits.)

- **F2: `README.md` still presents the layout core as `shelving_core`**
  (`README.md:11`, `README.md:64`, `README.md:67`, `README.md:102`): line 11's
  intro says "The layout math lives in a pure-Python core (`shelving_core`)";
  the Glossary header at line 64 says the vocabulary maps "onto the code in
  `shelving_core`", and lines 67 and 102 cite `Unit` in `shelving_core.layout`
  and `Catalog` in `shelving_core.materials`. None of those import paths
  resolve after this branch. `README.md` is live human-facing documentation
  describing current code, and this task already edits it (the Tests section),
  so it is in scope; the Must Have's explicit freeze applies only to
  `docs/architecture.md` and `docs/parametric-model-evaluation.md`, both of
  which were correctly left alone.

- **F3: `freecad/shelving/default_catalog.py:4` still says "vendored core"**:
  the module docstring reads "Standard library plus vendored core only", one
  line above the import this branch rewrote to
  `from freecad.shelving.core.materials import ...`. There is no vendored core
  any more, and per `CLAUDE.md` § Writing style the sentence should state
  current behavior directly (the core is a sibling package under
  `freecad/shelving/`).

## Non-blocking notes

- **N1: an empty `shelving_core/` directory is left behind in the working
  tree** (repo root): `git ls-files shelving_core` is empty and
  `git status --porcelain` is clean, so this is not in the diff and a fresh
  clone will not have it — but it is present locally after the `git mv` and,
  being an empty directory on `sys.path`'s repo root, it makes a bare
  `import shelving_core` succeed as an empty namespace package during local
  runs. Worth `rmdir`-ing so a stale import fails loudly instead of half-way.

- **N2: `docs/roadmap.md` M1/M2 entries still name `shelving_core.layout`,
  `shelving_core.solver`, `shelving_core.materials`, `shelving_core.expand`**
  (`docs/roadmap.md:74`, `:86`, `:88`, `:91`): these sit under **Status: Done**
  milestone descriptions, so leaving them as a record of what shipped is
  defensible on the same reasoning the Must Have gives for freezing
  `docs/architecture.md`. Fold in only if you disagree with that reading; do
  not touch the forward-looking M6-M8 sections, which are already clean.

- **N3: `tools/freecad_scan_smoke.py:44-46` keeps the
  `if _REPO_ROOT not in sys.path` guard that friction-013 identifies as a
  trap**: it is correct there (`freecadcmd` runs without the editable
  install's `.pth`, so the guard fires), but nothing at the call site says so,
  and the next reader who copies it pays friction-013 again. One inline line
  explaining why the membership check is safe under `freecadcmd` specifically,
  or dropping the guard for consistency with `layout_demo.py`, would close it.

- **N4: `docs/manual-qa.md:49-52` says the core "needs `freecad/` on
  `sys.path` as a namespace package"**: what has to be on `sys.path` is the
  directory *containing* `freecad/`, which is the repo root, and that is also
  the actual reason the whole repo gets linked. The note's conclusion is
  right; the one clause reads backwards.
