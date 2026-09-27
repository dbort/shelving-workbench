---
name: new-task
description: Interview the user about a new unit of work and write its tasks/active/sh-XXX task file for the Implementer. Use when the user starts a new task or asks to plan one.
---

# Skill: Task Discovery & File Generator

## Purpose
To interview the human user about a new task request, refine the requirements, and generate a clean, machine-optimized task file inside `tasks/active/` for the Implementer agent to execute. The Implementer reaches the user only through a question relay that halts its run (`.claude/docs/pipeline.md` § Implementer questions), so settle every decision the user owns here.

## Execution Protocol


### Step 1: The In-Depth Interview
Interview the user relentlessly about the task request until reaching a shared understanding — do not stop after a couple of questions. Walk down each branch of the decision tree, resolving ambiguities and the dependencies between decisions one by one, and keep following up within a branch until it's fully resolved before moving to the next. Probe whatever is ambiguous or unstated in *this* request rather than working through a fixed checklist. Spend the questions on what only the user can decide: intended behavior, edge cases, the Must Haves, tradeoffs they care about. Leave file-by-file mechanics to the Implementer, which can work those out from the codebase.

If a question can be answered by exploring the codebase instead of asking the user, explore the codebase first. For each question you do ask, provide your own recommended answer so the user can confirm or correct it rather than starting from a blank page.

### Step 2: File Generation Rules
Once the user provides answers, output the final file. You must follow these machine-routing constraints:
1. **Agent-directed language:** `## Frontier Advice` and `## Execution Plan` are read by the Implementer, not a human skimmer: dense and specific, no tutorial prose. State each constraint plainly with its reason (e.g., instead of "Make sure to handle errors neatly," write "Wrap network JSON decoding in null and error-type guards and return the module's sentinel internal-error value, because callers branch on that sentinel."). Record current decisions, not how the plan reached them: superseded designs and review-round history stay in git and in completed task files.
2. **Strict Step Isolation:** Break the code generation into separate files. Prefer steps where step $N$ does not depend on uncompleted files in step $N+1$. When a change is atomic across files (an interface rename, widening a type/lint gate) and a clean split is impossible, group those steps and place one deferred checkpoint line after the last of them (`.claude/docs/pipeline.md` § Deferred verification) rather than forcing a false split.
3. **Phase Structuring:** Set `current_phase: planning`. Let the user explicitly verify your output before updating the state to `implementation`.
4. **Task ID Allocation:** run `python3 tools/task_status.py` (or `pixi run task-status`) and use its `next_id` field verbatim as this task's `id` — it already scans `tasks/active/`, `tasks/completed/`, and `tasks/abandoned/` (including every local branch's own copy of those directories, so an id already claimed on another branch is never reissued) and zero-pads to match the existing width. Never reuse an id (`.claude/docs/pipeline.md` § Task files and directories).
5. **Blocking Dependencies:** if this task's code or tests genuinely cannot proceed without another still-open task's output (e.g. it imports a package/file that task creates), add `blocked_by: [sh-XXX, ...]` to the frontmatter, listing every such task's id. Hard blockers only — softer recommended-sequencing goes in `## Frontier Advice` prose, and no blocker at all means omitting the field entirely, not `blocked_by: []` (semantics: `pipeline.md` § Task dependencies).
6. **Human-Readable Summary:** unlike `## Frontier Advice`/`## Execution Plan`, `## Summary` is written FOR a human skimmer, not an LLM executor — ordinary clear prose, not an imperative/dense prompt. 1-3 sentences: what the task does and why, adding real information beyond the title (don't just restate the title in sentence form). Goes directly under the `# sh-XXX: Title` heading, before `## Status`.
7. **Standing obligations:** check `CLAUDE.md` § Standing task-planning obligations. Each listed obligation either shapes the plan or gets an explicit opt-out reason in `## Frontier Advice`; silently skipping one is not an option.

---

## Output Blueprint

File name: `tasks/active/sh-XXX-[human-readable-slug].md`

```markdown
---
id: sh-XXX
title: "[Short Task Title]"
current_agent: implementer
current_phase: planning
review_rejections: 0
# blocked_by: [sh-YYY]   # only for a genuine hard blocker — see rule 5 above; omit this line otherwise
---

# sh-XXX: [Short Task Title]

## Summary
[1-3 sentences, plain human-readable prose — see rule 6 above. What this task does and why.]

## Status
- [ ] Planning
- [ ] Implementation
- [ ] Review
- [ ] User sign-off

## Must Have
- [ ] [Strict machine-checkable condition 1]
- [ ] [Strict machine-checkable condition 2]

## Frontier Advice
[Decisions and constraints the Implementer must honor, each with its reason: architectural constraints, library/method choices, error-handling requirements, and codebase facts it would otherwise have to rediscover.]

## Execution Plan
- [ ] **Step 1** (`path/to/...`): [What this step changes and the interfaces/types involved: the outcome, not a keystroke script.]

## Decisions log
```

`## Decisions log` starts empty. It is append-only and filled after planning, by Implementer questions and the user's answers (`.claude/docs/pipeline.md` § Implementer questions).
