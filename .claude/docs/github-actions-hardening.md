# GitHub Actions hardening

Every workflow in `.github/workflows/` follows these rules. They limit the
blast radius of a compromised action, a malicious pull request, or a leaked
token. A change that relaxes one changes this file too and says why in its
commit message.

`tools/lint-workflows.sh` enforces the machine-checkable rules and runs
inside `pixi run tests`. It drives `actionlint` (which needs `shellcheck`
for `run:` bodies), `zizmor --offline --config zizmor.yml`,
`check-jsonschema` against the vendored Dependabot schema, and
`tools/check_action_pins.py`. Any failure fails the run.

## Pin every action to a commit SHA

Every `uses:` names a full 40-hex commit SHA followed by the release it
corresponds to:

```yaml
uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

Tags and branches are mutable; a SHA is not. Resolve the SHA from the
release tag yourself, never from a value pasted from documentation.

`zizmor.yml` sets the `unpinned-uses` policy to `hash-pin`, so a tag or
branch ref fails offline. `check_action_pins.py` fails offline on a
missing or malformed `# vX.Y.Z` comment or an upper-case SHA, and online
resolves each tag through the GitHub API (following annotated tags) and
fails unless it names the pinned commit. Any network failure is fatal;
`pixi run tests -- --offline` is the only way to skip the online check.

A confirmed `zizmor` false positive is silenced inline with `# zizmor:
ignore[<rule>]` and a one-line reason. A genuine finding is fixed, never
suppressed.

## Start with no permissions

Each workflow sets `permissions: {}` at the top level, and each job grants
only the scopes it uses. Only the Scorecard job holds more than `contents:
read`: `security-events: write` and `id-token: write`.

## Never `pull_request_target`

Workflows trigger on `push` and `pull_request` only. `pull_request_target`
runs with a read-write token and secrets while checking out untrusted code.

## Never interpolate event context into shell

No `run:` body contains `${{ github.event.* }}` or any other
attacker-controllable expression, because it is substituted before the
shell parses the line. Pass it through `env:` and quote the variable:

```yaml
- env:
    TITLE: ${{ github.event.pull_request.title }}
  run: echo "$TITLE"
```

## Pinned runner, harden-runner first

`runs-on` names a dated image (`ubuntu-24.04`), never `ubuntu-latest`, so
an OS upgrade is never an unplanned side effect of an unrelated push.
`step-security/harden-runner` with `egress-policy: audit` is the first step
of every job, building the baseline for a later move to `block`.

`ci.yml` cancels a branch's in-flight run on a new push (`concurrency`
keyed on workflow and ref).

## Dependency updates

`.github/dependabot.yml` proposes weekly SHA bumps for `github-actions`
and watches `pip` for anything later added to `[project.dependencies]`.
Dependabot cannot read pixi, so `pixi.lock` is refreshed by hand with
`pixi update`.

`.github/workflows/scorecard.yml` runs OpenSSF Scorecard weekly and on
push to `main`. A dropping score is a regression to investigate.
