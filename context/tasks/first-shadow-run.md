---
id: task-first-shadow-run
type: task
title: Run first weekly-status shadow run
created: 2026-11-21
updated: 2026-11-21
status: doing
project: project-shared-context-rollout
---

# Run first weekly-status shadow run

Execute `python3 -m ctx factory run --factory weekly-project-status
--project shared-context-rollout --shadow`, hand the assembled `prompt.md` to
an agent, and record the drafted update with `ctx run log`.

Done when: one run directory exists with bundle.md, prompt.md, run.json, and a
logged verdict.
