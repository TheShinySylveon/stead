"""Close the loop: a delivered build updates the context it came from.

Two kinds of write-back, deliberately separated:

- **Facts** (this module): on a successful build, record the outcome as a
  versioned ``build-record`` document, mark the contribution merged when it
  merged, and close tasks that point at it. These need no review.
- **Interpretation** (decisions, glossary): the build may only *propose* these
  as inbox notes. A person triages them into documents. An agent never quietly
  rewrites the context later builds depend on.

The record is a normal markdown object, so git versions it and the wiki and the
next bundle can read it. The SQLite ``runs`` table stays a rebuildable index.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from pathlib import Path

from ctx import frontmatter, objects

RECORD_TAG = "build-record"


class WritebackError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _repo_of(root: Path, contribution_ref: str):
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise WritebackError(f"contribution not found: {contribution_ref}")
    _path, meta, _body = found
    repo = objects.find(root, "repo", meta.get("repo") or "")
    return meta, (repo[1] if repo else {})


def record_delivery(root: Path, contribution_ref: str, result: dict,
                    run_id: object = None) -> dict:
    """Write the factual record and update linked statuses. Returns the doc id."""
    contrib, repo_meta = _repo_of(root, contribution_ref)
    repo_id = str(repo_meta.get("id") or contrib.get("repo") or "repo")
    merged = bool(result.get("merged"))
    today = date.today().isoformat()
    updated: list[str] = []

    if merged and contrib.get("state") != "merged":
        _patch(root, "contribution", contribution_ref, {"state": "merged"})
        updated.append(contribution_ref)

    if merged:
        for path, meta, _body in objects.iter_objects(root, "task"):
            related = meta.get("related") or []
            if isinstance(related, str):
                related = [related]
            if contribution_ref in related or contrib.get("id") in related:
                if meta.get("status") != "done":
                    _patch(root, "task", meta.get("id") or path.stem, {"status": "done"})
                    updated.append(str(meta.get("id") or path.stem))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-",
                  (contrib.get("title") or contribution_ref).lower()).strip("-") or "build"
    folder = root / "context" / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"build-{slug[:40]}-{stamp}"
    path = folder / f"{name}.md"
    n = 2
    while path.exists():
        path = folder / f"{name}-{n}.md"
        n += 1
    doc_id = f"document-{path.stem}"
    outcome = "merged" if merged else ("published" if result.get("published") else "committed")
    title = f"Build: {contrib.get('title') or contribution_ref} ({outcome})"
    meta = {
        "id": doc_id, "type": "document", "title": title[:200],
        "created": today, "updated": today, "status": "active",
        "tags": [RECORD_TAG, f"repo:{repo_id}"],
        "outcome": outcome,
        "checks_mode": str(result.get("checks_mode") or "none"),
        "elapsed_seconds": str(result.get("elapsed_seconds") or 0),
        "repair_rounds": str(result.get("repair_rounds") or 0),
        "files": list(result.get("files") or []),
        "tests_touched": list(result.get("tests_touched") or []),
        "tests_deleted": list(result.get("tests_deleted") or []),
    }
    if result.get("branch"):
        meta["branch"] = result["branch"]
    if result.get("commit"):
        meta["commit"] = result["commit"]
    if result.get("pr_url"):
        meta["pr_url"] = result["pr_url"]
    if repo_meta.get("project"):
        meta["project"] = repo_meta["project"]
    if run_id is not None:
        meta["source_run"] = str(run_id)
    from ctx.actors import stamp as actor_stamp
    actor_stamp(root, meta)
    body = _record_body(contrib, result, outcome)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"id": doc_id, "path": path.relative_to(root).as_posix(),
            "outcome": outcome, "updated": updated}


def _record_body(contrib: dict, result: dict, outcome: str) -> str:
    lines = [f"# Build record: {contrib.get('title') or contrib.get('id')}", "",
             f"Outcome: **{outcome}**.", ""]
    if result.get("branch"):
        lines.append(f"- branch: `{result['branch']}`")
    if result.get("commit"):
        lines.append(f"- commit: `{result['commit']}`")
    if result.get("pr_url"):
        lines.append(f"- pull request: {result['pr_url']}")
    if result.get("merged_url"):
        lines.append(f"- merged: {result['merged_url']}")
    if result.get("checks"):
        lines.append(f"- checks: `{result['checks']}` ({result.get('checks_mode', 'host')})")
    if result.get("files"):
        lines.append("- files: " + ", ".join(f"`{p}`" for p in result["files"]))
    if result.get("deleted"):
        lines.append("- deleted: " + ", ".join(f"`{p}`" for p in result["deleted"]))
    if result.get("tests_touched"):
        lines.append("- tests touched: " + ", ".join(f"`{p}`" for p in result["tests_touched"]))
    if result.get("tests_deleted"):
        lines.append("- tests deleted: " + ", ".join(f"`{p}`" for p in result["tests_deleted"]))
    if result.get("summary"):
        lines += ["", "## Summary (model)", "", str(result["summary"]).strip()]
    lines += ["", "Factual record written by Stead on delivery. Interpretive notes "
              "(decisions, glossary) are proposed to the inbox for a person to triage.", ""]
    return "\n".join(lines)


def _patch(root: Path, otype: str, ref: str, fields: dict) -> None:
    found = objects.find(root, otype, ref)
    if found is None:
        return
    path, meta, body = found
    meta.update(fields)
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")


def prior_records(root: Path, repo_id: str, limit: int = 5) -> list[tuple[Path, dict, str]]:
    """Recent build records for one repo, newest first. Used by the bundle."""
    found = []
    for path, meta, body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags or f"repo:{repo_id}".lower() not in tags:
            continue
        found.append((path, meta, body))
    found.sort(key=lambda item: str(item[1].get("created") or ""), reverse=True)
    return found[:limit]


def propose_note(root: Path, kind: str, title: str, text: str,
                 source: str = "") -> dict:
    """An interpretive proposal goes to the inbox, not into context/."""
    kind = (kind or "decision").strip().lower()
    if kind not in {"decision", "glossary"}:
        raise WritebackError("propose kind must be decision or glossary")
    title = (title or "").strip()
    text = (text or "").strip()
    if not title or not text:
        raise WritebackError("a proposal needs a title and text")
    folder = root / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or kind
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"propose-{kind}-{slug[:40]}-{stamp}.md"
    n = 2
    while path.exists():
        path = folder / f"propose-{kind}-{slug[:40]}-{stamp}-{n}.md"
        n += 1
    body = (f"# Proposed {kind}: {title}\n\n{text}\n\n"
            f"Proposed by a build{(' from ' + source) if source else ''}. "
            "Triage into context/documents/ if it is worth keeping.\n")
    path.write_text(body, encoding="utf-8")
    return {"path": path.relative_to(root).as_posix(), "kind": kind, "title": title}
