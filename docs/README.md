# Documentation

Human docs for Stead. The command is `stead`. The README is the front door.
This folder is the rest of the house. Agent rules live in `AGENTS.md`. The
file format lives in `CONVENTIONS.md`.

Stead is licensed under the Apache License, Version 2.0. See `LICENSE`.
Copyright 2026 Tyler Rathbone. That license allows commercial use. You keep
the copyright in code you write.

## Start here

1. [Getting started](getting-started.md) — clone, requirements, first command.
2. [First run](first-run.md) — the welcome screen, and what it does not do.
3. [Concepts](concepts.md) — files, the index, factories, and what stays private.
4. [Several people and agents](multi-actor.md) — git shares the files. SQLite stays local.
5. [Deploy](deploy.md) — this computer, or a Docker shared server.

## Use it

- [Cockpit](cockpit.md) — the local browser UI.
- [CLI](cli.md) — every `stead` command.
- [Factories](factories.md) — the four workflows, scheduling, and why a draft is not a merge.
- [Models](models.md) — the optional OpenAI-compatible endpoint factories draft with.
- [Spec Kit](spec-kit-workflow.md) — planning before code, and `stead onboard`.

## Not in this folder

- `examples/context/` — sample objects. Not loaded into a fresh checkout.
- `PLAN.md` — design history. Do not treat it as a user guide.
