"""File one approved draft as a private document. Local only.

This is the last rung for the digest and status factories: a person approves a
run, then files its text into context/documents/. Nothing is posted to GitHub.
An unapproved run, a rejected run, or a draft with no text is refused.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from ctx import db, frontmatter, objects

FILING_FACTORIES = ("weekly-contribution-digest", "weekly-project-status")


class DeliveryError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def file_run(root: Path, run_id: object, title: str | None = None) -> dict:
    """Write an approved run to context/documents/. Raises DeliveryError."""
    db.require_db(root)
    try:
        rid = int(run_id)
    except (TypeError, ValueError) as exc:
        raise DeliveryError("run id must be a number") from exc
    conn = db.connect(root)
    try:
        run = conn.execute(
            "SELECT id, factory, task_ref, project, prompt_version, mode, output, verdict "
            "FROM runs WHERE id = ?", (rid,)).fetchone()
        production = conn.execute(
            "SELECT version FROM prompt_versions WHERE factory = ? AND status = 'production'",
            (run["factory"],) if run else ("",)).fetchone()
    finally:
        conn.close()
    if run is None:
        raise DeliveryError(f"run not found: {rid}")
    if run["factory"] not in FILING_FACTORIES:
        raise DeliveryError(
            "only an approved digest or project status can be filed. "
            "feature-builder output belongs on a branch, not a document.")
    if run["verdict"] != "approved":
        raise DeliveryError(
            f"run {rid} is {run['verdict']}. Approve it before filing.")
    text = (run["output"] or "").strip()
    if not text:
        raise DeliveryError(f"run {rid} has no draft text to file")
    if not production or production["version"] != run["prompt_version"]:
        raise DeliveryError(
            f"run {rid} used {run['prompt_version']}, which is not production. "
            "Promote the prompt with recorded eval passes first.")
    for path, meta, _body in objects.iter_objects(root, "document"):
        if str(meta.get("source_run") or "") == str(rid):
            raise DeliveryError(
                f"run {rid} is already filed as {meta.get('id') or path.name}")
    if title is not None and not title.strip():
        raise DeliveryError("title cannot be blank")
    shown = (title or "").strip() or _default_title(root, run)
    folder = root / "context" / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", shown.lower()).strip("-") or f"run-{rid}"
    document_id = f"document-{slug}"
    path = folder / f"{slug}.md"
    n = 2
    while path.exists():
        document_id = f"document-{slug}-{n}"
        path = folder / f"{slug}-{n}.md"
        n += 1
    today = date.today().isoformat()
    meta = {"id": document_id, "type": "document", "title": shown,
            "created": today, "updated": today, "status": "active",
            "source_run": str(rid)}
    if run["project"]:
        meta["project"] = run["project"]
    from ctx.actors import stamp
    stamp(root, meta)
    body = (f"# {shown}\n\n{text}\n\n"
            f"Filed from run {rid} ({run['factory']} {run['prompt_version']}). "
            "Local only. Nothing was posted, pushed, or merged.\n")
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"ok": True, "run_id": rid, "id": document_id, "path": path,
            "project": run["project"]}


def _default_title(root: Path, run) -> str:
    today = date.today().isoformat()
    if run["factory"] == "weekly-project-status" and run["project"]:
        found = objects.find(root, "project", run["project"])
        name = found[1].get("title") if found else run["project"]
        return f"{name} status {today}"[:200]
    return f"Contribution digest {today}"
