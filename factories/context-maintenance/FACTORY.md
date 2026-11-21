# FACTORY: context-maintenance

One job: draft a triage note for this checkout. It looks at the inbox, broken
relations, and stale objects. It does not edit those files. It does not post,
push, or merge.

## Trigger

Manual, or any scheduler:

```bash
python -m stead factory run --factory context-maintenance --shadow
```

## Inputs

Local files only. No network.

- `inbox/*.md`
- objects whose `project:` or `repo:` does not resolve
- objects whose `updated` date is older than 30 days, unless status is `done`
  or `archived`

Private notes may appear in the bundle. The draft stays on disk.

## Stages

1. Assemble a deterministic bundle. No model, no network.
2. Optional `--generate` writes `output.md`. That file is a draft.
3. A person triages the inbox and fixes relations. The factory does not.

## Must not

- Edit `context/` or `inbox/` during assembly.
- Create an issue, comment, label, or pull request.
- Guess a missing relation.
