---
id: contribution-example-org-example-repo-issue-202
type: contribution
title: "EXAMPLE: Add --sort and --filter options to the list command"
created: 2026-11-21
updated: 2026-11-21
repo: repo-example-org-example-repo
kind: issue
number: 202
url: https://github.com/example-org/example-repo/issues/202
role: author
state: open
ci: none
review: none
method: spec-kit
visibility: public
tags: [example, seed, feature-spec]
---

# EXAMPLE: Add --sort and --filter options to the list command

**EXAMPLE SEED — not a real issue.** Demonstrates a *spec-kit* (Spec-Driven
Development) feature spec: `method: spec-kit` means `feature-builder` runs the
full SDD flow — constitution -> specify -> plan -> tasks -> implement ->
converge — with strong planning before any code. `method` selects only the
tooling; planning-before-code is unconditional in every run. Try it fully
offline:

```
python -m stead factory run --factory feature-builder \
    --contribution contribution-example-org-example-repo-issue-202 --shadow
```

## Description

The example repo's CLI `list` command prints items in a fixed order and cannot
narrow the output. Users with many items need to sort and filter without
piping through external tools. Add two opt-in flags: `--sort <field>` (ascending
by default, `--sort <field>:desc` for descending) and `--filter <field>=<value>`
(substring match on string fields, equality on others). The default output when
neither flag is present must remain byte-for-byte unchanged, so existing users
and tests are unaffected. Unknown fields in either flag are a usage error: print
to stderr and exit non-zero. Follow the repo's CONTRIBUTING guidance for test
layout and commit style.

## Acceptance criteria

- [ ] `list --sort <field>` orders output ascending by the given field; `:desc` suffix reverses it
- [ ] `list --filter <field>=<value>` restricts output to matching items only
- [ ] Combining `--sort` and `--filter` composes correctly (filter first, then sort)
- [ ] Default output (no flags) is byte-for-byte unchanged and existing tests pass
- [ ] An unknown `--sort` or `--filter` field prints to stderr and exits non-zero
- [ ] Unit tests cover sort (asc/desc), filter, combined, and the error case
