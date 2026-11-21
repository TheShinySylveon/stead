---
id: document-architecture-decisions
type: document
title: Architecture decisions — Shared Context
created: 2026-11-21
updated: 2026-11-21
project: project-shared-context-rollout
tags: [decisions, architecture]
---

# Architecture decisions — Shared Context

Decision log. Append new decisions; never rewrite old ones.

## D1 — Open standards only (2026-11-21)

Markdown + YAML frontmatter for knowledge, SQLite for operational state, git
for versioning. Rejected: convenient glue / proprietary formats. Rationale:
durability and zero vendor lock-in ("rent the intelligence, own the context").

## D2 — state.db is a rebuildable artifact (2026-11-21)

Track `ctx/schema.sql` + seed markdown in git; gitignore `state.db`.
`ctx init` rebuilds it deterministically. Rationale: the repo stays 100%
diffable text; no binary merge conflicts; any machine can rebuild.

## D3 — Stdlib-only Python, no hardwired LLM (2026-11-21)

All code uses the Python standard library (runs on bare 3.14). The factory
runner assembles context bundles deterministically with no LLM call;
generation is pluggable (any agent/human reads prompt.md and supplies output).
Triggers are plain CLI commands any scheduler can invoke.

## D4 — First factory: weekly-project-status, shadow-first (2026-11-21)

Drafts a status update per active project from its tasks/docs/meetings.
Human reviews before filing. Incremental risk: shadow → low volume →
consequential actions.

## D5 — Single-user minimal scope (2026-11-21)

No people DB, no permissions layer, no multi-machine sync. Frontmatter
relations kept so the system can grow later without a rewrite.
