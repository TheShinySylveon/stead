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
| `repo` | `context/repos/` | A repo/project you work on — own or OSS | `active`, `paused`, `archived` |
| `contribution` | `context/contributions/` | An issue or PR you're involved with (GitHub cache) | uses `state:` instead of `status:` |

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

### Repo fields (`context/repos/`)

```yaml
---
id: repo-example-org-example-repo    # repo-<owner>-<name> slug
type: repo
title: EXAMPLE example-org/example-repo (not a real repo)
created: 2026-11-21
updated: 2026-11-21
status: active                       # active | paused | archived
kind: oss                            # own | oss
url: https://github.com/example-org/example-repo
default_branch: main                 # optional
contributing: https://github.com/example-org/example-repo/blob/main/CONTRIBUTING.md  # optional, url or path
notes: ...                           # optional, short scalar
---
```

### Contribution fields (`context/contributions/`)

```yaml
---
id: contribution-example-org-example-repo-pr-101   # contribution-<repo-slug>-<kind>-<number>
type: contribution
title: "EXAMPLE: Add caching layer to the parser"
created: 2026-11-21
updated: 2026-11-21
repo: repo-example-org-example-repo  # required relation to a repo id
kind: pr                             # issue | pr
number: 101                          # GitHub issue/PR number
url: https://github.com/example-org/example-repo/pull/101
role: author                         # author | assignee | reviewer
state: open                          # open | closed | merged
ci: pass                             # pending | pass | fail | none
review: requested                    # requested | approved | changes | none
method: spec-kit                     # spec-kit (default) | builtin — tooling only
visibility: public                   # GitHub-derived data is always public
---
```

`ctx sync github` owns the GitHub-derived fields (`title`, `url`, `state`, `ci`,
`review`, `updated`); your edits to `role`, `method`, `tags`, `related`,
`created`, and the body are preserved across syncs. A missing `method` is filled
with `spec-kit`; sync never overrides a value you set.

### Buildable feature specs (`feature-builder` factory)

A contribution doubles as a **buildable feature spec** — the input to the
`feature-builder` factory (issue → PR autonomous build) — when ALL of:

- `kind: issue` and `role: author` (you authored the spec), linked to a `repo`
- `tags:` includes `feature-spec` (marks it as a build target)
- the body contains a feature description followed by a `## Acceptance
  criteria` section with a `- [ ]` checklist — one concrete, testable
  criterion per item

```markdown
---
id: contribution-example-org-example-repo-issue-201
type: contribution
title: "EXAMPLE: Add --json output to the list command"
created: 2026-11-21
updated: 2026-11-21
repo: repo-example-org-example-repo
kind: issue
number: 201
url: https://github.com/example-org/example-repo/issues/201
role: author
state: open
ci: none
review: none
visibility: public
tags: [example, seed, feature-spec]
---

# EXAMPLE: Add --json output to the list command

Description of the feature: what, why, scope, constraints. Keep it
substantive (a one-line wish gets flagged, not built).

## Acceptance criteria

- [ ] `list --json` prints a single valid JSON array to stdout
- [ ] Each object contains id, title, and status fields
- [ ] Without the flag, output is unchanged and existing tests pass
```

Author it with `ctx contribution add --kind issue --role author ...` then edit
the body (add the description + checklist + `feature-spec` tag), or write the
file by hand and run `ctx init`. Optional: `related: [document-...]` links
design notes into the build bundle. Optional: `--method spec-kit|builtin`
(default `spec-kit`).

#### Tooling (`method`) — planning is unconditional

Every `feature-builder` run is **spec-driven and planning-first**. No
implementation is written before a specification, a technical plan, and
dependency-ordered tasks exist and have been reviewed. That discipline does
not depend on `method`. `method` selects only the *tooling*:

- `spec-kit` (**default**, including when the field is omitted) — Spec-Driven
  Development via the external, optional `specify` CLI (GitHub Spec Kit).
  Phases: constitution → specify → plan → tasks → implement (TDD) → converge.
- `builtin` — the same phases, hand-rolled as `constitution.md` / `spec.md` /
  `plan.md` / `tasks.md`. No `specify` CLI.

`ctx` never imports or invokes `specify`. Set or change it with
`ctx contribution add --method ...` or `ctx contribution set ID --method ...`.
Full flow, install, and own-vs-OSS rules: `docs/spec-kit-workflow.md`.
EXAMPLE seed issue 202 sets `method: spec-kit`; issue 201 omits the field and
still resolves to `spec-kit`. Production prompt is `prompts/v2.md` (`ctx init`
seeds the highest version; switch with `ctx prompt promote`).

The assembler applies **deterministic quality flags** (no LLM):
`missing-acceptance-criteria` (no checklist), `vague-spec` (description under
25 words), `large-spec` (over 8 criteria or 400 description words). Any flag
means **NEEDS DECOMPOSITION** — an agent must produce a decomposition /
clarification plan, never guess and build.

Build it (shadow by default — plan + proposed diff only, no remote writes):

```bash
python3 -m ctx factory run --factory feature-builder \
    --contribution contribution-example-org-example-repo-issue-201 --shadow
```

Safety is governed by the autonomy ladder in
`factories/feature-builder/FACTORY.md`: shadow → draft-PR (human merges) →
trusted (never the default). Never push to the default branch; never
auto-merge by default.

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
- A contribution points at its repo with `repo: <repo-id>`.
- Relations reference **ids**, never filenames or titles.
- One primary project per object. Cross-links go in `related:`.
- Every object has exactly one logical home. Unclassified capture goes to
  `inbox/` and must be triaged (filed into `context/` with full frontmatter),
  not left to rot.

## Public / private split (locked rule)

- **Public:** everything GitHub-derived — `context/repos/` metadata and
  `context/contributions/` (always `visibility: public`). These files mirror
  public GitHub state and may appear in digests shared with others.
- **Private:** your notes, strategy, and decisions — `context/documents/`,
  `context/meetings/`, project/task bodies. Never copy private strategy into a
  contribution file or a digest draft.
- The digest factory reads only the public layer; private context stays local.

## GitHub sync (read-only, offline-capable)

- `python3 -m ctx sync github [--author @me] [--limit N]` shells out to the
  open-source `gh` CLI (stdlib `subprocess`) and caches your open PRs (author),
  review-requested PRs, and assigned issues as contribution markdown files.
- **READ-ONLY:** only `gh search`, `gh pr view`, `gh api user` (GET). The system
  never creates issues/PRs/comments/labels and never pushes. No remote writes.
- Sync is explicit/on-demand. `--offline` skips the network entirely and just
  re-indexes the cached files. `ctx init` also rebuilds the index from files
  without gh — the cache is fully offline-capable.
- `gh` missing or not authenticated → clear error message; use `--offline`.
- Seed data marked `EXAMPLE` in title/tags is demonstrative, not real.

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
2. Prefer the CLI: `python3 -m ctx task add|set`, `repo add|list`,
   `contribution add|list|set` keep markdown and the SQLite index in sync and
   enforce the schema.
3. Creating documents/meetings/projects/repos/contributions by hand is fine —
   use the exact schema above, then run `python3 -m ctx init` to re-index.
4. Bump `updated:` on every edit. Never edit `created:` or `id:`.
5. Do not edit `PLAN.md` (human-owned). Do not delete or rewrite files under
   `factories/*/runs/` (append-only audit trail).
6. Commit with git after meaningful changes; write descriptive messages.

## Operational state (SQLite)

`state.db` is a **rebuildable index**, never the source of truth:

- `tasks` — mirror of `context/tasks/` frontmatter (rebuilt by `ctx init`)
- `repos` — mirror of `context/repos/` frontmatter (rebuilt by `ctx init`)
- `contributions` — mirror of `context/contributions/` frontmatter (rebuilt by
  `ctx init`; upserted by `ctx sync github`)
- `prompt_versions` — testing / production / retired per factory
- `runs` — one row per factory run or manually logged run
- `evals` — loaded from `factories/*/evals/*.json`

Knowledge lives in files; if `state.db` is lost, `ctx init` restores it.
