# sh-027 Review — Round 2

**Verdict:** REJECTED

Round 1's three blocking findings are all fixed on `d666f0f`:
`.claude/agents/implementer.md` no longer carries the `tools/vendor-core.sh`
constraint, `.claude/skills/new-task/SKILL.md:26` no longer forbids authoring a
vendor step, `.claude/docs/pipeline.md:27-30` now describes the checks as the
`freecad.shelving.core` unit suite plus the `pixi.lock` path guard (matching
`README.md`), `README.md` names `freecad.shelving.core` throughout the intro
and Glossary, and `freecad/shelving/default_catalog.py:4-6` drops "vendored
core". Round 1's N1 is fixed too: the empty `shelving_core/` directory is gone
from the working tree.

The repo-wide grep is clean. `git grep -n 'shelving_core\|shelving\.vendor\|
vendor-core'` outside `tasks/`, `pixi.lock`, and the three deliberately frozen
documents returns only `.claude/docs/friction-log.md:122` and `:126`, both
inside `friction-009`'s narrative of a past event, which is a historical record
and correctly left alone (same reasoning as round 1's N2 on `docs/roadmap.md`).

`pixi run tests` is green on the branch tip (exit 0; 173 passed, ruff, `mypy
--strict` over `freecad/`, `tools/`, `tests/`, the workflow lint, and the 9
`freecadcmd` smoke tests). The move itself, the packaging retarget, and the
`pixi.lock` regeneration that drops `rsync`/`popt`/`xxhash` all remain correct.

On the friction-013 fix specifically: `pixi.toml:7-16`'s `[activation.env]` is
valid pixi manifest syntax and sensibly placed (workspace level, before
`[dependencies]`), `tools/layout_demo.py:27-36`'s defensive unconditional
`sys.path.insert` is correctly retained, and the `friction-013` entry is
deleted from `.claude/docs/friction-log.md` with `next_id: friction-014` left
intact, so the id is retired rather than reused. What blocks approval is that
the fix itself has no test, and that two comments now describe a resolution
mechanism the file's own new comment contradicts.

## Blocking findings

- **F1: the friction-013 `PYTHONPATH` fix has no automated coverage; deleting
  it would leave `pixi run tests` green** (`pixi.toml:7-16`): nothing in the
  checks exercises the path this setting controls. Every route the suite takes
  into this checkout's `freecad` package already has its own independent
  mechanism: `pytest freecad/shelving/core tests` gets the repo root at
  `sys.path[0]` from pytest's own rootdir insertion (`freecad/__init__.py` and
  every directory below it have `__init__.py`, so prepend import mode walks up
  to the repo root), `tests/test_layout_demo.py:26-31` subprocesses a script
  that carries its own `sys.path.insert` (`tools/layout_demo.py:35-36`), and
  `tools/freecad_scan_smoke.py:44-47` carries its own guard plus an
  `extend_path` call. So the evidence is that commenting out `PYTHONPATH` —
  or typo-ing the variable name, or having pixi not expand
  `$PIXI_PROJECT_ROOT` at all and export it literally — produces an identical
  all-green run, which means the checks cannot currently distinguish the fix
  working from the fix being absent. The commit message for `d666f0f` states
  the fix was "Verified with `pixi run tests` and by running
  `tools/layout_demo.py` directly", and neither of those observations can
  actually separate the two cases; the second also leaves no trace for a
  future author to re-run. Add a durable test inside `pixi run tests` that
  asserts the environment setting does its job: a subprocess test (a new
  `tests/test_pixi_env_pythonpath.py`, alongside the existing
  `tests/test_layout_demo.py` subprocess pattern) that runs `sys.executable
  -c "import freecad.shelving.core.layout as m; print(m.__file__)"` with `cwd`
  set to a `tmp_path` outside the checkout and no per-script shim in play, and
  asserts the printed path resolves under the repo root. With the activation
  env working, the child inherits `PYTHONPATH` and resolves this checkout;
  without it, the child's `sys.path` starts at its own cwd and reaches
  site-packages first, where the conda `freecad` package has no `shelving`
  subpackage, so the import fails. That is the assertion the fix is making and
  the one no committed test makes today.

- **F2: two comments still credit the editable install with a resolution the
  same file now says it cannot provide** (`pixi.toml:42-44`, `README.md:43-45`):
  `pixi.toml:42-44` reads "The project installs itself editable so `import
  freecad.shelving.core` resolves to the checkout under `pixi run` / `pixi
  shell` with no per-script sys.path shim." That is contradicted twice over by
  this branch: `pixi.toml:10-12`, eleven lines above it, states that the
  editable install's `.pth` "only appends the repo root to sys.path, well after
  site-packages, so without this the conda package wins the race", and
  `tools/layout_demo.py:35-36` is exactly the per-script `sys.path` shim the
  comment says is unnecessary. `README.md:43-45` carries the same wrong
  mechanism to the human-facing side: "`pixi run` and `pixi shell` then work
  from the checkout, putting `freecad` (this checkout's namespace package) on
  the import path via the editable install" — the editable install puts it on
  the path, but at the back, where it loses; what makes `pixi run` work is the
  activation `PYTHONPATH`. This is the same class of finding as round 1's F1-F3
  (live prose asserting a mechanism the code no longer relies on), and both
  lines are in files this round already edits. State the current mechanism
  directly: the editable install registers the project, and the activation
  `PYTHONPATH` is what puts the checkout ahead of the conda environment's
  same-named package.

## Non-blocking notes

- **N1: `sys.path[1]` is not where the repo root lands for a script
  invocation** (`pixi.toml:12-13`): "Prepending PYTHONPATH puts the repo root
  at sys.path[1] (right after the empty cwd entry)" holds for `python -c` and
  `python -m`, but for `python tools/layout_demo.py` — the invocation that
  motivated the fix — `sys.path[0]` is the script's own directory (`tools/`),
  not an empty cwd entry. The load-bearing claim, that the repo root lands
  ahead of site-packages, is right either way; drop the parenthetical or say
  "ahead of site-packages" and leave the index out.

- **N2: `docs/manual-qa.md:51-52` reads backwards** (carried from round 1's
  N4, unaddressed): "which needs `freecad/` on `sys.path` as a namespace
  package" — what goes on `sys.path` is the directory *containing* `freecad/`,
  namely the repo root, which is also the actual reason the whole repo gets
  linked. The note's conclusion is correct; the one clause inverts the
  relationship.

- **N3: `tools/freecad_scan_smoke.py:44-46`'s `if _REPO_ROOT not in sys.path`
  guard is now dead under `pixi run`** (carried from round 1's N3): with the
  activation `PYTHONPATH` in place, the repo root is already in `sys.path` for
  any `freecadcmd` invocation inside the environment, so the insert never
  fires — harmless, since `PYTHONPATH` supplies the same entry earlier, but it
  now sits in the file as the exact pattern `friction-013` was written to warn
  about, with nothing at the call site saying why it is safe here.
