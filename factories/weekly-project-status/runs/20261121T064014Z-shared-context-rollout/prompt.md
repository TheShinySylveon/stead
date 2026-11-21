# Prompt v1 — weekly-project-status (production)

You are drafting a **weekly project status update** for the project described
in the context bundle below the `---` separator. The bundle is the complete,
authoritative context: the project file, its tasks, linked documents, and
meeting notes. Do not invent facts that are not in the bundle.

## Instructions

Write a status update in Markdown with exactly these sections:

1. **Header** — project title, report date (use the bundle's `created`
   timestamp date), and one sentence stating the project's goal.
2. **Summary** — 2–4 sentences: overall health (on-track / at-risk / blocked)
   and the single most important thing that happened since the last update.
   Judge health from task statuses and recent meeting/document content.
3. **Progress** — bullet list of tasks with status `done` (recently completed
   work) and `doing` (in flight). Reference task titles, not ids.
4. **Next up** — bullet list of `to-do` tasks, in a sensible order.
5. **Risks & blockers** — bullet list of `blocked` tasks and any risks evident
   from documents/meetings. If none, write "None identified."
6. **Asks** — decisions or help needed from the human owner, if any; otherwise
   "None."

## Rules

- Be factual and concise: the whole update should be 150–350 words.
- Every claim must be traceable to the bundle. If the bundle is too thin to
   judge health, say so explicitly instead of guessing.
- Plain professional tone; no marketing language, no emoji.
- Do not modify any files. Output only the status update Markdown.
- This is a shadow run: a human will review your draft before it is filed.

---

# Context bundle — Shared Context Rollout
<!-- factory: weekly-project-status | prompt: v1 | mode: shadow | created: 2026-11-21T06:40:14Z -->

## Project (1)

### Shared Context Rollout — status: active
<!-- source: context/projects/shared-context-rollout.md | id: project-shared-context-rollout -->

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

## Tasks (5)

### Define ontology and frontmatter conventions — status: done
<!-- source: context/tasks/define-frontmatter-conventions.md | id: task-define-frontmatter-conventions -->

# Define ontology and frontmatter conventions

Lock object types (project/task/document/meeting), required frontmatter fields
(id, type, title, created, updated, status, project), naming rules, and the
supported flat-YAML subset.

Outcome: `CONVENTIONS.md` committed; seed objects follow it.

### Draft AGENTS.md cross-agent entry point — status: done
<!-- source: context/tasks/draft-agents-md.md | id: task-draft-agents-md -->

# Draft AGENTS.md cross-agent entry point

Write the tool-agnostic entry point: what the system is, layout, read/write
protocols, CLI reference, shadow-first factory rules. Must be useful to any
AGENTS.md-compliant agent, not just Hermes.

Outcome: `AGENTS.md` committed at repo root.

### Run first weekly-status shadow run — status: doing
<!-- source: context/tasks/first-shadow-run.md | id: task-first-shadow-run -->

# Run first weekly-status shadow run

Execute `python3 -m ctx factory run --factory weekly-project-status
--project shared-context-rollout --shadow`, hand the assembled `prompt.md` to
an agent, and record the drafted update with `ctx run log`.

Done when: one run directory exists with bundle.md, prompt.md, run.json, and a
logged verdict.

### Review shadow-run drafts and log verdicts — status: to-do
<!-- source: context/tasks/review-shadow-output.md | id: task-review-shadow-output -->

# Review shadow-run drafts and log verdicts

Human reviews each drafted status update for accuracy (does it match the
tasks/docs?), tone, and completeness. Log `approved` / `rejected` verdicts via
`ctx run log`. Fix real observed failures in the prompt; promote a new version
only after evals pass.

Done when: 3–5 shadow runs reviewed end-to-end (Phase 2 exit criterion).

### Verify CLI end-to-end — status: done
<!-- source: context/tasks/verify-cli-end-to-end.md | id: task-verify-cli-end-to-end -->

# Verify CLI end-to-end

## Documents (1)

### Architecture decisions — Shared Context
<!-- source: context/documents/architecture-decisions.md | id: document-architecture-decisions -->

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

## Meetings (1)

### Kickoff — Shared Context design
<!-- source: context/meetings/2026-11-21-kickoff.md | id: meeting-2026-11-21-kickoff -->

# Kickoff — Shared Context design (2026-11-21)

Solo planning session. Reviewed Notion's *A New Shape for Work* and mapped it
to a local implementation (see PLAN.md).

## Decisions

- Two pillars: context system + factories. Guiding line: "Rent the
  intelligence. Own the context."
- Sustainability mandate: open standards, stdlib-only Python, AGENTS.md as
  cross-agent entry point, no hardwired LLM provider, local-first/offline.
- First factory: `weekly-project-status`, shadow-run first, human review
  before filing.
- Scope locked: single user, single machine, minimal.

## Actions

- Build Phase 1 foundation + factory scaffold (this session).
- Then: first shadow run, review output, iterate on real failures only.
