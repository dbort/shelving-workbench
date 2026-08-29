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

<!-- TODO: Replace with the constraints every implementation and review agent
enforces. Aim for the same shape as these examples (each a checkable
rule, not a vibe):

- **No swallowed errors:** every error handled or returned explicitly.
- **Context/cancellation awareness:** every network or DB request
  respects the caller-provided cancellation mechanism.
- **Clean interface mocking:** external APIs consumed through interfaces
  the tests can stub without live endpoints.
-->

## Standing task-planning obligations

Cross-cutting requirements every new task plan must either satisfy or
explicitly opt out of (with the reason stated in the task's
`## Frontier Advice`). Skipping one silently is not an option; the
`new-task` skill checks this list during planning. Add an entry here
whenever a bug reveals a class of work that future tasks keep getting
wrong.

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
  never restate the adjacent code.
- State current behavior as though it has always been this way; no
  reader-memory framing ("works exactly as before", "no longer requires",
  "used to"). A "(see sh-XXX)" pointer stays only when it
  explains *why* otherwise-unusual logic exists, not as a comparison to
  superseded code.
- Doc comments: identifier-first summary line that adds information
  beyond the name.
- No em-dash asides; use a comma, colon, or separate sentence.
- No filler adverbs (really, simply, actually, crucially...) and no
  marketing fluff (robust, seamless, comprehensive, leverage).
- No throat-clearing openers ("Here is...", "This module acts as...") or
  rhetorical setups ("it's worth noting"). State the thing directly.

**Task files** (`tasks/*/*.md`): dense imperative machine-prose in
`## Frontier Advice`/`## Execution Plan`; plain human prose in
`## Summary`. Defined in `.claude/skills/new-task/SKILL.md` § File
Generation Rules.
