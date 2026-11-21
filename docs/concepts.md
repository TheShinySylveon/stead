# Concepts

Rent the model. Keep the files.

Stead is two things in one folder:

1. A **context system** — projects, tasks, notes, meetings, repos, and the
   issues and pull requests you touch.
2. **Factories** — a few named workflows that assemble a prompt from those
   files. A person or any coding agent writes the result. The factory does not
   call a model.

Nothing here is tied to one vendor. Hermes, Claude Code, Codex, or a human
can read the same files.

## Files are the truth

Every object is one markdown file with a flat YAML frontmatter block. The
schema is in `CONVENTIONS.md`. If you are unsure where a note goes, put it in
`inbox/` and file it later.

`state.db` is a rebuildable index. It is gitignored. `python3 -m ctx init`
deletes and recreates it from the markdown and from `ctx/schema.sql`. Do not
treat the database as a backup.

## Public and private

| Keep private | Safe to treat as public |
|---|---|
| `context/documents/` | `context/repos/` |
| `context/meetings/` | `context/contributions/` |
| Project and task bodies, when they hold strategy | GitHub URLs, issue numbers, CI, review state |

GitHub sync only reads. It never creates an issue, comments, labels, or pushes.
Private notes are not copied into contribution files or into a digest.

A contribution body is a **public spec**. Do not put strategy there. Put that
in a document.

## Relations

Objects point at each other with ids, not with folder guessing.

- A task, document, or meeting has `project:`.
- A contribution has `repo:`.
- A repo created by welcome or onboard has `project:`.

Ids are stable. Renaming a note in the cockpit changes the title, not the id.

## Factories

A factory is a folder under `factories/<name>/`: a definition, versioned
prompts, evals, and run logs. `ctx factory run` assembles a bundle and a
prompt. It does not generate the answer. You hand `prompt.md` to an agent and
record the verdict with `ctx run log`, or with Approve / Reject in the cockpit.

Shadow mode is the default. It drafts locally. It does not push or open a
pull request. See [Factories](factories.md).

## Several writers

Humans and agents share markdown through git, or they share one Docker
server with an access token. Each clone keeps its own `state.db`. The
container keeps one index for that server. SQLite is not being replaced.
See [Several people and agents](multi-actor.md) and [Deploy](deploy.md).

## What this is not

- Not a hosted multi-user website. The cockpit is loopback-only.
- Not a model provider. Generation is whoever reads the prompt.
- Not an auto-merge bot. Merging is a human action.
