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

`ui` opens the cockpit. On an empty checkout it shows Welcome. Without
`--deploy` it stays on loopback, even if `stead.json` says multi.
`--deploy` is the shared server. It refuses to start unless an account
exists, or `STEAD_ACCESS_TOKEN` is set for a server that has no accounts yet.
Prefer Docker. See [Deploy](deploy.md).

`welcome` creates one project and a repo record. It does not run Spec Kit.
`--deployment multi` prints an access token once and tells you how to start
the container. It does not open the port on this computer.

`init` rebuilds `state.db`. If there are no projects, it prints the welcome
commands.

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
```

`method` chooses tooling for feature-builder. It does not turn planning off.
Omitted, it is `spec-kit`.

## Status and GitHub

```bash
python -m stead actor add --title "Ada" --kind human|agent
python -m stead actor list
python -m stead actor use actor-ada
python -m stead account add --name ada --actor actor-ada
python -m stead account list
python -m stead account reset --name ada

python -m stead status PROJECT
python -m stead sync github [--author @me] [--limit N]
python -m stead sync github --offline
```

`sync github` is read-only. It uses `gh`. `--offline` only re-indexes files
already on disk.

`actor use` remembers who is writing on this computer. Later writes stamp
`actor:` when that file exists. `account add` is a shared-server sign-in for
one actor. The password is printed once and stored as a hash in gitignored
`private/accounts.json`. `account list` never prints it. This computer does
not ask for that password.

## Factories and prompts

```bash
python -m stead model show
python -m stead model set --provider openai|anthropic|grok|openrouter|ollama|custom --name NAME [--base-url URL] [--key KEY]
python -m stead factory run --factory weekly-contribution-digest [--shadow|--live] [--generate]
python -m stead factory run --factory weekly-project-status --project P [--shadow|--live] [--generate]
python -m stead repo set ID [--trigger on-demand|watch] [--reach shadow|draft-pr|pr|merge]
python -m stead factory defaults [--trigger on-demand|watch] [--reach shadow|draft-pr|pr]
python -m stead factory new --name NAME --title "What it drafts"
python -m stead factory run --factory context-maintenance --shadow
python -m stead inbox import PATH
python -m stead hook set
python -m stead hook show
python -m stead factory watch
python -m stead factory publish --contribution ID
python -m stead factory merge --contribution ID
python -m stead repo set ID --path DIR
python -m stead factory run --factory feature-builder --contribution ID [--shadow|--live] [--generate] [--reach REACH]
python -m stead digest [--generate]
python -m stead eval run [--factory F]
python -m stead eval judge --factory F --case ID --output PATH [--prompt-version V]

python -m stead run log --factory F --task REF --prompt-version V \
    [--output TEXT] [--verdict approved|rejected]
python -m stead prompt list --factory F
python -m stead prompt promote --factory F --version V
```

`factory run` and `digest` assemble a prompt. They call a model only with
`--generate`, and only the endpoint in Settings. The draft is `output.md`.
Nothing is posted or pushed. `--live` records the run as live. It does not
raise the ceiling and it does not open a pull request. `--reach` is
feature-builder only. It cannot exceed the repo ceiling. Merge is not an
install default. See [Models](models.md).

`factory new` writes `FACTORY.md`, `prompts/v1.md`, and one eval. Run
`stead init` after that so the prompt is indexed. `inbox import` copies a
local `.eml`, `.ics`, `.md`, or `.txt` file into `inbox/`. It does not write
`context/`. `hook set` prints a token once. `POST /hook` with header
`X-Stead-Hook` captures one inbox note and does not run a factory. The hook
is off until that token exists.

`factory publish` pushes the checkout's current branch and opens a pull
request. The branch must not be the default, and it must be ahead of that
default. The repo ceiling must be `draft-pr`, `pr`, or `merge`. Set
`code_path` with `repo set --path` first. This command does not merge.

`factory merge` is separate. The repo file must say `reach: merge`. The pull
request must be open, and the checks must be green. It does not pass
`--admin`, and it does not push the default branch. A factory run does not
call it.

`prompt promote` marks one version production and retires the previous one.
It refuses if any eval case lacks a recorded pass for that version. Judge
with `--prompt-version` first. Old prompt files are kept.

## Tests

```bash
python -m unittest discover -s tests
```
