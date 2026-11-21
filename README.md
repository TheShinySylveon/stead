# Shared Context

A local-first, model-agnostic knowledge system for one person and their agents.
Inspired by Notion's *A New Shape for Work*: a **context system** (one shared,
organized, versioned place for knowledge) plus **factories** (specific, shared,
scrutinized AI workflows).

> **Rent the intelligence. Own the context.**

Everything is open and durable:

- **Markdown + YAML frontmatter** for all knowledge objects (git-versioned).
- **SQLite** (Python stdlib `sqlite3`) for rebuildable operational state.
- **git** for history, audit, and rollback.
- **Python standard library only** — zero pip dependencies, runs on a bare
  Python 3.14 install, fully offline.
- **AGENTS.md** as the cross-agent entry point (works with Hermes, Claude Code,
  Codex, Cursor — anything that honors the convention).
- **No hardwired LLM.** The factory runner assembles prompts deterministically;
  any model/agent/human can supply the generation step.

## Quick start

```bash
cd "Shared Context"
python3 -m ctx init                                    # build state.db (rebuildable)
python3 -m ctx task list                               # see the seeded tasks
python3 -m ctx status shared-context-rollout           # project rollup
python3 -m ctx factory run --factory weekly-project-status \
    --project shared-context-rollout --shadow          # assemble a shadow run
python3 -m unittest                                    # run tests
```

The shadow run writes `factories/weekly-project-status/runs/<run-id>/`:

- `bundle.md` — the deterministic context bundle (project + tasks + docs + meetings)
- `prompt.md` — the assembled prompt (production prompt + bundle), ready to hand
  to any LLM/agent
- `run.json` — run metadata (also logged to `state.db`)

A human or agent then reads `prompt.md`, drafts the status update, and records
the result:

```bash
python3 -m ctx run log --factory weekly-project-status \
    --task project-shared-context-rollout --prompt-version v1 \
    --output "..." --verdict approved
```

## Structure

| Path | Purpose |
|---|---|
| `AGENTS.md` | Agent entry point: navigation, writing rules, CLI reference |
| `CONVENTIONS.md` | Ontology: object types, frontmatter schema, naming |
| `PLAN.md` | Design document and phased rollout (human-owned) |
| `context/` | Knowledge objects: `projects/`, `tasks/`, `documents/`, `meetings/` |
| `inbox/` | Unsorted capture; triage into `context/` |
| `factories/` | Workflow definitions, versioned prompts, evals, run logs |
| `ctx/` | Stdlib-only CLI package (`python3 -m ctx`) |
| `ctx/schema.sql` | SQLite schema — tracked in git |
| `state.db` | Operational index — **gitignored**, rebuilt by `ctx init` |

### Why state.db is not tracked

The repo stays 100% diffable text. Markdown files are the source of truth for
knowledge; `schema.sql` + seed files fully determine `state.db`, so `ctx init`
rebuilds it anywhere (idempotent). Run logs are kept as text under
`factories/*/runs/` and tracked, so the audit trail survives a rebuild.

## Scheduling

Triggers are plain CLI commands — use whatever scheduler you like (cron,
Windows Task Scheduler, Hermes cron, a shell loop). Example weekly shadow run:

```
python3 -m ctx factory run --factory weekly-project-status --project shared-context-rollout --shadow
```

## Growing it

Phase 1 (this repo): context skeleton + first factory scaffold, shadow-first.
Next phases per `PLAN.md`: eval-driven prompt promotion, scheduled triggers,
inbox triage factory. Frontmatter relations are already team-ready; no rewrite
needed to add people or permissions later.
