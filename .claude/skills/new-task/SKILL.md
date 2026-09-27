---
name: new-task
description: Interview the user about a new unit of work and write its tasks/active/sh-XXX task file. Use when the user starts a new task or asks to plan one.
---

# New task

Pipeline rules: `.claude/docs/pipeline.md`.

1. **Interview** the user the way `/grill-me` does: branch by branch until
   shared understanding, a recommended answer with every question, and
   the codebase explored instead of asked wherever it can answer. Spend
   questions on what only the user decides: behavior, edge cases, Must
   Haves, tradeoffs. Leave file-level mechanics to `/work`.
2. **Check** `CLAUDE.md` § Standing task-planning obligations. Each one
   shapes the plan or gets an opt-out reason in `## Advice`.
3. **Write** `tasks/active/sh-XXX-<slug>.md` with the id from
   `pixi run task-status -- --next-id`, using the template below.
4. **Roadmap:** if the task delivers a `docs/roadmap.md` milestone, set
   that milestone's Status (or split checklist) as `docs/roadmap.md`
   § Status legend describes.
5. **Commit** the task file and any roadmap edit to `main` (`sh-XXX: plan
   <title>`), show the file to the user, and stop. The user starts the work
   with `/work sh-XXX`.

Writing rules: `## Summary` is plain prose for a human skimmer and adds
information beyond the title. `## Advice` and `## Plan` are dense and
imperative, for an agent: each constraint with its reason, current
decisions only, no history. Must Haves are machine-checkable ("returns
HTTP 429 on rate limit", not "handles errors well"). Plan steps state
outcomes and interfaces, not keystrokes.

```markdown
---
id: sh-XXX
title: "Short title"
# blocked_by: [sh-YYY]   # hard blockers only; omit otherwise
---

# sh-XXX: Short title

## Summary
1-3 sentences: what the task does and why.

## Must Have
- [ ] Machine-checkable condition.

## Advice
Decisions and constraints the implementer must honor, each with its reason.

## Plan
- [ ] **Step 1** (`path/to/file`): outcome and interfaces involved.

## Review log
```
