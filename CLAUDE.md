# Agent Instructions

Work is planned, implemented, and reviewed through the task pipeline:
`/new-task` → `/work sh-XXX` → `/ship sh-XXX`. Its rules live in
`.claude/docs/pipeline.md`; skills link there rather than restating them.

Doc placement: `docs/` is human-facing prose, swept by `doc-hygiene`;
`.claude/docs/` is agent-contract material whose absolutes are never
style-swept.

## Invariants

- Never merge into `main`, create a `sh-XXX` branch, or append a review
  verdict unless the user invoked `/work` or `/ship` for that task in this
  conversation. Subagents never do these, whatever the repo's state
  suggests.
- Task work never commits directly to `main` (`pipeline.md` § Git).

## Project conventions

- **Units in the name:** every identifier bound to a numeric quantity
  that has a physical unit carries that unit as a suffix — `_mm` for
  millimetre lengths (`width_mm`, `thickness_mm`, `axis_span_mm`),
  `_mm3` for cubic-millimetre volumes, and so on. This covers dataclass
  fields, function parameters, locals, and any helper whose return value
  is such a quantity (`_effective_thicknesses_mm`, never
  `_effective_thicknesses`). An identifier whose value is a `str` label
  rather than the number itself (`nominal_thickness`) takes no unit
  suffix. There is no dedicated units type; the suffix is the whole
  mechanism. (`docs/architecture.md` states the same rule for the
  split-tree; this is the project-wide form.)

## Standing task-planning obligations

Cross-cutting requirements every new task plan must either satisfy or
explicitly opt out of (with the reason stated in the task's
`## Advice`). Skipping one silently is not an option; the
`new-task` skill checks this list during planning. Add an entry here
whenever a bug reveals a class of work that future tasks keep getting
wrong.

- **Typed Python:** new or changed Python uses precise types. No bare
  `Any`, and no bare `dict`/`list`/`tuple`/`set` in function signatures or
  public attributes; reach for `TypedDict`, `NewType`, `Protocol`,
  generics, `Mapping`/`Sequence`, and `Literal` instead. `Any` is
  allowed only where a boundary genuinely erases the type (parsing
  arbitrary external JSON, a third-party API that is itself untyped), and
  then with a comment saying why. `mypy --strict` over the changed code
  must pass.

- **Shell stays simple:** bash is only for a linear sequence of commands,
  simple conditionals, and thin wrappers (the `tools/run-tests.sh` /
  `tools/lint-workflows.sh` shape). Anything past that — loops that parse
  text, HTTP calls, JSON, retry/backoff, arithmetic beyond trivial,
  arrays or maps used as data structures — is written as typed Python
  under the Typed Python rule above, with its logic in importable
  functions so tests exercise them directly rather than only
  subprocess-driving the script.

<!-- Example shape for future entries:

- **Config parity:** any task adding an env var a deploy-managed service
  reads must wire it into the deploy config, not just the shell.
- **Observability coverage:** any task adding a new class of monitored
  work must add the repo's standard instrumentation for it.
-->

## Friction log and bug log

A workaround forced while developing or testing this repo goes in
`.claude/docs/friction-log.md`; a defect in the workbench on `main` goes in
`.claude/docs/bug-log.md`. Log it in the same session, even when the
workaround succeeded or the bug is fixed at once. Each file defines its
own format and scope.

## Writing style by destination

Different destinations get different writing styles. Match the block below
to where the text is going; never let one destination's rules bleed into
another.

**Interactive replies to the user** (conversation only; nothing persisted):
be brief. Lead with the answer, cut preamble, recaps, hedging, and
unsolicited elaboration — one good paragraph usually beats four. Exception:
interview flows (`new-task`, design questioning) use enough prose to make
each question and its recommended answer clear.

**File content — code comments, docs, commit messages:** normal full
prose, regardless of any conversational-brevity rules in effect. This is
the rule set `doc-hygiene` enforces.
- Comments explain *why* (non-obvious rationale, tradeoff, constraint) —
  never restate the adjacent code. Do not open a file or function with a
  comment that lists the steps or sections below it; keep the one or two
  non-obvious points, each on the line it explains. Assume an expert
  reader of the language.
- State current behavior as though it has always been this way; no
  reader-memory framing ("works exactly as before", "no longer requires",
  "used to") and no mentions of earlier versions. Keep history only when
  it answers "why not X?" or guards against a known regression. A "(see
  sh-XXX)" pointer stays only when it explains *why* otherwise-unusual
  logic exists.
- Doc comments: identifier-first summary line that adds information
  beyond the name. A function or method docstring states the *contract* a
  caller relies on: the return value and any ordering or shape guarantee,
  what it raises, which inputs have no effect, invariants. It does not
  narrate the body step by step. A maintainer note that earns its place
  goes inline at the line it explains. Document each field on its own
  declaration, not in the type's docstring.
- No em-dash asides or ` -- ` dashes; use a comma, colon, or separate
  sentence.
- No filler adverbs (really, simply, actually, crucially, genuinely...)
  unless the word carries scope ("only"), and no marketing fluff (robust,
  seamless, comprehensive, leverage, delve).
- No throat-clearing openers ("Here is...", "This module acts as...") or
  rhetorical setups ("it's worth noting", "here's the thing").
- No formulaic structures: "not X, it's Y" (state Y), listing what
  something is not before what it is, and false agency ("the decision
  emerges") where a real actor or mechanism can be named.
- "Always"/"never"/"every" only for real invariants, not sweeping
  emphasis. A parenthetical holds one short fact; unpack anything longer
  or nested.

**Task files** (`tasks/*/*.md`): dense imperative prose in `## Advice`
and `## Plan`; plain human prose in `## Summary`
(`.claude/skills/new-task/SKILL.md`).
