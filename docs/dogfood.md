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

- **The build loop works but is not measured.** Two tuning specs built
  correctly on a local 27B model and reached a green, human-merged PR at the
  `pr` ceiling (#20, #30). Two runs are not a reliability estimate; Set B is
  the first scored one.
- **The full path has run once, not been signed off.** #25 went from label
  intake through `spec draft`, approval, build, publish, the issue comment, and
  merge (#30). The frozen sign-off below runs it fresh on issues the harness
  never saw.

## Correctness rubric (fixed before the run)

A build is **correct** when, checked by hand against the built change:

1. every `## Acceptance criteria` item is actually satisfied (not just "checks
   passed");
2. the mechanical fail-before/pass-after gate holds (the new test fails without
   the change and passes with it);
3. CI is green on the PR.

A PR that needed human commits before merge is **not** a first-attempt success.
It is recorded separately as "success with human edits" (the ledger already
detects this by comparing the merged head to the recorded build commit; a
merge that only brings the branch up to date with the base, like GitHub's
"Update branch", is not an edit).

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
# The first run saves the scope, so the dogfood store never pulls in your other repos.
python -m stead --root ../stead-dogfood sync github --repo TheShinySylveon/stead --remember
python -m stead --root ../stead-dogfood sync github
```

When a PR merges — whether by `stead factory merge` or by a human under the `pr`
ceiling — the record's outcome becomes merged, the contribution is marked merged,
the raw issue a spec was drafted from is marked closed (own repos, where the PR
said `Closes #N`), linked tasks close, and the next bundle reads the prior record. A human merge is
picked up by `sync github`; if the PR head SHA differs from the commit Stead
recorded, the record flags `human_edits`. Interpretive notes the model proposes
land in `inbox/` for triage.

## Unattended operation (planned)

The loop is proven by hand (#20, #30, #34). To run it on a schedule — sync →
draft → human approves → build → PR → comment — three pieces are tracked here so
they are not lost:

1. **Schedule for a separate store (Task A, code) — implemented, PR #38 open.**
   `ctx/schedule.py` now changes into the Stead code folder and passes
   `--root "<store>"` to every `stead` call, in both Windows (`cd /d`) and
   POSIX (`cd`) syntax, so a store that is not the code folder (like
   `C:\dev\stead-dogfood`) no longer fails with `No module named stead`.
2. **Settings (Task B) — applied 2026-11-22.** `factory defaults
   --build-minutes 90`, `repo set repo-theshinysylveon-stead --trigger watch`,
   and `schedule install --interval hourly --watch` (the `SteadMonitor` hourly
   task). Note: `--interval` alone is sync-only despite its "sync + watch" help
   text, so `--watch` is required for the build step.
3. **Auto-draft during the monitor run — implemented.** `spec draft --all`
   runs after `sync github` in the monitor cadence and drafts every open
   `stead-build` issue with no draft yet, so the person only approves. It never
   approves.

## Candidate specs

Small, real, testable improvements to Stead. Each is a build target once
authored and approved. These are Set A (tuning), filed as GitHub issues with
the `stead-build` label: 1 is #25 (built as #30), 2 was built as #20, 3 is #27.

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

### 3. `stead inbox list`

Show what is waiting in the inbox.

```
## Acceptance criteria
- [ ] `stead inbox list` lists each inbox note with its file name, kind, and title
- [ ] `--kind KIND` limits the list to one kind (decision, glossary, or note)
- [ ] an empty or missing inbox prints a clear message, not nothing
- [ ] listing is read-only: nothing is moved, edited, or deleted
- [ ] a test covers a listing, the kind filter, and an empty inbox
```

This replaced "`doctor` flags an unapproved feature spec" on 2026-11-22,
before any of it was built: that spec was the same check as frozen Set B #2
(only the tag differed), so tuning on it would have leaked a scoring spec.
Set B is unchanged.

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

### Arete 27B (2026-11-22)

Set A spec 2 (`metrics --since`), the tuning set, so these runs are not scored.

| Field | Value |
|---|---|
| model (name + quantization) | `nousresearch_arete-27b` via LM Studio (quantization not recorded) |
| context length the model loaded with | 64,000 |
| LM Studio version | not recorded |
| harness commit | `06bfddb` (#18), with #15 and #17 |
| call timeout | 1,200 s (`model set --call-timeout`) |

| Attempt | Outcome (reason) | What happened | Fix |
|---|---|---|---|
| 1 | failed (timeout, 437 s) | Good plan; read `ctx/metrics.py` and `ctx/cli.py`; the fourth model call ran past the fixed 300 s limit and surfaced as a raw traceback. | #17: per-model `--call-timeout`, clean message |
| 2 | failed (budget, 90 min) | Wrote a correct `ctx/metrics.py`, then spent 18 of 22 turns re-reading `ctx/cli.py`. Reads stopped silently at 40,000 characters, `cli.py` is 73,000, and `write` replaces whole files, so the command handler at line 942 was never visible or safely writable. | #18: line-range `read`, a cut-off notice, exact-snippet `edit` |
| 3 | committed, **correct** | 34 minutes, about 20 turns, no repair rounds. Searched, read `cli.py` lines 620–632 and 938–958, changed both with `edit`, added `tests/test_metrics_since.py` (fails before, passes after), checks passed. | — |

Attempt 3 was hand-checked against the rubric (`--since 2026-11-22` counts 4 of
5 records; `--since banana` prints a clear error and exits 1; full suite green),
published at `pr` with `factory publish` as #20, passed the required checks
after "Update branch", and was merged by a human. `sync github` recorded it as
merged with `human_edits: false`.

Other gaps the same day, fixed: a killed rebuild could wedge the spec on a
stale record (#15); `factory publish` did not save the PR url, so the merge
would never reconcile (#21); and `sync github` pulled every open PR the user
had into the dogfood store (#22, `--repo` with `--remember`).

### Set A spec 1 on Arete 27B (2026-11-22)

`stead context search`, from GitHub issue #25. Tuning set, so not scored. The
first run of every loop step on a real issue:

- `sync github --repo TheShinySylveon/stead` picked up the labelled issue.
- `spec draft` (one model call) wrote the spec. Its plan named
  `stead/context/search.py` and `stead/cli.py`, paths that do not exist; a
  person fixed the plan before approving, and #26 now shows the drafter the repo
  tree and flags such paths.
- The build took 27 minutes, 15 model steps, and no repair rounds: it searched,
  read `ctx/cli.py` in two ranges and `ctx/objects.py`, wrote `ctx/search.py`,
  made two `edit`s to `cli.py`, and added six tests that fail before the change
  and pass after it.
- Hand-checked correct. One recorded deviation: `--repo` also counts a body line
  that reads exactly `repo: X`, beyond "a `repo` field or `repo:` tag".
- `factory publish` opened #30 with `Closes #25`, `factory comment` linked it
  on the issue, CI passed on Linux and Windows, and a human merged it. `sync
  github` recorded it as merged with `human_edits: false`.

Aggregate, from `stead metrics` (2026-11-22): 7 builds, 3 merged, 3 correct, 1
incorrect (the LFM3 run above), 3 failed (2 build-class, 1 infrastructure), 0
merged after a human edit.

### Set A spec 3 on Arete 27B (2026-11-22)

`stead inbox list`, from GitHub issue #27. Tuning set, so not scored. The same
real loop as #25, on the first attempt:

- The first `spec draft` produced a 10-criteria spec that approval accepted and
  the build then refused as `large-spec`; #35 now makes `spec approve` refuse the
  same body and tells the drafter the at-most-8-criteria limit.
- The build took 51 minutes and 23 model steps with no repair rounds, and added
  `tests/test_inbox_list.py` (fails before the change, passes after it).
- Hand-checked correct. `factory publish` opened #34 with `Closes #27`,
  `factory comment` linked it on the issue, CI passed, and a human merged it.
  `sync github` recorded it as merged with `human_edits: false` and closed the
  store's copy of issue #27 (#31).

Three tuning builds are not a success rate. The first published score is Set B,
on a single first attempt each.
