# MVP: the one loop that must work

**Status: not yet met.** Everything else is deferred until this works. No new
features or QoL until the MVP bar is cleared. This page is the focus filter: if
a task is not on the "In scope" list or a blocker for it, it waits.

## The MVP in one sentence

One person, local-first, takes an issue they authored, approves it as a spec,
and `stead build` produces a **correct, tested** change on an isolated branch,
opens a pull request, CI goes green, and the person reviews and merges — with
the context and the ledger capturing what happened — repeatably.

## Definition of done

The MVP is met when, on a local model, **three real specs** each go through the
full loop and:

- [ ] the spec is approved by content hash (`spec approve`);
- [ ] the build implements the spec **correctly** — the acceptance criteria are
      actually satisfied, not just "checks passed";
- [ ] a test was added that fails without the change and passes with it
      (`require_tests`);
- [ ] checks run scrubbed (or containerized) and pass;
- [ ] a PR is opened at the `pr` ceiling from an isolated branch;
- [ ] CI is green on the PR;
- [ ] a human reviews and merges (Stead never auto-merges);
- [ ] a `build-record` is written and `stead metrics` reports it;
- [ ] a build that cannot meet the spec **fails honestly** with a transcript —
      no silent empty work.

The dogfood contract and the real results live in [Dogfood](dogfood.md). The
safety gates live in [Trust](trust.md).

## In scope (must work for MVP)

| Piece | State |
|---|---|
| Model config + `model test`/`list` (local LM Studio/Ollama) | working |
| Spec approval bound to body hash | working |
| Build loop: plan once → read → write → check → finish | improving; correctness on a small model is the blocker |
| `require_tests` gate (no empty work) | working |
| Protected paths (tests/CI), scrubbed/container checks | working |
| Publish a PR from an isolated branch (`pr`) | working |
| Merge gates (green + required checks, no `--admin`) | working (used after MVP, at `merge`) |
| Write-back record + `stead metrics` | working |
| `stead doctor`, cockpit local read/build | working |

## The blocker

**Build correctness.** Run 1 passed checks and committed but did not implement
the spec (invented path, feature not wired). `require_tests` and a firmer
protocol were added; a re-run is validating whether the model now produces a
correct, tested change or fails honestly. Until a build reliably meets the spec,
the MVP is not met. This is the only thing to work on.

## Deferred until MVP (recorded, not lost)

Do not start these until the definition of done is cleared. Each is tracked in
its proper doc:

- Factories tab UX overhaul, guided New factory, factory delete —
  [Vision](vision.md#open-items-from-review) (ASAP, but post-MVP).
- GitHub commenting and filing issues upstream (semi-autonomy) —
  [Trust](trust.md#github-writes-beyond-opening-a-pr), [Vision](vision.md).
- Acceptance check that exercises the feature in CI; independent reviewer pass —
  [Trust](trust.md#empty-work-ci-and-acceptance-checks).
- Pluggable executor; patch-level edits — [Vision](vision.md).
- Eval redesign (pinned judge, repeats, code evals) — [Vision](vision.md),
  [Factories](factories.md).
- Token/dollar budgets — [Trust](trust.md#known-gaps).
- Shared-server hardening (roles, per-object permissions, rate limit, TLS) —
  [Trust](trust.md#shared-server-every-account-is-an-admin).
- `spec`/`ghost` rung polish, `.stead/` publish, global search/timeline,
  kanban changes — [Vision](vision.md), `PLAN.md` §7.

## Rule

If it is not in "In scope" and not a blocker for the definition of done, it goes
on the deferred list and waits. Record it, link it, move on.