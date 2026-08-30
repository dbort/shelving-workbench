---
id: sh-002
title: "Dev-env bootstrap script and CI Python matrix"
current_agent: user
current_phase: abandoned
review_rejections: 0
---

# sh-002: Dev-env bootstrap script and CI Python matrix

## Summary
Would have added a `tools/bootstrap-dev.sh` setup script, a `test.sh --fast`
toolchain preflight, and a Python 3.11/3.12 CI matrix, and cleared the related
friction-log entry.

## Abandoned

Folded into sh-001 on 2026-08-30 when that task was re-scoped from a minimal
scaffold to "scaffold with hardened CI and reproducible environment." The
bootstrap script is superseded by sh-001's `tools/install-deps.sh` (pixi-based,
one script for the full environment), and the preflight, CI Python matrix, and
friction-log cleanup are now sh-001 Must Have items. The full original plan is
in git history at `tasks/active/sh-002-dev-bootstrap.md`.

Superseded by: sh-001.
