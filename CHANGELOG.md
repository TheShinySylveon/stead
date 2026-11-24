# Changelog

## Unreleased

- **Address PR review comments.** New `stead address --contribution ID` (and an
  **Address review** button on a published PR) fetches the PR's review comments
  and runs the model in a focused loop to fix each one, committing on the PR
  branch and pushing so the reviewer re-runs. `--no-push` commits locally only.
- **A published PR no longer shows twice in the pipeline.** A Stead PR that
  collapses onto its spec (via the build record's `pr_url`) is now hidden from
  the Repos pipeline, so it appears once on the source issue/spec card instead
  of also as a separate "PR open" card.
- **Comment on issue no longer asks for the PR URL.** Both the cockpit and the
  CLI (`stead factory comment`) now resolve the pull request URL from the build
  record when it isn't given, so the comment action posts the link directly
  instead of requiring a URL to paste. (`--pr-url` remains an override.)
- **Per-repo auto-publish, and the cockpit says so.** A repo can set
  `auto_publish: true` to have a successful build open a pull request
  automatically (when its reach is `draft-pr`/`pr`/`merge`); default off. The
  Repos settings gain an **Auto-publish PR** toggle, and the Build confirmation
  and result now state plainly that Build commits to a branch and only
  auto-publish (or the Publish step) opens a PR.
- **`spec draft` now writes narrow, verifiable specs.** The drafting prompt
  pushes for ONE concrete change (picking the smallest slice of a broad issue
  rather than scoping the whole ambition), aims for 1-3 acceptance criteria
  that each name a test or a before/after behavior, forbids vague criteria
  like "improve correctness" or "score Set B", and refuses to plan training or
  research tasks or edits to protected paths (CI config, existing tests, the
  checks definition) — which a build refuses anyway. A broad spec is what let
  the build agent loop; a narrow one gives it an unambiguous finish line.
- **The build loop pushes back on models that loop.** A model that plans but
  never edits now gets escalating reminders at steps 5, 15, and 30 (not one
  ignored nudge); re-reading or re-searching the same target 3+ times, or
  re-editing the same file 5+ times, gets a pointed "stop and act, or finish"
  reminder. This breaks the read-only and doc-thrash loops a weak model falls
  into on a broad spec.
- **The prompt cap now fits a 250k-token model.** `MAX_PROMPT_CHARS` is raised
  from 120k to 1M chars (~250k tokens at 4 chars/token), so a build can send
  the model its full context window instead of truncating the transcript at a
  fraction of it.
- **Long builds stream to the end instead of giving up.** The cockpit no
  longer stops polling a build after ~48 minutes with "Build is taking too
  long" — a build now runs up to its 4-hour budget with the log streaming the
  whole way. Streaming also no longer stalls after 200 progress lines: the task
  now reports a monotonic line total so the card can keep appending new lines
  even as the server trims its buffer.
- **Cockpit review fixes.** A build started from the opened spec logs there as well as on the card; `*emphasis*` and `_emphasis_` no longer change code spans or link addresses; the skip link moves focus without replacing the view's address.
- **Cockpit polish from an Impeccable critique (desktop).**
  - **Lifecycle track:** each pipeline card shows Draft · Approve · Build · Publish with the current step and the repo's limit, and replaces the amber stage chip.
  - **Review before approve:** a drafted spec offers Review spec; Approve appears only inside the opened spec. Build options wait for approval and default to the repo's limit.
  - **Fix:** a successful build no longer erases its own log. Lines are kept per contribution and restored after the redraw, with a result note.
  - **Safety copy:** the sidebar no longer says nothing writes to GitHub (Publish, Comment and Merge do, each behind a confirmation); the Factories and Settings lines are scoped the same way.
  - **Colour roles:** amber marks the step that needs you; ci pass is green and ci pending neutral; links are blue; Sync GitHub and "Use a shared server" are quiet buttons.
  - **Home:** runs awaiting a verdict join Needs you (the Home badge counts them), and the four count tiles are gone.
  - **One field for filter and search:** typing in the header field filters the view; Enter searches all context, with results under the header on any view; Escape clears.
  - **Settings:** every field has a visible label that stays once it is filled (placeholders are now examples); People sits in a panel, and its actor selects say so when there are no actors yet.
  - **Accessibility:** fields and buttons have 3:1 borders and a readable placeholder; a skip link; the view title is the page's h1, updates `document.title`, and takes focus on navigation; expanding a spec sets `aria-expanded`; Escape no longer fires twice.
  - **Craft:** no one-sided list trail, no glow on the mark, a tint instead of a side bar for the current nav item, sans headings inside notes and specs, `*emphasis*` rendered, and targeted reduced-motion rules instead of a global kill.
- **The default wall-clock budget is now 4 hours (was 30 minutes).** A weak
  local model can take far longer than 30 minutes to work through a build, so
  `--max-minutes` and `build_minutes` default to 240 (4 hours), and the ceiling
  is raised from 8 hours to 24 hours for builds that need even longer.
- **The default token budget is now 10M (was 2M).** A local model has no
  per-token cost, so a generous cumulative budget is safe and lets a 300-step
  build run to completion instead of aborting. `stead factory defaults` (and
  the `--max-tokens` / cockpit Tokens field) now default to 10M tokens per
  build.
- **The build step cap is now 300 (was 30).** `stead build` defaults to 300
  model steps, and the CLI's `--steps N` no longer clamps to 60. The cockpit's
  Build options gain a **Steps** field so GUI builds can set their own cap, and
  a build that leaves it blank uses the 300 default.
- **A stale build lock is now resolvable from the cockpit.** When a build fails
  with "another build holds the lock", or a lock is left behind after a crash,
  the contribution reader's Build options show the lock (pid, host, age, and
  whether it looks live) with a **Remove lock** button. Removing a live-looking
  lock asks for a stronger confirmation, and a failed Build offers to clear the
  lock inline. Removing the lock also reclaims the killed build's leftover
  started marker and worktree (so the branch is not stuck even when the OS
  reused the pid), and a removal that actually fails is reported as a failure
  rather than a silent success. The CLI-equivalent recovery no longer requires
  hunting for the lock file under the temp directory.
- **Cockpit UI/UX overhaul (ui-ux-pro-max design system).** The whole build
  flow now lives on one pane: each build target on the Repos tab expands inline
  to show its spec, stage, and the next action (Draft → Approve → Build →
  Publish), plus build options, a "Preview bundle" button, and an editable spec —
  no separate overlay or tab hops. Builds, drafts, and reviews stream their
  progress into an inline log, so a run never looks stalled. Controls are
  streamlined: the spec editor and build options collapse behind small toggles,
  and "Review" only appears once a branch exists. The pipeline is now the
  headline: cards are grouped by stage (Ready to build → Ready to publish → PR
  opened → Needs approval → Ready to draft), each showing its stage chip, CI and
  review status, age, and the next-action button directly on the card — no need
  to expand to act. In-progress runs stream their latest line onto the card, and
  the manual add/repo forms collapse behind a single "Manage repos" toggle at
  the bottom instead of taking the top of the screen. The graphite/amber dark
  theme and monospace display headings are kept (system fonts — still offline).
  Views are deep-linkable via `#hash` routes. The same "everyday first, manual
  entry collapsed" rule now applies across the whole cockpit: Tasks, Projects,
  Library, and Factories put their content (board, grid, lists, panels) first and
  tuck "add"/"onboard"/"watch" forms behind a toggle, Inbox keeps a compact
  capture and hides file import, and Home gains a one-line quick capture with the
  "Needs you" items called out by type instead of a raw id.
- **Dropdown selectors are restyled and de-cluttered.** Native `<select>` controls
  now use a custom chevron, dark-theme surface, and hover/focus states instead of
  the OS default. Repo cards no longer show four always-on dropdowns: they show
  their current `kind` / `status` / `reach` as read-only chips, with the editable
  fields behind a per-card "Settings" toggle. GitHub-synced contribution fields
  (`state`, `ci`, `review`) remain read-only chips, never dropdowns.
- **The contribution list is a pipeline, not a CRUD grid.** Each build target is
  one card with a stage (`ready to draft → drafted → approved → built → PR
  opened → merged/closed`) and a single "next step" button, so you only see the
  action that matters now. The source issue and its drafted spec collapse into
  one card, the GitHub-synced dropdowns are gone (CI/review stay as read-only
  chips), and the reader shows only the next step instead of every action at
  once.
- **The whole build lifecycle lives on one tab.** Draft → Approve → Build →
  Publish run from the Repos tab's pipeline cards and the contribution reader,
  which now also carries the build options (minutes / tokens / USD / reach), an
  "Assemble shadow" preview, "Review", and a plain-language hint for each stage.
  The Factories tab's `feature-builder` panel no longer duplicates the build — it
  points to the Repos pipeline — so there is one place to take an issue to a PR.
- **Sync drops closed issues that were never started.** A cached issue GitHub
  closed is removed from the local cache when it has no draft, approval, or build
  record; a started one is marked closed so it stays visible and can be deleted
  deliberately. `stead delete contribution ID` (and the cockpit Delete button)
  now removes a contribution — and its drafted spec — instead of refusing.
- **Factories are self-evident, guided, and deletable.** The Factories tab opens
  with a plain-language explanation and each panel says what it does and what it
  reads. New factory is a guided form (name + what it drafts) with a visible result
  and next step; a custom factory reads a project. `stead factory delete --name NAME
  [--force]` (and a cockpit Delete button) removes a factory; it refuses the four
  shipped factories and any run logs (the audit trail) unless `--force`. Creating or
  deleting a factory updates only that factory's index rows — it never rebuilds the
  database, so the runs ledger and other factories' production prompts are preserved.
  CLI↔GUI parity verified: every CLI command has a cockpit control.
- **`sync github` reconciles merged PRs, and the cockpit splits open from done.**
  Cached open PR contributions now get their live state checked during sync, so
  a merged or closed PR stops showing as open (before, sync only fetched open
  PRs, so a merge left the cached copy stuck at "open"). The Repos view groups
  open items at the top, separated from merged/closed ones.
- **Free review tooling.** CI adds a `ruff` lint job (`ruff.toml`, starting
  with syntax errors and undefined names) and a CodeQL workflow (security and
  quality queries, weekly and on PRs). Dependabot keeps the GitHub Actions
  current. `.coderabbit.yaml` and `.gemini/` hold review rules for the free
  CodeRabbit and Gemini Code Assist apps; none of these are required checks.
- **The monitor cadence defaults to watch, and `inbox list` reads any encoding.**
  `schedule show/install --interval` now implies `--watch` (the monitor cadence
  is sync + watch by definition), matching its help text instead of producing a
  sync-only command. `inbox list` no longer crashes on a note that is not UTF-8;
  undecodable bytes are replaced. `docs/trust.md` records that the local cockpit
  reaches publish/merge/comment behind a confirmation.
- **The cockpit reaches CLI parity; remote writes are confirmation-gated.**
  `spec draft` (issue → spec), the independent `review`, the build ledger with
  `metrics mark`, `doctor`, and the build kill switch (`factory stop`/`start`)
  are all reachable from the browser. Builds run in the background with live
  progress and optional max-minutes/tokens/cost instead of blocking the request.
  Publish, merge, and issue comments are reachable behind an explicit
  confirmation, and are refused on a shared server. Schedule exposes the
  hourly/daily monitor cadence, model settings expose `call_timeout`, factory
  defaults expose `build_minutes`, sync is scoped by repo, and a context search
  box finds any object.
- **`spec draft --all` drafts every open `stead-build` issue with no draft
  yet.** The monitor cadence runs it automatically after `sync github`, so a
  person only approves. It never approves: each draft is still gated by
  `spec approve`. An issue with an existing draft, a closed issue, or a draft
  that fails (e.g. no fetched body) is skipped, not fatal.
- **`schedule show` / `install` work for a store that is not the code folder.**
  The generated command changed into the store (`cd /d "<store>"`) and assumed
  the Stead code lived there, so a dogfood store (`--root C:\dev\stead-dogfood`)
  failed with `No module named stead`. The command now changes into the Stead
  code folder and passes `--root "<store>"` to every `stead` call, in both the
  Windows (`cd /d`) and POSIX (`cd`) forms. A store that is the code folder
  still works (a redundant `--root` is harmless).
- **The tamper check ignores a person's harmless git config changes.** It
  compared `.git/config` byte for byte, so a `git push -u`, a new tracking
  branch, or setting an identity in the same repo while a build ran its checks
  failed the build as tampering and reverted the change. Config is now compared
  by its parsed settings (`git config --no-includes --list`); `branch.*` and
  `user.*` changes are ignored and kept. Any other setting, an unparseable
  config, or any hook change still fails the build and is restored.
- **`spec approve` refuses a spec the build would refuse.** More than 8
  acceptance criteria, or a description under 25 or over 400 words, now fails
  approval with what to fix, and `spec draft` tells the model the limit and
  warns about a draft that breaks it. The first #27 draft had 10 criteria; it
  was drafted and approved, then refused by the build as `large-spec`.
- **`context search --repo` counts only relations.** The `repo` field and
  `repo:` tags put an object in a repo; a body line reading `repo: X` no
  longer does (the deviation recorded when #30 was hand-checked).
- **`stead inbox list` — read-only listing of what is waiting in the inbox
  (#27).** Lists each inbox note with its file name, kind, and title;
  `--kind decision|glossary|note` limits the output to one kind. A missing or
  empty inbox prints a clear message. Nothing is moved, edited, or deleted.
  The third Set A dogfood spec: built by Stead and merged as #34.
- **A merged spec closes the issue it was drafted from.** On an own repo the PR
  says `Closes #N`, so GitHub closes the issue, but `sync github` fetches open
  issues only and never saw it. Recording the merge now marks the source issue
  `closed` and closes tasks linked to it as well as to the draft. On other
  repos the PR only tracks the issue, so it stays open.
- **`stead context search` — read-only search over the context store (#25).**
  `stead context search QUERY` lists matching objects with their path and a
  one-line snippet centered on the match. `--repo ID` limits the scan to one
  repo's objects (the repo file plus anything that references it through a
  `repo:` field or `repo:` tag), and `--json` emits a machine-readable list of
  `{id, type, path, snippet}`. The scan is case-insensitive, calls no model,
  touches no network, and writes nothing — it does not even create `state.db`.
  The first Set A dogfood spec: built by Stead and merged as #30.
- **`spec draft`, `factory run --generate`, and `eval judge` use the model's
  `call_timeout`.** They had a fixed 120 s limit, so a 27B model drafting with
  the repo tree in the prompt timed out with a raw traceback. A timeout now
  stops with a clean message naming the limit and `--call-timeout`.
- **`spec draft` sees the repository tree and checks the plan's paths.** The
  drafting prompt now carries the repo's depth-2 tree (the same one the builder
  sees) and tells the model to name real files or new files in real folders.
  After drafting, a plan path whose folder doesn't exist, or a new file that
  shadows an existing one of the same name, prints a warning to fix before
  approval. The first real draft (issue #25) planned `stead/context/search.py`
  and `stead/cli.py`; the code lives in `ctx/`.
- **Builds report progress while they run (#19).** `stead build` prints one
  line per model step to stderr (step, action and path, prompt size, call
  time) plus phase changes (worktree, base suite, fail-before gate, checks,
  commit, outcome), and appends the same lines to
  `factories/feature-builder/runs/<stamp>-build-<slug>.progress.log` as they
  happen. When the build ends the log moves into its run folder as
  `progress.log`. Lines never hold file contents or model replies.
- **`stead metrics` lists same-day records newest first**, ordering by the
  stamp in the record's file name, and `--since` reuses one date parser.
- **`sync github --repo OWNER/NAME` scopes the sync.** Each `gh search` gets
  `--repo`, out-of-scope results are dropped, and label intake skips owned
  repos outside the scope. `--remember` saves the scope in `stead.json` for
  plain and scheduled runs; `--all-repos` overrides it for one run or, with
  `--remember`, clears it. Without it, a dogfood store's first sync pulled in
  every open PR the user had, across unrelated and work repos.
- **Updating a Stead PR from main no longer counts as a human edit.** The
  merged head is compared with the build commit by content: commits on the
  branch line must all be clean merges of the base (same patch id before and
  after). A direct commit, a change slipped into the update merge, or a head
  the checkout can't see still counts as an edit. Under a strict up-to-date
  rule nearly every PR is updated before merge, so the old SHA check flagged
  almost all of them. `stead factory publish` run on its own now saves the
  PR url on the build record (outcome `published`), so `sync github` can
  reconcile its merge, and `factory merge` updates the newest record of the
  day rather than an arbitrary same-day one.
- **Builds can change long files.** A read longer than the read limit now
  says where it was cut and how to read on, `read` takes a `start`/`end` line
  range, and a new `edit` action replaces one exact snippet (it must match one
  place; a miss or an ambiguous match is fed back, not fatal). Edits pass the
  same protected-path gates as `write`. Before this, a read silently stopped
  at 40,000 characters, so a model could not see or safely rewrite
  `ctx/cli.py` (73,000) and the issue #1 dogfood build looped on reads.
- **The MVP loop, end to end (M0–M7).** An issue carrying the `stead-build`
  label syncs read-only, `stead spec draft` turns it into an approvable spec in
  one model call, `stead spec approve` binds approval to the body hash, and
  `stead build` implements it in its own `git worktree` — the user's checkout
  is never touched and Stead never runs `git clean`. `build --publish` opens the
  PR, and `factory comment` links it on the issue (gated: `allow_comment`,
  `kind: own`). A human reviews and merges; `sync github` reconciles the outcome.
- **Build correctness harness (M1).** The builder asks for structured JSON
  output (`json_schema` `response_format`, with a fallback on a 400), logs
  characters/latency, and enforces the three-run fail-before/pass-after gate:
  the base suite must pass, a new test must fail against the base without the
  code change, and the branch must pass.
- **One automatic attempt per approved hash (M0.6).** A build-class failure
  blocks a re-run until re-approval or `--retry`; infrastructure failures don't
  consume the attempt. A killed build's started marker is reclaimed as an
  infrastructure failure record.
- **Metrics split build-class from infrastructure failures**, and the failure
  rate is build-class only.
- **Monitor cadence.** `schedule show/install --interval hourly|daily` runs a
  read-only sync + `factory watch --build --publish` on its own task, separate
  from the weekly digest job.
- The sign-off runbook (rubric, frozen issue sets A/B/C + hold-out, baseline
  procedure, and the `pr`-ceiling procedure) is in `docs/dogfood.md`.

- **`ghost` reach — a new lowest rung below shadow.** First option in every
  ceiling dropdown (cockpit and CLI). Ghost is purely spec, docs, and a code
  plan for human approval: the build plans first and may write or delete
  markdown spec/doc files only (code snippets inside the plan are fine).
  Zero code is applied to the checkout, no checks run, and publish/merge
  refuse a ghost repo. A human approves before any code is written.
- **Spec approval is bound to the body.** `stead spec approve` (and a cockpit
  button) stores a SHA-256 of the spec body. A build refuses an unapproved spec
  or one whose body changed since approval. The `author` role and `feature-spec`
  tag are labels, not permissions. Non-spec bundle text is marked untrusted.
- **Write-back closes the loop.** A successful build writes a versioned
  `build-record` document, marks the contribution merged and closes linked
  tasks on merge, and prior records feed the next feature-builder bundle.
  Decisions and glossary terms are only *proposed* to the inbox for triage.
  The wiki History page lists the durable records.
- **Shared-server indirect path closed.** On a shared server the cockpit makes
  `checks:`, `protected_paths:`, reach, trigger, `code_path`, the author role,
  spec authoring, and spec approval read-only, so an account cannot reach a
  shell through a later scheduled build.
- **Runner-config warning.** `repo set` warns when `checks:` names a runner
  whose config (Makefile, package.json, conftest.py, pyproject.toml, …) is
  present but unprotected. PR bodies now separate tests touched from tests
  deleted.
- **Containment for the build agent.** Tests and CI config are protected paths
  by default (`allow_test_edits`, `allow_ci_edits`, or `protected_paths:` to
  opt in). Checks run with a scrubbed environment, or in a networkless
  container with `checks_isolation: docker` + `checks_image`. Merge requires
  the container (or an explicit `trust_checks: host`), and refuses a default
  branch with no required status checks unless the repo acknowledges it.
- **Bounds and a kill switch.** `stead build --max-minutes`, a stop file
  (`stead factory stop` / `start`), a daily watched-build budget, and stale-lock
  recovery when the owning process is gone. `stead factory defaults` sets the
  budget and per-build minutes.
- **The cockpit no longer writes remotely.** Build with model and Watch and
  build commit locally only; publish and merge are CLI commands. Both refuse to
  run a build on a shared server, where every account is an admin.
- **`stead doctor`** lints frontmatter, required fields, duplicate ids, dates,
  and relation targets. `repo set --set KEY=VALUE` edits any repo field.
- **`docs/trust.md`**: the threat model, merge gates, protected paths, the
  shared-server warning, and a table of what is sent to a model provider.
- README opens with the user, the problem, one store / two readers / one dial,
  and write-back. Notion moves to an inspiration line. Limits now state the
  checks risk, merge gap, and that every shared-server account is an admin.
- A repo **Wiki** space: home page, page tree, child pages for specs,
  decisions, glossary, and tasks, labels, metadata, and an on-page table of
  contents. Entries are real pages, not side panels.
- Wiki **Arrange** reorders the tree and pins pages to Start here. **Request a
  change** files a request document; generated pages are never edited inline.
- `docs/vision.md` records the long-range design: an autonomy slider with a
  `spec` rung, opt-in `.stead/` repo context, and two readers over one store —
  a person browses freely, an agent gets a scoped bundle with provenance,
  budget, and a logged retrieval trail.
- `PLAN.md` §7.8–7.10 carries the near-term slice.
- `PLAN.md` now carries the autonomy roadmap: PR feedback repair, queue and
  workers, check detection, patch edits, budgets, stale-lock recovery, and
  post-merge cleanup.
- `stead build` gains an autonomous repair loop: `check` returns test output,
  failed checks are fed back, and `--repair-rounds` bounds the attempts.
  The agent can also `search` and `delete`. A per-checkout lock prevents
  concurrent builds, `--resume` continues a failed branch, `--wait` polls PR
  checks before merge, and every build records a plan and summary under
  `factories/feature-builder/runs/`.
- README, concepts, PLAN, and factories state the Notion lineage and the
  deliberate twist: factories execute, and reach is per repo.
- `stead build --contribution ID` has the configured model plan, edit the
  repo checkout, run the repo's `checks:`, and commit on an isolated branch.
  `--publish` opens the pull request; `--merge` merges when the repo says
  `reach: merge`. `factory watch --build --publish [--merge]` does the same
  for every watched spec, and `schedule --watch [--merge]` runs it weekly.
  The model cannot choose shell commands and cannot leave the checkout.

## 0.1.0 — 2026-11-21

The cockpit catches up with the CLI, a shared server has per-person sign-in,
and the planned factory set is complete.

- Delete for projects, tasks, documents, meetings, repos, and actors, in the
  CLI and the reader. A linked project or repo is refused without force.
- A project's reader shows task counts, linked notes, and recent runs.
- Eval results are per case, so a failed promote shows which cases lack a pass.
  Judge asks the configured model about the newest draft for that factory.
- Run history shows beyond the newest six; the run viewer keeps the draft.
- The page shows its version, keeps scroll and focus, confirms before closing
  unsaved edits, traps focus in the reader, warns errors longer, and reflows at
  phone width.
- The Windows weekly task registers a short launcher in `private/`, so a deep
  checkout path no longer hits the 261-character limit.
- A review note no longer replaces the draft. It is stored as `note`, and the
  run viewer shows the draft, prompt, and bundle.
- "Needs you" lists one row per object with every reason.
- The cockpit shows the port it serves, signs out on a shared server, and
  edits a repo's `code_path` and `default_branch`.
- The cockpit covers the local commands: factory scaffold, watch, eval check,
  prompt promote, file an approved run, inbox file import, account reset,
  webhook token, index rebuild, and the weekly job. Publish and merge stay
  CLI-only, with the commands shown on the contribution.
- `stead run file --run ID` files an approved digest or status into
  `context/documents/`. It never posts, pushes, or merges.
- `stead schedule show` / `install` wire the weekly read-only sync, the
  changed-cache digest, and the maintenance draft. `--project P` also drafts a
  project status. A project id is checked before it goes into the command.
- `stead sync github --digest` assembles only after the cache changes.
- `context-maintenance` also sweeps duplicate titles.
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
