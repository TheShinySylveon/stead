# Changelog

## Unreleased

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
