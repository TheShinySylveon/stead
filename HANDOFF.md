# Handoff — Shared Context (local, model-agnostic context system + factories)

**Guiding principle: "Rent the intelligence. Own the context."**
Local-first, sustainable: Markdown + YAML frontmatter is the source of truth;
SQLite `state.db` is a rebuildable index; `git` + `AGENTS.md` hold the workflow;
the `ctx` core is **Python stdlib only, zero pip dependencies**. External open
tools (`git`, `gh`, `uv`, `specify`) are used as *tools*, never library deps, and
the system never hardwires an LLM provider — prompts are handed to any pluggable
coding agent.

Repo root: `C:\Users\tylra\OneDrive\Documents\Projects\Shared Context` (Windows,
Python 3.14.9). Branch `main`.

---

## Current state

- **HEAD:** `b81cb0f` — working tree clean.
- **Tests:** `python3 -m unittest discover -s tests` → **67 OK**.
- **Three factories** (shared, scrutinized AI workflows):
  - `weekly-contribution-digest`, `weekly-project-status`, `feature-builder`.
- **Phase 3** (`feature-builder`: issue → PR in shadow/draft-PR mode) is complete
  and committed (`d07ea3c`); `AGENTS.md` documents all three factories (`e7db350`).

## Just completed (commit `b81cb0f`) — Spec Kit as the always-on flow

`feature-builder` is now **spec-driven and planning-first in every run** — SDD is
the *natural/default* flow, not an opt-in. The `method` field selects only the
*TOOLING*, never whether planning happens:

- **`method: spec-kit` (DEFAULT)** — Spec-Driven Development via GitHub Spec Kit
  (`specify` CLI → `.specify/`). Phases: `constitution → specify → plan → tasks →
  implement (TDD) → converge`, each reviewed before the next.
- **`method: builtin`** — the *same* SDD + planning-first phases, hand-rolled as
  markdown (`constitution.md`/`spec.md`/`plan.md`/`tasks.md`), no `specify` CLI.
- **`prompts/v2.md` is production by default** — `db.py` now seeds the *highest*
  version as production on `ctx init` (v1 is retired). Roll back/switch via
  `ctx prompt promote`.

Verified end-to-end: a spec with no `method` field resolves to `spec-kit` + `v2`,
and the bundle/prompt carry `## Method\nspec-kit` + the SDD phases.

---

## What remains (next steps)

1. **Documentation parity (not yet done):** `CONVENTIONS.md`, `README.md`, and
   `AGENTS.md` do NOT yet mention the `method` field, the always-SDD flow, or
   `docs/spec-kit-workflow.md` (which exists). Add:
   - `method` field semantics + default `spec-kit`.
   - pointer to `docs/spec-kit-workflow.md`.
   - a note that SDD/planning-before-code is unconditional.
   (Parent owns `AGENTS.md`; patch targeted, don't full-rewrite.)
2. **Cosmetic:** commit `b81cb0f`'s message has two dropped phrases
   (`ctx init`, `ctx prompt promote`) — the backticks in the `git commit -m "..."`
   string were bash command-substituted. Optional `git commit --amend`. No code impact.
3. **Optional verify:** actually run `specify init . --integration claude
   --non-interactive` in a scratch repo to confirm offline scaffolding end-to-end
   (only `specify --version` 1.4.3 and `specify init --help` verified so far).
   `uv 0.13.9` and `specify-cli 1.4.3` are installed.
4. **Optional eval evidence:** the 6 eval JSONs under
   `factories/feature-builder/evals/` are validated structurally by tests; there
   is no automated LLM-judgment runner. To gather promote-style evidence, run a
   real coding agent against each eval's `input` and check `pass_criteria`.
   (v2 is already production, so this is evidence, not a gate.)

## Constraints & rules (non-negotiable)

- `ctx` core stays stdlib-only. `uv`/`specify`/`gh` are external tools only.
- No hardwired LLM provider/API. Prompt assembly is deterministic, local, no network.
- Safety: never push to the default branch; never auto-merge; human review gate;
  SHADOW = zero remote writes; DRAFT-PR = draft PR, human merges. Private strategy
  never goes into public artifacts. `gh` sync is read-only.
- Subagents (`delegate_task`) must NOT edit `AGENTS.md` or `PLAN.md` (parent-owned).
- Keep each factory's prompt versions (vN.md) + evals; promote via `ctx prompt promote`.

## How to verify

```bash
cd "/c/Users/tylra/OneDrive/Documents/Projects/Shared Context"
python3 -m ctx init            # rebuilds state.db; v2 -> production, v1 retired
python3 -m unittest discover -s tests      # expect 67 OK
python3 -m ctx factory run --factory feature-builder \
    --contribution contribution-example-org-example-repo-issue-202 --shadow
# -> run.json: method=spec-kit, prompt_version=v2
```

## Key files

- `AGENTS.md` — entry doc: one-cockpit, repos/contributions, factories, autonomy ladder.
- `PLAN.md` — original 13-pillar plan (sustainability decisions).
- `CONVENTIONS.md` / `README.md` — conventions + usage (need the spec-kit update, step 1).
- `ctx/` — `cli.py`, `factory.py`, `db.py`, `frontmatter.py`, `sync.py`, `schema.sql`, `objects.py`.
- `factories/feature-builder/` — `FACTORY.md`, `prompts/{v1,v2}.md`, `evals/*.json` (6).
- `docs/spec-kit-workflow.md` — the SDD flow + tooling + install.
- `context/` — `repos/`, `contributions/`, `tasks/`, `documents/`, `meetings/`, `projects/` (markdown source of truth).
- `tests/` — `test_ctx.py`, `test_contributions.py`, `test_feature_builder.py`, `test_spec_kit.py`.

## Gotchas

- Windows git-bash: `LF will be replaced by CRLF` warnings are noise; harmless.
- Never put backticks inside a double-quoted `git commit -m "..."` — bash
  command-substitutes them and mangles the message (use single quotes or a message file).
- `state.db` and `factories/*/runs/` are gitignored (rebuildable).
- `security.protected_instruction_files: false` is already set in Hermes config
  (avoids per-write consent prompts on instruction files).
- Subagents can hit `HTTP 402 "included Hermes usage for today is used up"`
  (daily cap; resets ~Nov 22 6:39 AM UTC). Prefer finishing small work directly,
  or schedule delegation around the reset.
