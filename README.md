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

### Feature builder: issue → PR autonomous build (shadow / draft-PR)

The third factory, `feature-builder`, turns a feature spec you author into a
build context bundle + prompt that a pluggable coding agent (Hermes, Claude
Code, Codex — anything that reads `prompt.md`) implements under a strict
issue-to-PR discipline. The factory itself is deterministic and LLM-free: it
writes no code, calls no LLM, uses no network, and performs **no remote
writes in any mode**.

A buildable spec is a contribution with `kind: issue`, `role: author`, tagged
`feature-spec`, whose body has a description + a `## Acceptance criteria`
checklist (see CONVENTIONS.md). A clearly-marked EXAMPLE spec is seeded.

Every run is **spec-driven and planning-first**: the specification, technical
plan, and dependency-ordered tasks are produced and reviewed before any
implementation code. That is unconditional — it does not depend on `method`.
The spec's `method` field selects only the tooling:

- `spec-kit` (default, including when omitted) — Spec-Driven Development via
  the external, optional `specify` CLI (GitHub Spec Kit).
- `builtin` — the same phases, hand-rolled as markdown. No `specify` CLI.

`ctx` never invokes `specify`. Flow, install, and own-vs-OSS rules:
`docs/spec-kit-workflow.md`. Production prompt is `prompts/v2.md` (`ctx init`
seeds the highest version; switch with `ctx prompt promote`). EXAMPLE issue
202 sets `method: spec-kit`; issue 201 omits the field and still resolves to
`spec-kit`.

```bash
python3 -m ctx factory run --factory feature-builder \
    --contribution contribution-example-org-example-repo-issue-201 --shadow
# bundle: spec + acceptance criteria + repo conventions + related docs
#         + other cached contributions (duplicate/overlap sweep input)
# hand factories/feature-builder/runs/<run-id>/prompt.md to a coding agent,
# review its plan/diff, then record:
python3 -m ctx run log --factory feature-builder \
    --task contribution-example-org-example-repo-issue-201 \
    --prompt-version v2 --output "..." --verdict approved
```

The production prompt (`prompts/v2.md`) runs the SDD phases in
`docs/spec-kit-workflow.md` before any implementation. It then encodes the
delivery discipline: read the issue + all comments →
sweep for duplicate/overlapping PRs and issues → validate the premise against
current code → map EACH acceptance criterion to a test → TDD red-green on an
isolated branch → sabotage-test the regression → run the repo's quality gates
→ shadow plan/diff or a DRAFT PR linking the issue → report CI honestly.
Vague or large specs are deterministically flagged **NEEDS DECOMPOSITION**
(no checklist / thin description / excessive scope) — flagged specs get a
decomposition plan, never guessed code.

**Autonomy ladder** (full rules in `factories/feature-builder/FACTORY.md`):

1. **SHADOW (default):** plan + proposed diff only. No push, no PR, no remote
   writes. A human reviews locally.
2. **DRAFT-PR:** agent pushes an isolated feature branch and opens a DRAFT PR
   with passing tests; a **human reviews and merges**.
3. **TRUSTED (never the default):** auto-merge only after a proven record +
   adversarial review + server-side branch protection, explicitly enabled.

Hard safety rules in every mode: never push to main/the default branch
directly; never auto-merge by default; human review gate before anything
consequential; vague/large specs are flagged for decomposition, not guessed.

## Structure

| Path | Purpose |
|---|---|
| `AGENTS.md` | Agent entry point: navigation, writing rules, CLI reference |
| `CONVENTIONS.md` | Ontology: object types, frontmatter schema, naming |
| `PLAN.md` | Design document and phased rollout (human-owned) |
| `docs/spec-kit-workflow.md` | Always-on SDD flow for `feature-builder` (`method` selects tooling only) |
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

Phase 1: context skeleton + factory scaffolds, shadow-first. Phase 2:
`weekly-contribution-digest` as the first factory — read-only GitHub cache,
offline-capable, EXAMPLE seeds; specific real repos are deferred (see PLAN.md).
Phase 3 (current): `feature-builder` — issue → PR autonomous build, always
spec-driven and planning-first (`method: spec-kit` by default), in strict
shadow/draft-PR mode, with an autonomy ladder and hard safety rules.
Next phases per `PLAN.md`: eval-driven prompt promotion, scheduled triggers,
inbox triage factory. Frontmatter relations are already team-ready; no rewrite
needed to add people or permissions later.
