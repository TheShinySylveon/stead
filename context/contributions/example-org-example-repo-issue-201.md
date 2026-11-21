---
id: contribution-example-org-example-repo-issue-201
type: contribution
title: "EXAMPLE: Add --json output to the list command"
created: 2026-11-21
updated: 2026-11-21
repo: repo-example-org-example-repo
kind: issue
number: 201
url: https://github.com/example-org/example-repo/issues/201
role: author
state: open
ci: none
review: none
visibility: public
tags: [example, seed, feature-spec]
---

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