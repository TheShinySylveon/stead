# Cockpit

The cockpit is a browser page served by Stead. The command is `stead`.

```bash
python -m stead ui
python -m stead ui --no-browser --port 8765
```

The cockpit lives at **http://127.0.0.1:8765/** by default. `stead ui` prints
the URL at startup. Change the port with `--port N`, or a `port` field in
gitignored `stead.json`.

On this computer the server refuses any address except loopback
(`127.0.0.1`, `localhost`, `::1`). A shared server is the Docker image, or
`stead ui --deploy`. It starts if a person account exists, or if
`STEAD_ACCESS_TOKEN` is set and no account exists yet. See [Deploy](deploy.md).

The page has no external fonts or scripts. It works offline.

Each section has a `#hash` route (for example `#repos`, `#tasks`), so the back
button, browser history, and shared URLs land on the right view.

Writes go through the same rules as the CLI. Markdown stays the source of
truth. The page calls a model only when you check **Draft with model** or
press **Build** on an approved spec. A cockpit build runs in the background
with live progress, commits locally, and stops there. Publish, merge, and issue
comments are explicit, confirmation-gated steps (and refused on a shared server).

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
| Repos | Add a repo. Sync GitHub read-only, or re-index offline. Change kind, status, trigger, and the factory ceiling. Add a local issue or feature spec. The build pipeline lives here: each issue/spec is a card with a four-step track (Draft · Approve · Build · Publish) that marks the current step and the repo's limit (ghost stops at the spec, shadow at a local build, draft-pr and up may publish). A drafted spec offers Review spec; Approve lives inside the opened spec, under its text. Build options appear once a spec is approved and default to the repo's limit. A finished build keeps its log and a result note on the card until you publish. On a shared server, trigger, reach, code_path, and the checks/protected-path fields are read-only. |
| Wiki | A Confluence-style space per repo: home, page tree, child pages, labels, metadata, on-page table of contents. Arrange reorders and pins; Request a change files a request document instead of editing generated pages. |
| Inbox | Drop a note, or import a local `.eml`, `.ics`, `.md`, or `.txt` file. File it as a document, meeting, or task, or delete it. |
| Factories | What a factory is and what each one reads, in plain language. Assemble a shadow run; check Draft with model to write `output.md`. Watch now assembles; Watch and build plans, edits, checks, and commits locally. Guided New factory (a custom factory reads a project). Delete a factory (shipped factories and run logs need force). Per-case eval results, Judge, Promote prompt. feature-builder's Draft → Approve → Build → Publish lives on Repos. A shared server refuses any build. |
| Settings | This computer or a shared server. The rented model (including the call timeout). The install factory default (including build minutes). The build kill switch. The build ledger (metrics) with Correct/Incorrect marking. The weekly job and the hourly/daily monitor cadence. Doctor. Rotate the access token. Add a sign-in, or reset its password. Sign out on a shared server. Choose who is writing. Add actors (`human` or `agent`). The capture webhook. Rebuild the index. |

Opening a project, task, document, or meeting shows the note and an editor.
Saving updates the body and the `updated` date. It does not change `created`
or `id`. Escape closes the reader. A project also shows a rollup: task counts,
linked documents and meetings, and its recent runs.

Every project, task, document, meeting, repo, actor, and contribution can be
deleted from the reader. Git history keeps the old text. A project with linked
objects, or a repo with cached contributions, asks before forcing. Deleting a
contribution also removes the spec drafted from it.

"Needs you" lists one row per object. An object with two reasons shows two
chips, and counts once.

A contribution expands inline as a **public spec**. The file can be shared;
private notes belong in Library. Expanding a card on the Repos tab shows the
spec, the current stage, and the next action — Draft, Approve, Build, or
Publish — all in one pane. **Approve** records a hash of the current body; any
later edit needs re-approval. **Build options** (minutes / tokens / USD / reach)
bound the build; an explicit `0` turns the token or cost limit off. **Preview
bundle** assembles the feature-builder bundle without building, and **Review**
runs the independent reviewer (once a branch exists). Builds, drafts, and
reviews stream their progress into an inline log. On a shared server, approval,
the author role, and authoring a spec with acceptance criteria are read-only.

## GitHub sync

Repos → Sync GitHub runs `gh` read-only and refreshes the local cache.
Re-index offline does the same with no network. Neither button creates a
remote issue or pull request.

Sync also reconciles cached state: a merged or closed PR stops showing as open,
and a cached issue closed upstream is dropped when it was never started (no
draft, approval, or build record) or marked closed when it was — so started
issues stay visible and can be deleted from their reader.

## Factory runs

Preview bundle (assemble shadow) writes `bundle.md`, `prompt.md`, and `run.json`
under `factories/<name>/runs/`. Those directories are gitignored. Hand
`prompt.md` to any agent. Come back and approve or reject the run on Home.
**Open run** shows the draft, the prompt, and the bundle. Home lists the newest
runs, with
a control to show the full history.

**Publish** opens a pull request from an isolated branch, and **Merge** merges
only when that repo says `reach: merge` and the checks are green. Both are
confirmation-gated buttons on the spec, and also CLI commands (`stead factory
publish`, `stead factory merge`). The cockpit never pushes the default branch;
on a shared server these remote writes are refused.

An approved digest or status can be filed as a private document with the
**File as document** button on Home, or `stead run file --run ID`.

## Stopping it

Ctrl+C in the terminal that started `stead ui`.
