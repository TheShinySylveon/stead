# Shared Context — Local Implementation Plan

A local, model-agnostic version of Notion's *A New Shape for Work*: a **context
system** (one shared place where humans and agents read/write knowledge) plus
**factories** (shared, scrutinized AI workflows that compound over time).

> Guiding line from the source: **"Rent the intelligence. Own the context."**

**Build philosophy: sustainable, not convenient.** Open standards (Markdown +
YAML frontmatter, SQLite, git, `AGENTS.md`), Python **stdlib only** (zero pip
deps), local-first, tool- and scheduler-agnostic, no hardwired LLM provider.
The system must outlive any single agent, model, or scheduler.

**Scope:** one unified cockpit for **both your own projects and the open source
projects you contribute to**. Specific repos are seeded later; the ontology is
built to accommodate them now.

---

## 1. Concept → local mapping

| Notion concept | Local equivalent |
|---|---|
| Context system / workspace | This folder: markdown + JSON, git-versioned |
| Core databases (Projects/Repos, Tasks, Contributions, Documents) | `context/` markdown + SQLite tables |
| Ontology / relations | YAML frontmatter links (`repo:`, `project:`, `issue:`, `pr:`) + `CONVENTIONS.md` |
| Factory (specific, shared, scrutinized) | `factories/<name>/` = definition + versioned prompts + evals + run logs |
| Task queue (to-do / doing / done) | `context/tasks/` files with a `status` field |
| Prompt versions (testing / production / retired) | `factories/<name>/prompts/` + `registry.json` status |
| Evals (tasks + judgement criteria) | `factories/<name>/evals/` cases, judged by agent or human |
| Scheduled triggers | Any scheduler calling `python3 -m ctx factory run ...` |
| Event-driven triggers | `inbox/` drop folder + (later) Hermes webhooks |
| Governance / audit / preview | git history + run logs + **shadow-run** mode |
| Sync external context | `ctx sync github` (via `gh`, cached in SQLite, offline-capable) + import scripts → `inbox/` |
| Agent execution engine | **Tool-agnostic:** `AGENTS.md` + stdlib CLI (`python3 -m ctx`); any agent/scheduler drives it |

**Runtime choice:** context + factory definitions live in open files + SQLite.
Execution is a plain Python-stdlib CLI (`python3 -m ctx`) that *any* agent or
scheduler can invoke. Hermes can drive it today, but nothing requires Hermes.
Structured state (tasks, prompt versions, runs, evals) lives in SQLite; knowledge
objects stay markdown. `state.db` is a rebuildable, gitignored artifact.

---

## 2. Folder structure

```
Shared Context/
├── AGENTS.md              # cross-agent entry point (open convention)
├── README.md              # human entry point: quick start, structure
├── CONVENTIONS.md         # ontology: object types, frontmatter schema, naming
├── PLAN.md                # this file
├── ctx/                   # Python stdlib-only CLI (python3 -m ctx)
│   ├── __main__.py        # argparse subcommands (incl. sync github via gh)
│   ├── schema.sql         # SQLite schema (tracked, diffable)
│   └── test_ctx.py        # stdlib unittest tests
├── state.db               # SQLite state (gitignored, rebuildable via ctx init)
├── context/
│   ├── repos/             # one .md per repo/project (own + OSS): url, branch,
│   │                      # contributing guide, conventions, maintainers
│   ├── contributions/     # issues/PRs you're working: repo, github #/url, status
│   ├── tasks/             # local tasks (status: to-do|doing|done|blocked)
│   ├── documents/         # your PRIVATE notes, decisions, learnings
│   └── meetings/          # notes/discussions, linked to repos
├── factories/
│   └── weekly-contribution-digest/
│       ├── FACTORY.md     # trigger, inputs, stages, outputs, tools, risk level
│       ├── prompts/       # v1.md ... (versioned; status in prompt_versions table)
│       ├── evals/         # test cases + pass criteria
│       └── runs/          # context bundles + run logs (also in runs table)
├── inbox/                 # unsorted capture; triage factory files it away
├── .gitignore
└── .git/                  # version control = audit trail + rollback
```

Rules that keep it agent-friendly (from the article's "bad context is Enemy No. 1"):
- Every object has frontmatter: `id`, `type`, `title`, `created`, `updated`, relations.
- One logical place for everything; `inbox/` is the only dumping ground, and it
  gets triaged, not left to rot.
- Agents write through the conventions, never freestyle scattered files.

---

## 3. Phased rollout

### Phase 1 — Context skeleton (one session)
- `git init`, `README.md`, `CONVENTIONS.md` (ontology + frontmatter schema).
- Create `context/` dirs and seed 1–2 real projects + a few tasks.
- Author **`AGENTS.md`** (open cross-agent convention) + a stdlib `ctx/` CLI so
  *any* agent/session can navigate, read, and write here correctly. This is the
  single most important artifact — tool-agnostic, not a Hermes-only skill.
- **Done when:** a fresh agent session can answer "what's the status of project X?"
  by navigating the folder, not by being hand-fed context.

### Phase 2 — First factory: `weekly-contribution-digest` (start tiny)
- Inputs: your PRs in flight, reviews awaiting your reply, claimed issues, CI
  status — pulled by `ctx sync github` (cached) across your repos.
- Write `FACTORY.md` + `prompts/v1.md`; trigger **manually** first.
- **Shadow runs first:** it drafts the digest; a human reviews before filing.
  Never auto-posts to GitHub. Log every run to `runs/`.
- **Done when:** the factory produces 3–5 real digests end-to-end with logs.

### Phase 3 — Scrutiny loop (make it compound)
- Build an **eval suite** (5–10 representative cases + pass criteria) so prompt
  changes are tested against the whole suite, not just the latest failure.
- Prompt versioning via the `prompt_versions` table (testing → production → retired).
- Wire a **scheduler** (Task Scheduler/cron/Hermes) for recurring runs; low volume
  first, expand as trust grows.
- Review run logs weekly; fix real observed failures, not imagined ones.
- **Done when:** a prompt improvement is validated by evals before promotion.

### Phase 4 — Compounding flywheel
- More factories (each follows the same template).
- **Syncs:** `ctx sync github` for issues/PRs/reviews; import email/calendar/transcripts into `inbox/`.
- A **context-maintenance factory**: triage inbox, dedupe, flag stale docs,
  keep relations consistent (agents maintaining the system, per the article).
- Eventually a **factory factory** that scaffolds new factories from the template.

---

## 4. Principles carried over from the source
- **Start simple, watch it fail, fix real failures.** Don't pre-build complexity.
- **Incremental risk:** shadow run → low volume → consequential actions.
- **Specific + shared + scrutinized** — the three factory tests.
- **Humans stay in the loop** where judgment/creativity matters; the system
  elevates people to overseeing the assembly line, not removes them.
- **Model-agnostic:** plain files mean you can swap the underlying LLM freely.

## 5. Decisions (locked)
1. **First factory:** `weekly-contribution-digest` — recurring, verifiable,
   low-risk. Summarizes PRs in flight, reviews awaiting reply, claimed issues,
   and CI across your repos. Human reviews before filing; never auto-posts.
2. **Scope:** single user, single machine; covers **both own projects and OSS
   contributions** in one unified cockpit. Specific repos seeded later. No
   `people/` DB, no permissions layer. Frontmatter relations keep it extensible.
   Public GitHub-derived data is kept separate from your private notes.
3. **Git inside OneDrive:** fine for single-machine use. OneDrive acts as
   backup; revisit only if this ever syncs across machines/people.
4. **Sustainable stack:** open formats + SQLite + git + `AGENTS.md` + Python
   stdlib only; no third-party deps; no hardwired LLM provider; scheduler-agnostic.
5. **GitHub integration:** `ctx sync github` shells out to the open-source `gh`
   CLI (an external tool like git, not a pip dep), caches results in SQLite, and
   stays offline-capable. Sync is explicit/on-demand, not a hardwired cloud call.
   Authenticated account: TheShinySylveon.