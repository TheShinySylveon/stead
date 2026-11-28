# Stead

**Rent the model. Own the context.**

[![CI](https://github.com/TheShinySylveon/stead/actions/workflows/ci.yml/badge.svg)](https://github.com/TheShinySylveon/stead/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/TheShinySylveon/stead)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue)](docs/getting-started.md)

Stead is a local workspace for projects, tasks, notes, and GitHub work. It stores
context in plain Markdown you can read and version with Git. Browse those files
in the cockpit or use the CLI; neither requires a model or an account.

With a model configured, a **factory** can draft a spec from an issue, build the
approved change on a separate branch, and run the repo's checks. Each repo has
its own limit: for example, draft a plan only, open a PR, or merge after the
configured checks pass. Build records go back into the same Markdown store.

See [MVP status and roadmap](docs/mvp.md) for what's shipped and
[Dogfood results](docs/dogfood.md) for what was tested end to end.

## Quick start

Requires Python 3.11+. No pip packages.

```bash
git clone https://github.com/TheShinySylveon/stead.git
cd stead
python -m stead ui
```

Open **http://127.0.0.1:8765/**. A fresh checkout shows Welcome — name a
project and you're in. No browser? `python -m stead welcome --title "My Project"`.

![Stead cockpit](docs/images/cockpit.png)

![First run](docs/images/welcome.png)

## What you get

- **One connected graph.** Projects, tasks, documents, meetings, and repos linked
  by relations in flat-YAML-frontmatter markdown. Git is the audit trail.
- **Two readers.** Agents get scoped bundles; people get a Confluence-style wiki.
  No second store to drift.
- **One dial per repo.** A factory stops at a shadow plan, opens a draft or
  normal PR, or merges — never inherited, never bypassing branch protection.
- **Factories that execute.** Four pipelines — contribution digest, project
  status, feature-builder, context maintenance — plan, assemble, and (with a
  model) edit code, run checks, and deliver under the repo's ceiling.
- **Write-back.** A delivered build writes a versioned `build-record`; decisions
  and glossary terms are only *proposed* to the inbox, never quietly written.
- **A browser cockpit or the CLI.** The same actions either way, plus an
  optional shared Docker server ([deploy](docs/deploy.md)).

## Build checks

Stead checks the spec before building and runs the repo's tests before delivery.
These checks complement human review:

- **Planning before code, always.** A build refuses to start without a spec and
  an approved plan; autonomy changes what the agent may produce, never whether
  it plans.
- **Spec validation.** A spec is refused if it's too vague,
  too large, has no acceptance criteria, or asks for a value a hardcoded number
  could satisfy — a "score" or "non-zero float" gets flagged `fabricated-value`
  before any code is written.
- **Fail-before, pass-after tests.** The build maps acceptance criteria to
  tests. When the regression-test gate is enabled, Stead checks that new tests
  fail without the change and pass with it.
- **Anti-slop gate on new code.** Deterministic, language-agnostic rules refuse
  a new file that carries a hard finding (bare `except:`, `gets(`, `%`-format,
  commented-out code, dead branches) and nudge on advisory ones (debug `print`,
  `console.log`, `any` types). The repo's own linter via `checks:` stays the
  authoritative gate — Stead layers on top, it doesn't replace it.
- **Honest CI.** The build runs the repo's checks and reports them truthfully.
  Nothing is claimed green that wasn't checked.

## Build records and metrics

The context outlives the model, and the system gets stricter over time. Every
build — success or failure — writes a versioned `build-record` into the same
graph. A human marks each one against the correctness rubric, and when a build
is wrong, that verdict feeds back two ways:

- **Mistake → rule.** Mark a build incorrect with
  `stead metrics mark ID --correct false --rule "…"`, and the described check
  is proposed to the inbox as a candidate anti-slop rule. A failure becomes a
  future automated check instead of a repeat.
- **The ledger.** `stead metrics` reports what actually happened — builds,
  failure rate, share merged after review, hand-checked correct vs. committed —
  so the number you ship is real, never invented.

## Safety

Stead can run code and merge it. The threat model, the merge gates, and exactly
what leaves the machine: **[docs/trust.md](docs/trust.md)**. It's 0.1.0 — the
known limits (shared-server roles, check sandboxing, reviewer strength) live
there too.

## Documentation

| | |
|---|---|
| [Getting started](docs/getting-started.md) | Requirements, clone, first command |
| [MVP](docs/mvp.md) | The one loop that must work; everything else is deferred |
| [First run](docs/first-run.md) | Welcome, and what it refuses to do |
| [Concepts](docs/concepts.md) | Files, the index, public and private, the glossary |
| [Trust](docs/trust.md) | Threat model, merge gates, and what leaves the machine |
| [Cockpit](docs/cockpit.md) | The browser UI |
| [CLI](docs/cli.md) | Every command |
| [Factories](docs/factories.md) | The four workflows |
| [Models](docs/models.md) | The optional endpoint a factory drafts with |
| [Dogfood](docs/dogfood.md) | Stead manages Stead: the contract and the ledger |
| [Deploy](docs/deploy.md) | Docker, the image, and sign-in |
| [Several writers](docs/multi-actor.md) | Actors, git, and why SQLite stays |
| [Vision](docs/vision.md) | The autonomy slider and long-range design |
| [Roadmap](PLAN.md) | Design history and the §7 roadmap |
| [CONVENTIONS.md](CONVENTIONS.md) | Frontmatter schema. Read before writing objects. |
| [AGENTS.md](AGENTS.md) | Entry point for coding agents |

## Repository layout

| Path | What belongs there |
|---|---|
| [`stead/`](stead/) and [`ctx/`](ctx/) | Command entry point and standard-library implementation |
| [`tests/`](tests/) | Regression tests |
| [`factories/`](factories/) | Workflow definitions, prompts, and eval cases |
| [`context/`](context/), [`inbox/`](inbox/), and [`examples/`](examples/) | Store structure, capture entry point, and sample data. Keep your working data in a separate context repo. |
| [`docs/`](docs/) | User and contributor guides |
| [`deploy/`](deploy/) | Container startup script; `Dockerfile` and `docker-compose.yml` stay at the root |

Local worktrees, caches, generated runs, and credentials are not part of the
source tree. See [local artifact rules](docs/README.md#keep-local-artifacts-out-of-commits).

## Develop

```bash
python -m unittest discover -s tests -b
```

CI runs the suite on Python 3.11 and 3.12, Linux and Windows, plus `ruff`
(config in `ruff.toml`) and CodeQL. Merging to `main` publishes
`ghcr.io/theshinysylveon/stead`. The [review guide](docs/review.md) applies
whether feedback comes from a person or a review bot.

## License

Apache License, Version 2.0. Copyright 2026 Tyler Rathbone. See [LICENSE](LICENSE).
