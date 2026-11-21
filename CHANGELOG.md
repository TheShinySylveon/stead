# Changelog

## Unreleased

- feature-builder trigger and reach. On demand or watch. Ceiling is per repo:
  shadow, draft-pr, pr, or merge. Merge is never inherited. A run above the
  ceiling is refused. Nothing is pushed, opened, or merged.
- Anthropic and Grok are model choices. Grok uses chat completions.
  Anthropic uses its messages API. The key stays out of git.
- Optional model drafts. `ctx factory run --generate` and the cockpit checkbox
  call an OpenAI-compatible endpoint and write `output.md`. Assembly still
  calls nothing. Nothing is posted or pushed.
- `ctx model set` / Settings store the endpoint. The key stays in the
  environment or gitignored `stead.json`.
- `ctx eval run` checks eval files with no model. `ctx eval judge` asks the
  configured model about one draft. Promote does not require that yet.

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
