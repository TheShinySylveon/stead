# CONVENTIONS.md — Ontology & Writing Rules

The contract every human and agent follows when reading/writing this system.
Bad context is Enemy No. 1; these rules keep context good.

## Object types

| Type | Folder | Purpose | `status` values |
|---|---|---|---|
| `project` | `context/projects/` | An outcome with a beginning and end | `active`, `paused`, `done` |
| `task` | `context/tasks/` | A unit of work belonging to a project | `to-do`, `doing`, `done`, `blocked` |
| `document` | `context/documents/` | Notes, decisions, specs, research | (optional, free) |
| `meeting` | `context/meetings/` | Meeting notes / transcripts | (optional, free) |

No `people/` database: single-user scope (locked decision). Relations are kept
in frontmatter so the system can grow later without a rewrite.

## Frontmatter schema (required)

Every object file starts with a YAML frontmatter block:

```yaml
---
id: task-first-shadow-run          # globally unique, <type>-<slug>
type: task                         # project | task | document | meeting
title: Run first shadow status draft
created: 2026-11-21                # ISO date, never changed after creation
updated: 2026-11-21                # ISO date, bump on every edit
status: to-do                      # required for project and task
project: project-shared-context-rollout   # required for task; recommended for document/meeting
---
```

Optional fields:

- `related:` — inline list of object ids, e.g. `related: [document-architecture-decisions]`
- `tags:` — inline list of free labels.

### Supported YAML subset

The stdlib parser (`ctx/frontmatter.py`) intentionally supports only:

- `key: value` scalars (strings; quotes optional, dates stay strings)
- inline lists: `key: [a, b, c]`
- block lists: `key:` followed by `- item` lines
- `#` comments and blank lines

No nested maps, no anchors, no multiline scalars. Keep frontmatter flat — this
is a feature, not a limitation: any tool can parse it.

## Relations

- A task/document/meeting points at its project with `project: <project-id>`.
- Relations reference **ids**, never filenames or titles.
- One primary project per object. Cross-links go in `related:`.
- Every object has exactly one logical home. Unclassified capture goes to
  `inbox/` and must be triaged (filed into `context/` with full frontmatter),
  not left to rot.

## Naming

- Filename: `<slug>.md` where slug is lowercase kebab-case, e.g.
  `context/tasks/first-shadow-run.md`.
- `id` = `<type>-<slug>` (the filename stem prefixed by the type).
- Meeting slugs start with the date: `2026-11-21-kickoff.md`.
- Never rename an `id` after creation (relations would break); change `title`
  instead.

## Body

After frontmatter: a `# Title` heading, then free Markdown. Keep bodies
factual and concise; agents read these verbatim into context bundles.

## How agents write safely

1. Read this file and `AGENTS.md` before writing anything.
2. Prefer the CLI for tasks: `python3 -m ctx task add|set` keeps markdown and
   the SQLite index in sync and enforces the schema.
3. Creating documents/meetings/projects by hand is fine — use the exact schema
   above, then run `python3 -m ctx init` to re-index.
4. Bump `updated:` on every edit. Never edit `created:` or `id:`.
5. Do not edit `PLAN.md` (human-owned). Do not delete or rewrite files under
   `factories/*/runs/` (append-only audit trail).
6. Commit with git after meaningful changes; write descriptive messages.

## Operational state (SQLite)

`state.db` is a **rebuildable index**, never the source of truth:

- `tasks` — mirror of `context/tasks/` frontmatter (rebuilt by `ctx init`)
- `prompt_versions` — testing / production / retired per factory
- `runs` — one row per factory run or manually logged run
- `evals` — loaded from `factories/*/evals/*.json`

Knowledge lives in files; if `state.db` is lost, `ctx init` restores it.
