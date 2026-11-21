# FACTORY: feature-builder

The **third factory**: issue → PR autonomous build, in **strict shadow /
draft-PR mode**. You author a feature spec for your own project (or an OSS
repo); a pluggable coding agent (Hermes, Claude Code, Codex — anything that
reads `prompt.md`) implements it under the discipline encoded in the prompt.

Like every factory here, feature-builder itself is **deterministic and
LLM-free**: `ctx factory run --factory feature-builder --contribution ID`
only assembles a build context bundle + prompt from local files. It writes no
code, calls no LLM, uses no network, and performs **no remote writes in any
mode**. The coding happens later, outside the factory, under the autonomy
ladder below.

## Autonomy ladder (incremental trust — never skip a rung)

1. **SHADOW (default, current).** The agent reads `prompt.md` and proposes a
   **plan + proposed diff only**. NO remote writes, NO push, NO PR/issue/
   comment/label creation. A human reviews the plan and diff locally before
   anything is applied. This is the only mode new specs and new prompt
   versions run in.
2. **DRAFT-PR (next, per-spec opt-in).** After shadow runs are consistently
   approved, the agent may push an **isolated feature branch** and open a
   **DRAFT PR** via `gh pr create --draft` with passing tests and a structured
   body linking the issue. A **HUMAN reviews and merges**. The agent never
   marks the PR ready-for-review, never merges, never pushes to the default
   branch.
3. **TRUSTED (far future, never the default).** Auto-merge only after ALL of:
   a proven record of approved draft-PR runs, an adversarial review of the
   agent's work and prompts, and repository branch protection (required
   reviews + required status checks) enforced server-side. Even then,
   auto-merge is limited to repos where the human explicitly enables it.
   Nothing in this repo enables it today.

## Hard safety rules (every rung, every mode)

- **Never push to main / the default branch directly.** All work happens on
  an isolated feature branch cut from the default branch.
- **Never auto-merge by default.** Merging is a human action (rung 3 is an
  explicit, gated exception — not a default).
- **Human review gate before anything consequential.** Shadow output is a
  draft; a draft PR is a request for review, not a delivery.
- **Vague or large specs are flagged for decomposition, never guessed.** The
  assembler deterministically flags specs with no `## Acceptance criteria`
  checklist (`missing-acceptance-criteria`), a thin description
  (`vague-spec`), or excessive scope (`large-spec`). A flagged spec gets a
  decomposition/clarification plan, not code.
- **Honest CI reporting.** Never claim green without checking the actual
  checks; report pending/fail truthfully.
- The factory assembly itself: no LLM, no network, no subprocess, no remote
  state changes — provably local-file-only.

## Buildable spec convention

A build target is a `contribution` with `kind: issue`, `role: author`, linked
to a `repo`, tagged `feature-spec`, whose body contains the feature
description plus a `## Acceptance criteria` checklist (`- [ ]` items).
See CONVENTIONS.md → "Buildable feature specs". Author it with
`ctx contribution add` (then edit the body) or by hand + `ctx init`.

## Trigger

- **Manual / on-demand (now):**
  `python3 -m ctx factory run --factory feature-builder --contribution <spec-id> --shadow`
- **Event-driven (later):** when a spec contribution is tagged `feature-spec`
  and its spec-quality flags are clear. Scheduler-agnostic: any cron / Task
  Scheduler / Hermes job can invoke the CLI.

## Inputs (all local files — no network at assembly time)

1. The spec contribution (`context/contributions/`): title, body, acceptance
   criteria checklist, url, number.
2. Its repo's conventions (`context/repos/`): url, default_branch,
   contributing, notes, kind (own|oss), status.
3. `related:` documents (`context/documents/`) referenced by the spec.
4. Every other cached contribution in the same repo — the local input for
   the duplicate/overlap sweep (the agent also sweeps live GitHub read-only).

## Stages

1. **Author** the spec (human): description + acceptance criteria +
   `feature-spec` tag.
2. **Assemble** (`ctx factory run --factory feature-builder --contribution ID`):
   deterministic bundle + prompt + run.json + runs row; spec-quality flags
   computed. **No LLM call, no network, no remote writes.**
3. **Generate** (pluggable coding agent): reads `prompt.md`; follows the
   issue-to-PR discipline (read issue + comments → duplicate sweep → validate
   premise → criterion→test map → TDD red-green on an isolated branch →
   sabotage-test → quality gates → shadow plan/diff or draft PR → honest CI
   report).
4. **Review** (human, mandatory): plan/diff in shadow; the draft PR in
   draft-PR mode. The human merges.
5. **Record**: `ctx run log --factory feature-builder --task <spec-id>
   --prompt-version <v> --output <summary> --verdict approved|rejected`.

## Outputs

- `runs/<timestamp>-<spec-slug>/bundle.md` — deterministic build context bundle
- `runs/<timestamp>-<spec-slug>/prompt.md` — assembled prompt (the emit)
- `runs/<timestamp>-<spec-slug>/run.json` — run metadata (flags, counts, mode)
- `runs` row in state.db (verdict starts `pending`)
- After review: plan/diff (shadow) or a draft PR (draft-PR mode) + verdict

## Tools

Python 3.14+ standard library only (`python3 -m ctx`). External open-source
tools used by the *generation* step (not by assembly): `git` (branching,
audit), `gh` (read-only context; draft-PR creation only in draft-PR mode).
No provider is hardwired; no API key is required by this repo.

## Risk level & incremental rollout

**High-consequence factory, shadow-first, hard gates.** Unlike the digest
(draft text only), this factory's downstream output is code. That is why the
autonomy ladder is explicit and rung 1 (shadow) is the default and the only
mode enabled today. Promotion between rungs requires reviewed runs with
`approved` verdicts, passing evals, and an explicit human decision — never an
agent's own judgement.

## Scrutiny

- Prompts are versioned (`prompts/v1.md`, ...); `ctx prompt list` shows
  testing/production/retired. Promote only after evals pass (`ctx prompt
  promote`); old production is retired, never deleted.
- Evals live in `evals/*.json` (loaded into state.db by `ctx init`): clear
  spec → full criterion→test mapping; vague spec → needs-decomposition;
  duplicate work → surfaced, not silently rebuilt.
- Review run logs; fix **real observed failures**, not imagined ones.