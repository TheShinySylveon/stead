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
python -m stead sync github --offline
```

`sync github` is read-only. It uses `gh`. `--offline` only re-indexes files
already on disk. `--digest` assembles the digest only when the cache changed.
It still does not post.

`actor use` remembers who is writing on this computer. Later writes stamp
`actor:` when that file exists. `account add` is a shared-server sign-in for
one actor. The password is printed once and stored as a hash in gitignored
`private/accounts.json`. `account list` never prints it. This computer does
not ask for that password.

Scheduling is under [Capture and schedule](#capture-and-schedule).

## Factories and models

```bash
python -m stead model show
python -m stead model set --provider openai|anthropic|grok|openrouter|ollama|custom --name NAME [--base-url URL] [--key KEY]
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
python -m stead schedule install [--project P] [--watch] [--merge]
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

## Publishing and merging

```bash
python -m stead spec approve --contribution ID
python -m stead factory publish --contribution ID
python -m stead factory merge --contribution ID
python -m stead build --contribution ID [--publish] [--merge] [--resume] [--wait] \
    [--steps N] [--repair-rounds N] [--max-minutes N]
```

`spec approve` records a SHA-256 of the contribution body. A build refuses an
unapproved spec, and refuses a spec whose body changed since approval. The
`author` role and `feature-spec` tag are labels; the hash is the gate.

`factory publish` pushes the checkout's current branch and opens a pull
request. The branch must not be the default, and it must be ahead of that
default. Set `code_path` with `repo set --path` first. The ceiling must be
`draft-pr`, `pr`, or `merge`. This command does not merge.

`factory merge` is separate. The repo file must say `reach: merge`. The pull
request must be open, and the checks must be green. The checks run must be
isolated (`checks_isolation: docker`) or explicitly trusted
(`trust_checks: host`), and the default branch must have required status
checks unless the repo says `merge_without_required_checks: true`. It does not
pass `--admin`, and it does not push the default branch. A factory run does not
call it.

`build` is the model-driven implementation step. It needs a configured model,
a repo `code_path`, a clean checkout on the default branch, and a buildable
spec. The model must first write a plan, then it may list, read, search, write,
delete, and run the configured checks inside that checkout. It cannot touch
`.git`, leave the repo, choose a shell command, or write a protected test or CI
path unless the repo opts in. Checks run with a scrubbed environment, or in a
container. Failed checks are fed back so it can repair them
(`--repair-rounds`, default 2). A lock prevents two builds on one checkout and
is reclaimed when its process is gone. `--max-minutes` bounds the build.
Stead commits on a new `stead/<issue>-<slug>` branch and records the plan,
summary, checks mode, tests touched, and actions under
`factories/feature-builder/runs/`. `--publish` pushes and opens a pull request
when the ceiling allows it. `--wait` polls PR checks before `--merge`, and
`--merge` runs only when the repo says `reach: merge`. `--resume` continues a
failed build on its existing branch, keeping its uncommitted edits. The spec
must be approved (`spec approve`) and its body unchanged since approval.

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
