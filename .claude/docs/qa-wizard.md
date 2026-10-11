# QA wizard contract

`freecad/Shelving/qa/` is developer tooling: a dock that walks a person
through the manual QA cases. These rules keep it small and keep production
code free of it. `tests/test_qa_guard_rails.py` enforces the first four.

- **Production never depends on the wizard.** Only
  `freecad/Shelving/commands/qa_wizard.py` and
  `freecad/Shelving/init_gui.py` import `freecad.Shelving.qa`.
- **Public API only.** Wizard code imports no underscore name from another
  `freecad.Shelving` module and reads no underscore attribute of anything
  but its own `self`. When a setup action is awkward to write, the fix is a
  production change that is a testability improvement worth having on its
  own, such as a public helper the tests could use too. Never a hook that
  exists only for the wizard.
- **A size budget.** The Python under `freecad/Shelving/qa/` totals at most
  the line budget in `tests/test_qa_guard_rails.py`. Raising it is the
  user's decision, made when a task is planned, never during `/work`.
- **Case files are closed data.** The loader rejects any key it does not
  know, so a case gains a field only when a reviewed task adds it to the
  loader. Case files never hold code.
- **A new manual QA case** is a TOML file under
  `freecad/Shelving/qa/cases/` plus, at most, a new setup action or check
  in `freecad/Shelving/qa/actions.py`. A manual QA case covers only what
  no automated test can assert.
- **How a step reads.** `instruction` is a list with one action per line:
  "Select TestUnit." and "Run Scan Unit." are two lines, not one. Typing a
  value and pressing Return counts as one action. A setup button shows
  above the lines, so it must be the first thing the step does, and no
  line says "press the button". A step whose button is the whole step
  omits `instruction`. A step never offers an "or do it by hand"
  alternative: the button does it, and its label says what it does.
- **New wizard features need their own task.** A task that adds cases does
  not change the dock, the report, or the loader along the way.
