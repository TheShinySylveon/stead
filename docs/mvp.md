# MVP: a repo, end to end

**Status: not yet met.** This is the focus filter. If a task is not part of this
loop or a blocker for it, it waits — no new features or QoL until the MVP bar is
cleared.

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
| M0 foundations | landed | not run |
| M1 harness | landed | baseline + first-attempt score **not run** |
| M5 spec draft | landed | not run |
| M3 intake | landed | not run |
| M2 comment | landed | not run |
| M4, M6, M7 | procedure written | not run |

The code milestones above carry the review fixes for PRs #4–#8. Acceptance needs
real model runs and a green PR at the `pr` ceiling, per [Dogfood](dogfood.md).

## In scope (state)

| Stage | State |
|---|---|
| Model config + `model test`/`list` (local LM Studio/Ollama) | working |
| Monitor: `sync github` + `trigger: watch` + scheduler | working (read-only) |
| Spec/docs/plan: `spec draft` + `spec approve` | built; **validate the monitor→draft→approve flow end to end** |
| Spec approval by content hash | working |
| Build correctness on a local model | harness built (structured output, fail-before/pass-after); **first-attempt score not run** |
| `require_tests`, protected paths, scrubbed/container checks | working |
| PR from isolated branch (`pr`) | working |
| **Comment on the issue linking the PR** | built (gated: `allow_comment`, `kind: own`) |
| Write-back record + `stead metrics` | working |
| Merge gates (green + required checks, no `--admin`) | working (human merges at MVP) |
| `stead doctor`, cockpit local read/build | working |

## Blockers (the only work to do)

The code for the full loop is landed (see
[Milestone progress](#milestone-progress)). What remains is operational, not
more code:

1. **Build correctness on a real model.** Run the baseline and score Set B on a
   single first attempt — a build must meet the spec or fail honestly. See
   [Dogfood](dogfood.md).
2. **Reach a green PR at `pr`.** `build --publish --wait` with CI as a required
   check, then a human review and merge.
3. **Run the sign-off (M7).** The monitor → draft → approve → build → PR →
   comment → merge loop on the frozen Set C + hold-out.

## Deferred until MVP (recorded, not lost)

- Factories tab UX overhaul, guided New factory, factory delete —
  [Vision](vision.md#open-items-from-review).
- Filing issues upstream (humans file issues for MVP; Stead comments) —
  [Vision](vision.md).
- Per-spec acceptance check in CI (the fail-before/pass-after gate already runs
  locally) — [Trust](trust.md#empty-work-ci-and-acceptance-checks).
- Pluggable executor; patch-level edits — [Vision](vision.md).
- Eval redesign — [Vision](vision.md), [Factories](factories.md).
- Shared-server hardening (roles, permissions, rate limit, TLS) —
  [Trust](trust.md#shared-server-every-account-is-an-admin).
- `.stead/` publish, global search/timeline, kanban changes —
  [Vision](vision.md), `PLAN.md` §7.

## Rule

If it is not part of the loop and not a blocker for the definition of done, it
goes on the deferred list and waits. Record it, link it, move on.