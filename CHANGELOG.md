# Changelog

## Unreleased

- README, concepts, PLAN, and factories state the Notion lineage and the
  deliberate twist: factories execute, and reach is per repo.
- `stead build --contribution ID` has the configured model plan, edit the
  repo checkout, run the repo's `checks:`, and commit on an isolated branch.
  `--publish` opens the pull request; `--merge` merges when the repo says
  `reach: merge`. `factory watch --build --publish [--merge]` does the same
  for every watched spec, and `schedule --watch [--merge]` runs it weekly.
  The model cannot choose shell commands and cannot leave the checkout.

## 0.1.0 — 2026-11-21

The cockpit catches up with the CLI, a shared server has per-person sign-in,
and the planned factory set is complete.

- Delete for projects, tasks, documents, meetings, repos, and actors, in the
  CLI and the reader. A linked project or repo is refused without force.
- A project's reader shows task counts, linked notes, and recent runs.
- Eval results are per case, so a failed promote shows which cases lack a pass.
  Judge asks the configured model about the newest draft for that factory.
- Run history shows beyond the newest six; the run viewer keeps the draft.
- The page shows its version, keeps scroll and focus, confirms before closing
  unsaved edits, traps focus in the reader, warns errors longer, and reflows at
  phone width.
- The Windows weekly task registers a short launcher in `private/`, so a deep
  checkout path no longer hits the 261-character limit.
- A review note no longer replaces the draft. It is stored as `note`, and the
  run viewer shows the draft, prompt, and bundle.
- "Needs you" lists one row per object with every reason.
- The cockpit shows the port it serves, signs out on a shared server, and
  edits a repo's `code_path` and `default_branch`.
- The cockpit covers the local commands: factory scaffold, watch, eval check,
  prompt promote, file an approved run, inbox file import, account reset,
  webhook token, index rebuild, and the weekly job. Publish and merge stay
  CLI-only, with the commands shown on the contribution.
- `stead run file --run ID` files an approved digest or status into
  `context/documents/`. It never posts, pushes, or merges.
- `stead schedule show` / `install` wire the weekly read-only sync, the
  changed-cache digest, and the maintenance draft. `--project P` also drafts a
  project status. A project id is checked before it goes into the command.
- `stead sync github --digest` assembles only after the cache changes.
- `context-maintenance` also sweeps duplicate titles.
- The container package `ghcr.io/theshinysylveon/stead` is public.
- `context-maintenance` drafts a triage note and does not edit the files.
  `stead factory new` scaffolds a factory. `stead inbox import` and `POST /hook`
  capture into the inbox only.
- Docs match the command: sign-in, publish, merge, and the image.
- `stead factory merge` merges a green pull request when the repo file says
  `reach: merge`. It does not bypass branch protection, and it does not push
  the default branch. Publish still does not merge.
- A shared server has per-person sign-in. Passwords are hashes in gitignored
  `private/accounts.json`. This computer still has no login.
- The container image is published to `ghcr.io/theshinysylveon/stead` on `main`.
- Writes stamp `actor:` when `stead actor use` or `STEAD_ACTOR` names an actor file.
- `stead prompt promote` refuses until every eval case has a recorded pass for that version.
- `stead factory publish` pushes an isolated branch and opens a pull request
  when the repo ceiling allows it. It refuses the default branch and does not merge.
- The command is `python -m stead`. `python -m ctx` still runs and says so.
- feature-builder trigger and reach. On demand or watch. Ceiling is per repo:
  shadow, draft-pr, pr, or merge. Merge is never inherited. A run above the
  ceiling is refused. Nothing is pushed, opened, or merged.
- Anthropic and Grok are model choices. Grok uses chat completions.
  Anthropic uses its messages API. The key stays out of git.
- Optional model drafts. `stead factory run --generate` and the cockpit checkbox
  call an OpenAI-compatible endpoint and write `output.md`. Assembly still
  calls nothing. Nothing is posted or pushed.
- `stead model set` / Settings store the endpoint. The key stays in the
  environment or gitignored `stead.json`.
- `stead eval run` checks eval files with no model. `stead eval judge` asks the
  configured model about one draft. Promote requires a recorded pass for that version.

## 0.0.1

First public snapshot of Stead.

- Local context system: markdown files, a rebuildable SQLite index, and a
  loopback cockpit.
- First-run welcome, plus a later onboard step for a constitution and
  optional Spec Kit.
- Three factories that assemble a prompt and stop: contribution digest,
  project status, and feature-builder.
- Single-user or shared-server choice. The shared server is a Docker image
  with a required access token.
- Actors as files. Several clones share markdown through git.

Not in this version: per-person passwords, draft pull requests, automatic
actor stamps, or a published container image.
