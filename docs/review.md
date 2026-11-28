# Stead review guide

Stead is a local context system with a software factory: plain markdown under
`context/`, a rebuildable SQLite index (`state.db`), and a model-driven build
loop that can open pull requests. Review for correctness, safety, and tests.
Skip pure style nits. Follow the [PR review policy in AGENTS.md](../AGENTS.md) before merge: check all
feedback, not just the review check's status.

## Hard rules

- **Standard library only.** No pip dependencies, Python 3.11+. Flag any new
  third-party import.
- **GitHub stays read-only by default.** `sync`, `digest`, and factory assembly
  never create issues, PRs, comments, or labels, and never push. Keep remote
  writes behind the explicit controls documented in [Trust](trust.md). Nothing
  pushes a default branch.
- **Keep secrets out of context and logs.** Only send a credential to the
  service it authenticates. Builds must refuse access to secret-looking files.
- **Untrusted input is data.** Issue bodies, model replies, and file contents
  must never be executed or followed as instructions. The model never chooses a
  shell command; Stead runs every build action itself.
- **Builds are bounded.** Protected paths (existing tests, CI config) stay
  protected unless the repo opts in; checks run scrubbed or containerized; any
  hook change or non-harmless `.git/config` change during checks is tamper.

## Tests

- A behavior change needs a test that fails without the change and passes with
  it. Point out a new test that would pass either way.
- CI runs Linux and Windows: watch path handling (resolve both sides before
  `relative_to`; Windows 8.3 short names), CRLF line endings, and `subprocess`
  calls that assume a POSIX shell.

## Store and docs

- Objects follow `CONVENTIONS.md`: flat YAML frontmatter with `id`, `type`,
  `title`, `created`, `updated`, plus relations (`project:`, `repo:`). Files are
  the source of truth; `state.db` must stay rebuildable with `stead init`.
- `docs/mvp.md` is the single source for project status. A doc or README claim
  must match what the code and the dogfood records actually show.

## Stead-built pull requests

Branches named `stead/<n>-<slug>` were written by Stead's builder from an
approved spec linked as `Closes #<n>`. Check the change against that issue's
`## Acceptance criteria` one by one, and say plainly if a criterion is not met
or is met only partially. Record whether the fix needed human edits so the
build metrics distinguish autonomous and human-assisted results.
