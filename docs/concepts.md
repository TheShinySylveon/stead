# Concepts

Rent the model. Keep the files.

Stead is two things in one folder, borrowed from Notion's guidebook and pushed
one step further:

1. A **context system** — projects, tasks, notes, meetings, repos, and the
   issues and pull requests you touch.
2. **Factories** — named pipelines that take an input through plan, build,
   verify, and delivery. A factory can stop at a draft, or with a model
   configured it can write the code, run the checks, and open or merge the
   pull request under a per-repo ceiling.

Nothing here is tied to one vendor. Hermes, Claude Code, Codex, or a human
can read the same files; the model is rented, not required.

## Notion's model, our twist

| Notion's concept | What Stead keeps | What Stead changes |
|---|---|---|
| Context system | One organized place where people and agents read and write | It is a folder of markdown in git. SQLite is only a rebuildable index |
| Factory | A specific, repeatable, scrutinized workflow | The factory executes: `stead build` plans, edits, checks, and commits |
| Human review | A person watches consequential steps | Review is a per-repo `reach`: human at `shadow`/`draft-pr`, autonomous at `pr`/`merge` |
| Prompt versions and evals | Test prompts before trusting them | Built in: eval cases, recorded passes, and a promote gate |
| Model choice | Intelligence is rented | Any OpenAI-compatible server, Anthropic, Grok, or Ollama; no vendor SDK |
| Governance | The work is legible | Git history, run logs, and an explicit ceiling per repo |

Two differences matter most. First, a Stead factory is not only an assembly
step; it is a pipeline that can deliver. Second, autonomy is not one global
switch. It is granted per repo, and the top rung (`merge`) must be written on
that repo file before any run can use it.

## Files are the truth

Every object is one markdown file with a flat YAML frontmatter block. The
schema is in `CONVENTIONS.md`. If you are unsure where a note goes, put it in
`inbox/` and file it later.

`state.db` is a rebuildable index. It is gitignored. `python -m stead init`
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

A factory is a repeatable pipeline: plan, build, verify, deliver. Each lives
under `factories/<name>/` as a definition, versioned prompts, evals, and run
logs. `stead factory run` assembles a bundle and a prompt. With a model
configured, `stead build` plans, edits the repo checkout, runs the repo's
`checks:`, and commits on an isolated branch; `--publish` opens the pull
request and `--merge` merges when the repo says `reach: merge`. An approved
digest or status can be filed with `stead run file --run ID`.

Shadow mode is the default. It drafts locally. It does not push or open a
pull request. See [Factories](factories.md).

## Several writers

Humans and agents share markdown through git, or they share one Docker
server and sign in as themselves. Each clone keeps its own `state.db`. The
container keeps one index for that server. SQLite is not being replaced.
See [Several people and agents](multi-actor.md) and [Deploy](deploy.md).

## What this is not

- Not a hosted website you sign up for. This computer is loopback-only.
  A shared server is a container you run, and each person signs in there.
- Not a model provider. A draft is a file. You choose the endpoint, or you
  hand `prompt.md` to any agent.
- Not an auto-merge bot. `stead factory merge` is an explicit command. A
  factory run does not call it. A red check is refused.
