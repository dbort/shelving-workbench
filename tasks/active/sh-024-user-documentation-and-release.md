---
id: sh-024
title: "User documentation and the v1 release"
blocked_by: [sh-022, sh-035, sh-023]
---

# sh-024: User documentation and the v1 release

## Summary
The documentation a user needs and the metadata the Addon Manager needs: a guide
covering both ways in, adopting geometry you already have and starting from
nothing, and what a refusal means; a finalized `package.xml`; and the release
check of installing from the repository on a clean profile. Milestone M10, part
3 of 3, and the last task before v1.

## Must Have
- [ ] `pixi run tests` green.
- [ ] `docs/user-guide.md` exists and covers, in this order: what the workbench
      does in a paragraph; scanning a unit you already modeled; creating one
      from nothing; editing in the panel; board stock; what a refusal
      means and the common ones; and what other tools can do with the output.
- [ ] Every command the workbench registers appears in the guide with its menu
      name, what it acts on, and what it does. A test asserts the set of command
      ids in `init_gui` equals the set documented, so a command added later
      without documentation fails the build.
- [ ] The guide states the three limits a user will meet: rectangular boxes
      only, one elevation plane per unit, and layouts reachable by straight
      cuts. Each says what happens when you exceed it, which is a named refusal
      rather than a wrong answer.
- [ ] `package.xml` carries the final name, description, version, icon,
      maintainer, license, and the FreeCAD minimum version, and validates
      against the Addon Manager's schema.
- [ ] `README.md` leads with what the workbench is for and links the guide, the
      scope document, and the roadmap. Its glossary stays, as the reference for
      the vocabulary.
- [ ] A release QA case in `freecad/Shelving/qa/cases/` covers: install from
      the repository through the Addon Manager on a clean profile, model a
      unit, move it into a second document, confirm the guide's steps work
      as written.
- [ ] No document refers to a milestone as forthcoming that has shipped, and no
      document names a module, command or property that does not exist. Asserted
      by a check over the documents naming code identifiers.
- [ ] `pyrefly check` clean.

## Advice

AUDIENCE: a FreeCAD user who has not seen this project. They know FreeCAD, they
want shelving, and they have not read the scope document. Write for them.
`docs/scope-and-design.md` explains why the project exists and how it is built;
the guide explains how to use it, and must not repeat the design rationale.

LEAD WITH ADOPTION, not creation. Scanning geometry you already have is what
distinguishes this workbench, it is the thing no other tool does, and a reader
deciding whether to install should meet it first. Creating from nothing is the
second entry point, not the headline.

DOCUMENT THE REFUSALS, and give them their own section. This workbench refuses
rather than guessing, so a user will meet a refusal early and it will be their
first real interaction with the design. For each common one, say what it means
in terms of their geometry and what to do: a part that is not a box, a layout
not reachable by straight cuts, an over-constrained size, a pinned part the
layout wants to resize. A refusal a user cannot act on reads as a bug.

DO NOT OVERSELL. State the three limits plainly in their own section:
rectangular boxes only, one elevation plane per unit, layouts reachable by
straight cuts. A user who meets one of these unprepared concludes the workbench
is broken; one who read about it concludes it is honest. The scope document
already words these; keep them consistent without copying wholesale.

THE COMMAND TABLE IS TEST-ENFORCED. Write a test comparing the command ids
`init_gui` registers against the ids the guide documents, failing on either
side. Undocumented commands are how a guide rots, and this is the cheapest
possible guard. Parse the guide for the ids rather than maintaining a second
list.

`package.xml` VALIDATES AGAINST THE ADDON MANAGER SCHEMA. Do not guess the
fields; the schema is published and the existing file is already close. The
version becomes the release version rather than `0.0.1`.

DO NOT WRITE TUTORIAL SCREENSHOTS OR VIDEO. Prose plus the QA cases' steps is
the deliverable. Images go stale faster than anything else in
a document and nothing in this repository can regenerate them.

STANDING OBLIGATIONS (`CLAUDE.md`). Typed Python applies to the one test this
task adds: no bare `Any`, no bare containers in signatures, `pyrefly check`
clean. Shell stays simple applies: if the document check needs more than a grep,
write it as typed Python under `tools/` with its logic in importable functions,
not as a shell pipeline.

The writing-style rules in `CLAUDE.md` § Writing style by destination apply in
full to every document this task writes, and `doc-hygiene` is the authority.

## Plan

- [ ] **Step 1** (`docs/user-guide.md`): Write the guide. Open with a paragraph on what the workbench does and who it is for. Then, in order: scanning a unit you already modeled by opening it with Edit Unit, including what a container is and why one is required; creating a unit from nothing; editing in the panel, covering selection, split, merge, typed sizes, dragging, and what the measurement basis means with the thickness-change example; board stock: where material, color and grain live, which board a new one copies them from, and changing them with the editor's stock swap (sh-031); working alongside other tools, naming what Woodworking's cut list and drilling do with the output and that a document opens without this workbench installed. Use the vocabulary the README glossary defines and no other.

- [ ] **Step 2** (`docs/user-guide.md`): Add the two sections that keep the guide honest. A refusals section, one subsection per common refusal, each saying what it means in terms of the user's geometry and what to do about it. A limits section stating rectangular boxes only, one elevation plane per unit, and guillotine layouts only, each with what happens when you exceed it. Keep both consistent with `docs/scope-and-design.md` without copying it.

- [ ] **Step 3** (`docs/user-guide.md`, `tests/test_docs.py`): Add the command table: one row per registered command with its id, menu name, what it acts on, and what it does. Write the test comparing the ids `freecad.Shelving.init_gui` registers against the ids parsed from that table, failing when either side has an id the other lacks. Import `init_gui` without FreeCAD if possible; if not, read the id list from the module source rather than importing it, and say in a comment why.

- [ ] **Step 4** (`package.xml`, `README.md`): Finalize the package metadata against the Addon Manager schema: name, description matching the guide's opening, release version, icon path, maintainer, license, and FreeCAD minimum version. Rewrite the README's opening to lead with what the workbench is for and link the guide first, then the scope document, then the roadmap; keep the setup, tests and glossary sections.

- [ ] **Step 5** (`freecad/Shelving/qa/cases/`): Add a release QA case: install from the repository through the Addon Manager on a clean profile with no development symlink; create a unit; open a unit modeled by hand in Edit Unit; move a finished unit into a second document with an ordinary placement and confirm it is intact; and walk the user guide's steps exactly as written, confirming each does what it says. State in the case that it is the pre-release gate and is run once per release rather than per task.

## Review log
