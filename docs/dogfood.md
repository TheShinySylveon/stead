# Dogfooding Stead on Stead

The most persuasive number is a real one. This page is the procedure for running
Stead's own factory against the Stead codebase and publishing what happened. It
deliberately contains **no invented metrics** — the tables are filled by a real
run, then committed.

> Prerequisite: a model endpoint. `stead build` rents a model; assembly alone
> calls nothing. For local-first dogfooding, Ollama keeps every prompt on the
> machine:
>
> ```bash
> python -m stead model set --provider ollama --name llama3.2
> ```
>
> Any OpenAI-compatible endpoint works — a local LM Studio or Ollama server
> keeps every prompt on this computer and needs no key. The key for a hosted
> provider lives in gitignored `stead.json` or `STEAD_MODEL_API_KEY`, never in
> context. Verify with `stead model test`.

## Operating policy (the dogfood contract)

Once Stead is usable, **Stead manages Stead**: it monitors the issue queue,
creates specs/docs/plans, fixes them through the factory, opens PRs, and comments
on the issue linking the PR. This is the dogfood metric — the actual way work
gets done on this repo. The full scope and definition of done are in
[MVP](mvp.md).

- **Ceiling `pr`: stop just short of `merge`.** Every change opens a pull
  request; a human reviews the output and merges. Stead never auto-merges its
  own work. Set the repo `reach: pr`; `merge` stays off. (If a repo is raised to
  `reach: merge`, `stead factory merge` also runs an independent reviewer before
  merging, unless `merge_without_review: true`.)
- **Monitor → spec/docs/plan → approve → fix → PR → comment.** `sync github`
  reads issues read-only; the `ghost` rung drafts spec/docs/plan; a person
  approves the spec (`spec approve`, bound to the body hash); `stead build
  --publish` plans, edits, runs checks, and opens the PR; Stead comments on the
  issue linking the PR so the human can merge and close together. Write-back
  records the outcome and feeds the next bundle.
- **Humans file the issues for MVP.** Stead monitors and responds; filing issues
  upstream is deferred.
- **Human gate on interpretation.** Decisions and glossary terms the model
  proposes go to the inbox for triage, never straight into context.
- **The metric is the ledger.** `stead metrics` reports specs built, the failure
  rate, share merged after review, how many merged after a human edit, repair
  rounds, checks mode, time, tests touched, characters/tokens sent, cost, and
  independent-review verdicts. Every build writes a record, success or failure.
  Merged/closed outcomes and human edits are reconciled from live PR state by
  `stead sync github` (read-only), so a human merge under the `pr` ceiling
  reaches the numbers. Publish those numbers here as they accumulate.
- **Spend is bounded.** Each build has a token budget (default 2M) and, when
  model prices are configured, a USD budget. A watch run also has a daily build
  count. Raise or lower them with `stead factory defaults`.

Honest gaps in the contract today (MVP blockers):

- **The build loop is not yet reliable on a small model.** We are stabilizing at
  `shadow` (local, hand-reviewed) until a build consistently reaches a green PR.
  The `pr` ceiling applies once it does.
- **The monitor → ghost → approve → build path needs end-to-end validation.**
  The pieces exist (label intake, `spec draft`, `spec approve`, worktree build,
  publish, comment); the sign-off run below exercises them as one path.

## Correctness rubric (fixed before the run)

A build is **correct** when, checked by hand against the built change:

1. every `## Acceptance criteria` item is actually satisfied (not just "checks
   passed");
2. the mechanical fail-before/pass-after gate holds (the new test fails without
   the change and passes with it);
3. CI is green on the PR.

A PR that needed human commits before merge is **not** a first-attempt success.
It is recorded separately as "success with human edits" (the ledger already
detects this by comparing the merged head SHA to the recorded build commit).

Record the verdict per build with
`python -m stead --root ../stead-dogfood metrics mark ID --correct true|false`,
so `stead metrics` keeps **committed** (mechanical) apart from **correct** (the
rubric) and an unverified build never reads as a success.

## Pre-registered issue sets

Frozen before any tuning. None of the M7 sign-off issues may have been used for
tuning. "Unseen" means not used while tuning the harness — the full text is
written here now, and the harness is frozen before any of it is run.

- **Set A — tuning (3).** The three candidate specs below. Used to tune the
  harness; NOT scored.
- **Set B — unseen scoring (3).** Frozen full text below; run once on a single
  first attempt after the harness is frozen.
- **Set C — M7 fresh end-to-end (3) + 1 hold-out.** Frozen full text below; run
  the full monitor→draft→approve→build→PR→comment→merge loop fresh. The
  hold-out is scored separately and was never used in tuning or M1.

### Pass bar

- **Set B:** ≥2 of 3 correct on their single first attempt, per the rubric above.
- **Set C:** all 3 fresh issues correct through the full loop, and the hold-out
  correct. **2 of 3 is a smoke bar on n=3, not a reliability estimate.**

### Set B (frozen)

1. `stead contribution list --json` — add a `--json` flag to
   `contribution list` that emits one JSON object per contribution (id, repo,
   kind, number, role, state, ci, title) as a JSON array; the default table
   output is unchanged; a test covers the JSON shape and the unchanged default.
2. `doctor` flags an unapproved `stead-build`-labeled issue — `stead doctor`
   warns when a contribution tagged `stead-build` has no `spec_sha`, warns when
   `spec_sha` is present but the body changed, and is silent on an approved one;
   a test covers all three.
3. `stead status` prints a build-record summary — `stead status --project P` adds
   a one-line summary of the most recent build record for that project's repo
   (outcome, reason, date); a test covers a repo with and without records.

### Set C (frozen, fresh end-to-end)

1. Add a `--sort` option to `stead task list` (by title then status).
2. `stead repo list --json`.
3. `stead doctor` reports a contribution whose `repo:` relation is missing.

### Hold-out (frozen)

`stead metrics --json` emits `attempts`, `build_failures`, and `infra_failures`
as top-level numbers.

## M4 — build → PR → CI (procedure)

To reach a real green PR at the `pr` ceiling:

1. `stead repo set <id> --reach pr` (human merges; no auto-merge).
2. `stead build --contribution ID --publish --wait` so publish opens the PR and
   `--wait` polls its checks.
3. Configure branch protection with CI as a **required** status check on the
   default branch (so a red PR cannot merge).
4. Confirm the PR body carries `Closes #N`, and verify the `.git`/hook protection
   holds against a real `gh` session: run a spec whose check plants a
   `post-commit` hook in `.git/hooks`; the build must fail with the `tamper`
   reason and the hook must be gone afterwards.


## Why a separate checkout

`stead build` refuses a `code_path` equal to the context root, so the store and
the code being edited must be different directories. Use a worktree of the Stead
repo as the code, and a small store as the context:

```bash
# 1. A code checkout separate from this context repo.
git worktree add ../stead-dogfood-code main

# 2. A context store for the dogfood run.
mkdir ../stead-dogfood
python -m stead --root ../stead-dogfood init
python -m stead --root ../stead-dogfood repo add --title "Stead (dogfood)" \
    --url https://github.com/TheShinySylveon/stead --kind own
python -m stead --root ../stead-dogfood repo set repo-theshinysylveon-stead \
    --path ../stead-dogfood-code --reach draft-pr \
    --set checks="python -m unittest discover -s tests"
```

`repo set` prints a warning if the check runner's config is unprotected. The
Stead suite is run by `python -m unittest`, so there is no Makefile/package.json
to protect; the tests themselves are protected paths by default. A feature that
needs a new test sets `allow_test_edits: true` on the repo, and the build records
which tests it touched.

## The loop

For each candidate spec below:

```bash
# Author the spec as a contribution (kind issue, role author, feature-spec tag,
# a description + ## Acceptance criteria). Then approve the exact body:
python -m stead --root ../stead-dogfood spec approve --contribution CONTRIBUTION_ID

# Build at draft-pr. A human reviews and merges; Stead does not auto-merge here.
python -m stead --root ../stead-dogfood build --contribution CONTRIBUTION_ID --publish

# Read the numbers. Every build, success or failure, wrote a build-record.
python -m stead --root ../stead-dogfood metrics

# Reconcile merged/closed outcomes and human edits from live PR state (read-only).
python -m stead --root ../stead-dogfood sync github
```

When a PR merges — whether by `stead factory merge` or by a human under the `pr`
ceiling — the record's outcome becomes merged, the contribution is marked merged,
linked tasks close, and the next bundle reads the prior record. A human merge is
picked up by `sync github`; if the PR head SHA differs from the commit Stead
recorded, the record flags `human_edits`. Interpretive notes the model proposes
land in `inbox/` for triage.

## Candidate specs

Small, real, testable improvements to Stead. Each is a build target once
authored and approved.

### 1. `stead context search`

Full-text search over the context objects from the CLI.

```
## Acceptance criteria
- [ ] `stead context search QUERY` lists matching objects with path and a snippet
- [ ] `--repo REPO` limits results to one repo's objects
- [ ] `--json` emits a machine-readable list
- [ ] search is read-only and calls no model and no network
- [ ] a test covers a match, a miss, and the repo filter
```

### 2. `stead metrics --since`

Time-window the dogfood numbers.

```
## Acceptance criteria
- [ ] `stead metrics --since YYYY-MM-DD` counts only records created on/after the date
- [ ] an invalid date is a clear error, not a crash
- [ ] a test covers the filter and the empty window
```

### 3. `doctor` flags an unapproved feature spec

Make the approval gate visible to a hand editor.

```
## Acceptance criteria
- [ ] `stead doctor` warns on a contribution tagged feature-spec with no spec_sha
- [ ] it warns when spec_sha is present but the body changed
- [ ] approved specs produce no warning
- [ ] a test covers all three cases
```

## Baseline (M1.1) and measurement record

Before scoring Set B, run the baseline: the same Set A specs, each from a clean
state, on LFM3-1.7B and on one larger local model. This separates harness limits
from model limits. Record every published result with enough to repeat it:

| Field | Value |
|---|---|
| model (name + quantization) | |
| context length the model loaded with | |
| LM Studio version | |
| harness commit (frozen) | |
| attempts per issue (with each failure's reason code) | |

## Results (real runs)

Model: LFM3-1.7B via LM Studio (local, OpenAI-compatible). Ceiling: `shadow`.

| # | Spec | Mechanically | Spec actually met? | Notes |
|---|---|---|---|---|
| 1 | `metrics --since` | committed, checks passed | **No** | Wrote a stray `stead/metrics.py` (an invented path); never edited `ctx/metrics.py` or `ctx/cli.py`; `stead metrics --since` was still unrecognized. The existing suite passed because nothing tested the new feature. |

**Finding from run 1: green checks ≠ criteria met.** The check command ran the
existing suite, which did not cover the new behavior, so empty work passed.
Mitigations added afterward:

- `require_tests` gate (default on): a code spec with acceptance criteria must
  add a test that fails without the change and passes with it.
- Firmer protocol: plan once, one action per reply, use the real paths from the
  tree, and a progress nudge toward write → check → finish.
- Failed builds now save a full transcript so the next failure is diagnosable.

CI/CD is the independent backstop (see [Trust](trust.md#empty-work-ci-and-acceptance-checks)):
the new test re-runs on the PR, and required CI blocks merge. An **acceptance
check** that exercises the feature itself is still needed to catch a
trivially-passing test.

Aggregate, from `stead metrics --json`: _pending more runs_.

Publish these here and link them from the README once they exist. Until then the
honest claim is the pipeline and the gates, not a success rate.
