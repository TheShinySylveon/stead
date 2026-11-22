# Cockpit

The cockpit is a browser page served by Stead. The command is `stead`.

```bash
python -m stead ui
python -m stead ui --no-browser --port 8765
```

On this computer the server refuses any address except loopback
(`127.0.0.1`, `localhost`, `::1`). A shared server is the Docker image, or
`stead ui --deploy`. It starts if a person account exists, or if
`STEAD_ACCESS_TOKEN` is set and no account exists yet. See [Deploy](deploy.md).

The page has no external fonts or scripts. It works offline.

Writes go through the same rules as the CLI. Markdown stays the source of
truth. The page calls a model only when you check **Draft with model**. It
never pushes, opens a pull request, or merges.

## First visit

If `context/projects/` is empty, you get Welcome instead of the normal
navigation. Title, optional GitHub URL, and this computer or a shared server.
See [First run](first-run.md).

## Pages

| Page | What you can do |
|---|---|
| Home | What needs you, projects, recent factory runs. Open a run to read its draft, prompt, and bundle. Approve or reject, with a review note that is kept apart from the draft. File an approved digest or status as a document. |
| Tasks | Add a task, move its status. The title opens the note. |
| Projects | Onboard a later project (repo + constitution, optional Spec Kit). Or add a project with no repo. Change a project's status. |
| Library | Add and edit documents and meetings. Rename them. The id does not change. |
| Repos | Add a repo. Sync GitHub read-only, or re-index offline. Change kind, status, trigger, and the factory ceiling. Add a local issue or feature spec. |
| Wiki | A Confluence-style space per repo: home, page tree, child pages, labels, metadata, on-page table of contents. Arrange reorders and pins; Request a change files a request document instead of editing generated pages. |
| Inbox | Drop a note, or import a local `.eml`, `.ics`, `.md`, or `.txt` file. File it as a document, meeting, or task, or delete it. |
| Factories | Assemble a shadow run. Check Draft with model to write `output.md`. Watch now assembles; Watch and build plans, edits, checks, commits, and publishes. Build with model has Publish and Merge-if-allowed options. New factory, per-case eval results, Judge, Promote prompt. |
| Settings | This computer or a shared server. The rented model. The install factory default. Rotate the access token. Add a sign-in, or reset its password. Sign out on a shared server. Choose who is writing. Add actors (`human` or `agent`). The weekly job. The capture webhook. Rebuild the index. |

Opening a project, task, document, or meeting shows the note and an editor.
Saving updates the body and the `updated` date. It does not change `created`
or `id`. Escape closes the reader. A project also shows a rollup: task counts,
linked documents and meetings, and its recent runs.

Every project, task, document, meeting, repo, and actor can be deleted from the
reader. Git history keeps the old text. A project with linked objects, or a
repo with cached contributions, asks before forcing.

"Needs you" lists one row per object. An object with two reasons shows two
chips, and counts once.

A contribution opens as a **public spec**. The banner is there because that
file can be shared. Private notes belong in Library.

## GitHub sync

Repos → Sync GitHub runs `gh` read-only and refreshes the local cache.
Re-index offline does the same with no network. Neither button creates a
remote issue or pull request.

## Factory runs

Assemble shadow writes `bundle.md`, `prompt.md`, and `run.json` under
`factories/<name>/runs/`. Those directories are gitignored. Hand `prompt.md`
to any agent. Come back and approve or reject the run on Home. **Open run**
shows the draft, the prompt, and the bundle. Home lists the newest runs, with
a control to show the full history.

Draft pull requests are not a button. `stead factory publish` opens one
from an isolated branch. `stead factory merge` is a separate command, and
only when that repo says `reach: merge`. The cockpit does not push or merge.
A contribution shows both commands, ready to copy.

An approved digest or status can be filed as a private document with the
**File as document** button on Home, or `stead run file --run ID`.

## Stopping it

Ctrl+C in the terminal that started `stead ui`.
