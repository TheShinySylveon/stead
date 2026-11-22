# Trust, isolation, and what leaves the machine

Stead can write code and, when a repo says `reach: merge`, merge it. This page
states what is trusted, what is not, and which control stops which failure. It
is deliberately narrower than "safe": a local tool that runs a model is not a
sandbox, and this page says where the sandbox ends.

## The model is not trusted

Everything the model produces is treated as untrusted input:

- It answers with JSON actions. It cannot choose a shell command.
- It may only write inside the repo's `code_path`. `..`, absolute paths, and
  `.git` are refused.
- It must plan before it writes.
- Its writes to tests, CI config, and paths the repo marks protected are
  refused (see below). Files that look like secrets (`.env`, `*.pem`, `*.key`,
  `id_rsa`, `credentials.json`) are hidden from the tree, search, and read, and
  cannot be written or deleted.
- Merge is a separate command that re-reads the pull request from GitHub. A
  model cannot ask `stead build` to merge past the repo ceiling.

## Who makes a spec buildable

A synced issue cannot become a build target by itself. `stead build` requires
all of these:

- the contribution is `kind: issue` and `role: author`;
- its body has a description and a `## Acceptance criteria` checklist;
- it carries the `feature-spec` tag;
- its repo has `code_path` and a ceiling above `shadow`.

`sync github` fills the GitHub-derived fields. The tag, the `author` role, and
the criteria are a human edit. For a public repo, that is the real control
against prompt injection through an issue body: a person decides the text is a
spec before any model reads it as one.

## Checks run untrusted code

The repo's `checks:` command is chosen by the repo owner, not the model. But
the command usually runs code the model just wrote, so treat a check run as
code execution with the permissions of your user account.

| Control | Default | What it stops |
|---|---|---|
| Scrubbed environment | On | Checks cannot read `STEAD_MODEL_API_KEY`, `GH_TOKEN`, cloud keys, or the deployment token from the environment. Only `PATH`, home, temp, locale, Windows system variables, and `checks_env:` are passed. |
| Container isolation | Opt-in: `checks_isolation: docker` + `checks_image` | Checks get no network, dropped capabilities, a PID limit, and a memory/CPU cap. The checkout is mounted at `/src` so the checks can read and write it. |
| Wall-clock budget | 30 minutes per build | A repair loop cannot run forever. `--max-minutes` changes it; watched builds use `build_minutes`. |
| Step and edit caps | 30 steps, 1 MB written | A model cannot loop or dump unbounded output. |
| Stop file | `.stead-stop` | A build and a watched run stop between steps. `stead factory stop` creates it. |

The container is not available for every repo (it needs Docker and an image
with the toolchain). The honest statement is: **without
`checks_isolation: docker`, checks run on your host with a scrubbed
environment, not in a sandbox.**

## Protected paths

A model that can edit its own gate can pass it. By default these are refused:

- `.github/**`, `.gitlab-ci.yml`, `.circleci/**`, `azure-pipelines.yml`,
  `.buildkite/**`, `Jenkinsfile`
- `tests/**`, `test/**`, `spec/**`, `**/conftest.py`, `**/test_*.py`,
  `**/*_test.py`, and the common JS/TS test file names

A repo can opt in with `allow_test_edits: true`, `allow_ci_edits: true`, or
`allow_protected: true`, and can add its own paths with `protected_paths:`.
When tests are allowed, the build records `tests_touched` in its run log.

The checks command itself lives in the repo's frontmatter, outside the
checkout, so the model cannot rewrite it. If `checks:` calls a file the model
can edit (`make test`, `npm test`), add that file to `protected_paths:`.

## Merge gates

`stead factory merge` merges only when all of these hold:

1. The repo file says `reach: merge`. Merge is never inherited from the install
   default.
2. The build runs from a non-default branch, and the pull request's head is
   that branch, based on the default branch.
3. Every reported check is green.
4. The checks run is trusted: `checks_isolation: docker`, or the repo
   explicitly sets `trust_checks: host`.
5. The default branch has required status checks. Otherwise "branch protection
   is not bypassed" would protect nothing. A repo can acknowledge that with
   `merge_without_required_checks: true`.

The command never passes `--admin`, never pushes the default branch, and never
merges a draft. It does not add an independent reviewer pass; that is a known
gap, not a claim.

## Shared server: every account is an admin

`stead ui --deploy` and the Docker image serve several people. Accounts are
names with scrypt password hashes and a session cookie. There are no
per-object permissions, no roles, and no approval queue for context edits.

- Any signed-in person can edit any context object.
- Factory runs from the cockpit are shadow-only and never push.
- **The cockpit refuses to start a build on a shared server.** A build runs
  model-written code on the host. `STEAD_ALLOW_SERVER_BUILD=1` overrides this
  for a server you fully trust; do not set it for a team you do not control.
- Put the server behind a reverse proxy that terminates TLS and does SSO if
  you expose it. The built-in server speaks HTTP, has no login rate limit, and
  is not hardened for the public internet.

## What leaves the machine

Nothing is sent to the Stead authors. There is no telemetry. The only
outbound calls are the ones a command makes:

| Command | What is sent | Where |
|---|---|---|
| `stead sync github` | Read-only `gh` queries for your PRs, reviews, and issues | GitHub, through `gh` |
| `stead factory run --generate` | The assembled prompt: digest = cached public contributions; project status = one project's tasks, documents, meetings; feature-builder = spec, criteria, repo notes, related documents | Your configured model endpoint |
| `stead build` | The system prompt, repo tree, spec, and every file the model reads, plus check output | Your configured model endpoint |
| `stead eval judge` | The draft and its pass criteria | Your configured model endpoint |
| `stead ui` | Nothing. The page has no external assets. | Loopback, or your own container |

`stead model set --provider ollama` keeps every prompt on the machine. The
feature-builder bundle can contain private documents on purpose: they are what
makes the build good. The bundle is local, and it is sent only when you run a
model step. The pull request body Stead opens is fixed text and the public
spec title; it never includes private notes.

## How the public/private split is enforced

- `context/contributions/` and `context/repos/` are the public layer.
- `context/documents/`, `context/meetings/`, `context/tasks/`, and project
  bodies are private.
- The digest assembler reads only contributions and repo metadata, so private
  notes cannot enter it. A test covers this.
- The feature-builder bundle deliberately includes related private documents so
  the build has context. It is marked as possibly private and is not published.
- The wiki is a projection over the same files. It has no separate store, and
  its change requests are ordinary private documents.

## Known gaps

- No independent reviewer pass before merge.
- No per-object permissions or roles on the shared server.
- No login rate limiting, TLS, or CSRF token beyond the custom `X-Ctx-Token`
  header and `SameSite=Lax` session cookie. Use a proxy.
- Container isolation is per repo and opt-in, not enforced globally.
- A model can still write a test-shaped file outside the protected globs if the
  repo's layout is unusual. Add it to `protected_paths:`.
