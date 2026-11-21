# Spec Kit workflow — Spec-Driven Development inside the cockpit

`feature-builder` is SPEC-DRIVEN and PLANNING-FIRST in every run: no
implementation code is written before the specification, the technical plan and
the dependency-ordered tasks are produced and reviewed. GitHub Spec Kit
(github/spec-kit, MIT) is the tool that formalizes this when present; without
it, the same phases are hand-rolled as plain markdown. Either way the discipline
is identical — `method` selects only the tooling.

## The flow (every feature)

0. **Gate check** — a flagged spec (missing acceptance criteria / vague / large)
   is decomposed, not built.
1. **Constitution** (once per repo) — code-quality / testing / maintainability /
   dependency principles, grounded in the repo's conventions.
2. **Read + sweep + premise** — issue + all comments, duplicate/overlap sweep,
   validate the premise against current code.
3. **Specify** — the feature specification, seeded from OUR spec + acceptance
   criteria; every criterion appears; ambiguities clarified, never guessed.
4. **Plan** — technical plan (approach, data model, contracts, test strategy,
   risks) + a constitution check. No code yet.
5. **Tasks** — dependency-ordered breakdown, each criterion covered.
6. **Implement** — TDD red-green on an isolated branch (never the default).
7. **Sabotage + quality gates** — revert-and-confirm regression tests, run the
   repo's full gates.
8. **Converge** — re-assess against the spec; repeat implement->converge until
   `Converged`.
9. **Map artifacts** — tasks -> `context/tasks/`, plan + spec ->
   `context/documents/`, constitution -> repo notes; `ctx init`. One context.
10. **Deliver** — SHADOW (artifacts + proposed diff, zero remote writes) or
    DRAFT-PR (draft PR, human merges).

## Tooling (`method` on the spec)

- `spec-kit` (DEFAULT) — use the `specify` CLI to scaffold `.specify/` and run
  the phases as agent skills: `/speckit-constitution`, `/speckit-specify`,
  `/speckit-plan`, `/speckit-tasks`, `/speckit-implement`, `/speckit-converge`.
- `builtin` — the same phases, hand-rolled as `constitution.md` / `spec.md` /
  `plan.md` / `tasks.md` markdown in the target repo (no CLI).

## Install (external, optional)

```
uv tool install specify-cli      # pinned stable release; needs Python 3.11+ and uv
specify init . --integration claude --non-interactive   # or --integration copilot
```

`specify` is an external tool like `gh`: `ctx` never imports or invokes it, and
the whole system works without it (use `builtin`). `specify init` scaffolds from
bundled assets, so it needs no network.

## Own projects vs OSS repos

- **Own repo:** `specify init` directly in the repo; `.specify/` committed if
  you want the SDD trail visible.
- **OSS repo:** work in a LOCAL clone; `.specify/` stays local; contribute the
  code as a DRAFT PR to upstream under the human gate. Never impose `.specify/`
  on an upstream repo uninvited.

## Safety (unchanged)

SHADOW (default) = zero remote writes; DRAFT-PR = draft PR, human merges; never
push to the default branch; never auto-merge. Spec Kit's own bug-fix and
idea-assessment extensions are optional and not part of the default flow.
