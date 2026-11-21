---
id: project-shared-context-rollout
type: project
title: Shared Context Rollout
created: 2026-11-21
updated: 2026-11-21
status: active
---

# Shared Context Rollout

Stand up a local, model-agnostic context system (Markdown + YAML frontmatter,
SQLite via stdlib, git) and prove it with one scrutinized factory:
`weekly-project-status`.

## Goal

A fresh agent session can answer "what's the status of project X?" by
navigating this folder alone — no hand-fed context — and the first factory
completes 3–5 shadow runs end-to-end with logs before any live use.

## Scope (locked)

- Single user, single machine, minimal. No people DB, no permissions, no sync.
- Python standard library only; zero pip dependencies; offline-capable.
- Shadow-run first; human reviews every drafted status update before filing.

## Current state

Phase 1 foundation built: conventions, seed objects, `ctx` CLI, factory
scaffold. Next: first shadow run and human review of its output.

## Links

- Decisions: `document-architecture-decisions`
- Kickoff notes: `meeting-2026-11-21-kickoff`
- Factory: `factories/weekly-project-status/FACTORY.md`
