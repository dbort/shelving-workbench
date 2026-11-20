---
id: sh-052
title: "GUI tests drop offscreen Qt's plugin warnings, ending the popup deadlock"
---

# sh-052: GUI tests drop offscreen Qt's plugin warnings, ending the popup deadlock

## Summary
The offscreen GUI test suite deadlocks on the x86_64 dev VM, so the merge
gate cannot pass there (friction-030). FreeCAD 1.1.3 shows a notification
popup for a repeated message even with popups turned off. Under offscreen
Qt, the popup's `raise()` logs a "This plugin does not support raise()"
warning, which re-enters the Notification Area while it holds its own
lock. The GUI test setup now installs a Qt message handler that discards
these offscreen-only plugin warnings and passes every other Qt message to
FreeCAD's console, the way FreeCAD's own handler does. The change touches
tests and docs only, never the shipped workbench. The docs that describe
the deadlock are corrected to match.

## Must Have
- [ ] `pixi run tests` exits 0 on the x86_64 dev VM; `pyrefly check` clean
      over the changed code.
- [ ] No file under `freecad/` changes (`git diff --stat main -- freecad/`
      is empty).
- [ ] An importable, FreeCAD-free function decides a Qt message's fate. A
      plain-tier unit test (under `tests/`, outside the FreeCAD tiers)
      asserts that it drops `This plugin does not support raise()` and
      `This plugin does not support propagateSizeHints()`, and forwards
      `probe` and `QWidget::repaint: Recursive repaint detected`.
- [ ] The same unit test asserts the forwarding level for each Qt message
      type: warning → `PrintWarning`, critical and fatal → `PrintError`,
      info and debug → `PrintLog`, each with the text followed by a newline.
      Use FreeCAD 1.1.3's mapping instead if its source differs (see
      Advice).
- [ ] A GUI-tier test calls `raise_()` on a shown offscreen `QWidget` and
      asserts that the Report view gained no `This plugin does not support`
      text, then calls `QtCore.qWarning` with a unique marker and asserts
      the marker reaches the Report view.
- [ ] A GUI-tier test sets up the deadlock situation: the main window
      activated, popups off as the test settings leave them, and the same
      warning sent twice in a row through `FreeCAD.Console.PrintWarning`,
      with Qt events processed after each. It asserts that the calls return
      and that the Report view gained no `This plugin does not support`
      text. It asserts nothing about whether a popup appeared, so it
      passes when this machine's timing never reaches the popup.
- [ ] `tests/freecad_gui/test_qa_wizard.py` prints its Report view marker
      through `FreeCAD.Console`, with no direct `append` to the Report view
      widget and no comment about a deadlock.
- [ ] `grep -rn -i deadlock tests/ tools/` finds no claim that a popup
      deadlocks the suite outside `tests/freecad_gui/conftest.py`'s
      explanation of the filter.
- [ ] `.claude/docs/freecad-notes.md` § "A headless notification popup
      deadlocks FreeCAD 1.1" names the repeated-message path that ignores
      `NonIntrusiveNotificationsEnabled`, names the GUI tier's warning
      filter as the remedy, and states that Xvfb's `raise()` does not warn.
- [ ] `.claude/docs/xvfb-gui-testing.md` no longer says a popup deadlocks
      FreeCAD under Xvfb.
- [ ] `friction-030` is gone from `.claude/docs/friction-log.md`, removed
      in the same commit as the filter, and that commit's message records
      the papercut and its fix; `next_id` stays `friction-031`.

## Advice
- The filter is test-only: install it from `tests/freecad_gui/conftest.py`'s
  `pytest_sessionstart`, never from workbench code. The offscreen platform
  exists only in this tier.
- GUI tier only, not `tests/freecad_view/`. Probed during planning: under
  Xvfb (xcb), `QWidget.raise_()` emits no warning, so the view tier cannot
  re-enter this way. Do not add a no-op filter there.
- PySide6 cannot chain to FreeCAD's handler. Probed during planning: after
  `FreeCADGui.showMainWindow()`, `QtCore.qInstallMessageHandler` returns
  `None`, because FreeCAD's handler is C++. The Python handler replaces it,
  so it must forward everything it keeps to `FreeCAD.Console` itself.
  Don't use ctypes to chain to the C++ handler. The user chose forwarding
  as the cheaper route, and its fidelity is enough for tests.
- Match FreeCAD 1.1.3's `messageHandler` (`src/Gui/Application.cpp`): if
  the source is reachable, copy its level mapping and its `(category) `
  prefix for non-default categories. From memory, a release build sends
  debug and info to `Log`, warning to `Warning`, and critical and fatal to
  `Error`, and fatal also aborts. Qt aborts after any handler returns from a
  fatal message, so the Python handler does not abort.
- Match on the prefix `This plugin does not support `. It is
  `QPlatformWindow`'s default-implementation warning family, which only
  minimal platforms such as offscreen hit. Dropping the whole family is
  safe, and it covers any other unsupported call a popup makes.
- Install the handler right after `FreeCADGui.showMainWindow()`. If FreeCAD
  turns out to install its handler later (the probe saw it in place by
  then), move ours after that point.
- Keep the logic in a module importable without FreeCAD (for example
  `tests/qt_messages.py`, importing only PySide6). The console is passed in
  as a `Protocol` with `PrintLog`/`PrintWarning`/`PrintError`, so the unit
  test hands it a recording fake (Typed Python obligation).
- Keep `NonIntrusiveNotificationsEnabled=0` in `tools/freecad-test-user.cfg`.
  It still blocks every non-repeated popup, and the view tier's notes about
  the Report view rely on popups being off. Rewrite only its comment: popups
  stay off for stable runs, and the repeated-message hole is covered by the
  GUI tier's filter.
- `tests/freecad/test_temp_dirs.py:67`: that test runs in the headless tier,
  which has no GUI, so the deadlock is not why it supplies the selection
  directly. Reword the docstring to give the real reason (no GUI selection
  in this tier) and drop the freecad-notes pointer.
- `freecad-notes.md`: drop "On this aarch64 VM". The dev VM is x86_64 now.
  Keep the `eu-stack` tip only if it still holds there; check that `gdb`
  can attach before stating either.
- Two GUI regression tests, each with its own job. The `raise_()` test is
  deterministic: it catches the most likely regression, a Qt upgrade that
  rewords the warning. The repeated-warning test exercises the filter on
  the path that deadlocked (FreeCAD 1.1.3 shows a popup for a message
  identical to the last one, but only while its main window is active).
  The user wants that path covered without the test depending on
  reproducing the hang. Never assert that the popup was shown, and never
  skip or fail when it wasn't. During `/work`, find out once whether the
  test reaches the popup on this VM: check for a visible popup widget, or
  remove the filter and run the test under `timeout`. Record the answer in
  a comment on the test. Keep the test whichever way the check comes out;
  if it never reaches the popup here, say so in the comment. Activate the
  main window with `activateWindow()` and `raise_()` on
  `FreeCADGui.getMainWindow()`, then process events.
- Standing obligations: Shell stays simple holds with no shell. Opted out
  of Follow FreeCAD's own tools, because this is test harness plumbing with
  no FreeCAD-facing behavior; the only precedent that applies is FreeCAD's
  own message-handler mapping, which the handler mirrors. Opted out of Users
  never read the log, because no user-facing path changes.

## Plan
- [ ] **Step 1** (`tests/qt_messages.py`, `tests/test_qt_messages.py`):
      a typed function taking a `QtMsgType`, a `QMessageLogContext`
      category and text, and a console `Protocol`. It drops the
      plugin-warning family and forwards the rest at FreeCAD's level and
      prefix. Plus a factory returning the handler to install. Unit tests
      cover the drop and keep cases and the level mapping.
- [ ] **Step 2** (`tests/freecad_gui/conftest.py`): install the handler
      after `showMainWindow()`, passing `FreeCAD.Console`. Rewrite the module
      docstring to explain the filter and why popups-off alone does not
      prevent the deadlock.
- [ ] **Step 3** (`tests/freecad_gui/`): add the `raise_()` and `qWarning`
      Report view test and the repeated-warning test. For the second, do the
      one-time check Advice describes. Switch `test_qa_wizard.py`'s marker to
      `FreeCAD.Console.PrintMessage` and delete its workaround comment.
- [ ] **Step 4** (`tests/freecad/test_temp_dirs.py`,
      `tools/freecad-test-user.cfg`): reword the docstring and the cfg
      comment as Advice says.
- [ ] **Step 5** (`.claude/docs/freecad-notes.md`,
      `.claude/docs/xvfb-gui-testing.md`): correct the deadlock section and
      the "Notification popups stay off" bullet.
- [ ] **Step 6** (`.claude/docs/friction-log.md`): delete `friction-030`
      in the commit that lands Step 2, recording the papercut and fix in
      that commit's message.
- [ ] **Step 7**: run `pixi run tests` on this VM, save the output and exit
      status to a file, and confirm the GUI suite finishes.

## Review log
