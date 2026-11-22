"""Repo wiki: a human-readable home page and drill-down pages.

Read-only. It composes existing context files and the run ledger; it does not
call a model, write files, or touch GitHub. Agents use bundles instead.
"""

from __future__ import annotations

from pathlib import Path

from ctx import db, objects

PAGE_TITLES = [
    ("overview", "Overview"),
    ("specs", "Specs"),
    ("decisions", "Decisions"),
    ("glossary", "Glossary"),
    ("tasks", "Tasks"),
    ("history", "History"),
]

DECISION_TAGS = {"decision", "decisions", "adr", "architecture"}
GLOSSARY_TAGS = {"glossary", "terms", "vocabulary"}


class WikiError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _tags(meta: dict) -> set[str]:
    raw = meta.get("tags") or []
    values = raw if isinstance(raw, list) else [str(raw)]
    return {str(value).strip().lower() for value in values if str(value).strip()}


def _first_paragraph(body: str) -> str:
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if not stripped:
            if lines:
                break
            continue
        lines.append(stripped)
    return " ".join(lines)[:400]


def _repo(root: Path, repo_ref: str):
    found = objects.find(root, "repo", repo_ref)
    if found is None:
        raise WikiError(f"repo not found: {repo_ref}")
    return found


def _project_objects(root: Path, project_id: str, otype: str) -> list[tuple[Path, dict, str]]:
    if not project_id:
        return []
    return [(path, meta, body) for path, meta, body in objects.iter_objects(root, otype)
            if meta.get("project") == project_id]


def _contributions(root: Path, repo_id: str) -> list[tuple[Path, dict, str]]:
    return [(path, meta, body) for path, meta, body in objects.iter_objects(root, "contribution")
            if meta.get("repo") == repo_id]


def _runs(root: Path, contribution_ids: set[str]) -> list[dict]:
    if not db.db_path(root).exists() or not contribution_ids:
        return []
    conn = db.connect(root)
    try:
        rows = conn.execute(
            "SELECT id, factory, task_ref, prompt_version, mode, verdict, created, bundle_path "
            "FROM runs ORDER BY id DESC LIMIT 200").fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows if row["task_ref"] in contribution_ids]


def _page_list(root: Path, repo_id: str, project_id: str) -> list[dict]:
    docs = _project_objects(root, project_id, "document")
    has_glossary = any(_tags(meta) & GLOSSARY_TAGS for _path, meta, _body in docs)
    pages = []
    for slug, title in PAGE_TITLES:
        if slug == "glossary" and not has_glossary:
            continue
        pages.append({"slug": slug, "title": title})
    return pages


def index(root: Path, repo_ref: str) -> dict:
    """The repo home: status, the essentials, and links into the wiki."""
    repo_path, repo, repo_body = _repo(root, repo_ref)
    repo_id = repo.get("id", repo_path.stem)
    project_id = repo.get("project") or ""
    project = objects.find(root, "project", project_id) if project_id else None
    summary = _first_paragraph(repo_body) or (_first_paragraph(project[2]) if project else "")
    specs = [(p, m, b) for p, m, b in _contributions(root, repo_id)
             if m.get("kind") == "issue"]
    contributions = _contributions(root, repo_id)
    docs = _project_objects(root, project_id, "document")
    decisions = [(p, m, b) for p, m, b in docs if _tags(m) & DECISION_TAGS]
    glossary = [(p, m, b) for p, m, b in docs if _tags(m) & GLOSSARY_TAGS]
    tasks = _project_objects(root, project_id, "task")
    open_tasks = [item for item in tasks if item[1].get("status") != "done"]
    merged = [item for item in contributions if item[1].get("state") == "merged"]
    runs = _runs(root, {m.get("id") for _p, m, _b in contributions})

    start = []
    if project:
        start.append({"title": project[1].get("title") or project_id,
                      "why": "the project record", "type": "project",
                      "id": project_id})
    if decisions:
        start.append({"title": decisions[0][1].get("title") or decisions[0][0].stem,
                      "why": "the newest decision", "type": "document",
                      "id": decisions[0][1].get("id")})
    open_specs = [item for item in specs if item[1].get("state") in (None, "", "open")]
    if open_specs:
        start.append({"title": open_specs[0][1].get("title") or open_specs[0][0].stem,
                      "why": "the current spec", "type": "contribution",
                      "id": open_specs[0][1].get("id")})
    if glossary:
        start.append({"title": glossary[0][1].get("title") or glossary[0][0].stem,
                      "why": "shared vocabulary", "type": "document",
                      "id": glossary[0][1].get("id")})

    recent = []
    for _path, meta, _body in merged[-3:]:
        recent.append({"when": meta.get("updated", ""), "kind": "merged",
                       "title": meta.get("title", ""), "id": meta.get("id")})
    for run in runs[:3]:
        recent.append({"when": run["created"], "kind": f"run {run['verdict']}",
                       "title": f"{run['factory']} · {run['prompt_version']}",
                       "id": None})
    recent.sort(key=lambda item: item["when"], reverse=True)

    return {
        "repo": {
            "id": repo_id,
            "title": repo.get("title", repo_id),
            "kind": repo.get("kind") or "oss",
            "status": repo.get("status") or "active",
            "url": repo.get("url") or "",
            "project": project_id,
            "trigger": repo.get("trigger") or "on-demand",
            "reach": repo.get("reach") or "shadow",
            "code_path": repo.get("code_path") or "",
            "default_branch": repo.get("default_branch") or "",
        },
        "summary": summary,
        "pages": _page_list(root, repo_id, project_id),
        "counts": {
            "specs_open": len(open_specs),
            "decisions": len(decisions),
            "tasks_open": len(open_tasks),
            "merged": len(merged),
        },
        "start": start,
        "recent": recent,
    }


def page(root: Path, repo_ref: str, slug: str) -> dict:
    """One wiki page. Bodies are markdown; entries are clickable objects."""
    repo_path, repo, _repo_body = _repo(root, repo_ref)
    repo_id = repo.get("id", repo_path.stem)
    project_id = repo.get("project") or ""
    docs = _project_objects(root, project_id, "document")
    entries: list[dict] = []
    markdown = ""

    if slug == "overview":
        project = objects.find(root, "project", project_id) if project_id else None
        project_body = project[2] if project else ""
        markdown = (f"## What this repo is\n\n{project_body.strip() or 'No project description yet.'}\n\n"
                    "## How work happens here\n\n"
                    f"- Trigger: `{repo.get('trigger') or 'on-demand'}`\n"
                    f"- Autonomy ceiling: `{repo.get('reach') or 'shadow'}`\n"
                    f"- Default branch: `{repo.get('default_branch') or 'main'}`\n"
                    f"- Local checkout: `{repo.get('code_path') or 'not set'}`\n")
    elif slug == "specs":
        for path, meta, body in _contributions(root, repo_id):
            if meta.get("kind") != "issue":
                continue
            entries.append({
                "type": "contribution", "id": meta.get("id"),
                "title": meta.get("title", path.stem),
                "meta": f"issue #{meta.get('number', '?')} · {meta.get('state', 'open')}",
                "body": _first_paragraph(body),
            })
    elif slug == "decisions":
        for path, meta, body in docs:
            if not (_tags(meta) & DECISION_TAGS):
                continue
            entries.append({
                "type": "document", "id": meta.get("id"),
                "title": meta.get("title", path.stem),
                "meta": f"updated {meta.get('updated', '')}",
                "body": _first_paragraph(body),
            })
    elif slug == "glossary":
        for path, meta, body in docs:
            if not (_tags(meta) & GLOSSARY_TAGS):
                continue
            entries.append({
                "type": "document", "id": meta.get("id"),
                "title": meta.get("title", path.stem),
                "meta": "shared terms", "body": body.strip()[:2000],
            })
    elif slug == "tasks":
        for path, meta, _body in _project_objects(root, project_id, "task"):
            entries.append({
                "type": "task", "id": meta.get("id"),
                "title": meta.get("title", path.stem),
                "meta": meta.get("status", "to-do"), "body": "",
            })
    elif slug == "history":
        contributions = _contributions(root, repo_id)
        ids = {m.get("id") for _p, m, _b in contributions}
        for path, meta, body in contributions:
            if meta.get("state") not in {"merged", "closed"}:
                continue
            entries.append({
                "type": "contribution", "id": meta.get("id"),
                "title": meta.get("title", path.stem),
                "meta": f"{meta.get('kind')} #{meta.get('number', '?')} · {meta.get('state')}",
                "body": _first_paragraph(body),
            })
        for run in _runs(root, ids)[:20]:
            entries.append({
                "type": None, "id": None,
                "title": f"run {run['id']} · {run['factory']}",
                "meta": f"{run['mode']} · {run['verdict']} · {run['created']}",
                "body": "",
            })
    else:
        raise WikiError(f"unknown wiki page: {slug}")

    pages = _page_list(root, repo_id, project_id)
    if not any(item["slug"] == slug for item in pages):
        raise WikiError(f"page not available: {slug}")
    return {
        "repo": {"id": repo_id, "title": repo.get("title", repo_id)},
        "pages": pages,
        "page": {"slug": slug,
                 "title": next(item["title"] for item in pages if item["slug"] == slug),
                 "markdown": markdown, "entries": entries},
    }
