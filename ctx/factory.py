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


def assemble(root: Path, factory: str, project_ref: str, mode: str = "shadow") -> dict:
    """Build the context bundle + assembled prompt for one project. Returns run info."""
    db.require_db(root)
    found = objects.find(root, "project", project_ref)
    if found is None:
        raise SystemExit(f"project not found: {project_ref!r} (see context/projects/)")
    proj_path, proj_meta, proj_body = found
    project_id = proj_meta["id"]

    fdir = root / "factories" / factory
    if not (fdir / "FACTORY.md").exists():
        raise SystemExit(f"unknown factory: {factory!r} (no factories/{factory}/FACTORY.md)")

    conn = db.connect(root)
    try:
        row = conn.execute(
            "SELECT version, path FROM prompt_versions "
            "WHERE factory = ? AND status = 'production'", (factory,)
        ).fetchone()
        if row is None:
            raise SystemExit(f"no production prompt for factory {factory!r}; "
                             "use `ctx prompt promote` first")
        version = row["version"]
        prompt_text = (root / row["path"]).read_text(encoding="utf-8")

        tasks = objects.linked(root, "task", project_id)
        docs = objects.linked(root, "document", project_id)
        meetings = objects.linked(root, "meeting", project_id)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        run_dir = fdir / "runs" / f"{stamp}-{proj_path.stem}"
        suffix = 2
        while run_dir.exists():
            run_dir = fdir / "runs" / f"{stamp}-{proj_path.stem}-{suffix}"
            suffix += 1
        run_dir.mkdir(parents=True)

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
