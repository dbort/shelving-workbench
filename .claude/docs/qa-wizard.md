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
- **New wizard features need their own task.** A task that adds cases does
  not change the dock, the report, or the loader along the way.
