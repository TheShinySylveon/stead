# CLI

Run from the repository root. Python standard library only.

```bash
python3 -m ctx
python3 -m ctx version
python3 -m ctx --help
python3 -m ctx <command> --help
```

`--root` defaults to the current directory. Point it at a checkout if you are
not standing in one.

## First run and setup

```bash
python3 -m ctx ui [--no-browser] [--port N] [--deploy]
python3 -m ctx welcome --title "My Project" [--url URL] [--deployment single|multi]
python3 -m ctx init
```

`ui` opens the cockpit. On an empty checkout it shows Welcome. Without
`--deploy` it stays on loopback, even if `stead.json` says multi.
`--deploy` is the shared server. It refuses to start without an access token.
Prefer Docker. See [Deploy](deploy.md).

`welcome` creates one project and a repo record. It does not run Spec Kit.
`--deployment multi` prints an access token once and tells you how to start
the container. It does not open the port on this computer.

`init` rebuilds `state.db`. If there are no projects, it prints the welcome
commands.

Full project plus constitution, optional `specify init`:

```bash
python3 -m ctx onboard --title "My App" --kind own|oss \
    [--url URL] [--path DIR] [--method spec-kit|builtin] \
    [--integration claude|copilot|gemini|codex|generic] [--no-specify]
```

See [Spec Kit](spec-kit-workflow.md).

## Tasks, repos, contributions

```bash
python3 -m ctx task add --title T --project P [--status to-do|doing|done|blocked]
python3 -m ctx task list [--project P] [--status S]
python3 -m ctx task set ID --status S

python3 -m ctx repo add --title T [--url URL] [--kind own|oss] \
    [--status active|paused|archived]
python3 -m ctx repo list [--kind own|oss]

python3 -m ctx contribution add --title T --repo REPO --kind issue|pr --number N \
    [--role author|assignee|reviewer] [--state open|closed|merged] \
    [--ci pending|pass|fail|none] [--review requested|approved|changes|none] \
    [--method spec-kit|builtin]
python3 -m ctx contribution list
python3 -m ctx contribution set ID [--state S] [--ci C] [--review R] \
    [--role R] [--method spec-kit|builtin]
```

`method` chooses tooling for feature-builder. It does not turn planning off.
Omitted, it is `spec-kit`.

## Status and GitHub

```bash
python3 -m ctx actor add --title "Ada" --kind human|agent
python3 -m ctx actor list

python3 -m ctx status PROJECT
python3 -m ctx sync github [--author @me] [--limit N]
python3 -m ctx sync github --offline
```

`sync github` is read-only. It uses `gh`. `--offline` only re-indexes files
already on disk.

## Factories and prompts

```bash
python3 -m ctx model show
python3 -m ctx model set --provider openai|openrouter|ollama|custom --name NAME [--base-url URL] [--key KEY]
python3 -m ctx factory run --factory weekly-contribution-digest [--shadow|--live] [--generate]
python3 -m ctx factory run --factory weekly-project-status --project P [--shadow|--live] [--generate]
python3 -m ctx repo set ID [--trigger on-demand|watch] [--reach shadow|draft-pr|pr|merge]
python3 -m ctx factory defaults [--trigger on-demand|watch] [--reach shadow|draft-pr|pr]
python3 -m ctx factory watch
python3 -m ctx factory run --factory feature-builder --contribution ID [--shadow|--live] [--generate] [--reach REACH]
python3 -m ctx digest [--generate]
python3 -m ctx eval run [--factory F]
python3 -m ctx eval judge --factory F --case ID --output PATH

python3 -m ctx run log --factory F --task REF --prompt-version V \
    [--output TEXT] [--verdict approved|rejected]
python3 -m ctx prompt list --factory F
python3 -m ctx prompt promote --factory F --version V
```

`factory run` and `digest` assemble a prompt. They call a model only with
`--generate`, and only the endpoint in Settings. The draft is `output.md`.
Nothing is posted or pushed. `--live` records the run as live. It does not
raise the ceiling and it does not open a pull request. `--reach` is
feature-builder only. It cannot exceed the repo ceiling. Merge is not an
install default. See [Models](models.md).

`prompt promote` marks one version production and retires the previous one.
Old prompt files are kept.

## Tests

```bash
python3 -m unittest discover -s tests
```
