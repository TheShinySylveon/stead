# Factories

A factory is a repeatable pipeline: plan, build, verify, and deliver. That is
the deliberate divergence from Notion's advisory model: the factory executes,
and the per-repo reach decides how far. Each one lives in `factories/<name>/`:

- `FACTORY.md` — what it is, what it may do, and what it must not do.
- `prompts/vN.md` — versioned instructions. The highest version is production
  after `stead init`. Switch with `stead prompt promote`.
- `evals/*.json` — cases and pass criteria. `stead eval run` checks that the
  files are well-formed. `stead eval judge` asks the configured model about
  one draft and records a pass or fail. `stead prompt promote` refuses until
  every case has a recorded pass for that version.
- `runs/` — one directory per assembly. Gitignored. Safe to delete.

The eval gate is a guardrail, not a proof. `eval judge` is a single-run pass/fail
from the configured model, which is noisy; a pinned separate judge, repeated
runs, and comparison against the previous prompt version are planned.
`feature-builder` does not yet have code-pipeline evals (replay past specs,
score on checks passed, diff size, human acceptance). See
[Vision](vision.md#open-items-from-review).

## What a run actually does

`python -m stead factory run` reads local files and writes three things:

- `bundle.md` — the context the workflow is allowed to see.
- `prompt.md` — the production prompt plus that bundle.
- `run.json` — counts, mode, and flags.

That step calls no model and uses no network. Add `--generate` and Stead
sends `prompt.md` to the model you configured, then writes `output.md`.
The draft is not executed, posted, or pushed. See [Models](models.md).

You, or any agent, can still read `prompt.md` and record a verdict:

```bash
python -m stead run log --factory F --task REF --prompt-version vN \
    --output "what happened" --verdict approved
```

The cockpit can assemble the same shadow run and approve or reject it.

## The four factories

### weekly-contribution-digest

A weekly picture of pull requests in flight, reviews waiting on you, claimed
issues, and CI, across the repos in the local cache.

```bash
python -m stead sync github --limit 30
python -m stead digest
```

It drafts. It never posts to GitHub.

### weekly-project-status

A status draft for one of your projects, from its tasks, documents, and
meetings.

```bash
python -m stead factory run --factory weekly-project-status \
    --project project-id --shadow
```

### feature-builder

Turns an enabled feature spec into a build bundle. The spec is a
contribution with `kind: issue`, tagged `feature-spec` (or `stead-build`, the
synced GitHub label), and a `## Acceptance criteria` checklist. A person must
also approve the body with `stead spec approve`; the approval is a hash, so any
edit needs re-approval. The bundle marks everything that is not the approved
spec as untrusted, and includes prior `build-record` documents for the repo.

```bash
python -m stead factory run --factory feature-builder \
    --contribution contribution-id --shadow
```

Every run is planning-first. A thin, vague, or oversized spec is flagged for
decomposition instead of being built. `method` on the spec is `spec-kit` or
`builtin`. Both plan before code. Only the tooling changes. See
[Spec Kit](spec-kit-workflow.md).

**Build with model** (or `stead build --contribution ID`) goes one step
further. With a model configured it asks for a plan first, lets the model
list, read, search, edit, write, and delete files inside the repo's `code_path`
(a long file is read in line ranges and changed by exact replacement),
runs the repo's `checks:` command, feeds failures back for repair, commits on
an isolated branch, and stops. `--publish` opens the pull request; `--wait`
waits for its checks and `--merge` merges under `reach: merge`. `--resume`
continues a failed build. The model never chooses a shell command, cannot
touch `.git`, cannot leave the checkout, and cannot write protected test or CI
paths unless the repo opts in. It may `propose` a decision or glossary term to
the inbox. Each build records its plan and summary under
`factories/feature-builder/runs/`, and writes a versioned `build-record`
document under `context/documents/`. On merge it marks the contribution merged
and closes linked tasks; the next bundle reads the prior records.

### context-maintenance

A triage note for one checkout: inbox notes waiting, relations that point at a
missing object, objects unchanged for over 30 days, and titles that appear
twice. The draft recommends; it never edits, merges, or deletes.

```bash
python -m stead factory run --factory context-maintenance --shadow
```

## Shadow and the ceiling

Shadow is the only mode the cockpit offers, and the default on the CLI.
Output stays on disk. Draft with model writes `output.md` in that same
directory. It does not change the mode.

feature-builder has two knobs, set per repo. The install default cannot be
merge.

| Knob | Values | Default |
|---|---|---|
| trigger | `on-demand`, `watch` | on-demand |
| reach | `ghost`, `shadow`, `draft-pr`, `pr`, `merge` | shadow |

A run may ask for less than the repo ceiling. It may not ask for more.
`ghost` is the lowest rung: purely spec, docs, and a code plan for human
approval. The build plans first and may write or delete markdown spec/doc
files only; code snippets inside the plan are fine. Zero code is applied
to the checkout, no checks run, and publish refuses a ghost repo.
`context-maintenance` drafts a triage note from the inbox, broken relations,
objects older than 30 days, and titles that appear twice. Assembly does not
edit those files.

```bash
python -m stead factory run --factory context-maintenance --shadow
python -m stead factory new --name NAME --title "What it drafts"
```

`stead factory watch` assembles open enabled `feature-spec`/`stead-build` issues
on repos set to watch, and skips flagged specs. With `--build` it also runs the
model build on each one; `--publish` opens the pull request and `--merge` merges
when the repo says `reach: merge` and the checks are green. A spec whose branch
already exists is skipped.

`stead factory publish` pushes an isolated branch and opens a pull request
when the ceiling is `draft-pr`, `pr`, or `merge`. The branch must not be the
default. Set the repo `code_path` first. Publish does not merge.

`stead factory merge` is a separate command. The repo file must say
`reach: merge`. The checks must be green. It does not bypass branch
protection, and it does not push the default branch. A factory run does not
call it. See
[feature-builder/FACTORY.md](../factories/feature-builder/FACTORY.md).

## Scheduling

`stead schedule` wires the weekly local jobs. It is still just the CLI, so any
scheduler can run it.

```bash
python -m stead schedule show                 # print the command
python -m stead schedule show --project P     # add a status draft
python -m stead schedule install              # Windows, current user
```

The job runs a read-only GitHub sync, the digest only if the cache changed, the
maintenance draft, and the status of `--project` when you pass one. With
`--watch` it also builds and publishes watched specs; add `--merge` to merge
those a repo allows. Nothing is posted, pushed, or merged outside that reach.

For any other scheduler, use the same shape:

```bash
python -m stead sync github --limit 30 --digest
python -m stead factory run --factory context-maintenance --shadow
```
