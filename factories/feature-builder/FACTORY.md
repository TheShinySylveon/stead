# FACTORY: feature-builder

The **third factory**: issue → PR autonomous build, in **strict shadow /
draft-PR mode**. You author a feature spec for your own project (or an OSS
repo); a pluggable coding agent (Hermes, Claude Code, Codex — anything that
reads `prompt.md`) implements it under the discipline encoded in the prompt.

Like every factory here, feature-builder itself is **deterministic and
LLM-free**: `stead factory run --factory feature-builder --contribution ID`
only assembles a build context bundle + prompt from local files. It writes no
code, calls no LLM, uses no network, and performs **no remote writes in any
mode**. The coding happens later, outside the factory, under the autonomy
ladder below.

## Knobs

Two settings, not one ladder everyone climbs. The ceiling is per repo.

- **trigger:** `on-demand` (default) or `watch`. Watch may assemble open
  authored issues tagged `feature-spec` when a scheduler runs
  `stead factory watch`. Flagged specs are skipped. On-demand repos are skipped.
- **reach:** `ghost`, `shadow` (default), `draft-pr`, `pr`, or `merge`. A run
  may ask for less. It may not ask for more.

An install default in gitignored `stead.json` can be `ghost`, `shadow`,
`draft-pr`, or `pr`. Merge is never inherited. The repo file has to say
`reach: merge`. A fresh install starts at on-demand and shadow.

Assembly stays on disk. `stead factory publish` pushes an isolated branch
and opens a pull request when the ceiling allows `draft-pr`, `pr`, or
`merge`. It refuses the default branch. It does not merge.
`stead factory merge` is a separate command. The repo file must say
`reach: merge`. The checks must be green. It does not bypass branch
protection, and it does not push the default branch.

## Autonomy ladder (incremental trust — never skip a rung)

The reaches above are the rungs. A repo may sit on any rung.

1. **GHOST.** Purely **spec, docs, and a code plan**, for human approval.
   The build plans first and may write or delete markdown spec/doc files
   only; code snippets inside the plan or docs are fine. ZERO code is
   applied to the checkout: no source, test, or CI edits, no checks run,
   no push, no PR. A human approves before any code is written.
2. **SHADOW (default, current).** The agent reads `prompt.md` and proposes a
   **plan + proposed diff only**. NO remote writes, NO push, NO PR/issue/
   comment/label creation. A human reviews the plan and diff locally before
   anything is applied.
3. **DRAFT-PR.** When the repo ceiling allows it, `stead factory publish`
   pushes an isolated feature branch and opens a **DRAFT PR**. A **HUMAN
   reviews and merges**. The command never marks the PR ready-for-review,
   never merges, and never pushes the default branch.
4. **PULL REQUEST.** `stead factory publish` opens a normal pull request.
   A human still merges, unless the repo file says `reach: merge`.
5. **TRUSTED (explicit per repo, never the default).** `stead factory merge`
   only after ALL of: the repo file says `reach: merge`, the checks are
   actually green, and GitHub accepts the merge. Branch protection is not
   bypassed. A factory run does not call it. Nothing merges a red check.

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

A build target is a `contribution` with `kind: issue`, linked to a `repo`,
tagged `feature-spec` (or `stead-build`, the synced GitHub label), whose body
contains the feature description plus a `## Acceptance criteria` checklist
(`- [ ]` items) and, after it, a `## Plan` section. See CONVENTIONS.md →
"Buildable feature specs". Author it with `stead spec draft --contribution ID`
(from a synced issue) or `stead contribution add` (then edit the body), or by
hand + `stead init`.

## Spec-driven, planning-first (every run)

No implementation code is written before the specification, the technical
plan, and the dependency-ordered tasks are produced and reviewed. That is
unconditional. The spec's `method` field selects only the tooling:

- `spec-kit` (default, including when omitted) — Spec-Driven Development via
  the external, optional `specify` CLI. Phases: constitution → specify →
  plan → tasks → implement (TDD) → converge.
- `builtin` — the same phases, hand-rolled as markdown. No `specify` CLI.

`ctx` never imports or invokes `specify`. Assembly stays deterministic,
local, and network-free for both. Full flow, install, and own-vs-OSS rules:
`docs/spec-kit-workflow.md`. Production prompt is `prompts/v2.md`.

## Trigger

- **On demand (default):**
  `python -m stead factory run --factory feature-builder --contribution <spec-id>`
  Optional `--reach` cannot exceed the repo ceiling.
- **Watch:** `python -m stead factory watch` assembles open enabled issues
  tagged `feature-spec` (or `stead-build`) whose repo `trigger` is `watch` and
  whose spec flags
  are clear. Scheduler-agnostic: any cron / Task Scheduler / Hermes job can
  invoke that command. It does not push.

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
2. **Assemble** (`stead factory run --factory feature-builder --contribution ID`):
   deterministic bundle + prompt + run.json + runs row; spec-quality flags
   computed. **No LLM call, no network, no remote writes.**
3. **Generate** (pluggable coding agent): reads `prompt.md`; follows the
   issue-to-PR discipline (read issue + comments → duplicate sweep → validate
   premise → criterion→test map → TDD red-green on an isolated branch →
   sabotage-test → quality gates → shadow plan/diff or draft PR → honest CI
   report).
4. **Review** (human, mandatory): plan/diff in shadow; the draft PR in
   draft-PR mode. The human merges.
5. **Record**: `stead run log --factory feature-builder --task <spec-id>
   --prompt-version <v> --output <summary> --verdict approved|rejected`.

## Outputs

- `runs/<timestamp>-<spec-slug>/bundle.md` — deterministic build context bundle
- `runs/<timestamp>-<spec-slug>/prompt.md` — assembled prompt (the emit)
- `runs/<timestamp>-<spec-slug>/run.json` — run metadata (flags, counts, mode)
- `runs` row in state.db (verdict starts `pending`)
- After review: plan/diff (shadow) or a draft PR (draft-PR mode) + verdict

## Tools

Python 3.14+ standard library only (`python -m stead`). External open-source
tools used by the *generation* step (not by assembly): `git` (branching,
audit), `gh` (read-only context; draft-PR creation only in draft-PR mode),
and optionally `specify` (Spec Kit CLI, when `method` is `spec-kit`). `ctx`
never invokes `specify`. No provider is hardwired; no API key is required
by this repo.

## Risk level & incremental rollout

**High-consequence factory, shadow-first, hard gates.** Unlike the digest
(draft text only), this factory's downstream output is code. That is why the
autonomy ladder is explicit and rung 1 (shadow) is the default and the only
mode enabled today. Promotion between rungs requires reviewed runs with
`approved` verdicts, passing evals, and an explicit human decision — never an
agent's own judgement.

## Scrutiny

- Prompts are versioned (`prompts/v1.md`, ...); `stead prompt list` shows
  testing/production/retired. Promote only after evals pass (`stead prompt
  promote`); old production is retired, never deleted.
- Evals live in `evals/*.json` (loaded into state.db by `stead init`): clear
  spec → full criterion→test mapping; vague spec → needs-decomposition;
  duplicate work → surfaced, not silently rebuilt.
- Review run logs; fix **real observed failures**, not imagined ones.