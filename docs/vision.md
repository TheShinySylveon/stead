# Vision

Stead is a shared, model-agnostic context system with an autonomy slider. The
same repository can be a place where a human writes notes, where an agent
observes and proposes, or where an agent writes the spec and the code and
delivers a pull request — without changing tools or losing the history.

> The context outlives the model. The record outlives the run.

## What this is not

- Not a chat memory file with a line cap.
- Not a vector database with a markdown export.
- Not a hosted account you must join.
- Not an agent that acts without a stated ceiling.

## Five commitments

1. **Human-readable first.** Every durable object is a file a person can open:
   markdown with flat frontmatter, plus append-only events. Derived indexes and
   summaries always point back to a file and a commit.
2. **Model-agnostic.** Any model can read the context and any model can be the
   builder. No vendor SDK, no hard-coded key, no format a single tool owns.
3. **No context window.** Agents retrieve the slice they need. The store may be
   larger than any prompt; a bundle is a bounded selection, never the whole
   history.
4. **Spec-driven at every rung.** Planning before code is unconditional.
   Autonomy changes what the agent may produce, never whether it plans.
5. **Opt-in sharing.** Private notes stay local. A repository can publish a
   curated context so a clone carries the history, decisions, and specs.

## The autonomy slider

One ladder per repo. The current `reach` values are the implementation of the
bottom three rungs; `spec` is the missing rung.

| Rung | The agent may | SDD artifacts | Human gate |
|---|---|---|---|
| **observe** | read, summarize, draft notes in the local inbox | none committed | everything |
| **spec** | write specs, decisions, glossaries, and plans as a docs PR | spec + plan | review the docs PR |
| **build** | do everything above, then implement and open a code PR | spec + plan + tasks + tests + code | review the code PR (draft or normal) |
| **deliver** | do everything above, wait for green checks, merge | same | GitHub branch protection only |

- `trigger` stays separate: `on-demand` or `watch`.
- The ceiling is per repo. The install default cannot be `deliver`.
- A run may ask for a lower rung, never a higher one.
- Today: `shadow` ≈ observe/spec, `draft-pr` and `pr` ≈ build,
  `merge` = deliver. Adding `spec` is the first step.

## Shared repo context for OSS

A repository can opt in by committing a `.stead/` directory. A contributor who
clones it gets the context, not just the code.

```
.stead/
  repo.md                 # what this project is, owners, conventions
  autonomy.toml           # default trigger and rung, never above the repo's own
  specs/                  # accepted specs and their status
  decisions/              # ADRs: context, options, outcome
  glossary.md             # names that agents must not guess
  roadmap.md              # what is planned and what is deliberately out
  history/
    YYYY-QN.md            # compacted, reviewed summaries of what changed
    events.jsonl          # optional append-only record, public fields only
```

Rules:

- **Allowlist, not blocklist.** Only the public context types are committed.
  Private notes, inbox, drafts, and credentials never are.
- **Reviewed summaries.** `history/` is written by a person or approved by one.
  Raw model output is not history.
- **Small by default.** Events are compacted into quarterly summaries; git
  carries the rest.
- **A clone is enough.** No server is required to read or extend it. The server
  adds search, not truth.
- **Removal is the repo owner's call.** Stead never pushes `.stead/` to a repo
  that has not asked for it.

## Context without a cap

Three layers, each with one job:

1. **Objects** — markdown files. Canonical, diffable, human-readable.
2. **Events** — append-only JSONL: run started, spec approved, plan written,
   build committed, PR opened, review comment, merge. Cheap to append, easy to
   compact.
3. **Index** — SQLite with FTS5, rebuildable from 1 and 2. Optional embeddings
   are an extension, never a requirement.

Retrieval is a first-class operation:

```bash
stead context search "rate limiter" --repo repo-acme-api
stead context timeline --repo repo-acme-api --since 2026-01-01
stead context bundle --task contribution-acme-api-issue-42 --budget 12000
```

A bundle is selected by relevance and recency, then rendered to the model with
source links. The bundle builder, not the model, enforces the token budget.

## Two readers, one store

The store is shared. The projection is not.

### The human reader

A person opens the cockpit or the CLI and browses freely: full text, full
timeline, private notes included when their scope allows it. No budget, no
ranking, no summarization unless they ask. This is the "read the record"
experience — a clone, a search, and a decision trail.

Onboarding for a person is a generated path through `.stead/`:

```
repo.md → glossary → decisions (newest first) → current spec →
history (last two quarters) → first task
```

### The wiki shape

The human surface is a wiki, generated from the files. There is no second
store to maintain.

- **Repo home** — the name, a one-line summary, kind/status/autonomy chips,
  counts, **Start here** (project, newest decision, current spec, glossary),
  **Pages**, and **Recent**.
- **Drill-down pages** — Overview, Specs, Decisions, Glossary, Tasks, History.
  Each page lists entries; opening one shows the underlying file.
- **Navigation** — breadcrumb plus a persistent page rail. A person can always
  answer "where am I?" and "what is the next most useful page?".
- **Progressive refinement** — the home answers "what is this and where do I
  start?"; a page answers "what was decided and why?"; an entry answers "show
  me the exact text".

The wiki is read-only and private by default. Agents do not read the wiki; they
receive bundles. Both are projections of the same files.

### The agent reader

An agent worker never receives the store. It receives a **context bundle** for
one task, assembled before the first model turn:

- **Mandatory** — the task or spec, acceptance criteria, repo conventions and
  glossary, the files and tests the task touches.
- **Relevant** — decisions, prior related work, recent history, open questions,
  linked issues and PRs, ranked by relevance and recency.
- **Never** — private notes on a public repo, other actors' private scope, or
  the whole history.

Every item carries provenance: `path`, `commit`, `type`, `visibility`, and
`why` (the retrieval reason). The model can distrust or verify a claim instead
of treating a summary as fact. If mandatory material does not fit the budget,
the builder fails the run rather than silently truncating it.

### Just-in-time retrieval

Prefetch is not enough for real work, so the agent gets scoped tools:

| Tool | Returns | Scope |
|---|---|---|
| `search(query)` | matching files and lines | repo + visibility |
| `read(path)` | one file | repo + visibility |
| `timeline(since)` | events and summaries | repo + visibility |

Every call is logged. The log answers "what did the agent see?" after the fact,
which is also how bundle quality is measured and replayed.

### Why this slots into an OSS repo

1. The repo carries `.stead/` publicly.
2. A contributor clones, runs `stead init`, and both readers work offline.
3. Their local private overlay (`context/documents/`, `private/`) never leaves
   their machine.
4. Their agents get the same scoped bundles as the maintainer's agents, minus
   private material.
5. Onboarding is the same graph, projected differently: a reading path for the
   person, a bundle for the agent.

### Quality loop

Retrieval is testable, not vibes:

- **Golden tasks.** For a small set of real past tasks, the needed decision must
  appear in the bundle. Measure recall, not "looks relevant."
- **Provenance check.** Every bundle item resolves to a file and commit.
- **Staleness.** Items older than the last change to their subject are flagged.
- **Stream log.** A run records exactly what was streamed, so a bad output can
  be traced to a missing or misleading input.
- **Poisoning.** Model-written summaries are marked as derived until a person
  approves them; instructions inside repo content are data, not commands.

### Failure modes to design for

| Failure | Mitigation |
|---|---|
| The one decision that mattered was not retrieved | mandatory links, golden-task recall, "known unknowns" section |
| Bundle too large to fit | priority tiers, per-item budget, fail on mandatory overflow |
| Private note leaks into an OSS bundle | allowlist, visibility filter, secret scan before publish |
| Context is stale or contradicted | commit pinning, staleness flags, decisions supersede decisions |
| Agent is fed an injection in a comment or doc | content is labeled data; tools are fixed; no shell from content |

Why not one big file: a single markdown cannot be searched, diffed, or
partially retrieved at scale, and a single vector store loses the human
record. Why not one big database as truth: it stops being clonable and
portable. The files are the source; the index is a cache.

## One context graph, many repos

- Each checkout keeps its own index. That stays true offline.
- A Stead server can build a **global index** across opted-in repos: one
  search, one timeline, cross-repo related work.
- The global index is derived, never authoritative. Drop it and rebuild from
  the repos.
- Later, Postgres can replace SQLite for a multi-writer server. Knowledge still
  lives in files and events.
- Repo boundaries remain the privacy boundary. A global query returns only what
  the caller may read.

## How this differs from adjacent tools

| Tool | What it optimizes | Stead's difference |
|---|---|---|
| Claude `MEMORY.md` | A small, always-loaded memory | No fixed cap; retrieval instead of stuffing; git history |
| Hindsight / vector stores | Semantic recall | Human-readable objects first; embeddings optional; repo-native |
| Coding agents | One task, one session | Durable shared context; spec-driven; per-repo autonomy |
| Issue trackers | Work state | Context, decisions, and history travel with the repo |

## Phases

### Near term

1. Add the `spec` rung; make `autonomy` one ladder while keeping `trigger`.
2. Add `.stead/` opt-in with an allowlist, `autonomy.toml`, and a dry-run
   `stead context publish` that shows exactly what would be committed.
3. Add `stead context search` and `timeline` over the local index.
4. Add an append-only event log for runs and builds.

### Middle

5. `stead context bundle` with an explicit budget and source links, used by
   `stead build`.
6. A server global index across repos, read-only at first.
7. Compaction: quarterly history from events, reviewed before commit.

### Later

8. Cross-repo context graph queries and related-work suggestions.
9. Multi-writer server storage (Postgres) with the same file truth.
10. Policy: per-repo and per-person read scopes on a shared server.

## Open decisions

- **Rung names.** `observe / spec / build / deliver` is the recommendation;
  `shadow / draft-pr / pr / merge` stays as the compatibility mapping.
- **Global index ownership.** A server you run, or a federated set of indexes
  that a local Stead queries. Recommendation: server you run first.
- **Event public/private split.** Which event fields are safe in `.stead/`;
  recommendation: ids, titles, dates, outcomes, links — never note bodies.
- **Summary authorship.** Model-drafted, human-approved, or both. Recommendation:
  model drafts, a person approves, the approved text is the history.
