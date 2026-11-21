# Cockpit

The cockpit is a browser page served by Stead. The command is `stead`.

```bash
python -m stead ui
python -m stead ui --no-browser --port 8765
```

On this computer the server refuses any address except loopback
(`127.0.0.1`, `localhost`, `::1`). A shared server is different: it is the
Docker image, or `stead ui --deploy`, and it will not start without an access
token. See [Deploy](deploy.md).

The page has no external fonts or scripts. It works offline.

Writes go through the same rules as the CLI. Markdown stays the source of
truth. The page never calls a model, and it never pushes or opens a pull
request.

## First visit

If `context/projects/` is empty, you get Welcome instead of the normal
navigation. Title, optional GitHub URL, and this computer or a shared server.
See [First run](first-run.md).

## Pages

| Page | What you can do |
|---|---|
| Home | What needs you, projects, recent factory runs. Approve or reject a pending run, with an optional note. |
| Tasks | Add a task, move its status. The title opens the note. |
| Projects | Onboard a later project (repo + constitution, optional Spec Kit). Or add a project with no repo. Change a project's status. |
| Library | Add and edit documents and meetings. Rename them. The id does not change. |
| Repos | Add a repo. Sync GitHub read-only, or re-index offline. Change kind, status, trigger, and the factory ceiling. Add a local issue or feature spec. |
| Inbox | Drop a note. File it as a document, meeting, or task, or delete it. |
| Factories | Assemble a shadow run. Check Draft with model to write `output.md`. Nothing is posted. |
| Settings | This computer or a shared server. The rented model. The install factory default. Rotate the access token. Add actors (`human` or `agent`). |

Opening a project, task, document, or meeting shows the note and an editor.
Saving updates the body and the `updated` date. It does not change `created`
or `id`.

A contribution opens as a **public spec**. The banner is there because that
file can be shared. Private notes belong in Library.

## GitHub sync

Repos → Sync GitHub runs `gh` read-only and refreshes the local cache.
Re-index offline does the same with no network. Neither button creates a
remote issue or pull request.

## Factory runs

Assemble shadow writes `bundle.md`, `prompt.md`, and `run.json` under
`factories/<name>/runs/`. Those directories are gitignored. Hand `prompt.md`
to any agent. Come back and approve or reject the run on Home.

Draft pull requests are not a button. `stead factory publish` opens one
from an isolated branch. The cockpit does not push.

## Stopping it

Ctrl+C in the terminal that started `stead ui`.
