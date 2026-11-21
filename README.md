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
python3 -m unittest discover -s tests                  # run tests
```

### Open-source contributions + own projects (one cockpit)

The first factory is `weekly-contribution-digest`: a weekly digest of your PRs
in flight, reviews awaiting your reply, claimed issues, and CI status — across
your own repos and OSS repos you contribute to.

```bash
python3 -m ctx repo list                               # repos (kind: own | oss)
python3 -m ctx contribution list                       # cached issues/PRs
python3 -m ctx sync github --limit 30                  # READ-ONLY refresh via gh
python3 -m ctx sync github --offline                   # no network: re-index cache
python3 -m ctx factory run --factory weekly-contribution-digest --shadow
# equivalently: python3 -m ctx digest
```

- `sync github` shells out to the open-source `gh` CLI (stdlib subprocess) and
  caches your open PRs (author), review-requested PRs, and assigned issues as
  markdown under `context/contributions/` (flat frontmatter, `visibility:
  public`). It is **read-only** — it never creates, comments, labels, or pushes.
- Everything works offline afterwards: files are the source of truth, and
  `ctx init` rebuilds `state.db` without gh. If gh is missing or not
  authenticated you get a clear message; use `--offline`.
- A clearly-marked **EXAMPLE** repo + 3 example contributions are seeded so the
  digest is demonstrable with zero network. Real repos are your choice, later.
- **Public/private split:** GitHub-derived data (repos/contributions) is
  public; your notes and strategy (`context/documents/`) stay private and are
  never part of the digest bundle.
- **Never auto-posts:** the factory only drafts locally; a human reviews every
  digest before it is filed or shared.

The shadow run writes `factories/weekly-contribution-digest/runs/<run-id>/`:

- `bundle.md` — the deterministic context bundle (contributions grouped by repo
  for the digest factory; project + tasks + docs + meetings for the status factory)
- `prompt.md` — the assembled prompt (production prompt + bundle), ready to hand
  to any LLM/agent
- `run.json` — run metadata (also logged to `state.db`)

A human or agent then reads `prompt.md`, drafts the digest/status update, and
records the result:

```bash
python3 -m ctx run log --factory weekly-contribution-digest \
    --task contributions --prompt-version v1 \
    --output "..." --verdict approved
```

## Structure

| Path | Purpose |
|---|---|
| `AGENTS.md` | Agent entry point: navigation, writing rules, CLI reference |
| `CONVENTIONS.md` | Ontology: object types, frontmatter schema, naming |
| `PLAN.md` | Design document and phased rollout (human-owned) |
| `context/` | Knowledge objects: `projects/`, `tasks/`, `documents/`, `meetings/`, `repos/`, `contributions/` |
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
python3 -m ctx sync github --limit 30
python3 -m ctx factory run --factory weekly-contribution-digest --shadow
```

## Growing it

Phase 1: context skeleton + factory scaffolds, shadow-first. Phase 2 (current):
`weekly-contribution-digest` as the first factory — read-only GitHub cache,
offline-capable, EXAMPLE seeds; specific real repos are deferred (see PLAN.md).
Next phases per `PLAN.md`: eval-driven prompt promotion, scheduled triggers,
inbox triage factory. Frontmatter relations are already team-ready; no rewrite
needed to add people or permissions later.
