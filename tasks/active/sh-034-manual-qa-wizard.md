---
id: sh-034
title: "A manual QA wizard"
---

# sh-034: A manual QA wizard

## Summary
A dockable QA Wizard panel in FreeCAD walks a person through the manual QA
cases one step at a time. Buttons put the document into each case's
starting state, so there's no code to paste into the console, and Pass,
Fail or Skip plus a comment record each step. At the end, one Copy button
gives a JSON report, with the Report view output of every step, to paste
into an LLM session. The cases move from prose in `docs/manual-qa.md` into
TOML files the wizard reads, and the wizard is on by default for now
behind a developer flag that the planned preferences page will expose.

## Must Have
- [ ] `pixi run tests` green.
- [ ] Every case now in `docs/manual-qa.md` (Scan, export and a refusal; a
      board moved within the joint clearance; a document opening without
      the workbench; one editing session; dimensions; objects this
      workbench did not create; unit size controls) exists as a case in a
      TOML file under `freecad/Shelving/qa/cases/`. `docs/manual-qa.md`
      holds no case steps and no ```` ```python ```` block: only what
      manual QA is for and how to run the wizard.
- [ ] In the core-free suite, every case file loads into typed case
      records; case and step ids are unique; every setup action and check
      a case names exists in the registry, and every registered action and
      check is named by some case. A test fails on each of those.
- [ ] Every setup action that needs no GUI runs without error on a fresh
      document in `tests/freecad/`; every action that needs the GUI runs
      without error in `tests/freecad_gui/`.
- [ ] Building the JSON report from recorded step results is a pure
      function, unit-tested: for each step, its verdict (`pass`, `fail` or
      `skip`), comment, advisory check result, and Report view text; for
      the run, the FreeCAD version, the checkout's git commit (or
      `unknown`), and start and end times. The output passes `json.loads`.
- [ ] Saving progress and loading it back restores every case's step
      verdicts and comments, asserted with a temporary file.
- [ ] Case 2's step that restores **Side 1** carries an advisory check that
      it is back at x = 0, and its result appears in the report.
- [ ] In `tests/freecad_gui/`, one test opens the wizard dock, starts a
      case, presses a step's setup button, records Pass with a comment, and
      gets a JSON report holding that verdict and comment.
- [ ] The QA Wizard command is in the Shelving menu, not the toolbar, while
      the wizard's developer flag is on, and absent while it is off. The
      flag is on by default.
- [ ] Guard rails, each a test in the core-free suite with a failure
      message that names the rule:
      - no module under `freecad/Shelving/` outside `qa/` imports
        `freecad.Shelving.qa`, except the QA Wizard command module and
        `init_gui.py`;
      - no module under `freecad/Shelving/qa/` imports an underscore name
        from another `freecad.Shelving` module, or reads an underscore
        attribute of anything but its own `self`;
      - the Python under `freecad/Shelving/qa/` totals at most 1,200 lines,
        and the message says raising the budget is a planning decision for
        the user;
      - loading a case file with a key the loader does not know fails,
        naming the key and the file.
- [ ] `.claude/docs/qa-wizard.md` states the wizard's contract (Advice,
      GUARD RAILS), and `CLAUDE.md` points to it in one line.
- [ ] `tasks/active/sh-023-preferences.md` plans a Developer group with the
      timing log and QA wizard toggles, both off by default.
      `tasks/active/sh-022-appearance-and-errors.md`,
      `tasks/active/sh-024-user-documentation-and-release.md` and
      `tasks/active/sh-031-editor-stock-list-and-swap.md` plan their manual
      QA as cases in `freecad/Shelving/qa/cases/`, and friction-024 is
      deleted from `.claude/docs/friction-log.md`.
- [ ] `mypy --strict` clean.

## Advice

DECISIONS (user, 2026-10-10):
- **Cases are data.** Each case lives in a TOML file under
  `freecad/Shelving/qa/cases/`: title, start, steps, each step's
  instruction and expected result, and by name the setup action and
  advisory check it uses. Actions and checks are typed Python functions in
  one registry; TOML names them, never holds code. `docs/manual-qa.md`
  keeps only the policy and how to run the wizard.
- **Setup is a button per step.** A step that needs setup shows a button
  naming what it does ("Add the skewed box"). The wizard never changes the
  document without a press, and pressing again runs it again.
- **Advisory checks, where cheap.** A step may name a check that reads the
  document. The dock shows its result beside the verdict buttons and the
  report records it; the person still decides the verdict. Only for what
  the document can answer, never for what something looks like.
- **A dock widget** in FreeCAD's main window, beside the Tasks tab. Edit
  Unit holds the Tasks panel, which takes one dialog at a time, so the
  wizard cannot be a task panel.
- **Save and resume.** Every verdict and comment is written to a progress
  file at once, under FreeCAD's user data directory. Opening the wizard
  with progress on disk offers to resume. The case that removes the
  workbench says to restore it and reopen the wizard to record what was
  seen.
- **Report: verdicts plus logs.** Per step, the verdict, comment, check
  result and the Report view text added while the step was current; per
  run, FreeCAD version, git commit and times. A Copy button puts the JSON
  on the clipboard and the dock shows the file it was also saved to.
- **Switch:** a module flag on by default, read the way `debug_log` reads
  its own. The QA Wizard command goes in the Shelving menu only, not the
  toolbar. This task amends sh-023 to add a Developer group holding the
  timing log and QA wizard toggles, both off by default there.
- **Tests: data and one smoke.** The loader and name-coverage test, every
  setup action on a fresh document, the report builder, progress
  round-trip, and one GUI test. No tests per button or of navigation.
- **Choosing cases:** the dock lists every case with its status (not run,
  passed, failed, skipped). Start opens the first case not run; any case
  can be picked. The report covers the cases run.
- **Verdicts:** Pass, Fail and Skip. A comment is optional on each; the
  dock prompts for one on Fail without requiring it.
- **Forward only.** Recording a verdict moves to the next step and is
  final. Restarting a case clears its verdicts and comments.

GUARD RAILS (user, 2026-10-10, after planning): keep the wizard small, and
add no production complexity for it beyond plain design for testability.
- Production code never depends on the wizard: only the QA Wizard command
  module and `init_gui.py` import `freecad.Shelving.qa`.
- The wizard drives production code through its public API only. When a
  setup action is awkward to write, the remedy is a production change that
  is a testability improvement worth having on its own (a public helper the
  headless or GUI tests could use too), never a hook that exists only for
  the wizard and never a reach into a private name.
- The `qa/` Python has a 1,200-line budget, about a quarter over the
  planned size. A test enforces it, and raising it is the user's call at
  planning time, not an implementer's during `/work`.
- Case files are closed data: the loader rejects unknown keys, so a case
  gains a field only when a reviewed task adds it to the loader.
- A new manual QA case is a TOML file plus, at most, a new setup action or
  check. Anything else the wizard should do is a new task.
- `.claude/docs/qa-wizard.md` states these rules for future work, so a
  later task's `/work` and review apply them without rereading this file.

PLANNING DECISIONS (2026-10-10):
- The wizard ships in the workbench package (`freecad/Shelving/qa/`),
  since it runs inside FreeCAD; hatchling already packages non-Python
  files under `freecad/`.
- Read TOML with the standard library's `tomllib`. Its result is untyped
  parsed data: validate it into typed records at that one boundary, with
  a comment saying why `Any` appears there, and nowhere else.
- Capture a step's log from the Report view widget's text: note its length
  when the step becomes current and take what was added when its verdict
  is recorded.
- Give each case and step a stable string id, so a case can be added,
  removed or reordered without renumbering others or breaking saved
  progress. That is what friction-024 asked for.
- The git commit comes from running `git rev-parse HEAD` in the
  workbench's own directory; a failure gives `unknown`, never an error.
- Port each current case's prose faithfully, including the bug-009 note
  for the editor cases, turning every pasted Python block into a setup
  action. A "start" state (fresh unit, shelf unit, TestUnit) is a setup
  action on the case's first step.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python: no bare `Any` except at
the TOML boundary noted above, no bare containers in signatures,
`mypy --strict` clean. Shell stays simple: this task adds no shell.

## Plan
- [x] **Step 1** (`freecad/Shelving/qa/`): The case model (typed records for cases and steps with stable ids), the TOML loader with validation, the registry of named setup actions and advisory checks, the pure report builder, and the progress file's save and load, with the core-free tests for the loader, name coverage, report and progress.
- [x] **Step 2** (`freecad/Shelving/qa/cases/`, `freecad/Shelving/qa/actions.py`): Port every case from `docs/manual-qa.md` to TOML, with setup actions for each starting point and pasted code block, and advisory checks where the document can answer (at least case 2's Side 1 position).
- [x] **Step 3** (`freecad/Shelving/qa/dock.py`, `freecad/Shelving/commands/qa_wizard.py`, `freecad/Shelving/init_gui.py`): The dock widget (case list with status, current step, setup button, check result, Pass/Fail/Skip, comment, restart case, Copy report), Report view capture, and the QA Wizard command registered in the Shelving menu only while the flag is on.
- [x] **Step 4** (`tests/freecad/`, `tests/freecad_gui/`): Every setup action on a fresh document, headless where it can be, and the one GUI smoke test.
- [x] **Step 5** (`tests/test_qa_guard_rails.py`, `.claude/docs/qa-wizard.md`, `CLAUDE.md`): The guard-rail tests (import direction, public API only, the line budget, closed case files) and the written contract, with `CLAUDE.md`'s one-line pointer.
- [x] **Step 6** (`docs/manual-qa.md`, `README.md`, `.claude/docs/friction-log.md`, `tasks/active/sh-022-appearance-and-errors.md`, `tasks/active/sh-023-preferences.md`, `tasks/active/sh-024-user-documentation-and-release.md`, `tasks/active/sh-031-editor-stock-list-and-swap.md`): Shrink the doc to policy and how to run the wizard, keep the README link accurate, delete friction-024, add the Developer group to sh-023, and point the other tasks' manual QA at case files.

## Review log

### Round 1: REJECTED
- **F1: Report view capture has no test** (`tests/freecad_gui/test_qa_wizard.py:45`, `freecad/Shelving/qa/dock.py:42`): `report_view_text()` returns `""` when its widget lookup fails, so a renamed widget empties every step's log with the suite green. Print a marker while step 1 is current in the GUI smoke test and assert it appears in the step's `log`.
- **F2: The bug-009 note never reaches the tester** (`freecad/Shelving/qa/cases/30-editor.toml:1-2`): it became a TOML comment the dock never shows; put it in text the dock shows, such as the `expected` of steps where crowded dimensions appear.
- **N1: The command docstring says the command is registered only while the flag is on** (`freecad/Shelving/commands/qa_wizard.py:3-4`): only the menu entry depends on the flag.
- **N2: The `Progress.started` comment does not match the code** (`freecad/Shelving/qa/report.py:34`): it is set when the dock is built; `isoformat(sep=" ")` is not strict ISO 8601.
- **N3: The public-API guard rail has gaps** (`tests/test_qa_guard_rails.py:62`): underscore components in an imported module path pass.
- **N4: `_commit()`'s `unknown` fallback is untested** (`freecad/Shelving/qa/dock.py:48`).
- **N5: Other task files still point at old locations** (`tasks/active/sh-022-appearance-and-errors.md:91`, `tasks/active/sh-023-preferences.md:118`): sh-022 Step 3 names `command_ids`; sh-023 Step 5 still lists `docs/manual-qa.md` and has no step wiring the toggles into the readers, whose Protocol lacks a bool getter; sh-024's reflowed Must Have runs past the line width.
- **N6: British spelling** (`tests/freecad/test_qa_actions.py:20`): "afterwards".

### Round 2: APPROVED
- **N1: Unitless locals for millimeter values** (`freecad/Shelving/qa/actions.py:192`): `a` and `b` hold millimeters.
- **N2: The step-id duplicate check is untested** (`freecad/Shelving/qa/model.py:94`).
- **N3: No test ties Case 2's restore step to the Side 1 check** (`tests/test_qa_cases.py:75`).
- **N4: The advisory checks' passing path is asserted only for Side 1** (`tests/freecad/test_qa_actions.py:28`).
- **N5: The import guard rail misses relative imports** (`tests/test_qa_guard_rails.py:34`): theoretical, the package uses none.
- **N6: British spelling left on an edited line** (`tasks/active/sh-023-preferences.md:114`): "afterwards".

Applied after this round: N1, N2, N3, N4 and N6. N5 left as is.
