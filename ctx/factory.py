"""Deterministic factory runner — NO LLM call, ever.

Assembles a project's markdown + linked tasks/documents/meetings into a
context bundle, emits the assembled prompt (production prompt + bundle), and
records a run row. Generation is pluggable: any agent or human reads
prompt.md and supplies the output via `ctx run log`.
"""

from __future__ import annotations

import json
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
                         "use `ctx prompt promote` first")
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
            "note": "Deterministic assembly; no LLM call. Supply output via `ctx run log`.",
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
            parts.append("_No contributions cached. Run `ctx sync github` "
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
                    "Supply output via `ctx run log`. Never auto-post to GitHub.",
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
