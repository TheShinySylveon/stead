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

- **M0 (foundations) — done.** Builds run in their own `git worktree` (the
  user's checkout is never touched); the builder reads the whole approved spec
  body; failures carry a `reason` code; a spec gets one automatic build attempt
  per approved hash (`--retry` to re-run); and a killed build's started marker
  is reclaimed as an infrastructure failure record.
- **M1 (build correctness harness) — done.** The builder asks for structured
  JSON output (`response_format`), logs characters sent/received and model
  latency per build, and enforces the fail-before/pass-after gate: the base
  suite must pass first, the new test must fail against the base (without the
  code change), and the branch must pass.
- **M5 (spec draft) — done.** `stead spec draft` turns a raw issue into a
  buildable draft spec (a new linked contribution) in one model call, without
  touching the source issue; the plan lives inside the approved body.
- **M3 (intake + enablement) — done.** Sync fetches issues carrying the
  `stead-build` label and records it as a tag; the build/publish/merge/review/
  watch gates drop the `role: author` requirement in favour of "enabled (label
  or `feature-spec` tag) + approved hash"; and `stead schedule show --interval
  hourly|daily` prints the shorter monitor cadence.
- **M2 (issue comment) — done.** A gated, idempotent comment links the PR on the
  source issue (`allow_comment: true`, `kind: own` only, never from assembly);
  auto-runs on `build --publish` when enabled, or via `stead factory comment`.
- **M4 / M6 / M7 (operational) — runbook ready.** M6 (reconcile-on-sync) is
  wired into `sync github`; M4 (reach `pr` + required CI) and M7 (the fixed
  rubric, pre-registered issue sets A/B/C + hold-out, and the sign-off
  procedure) are documented in [Dogfood](dogfood.md) and need the human's real
  model + CI runs, not more code.

## In scope (state)

| Stage | State |
|---|---|
| Model config + `model test`/`list` (local LM Studio/Ollama) | working |
| Monitor: `sync github` + `trigger: watch` + scheduler | working (read-only) |
| Spec/docs/plan: `ghost` rung | built; **validate the monitor→ghost→approve flow end to end** |
| Spec approval by content hash | working |
| Build correctness on a local model | **blocker** — run 1 passed checks but did not implement the spec |
| `require_tests`, protected paths, scrubbed/container checks | working |
| PR from isolated branch (`pr`) | working |
| **Comment on the issue linking the PR** | built (gated: `allow_comment`, `kind: own`) |
| Write-back record + `stead metrics` | working |
| Merge gates (green + required checks, no `--admin`) | working (human merges at MVP) |
| `stead doctor`, cockpit local read/build | working |

## Blockers (the only work to do)

1. **Build correctness.** A build must meet the spec or fail honestly.
   `require_tests` + firmer protocol added; a re-run is validating. First.
2. **Issue commenting.** A gated remote write that posts a comment on the source
   issue linking the PR (and CI status). Not built. Required for the human to
   merge and close together. Design: explicit per-repo permission, never from
   assembly, reviewable; see [Trust](trust.md#github-writes-beyond-opening-a-pr).
3. **Validate the ghost flow.** Confirm monitor → spec/docs/plan → approve →
   build works as one path, not just isolated commands.

## Deferred until MVP (recorded, not lost)

- Factories tab UX overhaul, guided New factory, factory delete —
  [Vision](vision.md#open-items-from-review).
- Filing issues upstream (humans file issues for MVP; Stead comments) —
  [Vision](vision.md).
- Acceptance check in CI; independent reviewer pass —
  [Trust](trust.md#empty-work-ci-and-acceptance-checks).
- Pluggable executor; patch-level edits — [Vision](vision.md).
- Eval redesign — [Vision](vision.md), [Factories](factories.md).
- Token/dollar budgets — [Trust](trust.md#known-gaps).
- Shared-server hardening (roles, permissions, rate limit, TLS) —
  [Trust](trust.md#shared-server-every-account-is-an-admin).
- `.stead/` publish, global search/timeline, kanban changes —
  [Vision](vision.md), `PLAN.md` §7.

## Rule

If it is not part of the loop and not a blocker for the definition of done, it
goes on the deferred list and waits. Record it, link it, move on.