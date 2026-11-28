# Documentation

Human docs for Stead. The command is `stead`. The README is the front door.
This folder is the rest of the house. Agent rules live in `AGENTS.md`. The
file format lives in `CONVENTIONS.md`.

Stead is licensed under the Apache License, Version 2.0. See `LICENSE`.
Copyright 2026 Tyler Rathbone. That license allows commercial use. You keep
the copyright in code you write.

## Start here

1. [Getting started](getting-started.md) — clone, requirements, first command.
2. [MVP](mvp.md) — the one loop that must work; the focus filter for all other work.
2. [First run](first-run.md) — the welcome screen, and what it does not do.
3. [Concepts](concepts.md) — files, the index, and our twist on Notion's model.
4. [Several people and agents](multi-actor.md) — git shares the files. SQLite stays local.
5. [Deploy](deploy.md) — this computer, or a Docker shared server.
6. [Trust](trust.md) — what is trusted, what merge requires, what leaves the machine.

The long-range design is [Vision](vision.md): the autonomy slider, opt-in
repo context, and one context graph across repos.

## Use it

- [Cockpit](cockpit.md) — the local browser UI.
- [CLI](cli.md) — every `stead` command.
- [Factories](factories.md) — the four workflows, scheduling, and why a draft is not a merge.
- [Models](models.md) — the optional OpenAI-compatible endpoint factories draft with.
- [Spec Kit](spec-kit-workflow.md) — planning before code, and `stead onboard`.
- [Review guide](review.md) — what to verify before merging a PR.

## Not in this folder

- `examples/context/` — sample objects. Not loaded into a fresh checkout.
- `PLAN.md` — design record and the autonomy roadmap. Do not treat it as a user guide.

## Keep local artifacts out of commits

Use `.worktrees/` for local Git worktrees and `.venv/` for an optional development
environment. Git and Docker exclude these, tool caches, local secrets, and generated
factory runs. Keep authored Markdown under `context/` or `inbox/` in your own
context repository; don't put your working data in the public Stead repo.
