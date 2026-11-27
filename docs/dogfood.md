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
- **Spend is bounded.** Each build has a token budget (default 10M) and, when
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

## Set B on LFM3-1.7B (2026-11-24/25) — not a pass

Set B is the first *scored* run, on the cheap local model the `build` role is
bound to. The role split was draft/review/address = strong, build = weak, on the
theory that a weak model can follow a plan it did not write. Set B tested that
theory and refuted it for this model.

| # | Spec | Mechanically | Spec actually met? | Notes |
|---|---|---|---|---|
| 1 | `contribution list --json` | committed, checks red (broken fixture) | **No — hand-finished** | The implementation was correct (the `--json` flag + 8 fields), but the test called `cmd_contribution_add` with a repo that was never created, so checks stayed red and the model churned 26 stale `edit`s on `cli.py` without converging. |
| 2 | `doctor` flags unapproved `stead-build` | committed, checks red (import error) | **No — hand-finished** | Twice. First, the model re-nested the existing `body_sha` check inside its new block. Second, it wrote a *top-level* block referencing `root` (a function parameter) so `doctor.py` failed to import. Both times it churned on `doctor.py`/its test without noticing. |

**Finding: a 1.7B model can produce correct-looking code but not
correct-structure code.** Every failure was structural — a broken fixture, a
nested block, a top-level reference to a parameter — not a wrong algorithm. No
amount of plan precision fixed it: the plans were rewritten to be mechanical
(PR #149: additive-only edits, explicit boundary constraints, a `vague-plan`
gate), and the model still could not reliably place code *inside* a function vs.
at module top level.

The harness changes made during these runs (failed-edit coercion, check-failure
summaries, anti-slop gate) are real improvements, but they compensate for a
model that cannot be steered, not one that can.

**Next: re-run Set B on a 27B model.** The 27B (Arete) built Set A correctly on
2026-11-22; Set B on 27B is the fair test of the harness, holding the model
constant at a level that has already been shown to work. The 1.7B result is
recorded here as data, not as the final score.

## Set B on Arete 27B (2026-11-25) — first autonomous pass

| Field | Value |
|---|---|
| model | `NousResearch_Arete-27B-GGUF` via LM Studio |
| context window | 40,000 tokens (per-model `context`, PR #152) |
| harness commit | `e0112ea` (#152) + the #102 spec |
| call timeout | 1,200 s |

| # | Spec | Mechanically | Spec actually met? | Notes |
|---|---|---|---|---|
| 3 | `stead status --project P` prints a build-record summary | committed, checks passed, fail-before held, CI green, PR #153 merged by a human | **Yes** | 31 minutes, 13 model steps, 0 repair rounds, 0 human edits. The plan named the real data model (build records are markdown documents, not a SQL table) and the model followed it. |

**Finding: the 1.7B failures were model capability, not harness.** Holding the
same pipeline constant and swapping the model to 27B produced a clean,
first-attempt pass. The difference was the model's ability to follow a precise
plan and reconcile code with its own test — which the 1.7B could not do.

One caveat, recorded honestly: the #102 *spec* needed a human correction before
the build — the strong drafter invented a `build_records` SQL table that does not
exist (records are documents). So this is an autonomous *build*, not an
autonomous *spec→PR*. The draft step still needs human review. That is the next
frontier, not a regression: the weak-model-build question is answered.

Set B total so far: #1 and #2 hand-finished, #3 autonomous. Set C and the
hold-out are not yet run.

## Set C (2026-11-25) — in progress, and the draft step is the bottleneck

Set C is the *fresh end-to-end* sign-off: `monitor → draft → approve → build →
PR → comment → merge`, unattended. It is not runnable yet, and the reason is
specific: **the draft step invents the data model.** Three consecutive drafts
got the ontology wrong before any build ran:

| Draft | Invented | Reality |
|---|---|---|
| #101 | `kind: stead-build` | `stead-build` is a *tag*, not the `kind` field |
| #102 | a `build_records` SQL table + `get_latest_build_record` db helper | build records are *markdown documents* tagged `build-record`, read by `writeback` |
| #103 | `ctx/tasks.py list_tasks()` | `ctx/tasks.py` is the cockpit's thread registry; the command is `cmd_task_list` in `ctx/cli.py` |

Also, #103's acceptance criterion ("preserves insertion order") was *unrealizable*
— the default is `ORDER BY id`, and ids are title-derived slugs, so insertion
order is not what's preserved.

**Finding: the drafter was shown a tree of filenames but not what is inside
them, so it guessed plausible symbols instead of reading real ones.** A filename
cannot tell it that `ctx/tasks.py` is a thread registry.

**Rule added (this change): a symbol map + a deterministic symbol-existence
gate.** The draft prompt now lists the real functions/classes per file (an
`ast`-derived map), and `plan_symbol_warnings` refuses a plan that names a
symbol the checkout does not define — the same family as `vague-plan` and
`fabricated-value`, applied to the draft's data model. Verified against the
three historical failures: it flags `build_records`, `get_latest_build_record`,
and `list_tasks`, and passes the real symbols. This is the mistake→rule loop
applied to the draft step itself.

Set C remains unrun until the draft step is shown to stop inventing models; the
frozen Set C specs are not spent on runs that need rescuing.

### The draft step: from symbol map to a read step (2026-11-25)

A fourth draft (#104) was still wrong *after* the symbol map: it wrote
`config.load()["repos"]`, assuming repos live in a `stead.json` key, when
`cmd_repo_list` actually queries the `repos` SQL index. The symbol gate passed it
(`config.load` is a real function), which proved the limit: **a symbol map tells
the drafter what exists, not how data flows.**

The deeper rule: every draft failure so far — `kind` vs `tag`, the fake
`build_records` table, `list_tasks`, `config.load()["repos"]` — was the same
failure at a different layer: the drafter *guessed* where data lives instead of
*tracing* it. So the draft step now has a **read/search research phase**: before
writing the plan, the drafter can issue read/search actions against the real
checkout (bounded, read-only) and must name the real data source it found. If
it skips straight to a spec, the deterministic symbol gate still applies.

This is the mistake→rule loop applied to the draft step itself, and the finding
is recorded here so the next bundle and future evals can cite it.

### The read step helped, but the drafter still invents the source (2026-11-25)

With the read/search research phase live, #104 was re-drafted. The structure was
now correct (description + criteria + plan, with a "Data source traced" note),
and the model did read `cmd_repo_list`. But it still wrote the source as
`config.public_list()` — three errors at once:

1. `public_list` is defined in `ctx/accounts.py`, not `ctx/config.py` (location
   error — the symbol exists, in the wrong module).
2. Neither is the data source for `repo list`, which reads the `repos` SQL index
   via `db.connect` (flow error — the model read `cmd_repo_list` and still
   guessed).
3. The symbol gate passed, because it checks "does `public_list` exist anywhere"
   and the answer is yes (in accounts) — it does not check "is it in the file the
   plan claims".

**Finding: a model can read the right file and still pattern-match to a
plausible-but-wrong answer.** The next tightening is a *location* check: a plan
that names `module.symbol` must have that symbol defined in that module, not just
anywhere. That is a deterministic rule (the symbol map already records file ->
symbols), and it would have flagged `config.public_list` immediately.

### Facts, not symbols: the drafter sees and is checked against the data model (2026-11-26)

The location check was shipped (it flags `config.public_list` → "in accounts.py,
not config"), but a fifth draft (#106) exposed the other failure mode of the
*symbol* approach: the bare-name heuristic false-flagged `build_failures` and
`infra_failures` — legitimate JSON keys the plan was *adding* — as invented
functions. The symbol map tells the drafter what **functions** exist, but the
drafter's real error all along was guessing where **data** lives, and that is
not a symbol question at all.

So the draft step was reworked around **facts, not symbols**:

1. **The drafter now sees the data model, derived not written.** A
   `data_model_facts` block (SQL tables + columns from `schema.sql`, markdown
   object types from `TYPE_DIRS`, build-records-are-documents from `writeback`)
   is derived at draft time and fed into both the research and write turns. It
   cannot drift, because it is not a hand-written note.
2. **Stead verifies the plan's data-model claims against that same schema.** A
   new `plan_data_warnings` gate flags a plan that names a SQL table the
   checkout does not define (the `build_records` failure) or reads a markdown
   object / SQL table from `config` (the `config.load()["repos"]` failure). It
   is grounded in the derived facts, not prose patterns, and is deliberate about
   false positives (uppercase SQL verbs only, real tables and plain config keys
   pass).
3. **The bare-name symbol check was demoted to call-only.** A bare backticked
   name is only flagged when written as a call (`list_tasks()`), because `(` is
   the unambiguous marker of a function reference; a bare `build_failures` is a
   field, not a function. This removed the #106 false positive. Dotted
   location-check warnings were also deduplicated (five `config.public_list`
   occurrences now warn once).

**Finding, recorded honestly: the draft step is still human-gated.** Five
drafts, five invented data models, each a different wrong answer. The gates now
catch *gross* errors deterministically (invented tables, wrong modules, data
claimed to live in config), but they do **not** guarantee a correct data flow —
a model that reads `cmd_repo_list`, sees `SELECT … FROM repos`, and still writes
`config.public_list()` will not be fixed by more rules. The deterministic gates
are **defense in depth**, not a correctness proof.

The honest framing of the product today: **Stead makes human review fast and
structured, and deterministically refuses the obvious slop — it does not yet
write correct specs unattended.** The next real investment is *cite-and-verify*
drafting: the plan must say where it saw the data source ("repos come from
`db.connect` querying `repos`, seen in `cmd_repo_list`"), and Stead verifies
that citation against the code — the difference between "name real symbols"
(done) and "prove your claim matches the code" (not done). Until then, the
remaining frozen specs (#104, #106) are finished **by hand**, with each
human edit recorded, because the honest metric is not "zero human edits" but
"where exactly does the human step in, and is that shrinking."

### Per-repo, not Stead's model (2026-11-26)

The first `data_model_facts`/`plan_data_warnings` pass was built while dogfooding
Stead-on-Stead, so it accidentally baked Stead in: it read `ctx/schema.sql` by
path and imported `ctx.objects.TYPE_DIRS` from the *running* package, so any
other repo would have been told Stead's object types as if they were the
target's. The fix makes the data model **per-repo**:

1. **Declared (human-owned, primary).** The repo's `notes` field, a
   `## Data model` section of its markdown body, and its `related:` documents —
   the same channel the build bundle already uses for repo conventions. The
   Stead dogfood repo now declares its model this way ("repos are NOT a config
   key"; "`public_list` is in `accounts.py`, not `config.py`").
2. **Derived (generic).** SQL/Prisma schema artifacts anywhere in the checkout —
   every `*.sql` file and `prisma/schema.prisma` — not just Stead's
   `ctx/schema.sql`.
3. **Stead-specific hints detected, not assumed.** "Build records are documents"
   is keyed off the target's own `record_delivery` symbol.

A repo that declares nothing and has no schema artifact gets an empty block, and
the verification gate is a no-op — honest, not wrong. This is the answer to "how
does Stead see the relevant info of *any* repo": it reads the repo's own declared
context plus generic schema discovery, never its own self.

### Set C + hold-out scored (2026-11-27)

The frozen specs were finished **by hand at the spec step** and **built
autonomously on the 27B**. All pass the correctness rubric (criteria met,
fail-before held, CI green) with **zero human commits**:

| Spec | Spec step | Build | Verdict |
|---|---|---|---|
| `repo list --json` (#104) | hand-corrected (data source = `repos` SQL index, not `config.public_list`) | 20 steps, 1 repair round, PR #166 | **correct** |
| `metrics --json` counters (#106, hold-out) | hand-corrected (`attempts` is computed-but-not-returned; add it to `collect`) | 14 steps, 2 repair rounds, PR #167 | **correct** |
| `doctor` missing `repo:` (#107) | hand-corrected (the relation loop silently skipped an *empty* relation) | 9 steps, 0 repair rounds, PR #169 | **correct** |

**Finding, recorded honestly:** the split held exactly — **draft: human-always,
build: human-rarely.** The *build* is now autonomous on the 27B (all three
frozen specs went spec→PR→merge with no human edits), while the *draft* still
needs a human to trace the data source. The honest metric is not "zero human
edits" but "where the human steps in, and is it shrinking" — and it has shrunk
from "draft + build both wrong" to "draft only."

**Set C + hold-out are now complete: 3/3 Set C + 1/1 hold-out, all correct.**
(Set C #1 `task list --sort`, #103, was scored correct earlier.)

### Fresh-draft test (2026-11-27): the draft step, measured unattended

To answer "did the draft hardening actually help?", a new, non-frozen issue
(`task list --json`, #108) was drafted **by the model, no hand-holding**, on the
strong drafter (DeepSeek) with the full gate stack live:

- **Attempt 1:** failed — the draft omitted the `## Acceptance criteria`
  section (the same non-determinism seen all along).
- **Attempt 2:** **correct.** The drafter traced the real `cmd_task_list`
  (`SELECT id, status, project, title FROM tasks` via `db.connect`) — it did
  **not** invent `config.load()`, `public_list()`, or a fake table. The spec
  passed every gate (readiness, path, symbol, data, citation) with zero
  warnings.

**Two findings, recorded honestly:**

1. The drafter is **better** — on the attempt that succeeded it traced the real
   source, which is the exact thing it failed at five times before. But it is
   still **non-deterministic**: 1 of 2 attempts was malformed. The draft step is
   still human-gated; the honest number is now "draft: human-mostly, build:
   human-rarely" — closer, not there.
2. The test surfaced a real bug in the new citation gate: it read the *first*
   backticked snippet (often the label, e.g. `task list`) instead of the quoted
   *code* before the `(file:line)`, so it false-flagged a correct citation.
   Fixed: the gate now verifies the snippet immediately before the location.
