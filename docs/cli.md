# CLI

Run from the repository root. Python standard library only.

```bash
python3 -m ctx
python3 -m ctx --help
python3 -m ctx <command> --help
```

`--root` defaults to the current directory. Point it at a checkout if you are
not standing in one.

## First run and setup

```bash
python3 -m ctx ui
python3 -m ctx welcome --title "My Project" [--url https://github.com/owner/name]
python3 -m ctx init
```

`ui` opens the cockpit. On an empty checkout it shows Welcome.
`welcome` creates one project and a repo record. It does not run Spec Kit.
`init` rebuilds `state.db`. If there are no projects, it prints the two
commands above.

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
python3 -m ctx status PROJECT
python3 -m ctx sync github [--author @me] [--limit N]
python3 -m ctx sync github --offline
```

`sync github` is read-only. It uses `gh`. `--offline` only re-indexes files
already on disk.

## Factories and prompts

```bash
python3 -m ctx factory run --factory weekly-contribution-digest [--shadow|--live]
python3 -m ctx factory run --factory weekly-project-status --project P [--shadow|--live]
python3 -m ctx factory run --factory feature-builder --contribution ID [--shadow|--live]
python3 -m ctx digest

python3 -m ctx run log --factory F --task REF --prompt-version V \
    [--output TEXT] [--verdict approved|rejected]
python3 -m ctx prompt list --factory F
python3 -m ctx prompt promote --factory F --version V
```

`factory run` and `digest` assemble a prompt. They do not call a model.
`--live` records the run as live. It still does not push or open a pull
request. Shadow is the default.

`prompt promote` marks one version production and retires the previous one.
Old prompt files are kept.

## Tests

```bash
python3 -m unittest discover -s tests
```
