# First run

A fresh checkout has no projects. The app notices that and asks for one thing:
a name.

## In the browser

```bash
python3 -m ctx ui
```

The cockpit binds to `127.0.0.1` only. The first page is Welcome.

1. Type a project title.
2. Optionally paste a GitHub URL (`https://github.com/owner/name`).
3. Press Start.

That writes:

- `context/projects/<slug>.md` — the project.
- `context/repos/<slug>.md` — a repo record linked to that project.
- `context/documents/<slug>-constitution.md` — a short planning baseline, in
  plain markdown. Spec Kit is not run.

Then the normal cockpit opens. Your notes are files. Nothing was posted.

The same step from a terminal:

```bash
python3 -m ctx welcome --title "My Project"
python3 -m ctx welcome --title "My Project" --url https://github.com/owner/name
```

`python3 -m ctx` with no command prints these two entry points.

## What first run does not do

- It does not run `specify init`.
- It does not clone a repository.
- It does not push, open an issue, or open a pull request.
- It does not call a language model.

Those belong to later steps.

## After the first project

The Projects page has a second form, **Onboard**, and the CLI has `ctx onboard`.
Use that when you have a code directory and you want a constitution plus, if
`specify` is installed, a Spec Kit scaffold in that directory.

```bash
python3 -m ctx onboard --title "My App" --kind own --method spec-kit \
    --path /path/to/the/code
```

`--path` must be that project's directory, not this Stead checkout.
`--kind oss` records that `.specify/` stays local and must not be pushed
upstream. `--method builtin` never runs `specify`.

Full rules: [Spec Kit](spec-kit-workflow.md).

## If you already have projects

Welcome is only shown when `context/projects/` has no markdown files. To add
another project later, use Projects → Onboard, or `ctx onboard`, or Add project
for a project with no repo.
