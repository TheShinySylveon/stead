"""Factory runner.

Assembly is deterministic and does not call a model. `write_output` stores a
draft that `stead factory run --generate` got from the configured endpoint.
That draft is a file. Nothing here posts, pushes, or merges.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from ctx import db, objects


def _section(title: str, items: list[tuple[Path, dict, str]], root: Path) -> str:
    parts = [f"## {title} ({len(items)})\n"]
    if not items:
        parts.append("_None linked._\n")
    for path, meta, body in items:
        rel = path.relative_to(root).as_posix()
        status = f" — status: {meta['status']}" if meta.get("status") else ""
        parts.append(f"### {meta.get('title', path.stem)}{status}\n"
                     f"<!-- source: {rel} | id: {meta.get('id')} -->\n\n"
                     f"{body.strip()}\n")
    return "\n".join(parts)


def _production_prompt(conn, root: Path, factory: str) -> tuple[str, str]:
    """Return (version, prompt_text) for a factory's production prompt."""
    row = conn.execute(
        "SELECT version, path FROM prompt_versions "
        "WHERE factory = ? AND status = 'production'", (factory,)
    ).fetchone()
    if row is None:
        raise SystemExit(f"no production prompt for factory {factory!r}; "
                         "use `stead prompt promote` first")
    return row["version"], (root / row["path"]).read_text(encoding="utf-8")


def _check_factory_dir(root: Path, factory: str) -> Path:
    fdir = root / "factories" / factory
    if not (fdir / "FACTORY.md").exists():
        raise SystemExit(f"unknown factory: {factory!r} (no factories/{factory}/FACTORY.md)")
    return fdir


def _run_dir(fdir: Path, stamp: str, label: str) -> Path:
    run_dir = fdir / "runs" / f"{stamp}-{label}"
    suffix = 2
    while run_dir.exists():
        run_dir = fdir / "runs" / f"{stamp}-{label}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True)
    return run_dir


def write_output(root: Path, info: dict, output: str, *, source: str) -> dict:
    """Store a draft next to the bundle. Does not execute it or send it anywhere."""
    text = output if output.endswith("\n") else output + "\n"
    run_dir = root / info["run_dir"]
    (run_dir / "output.md").write_text(text, encoding="utf-8")
    raw_path = run_dir / "run.json"
    stored = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.is_file() else {}
    stored["output_path"] = f"{info['run_dir']}/output.md"
    stored["generated"] = source
    stored["note"] = "Draft only. Nothing was posted, pushed, or merged."
    raw_path.write_text(json.dumps(stored, indent=2) + "\n", encoding="utf-8")
    updated = dict(info)
    updated["output"] = text
    updated["output_path"] = stored["output_path"]
    updated["generated"] = source
    updated["note"] = stored["note"]
    if updated.get("run_id"):
        conn = db.connect(root)
        try:
            conn.execute("UPDATE runs SET output = ? WHERE id = ?", (text, updated["run_id"]))
            conn.commit()
        finally:
            conn.close()
    return updated


def assemble(root: Path, factory: str, project_ref: str, mode: str = "shadow") -> dict:
    """Build the context bundle + assembled prompt for one project. Returns run info."""
    db.require_db(root)
    found = objects.find(root, "project", project_ref)
    if found is None:
        raise SystemExit(f"project not found: {project_ref!r} (see context/projects/)")
    proj_path, proj_meta, proj_body = found
    project_id = proj_meta["id"]

    fdir = _check_factory_dir(root, factory)

    conn = db.connect(root)
    try:
        version, prompt_text = _production_prompt(conn, root, factory)

        tasks = objects.linked(root, "task", project_id)
        docs = objects.linked(root, "document", project_id)
        meetings = objects.linked(root, "meeting", project_id)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = _run_dir(fdir, stamp, proj_path.stem)

        created = db.utcnow()
        bundle = "\n".join([
            f"# Context bundle — {proj_meta.get('title', project_id)}",
            f"<!-- factory: {factory} | prompt: {version} | mode: {mode} | created: {created} -->",
            "",
            _section("Project", [(proj_path, proj_meta, proj_body)], root),
            _section("Tasks", tasks, root),
            _section("Documents", docs, root),
            _section("Meetings", meetings, root),
        ])
        assembled_prompt = (prompt_text.rstrip() + "\n\n---\n\n" + bundle)

        (run_dir / "bundle.md").write_text(bundle, encoding="utf-8")
        (run_dir / "prompt.md").write_text(assembled_prompt, encoding="utf-8")
        info = {
            "factory": factory,
            "project": project_id,
            "prompt_version": version,
            "mode": mode,
            "created": created,
            "counts": {"tasks": len(tasks), "documents": len(docs), "meetings": len(meetings)},
            "verdict": "pending",
            "note": "Deterministic assembly; no LLM call. Supply output via `stead run log`.",
        }
        (run_dir / "run.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

        cur = conn.execute(
            "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, bundle_path, verdict, created) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (factory, project_id, project_id, version, mode,
             run_dir.relative_to(root).as_posix(), created),
        )
        conn.commit()
        info["run_id"] = cur.lastrowid
        info["run_dir"] = run_dir.relative_to(root).as_posix()
        info["assembled_prompt"] = assembled_prompt
        return info
    finally:
        conn.close()


DIGEST_FACTORY = "weekly-contribution-digest"


def _contribution_entry(path: Path, meta: dict, body: str, root: Path) -> str:
    rel = path.relative_to(root).as_posix()
    kind = meta.get("kind", "?")
    number = meta.get("number", "?")
    facts = " | ".join(f"{k}: {meta.get(k, '?')}"
                       for k in ("role", "state", "ci", "review", "updated"))
    return (f"### [{kind} #{number}] {meta.get('title', path.stem)}\n"
            f"{facts}\n"
            f"url: {meta.get('url', '(none)')}\n"
            f"<!-- source: {rel} | id: {meta.get('id')} -->\n\n"
            f"{body.strip()}\n")


def assemble_digest(root: Path, factory: str = DIGEST_FACTORY,
                    mode: str = "shadow") -> dict:
    """Deterministically assemble the weekly contribution digest bundle from
    the cached contribution files (no LLM, no network). Groups by repo."""
    db.require_db(root)
    fdir = _check_factory_dir(root, factory)

    contribs = list(objects.iter_objects(root, "contribution"))
    repos = {meta["id"]: (path, meta, body)
             for path, meta, body in objects.iter_objects(root, "repo")}

    # Deterministic grouping: repo id, then kind, then number.
    by_repo: dict[str, list] = {}
    for path, meta, body in contribs:
        by_repo.setdefault(meta.get("repo", "(unlinked)"), []).append((path, meta, body))
    for items in by_repo.values():
        items.sort(key=lambda t: (t[1].get("kind", ""), int(t[1].get("number", 0) or 0)))

    def _count(pred) -> int:
        return sum(1 for _p, m, _b in contribs if pred(m))

    counts = {
        "contributions": len(contribs),
        "repos": len(by_repo),
        "prs_in_flight": _count(lambda m: m.get("kind") == "pr"
                                and m.get("role") == "author" and m.get("state") == "open"),
        "reviews_awaiting": _count(lambda m: m.get("kind") == "pr"
                                   and m.get("role") == "reviewer" and m.get("state") == "open"),
        "claimed_issues": _count(lambda m: m.get("kind") == "issue"
                                 and m.get("role") == "assignee" and m.get("state") == "open"),
        "ci_flags": _count(lambda m: m.get("state") == "open"
                           and m.get("ci") in ("fail", "pending")),
    }

    conn = db.connect(root)
    try:
        version, prompt_text = _production_prompt(conn, root, factory)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = _run_dir(fdir, stamp, "digest")
        created = db.utcnow()

        parts = [
            "# Contribution digest bundle — weekly",
            f"<!-- factory: {factory} | prompt: {version} | mode: {mode} | created: {created} -->",
            "",
            "## Summary",
            f"- repos with contributions: {counts['repos']}",
            f"- contributions cached: {counts['contributions']}",
            f"- PRs in flight (author, open): {counts['prs_in_flight']}",
            f"- reviews awaiting reply (reviewer, open): {counts['reviews_awaiting']}",
            f"- claimed issues (assignee, open): {counts['claimed_issues']}",
            f"- CI flags (open, ci fail/pending): {counts['ci_flags']}",
            "",
            "Data is a read-only local cache of public GitHub state "
            "(context/contributions/, visibility: public). No private notes are included.",
        ]
        for repo_id in sorted(by_repo):
            rmeta = repos.get(repo_id, (None, {}, ""))[1]
            header = f"## Repo: {rmeta.get('title', repo_id)} ({repo_id})"
            if rmeta.get("kind"):
                header += f" [kind: {rmeta['kind']}]"
            parts.append(header)
            if rmeta.get("url"):
                parts.append(f"url: {rmeta['url']}")
            parts.append("")
            for path, meta, body in by_repo[repo_id]:
                parts.append(_contribution_entry(path, meta, body, root))
        if not contribs:
            parts.append("_No contributions cached. Run `stead sync github` "
                         "(or `--offline` after adding files) to populate._")
        bundle = "\n".join(parts)
        assembled_prompt = prompt_text.rstrip() + "\n\n---\n\n" + bundle

        (run_dir / "bundle.md").write_text(bundle, encoding="utf-8")
        (run_dir / "prompt.md").write_text(assembled_prompt, encoding="utf-8")
        info = {
            "factory": factory,
            "project": None,
            "prompt_version": version,
            "mode": mode,
            "created": created,
            "counts": counts,
            "verdict": "pending",
            "note": "Deterministic assembly; no LLM call, no network. "
                    "Supply output via `stead run log`. Never auto-post to GitHub.",
        }
        (run_dir / "run.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

        cur = conn.execute(
            "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, bundle_path, verdict, created) "
            "VALUES (?, 'contributions', NULL, ?, ?, ?, 'pending', ?)",
            (factory, version, mode, run_dir.relative_to(root).as_posix(), created),
        )
        conn.commit()
        info["run_id"] = cur.lastrowid
        info["run_dir"] = run_dir.relative_to(root).as_posix()
        info["assembled_prompt"] = assembled_prompt
        return info
    finally:
        conn.close()


FEATURE_BUILDER_FACTORY = "feature-builder"

# feature-builder is ALWAYS spec-driven and planning-first: no implementation
# code is written before the specification, plan and tasks are produced and
# reviewed. `method` selects only the TOOLING, never whether planning happens:
#   spec-kit  (DEFAULT) = Spec-Driven Development via GitHub Spec Kit (an
#     EXTERNAL, OPTIONAL tool, like gh): the coding agent runs the SDD phases
#     in the target repo (constitution->specify->plan->tasks->implement->converge).
#   builtin = the SAME SDD + planning-first phases, hand-rolled as markdown
#     (no specify CLI) when it isn't installed or wanted.
# ctx itself never imports or invokes specify/uv; assembly is deterministic,
# local-only and identical for both tooling choices.
CONTRIB_METHODS = ("builtin", "spec-kit")
DEFAULT_METHOD = "spec-kit"

# Deterministic spec-quality heuristics (no LLM): a buildable spec needs a
# substantive description and an `## Acceptance criteria` checklist.
_AC_HEADER = re.compile(r"^##\s+acceptance\s+criteria\s*$", re.IGNORECASE | re.MULTILINE)
_CHECKLIST_ITEM = re.compile(r"^\s*[-*]\s+\[([ xX])\]\s+(.+?)\s*$", re.MULTILINE)
_NEXT_H2 = re.compile(r"^##\s+", re.MULTILINE)
_HEADING_LINE = re.compile(r"^#+\s.*$", re.MULTILINE)
_MIN_DESCRIPTION_WORDS = 25
_MAX_DESCRIPTION_WORDS = 400
_MAX_CRITERIA = 8


def split_spec(body: str) -> tuple[str, list[tuple[bool, str]]]:
    """Split a feature-spec body into (description, acceptance-criteria checklist).

    The checklist is the `## Acceptance criteria` section's `- [ ]` / `- [x]`
    items, as (done, text) pairs. Returns an empty list when the section is absent.
    """
    match = _AC_HEADER.search(body)
    if match is None:
        return body.strip(), []
    description = body[:match.start()].strip()
    section = body[match.end():]
    nxt = _NEXT_H2.search(section)
    if nxt:
        section = section[:nxt.start()]
    criteria = [(m.group(1).lower() == "x", m.group(2))
                for m in _CHECKLIST_ITEM.finditer(section)]
    return description, criteria


def spec_flags(description: str, criteria: list[tuple[bool, str]]) -> list[str]:
    """Deterministic quality flags; any flag means the spec needs decomposition
    or clarification BEFORE an agent is allowed to build it."""
    flags: list[str] = []
    if not criteria:
        flags.append("missing-acceptance-criteria")
    words = len(_HEADING_LINE.sub("", description).split())
    if words < _MIN_DESCRIPTION_WORDS:
        flags.append("vague-spec")
    if len(criteria) > _MAX_CRITERIA or words > _MAX_DESCRIPTION_WORDS:
        flags.append("large-spec")
    return flags


_REACH_SAFETY = {
    "shadow": (
        "Mode: **SHADOW** (default). Propose a plan and a proposed diff ONLY.\n"
        "NO remote writes of any kind: no push, no branch creation on the remote,\n"
        "no PR/issue/comment/label creation. All output stays local for human review."
    ),
    "draft-pr": (
        "Mode: **DRAFT-PR**. You may push an isolated feature branch and open\n"
        "a DRAFT PR via `gh pr create --draft` with passing tests. A HUMAN reviews\n"
        "and merges. NEVER push to the default branch, NEVER merge, NEVER mark the\n"
        "PR ready-for-review without explicit human approval."
    ),
    "pr": (
        "Mode: **PULL REQUEST**. You may push an isolated feature branch and open\n"
        "a pull request that is not a draft. A HUMAN reviews and merges.\n"
        "NEVER push to the default branch. NEVER merge."
    ),
    "merge": (
        "Mode: **MERGE**. This repo explicitly allows a merge. Never the default.\n"
        "You may push an isolated feature branch and merge only after the checks\n"
        "are actually green and branch protection allows it. NEVER push to the\n"
        "default branch. NEVER merge a red or pending check."
    ),
}


_MODE_SAFETY = {
    "shadow": (
        "Mode: **SHADOW** (default). Propose a plan and a proposed diff ONLY.\n"
        "NO remote writes of any kind: no push, no branch creation on the remote,\n"
        "no PR/issue/comment/label creation. All output stays local for human review."
    ),
    "live": (
        "Mode: **DRAFT-PR** (live). You may push an isolated feature branch and open\n"
        "a DRAFT PR via `gh pr create --draft` with passing tests. A HUMAN reviews\n"
        "and merges. NEVER push to the default branch, NEVER merge, NEVER mark the\n"
        "PR ready-for-review without explicit human approval."
    ),
}


def assemble_feature_build(root: Path, contribution_ref: str,
                           mode: str = "shadow", reach: str | None = None) -> dict:
    """Deterministically assemble the feature-builder bundle for one spec.

    Inputs (all local files, no network, no LLM): the spec contribution
    (kind: issue, role: author) with its body + acceptance criteria, its repo's
    conventions, `related:` documents, and the other cached contributions in
    the same repo (input for the duplicate/overlap sweep). Emits bundle.md,
    prompt.md, run.json and records a runs row. The factory itself NEVER writes
    code and NEVER touches the network or any remote — in any mode.
    """
    db.require_db(root)
    fdir = _check_factory_dir(root, FEATURE_BUILDER_FACTORY)
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise SystemExit(f"contribution not found: {contribution_ref!r} "
                         "(see context/contributions/)")
    spec_path, spec_meta, spec_body = found
    if spec_meta.get("kind") != "issue":
        raise SystemExit("feature-builder builds from a spec contribution with "
                         f"kind: issue (got {spec_meta.get('kind')!r})")
    if spec_meta.get("role") != "author":
        raise SystemExit("feature-builder builds specs you authored: role: author "
                         f"required (got {spec_meta.get('role')!r})")
    repo_ref = spec_meta.get("repo")
    repo_found = objects.find(root, "repo", repo_ref) if repo_ref else None
    if repo_found is None:
        raise SystemExit(f"repo not found: {repo_ref!r} — add it with `stead repo add` first")
    repo_path, repo_meta, repo_body = repo_found
    repo_id = repo_meta["id"]
    from ctx.autonomy import AutonomyError, effective, permit
    policy = effective(root, repo_meta)
    try:
        requested = permit(policy, reach)
    except AutonomyError as exc:
        raise SystemExit(str(exc)) from exc

    method = spec_meta.get("method", DEFAULT_METHOD)
    if method not in CONTRIB_METHODS:
        raise SystemExit(f"invalid method {method!r} on {spec_meta.get('id')}; "
                         f"choose from {CONTRIB_METHODS}")

    description, criteria = split_spec(spec_body)
    flags = spec_flags(description, criteria)

    related_refs = spec_meta.get("related") or []
    if isinstance(related_refs, str):
        related_refs = [related_refs]
    docs: list = []
    missing_refs: list[str] = []
    for ref in related_refs:
        doc = objects.find(root, "document", ref)
        if doc is None:
            missing_refs.append(ref)
        else:
            docs.append(doc)

    # Duplicate/overlap sweep input: every OTHER cached contribution in the repo.
    siblings = [(p, m, b) for p, m, b in objects.iter_objects(root, "contribution")
                if m.get("repo") == repo_id and m.get("id") != spec_meta.get("id")]
    siblings.sort(key=lambda t: (t[1].get("kind", ""), int(t[1].get("number", 0) or 0)))

    conn = db.connect(root)
    try:
        version, prompt_text = _production_prompt(conn, root, FEATURE_BUILDER_FACTORY)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = _run_dir(fdir, stamp, spec_path.stem)
        created = db.utcnow()

        parts = [
            f"# Feature build bundle — {spec_meta.get('title', spec_path.stem)}",
            f"<!-- factory: {FEATURE_BUILDER_FACTORY} | prompt: {version} "
            f"| mode: {mode} | method: {method} | created: {created} -->",
            "",
            "## Method",
            method,
            "",
            "The production prompt branches on this value. This factory is ALWAYS "
            "spec-driven and planning-first; `method` selects only the tooling — "
            "spec-kit = Spec-Driven Development via the external, optional Spec Kit "
            "toolchain; builtin = the same SDD phases hand-rolled as markdown (no "
            "specify CLI). Assembly is deterministic and local-only for both.",
            "",
            "## Build target (feature spec)",
            _contribution_entry(spec_path, spec_meta, spec_body, root),
            "## Acceptance criteria",
        ]
        if criteria:
            parts.append("Map EACH criterion below to at least one test before writing code:")
            parts.extend(f"- [{'x' if done else ' '}] {text}" for done, text in criteria)
        else:
            parts.append("_No `## Acceptance criteria` checklist found in the spec body._")
        parts += ["", "## Spec quality flags"]
        if flags:
            parts.append("**NEEDS DECOMPOSITION — do not implement until resolved.** "
                         "Flagged by deterministic checks:")
            parts.extend(f"- {flag}" for flag in flags)
            parts.append("Stop and produce a decomposition/clarification plan instead of code.")
        else:
            parts.append("None — spec looks buildable (description + acceptance criteria present).")
        parts += [
            "",
            f"## Repo conventions — {repo_meta.get('title', repo_id)} ({repo_id})"
            + (f" [kind: {repo_meta['kind']}]" if repo_meta.get("kind") else ""),
        ]
        for key in ("url", "default_branch", "contributing", "notes", "status"):
            if repo_meta.get(key):
                parts.append(f"- {key}: {repo_meta[key]}")
        parts.append(f"<!-- source: {repo_path.relative_to(root).as_posix()} "
                     f"| id: {repo_id} -->")
        parts += ["", repo_body.strip(), ""]
        parts.append(_section("Related documents", docs, root))
        if missing_refs:
            parts.append("_Related refs not found: " + ", ".join(missing_refs) + "_\n")
        parts.append(f"## Related work in local cache ({len(siblings)})")
        parts.append("Duplicate/overlap sweep input: other cached contributions in this repo. "
                     "Check these (and live GitHub, read-only) for duplicate or overlapping "
                     "work BEFORE building; surface anything that overlaps.\n")
        if siblings:
            for path, meta, body in siblings:
                parts.append(_contribution_entry(path, meta, body, root))
        else:
            parts.append("_No other contributions cached for this repo._\n")
        parts += [
            "## Mode & safety (binding)",
            _REACH_SAFETY.get(requested, _REACH_SAFETY["shadow"]),
            f"Allowed reach this run: {requested}. Ceiling for {repo_id}: {policy['ceiling']}.",
            "Do not go past the ceiling. Merge is never inherited.",
            "Hard rules in every mode: never push to main/the default branch directly; "
            "never auto-merge by default; a human reviews before anything consequential; "
            "vague or large specs are flagged for decomposition, never guessed.",
            "Assembly did not push, open, or merge. Publish is a separate command.",
        ]
        bundle = "\n".join(parts)
        assembled_prompt = prompt_text.rstrip() + "\n\n---\n\n" + bundle

        (run_dir / "bundle.md").write_text(bundle, encoding="utf-8")
        (run_dir / "prompt.md").write_text(assembled_prompt, encoding="utf-8")
        info = {
            "factory": FEATURE_BUILDER_FACTORY,
            "contribution": spec_meta["id"],
            "repo": repo_id,
            "project": None,
            "prompt_version": version,
            "mode": mode,
            "method": method,
            "created": created,
            "counts": {
                "acceptance_criteria": len(criteria),
                "related_documents": len(docs),
                "related_contributions": len(siblings),
                "spec_flags": len(flags),
            },
            "flags": flags,
            "needs_decomposition": bool(flags),
            "verdict": "pending",
            "reach": requested,
            "ceiling": policy["ceiling"],
            "trigger": policy["trigger"],
            "remote": "none" if requested == "shadow" else "not-implemented",
            "note": "Local assembly only. Nothing was pushed, opened, or merged.",
        }
        (run_dir / "run.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")

        cur = conn.execute(
            "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, bundle_path, verdict, created) "
            "VALUES (?, ?, NULL, ?, ?, ?, 'pending', ?)",
            (FEATURE_BUILDER_FACTORY, spec_meta["id"], version, mode,
             run_dir.relative_to(root).as_posix(), created),
        )
        conn.commit()
        info["run_id"] = cur.lastrowid
        info["run_dir"] = run_dir.relative_to(root).as_posix()
        info["assembled_prompt"] = assembled_prompt
        return info
    finally:
        conn.close()


def _tags(meta: dict) -> list[str]:
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        return [tags]
    return [str(tag) for tag in tags]


def watch_specs(root: Path) -> dict:
    """Assemble every open authored feature spec whose repo trigger is watch.

    Flagged specs are skipped, not guessed. On-demand repos are skipped.
    Nothing is pushed. A reach above shadow is recorded and not performed.
    """
    from ctx.autonomy import effective
    ran: list[dict] = []
    skipped: list[dict] = []
    for _path, meta, body in objects.iter_objects(root, "contribution"):
        if meta.get("kind") != "issue" or meta.get("role") != "author":
            continue
        if meta.get("state") not in (None, "", "open"):
            continue
        if "feature-spec" not in _tags(meta):
            continue
        repo = objects.find(root, "repo", meta.get("repo") or "")
        if repo is None:
            skipped.append({"id": meta.get("id"), "reason": "repo missing"})
            continue
        policy = effective(root, repo[1])
        if policy["trigger"] != "watch":
            continue
        description, criteria = split_spec(body)
        flags = spec_flags(description, criteria)
        if flags:
            skipped.append({"id": meta.get("id"), "reason": ", ".join(flags)})
            continue
        try:
            info = assemble_feature_build(root, meta["id"], reach=policy["ceiling"])
        except SystemExit as exc:
            skipped.append({"id": meta.get("id"), "reason": str(exc)})
            continue
        ran.append({
            "id": meta.get("id"),
            "run_id": info.get("run_id"),
            "run_dir": info.get("run_dir"),
            "reach": info.get("reach"),
            "ceiling": info.get("ceiling"),
            "remote": info.get("remote"),
        })
    return {"ran": ran, "skipped": skipped}
