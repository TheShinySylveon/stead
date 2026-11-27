# Trust, isolation, and what leaves the machine

Stead can write code and, when a repo says `reach: merge`, merge it. This page
states what is trusted, what is not, and which control stops which failure. It
is deliberately narrower than "safe": a local tool that runs a model is not a
sandbox, and this page says where the sandbox ends.

## The model is not trusted

Everything the model produces is treated as untrusted input:

- It answers with JSON actions. It cannot choose a shell command.
- It may only write inside the repo's `code_path`. `..`, absolute paths, and
  `.git` are refused.
- It must plan before it writes.
- Its writes to existing tests, CI config, and paths the repo marks protected are
  refused (see below). Adding a brand-new test file is allowed. Files that look
  like secrets (`.env`, `*.pem`, `*.key`, `id_rsa`, `credentials.json`) are hidden
  from the tree, search, and read, and cannot be written or deleted.
- Merge is a separate command that re-reads the pull request from GitHub. A
  model cannot ask `stead build` to merge past the repo ceiling.

## Who makes a spec buildable

A synced issue cannot become a build target by itself. `stead build` requires
all of these:

- the contribution is `kind: issue` and **enabled** — tagged `feature-spec`
  (locally authored) or `stead-build` (the GitHub label, synced);
- its body has a description and a `## Acceptance criteria` checklist;
- its repo has `code_path` and a ceiling above `shadow`;
- **a person approved this exact body** with `stead spec approve`.

Approval stores a SHA-256 of the body (`spec_sha`). Any later edit or sync that
changes the body invalidates the approval, so the model never builds text
nobody approved. The `author` role and the `feature-spec`/`stead-build` tags are
**labels, not permissions**: anyone with file access can set them. The hash is
the gate.

For a public repo, that is the real control against prompt injection through an
issue body: a person decides the text is a spec before any model reads it as
one. Everything that is not the approved spec — repo notes, related documents,
prior builds, sibling issues — is marked **untrusted context**, and the prompt
tells the model to treat instructions inside it as data. This holds for the
`stead build` agent too: it reads the approved spec body plus the repo
conventions, related documents, and prior build records, with the non-spec
sections marked untrusted.

## Checks run untrusted code

The repo's `checks:` command is chosen by the repo owner, not the model. But
the command usually runs code the model just wrote, so treat a check run as
code execution with the permissions of your user account.

| Control | Default | What it stops |
|---|---|---|
| Scrubbed environment | On | Checks cannot read `STEAD_MODEL_API_KEY`, `GH_TOKEN`, cloud keys, or the deployment token from the environment. Only `PATH`, home, temp, locale, Windows system variables, and `checks_env:` are passed. |
| Container isolation | Opt-in: `checks_isolation: docker` + `checks_image` | Checks get no network, dropped capabilities, a PID limit, and a memory/CPU cap. The checkout is mounted at `/src` so the checks can read and write it, but `.git` is mounted read-only. A timed-out container is named and killed, not left running. |
| Git hygiene | On | Every Stead git call (build, publish, merge, watch) runs with the checkout's hooks and fsmonitor disabled, so a planted hook or `core.fsmonitor` never executes on the host. Every check run is bracketed by a `.git/config` and hooks snapshot. Any hook change, and any config setting other than branch tracking (`branch.*`) or identity (`user.*`), fails the build and is restored, in host mode too; config is compared by its parsed settings, so a person's `git push -u` during a build is not mistaken for tampering. |
| Commit boundary | On | `finish` requires HEAD to still be where Stead left it, stages only the model's own writes (`git add -A -- <paths>`), and refuses a tracked change the checks made; protected or secret paths fail hardest. Untracked leftovers are removed, not staged. The ledger (`tests_touched`, `ci_touched`, the file list) comes from the committed range `base..HEAD`, and a branch whose HEAD moved is reset. |
| Wall-clock budget | 4 hours (240 minutes) per build | A repair loop cannot run forever. `--max-minutes` changes it; watched builds use `build_minutes`. |
| Step, edit, and prompt caps | 300 steps, 1 MB written, 1M prompt chars (~250k tokens) | A model cannot loop, dump unbounded output, or grow the resent transcript without bound; older read outputs are trimmed first. |
| Token and cost budget | 10M tokens per build; USD off until prices are set | Each build accumulates token usage (provider-reported, else estimated from characters) and aborts past the budget. Set prices with `stead model set --input-price/--output-price`; override per build with `--max-tokens`/`--max-cost`. |
| Stop file | `.stead-stop` | A build and a watched run stop between steps. `stead factory stop` creates it. |
| Worktree build | On | Every build runs in its own `git worktree`; the user's checkout is never touched and Stead never runs `git clean`. A failed build commits its WIP to the build branch (kept, never pushed) and drops the worktree. A "started" marker is reclaimed as an infrastructure failure record if a build was killed (Task Scheduler/Task Manager). |
| One attempt per hash | On | A build-class failure blocks a re-run of the same approved content until re-approval (a new hash) or `--retry`. Infrastructure failures and precondition failures write no record and don't consume the attempt or the daily budget; real failures carry a `reason` code. |

The container is not available for every repo (it needs Docker and an image
with the toolchain). The honest statement is: **without
`checks_isolation: docker`, checks run on your host with a scrubbed
environment, not in a sandbox.** A scrubbed environment hides secrets from
the process environment, but it does not restrict the filesystem: host checks
can still read any file your user can read, such as `~/.ssh` or
`~/.config/gh`. Only the container limits them to the checkout and the image.

**`checks:` must work from a clean clone.** Every build runs in a fresh worktree,
so untracked local state (`.venv`, `node_modules`, `.env`, build output) is
absent. A check that depends on that state fails as "the base suite is red".
**The fail-before gate has a known limit:** a new test that merely imports a
new module fails on the base with an `ImportError` and passes on the branch
whatever it asserts — the gate sees that as a real fail-before. The hand check
in the rubric covers what the gate cannot.

## Protected paths

A model that can edit its own gate can pass it. By default these are refused:

- `.github/**`, `.gitlab-ci.yml`, `.circleci/**`, `azure-pipelines.yml`,
  `.buildkite/**`, `Jenkinsfile`
- `tests/**`, `test/**`, `spec/**`, `**/conftest.py`, `**/test_*.py`,
  `**/*_test.py`, and the common JS/TS test file names

A repo can opt in with `allow_test_edits: true`, `allow_ci_edits: true`, or
`allow_protected: true`, and can add its own paths with `protected_paths:`.
When tests are allowed, the build records `tests_touched` in its run log.

Adding a **brand-new** test file is allowed by default: that is the discipline
`require_tests` asks for, and a new file does not weaken an existing test.
Editing or deleting a test that existed at the base commit stays refused; a
test file the build created may be revised or removed, which is the normal
write-test, see-it-fail, fix-it loop. `conftest.py` and `__init__.py` change how
other tests run, so they are never "new test" additions; an explicit
`protected_paths:` entry always wins. A case variant that would collide with a
tracked path on macOS/Windows (`TESTS/test_app.py` beside `tests/test_app.py`)
is refused on Linux too. Matching is case-insensitive on every platform
(`.GitHub/...`, `TESTS/...`, `.ENV` are protected too) and checks the
symlink-resolved path, so a symlinked directory inside the repo cannot sidestep
`tests/**`.

Protection on the **tool** is not enough: checks execute model-written code,
and that code can change any file. So the commit step enforces the boundary
too — it stages only the model's writes, refuses any other change the checks
made, and computes `tests_touched`/`ci_touched` from the real diff.

The checks command itself lives in the repo's frontmatter, outside the
checkout, so the model cannot rewrite it. If `checks:` calls a file the model
can edit (`make test`, `npm test`), add that file to `protected_paths:`.
`stead repo set` warns when the command names a runner whose config is present
but unprotected (`make` → Makefile, `npm`/`yarn`/`pnpm` → package.json,
`pytest`/`unittest`/`tox`/`nox` → conftest.py, pyproject.toml, tox.ini,
noxfile.py, setup.cfg, pytest.ini). Protection is opt-in, so the warning is
there to catch the files you would otherwise miss.

## What counts as a build attempt

Only a run that reached the model is a build attempt. A precondition failure
(dirty checkout, no approval) and an infrastructure failure (the model is
unreachable) do not write a build record, do not spend the daily budget, and
remove the empty branch so the spec stays eligible for the next run. A run that
reached the model and failed writes a record with a reason code — `protocol`,
`gate`, `checks`, `budget`, `tamper`, or `infrastructure` — quarantines its work
in progress on the branch, and spends the budget.

## Merge gates

The workflow requires addressing all actionable human and bot PR comments before
merge (see `AGENTS.md`). A green review-bot check only means the check completed;
it is not proof the feedback was addressed. This is a workflow requirement, not
an automatic comment-resolution check in `stead factory merge`.

`stead factory merge` checks the following:

1. The repo file says `reach: merge`. Merge is never inherited from the install
   default.
2. The build runs from a non-default branch, and the pull request's head is
   that branch, based on the default branch.
3. Every reported check is green.
4. The checks run is trusted: `checks_isolation: docker`, or the repo
   explicitly sets `trust_checks: host`.
5. The default branch has required status checks — read from branch protection,
   or from the branch rules API (rulesets) when protection is not readable.
   Otherwise "branch protection is not bypassed" would protect nothing. A repo
   can acknowledge that with `merge_without_required_checks: true`.
6. The pull request head still equals the commit Stead built and recorded. The
   merge passes `--match-head-commit <sha>`, so a head that moved (a human
   pushed edits) is refused rather than merged unreviewed.
7. An **independent reviewer** approves the diff. That is a separate model
   invocation with a fresh context (the builder's transcript is never reused),
   given only the approved spec and the diff; it must confirm every acceptance
   criterion and that tests/CI were not weakened. A reject blocks the merge. A
   repo can opt out explicitly with `merge_without_review: true`; the reviewer
   model is `stead model set --review`, falling back to the builder model.

The command never passes `--admin`, never pushes the default branch, and never
merges a draft.

## Empty work: CI and acceptance checks

A build can pass the repo's checks and still not implement the spec. Observed in
dogfood: the model added a stray file at an invented path, never wired the
feature, and the existing test suite passed because nothing tested the new
behavior. Green checks are not the same as criteria met. The mitigation is a
stack, not one trick:

1. **Force coverage locally.** `require_tests` (default on) refuses `finish` on a
   code spec with acceptance criteria until the build adds a test. The test
   should fail without the change and pass with it, so the suite grows to cover
   the criterion. A repo can opt out with `require_tests: false`.
2. **Protect the gate.** `.github/` and CI config are protected paths, so the
   model cannot edit the workflow to make CI pass.
3. **CI as an independent required check.** The pull request triggers the repo's
   real CI, which re-runs the suite (including the new test) on a clean runner.
   If the feature is not wired, the new test fails and the PR is red.
4. **Merge gated on green required checks.** With CI as a required status check
   on the default branch, red CI blocks merge — a human cannot merge it without
   overriding branch protection. At the `pr` ceiling Stead opens the PR and a
   person reviews; CI is the objective backstop.

What CI cannot close: a model-written test can be trivially passing or test the
wrong thing, and CI runs whatever test was written. The merge gate now includes
an **independent reviewer pass** (a fresh invocation that must approve the diff
against the spec), which raises the cost of empty work. It is not a proof. The
remaining piece is an **acceptance check** that exercises the actual feature
independent of the model's tests — a per-spec `acceptance:` command (for
example, run the new CLI flag and assert the behavior) executed in CI. That
criterion→test mapping is still to build. `stead build --wait` can poll PR
checks and record the outcome in the ledger.

## GitHub writes beyond opening a PR

Today the remote writes are `publish` (push an isolated branch, open a PR),
`merge`, and the gated issue **comment**. Sync is strictly read-only. From the
cockpit, publish, merge, and comment are reachable behind an explicit
confirmation and are refused on a shared server; they are otherwise the same
gated commands. The
[MVP](mvp.md) requires Stead to **comment on the source issue linking the PR**
so a human can merge and close together; filing issues upstream is deferred
(humans file issues for now). The comment is gated like publish/merge: explicit
per-repo `allow_comment: true`, `kind: own` only, never from assembly, never the
default, and idempotent (one marked comment, updated in place). Before posting,
one read-only lookup verifies the number is a real upstream issue; a local-only
spec (no issue, or a number that belongs to a PR — the number space is shared)
is skipped cleanly, never posted onto `pull/<N>`. It carries no CI status today
— a stale status is worse than none — but the marked comment is the place CI
status could later be refreshed on `--wait`. It is lower-risk than merging but
is still a public remote write under the user's identity.

## Shared server: every account is an admin

`stead ui --deploy` and the Docker image serve several people. Accounts are
names with scrypt password hashes and a session cookie. There are no
per-object permissions, no roles, and no approval queue for context edits.

- Any signed-in person can edit any context object.
- Factory runs from the cockpit are shadow-only and never push.
- **The cockpit refuses to start a build on a shared server.** A build runs
  model-written code on the host. `STEAD_ALLOW_SERVER_BUILD=1` overrides this
  for a server you fully trust; do not set it for a team you do not control.
- **Execution fields are read-only in the cockpit on a shared server:**
  `checks:`, `checks_isolation`, `checks_image`, `protected_paths:`,
  `trust_checks`, the `allow_*` flags, reach, trigger, `code_path`,
  `default_branch`, the contribution `author` role, authoring a spec with
  acceptance criteria, spec approval, **the model endpoint, and the install
  factory defaults**. The model endpoint matters because the configured model
  (and its key) drives every scheduled build on the host; the install defaults
  set trigger and reach for every repo without explicit values. Setting a model
  also drops the stored key whenever `base_url` moves to a different host, so a
  key never rides along to a new endpoint. Edit all of these on the machine that
  runs builds.
- Put the server behind a reverse proxy that terminates TLS and does SSO if
  you expose it. The built-in server speaks HTTP, has no login rate limit, and
  is not hardened for the public internet.

## What leaves the machine

Nothing is sent to the Stead authors. There is no telemetry. The only
outbound calls are the ones a command makes:

| Command | What is sent | Where |
|---|---|---|
| `stead sync github` | Read-only `gh` queries for your PRs, reviews, and issues; read-only PR state to reconcile build records (merged/closed, human edits) | GitHub, through `gh` |
| `stead factory run --generate` | The assembled prompt: digest = cached public contributions; project status = one project's tasks, documents, meetings; feature-builder = spec, criteria, repo notes, related documents | Your configured model endpoint |
| `stead build` | The system prompt, the approved spec body, repo conventions and related context (marked untrusted), the repo tree, every file the model reads, and check output | Your configured model endpoint |
| `stead eval judge` | The draft and its pass criteria | Your configured model endpoint |
| `stead ui` | Nothing. The page has no external assets. | Loopback, or your own container |

`stead model set --provider ollama` keeps every prompt on the machine. The
feature-builder bundle can contain private documents on purpose: they are what
makes the build good. The bundle is local, and it is sent only when you run a
model step. The pull request body Stead opens is fixed text and the public
spec title; it never includes private notes.

## How the public/private split is enforced

- `context/contributions/` and `context/repos/` are the public layer.
- `context/documents/`, `context/meetings/`, `context/tasks/`, and project
  bodies are private.
- The digest assembler reads only contributions and repo metadata, so private
  notes cannot enter it. A test covers this.
- The feature-builder bundle deliberately includes related private documents so
  the build has context. It is marked as possibly private and is not published.
- The wiki is a projection over the same files. It has no separate store, and
  its change requests are ordinary private documents.

## Write-back has a human gate on interpretation

A delivered build writes **facts** back automatically: a versioned
`build-record` document, the contribution state on merge, and linked task
status. A failed build writes a record too (with its error class), so the
ledger has a failure rate. `stead factory merge` updates the record to merged;
a human merge under the `pr` ceiling is reconciled by `stead sync github`,
which also flags a human edit when the PR head differs from the recorded
commit. Prior records feed the next bundle for that repo.

Anything **interpretive** — a decision, a glossary term — the build may only
*propose* as an inbox note. A person triages it into `context/documents/`. The
agent cannot quietly rewrite the context that later builds depend on.

## Known gaps

What is built versus deferred is tracked in [MVP](mvp.md); these are the
residual risks of the design, not the project status.

- The independent reviewer is a separate model invocation, not a guarantee: it
  can be fooled by a plausible diff, and unless `stead model set --review` names
  another model it shares the builder's endpoint. The per-spec acceptance check
  is still to build.
- No token or dollar budget is enforced by the provider itself. Stead counts
  usage (provider-reported, else estimated from characters) and aborts past
  `max_tokens_per_build` (default 10M) or `max_cost_per_build_usd` (off until
  prices are set). A provider-side quota is still worth setting for defense in
  depth.
- No per-object permissions or roles on the shared server.
- No login rate limiting, TLS, or CSRF token beyond the custom `X-Ctx-Token`
  header and `SameSite=Lax` session cookie. Use a proxy.
- Container isolation is per repo and opt-in, not enforced globally. Host
  checks can still read any file your user can read.
- A model can still write a test-shaped file outside the protected globs if the
  repo's layout is unusual. Add it to `protected_paths:`.
