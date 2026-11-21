# FACTORY: weekly-project-status

The first factory. **Specific** (one task type: draft a weekly status update
for one project), **shared** (any agent/human can run it via the CLI),
**scrutinized** (versioned prompts, evals, run logs, human verdicts).

## Trigger

- **Scheduled (target):** weekly, e.g. Friday afternoon. Scheduler-agnostic:
  any cron / Windows Task Scheduler / Hermes cron job invokes:
  `python -m stead factory run --factory weekly-project-status --project <P> --shadow`
- **Event-driven (later):** project marked active, or manual trigger.
- **Now (Phase 1–2):** manual invocation only.

## Inputs

One project id. The runner deterministically gathers (no LLM involved):

1. `context/projects/<slug>.md` — the project object
2. All tasks with `project: <id>` (any status)
3. All documents with `project: <id>`
4. All meetings with `project: <id>`

## Stages

1. **Assemble** (`stead factory run`): build `bundle.md`, emit `prompt.md`
   (production prompt + bundle), write `run.json`, insert a `runs` row.
2. **Generate** (pluggable): any agent or human reads `prompt.md` and drafts
   the status update. No provider is hardwired; no API key is required by
   this repo.
3. **Review** (human, mandatory in shadow mode): check accuracy against the
   bundle, completeness, tone.
4. **Record**: `stead run log --factory weekly-project-status --task <project-id>
   --prompt-version <v> --output <draft> --verdict approved|rejected`.
5. **File** (only after approval, and only in later phases): the approved
   update becomes a document in `context/documents/` linked to the project.

## Outputs

- `runs/<timestamp>-<project>/bundle.md` — deterministic context bundle
- `runs/<timestamp>-<project>/prompt.md` — assembled prompt (the emit)
- `runs/<timestamp>-<project>/run.json` — run metadata
- `runs` row in state.db (verdict starts `pending`)
- After review: a drafted status update + verdict in the run ledger

## Tools

Python 3.14+ standard library only (`python -m stead`). Generation step: any
LLM/agent the operator chooses. No network dependency in the runner.

## Risk level & incremental rollout

**Low risk, shadow-first.**

1. **Shadow (current):** drafts only; nothing is filed or acted on without
   human approval. Default mode of `factory run`.
2. **Low volume (next):** after 3–5 reviewed shadow runs with mostly
   `approved` verdicts, schedule one project weekly.
3. **Consequential (filed):** `stead run file --run ID` writes an approved
   status update into `context/documents/`. The human approval is the gate.
   Nothing is posted.

## Scrutiny

- Prompts are versioned (`prompts/v1.md`, ...); `stead prompt list` shows
  testing/production/retired. Promote only after evals pass (`stead prompt
  promote`); old production is retired, never deleted.
- Evals live in `evals/*.json` (loaded into state.db by `stead init`).
- Review run logs weekly; fix **real observed failures**, not imagined ones.
