# MVP: a repo, end to end

**Status: met — the full loop (draft → approve → build → PR → merge) has now run
end to end on a fresh, model-drafted issue and scored correct. The draft is
model-drafted (`qwen3.8-flash`) with a fast human review; the build is autonomous.**
See [Dogfood](dogfood.md) for the scores.

## The MVP in one sentence

For one repo, end to end: Stead keeps the context updated, monitors for issues,
and — for issues enabled for it — creates the spec, docs, and code plan, builds
the code, opens a PR, and **comments on the issue linking the PR** so a human
can review, merge, and close in one place. Autonomy is per repo; a human gates
the consequential steps.

## The loop

1. **Monitor** — `sync github` (read-only) caches issues/PRs; `trigger: watch`
   plus the scheduler picks up enabled issues.
2. **Spec / docs / plan** — the `ghost` rung drafts the spec, doc changes, and a
   code plan for approval. No code applied yet.
3. **Approve** — a person approves the spec by content hash (`spec approve`).
4. **Build** — `stead build` implements the approved spec: plan once → read →
   write → check → finish, with `require_tests` and protected paths.
5. **PR** — at the `pr` ceiling, publish opens a pull request from an isolated
   branch.
6. **Comment** — Stead comments on the source issue linking the PR (and CI
   status), so the human can merge and close together.
7. **Review + merge** — a human reviews; CI must be green; merge is the human's
   (or, later, gated `merge`). Stead never auto-merges at MVP.
8. **Context updated** — a `build-record` is written, contribution/task status
   updates, and the next bundle reads the prior record. `stead metrics` reports
   it.

## Definition of done

The MVP is met when, on a local model, **three real issues** each go through the
loop and:

- [ ] the issue is picked up by monitor/watch (or authored locally) and enabled;
- [ ] spec/docs/code plan are produced (ghost) and the spec is approved by hash;
- [ ] the build implements the spec **correctly** — criteria actually satisfied,
      not just "checks passed";
- [ ] a test was added that fails without the change and passes with it;
- [ ] checks run scrubbed/containerized and pass;
- [ ] a PR opens at the `pr` ceiling from an isolated branch; CI is green;
- [ ] **Stead comments on the issue linking the PR**;
- [ ] a human reviews, merges, and closes;
- [ ] context is updated (build-record, status) and `stead metrics` reports it;
- [ ] a build that cannot meet the spec **fails honestly** with a transcript —
      no silent empty work.

Results live in [Dogfood](dogfood.md); safety gates in [Trust](trust.md).

## Milestone progress

Two states: **code landed** (the change is merged) and **acceptance met** (the
milestone's own measurement passed). Only the second is "done".

| Milestone | Code | Acceptance |
|---|---|---|
| M0 foundations | landed | run |
| M1 harness | landed | Set A (tuning) + Set B scored (2/3 hand-finished, 1/3 autonomous) + baseline |
| M5 spec draft | landed | **measured end to end** (#111 → #179): `qwen3.8-flash` drafts, a fast human review catches residual fabrication, the build is autonomous; gates + cite-and-verify landed |
| M3 intake | landed | exercised on real issues |
| M2 comment | landed | exercised (#30 on #25, #34 on #27, #166/#167/#169); clean skip for local-only specs (#178, exercised on #179) |
| M4, M6, M7 | procedure written | **Set C 3/3 + hold-out 1/1, all correct** (built autonomously on the 27B, merged with no human edits) |

The frozen scoring is complete and the full loop is measured end to end:
[Dogfood](dogfood.md) records every verdict. The draft step was the one human
gate; it is now model-drafted by `qwen3.8-flash` with a fast review (a spot-check,
not a rewrite), and the build after it is autonomous.

The code milestones above carry the review fixes for PRs #4–#8. Acceptance needs
real model runs and a green PR at the `pr` ceiling, per [Dogfood](dogfood.md).

**2026-11-22:** the first real-model runs on Arete 27B found four harness gaps,
fixed in #15, #17, #18, and #21 (stale-branch records, per-call timeout, long
files unreadable and unwritable, update merges counted as human edits). After
them, Set A spec 2 (`metrics --since`) built correctly, was published at `pr`
as #20, passed CI, and was merged by a human; `sync github` recorded it as
merged with no human edits. Details: [Dogfood](dogfood.md#arete-27b-2026-11-22).

Later the same day, Set A spec 1 went through every step on a real GitHub
issue: #25 was synced, drafted by the model into a spec, approved, built on
Arete 27B in 27 minutes with no repair rounds, published as #30 with
`Closes #25`, commented on the issue by Stead, merged by a human, and
reconciled by `sync github` (no human edits). Each fix that run surfaced landed
first: the drafter sees the repo tree (#26), drafting uses the model's call
timeout (#29), and builds report progress as they run (#24). Set A spec 3
(`inbox list`, #27) then ran the same loop on its first attempt, published as
#34 with `Closes #27` and merged with no human edits. "Exercised" above means
a step has run for real on a tuning issue; acceptance still means the
milestone's own measurement on the frozen sets.

## In scope (state)

| Stage | State |
|---|---|
| Model config + `model test`/`list` (local LM Studio/Ollama) | working |
| Monitor: `sync github` + `trigger: watch` + scheduler | working (read-only) |
| Spec/docs/plan: `spec draft` + `spec approve` | working; **draft→approve→build→PR→merge validated end to end on a model draft** (#111 → #179); a fast human review still catches residual fabrication |
| Spec approval by content hash | working |
| Build correctness on a local model | harness built (structured output, fail-before/pass-after, line-range reads, exact edits); three Set A specs built, hand-checked correct, and merged (#20, #30, #34); **first-attempt score not run** |
| `require_tests`, protected paths, scrubbed/container checks | working |
| PR from isolated branch (`pr`) | working: #20 published by `factory publish`, CI green, human-merged |
| **Comment on the issue linking the PR** | built (gated: `allow_comment`, `kind: own`); skips cleanly when the spec has no real upstream issue (#178) |
| Write-back record + `stead metrics` | working: a human merge reconciles via `sync github` (scoped with `--repo`, #22); update-from-base merges are not human edits (#21) |
| Merge gates (green + required checks, no `--admin`) | working (human merges at MVP) |
| `stead doctor`, cockpit local read/build | working |

## Blockers — cleared

The three operational blockers are now done:

1. **Build correctness on a real model** — Set B scored (2/3 hand-finished,
   1/3 autonomous on the 27B), and Set C 3/3 + hold-out 1/1 all correct.
2. **Reach a green PR at `pr`** — `build --publish` opened green PRs (#166,
   #167, #169) that CI passed and a human merged with no edits.
3. **Run the sign-off (M7)** — the frozen Set C + hold-out ran end to end;
   every spec scored correct (see [Dogfood](dogfood.md)).

The last human gate was the **draft step**, and it is now measured end to end:
model-drafted by `qwen3.8-flash` (fast), with a **fast human review** that still
catches residual fabrication (a fresh #111 re-draft invented a `--limit` flag the
gate stack does not check). The build after it was autonomous (0 repair rounds,
0 human commits). So the split is **draft = fast review, build = human-rarely** —
the loop completes on a model draft, but drafting is not yet unattended. The gate
stack (path → symbol → data-model → citation, plus the completion-retry) catches
data-model fabrication as a backstop; CLI-flag existence is the recorded gap.

## Post-MVP list (MVP met — now the active roadmap)

The definition of done is satisfied and the full loop is measured end to end.
These items were deferred during the MVP and are now the active post-MVP work;
each is filed as an issue so it is tracked, not lost. This is the *product*
roadmap; the *engineering* autonomy roadmap is `PLAN.md` §7, now annotated with
what already landed during the MVP (`edit`, budgets, lock recovery, and
`address`).

The headline three:

1. **Shared-server hardening** (roles, permissions, rate limit, TLS) — issue #64,
   [Trust](trust.md#shared-server-every-account-is-an-admin). Every account is an
   admin today; this is the gate before anyone else is invited onto a shared
   server.
2. **Eval redesign** (pin judge model, multiple runs, compare vs previous version)
   — issue #56, [Vision](vision.md), [Factories](factories.md). Makes the draft
   gates and prompt promotion trustworthy enough to lean on.
3. **Filing issues upstream** (Stead files issues, not just comments) — issue #63,
   [Vision](vision.md). Closes the intake side of the loop, which a human still
   drives today.

Also filed, behind those:

- Per-spec acceptance check in CI (the fail-before/pass-after gate already runs
  locally) — issue #52, [Trust](trust.md#empty-work-ci-and-acceptance-checks).
- Pluggable executor (headless agent CLI inside a sandbox) — issue #54;
  unified-diff edits (lift the per-file size cap) — issue #55,
  [Vision](vision.md).
- `.stead/` publish, global search/timeline, kanban changes — issue #65,
  [Vision](vision.md), `PLAN.md` §7.

Small and near-term, from the full-loop measurement: a draft gate that verifies a
CLI flag a plan names actually exists (recorded in [Dogfood](dogfood.md)). It is a
backstop in the same family as the symbol/data gates — not the primary fix, which
is model selection for the draft role.

## Rule

If it is not part of the loop and not a blocker for the definition of done, it
goes on the deferred list and waits. Record it, link it, move on.