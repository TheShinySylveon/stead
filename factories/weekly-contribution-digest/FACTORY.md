# FACTORY: weekly-contribution-digest

The **first factory** of the unified cockpit (own projects + OSS contributions).
**Specific** (one job: a weekly digest of your GitHub contributions in flight),
**shared** (any agent/human runs it via the CLI), **scrutinized** (versioned
prompts, evals, run logs, human verdicts).

> **NEVER auto-post.** This factory drafts locally. Nothing it produces is ever
> posted to GitHub (no comments, reviews, issues, PRs, labels, pushes). All
> `gh` usage in this system is READ-ONLY (`gh search`, `gh pr view`,
> `gh api user` GET). Publishing anything is a human action, outside the factory.

## Trigger

- **Scheduled (target):** weekly, e.g. Friday afternoon, after a fresh
  `python3 -m ctx sync github`. Scheduler-agnostic: any cron / Windows Task
  Scheduler / Hermes cron job invokes:
  `python3 -m ctx factory run --factory weekly-contribution-digest --shadow`
  (equivalently: `python3 -m ctx digest`).
- **Event-driven (later):** after a sync that changed contribution state.
- **Now:** manual invocation only; works fully offline from the cached files.

## Inputs

Cached contributions — no network at assembly time:

1. `context/contributions/*.md` — issues/PRs you're involved with
   (flat frontmatter: `repo`, `kind`, `number`, `role`, `state`, `ci`, `review`,
   `visibility: public`), populated by `ctx sync github` or by hand.
2. `context/repos/*.md` — repo metadata (own vs oss, url) for grouping.

Private notes/strategy (`context/documents/`) are deliberately NOT inputs:
GitHub-derived data is public; the digest stays public-safe.

## Stages

1. **Sync (explicit, read-only):** `ctx sync github [--author @me] [--limit N]`
   shells out to `gh` (subprocess), caches results as markdown + index.
   `--offline` re-indexes the cache without network.
2. **Assemble** (`ctx factory run` / `ctx digest`): deterministically group
   contributions by repo; compute counts (PRs in flight, reviews awaiting
   reply, claimed issues, CI flags); write `bundle.md`, `prompt.md`, `run.json`;
   insert a `runs` row. **No LLM call.**
3. **Generate** (pluggable): any agent or human reads `prompt.md` and drafts the
   digest. No provider is hardwired; no API key is required by this repo.
4. **Review** (human, mandatory in shadow mode): accuracy vs the bundle,
   completeness, tone; confirm nothing private leaked into the draft.
5. **Record**: `ctx run log --factory weekly-contribution-digest
   --task contributions --prompt-version <v> --output <draft>
   --verdict approved|rejected`.
6. **File** (only after approval, later phases): the approved digest becomes a
   document in `context/documents/` (private notes stay private). Never posted
   to GitHub by the system.

## Outputs

- `runs/<timestamp>-digest/bundle.md` — deterministic contribution bundle
- `runs/<timestamp>-digest/prompt.md` — assembled prompt (the emit)
- `runs/<timestamp>-digest/run.json` — run metadata
- `runs` row in state.db (verdict starts `pending`)
- After review: a drafted weekly digest + verdict in the run ledger

## Tools

Python 3.14+ standard library only (`python3 -m ctx`). External open-source
tools invoked via subprocess: `gh` (read-only sync), `git` (audit trail).
Generation step: any LLM/agent the operator chooses. Assembly is offline.

## Risk level & incremental rollout

**Low risk, shadow-first.**

1. **Shadow (current):** drafts only; a human reviews before anything is filed
   or acted on. Default mode. Never auto-posts, in any mode.
2. **Low volume (next):** after 3–5 reviewed shadow runs with mostly `approved`
   verdicts, schedule the weekly sync + digest.
3. **Consequential (later):** auto-filing approved digests into
   `context/documents/`, only after evals pass and the human explicitly
   promotes the workflow. Posting to GitHub remains out of scope, permanently.

## Scrutiny

- Prompts are versioned (`prompts/v1.md`, ...); `ctx prompt list` shows
  testing/production/retired. Promote only after evals pass (`ctx prompt
  promote`); old production is retired, never deleted.
- Evals live in `evals/*.json` (loaded into state.db by `ctx init`).
- Review run logs weekly; fix **real observed failures**, not imagined ones.
