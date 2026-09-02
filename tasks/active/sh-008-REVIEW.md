# sh-008 Review — Round 1

**Verdict:** REJECTED

The refactor itself is sound: `pixi run tests` passes end to end in 1.4s on
this branch (lock guard, ruff, ruff format, mypy over 13 sources, vendor-core
check, 63 pytest tests, workflow lint, FreeCAD smoke with the marker line);
`pixi lock --check` reports the lock already up to date; the self-install stays
`- pypi: ./` at all three occurrences; `jsonschema` and `rsync` resolve for both
`linux-64` and `linux-aarch64`; `shelving-workbench`'s `requires_dist` is gone;
`ci.yml` has one job with harden-runner first, SHA-pinned checkout and
setup-pixi, `frozen: true`, `permissions: { contents: read }`, and the top
hardening comment intact; `tools/run-tests.sh` runs the full ordered sequence
under `set -euo pipefail` with the no-arg guard (exit 2), the `command -v
freecadcmd` guard (exit 1), and the sh-007 marker grep, with no
`FAST_TOOLS`/`ensure_on_path`/`run_fast`/`run_full` residue and no tier or
`test.sh` language in its header; `shellcheck tools/run-tests.sh
tools/install-deps.sh tools/lint-workflows.sh tools/vendor-core.sh` is clean;
both acceptance greps in the Must Have return exactly what they should
(`.gitignore:8:.venv/` and nothing else). The `pipeline.md` edits and the six
restatements are wording-only: no agent's or skill's behavior moved, the
`review`/`user_signoff` rows and rejection loop are semantically unchanged, and
`reviewer.md` still says the checks run unconditionally on every review while
`doc-hygiene` Step 5 still runs them.

What blocks approval is that the de-tiering is not finished. The Must Have's
acceptance grep spells the tier words with a space (`fast tier`, `full tier`,
`both tiers`), so the hyphenated and possessive forms slipped through it, and
five live references to a tier split that no longer exists remain in the tree.

## Blocking findings

- **F1: Tier language survives in five places the acceptance grep could not
  see** (`.claude/agents/reviewer.md:27`, `tests/test_layout_demo.py:1`,
  `docs/roadmap.md:66`, `docs/roadmap.md:77`, `docs/architecture.md:279`): the
  final Must Have requires that no doc instruction or code comment still point
  at the old interface, and the tier-sync Must Have names `reviewer.md`
  explicitly. Each hit below still names a construct this branch deletes.
  - `.claude/agents/reviewer.md:27` — "Reason from the diff, the code, and the
    tiers' output". This is inside the very bullet the branch rewrote (the other
    two tier phrases in the same sentence were fixed), and `.claude/` is never
    swept by `doc-hygiene`, so nothing downstream will catch it. Should read
    "the checks' output" or similar.
  - `tests/test_layout_demo.py:1` — `"""Fast-tier coverage of
    ``tools/layout_demo.py``'s run-and-print contract.` The sibling file
    `tests/test_check_lock_paths.py:1` carried the identical opener and was
    correctly updated to "Coverage of ..."; this file was simply absent from
    Step 6's file list.
  - `docs/roadmap.md:66` — "full-tier smoke test asserts plank count and
    bounding box"; `docs/roadmap.md:77` — "full-tier test asserts the reflow".
    The M0 entry was reworded, but these M3/M4 verify lines still instruct a
    reader to run a tier that no longer exists.
  - `docs/architecture.md:279` — "The full CI tier is the early-warning system."
    The "Testing and CI" section was reframed; this line in "Open questions and
    risks" was not.

- **F2: `.github/dependabot.yml`'s header comment documents the deleted `dev`
  extra and the deleted CI fast leg** (`.github/dependabot.yml:2-4`): "The `pip`
  ecosystem below tracks only the pyproject `dev` extra, which feeds the
  FreeCAD-free path and CI's fast leg." After this branch, `pyproject.toml` has
  no `[project.optional-dependencies]` and `ci.yml` has no `fast` job, so the
  comment is false on both counts and is a code comment pointing at the old
  interface (the Must Have's grep missed it only because the file writes "dev
  extra" rather than `[dev]`). This is not a legitimate follow-up: the branch
  already rewrote this sentence's prose counterpart in
  `docs/github-actions-hardening.md:96-97`, so leaving the source file stale
  makes the doc and the file it documents disagree. Rewrite the comment to
  describe what the `pip` ecosystem covers now. Keeping the `pip` entry itself
  is fine (it costs nothing and catches future `[project.dependencies]`); do not
  treat this finding as a request to change Dependabot's configuration.

## Non-blocking notes

- **N1: Friction-log rewording is accepted, but one clause changed tense**
  (`.claude/docs/friction-log.md:33`): the minimal reword (`the dev extra's
  .venv` → `the core virtualenv`, `in the fast tier` → `in the harness`) is the
  right resolution of the conflict between "the entry is otherwise unchanged"
  and the repo-wide grep, and it preserves the papercut, so it is not a Must-Have
  deviation. One nit to fold into whatever round addresses F1/F2: "Neither check
  ran in the harness" reads as though they now do. Present tense ("Neither check
  runs in the harness") keeps the papercut live, which matters because the entry
  is still open and its "Simpler if" is still unimplemented.
- **N2: Nothing runs `shellcheck` over the repo's own shell scripts**
  (`tools/run-tests.sh:36-51`): `tools/lint-workflows.sh` shellchecks only
  `run:` bodies inside `.github/workflows/`, so `tools/run-tests.sh`,
  `tools/install-deps.sh`, `tools/vendor-core.sh`, and `tools/lint-workflows.sh`
  have no durable lint coverage. The Must Have's `shellcheck tools/run-tests.sh
  tools/install-deps.sh` requirement is satisfiable only by a hand-run command
  that leaves no trace, and the branch adds a `# shellcheck disable=SC2016`
  (`tools/install-deps.sh:25-27`) whose correctness nothing re-verifies. Adding a
  `shellcheck tools/*.sh` step to `tools/run-tests.sh` would put it in the one
  command; `shellcheck` is already a `[dependencies]` entry in `pixi.toml`. Fold
  it in here or file it as a follow-up task, but do not leave it implicit.
- **N3: The reworded Dependabot `pip` bullet is in scope and correct**
  (`docs/github-actions-hardening.md:96-97`): rewriting a sentence the task
  rendered factually dead is within Step 9's remit, not scope creep, so no change
  is required on that count. Note only that `pyproject.toml` now declares zero
  runtime dependencies, so "Python dependencies declared in `pyproject.toml`"
  describes an empty set today; a half-sentence saying the entry exists to catch
  dependencies added later would pair well with F2's comment fix.
