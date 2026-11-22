# Dogfooding Stead on Stead

The most persuasive number is a real one. This page is the procedure for running
Stead's own factory against the Stead codebase and publishing what happened. It
deliberately contains **no invented metrics** — the tables are filled by a real
run, then committed.

> Prerequisite: a model endpoint. `stead build` rents a model; assembly alone
> calls nothing. For local-first dogfooding, Ollama keeps every prompt on the
> machine:
>
> ```bash
> python -m stead model set --provider ollama --name llama3.2
> ```
>
> Any OpenAI-compatible endpoint works. The key lives in gitignored
> `stead.json` or `STEAD_MODEL_API_KEY`, never in context.

## Why a separate checkout

`stead build` refuses a `code_path` equal to the context root, so the store and
the code being edited must be different directories. Use a worktree of the Stead
repo as the code, and a small store as the context:

```bash
# 1. A code checkout separate from this context repo.
git worktree add ../stead-dogfood-code main

# 2. A context store for the dogfood run.
mkdir ../stead-dogfood
python -m stead --root ../stead-dogfood init
python -m stead --root ../stead-dogfood repo add --title "Stead (dogfood)" \
    --url https://github.com/TheShinySylveon/stead --kind own
python -m stead --root ../stead-dogfood repo set repo-theshinysylveon-stead \
    --path ../stead-dogfood-code --reach draft-pr \
    --set checks="python -m unittest discover -s tests"
```

`repo set` prints a warning if the check runner's config is unprotected. The
Stead suite is run by `python -m unittest`, so there is no Makefile/package.json
to protect; the tests themselves are protected paths by default. A feature that
needs a new test sets `allow_test_edits: true` on the repo, and the build records
which tests it touched.

## The loop

For each candidate spec below:

```bash
# Author the spec as a contribution (kind issue, role author, feature-spec tag,
# a description + ## Acceptance criteria). Then approve the exact body:
python -m stead --root ../stead-dogfood spec approve --contribution CONTRIBUTION_ID

# Build at draft-pr. A human reviews and merges; Stead does not auto-merge here.
python -m stead --root ../stead-dogfood build --contribution CONTRIBUTION_ID --publish

# Read the numbers. Each successful build wrote a build-record document.
python -m stead --root ../stead-dogfood metrics
```

On merge, Stead marks the contribution merged, closes linked tasks, and the next
bundle reads the prior record. Interpretive notes the model proposes land in
`inbox/` for triage.

## Candidate specs

Small, real, testable improvements to Stead. Each is a build target once
authored and approved.

### 1. `stead context search`

Full-text search over the context objects from the CLI.

```
## Acceptance criteria
- [ ] `stead context search QUERY` lists matching objects with path and a snippet
- [ ] `--repo REPO` limits results to one repo's objects
- [ ] `--json` emits a machine-readable list
- [ ] search is read-only and calls no model and no network
- [ ] a test covers a match, a miss, and the repo filter
```

### 2. `stead metrics --since`

Time-window the dogfood numbers.

```
## Acceptance criteria
- [ ] `stead metrics --since YYYY-MM-DD` counts only records created on/after the date
- [ ] an invalid date is a clear error, not a crash
- [ ] a test covers the filter and the empty window
```

### 3. `doctor` flags an unapproved feature spec

Make the approval gate visible to a hand editor.

```
## Acceptance criteria
- [ ] `stead doctor` warns on a contribution tagged feature-spec with no spec_sha
- [ ] it warns when spec_sha is present but the body changed
- [ ] approved specs produce no warning
- [ ] a test covers all three cases
```

## Results (fill from a real run)

| Spec | Outcome | Repair rounds | Checks mode | Build time | Tests touched | Human edits before merge |
|---|---|---|---|---|---|---|
| _pending a model run_ | | | | | | |

Aggregate, from `stead metrics --json`:

- specs built: _pending_
- share merged without human edits: _pending_
- repair rounds used: _pending_
- cost and time per build: _pending_

Publish these here and link them from the README once they exist. Until then the
honest claim is the pipeline and the gates, not a success rate.
