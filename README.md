# Stead

[![CI](https://github.com/TheShinySylveon/stead/actions/workflows/ci.yml/badge.svg)](https://github.com/TheShinySylveon/stead/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/TheShinySylveon/stead)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](docs/getting-started.md)

Stead takes the shape of Notion's guidebook
[*A New Shape for Work*](https://www.notion.com/nsfw) — a **context system**
plus **factories** — and adds one deliberate twist: a factory does not stop at
drafting. With a model configured it can plan, write the code, run the repo's
checks, open the pull request, and merge when that repo explicitly allows it.

> Rent the intelligence. Own the context.

The files stay yours and the model can be swapped. The command is `stead`.
Version **0.1.0**. Licensed under Apache-2.0. Copyright 2026 Tyler Rathbone.
See [LICENSE](LICENSE).

## The twist

- **Factories execute.** `stead build` runs a model agent that plans first,
  edits the checkout, runs the repo's `checks:`, and commits. `--publish` and
  `--merge` carry it to delivery.
- **Autonomy is per repo, not per install.** `reach` is `shadow`, `draft-pr`,
  `pr`, or `merge`. The safe rungs stay the default; `merge` is never
  inherited and never bypasses branch protection.
- **The context stays local and portable.** Markdown and git are the truth.
  The index is rebuildable. The cockpit is one offline file. A shared server
  is your own container, not a hosted account.
- **Scrutiny is built in.** Versioned prompts, eval cases, run logs, and a
  promote gate keep the autonomous path from becoming an unexamined one.

![Stead cockpit](docs/images/cockpit.png)

The cockpit, after the first project exists. The shot is a sample named Field notes, not data shipped with the repo.

![First run](docs/images/welcome.png)

A fresh checkout shows Welcome instead.

## What you get

- Markdown files with flat YAML frontmatter. That is the source of truth.
- A SQLite index (`state.db`) that `stead init` can rebuild. It is not shared.
- A local cockpit in the browser, or the same actions from the CLI.
- Four factories that plan, assemble, and — with a model — execute a pipeline.
  `--generate` drafts text; `stead build` edits code, runs checks, and commits.
- A model-driven build: `stead build` plans, edits the repo, runs its checks,
  commits, and can publish or merge under that repo's reach.
- A weekly local job that syncs read-only and drafts, plus `stead run file` to
  keep an approved draft as a private document.
- A first-run choice: this computer, or a shared Docker server where each person signs in.

Docs: [docs/README.md](docs/README.md).

## Quick start

Requires Python 3.11 or newer. No pip packages.

```bash
git clone https://github.com/TheShinySylveon/stead.git
cd stead
python -m stead ui
```

A fresh checkout has an empty `context/`. Welcome asks for a project title, an
optional GitHub URL, and whether this copy is for this computer or a shared
server. Nothing is pushed.

Without a browser:

```bash
python -m stead welcome --title "My Project"
```

## This computer or a shared server

| | This computer | Shared server |
|---|---|---|
| Who | One person, and the agents on that machine | Several people, one process |
| How | `python -m stead ui` | `docker compose pull && docker compose up --no-build` |
| Network | Loopback only | Published port, each person signs in |
| Index | One `state.db` on that machine | One `state.db` inside the container |

Choosing Shared server in Welcome does not open a port on your laptop. It
writes a gitignored `stead.json` and shows a token once. The image is
`ghcr.io/theshinysylveon/stead`. The token only starts a server that has no
accounts yet. After that, each person signs in. Details:
[docs/deploy.md](docs/deploy.md).

Do not scale the container. Do not put `state.db` on a network share. People
who each have a clone share the markdown through git, and each clone keeps
its own index. [docs/multi-actor.md](docs/multi-actor.md).

## Factories

A factory is a repeatable pipeline: plan, build, verify, and deliver. Stead
ships four. Assembly writes `bundle.md`, `prompt.md`, and `run.json` under
`factories/<name>/runs/` (gitignored). `--generate` writes `output.md` from
your model. With a model configured, `stead build` goes further: it plans,
edits the repo checkout, runs the repo's checks, commits, and can open or
merge a pull request under that repo's reach.

| Factory | What it drafts |
|---|---|
| `weekly-contribution-digest` | PRs in flight, reviews waiting, claimed issues, CI |
| `weekly-project-status` | A status note from one project's tasks, docs, and meetings |
| `feature-builder` | A plan and proposed diff from a feature spec you authored |
| `context-maintenance` | Inbox, broken relations, stale objects, duplicate titles |

`feature-builder` is planning-first on every run. `method: spec-kit` (the
default) uses the optional `specify` CLI when you onboard a code directory.
`method: builtin` is the same phases as markdown. Assembly itself never calls
a model and never pushes.

Shadow is the only mode the cockpit offers, and the CLI default. Assembly
does not push. `stead factory publish` opens a pull request from an isolated
branch when that repo's ceiling allows it. `stead factory merge` is separate,
and only when the repo file says `reach: merge` and the checks are green.

```bash
python -m stead sync github --limit 30    # read-only, needs gh
python -m stead sync github --digest      # assemble only if the cache changed
python -m stead digest                    # shadow digest
python -m stead schedule show             # the Friday local jobs
```

An approved digest or status becomes a private document:

```bash
python -m stead run file --run 7
```

More: [docs/factories.md](docs/factories.md) and
[docs/spec-kit-workflow.md](docs/spec-kit-workflow.md).

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | Requirements, clone, first command |
| [First run](docs/first-run.md) | Welcome, and what it refuses to do |
| [Concepts](docs/concepts.md) | Files, the index, public and private |
| [Vision](docs/vision.md) | The autonomy slider, shared repo context, one context graph |
| [Cockpit](docs/cockpit.md) | The browser UI |
| [CLI](docs/cli.md) | Every command |
| [Models](docs/models.md) | The optional endpoint a factory drafts with |
| [Deploy](docs/deploy.md) | Docker, the image, and sign-in |
| [Several writers](docs/multi-actor.md) | Actors, git, and why SQLite stays |
| [CONVENTIONS.md](CONVENTIONS.md) | Frontmatter schema. Read this before writing objects. |
| [AGENTS.md](AGENTS.md) | Entry point for coding agents |

Samples live in `examples/context/`. They are not loaded into a fresh checkout.

## Develop

```bash
python -m unittest discover -s tests
```

CI on `main` and on pull requests runs that suite on Python 3.11 and 3.12.
Pull requests build the Docker image. `main` publishes
`ghcr.io/theshinysylveon/stead`.

## Limits of 0.1.0

- A shared server asks each person to sign in. This computer does not.
  The access token only starts a server that has no accounts yet.
- A normal `stead ui` stays on loopback. `--deploy` and Docker are the only
  public binds. They start with an account, or with the token until the first
  account exists.
- `actor:` is stamped when you select who is writing, or when that person is
  signed in on a shared server. It is not a permission check.
- A factory calls a model only when you pass `--generate` or check Draft
  with model. The endpoint is yours: OpenAI, Anthropic, Grok, or another
  chat server. The draft is a file. Nothing is posted, pushed, or merged.
- `specify` is optional. If it is missing, onboarding still writes the
  constitution in `context/documents/`.
- Git history before the empty-context commit still contains early demo
  files. A clone of `main` does not load them.

## Contributing

Issues and pull requests are welcome. Read [AGENTS.md](AGENTS.md) and
[CONVENTIONS.md](CONVENTIONS.md) before adding objects. Run the tests before
you open a pull request:

```bash
python -m unittest discover -s tests
```

History of this release: [CHANGELOG.md](CHANGELOG.md).

## License

Apache License, Version 2.0. See [LICENSE](LICENSE).
