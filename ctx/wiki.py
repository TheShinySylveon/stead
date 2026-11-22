"""Repo wiki as a space: a page tree, child pages, labels, and metadata.

Read-only. Generated from the context files and the run ledger; no model call,
no second store, no writes. Agents still receive scoped bundles.
"""

from __future__ import annotations

import re
from pathlib import Path

from ctx import db, objects

DECISION_TAGS = {"decision", "decisions", "adr", "architecture"}
GLOSSARY_TAGS = {"glossary", "terms", "vocabulary"}
MAX_CHILDREN = 100


class WikiError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _tags(meta: dict) -> list[str]:
    raw = meta.get("tags") or []
    values = raw if isinstance(raw, list) else [str(raw)]
    return [str(value).strip() for value in values if str(value).strip()]


def _has_tag(meta: dict, wanted: set[str]) -> bool:
    return bool({tag.lower() for tag in _tags(meta)} & wanted)


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


def _blurb(body: str) -> str:
    return _first_paragraph(body)[:220]


def _without_title(body: str, title: str) -> str:
    """Drop a leading H1 that repeats the page title."""
    lines = body.splitlines()
    if lines and re.match(r"^#\s+(.+)$", lines[0].strip()):
        heading = lines[0].strip()[2:].strip()
        if heading.lower() == (title or "").strip().lower():
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
    return "\n".join(lines).lstrip("\n")


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


def _labels(meta: dict, *extra: str) -> list[str]:
    labels = list(extra)
    for key in ("kind", "state", "status"):
        value = meta.get(key)
        if value and str(value) not in labels:
            labels.append(str(value))
    for tag in _tags(meta):
        if tag not in labels:
            labels.append(tag)
    return labels


def _tree(root: Path, repo_id: str, project_id: str) -> list[dict]:
    docs = _project_objects(root, project_id, "document")
    specs = [item for item in _contributions(root, repo_id) if item[1].get("kind") == "issue"]
    decisions = [item for item in docs if _has_tag(item[1], DECISION_TAGS)]
    glossary = [item for item in docs if _has_tag(item[1], GLOSSARY_TAGS)]
    tasks = _project_objects(root, project_id, "task")
    tree = [{"slug": "overview", "title": "Overview", "children": []}]
    tree.append({"slug": "specs", "title": "Specs", "children": [
        {"slug": f"specs/{meta.get('id')}", "title": meta.get("title") or path.stem,
         "children": []}
        for path, meta, _body in specs[:MAX_CHILDREN]
    ]})
    tree.append({"slug": "decisions", "title": "Decisions", "children": [
        {"slug": f"decisions/{meta.get('id')}", "title": meta.get("title") or path.stem,
         "children": []}
        for path, meta, _body in decisions[:MAX_CHILDREN]
    ]})
    if glossary:
        tree.append({"slug": "glossary", "title": "Glossary", "children": [
            {"slug": f"glossary/{meta.get('id')}", "title": meta.get("title") or path.stem,
             "children": []}
            for path, meta, _body in glossary[:MAX_CHILDREN]
        ]})
    tree.append({"slug": "tasks", "title": "Tasks", "children": [
        {"slug": f"tasks/{meta.get('id')}", "title": meta.get("title") or path.stem,
         "children": []}
        for path, meta, _body in tasks[:MAX_CHILDREN]
    ]})
    tree.append({"slug": "history", "title": "History", "children": []})
    return tree


def index(root: Path, repo_ref: str) -> dict:
    """The space home: status, essentials, and the page tree."""
    repo_path, repo, repo_body = _repo(root, repo_ref)
    repo_id = repo.get("id", repo_path.stem)
    project_id = repo.get("project") or ""
    project = objects.find(root, "project", project_id) if project_id else None
    summary = _first_paragraph(repo_body) or (_first_paragraph(project[2]) if project else "")
    specs = [(p, m, b) for p, m, b in _contributions(root, repo_id) if m.get("kind") == "issue"]
    contributions = _contributions(root, repo_id)
    docs = _project_objects(root, project_id, "document")
    decisions = [(p, m, b) for p, m, b in docs if _has_tag(m, DECISION_TAGS)]
    glossary = [(p, m, b) for p, m, b in docs if _has_tag(m, GLOSSARY_TAGS)]
    tasks = _project_objects(root, project_id, "task")
    open_specs = [item for item in specs if item[1].get("state") in (None, "", "open")]
    open_tasks = [item for item in tasks if item[1].get("status") != "done"]
    merged = [item for item in contributions if item[1].get("state") == "merged"]
    runs = _runs(root, {m.get("id") for _p, m, _b in contributions})

    start = []
    if project:
        start.append({"title": project[1].get("title") or project_id,
                      "why": "the project record", "type": "project", "id": project_id})
    if decisions:
        start.append({"title": decisions[0][1].get("title") or decisions[0][0].stem,
                      "why": "the newest decision", "type": "document",
                      "id": decisions[0][1].get("id")})
    if open_specs:
        start.append({"title": open_specs[0][1].get("title") or open_specs[0][0].stem,
                      "why": "the current spec", "slug": f"specs/{open_specs[0][1].get('id')}"})
    if glossary:
        start.append({"title": glossary[0][1].get("title") or glossary[0][0].stem,
                      "why": "shared vocabulary", "slug": f"glossary/{glossary[0][1].get('id')}"})

    recent = []
    for _path, meta, _body in merged[-3:]:
        recent.append({"when": meta.get("updated", ""), "kind": "merged",
                       "title": meta.get("title", ""), "slug": f"history"})
    for run in runs[:3]:
        recent.append({"when": run["created"], "kind": f"run {run['verdict']}",
                       "title": f"{run['factory']} · {run['prompt_version']}", "slug": ""})
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
        "tree": _tree(root, repo_id, project_id),
        "counts": {
            "specs_open": len(open_specs),
            "decisions": len(decisions),
            "tasks_open": len(open_tasks),
            "merged": len(merged),
        },
        "start": start,
        "recent": recent,
    }


def _find_contrib(root: Path, repo_id: str, object_id: str):
    for path, meta, body in _contributions(root, repo_id):
        if meta.get("id") == object_id:
            return path, meta, body
    raise WikiError(f"page not found: {object_id}")


def _find_doc(root: Path, project_id: str, object_id: str):
    for path, meta, body in _project_objects(root, project_id, "document"):
        if meta.get("id") == object_id:
            return path, meta, body
    raise WikiError(f"page not found: {object_id}")


def _find_task(root: Path, project_id: str, object_id: str):
    for path, meta, body in _project_objects(root, project_id, "task"):
        if meta.get("id") == object_id:
            return path, meta, body
    raise WikiError(f"page not found: {object_id}")


def _breadcrumb(tree: list[dict], path: str) -> list[dict]:
    parts = path.split("/")
    trail = []
    for node in tree:
        if node["slug"] == parts[0]:
            trail.append({"slug": node["slug"], "title": node["title"]})
            if len(parts) > 1:
                for child in node.get("children") or []:
                    if child["slug"] == path:
                        trail.append({"slug": child["slug"], "title": child["title"]})
                        break
            break
    return trail


def page(root: Path, repo_ref: str, path: str) -> dict:
    """One page. `path` is `group` or `group/<object-id>`."""
    repo_path, repo, _repo_body = _repo(root, repo_ref)
    repo_id = repo.get("id", repo_path.stem)
    project_id = repo.get("project") or ""
    tree = _tree(root, repo_id, project_id)
    group, _, object_id = path.partition("/")
    markdown = ""
    labels: list[str] = []
    updated = ""
    author = ""
    children: list[dict] = []
    title = group.title()

    if group == "overview" and not object_id:
        title = "Overview"
        project = objects.find(root, "project", project_id) if project_id else None
        body = project[2] if project else ""
        markdown = (f"## What this repo is\n\n{body.strip() or 'No project description yet.'}\n\n"
                    "## How work happens here\n\n"
                    f"- Trigger: `{repo.get('trigger') or 'on-demand'}`\n"
                    f"- Autonomy ceiling: `{repo.get('reach') or 'shadow'}`\n"
                    f"- Default branch: `{repo.get('default_branch') or 'main'}`\n"
                    f"- Local checkout: `{repo.get('code_path') or 'not set'}`\n")
        labels = [repo.get("kind") or "oss", repo.get("status") or "active"]
        updated = repo.get("updated", "")
    elif group == "specs" and not object_id:
        title = "Specs"
        markdown = "Every spec cached for this repo. Open one for the full text."
        children = [{"slug": f"specs/{m.get('id')}", "title": m.get("title") or p.stem,
                     "meta": f"issue #{m.get('number', '?')} · {m.get('state', 'open')}",
                     "blurb": _blurb(b), "labels": _labels(m)}
                    for p, m, b in _contributions(root, repo_id) if m.get("kind") == "issue"]
    elif group == "specs" and object_id:
        p, m, b = _find_contrib(root, repo_id, object_id)
        title = m.get("title") or p.stem
        markdown = _without_title(b, title)
        labels = _labels(m)
        updated = m.get("updated", "")
        author = m.get("actor", "")
    elif group == "decisions" and not object_id:
        title = "Decisions"
        markdown = "Architecture and product decisions, newest first."
        docs = _project_objects(root, project_id, "document")
        children = [{"slug": f"decisions/{m.get('id')}", "title": m.get("title") or p.stem,
                     "meta": f"updated {m.get('updated', '')}", "blurb": _blurb(b),
                     "labels": _labels(m)}
                    for p, m, b in docs if _has_tag(m, DECISION_TAGS)]
    elif group == "decisions" and object_id:
        p, m, b = _find_doc(root, project_id, object_id)
        if not _has_tag(m, DECISION_TAGS):
            raise WikiError(f"page not found: {path}")
        title = m.get("title") or p.stem
        markdown = _without_title(b, title)
        labels = _labels(m)
        updated = m.get("updated", "")
        author = m.get("actor", "")
    elif group == "glossary" and not object_id:
        title = "Glossary"
        markdown = "Shared vocabulary. Agents must not guess these terms."
        docs = _project_objects(root, project_id, "document")
        children = [{"slug": f"glossary/{m.get('id')}", "title": m.get("title") or p.stem,
                     "meta": "shared terms", "blurb": _blurb(b), "labels": _labels(m)}
                    for p, m, b in docs if _has_tag(m, GLOSSARY_TAGS)]
    elif group == "glossary" and object_id:
        p, m, b = _find_doc(root, project_id, object_id)
        if not _has_tag(m, GLOSSARY_TAGS):
            raise WikiError(f"page not found: {path}")
        title = m.get("title") or p.stem
        markdown = _without_title(b, title)
        labels = _labels(m)
        updated = m.get("updated", "")
    elif group == "tasks" and not object_id:
        title = "Tasks"
        markdown = "Open work for this repo's project."
        children = [{"slug": f"tasks/{m.get('id')}", "title": m.get("title") or p.stem,
                     "meta": m.get("status", "to-do"), "blurb": _blurb(b),
                     "labels": _labels(m)}
                    for p, m, b in _project_objects(root, project_id, "task")]
    elif group == "tasks" and object_id:
        p, m, b = _find_task(root, project_id, object_id)
        title = m.get("title") or p.stem
        markdown = _without_title(b, title)
        labels = _labels(m)
        updated = m.get("updated", "")
        author = m.get("actor", "")
    elif group == "history" and not object_id:
        title = "History"
        contributions = _contributions(root, repo_id)
        ids = {m.get("id") for _p, m, _b in contributions}
        merged = [item for item in contributions if item[1].get("state") in {"merged", "closed"}]
        rows = [f"- **{m.get('title', p.stem)}** — {m.get('kind')} #{m.get('number', '?')} · "
                f"{m.get('state')} · {m.get('updated', '')}"
                for p, m, _b in merged]
        runs = _runs(root, ids)[:20]
        if runs:
            rows.append("")
            rows.append("### Factory runs")
            rows.extend(f"- run {r['id']} · {r['factory']} · {r['mode']} · {r['verdict']} · "
                        f"{r['created']}" for r in runs)
        markdown = "Closed work and the run ledger.\n\n" + ("\n".join(rows) or "No history yet.")
    else:
        raise WikiError(f"page not found: {path}")

    return {
        "repo": {"id": repo_id, "title": repo.get("title", repo_id)},
        "tree": tree,
        "page": {
            "path": path,
            "title": title,
            "markdown": markdown,
            "labels": labels,
            "updated": updated,
            "author": author,
            "breadcrumb": _breadcrumb(tree, path),
            "children": children,
        },
    }
