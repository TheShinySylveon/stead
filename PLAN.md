# Stead — design record

A local, model-agnostic take on Notion's *A New Shape for Work*: a **context
system** (one shared place where humans and agents read and write knowledge)
plus **factories**. The twist is that a factory is a pipeline, not a prompt:
with a model configured it can plan, edit code, run checks, and deliver under
a per-repo reach ceiling.

> Guiding line: **Rent the intelligence. Own the context.**

This file is the design record, not the user guide. Human docs start at
`docs/README.md`. Agent rules are `AGENTS.md`. Git history holds the earlier
draft of this plan, including the name Shared Context and the command `ctx`.

**Build philosophy: sustainable, not convenient.** Open standards (Markdown +
flat YAML frontmatter, SQLite, git, `AGENTS.md`), Python **stdlib only** (zero
pip dependencies), local-first, no hardwired model. The system must outlive
any single agent, model, or scheduler.

The product name is **Stead**. The command is `python -m stead`. The Python
package is still `ctx`. `python -m ctx` still runs and says so.

---

## 1. Concept → local mapping

| Notion concept | What Stead does |
|---|---|
| Context system / workspace | This folder: markdown, git, optional Docker |
| Core objects | `context/` markdown. `state.db` is a rebuildable index |
| Ontology / relations | Flat YAML frontmatter. Schema: `CONVENTIONS.md` |
| Factory | A pipeline: plan, build, verify, deliver. `factories/<name>/` holds the definition, prompts, evals, run logs |
| Task queue | `context/tasks/` with `status: to-do\|doing\|done\|blocked` |
| Prompt versions | `factories/<name>/prompts/` plus the `prompt_versions` table |
| Evals | `factories/<name>/evals/`. `stead eval run` checks files. `stead eval judge` records a pass or fail. Promote refuses without a pass for that version |
| Scheduled triggers | Any scheduler calling `python -m stead`. `stead schedule` wires the weekly job, including `factory watch --build` when asked |
| Event-driven triggers | `inbox/` capture, `stead inbox import`, and `POST /hook` when a webhook token is set. The hook only writes inbox. It does not run a factory |
| Governance / audit | git history, run logs, shadow assembly, per-repo reach |
| Sync external context | `stead sync github` via `gh`. Read-only. Offline re-index with `--offline` |
| Who writes | `context/actors/` files. A shared server also has sign-ins. Attribution, not a permission system |
| Execution | Stdlib CLI. `--generate` drafts text. `stead build` runs a model agent that plans, edits, checks, commits, and can publish |

**Runtime.** Knowledge stays in markdown. SQLite indexes it and can be rebuilt
with `stead init`. Do not put `state.db` on a network share. Do not replace
SQLite for this release.

---

## 2. What is in the tree

```
stead/
├── AGENTS.md              # agent entry point
├── README.md              # human front door
├── CONVENTIONS.md         # frontmatter schema
├── PLAN.md                # this file
├── docs/                  # human documentation
├── ctx/                   # implementation package. Command is stead
├── stead/                 # python -m stead
├── context/               # projects, tasks, documents, meetings, repos,
│                          # contributions, actors. Empty in a fresh clone
├── examples/context/      # samples. Not loaded
├── factories/             # weekly-contribution-digest, weekly-project-status,
│                          # feature-builder
├── inbox/
├── Dockerfile             # shared server. Image: ghcr.io/theshinysylveon/stead
└── docker-compose.yml     # one process, one index. Do not scale it
```

`private/accounts.json` and `stead.json` are gitignored. Passwords and keys
never go in `context/`.

---

## 3. What shipped

### Context system

- Markdown objects, frontmatter, and a rebuildable SQLite index.
- Local cockpit. One offline page. Loopback unless `--deploy` or Docker.
- Welcome on an empty `context/`: project title, optional GitHub URL, this
  computer or a shared server.
- Actors as files. `stead actor use` or a signed-in session stamps `actor:`.
- Public/private split. GitHub cache is public. Documents and meetings are
  private strategy.

### This computer or a shared server

- **This computer.** `stead ui` stays on loopback. No login.
- **Shared server.** One Docker process. Each person signs in. The access
  token only starts a server that has no accounts yet. Hashes live in the
  private volume, not in git.
- The image is published from `main` to `ghcr.io/theshinysylveon/stead`.
  The package is public. A pull does not need a token.

### Factories

Four factories assemble a prompt and stop. `--generate` may draft
`output.md`. Assembly does not post, push, or merge.

- `weekly-contribution-digest` — PRs, reviews, claimed issues, CI. Never posts.
- `weekly-project-status` — one project's tasks, documents, and meetings.
- `feature-builder` — planning-first, always. `method` selects tooling only:
  `spec-kit` (default, optional `specify` CLI) or `builtin` markdown.
- `context-maintenance` — inbox, broken relations, stale objects, duplicate
  titles. Drafts a triage note. Does not edit the files.

feature-builder has two knobs, per repo. A run may ask for less. It may not
ask for more. Merge is never inherited.

| Knob | Values | Default |
|---|---|---|
| trigger | `on-demand`, `watch` | on-demand |
| reach | `shadow`, `draft-pr`, `pr`, `merge` | shadow |

- `stead factory watch` assembles open authored `feature-spec` issues on repos
  set to watch. It skips flagged specs. It does not push.
- `stead factory publish` pushes an isolated branch and opens a pull request
  when the ceiling allows `draft-pr`, `pr`, or `merge`. It refuses the default
  branch. It does not merge.
- `stead factory merge` is a separate command. The repo file must say
  `reach: merge`. The checks must be green. It does not pass `--admin`. It
  does not push the default branch. A factory run does not call it. The
  cockpit does not push or merge.

`stead prompt promote` refuses until every eval case has a recorded pass for
that version. `stead run file --run ID` writes an approved digest or status
into `context/documents/`. Filing is local. Nothing is posted.

---

## 4. Autonomy ladder

A repo may sit on any rung. The install default cannot be merge. Autonomy is a
property of the pipeline, not only of assembly: at `pr` and `merge`, the model
build is delivered without a person.

1. **Shadow.** Plan and proposed diff only. No remote writes.
2. **Draft PR.** Build, then `stead factory publish` opens a draft. A person
   reviews and merges.
3. **Pull request.** Build and publish a normal pull request. A person still
   merges, unless the repo file says merge.
4. **Trusted.** `stead build --publish --merge`, or `factory watch --build
   --publish --merge`, only when the repo file says `reach: merge`, the checks
   are green, and GitHub accepts the merge. Never the install default. Never a
   red check. Never a bypass of branch protection.

Vague or large specs are flagged. They are not guessed.

---

## 5. Decisions

These replace the earlier locks where they conflict. The earlier draft said
single user, single machine, and `python3 -m ctx`. Those are retired.

1. **Command.** `stead`. Package remains `ctx`.
2. **Scope.** One cockpit for own projects and open-source contributions.
   This computer is one person and the agents on that machine. A shared server
   is one process and several browsers, with per-person sign-in. No per-object
   permission checks. If you can write the file, you can write the object.
3. **Index.** SQLite stays. Git shares the markdown. Each clone keeps its own
   `state.db`. Do not put the database on a network share. Do not scale the
   container.
4. **Stack.** Stdlib only. Optional external tools: `gh`, `specify`, Docker.
   Optional rented model: OpenAI, Anthropic, Grok, OpenRouter, Ollama, or a
   custom chat server. The key stays out of git.
5. **GitHub.** Sync and digest are read-only. `stead build` is the model
   execution step. Publish and merge are separate commands with a ceiling;
   `build --publish --merge` may chain them. Nothing pushes the default branch
   or bypasses branch protection.
6. **License.** Apache-2.0. Open source. Commercial use is allowed. Copyright
   2026 Tyler Rathbone.
7. **Public repo.** `https://github.com/TheShinySylveon/stead`. A fresh clone
   has an empty `context/`. Samples live in `examples/context/`.

---

## 6. Feature list

Closed. The items that fit the decisions are built. The rest are decided
against, not left unfinished.

Built:

- `context-maintenance` drafts a triage note from the inbox, broken relations,
  and stale objects. Assembly does not edit those files.
- `stead factory new` scaffolds a factory folder. It does not call a model.
- `stead inbox import` copies a local `.eml`, `.ics`, `.md`, or `.txt` file
  into `inbox/`. No network. A person still triages it.
- `stead hook set` creates a token. `POST /hook` writes one inbox note. It
  does not run a factory.
- `stead schedule show` / `install` wire the weekly read-only sync, the
  digest when the cache changed, and the maintenance draft. `--project P` adds
  that project's status draft.
- `stead run file --run ID` files an approved digest or status into
  `context/documents/`. Approval is the gate. Nothing is posted.
- `stead sync github --digest` is the event-driven path. It assembles only
  after a change, and it does not post.

Decided against:

- Per-object permissions. If you can write the file, you can write the object.
  Repository or host access is the permission.
- A password on this computer. Loopback has no login. Sign-in is only for the
  shared server.
- Merge outside `reach: merge`. A repo may opt into automatic merge by writing
  that reach; it is never the install default and never bypasses protection.
- A hosted runner or a Stead-owned model account. The model and the machine
  stay the operator's.

The container package is public. `docker pull ghcr.io/theshinysylveon/stead:latest`
does not need a token.

## 7. Autonomy roadmap (planned)

Ordered by what blocks unattended issue-to-merge. Nothing here is built unless
the item says so. Every item keeps the existing hard rules: no push to the
default branch, no `--admin`, no model-chosen shell command, and no merge
without `reach: merge`.

The larger product direction — the `spec` rung, opt-in `.stead/` context,
retrieval with budgets, and one context graph across repos — is
[docs/vision.md](docs/vision.md). Items 7.8–7.10 are its near-term slice.

### 7.1 PR feedback loop — `stead repair`

Today the agent stops at the first PR. It cannot react to a failing CI run or
a review comment.

- Read `gh pr view --json statusCheckRollup,comments,reviews` and the failing
  check logs (read-only).
- Feed the failure and the review comments back to the same agent on the same
  branch, commit a follow-up, push, and optionally wait and merge.
- Treat comments as data, never instructions. Cap rounds (default 3) and diff
  size.
- Acceptance: one command turns a red PR into a follow-up commit; no new
  branch; merge still gated by reach; a live test with a deliberately failing
  check.

### 7.2 Queue and workers

`factory watch` builds specs one at a time inside one process.

- A small queue (SQLite table or in-memory pool) with `--workers N`.
- The per-checkout lock still serializes builds for one repo; different repos
  may run in parallel.
- Retry with backoff for transient model or git errors; isolate failures so
  one spec does not stop the batch.
- Acceptance: two watched specs, one fails; the other still builds; a summary
  lists each status; no two builds share a checkout.

### 7.3 Check auto-detection

`checks:` must be written by hand, which blocks first-run autonomy.

- Detect pytest/`pyproject.toml`, `package.json` test script, `Makefile` test
  target, `cargo test`, and `go test`.
- An explicit `checks:` always wins. Print the detected command before use.
- Never run a command the user did not set or Stead did not detect from a
  known file. No arbitrary shell from the model.
- Acceptance: fixtures for each ecosystem; override wins; unknown repo returns
  guidance instead of guessing.

### 7.4 Patch-level edits

Whole-file writes are expensive and risky on large files.

- New `patch` action: `path`, `find`, `replace`, optional `count`.
- Fail to the model when the match is missing or ambiguous; fall back to
  `write` only when asked.
- Bound the replacement size with the existing edit budget.
- Acceptance: a unique match applies; an ambiguous match is refused; a missing
  match returns a message the model can correct.

### 7.5 Budgets

Steps are bounded; time, tokens, and cost are not.

- Flags and repo fields for wall-clock minutes, total bytes read/written, and
  an optional token estimate.
- On exhaustion: stop before commit, leave the branch and edits, print
  `--resume`.
- Acceptance: a tiny budget stops with a clear message, no commit, and a
  working `--resume`.

### 7.6 Stale lock recovery

A crashed build leaves a lock file that needs manual removal.

- Store PID and start time in the lock.
- Reclaim automatically when the PID is gone or the lock is older than six
  hours; `stead build --status` prints the holder; `--force-unlock` overrides.
- Acceptance: a dead-PID lock is reclaimed; a live PID still blocks; status
  names the holder.

### 7.7 Post-merge hygiene — `--cleanup`

- After a successful merge, delete the local build branch only when
  `--cleanup` is passed. Leave the remote branch to the operator's GitHub
  settings.
- Acceptance: local branch removed only on request; remote untouched.

### 7.8 One autonomy ladder, with a `spec` rung

- Add `spec` between observe and build: the agent writes specs, decisions, and
  plans as a docs PR; it does not write code.
- Expose `observe / spec / build / deliver` as one per-repo ladder, with
  `shadow / draft-pr / pr / merge` as the compatibility mapping.
- Acceptance: a `spec`-reach repo opens a docs-only PR; a build on it is
  refused; the existing reach values still work.

### 7.9 Opt-in shared repo context (`.stead/`)

- Commit a curated public context: repo description, autonomy defaults, specs,
  decisions, glossary, roadmap, compacted history.
- Allowlist only. Private notes, inbox, drafts, and secrets never publish.
- `stead context publish --dry-run` lists exactly what would be committed.
- Acceptance: a clone can rebuild the index from `.stead/` with no server; a
  private document is never included; the dry run matches the commit.

### 7.10 Context retrieval and the global index

- `stead context search`, `timeline`, and `bundle --budget N` over SQLite FTS5.
- A server index across opted-in repos, derived and rebuildable.
- Bundles cite source paths and commits; the budget is enforced by Stead.
- The agent receives mandatory, relevant, and excluded sets; mandatory overflow
  fails instead of truncating.
- Every retrieval is logged per run; a golden-task recall check guards against
  bundles that miss the decision that mattered.
- Acceptance: a query returns matches from two repos; a bundle stays under
  budget and resolves every item to a commit; private items never appear in a
  public bundle; deleting the global index and rebuilding loses nothing.

## 8. Principles

- Start simple. Fix real failures, not imagined ones.
- Incremental risk: shadow, then an explicit remote command, never a skip of
  the ceiling.
- Specific, shared, and scrutinized. Those are the factory tests.
- A person stays in the loop before anything consequential.
- Plain files. The model can be swapped. The notes stay here.
