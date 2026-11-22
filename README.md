# Stead

**Local context you own. Rent the model. Keep the files.**

[![CI](https://github.com/TheShinySylveon/stead/actions/workflows/ci.yml/badge.svg)](https://github.com/TheShinySylveon/stead/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/TheShinySylveon/stead)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](docs/getting-started.md)

Stead is one store of markdown files with two readers. Agents get scoped
bundles; people get a wiki over the same files. Each repo has one dial for how
far a factory may act on that context: draft, open a pull request, or merge.
Every delivered build writes a versioned record back into the store, and the
next bundle for that repo reads it.

It is built for the solo open-source contributor first: the person with a
dozen repos, a weekly review queue, and no wish to hand a vendor their notes.
The same files work for a small team behind one shared container.

> **Status and current focus: the [MVP](docs/mvp.md).** One reliable issue → spec
> → tested change → PR loop, reviewed by a human. New features and QoL are
> deferred until that loop works; milestone-by-milestone status lives in
> [MVP](docs/mvp.md).

Version **0.1.0**. Licensed under Apache-2.0. Copyright 2026 Tyler Rathbone.
See [LICENSE](LICENSE). The command is `python -m stead` (or `stead.cmd` on
Windows); there is no installed `stead` entry point yet.

## How it fits together

1. **Capture and context.** Notes, meetings, specs, tasks, repos, and cached
   GitHub issues live as markdown with flat YAML frontmatter. Git is the audit
   trail. `state.db` is an index you can rebuild at any time.
2. **Two readers.** An agent reads a scoped bundle for one job. A person reads
   the same objects as a Confluence-style wiki. There is no second store to
   drift.
3. **One dial per repo.** A factory can stop at a shadow plan, open a draft pull
   request, open a normal one, or merge. Merge is never inherited from the
   install default, and never bypasses branch protection.
4. **Write-back.** A delivered build writes a versioned `build-record` document
   (outcome, branch, commit, files, checks mode), closes the contribution and
   linked tasks when it merges, and the next bundle for that repo reads the
   prior records. Decisions and glossary terms are only *proposed* to the inbox
   for a person to triage — an agent never quietly rewrites the context.

The shape is inspired by Notion's guidebook
[*A New Shape for Work*](https://www.notion.com/nsfw). The deliberate twist is
execution: a factory does not stop at drafting. With a model configured it
plans, writes the code, runs the repo's checks, and can deliver under that
repo's ceiling.

## Safety, stated plainly

Stead can run code and merge it. The full threat model, the merge gates, and
exactly what leaves the machine are in **[docs/trust.md](docs/trust.md)**.
Four things worth saying on the front page:

- **A spec is approved by content, not by a tag.** `stead spec approve` stores a
  hash of the body; any later edit needs re-approval before a build. The
  `author` role and the `feature-spec`/`stead-build` tags are labels, not
  permissions — the hash is the gate.
- **Checks run code the model wrote.** With no container, they run on your host
  with a scrubbed environment — not in a sandbox. Set `checks_isolation: docker`
  and `checks_image` for real isolation; merge requires that, or an explicit
  `trust_checks: host`.
- **The agent cannot edit its own gate by default.** Tests and CI config are
  protected paths. A repo can opt in per group.
- **Merge requires more than a green build.** The repo must say `reach: merge`,
  every check must be green, the default branch must have required status
  checks, and Stead never passes `--admin`. An **independent reviewer pass** (a
  fresh model invocation that must approve the diff against the spec) runs
  before the merge unless the repo sets `merge_without_review: true`.

## What you get

- Markdown files with flat YAML frontmatter. That is the source of truth. The
  frontmatter is a **YAML subset**, not full YAML: scalars and lists only.
  `stead doctor` fails loudly on a hand edit that breaks it.
- A SQLite index (`state.db`) that `stead init` can rebuild. It is not shared.
- A local cockpit in the browser, or the same actions from the CLI.
- Four factories that plan, assemble, and — with a model — execute a pipeline.
  `--generate` drafts text; `stead build` edits code, runs checks, and commits.
- A model-driven build under explicit bounds: `--max-minutes`, a step cap, a
  token budget (`--max-tokens`), an optional USD budget (`--max-cost`), a stop
  file (`stead factory stop`), and a daily watched-build budget.
- A weekly local job that syncs read-only and drafts, plus `stead run file` to
  keep an approved draft as a private document.
- A repo wiki as a Confluence-style space: home page, page tree, child pages,
  labels, metadata, and an on-page table of contents. Generated from files;
  people arrange it and request changes instead of editing generated pages.
- A first-run choice: this computer, or a shared Docker server where each person signs in.

![Stead cockpit](docs/images/cockpit.png)

The cockpit, after the first project exists. The shot is a sample named Field notes, not data shipped with the repo.

![First run](docs/images/welcome.png)

A fresh checkout shows Welcome instead.

Docs: [docs/README.md](docs/README.md). Roadmap: [PLAN.md §7](PLAN.md).

## Quick start

Requires Python 3.11 or newer. No pip packages.

```bash
git clone https://github.com/TheShinySylveon/stead.git
cd stead
python -m stead ui
```

Then go to **http://127.0.0.1:8765/** — that is the cockpit's default address.
Stead prints the URL at startup and opens a browser; if no browser opens, use
that address. `--port N` changes the port.

A fresh checkout has an empty `context/`. Welcome asks for a project title, an
optional GitHub URL, and whether this copy is for this computer or a shared
server. Nothing is pushed.

Without a browser:

```bash
python -m stead welcome --title "My Project"
python -m stead ui --no-browser    # then visit http://127.0.0.1:8765/
```

Next: [Getting started](docs/getting-started.md) and [Cockpit](docs/cockpit.md).

## This computer or a shared server

| | This computer | Shared server |
|---|---|---|
| Who | One person, and the agents on that machine | Several people, one process |
| How | `python -m stead ui` | `docker compose pull && docker compose up --no-build` |
| Network | Loopback only (`127.0.0.1:8765`) | Published port `8765`, each person signs in |
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
| `feature-builder` | A plan and proposed diff from an enabled feature spec |
| `context-maintenance` | Inbox, broken relations, stale objects, duplicate titles |

`feature-builder` is planning-first on every run. `method: spec-kit` (the
default) uses the optional `specify` CLI when you onboard a code directory.
`method: builtin` is the same phases as markdown. Assembly itself never calls
a model and never pushes.

Shadow is the only mode the cockpit offers, and the CLI default. Assembly
does not push. `stead factory publish` opens a pull request from an isolated
branch when that repo's ceiling allows it. `stead factory merge` is separate,
and only when the repo file says `reach: merge`, the checks are green, the
checks run is isolated (or explicitly trusted), the default branch has required
status checks, and the independent reviewer has approved. `stead factory
comment` posts (or updates) a marked comment on the source issue linking the PR
— gated by `allow_comment: true` and `kind: own`.

The build loop, end to end: `stead spec draft` turns a raw issue into an
approvable spec in one model call, `stead spec approve` binds approval to the
body hash, and `stead build` runs in its own worktree, enforces the
fail-before/pass-after test gate, and can publish.

```bash
python -m stead sync github --limit 30    # read-only, needs gh
python -m stead sync github --digest      # assemble only if the cache changed
python -m stead digest                    # shadow digest
python -m stead schedule show             # the Friday local jobs
python -m stead schedule show --interval hourly   # the shorter monitor cadence
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
| [MVP](docs/mvp.md) | The one loop that must work; everything else is deferred |
| [First run](docs/first-run.md) | Welcome, and what it refuses to do |
| [Concepts](docs/concepts.md) | Files, the index, public and private, the glossary |
| [Trust](docs/trust.md) | Threat model, merge gates, and what leaves the machine |
| [Vision](docs/vision.md) | The autonomy slider, shared repo context, one context graph |
| [Cockpit](docs/cockpit.md) | The browser UI |
| [CLI](docs/cli.md) | Every command |
| [Models](docs/models.md) | The optional endpoint a factory drafts with |
| [Dogfood](docs/dogfood.md) | Stead manages Stead: the `pr`-ceiling contract and the ledger metrics |
| [Deploy](docs/deploy.md) | Docker, the image, and sign-in |
| [Several writers](docs/multi-actor.md) | Actors, git, and why SQLite stays |
| [Roadmap](PLAN.md) | Design history and the §7 roadmap |
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

- **Every account on a shared server is an admin.** Accounts are names with
  scrypt password hashes; there are no roles and no per-object permissions.
  The cockpit refuses to start a build there, and execution fields (`checks:`,
  `protected_paths:`, reach, trigger, `code_path`, the author role, and spec
  approval) are read-only in the cockpit. Any signed-in person can still edit
  other context objects. Put it behind an SSO/TLS proxy if you expose it. There
  is no login rate limit. [docs/trust.md](docs/trust.md).
- **Checks are not sandboxed unless you ask.** The default is the host with a
  scrubbed environment. `checks_isolation: docker` gives a container with no
  network. Merge requires one of those, or an explicit `trust_checks: host`.
- **The independent reviewer is a model, not a guarantee.** A fresh invocation
  must approve the diff against the spec before merge (unless
  `merge_without_review: true`). It can be fooled by a plausible diff, and it
  shares the builder's endpoint unless `stead model set --review` names another
  model.
- **Budgets are time, count, tokens, and optional spend.** A build has a
  wall-clock cap (`--max-minutes`), a step cap, an edit cap, a daily
  watched-build count, a token budget (default 2M, `--max-tokens`), and an
  optional USD budget once model prices are set (`--max-cost`). A
  provider-side quota is still worth setting for defense in depth.
- The build executor is Stead's own whole-file edit loop. A pluggable executor
  (hand the edit loop to a headless agent in a sandbox, keep the gates) and a
  stronger eval gate are planned; see [Vision](docs/vision.md) and
  [PLAN.md §7](PLAN.md).
- **The Factories tab is rough.** It does not explain itself, New factory takes
  only a name and a title (no kind, input, or autonomy options), and a factory
  cannot be deleted yet. This is tracked as ASAP in
  [Vision](docs/vision.md#open-items-from-review).
- A normal `stead ui` stays on loopback. `--deploy` and Docker are the only
  public binds. They start with an account, or with the token until the first
  account exists.
- `actor:` is stamped when you select who is writing, or when that person is
  signed in on a shared server. It is not a permission check.
- A factory calls a model only when you pass `--generate` or check Draft
  with model. The endpoint is yours: OpenAI, Anthropic, Grok, or another
  chat server. Prompt contents and the egress table:
  [docs/trust.md](docs/trust.md).
- Write-back is factual: a versioned `build-record` document, contribution and
  task status on merge, and prior records in the next bundle. Decisions and
  glossary entries are proposed to the inbox for a person to triage; they are
  not written into context automatically. The SQLite `runs` table is still a
  rebuildable index, not the durable record.
- `specify` is optional. If it is missing, onboarding still writes the
  constitution in `context/documents/`.
- Frontmatter is a flat YAML subset, not full YAML. `stead doctor` reports a
  broken hand edit; it does not repair it.
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
