# Feature build bundle — EXAMPLE: Add --json output to the list command
<!-- factory: feature-builder | prompt: v1 | mode: shadow | created: 2026-11-21T07:29:55Z -->

## Build target (feature spec)
### [issue #201] EXAMPLE: Add --json output to the list command
role: author | state: open | ci: none | review: none | updated: 2026-11-21
url: https://github.com/example-org/example-repo/issues/201
<!-- source: context/contributions/example-org-example-repo-issue-201.md | id: contribution-example-org-example-repo-issue-201 -->

# EXAMPLE: Add --json output to the list command

**EXAMPLE SEED — not a real issue.** Demonstrates a *buildable feature spec*
for the `feature-builder` factory: a contribution with `kind: issue`,
`role: author`, tagged `feature-spec`, whose body has a description plus a
`## Acceptance criteria` checklist. Try it fully offline:

```
python3 -m ctx factory run --factory feature-builder \
    --contribution contribution-example-org-example-repo-issue-201 --shadow
```

## Description

The example repo's CLI `list` command currently prints a human-readable table
only. Scripts and agents that consume its output have to parse that table,
which is brittle. Add an opt-in `--json` flag to `list` that emits machine-
readable output instead: a single JSON array on stdout, one object per listed
item, with stable field names. The default human-readable output must remain
byte-for-byte unchanged when the flag is absent, so existing users and tests
are unaffected. Errors still go to stderr with a non-zero exit code; `--json`
changes the success-path format only. Follow the repo's CONTRIBUTING guidance
for test layout and commit style.

## Acceptance criteria

- [ ] `list --json` prints a single valid JSON array to stdout (one object per item)
- [ ] Each JSON object contains at least the fields `id`, `title`, and `status`
- [ ] Without `--json`, the human-readable output is unchanged (existing tests still pass)
- [ ] An empty list prints `[]` with exit code 0
- [ ] Unit tests cover the `--json` happy path and the empty-list case

## Acceptance criteria
Map EACH criterion below to at least one test before writing code:
- [ ] `list --json` prints a single valid JSON array to stdout (one object per item)
- [ ] Each JSON object contains at least the fields `id`, `title`, and `status`
- [ ] Without `--json`, the human-readable output is unchanged (existing tests still pass)
- [ ] An empty list prints `[]` with exit code 0
- [ ] Unit tests cover the `--json` happy path and the empty-list case

## Spec quality flags
None — spec looks buildable (description + acceptance criteria present).

## Repo conventions — EXAMPLE example-org/example-repo (not a real repo) (repo-example-org-example-repo) [kind: oss]
- url: https://github.com/example-org/example-repo
- default_branch: main
- contributing: https://github.com/example-org/example-repo/blob/main/CONTRIBUTING.md
- status: active
<!-- source: context/repos/example-org-example-repo.md | id: repo-example-org-example-repo -->

# EXAMPLE example-org/example-repo

**EXAMPLE SEED — not a real repository.** Created to demonstrate the
`repo`/`contribution` ontology and the `weekly-contribution-digest` factory
fully offline. Replace with real repos via `ctx repo add` or `ctx sync github`
when you choose specific repos (that decision is deferred per PLAN.md).

## Related documents (0)

_None linked._

## Related work in local cache (3)
Duplicate/overlap sweep input: other cached contributions in this repo. Check these (and live GitHub, read-only) for duplicate or overlapping work BEFORE building; surface anything that overlaps.

### [issue #103] EXAMPLE: Docs — clarify the contribution workflow
role: assignee | state: open | ci: none | review: none | updated: 2026-11-21
url: https://github.com/example-org/example-repo/issues/103
<!-- source: context/contributions/example-org-example-repo-issue-103.md | id: contribution-example-org-example-repo-issue-103 -->

# EXAMPLE: Docs — clarify the contribution workflow

**EXAMPLE SEED — not a real issue.** Demonstrates an open issue claimed by the
user (`role: assignee`). Note the title contains a colon, exercising the flat
frontmatter quoting rules.

### [pr #101] EXAMPLE: Add caching layer to the parser
role: author | state: open | ci: pass | review: requested | updated: 2026-11-21
url: https://github.com/example-org/example-repo/pull/101
<!-- source: context/contributions/example-org-example-repo-pr-101.md | id: contribution-example-org-example-repo-pr-101 -->

# EXAMPLE: Add caching layer to the parser

**EXAMPLE SEED — not a real PR.** Demonstrates an open PR authored by the user
(`role: author`), CI passing, awaiting maintainer review. Used by the
`weekly-contribution-digest` shadow run.

### [pr #102] EXAMPLE: Fix off-by-one in pagination
role: reviewer | state: open | ci: pending | review: requested | updated: 2026-11-21
url: https://github.com/example-org/example-repo/pull/102
<!-- source: context/contributions/example-org-example-repo-pr-102.md | id: contribution-example-org-example-repo-pr-102 -->

# EXAMPLE: Fix off-by-one in pagination

**EXAMPLE SEED — not a real PR.** Demonstrates a PR where the user is a
requested reviewer (`role: reviewer`) and a reply is owed; CI still pending.

## Mode & safety (binding)
Mode: **SHADOW** (default). Propose a plan and a proposed diff ONLY.
NO remote writes of any kind: no push, no branch creation on the remote,
no PR/issue/comment/label creation. All output stays local for human review.
Hard rules in every mode: never push to main/the default branch directly; never auto-merge; a human reviews before anything consequential; vague or large specs are flagged for decomposition, never guessed.