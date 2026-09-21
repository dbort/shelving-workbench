# Skill: Task Discovery & File Generator

## Purpose
To interview the human user about a new task request, refine the requirements, and generate a clean, machine-optimized task file inside `tasks/active/` for a simpler implementation model to execute.

## Execution Protocol


### Step 1: The In-Depth Interview
Interview the user relentlessly about the task request until reaching a shared understanding — do not stop after a couple of questions. Walk down each branch of the decision tree, resolving ambiguities and the dependencies between decisions one by one, and keep following up within a branch until it's fully resolved before moving to the next. Don't confine the interview to a fixed checklist — probe whatever is genuinely ambiguous or unstated in *this* request, whatever category it falls into. Depending on the task, that might include things like:
- Edge cases or error conditions (e.g., "What happens if the API times out?").
- User-facing surface mechanics (CLI flags, UI affordances, API shapes — whatever this repo exposes).
- Target data/resources involved (schemas, external service contracts, file formats).
- Build, test, or deploy tooling (scripts, containers, CI, test harnesses).
- Configuration, environment variables, or local/prod parity concerns.
- Networking, infra, or deployment-environment quirks.
- Localization/i18n or other cross-cutting plumbing.

These are illustrative, not exhaustive — follow the task's actual shape rather than this list.

If a question can be answered by exploring the codebase instead of asking the user, explore the codebase first. For each question you do ask, provide your own recommended answer so the user can confirm or correct it rather than starting from a blank page.

### Step 2: File Generation Rules
Once the user provides answers, output the final file. You must follow these machine-routing constraints:
1. **Agent-Optimized Language:** Do *not* write descriptive, human-friendly tutorial prose in `## Frontier Advice` or `## Execution Plan`. Instead, write dense, imperative, constraint-focused prompts designed for an LLM (e.g., instead of "Make sure to handle errors neatly," write "CRITICAL: Wrap all network JSON decoding in explicit null and error-type guards. Return the module's sentinel internal-error value on fallback.").
2. **Strict Step Isolation:** Break the code generation into separate files. Prefer steps where step $N$ does not depend on uncompleted files in step $N+1$. When a change is atomic across files (an interface rename, widening a type/lint gate) and a clean split is impossible, group those steps and place one deferred checkpoint line after the last of them (`.claude/docs/pipeline.md` § Deferred verification) rather than forcing a false split.
3. **Phase Structuring:** Set `current_phase: planning`. Let the user explicitly verify your output before updating the state to `implementation`.
4. **Task ID Allocation:** `id` must be the next integer unused across `tasks/active/`, `tasks/completed/`, and `tasks/abandoned/` — list all three directories and pick one past the highest existing `sh-XXX`, zero-padded to match the existing width. Never reuse an id (`.claude/docs/pipeline.md` § Task files and directories).
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
[Dense context injector for the simple model. Include strict architectural constraints, library-specific method choices, error-handling requirements, and anti-hallucination guardrails.]

## Execution Plan
- [ ] **Step 1** (`path/to/...`): [Imperative prompt to the simple model detailing exactly what interfaces/types to build or alter. No conversational fluff.]
```
