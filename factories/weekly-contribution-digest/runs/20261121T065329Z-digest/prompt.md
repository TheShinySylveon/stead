# Prompt v1 — weekly-contribution-digest (production)

You are drafting a **weekly contribution digest** for one person who works on
their own projects and contributes to open-source repos. The context bundle
below the `---` separator is the complete, authoritative input: a read-only
local cache of their public GitHub contributions (PRs, review requests,
assigned issues) grouped by repo, with CI and review state. Do not invent facts
that are not in the bundle. Do not fetch anything from the network.

## Instructions

Write the digest in Markdown, **grouped by repo** (one section per repo that
has contributions; use the repo title, mark own vs oss). Within each repo
section use exactly these subsections, omitting any that are empty:

1. **PRs in flight** — open PRs where the user is the author (`role: author`).
   One bullet each: PR number + title, review state, CI state, and the single
   next action implied by the bundle (e.g. "awaiting review", "address change
   requests"). If CI is `fail` or `pending`, say so explicitly.
2. **Reviews awaiting reply** — open PRs where the user is a requested reviewer
   (`role: reviewer`). One bullet each: PR number + title, how long it has been
   waiting if `updated` suggests staleness, and that a reply is owed.
3. **Claimed issues** — open issues assigned to the user (`role: assignee`).
   One bullet each: issue number + title and current state.
4. **CI flags** — any open contribution with `ci: fail` (first) or `ci: pending`
   that needs attention. If none, write "None."

Then close with:

5. **This week's focus** — 2–4 bullets recommending what to tackle first,
   ordered by: failing CI on your own PRs > reviews you owe > your PRs awaiting
   review > claimed issues. Justify each pick from bundle facts only.

Start the digest with a one-line header: `# Weekly contribution digest — <date>`
(use the bundle's `created` timestamp date) and a one-sentence summary with the
bundle's Summary counts.

## Rules

- Be factual and concise: the whole digest should be 150–400 words.
- Every claim must be traceable to the bundle. If the cache looks stale or thin,
  say so explicitly and suggest `ctx sync github` instead of guessing.
- Reference PRs/issues by number and title, and link the url from the bundle.
- Plain professional tone; no marketing language, no emoji.
- **Never post anything.** Output only the digest Markdown; a human reviews it.
  Do not suggest automated comments/reviews/posts to GitHub.
- Do not include or infer private strategy notes; the bundle is public data only.
- This is a shadow run: a human will review your draft before it is filed.

---

# Contribution digest bundle — weekly
<!-- factory: weekly-contribution-digest | prompt: v1 | mode: shadow | created: 2026-11-21T06:53:29Z -->

## Summary
- repos with contributions: 1
- contributions cached: 3
- PRs in flight (author, open): 1
- reviews awaiting reply (reviewer, open): 1
- claimed issues (assignee, open): 1
- CI flags (open, ci fail/pending): 1

Data is a read-only local cache of public GitHub state (context/contributions/, visibility: public). No private notes are included.
## Repo: EXAMPLE example-org/example-repo (not a real repo) (repo-example-org-example-repo) [kind: oss]
url: https://github.com/example-org/example-repo

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
