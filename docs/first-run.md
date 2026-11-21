# First run

A fresh checkout has no projects. Stead notices that and shows Welcome
instead of the normal cockpit.

## In the browser

```bash
python3 -m ctx ui
```

On this computer the server binds to `127.0.0.1` only. The first page asks
for three things:

1. A project title.
2. An optional GitHub URL (`https://github.com/owner/name`).
3. Who this copy is for:
   - **This computer.** Loopback. No login.
   - **Shared server.** Several people, via Docker. You get an access token
     once. This window does not open the port.

Start writes:

- `context/projects/<slug>.md` — the project.
- `context/repos/<slug>.md` — a repo record linked to that project.
- `context/documents/<slug>-constitution.md` — a short planning baseline.
  Spec Kit is not run.
- `stead.json` — only if you chose Shared server. It is gitignored. It holds
  the access token. Do not commit it.

Then the normal cockpit opens on this computer. Nothing was posted.

The same step from a terminal:

```bash
python3 -m ctx welcome --title "My Project"
python3 -m ctx welcome --title "My Project" --url https://github.com/owner/name
python3 -m ctx welcome --title "Team notes" --deployment multi
```

`--deployment` is `single` (default) or `multi`. Multi prints the access
token once and tells you to start Docker. See [Deploy](deploy.md).

`python3 -m ctx` with no command prints the two entry points.

## What first run does not do

- It does not run `specify init`.
- It does not clone a repository.
- It does not push, open an issue, or open a pull request.
- It does not call a language model.
- It does not open a public port, even if you chose Shared server.

Those belong to later steps.

## After the first project

| Want | Where |
|---|---|
| Another project, with a constitution and optional Spec Kit | Projects → Onboard, or `ctx onboard` |
| A project with no repo | Projects → Add project |
| Switch this computer / shared server, rotate the token, add actors | Settings |
| The Spec Kit rules | [Spec Kit](spec-kit-workflow.md) |

```bash
python3 -m ctx onboard --title "My App" --kind own --method spec-kit \
    --path /path/to/the/code
```

`--path` must be that project's directory, not this Stead checkout.
`--kind oss` records that `.specify/` stays local and must not be pushed
upstream. `--method builtin` never runs `specify`.

## If you already have projects

Welcome is only shown when `context/projects/` has no markdown files.
