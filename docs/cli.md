# CLI

Run from the repository root. Python standard library only.

```bash
python -m stead
python -m stead version
python -m stead --help
python -m stead <command> --help
```

`--root` defaults to the current directory. Point it at a checkout if you are
not standing in one.

## First run and setup

```bash
python -m stead ui [--no-browser] [--port N] [--deploy]
python -m stead welcome --title "My Project" [--url URL] [--deployment single|multi]
python -m stead init
```

`ui` opens the cockpit at **http://127.0.0.1:8765/** — port **8765** by
default, printed at startup. `--port N` changes it; `stead.json` can also
set `port`. On an empty checkout it shows Welcome. Without
`--deploy` it stays on loopback, even if `stead.json` says multi.
`--deploy` is the shared server. It refuses to start unless an account
exists, or `STEAD_ACCESS_TOKEN` is set for a server that has no accounts yet.
Prefer Docker. See [Deploy](deploy.md).

`welcome` creates one project and a repo record. It does not run Spec Kit.
`--deployment multi` prints an access token once and tells you how to start
the container. It does not open the port on this computer.

`init` rebuilds `state.db`. If there are no projects, it prints the welcome
commands.

`python -m stead doctor` lints the markdown store without touching it: broken
frontmatter, missing required fields, duplicate ids, dates that are not dates,
and `project:` / `repo:` relations that point at nothing. It exits 1 when there
are errors. Add `--json` for a machine-readable report.

Full project plus constitution, optional `specify init`:

```bash
python -m stead onboard --title "My App" --kind own|oss \
    [--url URL] [--path DIR] [--method spec-kit|builtin] \
    [--integration claude|copilot|gemini|codex|generic] [--no-specify]
```

See [Spec Kit](spec-kit-workflow.md).

## Tasks, repos, contributions

```bash
python -m stead task add --title T --project P [--status to-do|doing|done|blocked]
python -m stead task list [--project P] [--status S]
python -m stead task set ID --status S

python -m stead repo add --title T [--url URL] [--kind own|oss] \
    [--status active|paused|archived]
python -m stead repo list [--kind own|oss]

python -m stead contribution add --title T --repo REPO --kind issue|pr --number N \
    [--role author|assignee|reviewer] [--state open|closed|merged] \
    [--ci pending|pass|fail|none] [--review requested|approved|changes|none] \
    [--method spec-kit|builtin]
python -m stead contribution list
python -m stead contribution set ID [--state S] [--ci C] [--review R] \
    [--role R] [--method spec-kit|builtin]

python -m stead delete TYPE ID [--force]
```

`method` chooses tooling for feature-builder. It does not turn planning off.
Omitted, it is `spec-kit`.

`delete` removes one project, task, document, meeting, repo, or actor file and
its index row. Git history keeps the old text. A project with linked objects,
or a repo with cached contributions, is refused unless `--force`. Cached
contributions are not deletable; refresh the cache instead.

## Search

```bash
python -m stead context search QUERY [--repo ID] [--json]
```

`context search` is read-only. It scans the `context/` markdown objects for a
case-insensitive query in a title or body, and prints each match's path and a
one-line snippet centered on the match. `--repo ID` limits the scan to one
repo's objects (the repo file plus any object that references it through a
`repo:` field or `repo:` tag); an unknown repo id is an error. `--json` emits
one object per match with `id`, `type`, `path`, and `snippet`. It calls no
model, touches no network, and writes nothing — it does not even create
`state.db`.

## People, status, and GitHub

```bash
python -m stead actor add --title "Ada" --kind human|agent
python -m stead actor list
python -m stead actor use actor-ada
python -m stead account add --name ada --actor actor-ada
python -m stead account list
python -m stead account reset --name ada

python -m stead status PROJECT
python -m stead sync github [--author @me] [--limit N] [--digest]
python -m stead sync github --repo OWNER/NAME [--repo ...] [--remember]
python -m stead sync github --all-repos [--remember]
python -m stead sync github --offline
```

`sync github` is read-only. It uses `gh`. `--offline` only re-indexes files
already on disk. `--digest` assembles the digest only when the cache changed.
It still does not post.

By default it caches your open PRs, review requests, and assigned issues from
every repo. `--repo OWNER/NAME` (repeatable) limits one run to those repos;
nothing outside them is written, not even a repo file. `--remember` saves that
list as the store's scope in `stead.json`, so a plain `sync github` (and the
scheduled job) stays inside it. `--all-repos` ignores the saved scope for one
run, and `--all-repos --remember` clears it.

`actor use` remembers who is writing on this computer. Later writes stamp
`actor:` when that file exists. `account add` is a shared-server sign-in for
one actor. The password is printed once and stored as a hash in gitignored
`private/accounts.json`. `account list` never prints it. This computer does
not ask for that password.

Scheduling is under [Capture and schedule](#capture-and-schedule).

## Factories and models

```bash
python -m stead model show
python -m stead model set --provider openai|anthropic|grok|openrouter|ollama|custom --name NAME [--base-url URL] [--key KEY] [--call-timeout SECONDS]
python -m stead model test [--prompt TEXT] [--timeout N]
python -m stead model list

python -m stead factory run --factory weekly-contribution-digest [--shadow|--live] [--generate]
python -m stead factory run --factory weekly-project-status --project P [--shadow|--live] [--generate]
python -m stead factory run --factory context-maintenance [--shadow|--live] [--generate]
python -m stead factory run --factory feature-builder --contribution ID [--shadow|--live] [--generate] [--reach REACH]
python -m stead digest [--generate]
python -m stead factory new --name NAME --title "What it drafts"
python -m stead factory watch [--build] [--publish] [--merge]
python -m stead factory defaults [--trigger on-demand|watch] [--reach ghost|shadow|draft-pr|pr] \
    [--max-builds-per-day N] [--build-minutes N]
python -m stead factory stop
python -m stead factory start
python -m stead repo set ID [--trigger on-demand|watch] [--reach ghost|shadow|draft-pr|pr|merge] \
    [--path DIR] [--set KEY=VALUE ...]

python -m stead eval run [--factory F]
python -m stead eval judge --factory F --case ID --output PATH [--prompt-version V]
```

`factory run` and `digest` assemble a prompt. They call a model only with
`--generate`, and only the endpoint in Settings. The draft is `output.md`.
Nothing is posted or pushed. `--live` records the run as live. It does not
raise the ceiling and it does not open a pull request. `--reach` is
feature-builder only. It cannot exceed the repo ceiling. Merge is not an
install default. See [Models](models.md).

`factory new` writes `FACTORY.md`, `prompts/v1.md`, and one eval. Run
`stead init` after that so the prompt is indexed.

`factory stop` writes `.stead-stop`; a build and a watched run check it
between steps. `factory start` removes it. `factory defaults` also stores the
daily watched-build budget (`0` means no cap) and the per-build wall clock.
`repo set --set` edits any repo field; the containment fields are:

| Field | Effect |
|---|---|
| `checks_isolation: docker` + `checks_image` | Run checks in a container with no network |
| `trust_checks: host` | Accept host checks for merge (explicit) |
| `allow_test_edits: true` | Let the agent write test paths |
| `require_tests: false` | Allow a code build with criteria to finish without adding a test (default on) |
| `allow_ci_edits: true` | Let the agent write `.github/` and CI config |
| `protected_paths:` | Extra paths the agent may not write (comma list) |
| `merge_without_required_checks: true` | Merge even when the default branch requires nothing |

See [Trust](trust.md) for the full set.

## Capture and schedule

```bash
python -m stead inbox import PATH
python -m stead hook set
python -m stead hook show
python -m stead schedule show [--project P] [--watch] [--merge]
python -m stead schedule show --interval hourly|daily [--watch] [--merge]
python -m stead schedule install [--project P] [--watch] [--merge]
python -m stead schedule install --interval hourly|daily [--watch] [--merge]
```

`inbox import` copies a local `.eml`, `.ics`, `.md`, or `.txt` file into
`inbox/`. It does not write `context/`. `hook set` prints a token once.
`POST /hook` with header `X-Stead-Hook` captures one inbox note and does not
run a factory. The hook is off until that token exists.

`schedule show` prints the Friday command for cron or Task Scheduler.
`schedule install` creates the current user's Windows task. It writes
`private/run-weekly.cmd` and registers that short path, because Task Scheduler
rejects a command over 261 characters. The job runs a read-only sync, a local
digest if the cache changed, a maintenance draft, and the status of
`--project` when you pass one. It does not push or merge.

`schedule show --interval hourly|daily` prints the shorter monitor cadence — a
read-only sync followed by `factory watch --build --publish` for enabled specs.
`schedule install --interval` registers it as its own task
(`private/run-monitor.cmd`), separate from the weekly digest job. Manual-only
does not satisfy the monitor requirement; land the attempt-gate and kill fixes
before turning on an hourly task.

## Publishing and merging

```bash
python -m stead spec draft --contribution ID [--redraft]
python -m stead spec approve --contribution ID
python -m stead factory publish --contribution ID
python -m stead factory merge --contribution ID
python -m stead factory comment --contribution ID --pr-url URL
python -m stead build --contribution ID [--publish] [--merge] [--resume] [--retry] \
    [--wait] [--steps N] [--repair-rounds N] [--max-minutes N] \
    [--max-tokens N] [--max-cost USD]
```

`spec draft` turns a raw issue into a buildable spec in one model call: a new
`feature-spec`-tagged contribution linked to the source issue (which is left
untouched). It refuses to draft from the unedited sync cache stub, from a draft,
or when a draft already exists — pass `--redraft` to replace the existing draft
and clear its approval. The draft must have a `## Acceptance criteria`
checklist and a `## Plan` section. When the repo has a `code_path` checkout,
the model sees its depth-2 tree (the same one a build sees), and `spec draft`
warns about any path in the plan whose folder is not in the repo, or that does
not exist while a file of the same name does elsewhere (`stead/cli.py` →
"did you mean `ctx/cli.py`?"). It also warns when a build would refuse the
draft: more than 8 acceptance criteria, or a description under 25 or over 400
words. `spec approve` refuses such a spec outright, so an approval always means
the spec is ready to build.

`spec approve` records a SHA-256 of the contribution body and prints the body
being approved. A build refuses an unapproved spec, and refuses a spec whose
body changed since approval. The `author` role and the `feature-spec` /
`stead-build` tags are labels; the hash is the gate.

`factory publish` pushes the build branch and opens a pull request. The branch
must not be the default, and it must be ahead of that default. Set `code_path`
with `repo set --path` first. The ceiling must be `draft-pr`, `pr`, or `merge`.
This command does not merge.

`factory merge` is separate. The repo file must say `reach: merge`. The pull
request must be open, and the checks must be green. The checks run must be
isolated (`checks_isolation: docker`) or explicitly trusted
(`trust_checks: host`), and the default branch must have required status
checks unless the repo says `merge_without_required_checks: true`. An
independent reviewer pass must approve the diff unless
`merge_without_review: true`. It does not pass `--admin`, and it does not push
the default branch. A factory run does not call it.

`factory comment` posts — or updates — a marked comment on the source issue
linking the PR. It is the only other remote write, and the most gated:
`allow_comment: true` on the repo, `kind: own` only, and the PR URL must be in
the same repo. It runs automatically after `build --publish` when enabled.

`build` is the model-driven implementation step. It needs a configured model, a
repo `code_path`, and a buildable, approved spec. Every build runs in its own
`git worktree`, so the user's checkout is never touched: there is no "must be on
the default branch" or "must be clean" precondition, and Stead never runs
`git clean`. The model must first write a plan, then it may list, read (a whole
file, or a line range of a long one), search, edit (replace one exact snippet),
write, delete, and run the configured checks inside the worktree. It cannot
touch `.git`, leave the repo, choose a shell command, or write a protected test
or CI path unless the repo opts in (adding a brand-new test file is allowed).
While it runs, the build prints one progress line per step to stderr and
appends it to a `.progress.log` under `factories/feature-builder/runs/`, so
a second terminal can follow it; the log moves into the run folder at the
end. Checks run with a scrubbed environment, or in a container. Because the build
runs in a fresh worktree, `checks:` must work from a clean clone — untracked
local state (a `.venv`, `node_modules`, `.env`) is absent. Failed checks are
fed back so it can repair them (`--repair-rounds`, default 2). A lock prevents
two builds on one checkout and is reclaimed when its process is gone.
`--max-minutes` bounds the build; `--max-tokens` and `--max-cost` bound spend.
Stead commits on a new `stead/<issue>-<slug>` branch and records the plan,
summary, checks mode, tests touched, characters/tokens sent, and actions under
`factories/feature-builder/runs/`. `--publish` pushes and opens a pull request
when the ceiling allows it. `--wait` polls PR checks before `--merge`, and
`--merge` runs only when the repo says `reach: merge`. `--resume` continues a
failed build from its existing branch (the WIP commit a failure left behind).

A spec gets one automatic build attempt per approved content hash. A build that
fails the work (a build-class failure) blocks a re-run until the body is
re-approved (a new hash) or you pass `--retry`; an infrastructure failure (the
model was down, a timeout, a setup error) does not consume the attempt. The spec
must be approved (`spec approve`) and its body unchanged since approval.

A failed build that reached the model also writes a `build-record` with outcome
`failed` and a `reason` code (protocol, gate, checks, budget, tamper, build, or
infrastructure), so the ledger has a denominator and a killed build is never
silent.

On a successful build Stead writes a versioned `build-record` document under
`context/documents/`, marks the contribution merged and closes linked tasks
when it merged, and the next feature-builder bundle for that repo reads the
prior records. The model may `propose` a decision or glossary term; that goes
to `inbox/` for a person to triage, never straight into context. `repo set`
warns when `checks:` names a runner whose config file is unprotected.

## Runs and prompts

```bash
python -m stead run log --factory F --task REF --prompt-version V \
    [--output TEXT] [--verdict approved|rejected]
python -m stead run file --run ID [--title T]
python -m stead prompt list --factory F
python -m stead prompt promote --factory F --version V
```

`run file` writes an approved digest or project status into
`context/documents/` as a private document. It refuses a pending or rejected
run, a run whose prompt version is not production, an empty draft, and a
feature-builder run. It never posts, pushes, or merges. Filing the same run
twice is refused.

`prompt promote` marks one version production and retires the previous one.
It refuses until every eval case has a recorded pass for that version. Judge
with `--prompt-version` first. Old prompt files are kept.

## Tests

```bash
python -m unittest discover -s tests
```
