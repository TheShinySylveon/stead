# AGENTS.md — Stead

Entry point for **any** agent (Hermes, Claude Code, Codex, Cursor, or a human).
This file follows the open AGENTS.md convention. Nothing here is tied to a
specific tool, model, or vendor.

> Guiding principle: **Rent the intelligence. Own the context.**
> All knowledge lives in plain Markdown + YAML frontmatter, versioned with git.
> All code is Python standard library only. The core is fully offline. An
> optional **read-only** GitHub sync uses the open-source `gh` CLI. An optional
> factory draft calls the OpenAI-compatible endpoint the user configured.
> No vendor SDK, no hardwired key, no SaaS account required to read or write
> context.

## What this system is

A local **context system** plus **factories**, covering both your
own projects and the open-source projects you contribute to (one cockpit):

1. **Context system** — one shared, organized, versioned place where humans and
   agents read and write knowledge. Objects: projects, tasks, documents,
   meetings, repos, contributions. Relations live in frontmatter. Everything
   has one logical home.
2. **Factories** — specific, shared, scrutinized AI workflows under
   `factories/<name>/`. Each has versioned prompts, evals, and run logs.
   The first factory is `weekly-contribution-digest`; `weekly-project-status`
   remains available for own projects. The third, `feature-builder`, turns an
   authored feature spec into an autonomous issue→PR build (shadow/draft-PR only,
   always planning-first; see `docs/spec-kit-workflow.md`).

## Layout

```
AGENTS.md            <- you are here (agent entry point)
README.md            <- human entry point
CONVENTIONS.md       <- ontology + frontmatter schema (READ BEFORE WRITING)
PLAN.md              <- design history (owned by the human; do not edit)
docs/                <- human documentation (start at docs/README.md)
  spec-kit-workflow.md <- always-on SDD flow (method selects tooling only)
context/
  projects/          <- one .md per project
  tasks/             <- one .md per task (status: to-do|doing|done|blocked)
  documents/         <- PRIVATE notes, decisions, specs, research
  meetings/          <- meeting notes, linked to projects
  repos/             <- one .md per repo/project (kind: own|oss)
  contributions/     <- cached GitHub issues/PRs (visibility: public)
  actors/            <- humans and agents who write here (kind: human|agent)
inbox/               <- unsorted capture; triage it, don't let it rot
factories/
  weekly-contribution-digest/   <- first factory (OSS + own-project digest)
  weekly-project-status/        <- own-project status updates
  feature-builder/              <- issue->PR autonomous build (shadow/draft-PR)
    FACTORY.md       <- trigger, inputs, stages, outputs, risk level
    prompts/v2.md    <- versioned prompt (production; v1 retired)
    evals/           <- test cases + pass criteria (JSON)
    runs/            <- one directory per run: bundle.md, prompt.md, run.json
ctx/                 <- Python stdlib-only CLI package (python -m stead)
  ui.py              <- localhost cockpit (stead ui); cockpit.html is the page
  schema.sql         <- SQLite schema; state.db is rebuilt from this
  sync.py            <- read-only GitHub sync via gh subprocess
state.db             <- GITIGNORED, rebuildable operational index (stead init)
```

## How to read (navigation protocol)

1. Start here, then read `CONVENTIONS.md` for the frontmatter schema.
2. "What is the status of project X?" -> `python -m stead status <project-id-or-slug>`
   or read `context/projects/<slug>.md` plus the task files whose frontmatter
   `project:` points at it.
3. "What needs my attention across my OSS work?" -> `python -m stead contribution list`,
   then `python -m stead digest` (or `factory run --factory weekly-contribution-digest
   --shadow`) and read the bundle under `factories/weekly-contribution-digest/runs/`.
4. Follow frontmatter relations (`project:`, `repo:`) instead of guessing folders.
   Files are the source of truth; `state.db` is an index that can always be
   rebuilt with `python -m stead init`.

## How to write (safety rules)

- **Always** give new objects full frontmatter: `id`, `type`, `title`, `created`,
  `updated`, plus relations (`project:` for tasks/docs/meetings; `repo:` for
  contributions). Schema and naming rules: `CONVENTIONS.md`.
- **One logical place** per object. If unsure where something goes, put it in
  `inbox/` and flag it for triage. Never scatter freestyle files.
- Prefer the CLI (`stead task|repo|contribution add/set`) so files and the SQLite
  index stay in sync. If you edit markdown by hand, run `python -m stead init`
  afterwards to re-index (init is a safe, idempotent rebuild).
- Update the `updated:` date whenever you change an object. Never edit `created:`
  or `id:`.
- **Public/private split:** GitHub-derived data (`repos/`, `contributions/`) is
  public; your notes and strategy (`documents/`, `meetings/`, project/task bodies)
  are private. Never copy private strategy into a contribution file or a digest.
- **Core GitHub access is read-only:** `sync`/`digest` never create
  issues/PRs/comments/labels and never push; the digest only drafts locally and a
  human reviews before anything is filed. The gated exceptions are explicit
  commands, not factory assembly: `stead factory publish` may push an isolated
  branch and open a pull request; `stead factory merge` may merge when the repo
  file says `reach: merge` and the checks are green. Neither pushes the default
  branch. Neither runs from the cockpit.
- Do not edit `PLAN.md`. Do not delete run logs under `factories/*/runs/`.
- Commit meaningful changes with git; the history is the audit trail.

## CLI reference (run from the repo root, Python 3.11+, stdlib only)

```
python -m stead version                       # print 0.0.1
python -m stead model show                    # configured endpoint; never prints the key
python -m stead model set --provider openai|anthropic|grok|openrouter|ollama|custom --name NAME
python -m stead eval run [--factory F]        # structural check, no model
python -m stead repo set ID --trigger on-demand|watch --reach shadow|draft-pr|pr|merge
python -m stead factory watch                # watched feature specs; no push
python -m stead factory new --name NAME --title T
python -m stead inbox import PATH             # local .eml .ics .md .txt into inbox/
python -m stead hook set                      # webhook token, printed once
python -m stead factory publish --contribution ID  # isolated branch + pull request. Never merges.
python -m stead factory merge --contribution ID    # green checks only. Repo must say reach: merge.
python -m stead account add --name NAME --actor ACTOR  # shared-server sign-in. Hash only.
python -m stead init                          # rebuild state.db from schema.sql + files
python -m stead task add --title T --project P [--status to-do]
python -m stead task list [--project P] [--status S]
python -m stead task set ID --status S
python -m stead status PROJECT                # task rollup + recent factory runs

python -m stead repo add --title T [--url URL] [--kind own|oss] [--status active|paused|archived]
python -m stead repo list [--kind own|oss]
python -m stead contribution add --title T --repo REPO --kind issue|pr --number N [--role author|assignee|reviewer] [--state open|closed|merged] [--ci pending|pass|fail|none] [--method spec-kit|builtin]
python -m stead contribution list
python -m stead contribution set ID [--state S] [--ci C] [--review R] [--role R] [--method spec-kit|builtin]

python -m stead sync github [--author @me] [--limit N]   # READ-ONLY refresh via gh
python -m stead sync github --offline                    # no network: re-index cache

python -m stead run log --factory F --task REF --prompt-version V [--output TEXT] [--verdict V]
python -m stead prompt list --factory F
python -m stead prompt promote --factory F --version V
python -m stead factory run --factory weekly-contribution-digest [--shadow|--live]
python -m stead factory run --factory weekly-project-status --project P [--shadow|--live]
python -m stead factory run --factory feature-builder --contribution ID [--shadow|--live]
python -m stead digest                        # shortcut for the digest shadow run
python -m stead onboard --title T [--kind own|oss] [--url URL] [--path DIR] [--method spec-kit|builtin] [--no-specify]
python -m stead welcome --title T [--url URL] # first run: one project, no Spec Kit
python -m stead ui                            # local cockpit; empty checkout shows welcome
python3 -m unittest discover -s tests        # run the test suite
```

`factory run` assembles a context bundle and emits the prompt under
`factories/<name>/runs/<run-id>/`. That step is deterministic and does not
call a model. `--generate` sends the assembled prompt to the configured
endpoint and writes `output.md`. It does not post, push, or merge. The digest
factory groups cached contributions by repo (PRs in flight / reviews awaiting
reply / claimed issues / CI flags); the status factory bundles a project's tasks +
documents + meetings; feature-builder bundles a feature spec + acceptance criteria
+ repo conventions. A person or an agent can still read `prompt.md` and record
the result with `stead run log --output ... --verdict ...`. Triggers are
scheduler-agnostic: any cron/Task Scheduler/systemd timer can invoke the CLI.

## Local cockpit

`python -m stead ui` opens a browser on `127.0.0.1` (`--no-browser` to serve
without opening one). A normal start stays on loopback even if Settings says
shared server. `--deploy`, or the Docker image, is the shared server: it
binds `0.0.0.0` and will not start unless an account exists, or
`STEAD_ACCESS_TOKEN` is set and no account exists yet. Human docs:
`docs/README.md`. Deploy: `docs/deploy.md`.

The page reads the same markdown and writes through the same handlers as the
CLI: projects, tasks, documents, meetings, repos, and actors; note edits;
contribution fields (including role, CI, review, and method); inbox capture
and triage; local issues and feature specs (public files); a read-only GitHub
sync; and shadow factory assembly. It never calls an LLM and never performs a
remote write. A contribution body is a public spec, not a private note.
Factory runs from the cockpit are shadow-only — no draft PR. The page has no
external assets, so it works offline.

## GitHub sync (read-only, offline-capable)

- `stead sync github` shells out to the open-source `gh` CLI (stdlib `subprocess`)
  and caches your open PRs (author), review-requested PRs, and assigned issues as
  contribution markdown (`visibility: public`). It owns the GitHub-derived fields
  (`title`, `url`, `state`, `ci`, `review`, `updated`); your edits to `role`,
  `method`, `tags`, `related`, `created`, and the body are preserved across
  syncs. A missing `method` is filled with `spec-kit`; sync never overrides it.
- **READ-ONLY:** only `gh search` / `gh pr view` / `gh api user` (GET). No remote
  writes, ever. `--offline` skips the network and re-indexes cached files.
- `gh` missing or not authenticated -> clear message; use `--offline`. Sample
  data marked `EXAMPLE` lives in `examples/context/`, not in a fresh `context/`.

## feature-builder (issue → PR, shadow/draft-PR only)

A build target is a `contribution` with `kind: issue`, `role: author`, linked to a
`repo`, tagged `feature-spec`, whose body has a description + a `## Acceptance
criteria` checklist. `stead factory run --factory feature-builder --contribution ID`
assembles a deterministic, LLM-free, network-free bundle (spec + criteria + repo
conventions + related docs + sibling contributions for a duplicate sweep) and
flags thin/large/criteria-less specs for decomposition. A pluggable coding agent
then reads `prompt.md` and implements under the issue-to-PR discipline (read
issue + comments → duplicate sweep → validate premise → criterion→test map → TDD
red-green → sabotage-test → quality gates → honest CI).

Every run is **spec-driven and planning-first**. No implementation is written
before a specification, a technical plan, and dependency-ordered tasks exist
and have been reviewed. That discipline is unconditional. The contribution
field `method` selects only the *tooling*:

- `method: spec-kit` (default, including when the field is omitted) — Spec-Driven
  Development via the external, optional `specify` CLI (GitHub Spec Kit). Phases:
  constitution → specify → plan → tasks → implement (TDD) → converge.
- `method: builtin` — the same phases, hand-rolled as markdown
  (`constitution.md` / `spec.md` / `plan.md` / `tasks.md`); no `specify` CLI.

`ctx` never imports or invokes `specify`. Full flow, install, and own-vs-OSS
rules: `docs/spec-kit-workflow.md`. Production prompt is `prompts/v2.md`
(`stead init` seeds the highest version as production; switch or roll back with
`stead prompt promote`).

**Autonomy is two knobs, per repo.** `trigger` is `on-demand` (default) or
`watch`. `reach` is the ceiling: `shadow` (default), `draft-pr`, `pr`, or
`merge`. A run may ask for less. It may not ask for more. Merge is never
inherited from the install default. `stead factory publish` may push an
isolated branch and open a pull request. It does not merge, and it refuses
the default branch. `stead factory merge` is separate. It runs only when the
repo file says `reach: merge`, the checks are green, and GitHub accepts it.
It does not pass `--admin`, and it does not push the default branch.

**Autonomy ladder (a repo may sit on any rung):**
1. **SHADOW (default):** plan + proposed diff only; zero remote writes.
2. **DRAFT-PR:** isolated branch + `gh pr create --draft`; a HUMAN merges.
   `stead factory publish` does this when the ceiling allows it.
3. **TRUSTED (never the install default):** `stead factory merge` only when
   the repo file says `reach: merge`, checks are green, and GitHub accepts
   the merge. No `--admin`. No push of the default branch.

**Hard rules (every mode):** never push to main/default branch; never auto-merge
by default; human review gate before anything consequential; vague/large specs
are flagged, never guessed; report CI honestly. Assembly itself does no
LLM/network/subprocess/remote writes.

## Factory protocol (incremental risk)

1. **Shadow first.** New factories and new prompt versions run in shadow mode
   (`--shadow`, the default): outputs are drafts, a human reviews before anything
   is filed or acted on. The digest **never auto-posts** to GitHub. Assembly
   does not push. Publish and merge are separate commands, and only inside the
   repo ceiling (autonomy ladder above).
2. Promote prompts only after evals pass: `stead prompt promote` refuses until
   every eval case has a recorded pass for that version. The old production
   version is retired, never deleted.
3. Log every run. Review run logs; fix real observed failures, not imagined
   ones. Start simple.
