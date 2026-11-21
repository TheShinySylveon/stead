# Factories

A factory is a shared, named workflow. Each one lives in `factories/<name>/`:

- `FACTORY.md` — what it is, what it may do, and what it must not do.
- `prompts/vN.md` — versioned instructions. The highest version is production
  after `ctx init`. Switch with `ctx prompt promote`.
- `evals/*.json` — cases and pass criteria. Tests check that the files are
  well-formed. They do not call a model to judge a run.
- `runs/` — one directory per assembly. Gitignored. Safe to delete.

## What a run actually does

`python3 -m ctx factory run` reads local files and writes three things:

- `bundle.md` — the context the workflow is allowed to see.
- `prompt.md` — the production prompt plus that bundle.
- `run.json` — counts, mode, and flags.

No model is called. No network is used. You, or any agent, read `prompt.md`,
do the work, and record a verdict:

```bash
python3 -m ctx run log --factory F --task REF --prompt-version vN \
    --output "what happened" --verdict approved
```

The cockpit can assemble the same shadow run and approve or reject it.

## The three factories

### weekly-contribution-digest

A weekly picture of pull requests in flight, reviews waiting on you, claimed
issues, and CI, across the repos in the local cache.

```bash
python3 -m ctx sync github --limit 30
python3 -m ctx digest
```

It drafts. It never posts to GitHub.

### weekly-project-status

A status draft for one of your projects, from its tasks, documents, and
meetings.

```bash
python3 -m ctx factory run --factory weekly-project-status \
    --project project-id --shadow
```

### feature-builder

Turns a feature spec you authored into a build bundle. The spec is a
contribution with `kind: issue`, `role: author`, tag `feature-spec`, and a
`## Acceptance criteria` checklist.

```bash
python3 -m ctx factory run --factory feature-builder \
    --contribution contribution-id --shadow
```

Every run is planning-first. A thin, vague, or oversized spec is flagged for
decomposition instead of being built. `method` on the spec is `spec-kit` or
`builtin`. Both plan before code. Only the tooling changes. See
[Spec Kit](spec-kit-workflow.md).

## Shadow, and what is not built

Shadow is the only mode the cockpit offers, and the default on the CLI.
Output stays on disk.

A future draft-PR step would push an isolated branch and open a draft pull
request for a human to merge. That step is not implemented. Nothing in this
repository auto-merges.

## Scheduling

There is no built-in timer. Any scheduler can run the CLI:

```bash
python3 -m ctx sync github --limit 30
python3 -m ctx factory run --factory weekly-contribution-digest --shadow
```
