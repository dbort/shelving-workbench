# Agent Instructions

This repo is developed through a multi-model task pipeline (Planner →
Implementer → Reviewer → human sign-off).

**Canonical pipeline semantics live in `.claude/docs/pipeline.md`** —
phases, branching, `blocked_by`, verification commands, task-file
conventions. Rules there are stated once; this file and the agent/skill
files link to it rather than restating. When pipeline behavior changes,
update `pipeline.md` first, then grep `CLAUDE.md`, `.claude/agents/`,
`.claude/skills/`, and `docs/agent-usage.md` for one-line restatements to
keep in sync.

Doc placement convention: `docs/` is human-facing prose (swept by
`doc-hygiene`); `.claude/docs/` is agent-contract material whose literal
absolutes must never be style-swept.

## Invariants

- Never commit task work directly to `main`; all task work happens on the
  task's `sh-XXX` branch (`pipeline.md` § Git branching).
- Advance a task's phase only via the owning skill — `new-task`,
  `dispatch-tasks`, `approve-task` — never by calling the
  Implementer/Reviewer subagents directly as a shortcut, unless the user
  explicitly says to skip a pipeline step (`pipeline.md` § Phase
  transitions).
- `planning`, `user_signoff`, and `blocked_needs_human` are human gates:
  never auto-advance past one, never reset `review_rejections`.
- One task in flight at a time — all task work shares one working tree.
- Task ids are never reused; allocation scans `tasks/active/`,
  `tasks/completed/`, and `tasks/abandoned/`.

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
`## Frontier Advice`). Skipping one silently is not an option; the
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

## Friction log

When work here forces a workaround — a missing tool or script, data in the
wrong shape, a doc you had to reverse-engineer — log it in
`.claude/docs/friction-log.md` in the same session, even (especially) when
the workaround succeeded. That file is canonical for the entry format and
the fix-and-delete protocol; this section is only the pointer.

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
prose, regardless of any conversational-brevity rules in effect. Distilled
from `doc-hygiene`'s rules (`.claude/skills/doc-hygiene/SKILL.md`; keep the
two in sync):
- Comments explain *why* (non-obvious rationale, tradeoff, constraint) —
  never restate the adjacent code. Do not open a file or function with a
  comment that lists the steps or sections below it; keep the one or two
  non-obvious points, each on the line it explains. Assume an expert
  reader of the language.
- State current behavior as though it has always been this way; no
  reader-memory framing ("works exactly as before", "no longer requires",
  "used to"). A "(see sh-XXX)" pointer stays only when it
  explains *why* otherwise-unusual logic exists, not as a comparison to
  superseded code.
- Doc comments: identifier-first summary line that adds information
  beyond the name. A function or method docstring states the *contract* a
  caller relies on: the return value and any ordering or shape guarantee,
  what it raises, which inputs have no effect, invariants. It does not
  narrate the body step by step ("calls X, then does Y, then returns Z").
  The internal call sequence lives in the code; a maintainer note that
  earns its place goes inline at the line it explains, not in the
  docstring.
- No em-dash asides; use a comma, colon, or separate sentence.
- No filler adverbs (really, simply, actually, crucially...) and no
  marketing fluff (robust, seamless, comprehensive, leverage).
- No throat-clearing openers ("Here is...", "This module acts as...") or
  rhetorical setups ("it's worth noting"). State the thing directly.

**Task files** (`tasks/*/*.md`): dense imperative machine-prose in
`## Frontier Advice`/`## Execution Plan`; plain human prose in
`## Summary`. Defined in `.claude/skills/new-task/SKILL.md` § File
Generation Rules.
