# AGENTS.md — Shared Context

Entry point for **any** agent (Hermes, Claude Code, Codex, Cursor, or a human).
This file follows the open AGENTS.md convention. Nothing here is tied to a
specific tool, model, or vendor.

> Guiding principle: **Rent the intelligence. Own the context.**
> All knowledge lives in plain Markdown + YAML frontmatter, versioned with git.
> All code is Python standard library only. No network, no API keys, no SaaS.

## What this system is

A local, single-user **context system** plus **factories**:

1. **Context system** — one shared, organized, versioned place where humans and
   agents read and write knowledge. Objects: projects, tasks, documents,
   meetings. Relations live in frontmatter. Everything has one logical home.
2. **Factories** — specific, shared, scrutinized AI workflows under
   `factories/<name>/`. Each has versioned prompts, evals, and run logs.
   The first factory is `weekly-project-status`.

## Layout

```
AGENTS.md            <- you are here (agent entry point)
README.md            <- human entry point
CONVENTIONS.md       <- ontology + frontmatter schema (READ BEFORE WRITING)
PLAN.md              <- design history (owned by the human; do not edit)
context/
  projects/          <- one .md per project
  tasks/             <- one .md per task (status: to-do|doing|done|blocked)
  documents/         <- notes, decisions, specs, research
  meetings/          <- meeting notes, linked to projects
inbox/               <- unsorted capture; triage it, don't let it rot
factories/
  weekly-project-status/
    FACTORY.md       <- trigger, inputs, stages, outputs, risk level
    prompts/v1.md    <- versioned prompt (production)
    evals/           <- test cases + pass criteria (JSON)
    runs/            <- one directory per run: bundle.md, prompt.md, run.json
ctx/                 <- Python stdlib-only CLI package (python3 -m ctx)
  schema.sql         <- SQLite schema; state.db is rebuilt from this
state.db             <- GITIGNORED, rebuildable operational index (ctx init)
```

## How to read (navigation protocol)

1. Start here, then read `CONVENTIONS.md` for the frontmatter schema.
2. To answer "what is the status of project X?" run:
   `python3 -m ctx status <project-id-or-slug>`
   or read `context/projects/<slug>.md` and the task files whose frontmatter
   `project:` points at it. Files are the source of truth; `state.db` is an
   index that can always be rebuilt with `python3 -m ctx init`.
3. Follow frontmatter relations (`project:`) instead of guessing folders.

## How to write (safety rules)

- **Always** give new objects full frontmatter: `id`, `type`, `title`,
  `created`, `updated`, plus relations (`project:` for tasks/docs/meetings).
  Schema and naming rules: `CONVENTIONS.md`.
- **One logical place** per object. If unsure where something goes, put it in
  `inbox/` and flag it for triage. Never scatter freestyle files.
- Prefer the CLI for tasks (`ctx task add/set`) so files and the SQLite index
  stay in sync. If you edit markdown by hand, run `python3 -m ctx init`
  afterwards to re-index (init is a safe, idempotent rebuild).
- Update the `updated:` date whenever you change an object.
- Do not edit `PLAN.md`. Do not delete run logs under `factories/*/runs/`.
- Commit meaningful changes with git; the history is the audit trail.

## CLI reference (run from the repo root, Python 3.14+, stdlib only)

```
python3 -m ctx init                          # rebuild state.db from schema.sql + files
python3 -m ctx task add --title T --project P [--status to-do]
python3 -m ctx task list [--project P] [--status S]
python3 -m ctx task set ID --status S
python3 -m ctx status PROJECT                # task rollup + recent factory runs
python3 -m ctx run log --factory F --task REF --prompt-version V [--output TEXT] [--verdict V]
python3 -m ctx prompt list --factory F
python3 -m ctx prompt promote --factory F --version V
python3 -m ctx factory run --factory weekly-project-status --project P [--shadow|--live]
python3 -m unittest                          # run the test suite
```

`factory run` is **deterministic and LLM-free**: it assembles the project's
markdown + linked tasks/documents/meetings into a context bundle and emits the
assembled prompt under `factories/<name>/runs/<run-id>/`. Generation is
pluggable: any agent (or human) reads `prompt.md`, produces the output, and
records it with `ctx run log --output ... --verdict ...`. Triggers are
scheduler-agnostic: any cron/Task Scheduler/systemd timer can invoke the CLI.

## Factory protocol (incremental risk)

1. **Shadow first.** New factories and new prompt versions run in shadow mode
   (`--shadow`, the default): outputs are drafts, a human reviews before
   anything is filed or acted on.
2. Promote prompts only after evals pass: `ctx prompt promote` (old production
   version is retired, never deleted).
3. Log every run. Review run logs; fix real observed failures, not imagined
   ones. Start simple.
