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
own projects and the open-source projects you contribute to (one cockpit).
The shape comes from Notion's *A New Shape for Work*. The deliberate twist is
that a factory executes as a pipeline, not merely a prompt, and that autonomy
is granted per repo rather than globally.

1. **Context system** — one shared, organized, versioned place where humans and
   agents read and write knowledge. Objects: projects, tasks, documents,
   meetings, repos, contributions. Relations live in frontmatter. Everything
   has one logical home.
2. **Factories** — named pipelines that take an input through plan, build,
   verify, and delivery under a per-repo reach ceiling. Each lives under
   `factories/<name>/` with versioned prompts, evals, and run logs.
   `weekly-contribution-digest` covers OSS and own-project PRs.
   `weekly-project-status` drafts one project's status. `feature-builder` turns
   an authored feature spec into a planning-first issue→PR build.
   `context-maintenance` drafts a triage note for the inbox, broken relations,
   stale objects, and duplicate titles. See `docs/spec-kit-workflow.md`.

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
  weekly-contribution-digest/   <- OSS + own-project digest
  weekly-project-status/        <- own-project status updates
  feature-builder/              <- issue->PR planning-first build
  context-maintenance/          <- inbox, relations, stale, duplicates
    FACTORY.md       <- trigger, inputs, stages, outputs, risk level
    prompts/v2.md    <- versioned prompt (production; v1 retired)
    evals/           <- test cases + pass criteria (JSON)
    runs/            <- one directory per run: bundle.md, prompt.md, run.json
ctx/                 <- Python stdlib-only package (python -m stead)
  ui.py              <- localhost cockpit (stead ui); cockpit.html is the page
  schema.sql         <- SQLite schema; state.db is rebuilt from this
  sync.py            <- read-only GitHub sync via gh subprocess
  deliver.py         <- file an approved run as a document
  schedule.py        <- the Friday local jobs
stead/               <- the `python -m stead` package entry
private/             <- GITIGNORED; shared-server account hashes
state.db             <- GITIGNORED, rebuildable operational index (stead init)
```

## How to read (navigation protocol)

0. The status of the Stead project itself lives in `docs/mvp.md` — the single
   source. The README, `docs/trust.md`, and `docs/vision.md` link to it rather
   than restating it.
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
python -m stead version                       # print 0.1.0
python -m stead doctor                        # lint frontmatter, ids, dates, relations
python -m stead model show                    # configured endpoint; never prints the key
python -m stead model set --provider openai|anthropic|grok|openrouter|ollama|custom --name NAME [--review] [--input-price X --output-price Y]
python -m stead eval run [--factory F]        # structural check, no model
python -m stead repo set ID --trigger on-demand|watch --reach ghost|shadow|draft-pr|pr|merge
python -m stead repo set ID --set checks_isolation=docker --set checks_image=python:3.12-slim
python -m stead factory stop                  # .stead-stop: halt builds between steps
python -m stead factory start                 # remove the stop file
python -m stead factory defaults --max-builds-per-day N --build-minutes N [--max-tokens-per-build N] [--max-cost-per-build USD]
python -m stead factory watch                # watched feature specs; no push
python -m stead factory new --name NAME --title T [--input project|contribution|none]
python -m stead factory delete --name NAME [--force]  # refuses shipped factories + run logs without --force
python -m stead inbox import PATH             # local .eml .ics .md .txt into inbox/
python -m stead inbox list [--kind KIND]      # read-only: what is waiting in inbox/
python -m stead hook set                      # webhook token, printed once
python -m stead factory publish --contribution ID  # isolated branch + pull request. Never merges.
python -m stead build --contribution ID [--publish] [--merge] [--resume] [--wait] [--max-tokens N] [--max-cost USD]  # model plans, edits, checks, commits
python -m stead review --contribution ID        # independent reviewer pass: approve or reject the branch diff
python -m stead spec draft --contribution ID [--all] [--redraft]  # issue -> spec (model); --all drafts every open stead-build issue
python -m stead spec approve --contribution ID  # bind approval to the spec body hash
python -m stead factory merge --contribution ID    # green checks + independent reviewer. Repo must say reach: merge.
python -m stead account add --name NAME --actor ACTOR  # shared-server sign-in. Hash only.
python -m stead init                          # rebuild state.db from schema.sql + files
python -m stead task add --title T --project P [--status to-do]
python -m stead task list [--project P] [--status S]
python -m stead task set ID --status S
python -m stead status PROJECT                # task rollup + recent factory runs
python -m stead context search QUERY [--repo ID] [--json]  # read-only search over context objects

python -m stead repo add --title T [--url URL] [--kind own|oss] [--status active|paused|archived]
python -m stead repo list [--kind own|oss]
python -m stead contribution add --title T --repo REPO --kind issue|pr --number N [--role author|assignee|reviewer] [--state open|closed|merged] [--ci pending|pass|fail|none] [--method spec-kit|builtin]
python -m stead contribution list
python -m stead contribution set ID [--state S] [--ci C] [--review R] [--role R] [--method spec-kit|builtin]
python -m stead delete TYPE ID [--force]       # TYPE: project task document meeting repo actor

python -m stead sync github [--author @me] [--limit N]   # READ-ONLY refresh via gh
python -m stead sync github --offline                    # no network: re-index cache
python -m stead sync github --digest                     # assemble only if the cache changed
python -m stead schedule show                            # the Friday local jobs
python -m stead schedule install                         # Windows current user
python -m stead schedule show --project P                # add a status draft

python -m stead run log --factory F --task REF --prompt-version V [--output TEXT] [--verdict V]
python -m stead run file --run ID [--title T]   # approved digest/status -> context/documents/
python -m stead prompt list --factory F
python -m stead prompt promote --factory F --version V
python -m stead factory run --factory weekly-contribution-digest [--shadow|--live]
python -m stead factory run --factory weekly-project-status --project P [--shadow|--live]
python -m stead factory run --factory feature-builder --contribution ID [--shadow|--live]
python -m stead digest                        # shortcut for the digest shadow run
python -m stead metrics [--json] [--repo R]  # dogfood numbers: committed vs correct
python -m stead metrics mark ID --correct true|false  # record the hand-checked rubric verdict
python -m stead onboard --title T [--kind own|oss] [--url URL] [--path DIR] [--method spec-kit|builtin] [--no-specify]
python -m stead welcome --title T [--url URL] # first run: one project, no Spec Kit
python -m stead ui                            # local cockpit; empty checkout shows welcome
python3 -m unittest discover -s tests -b     # run the test suite (buffered)
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

`python -m stead ui` opens a browser on `127.0.0.1:8765` (default port 8765,
printed at startup; `--port N` overrides, `--no-browser` serves without
opening one). A normal start stays on loopback even if Settings says
shared server. `--deploy`, or the Docker image, is the shared server: it
binds `0.0.0.0` and will not start unless an account exists, or
`STEAD_ACCESS_TOKEN` is set and no account exists yet. Human docs:
`docs/README.md`. Deploy: `docs/deploy.md`.

The page reads the same markdown and writes through the same handlers as the
CLI: projects, tasks, documents, meetings, repos, and actors; note edits;
contribution fields (including role, CI, review, and method); inbox capture,
file import, and triage; local issues and feature specs (public files); a
read-only GitHub sync; shadow factory assembly; factory scaffolding; eval
checks and prompt promotion; filing an approved digest or status as a
document; sign-ins, webhook token, index rebuild, and the weekly job. It calls
a model only when Draft with model is checked. Remote writes — publish, merge,
and issue comments — need an explicit confirmation and are refused on a shared
server. Long model steps (build, spec draft, review) run in the background and
are polled for progress.
The Wiki view is the human record for a repo as a Confluence-style space: a
home page, a page tree, and child pages for specs, decisions, glossary, and
tasks, with labels, metadata, and an on-page table of contents. Arrange
reorders and pins; Request a change files a document instead of editing a
generated page.
A contribution body is a public spec, not a private note.
Cockpit factory runs are local: shadow assembly, or a build that plans, edits,
checks, and commits (and may publish or merge behind a confirmation). It refuses
to run a build or a remote write when the deployment is a shared server. The
page has no external assets, so it works offline.

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

A build target is a `contribution` with `kind: issue`, linked to a `repo`,
tagged `feature-spec` (or `stead-build`, the synced GitHub label), whose body
has a description + a `## Acceptance criteria` checklist and a `## Plan`
section. `stead spec draft --contribution ID` turns a synced issue into one.
`stead factory run --factory feature-builder --contribution ID`
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
`watch`. `reach` is the ceiling: `ghost`, `shadow` (default), `draft-pr`, `pr`,
or `merge`. A run may ask for less. It may not ask for more. Merge is never
inherited from the install default. `stead factory publish` may push an
isolated branch and open a pull request. `stead build --publish` also runs the
model build first. `stead factory merge` runs only when the repo file says
`reach: merge`, the checks are green, and GitHub accepts it. `stead build
--publish --merge` chains that after a successful build. It does not pass
`--admin`, and it does not push the default branch.

**Autonomous pipeline.** A factory is not only an assembly step. With a model
configured, `stead build` plans, edits the repo checkout, runs the repo's
`checks:`, commits on an isolated branch, and can publish and merge. The
`trigger: watch` repo plus `stead factory watch --build --publish [--merge]`
turns that into issue-to-delivery without a person in the loop. Shadow and
draft-PR remain the safe defaults.

**Autonomy ladder (a repo may sit on any rung):**
1. **GHOST:** purely spec, docs, and a code plan for approval — the plan plus
   markdown spec/doc changes only (code snippets inside the plan are fine).
   Zero code applied to the checkout, no checks run, zero remote writes.
   A human approves before any code is written.
2. **SHADOW (default):** plan + proposed diff only; zero remote writes.
3. **DRAFT-PR:** isolated branch + `gh pr create --draft`; a HUMAN merges.
   `stead factory publish` does this when the ceiling allows it.
4. **TRUSTED (never the install default):** build, publish, and merge only
   when the repo file says `reach: merge`, checks are green, and GitHub
   accepts the merge. No `--admin`. No push of the default branch.

**Containment (what the build may touch):** tests and CI config are protected
paths by default; a repo opts in with `allow_test_edits` / `allow_ci_edits`.
`checks:` runs with a scrubbed environment (no model key, no `GH_TOKEN`).
`checks_isolation: docker` + `checks_image` runs it in a container with no
network. Merge requires isolation or an explicit `trust_checks: host`, and the
default branch must have required status checks (or an explicit
`merge_without_required_checks: true`). Merge also runs an independent reviewer
pass unless the repo sets `merge_without_review: true`. A build has a wall-clock
budget (`--max-minutes`, watched builds use `build_minutes`), a token budget
(default 2M, `--max-tokens`) and an optional USD budget, a step cap, and a stop
file (`stead factory stop` / `.stead-stop`). Watched builds stop at
`max_builds_per_day` and the token/cost budgets. `stead doctor` lints the store;
`docs/trust.md` is the threat model and egress table.

**Spec approval is bound to content.** `stead spec approve` stores a SHA-256 of
the body; a build refuses an unapproved spec or one whose body changed. The
`author` role and `feature-spec` tag are labels, not permissions. Bundle text
that is not the approved spec is marked untrusted.

**Write-back.** A successful build writes a versioned `build-record` document,
updates contribution/task status on merge, and prior records feed the next
bundle. Interpretive notes (decisions, glossary) are only proposed to `inbox/`
for a person to triage. On a shared server the cockpit makes execution fields
(checks, protected_paths, reach, trigger, code_path, author role, spec
approval) read-only, so an account cannot reach a shell through a later
scheduled build.

**Hard rules (every mode):** never push to main/default branch; merge only
when the repo says `reach: merge` and checks are green; no `--admin`; vague or
large specs are flagged, never guessed; report CI honestly. Assembly alone
does no LLM/network/subprocess/remote writes. `stead build` is a separate,
explicit step.

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
