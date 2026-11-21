# AGENTS.md — Shared Context

Entry point for **any** agent (Hermes, Claude Code, Codex, Cursor, or a human).
This file follows the open AGENTS.md convention. Nothing here is tied to a
specific tool, model, or vendor.

> Guiding principle: **Rent the intelligence. Own the context.**
> All knowledge lives in plain Markdown + YAML frontmatter, versioned with git.
> All code is Python standard library only. The core is fully offline; an
> optional **read-only** GitHub sync uses the open-source `gh` CLI (an external
> tool, like git). No API keys, no SaaS, no hardwired LLM.

## What this system is

A local, single-user **context system** plus **factories**, covering both your
own projects and the open-source projects you contribute to (one cockpit):

1. **Context system** — one shared, organized, versioned place where humans and
   agents read and write knowledge. Objects: projects, tasks, documents,
   meetings, repos, contributions. Relations live in frontmatter. Everything
   has one logical home.
2. **Factories** — specific, shared, scrutinized AI workflows under
   `factories/<name>/`. Each has versioned prompts, evals, and run logs.
   The first factory is `weekly-contribution-digest`; `weekly-project-status`
   remains available for own projects.

## Layout

```
AGENTS.md            <- you are here (agent entry point)
README.md            <- human entry point
CONVENTIONS.md       <- ontology + frontmatter schema (READ BEFORE WRITING)
PLAN.md              <- design history (owned by the human; do not edit)
context/
  projects/          <- one .md per project
  tasks/             <- one .md per task (status: to-do|doing|done|blocked)
  documents/         <- PRIVATE notes, decisions, specs, research
  meetings/          <- meeting notes, linked to projects
  repos/             <- one .md per repo/project (kind: own|oss)
  contributions/     <- cached GitHub issues/PRs (visibility: public)
inbox/               <- unsorted capture; triage it, don't let it rot
factories/
  weekly-contribution-digest/   <- first factory (OSS + own-project digest)
  weekly-project-status/        <- own-project status updates
    FACTORY.md       <- trigger, inputs, stages, outputs, risk level
    prompts/v1.md    <- versioned prompt (production)
    evals/           <- test cases + pass criteria (JSON)
    runs/            <- one directory per run: bundle.md, prompt.md, run.json
ctx/                 <- Python stdlib-only CLI package (python3 -m ctx)
  schema.sql         <- SQLite schema; state.db is rebuilt from this
  sync.py            <- read-only GitHub sync via gh subprocess
state.db             <- GITIGNORED, rebuildable operational index (ctx init)
```

## How to read (navigation protocol)

1. Start here, then read `CONVENTIONS.md` for the frontmatter schema.
2. "What is the status of project X?" -> `python3 -m ctx status <project-id-or-slug>`
   or read `context/projects/<slug>.md` plus the task files whose frontmatter
   `project:` points at it.
3. "What needs my attention across my OSS work?" -> `python3 -m ctx contribution list`,
   then `python3 -m ctx digest` (or `factory run --factory weekly-contribution-digest
   --shadow`) and read the bundle under `factories/weekly-contribution-digest/runs/`.
4. Follow frontmatter relations (`project:`, `repo:`) instead of guessing folders.
   Files are the source of truth; `state.db` is an index that can always be
   rebuilt with `python3 -m ctx init`.

## How to write (safety rules)

- **Always** give new objects full frontmatter: `id`, `type`, `title`, `created`,
  `updated`, plus relations (`project:` for tasks/docs/meetings; `repo:` for
  contributions). Schema and naming rules: `CONVENTIONS.md`.
- **One logical place** per object. If unsure where something goes, put it in
  `inbox/` and flag it for triage. Never scatter freestyle files.
- Prefer the CLI (`ctx task|repo|contribution add/set`) so files and the SQLite
  index stay in sync. If you edit markdown by hand, run `python3 -m ctx init`
  afterwards to re-index (init is a safe, idempotent rebuild).
- Update the `updated:` date whenever you change an object. Never edit `created:`
  or `id:`.
- **Public/private split:** GitHub-derived data (`repos/`, `contributions/`) is
  public; your notes and strategy (`documents/`, `meetings/`, project/task bodies)
  are private. Never copy private strategy into a contribution file or a digest.
- **GitHub is read-only:** never create issues/PRs/comments/labels and never push.
  The digest only drafts locally; a human reviews before anything is filed/shared.
- Do not edit `PLAN.md`. Do not delete run logs under `factories/*/runs/`.
- Commit meaningful changes with git; the history is the audit trail.

## CLI reference (run from the repo root, Python 3.14+, stdlib only)

```
python3 -m ctx init                          # rebuild state.db from schema.sql + files
python3 -m ctx task add --title T --project P [--status to-do]
python3 -m ctx task list [--project P] [--status S]
python3 -m ctx task set ID --status S
python3 -m ctx status PROJECT                # task rollup + recent factory runs

python3 -m ctx repo add --title T [--url URL] [--kind own|oss] [--status active|paused|archived]
python3 -m ctx repo list [--kind own|oss]
python3 -m ctx contribution add --title T --repo REPO --kind issue|pr --number N [--role author|assignee|reviewer] [--state open|closed|merged] [--ci pending|pass|fail|none]
python3 -m ctx contribution list
python3 -m ctx contribution set ID [--state S] [--ci C] [--review R] [--role R]

python3 -m ctx sync github [--author @me] [--limit N]   # READ-ONLY refresh via gh
python3 -m ctx sync github --offline                    # no network: re-index cache

python3 -m ctx run log --factory F --task REF --prompt-version V [--output TEXT] [--verdict V]
python3 -m ctx prompt list --factory F
python3 -m ctx prompt promote --factory F --version V
python3 -m ctx factory run --factory weekly-contribution-digest [--shadow|--live]
python3 -m ctx factory run --factory weekly-project-status --project P [--shadow|--live]
python3 -m ctx digest                        # shortcut for the digest shadow run
python3 -m unittest discover -s tests        # run the test suite
```

`factory run` is **deterministic and LLM-free**: it assembles a context bundle and
emits the assembled prompt under `factories/<name>/runs/<run-id>/`. The digest
factory groups cached contributions by repo (PRs in flight / reviews awaiting
reply / claimed issues / CI flags); the status factory bundles a project's tasks +
documents + meetings. Generation is pluggable: any agent (or human) reads
`prompt.md`, produces the output, and records it with
`ctx run log --output ... --verdict ...`. Triggers are scheduler-agnostic: any
cron/Task Scheduler/systemd timer can invoke the CLI.

## GitHub sync (read-only, offline-capable)

- `ctx sync github` shells out to the open-source `gh` CLI (stdlib `subprocess`)
  and caches your open PRs (author), review-requested PRs, and assigned issues as
  contribution markdown (`visibility: public`). It owns the GitHub-derived fields
  (`title`, `url`, `state`, `ci`, `review`, `updated`); your edits to `role`,
  `tags`, `related`, `created`, and the body are preserved across syncs.
- **READ-ONLY:** only `gh search` / `gh pr view` / `gh api user` (GET). No remote
  writes, ever. `--offline` skips the network and re-indexes cached files.
- `gh` missing or not authenticated -> clear message; use `--offline`. Seed data
  marked `EXAMPLE` in title/tags is demonstrative, not real.

## Factory protocol (incremental risk)

1. **Shadow first.** New factories and new prompt versions run in shadow mode
   (`--shadow`, the default): outputs are drafts, a human reviews before anything
   is filed or acted on. The digest **never auto-posts** to GitHub.
2. Promote prompts only after evals pass: `ctx prompt promote` (old production
   version is retired, never deleted).
3. Log every run. Review run logs; fix real observed failures, not imagined
   ones. Start simple.
