# Stead — design record

A local, model-agnostic version of Notion's *A New Shape for Work*: a **context
system** (one shared place where humans and agents read and write knowledge)
plus **factories** (shared, scrutinized workflows).

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
| Factory | `factories/<name>/`: definition, versioned prompts, evals, run logs |
| Task queue | `context/tasks/` with `status: to-do\|doing\|done\|blocked` |
| Prompt versions | `factories/<name>/prompts/` plus the `prompt_versions` table |
| Evals | `factories/<name>/evals/`. `stead eval run` checks files. `stead eval judge` records a pass or fail. Promote refuses without a pass for that version |
| Scheduled triggers | Any scheduler calling `python -m stead`. No timer is built in |
| Event-driven triggers | `inbox/` capture, `stead inbox import`, and `POST /hook` when a webhook token is set. The hook only writes inbox. It does not run a factory |
| Governance / audit | git history, run logs, shadow assembly |
| Sync external context | `stead sync github` via `gh`. Read-only. Offline re-index with `--offline` |
| Who writes | `context/actors/` files. A shared server also has sign-ins. Attribution, not a permission system |
| Execution | Stdlib CLI. Any agent can drive it. Optional `--generate` rents a model |

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

Three factories assemble a prompt and stop. `--generate` may draft
`output.md`. Assembly does not post, push, or merge.

- `weekly-contribution-digest` — PRs, reviews, claimed issues, CI. Never posts.
- `weekly-project-status` — one project's tasks, documents, and meetings.
- `feature-builder` — planning-first, always. `method` selects tooling only:
  `spec-kit` (default, optional `specify` CLI) or `builtin` markdown.

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
that version.

---

## 4. Autonomy ladder

A repo may sit on any rung. The install default cannot be merge.

1. **Shadow.** Plan and proposed diff only. No remote writes.
2. **Draft PR.** `stead factory publish` opens a draft. A person reviews and
   merges.
3. **Pull request.** The same command opens a normal pull request. A person
   still merges, unless the repo file says merge.
4. **Trusted.** `stead factory merge` only when the repo file says
   `reach: merge`, the checks are green, and GitHub accepts the merge. Never
   the install default. Never a red check. Never a bypass of branch protection.

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
5. **GitHub.** Sync and digest are read-only. Publish and merge are explicit
   commands with a ceiling. Neither runs from assembly. Neither pushes the
   default branch.
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
  does not run a factory. A scheduler is still whatever calls the CLI.

Decided against:

- Per-object permissions. If you can write the file, you can write the object.
  Repository or host access is the permission.
- A password on this computer. Loopback has no login. Sign-in is only for the
  shared server.
- Auto-merge. `stead factory merge` stays an explicit command. A factory run
  does not call it.

The container package is public. `docker pull ghcr.io/theshinysylveon/stead:latest`
does not need a token.

## 7. Principles

- Start simple. Fix real failures, not imagined ones.
- Incremental risk: shadow, then an explicit remote command, never a skip of
  the ceiling.
- Specific, shared, and scrutinized. Those are the factory tests.
- A person stays in the loop before anything consequential.
- Plain files. The model can be swapped. The notes stay here.
