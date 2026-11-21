"""Local cockpit: a loopback web UI over the context system.

Stdlib only. Binds to 127.0.0.1. Markdown stays the source of truth; writes
go through the same CLI handlers as the terminal. No LLM, no network beyond
the loopback socket, no remote writes. Factory runs from the UI are
shadow-only.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import secrets
import threading
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ctx import cli, db, factory, frontmatter, objects

PKG_DIR = Path(__file__).resolve().parent
PAGE_PATH = PKG_DIR / "cockpit.html"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
_GATE_STYLE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Stead</title>
<meta name="description" content="Enter the shared-server access token. It is not stored in git.">
<style>
  /* Hallmark: shape app screen, theme Console, redesign full, v2.0.0 */
  :root {
    --color-paper: oklch(17% 0.008 250); --color-paper-2: oklch(21% 0.009 250); --color-paper-3: oklch(13.5% 0.007 250);
    --color-ink: oklch(95% 0.005 250); --color-muted: oklch(71% 0.01 250);
    --color-rule: oklch(31% 0.01 250);
    --color-accent: oklch(82% 0.15 80); --color-accent-ink: oklch(18% 0.04 75); --color-focus: oklch(82% 0.15 80);
    --font-body: "Host Grotesk", "Segoe UI", ui-sans-serif, system-ui, sans-serif;
  }
  html, body { margin: 0; min-height: 100%; overflow-x: clip; }
  body { display: grid; place-items: center; background: var(--color-paper); color: var(--color-ink);
    font: 1rem/1.55 var(--font-body); }
  form { width: min(420px, 92vw); background: var(--color-paper-2); border: 1px solid var(--color-rule);
    border-radius: 10px; padding: 24px; }
  h1 { font: 500 1.728rem/1.05 var(--font-body); letter-spacing: -0.03em; margin: 0 0 8px; text-wrap: balance; }
  p { color: var(--color-muted); }
  input, button { font: inherit; width: 100%; box-sizing: border-box; margin-top: 8px;
    padding: 8px 12px; border-radius: 6px; min-height: 36px; }
  input { background: var(--color-paper-3); color: var(--color-ink); border: 1px solid var(--color-rule); }
  button { background: var(--color-accent); color: var(--color-accent-ink); border: 1px solid var(--color-accent); cursor: pointer; }
  button:disabled { opacity: 0.45; cursor: not-allowed; }
  :focus-visible { outline: 2px solid var(--color-focus); outline-offset: 2px; }
</style></head>
<body>
<form method="POST" action="/api/session">
  <h1>Stead</h1>
  __FIELDS__
  <button type="submit">Continue</button>
</form>
</body></html>
"""


def _gate_page(people: bool) -> bytes:
    if people:
        fields = (
            "<p>Sign in as yourself. The password is not stored in git.</p>"
            '<input name="name" autocomplete="username" required aria-label="Name">'
            '<input type="password" name="password" autocomplete="current-password" '
            'required aria-label="Password">'
        )
    else:
        fields = (
            "<p>No people yet. Enter the access token, then add an account. "
            "It is not stored in git.</p>"
            '<input type="password" name="token" autocomplete="current-password" '
            'required aria-label="Access token">'
        )
    return _GATE_STYLE.replace("__FIELDS__", fields).encode("utf-8")
MAX_BODY = 512 * 1024
MAX_NOTE = 200_000
EDITABLE = ("project", "task", "document", "meeting")
PROJECT_STATUSES = ("active", "paused", "done")

# What a shadow assemble needs. Unknown factories ask for a project.
FACTORY_NEEDS = {
    factory.DIGEST_FACTORY: "none",
    "weekly-project-status": "project",
    factory.FEATURE_BUILDER_FACTORY: "contribution",
}


class UiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _tags(meta: dict) -> list[str]:
    tags = meta.get("tags") or []
    return tags if isinstance(tags, list) else [str(tags)]


def _summary(root: Path, otype: str, path: Path, meta: dict) -> dict:
    item = {
        "type": otype,
        "id": meta.get("id", path.stem),
        "title": meta.get("title", path.stem),
        "updated": meta.get("updated", ""),
        "path": _rel(root, path),
    }
    for key in ("status", "project", "repo", "kind", "url", "role", "state",
                "ci", "review", "method", "number", "trigger", "reach"):
        if meta.get(key) not in (None, ""):
            item[key] = meta[key]
    if otype == "repo":
        from ctx.autonomy import effective
        policy = effective(root, meta)
        item["factory_trigger"] = policy["trigger"]
        item["factory_reach"] = policy["ceiling"]
        item["merge_explicit"] = policy["merge_explicit"]
    tags = _tags(meta)
    if tags:
        item["tags"] = tags
    return item


def _list(root: Path, otype: str) -> list[dict]:
    return [_summary(root, otype, path, meta)
            for path, meta, _body in objects.iter_objects(root, otype)]


def list_inbox(root: Path) -> list[dict]:
    folder = root / "inbox"
    if not folder.is_dir():
        return []
    items = []
    for path in sorted(folder.iterdir()):
        if not path.is_file() or path.name == "README.md" or path.name.startswith("."):
            continue
        stat = path.stat()
        items.append({
            "name": path.name,
            "path": _rel(root, path),
            "updated": date.fromtimestamp(stat.st_mtime).isoformat(),
            "bytes": stat.st_size,
        })
    return items


def _attention(tasks: list[dict], contribs: list[dict], inbox: list[dict]) -> list[dict]:
    items = []
    for task in tasks:
        if task.get("status") == "doing":
            items.append({"tone": "doing", "label": "In progress", "title": task["title"],
                          "type": "task", "id": task["id"]})
        elif task.get("status") == "blocked":
            items.append({"tone": "blocked", "label": "Blocked", "title": task["title"],
                          "type": "task", "id": task["id"]})
    for contrib in contribs:
        if contrib.get("review") == "requested":
            items.append({"tone": "review", "label": "Review requested",
                          "title": contrib["title"], "type": "contribution", "id": contrib["id"]})
        if contrib.get("ci") == "fail":
            items.append({"tone": "fail", "label": "CI failing", "title": contrib["title"],
                          "type": "contribution", "id": contrib["id"]})
    for item in inbox:
        items.append({"tone": "inbox", "label": "Needs triage", "title": item["name"],
                      "type": "inbox", "id": item["name"]})
    return items


def _factories(root: Path, runs: list[dict]) -> list[dict]:
    folder = root / "factories"
    if not folder.is_dir():
        return []
    out = []
    for fdir in sorted(p for p in folder.iterdir() if p.is_dir()):
        prompts = []
        pdir = fdir / "prompts"
        if pdir.is_dir():
            for path in sorted(pdir.glob("v*.md")):
                prompts.append({"version": path.stem, "path": _rel(root, path)})
        evals = len(list((fdir / "evals").glob("*.json"))) if (fdir / "evals").is_dir() else 0
        recent = [r for r in runs if r["factory"] == fdir.name][:5]
        out.append({
            "name": fdir.name,
            "needs": FACTORY_NEEDS.get(fdir.name, "project"),
            "prompts": prompts,
            "evals": evals,
            "recent_runs": recent,
        })
    return out


def _prompt_status(root: Path) -> dict[tuple[str, str], str]:
    if not db.db_path(root).exists():
        return {}
    conn = db.connect(root)
    try:
        rows = conn.execute("SELECT factory, version, status FROM prompt_versions").fetchall()
    except Exception:
        return {}
    finally:
        conn.close()
    return {(r["factory"], r["version"]): r["status"] for r in rows}


def _runs(root: Path) -> list[dict]:
    if not db.db_path(root).exists():
        return []
    conn = db.connect(root)
    try:
        rows = conn.execute(
            "SELECT id, factory, task_ref, project, prompt_version, mode, verdict, "
            "created, bundle_path FROM runs ORDER BY id DESC LIMIT 40"
        ).fetchall()
    except Exception:
        return []
    finally:
        conn.close()
    return [{
        "id": r["id"],
        "factory": r["factory"],
        "task_ref": r["task_ref"],
        "project": r["project"],
        "prompt_version": r["prompt_version"],
        "mode": r["mode"],
        "verdict": r["verdict"],
        "created": r["created"],
        "bundle_path": r["bundle_path"],
    } for r in rows]


def _needs_welcome(root: Path) -> bool:
    from ctx.onboard import needs_welcome
    return needs_welcome(root)


def _model_providers() -> list[dict]:
    from ctx.models import PROVIDER_LABELS, PROVIDERS
    return [{"id": key, "label": PROVIDER_LABELS[key]} for key in PROVIDERS]


def _accounts(root: Path) -> list[dict]:
    from ctx.accounts import AccountError, public_list
    try:
        return public_list(root)
    except AccountError:
        return []


def _current_actor(root: Path) -> str:
    from ctx.actors import current
    return current(root)


def _factory_defaults(root: Path) -> dict:
    from ctx.autonomy import factory_defaults
    return factory_defaults(root)


def _model_view(root: Path) -> dict:
    from ctx.models import public_model
    try:
        return public_model(root)
    except Exception:
        return {"configured": False, "provider": "", "name": "", "base_url": "",
                "key_set": False, "key_from": "", "key_env": "STEAD_MODEL_API_KEY"}


def _deployment_view(root: Path) -> dict:
    from ctx.config import ConfigError, public_view
    try:
        return public_view(root)
    except ConfigError:
        return {"deployment": "single", "bind": "127.0.0.1", "port": 8765, "token_set": False}


def add_actor(root: Path, title: str, kind: str = "human") -> dict:
    from ctx.config import ACTOR_KINDS
    title = (title or "").strip()
    if not title or len(title) > 200:
        raise UiError("an actor needs a title")
    if kind not in ACTOR_KINDS:
        raise UiError(f"invalid kind {kind!r}")
    object_id, path = _alloc_actor(root, title)
    today = date.today().isoformat()
    meta = {"id": object_id, "type": "actor", "title": title,
            "created": today, "updated": today, "status": "active", "kind": kind}
    path.write_text(frontmatter.dumps(meta, f"# {title}\n"), encoding="utf-8")
    return {"ok": True, "id": object_id, "kind": kind}


def _alloc_actor(root: Path, title: str) -> tuple[str, Path]:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "actor"
    folder = root / "context" / "actors"
    folder.mkdir(parents=True, exist_ok=True)
    object_id, n = f"actor-{slug}", 2
    while (folder / f"{object_id.removeprefix('actor-')}.md").exists():
        object_id, n = f"actor-{slug}-{n}", n + 1
    return object_id, folder / f"{object_id.removeprefix('actor-')}.md"


def snapshot(root: Path) -> dict:
    """Everything the page needs, except object bodies (loaded on open)."""
    tasks = _list(root, "task")
    contribs = _list(root, "contribution")
    inbox = list_inbox(root)
    runs = _runs(root)
    projects = _list(root, "project")
    by_project: dict[str, dict[str, int]] = {}
    for task in tasks:
        bucket = by_project.setdefault(task.get("project") or "", {s: 0 for s in cli.TASK_STATUSES})
        status = task.get("status", "to-do")
        bucket[status] = bucket.get(status, 0) + 1
    for project in projects:
        project["counts"] = by_project.get(project["id"], {s: 0 for s in cli.TASK_STATUSES})

    statuses = _prompt_status(root)
    factories = _factories(root, runs)
    for item in factories:
        for prompt in item["prompts"]:
            prompt["status"] = statuses.get((item["name"], prompt["version"]), "unindexed")

    attention = _attention(tasks, contribs, inbox)
    open_tasks = sum(1 for t in tasks if t.get("status") != "done")
    pending = sum(1 for r in runs if r["verdict"] == "pending")
    return {
        "today": date.today().isoformat(),
        "first_run": _needs_welcome(root),
        "deployment": _deployment_view(root),
        "model": _model_view(root),
        "factory": _factory_defaults(root),
        "actor": _current_actor(root),
        "actors": _list(root, "actor"),
        "accounts": _accounts(root),
        "counts": {
            "open_tasks": open_tasks,
            "attention": len(attention),
            "inbox": len(inbox),
            "pending_runs": pending,
        },
        "attention": attention,
        "projects": projects,
        "tasks": tasks,
        "documents": _list(root, "document"),
        "meetings": _list(root, "meeting"),
        "repos": _list(root, "repo"),
        "contributions": contribs,
        "inbox": inbox,
        "factories": factories,
        "runs": runs,
        "choices": {
            "task_status": list(cli.TASK_STATUSES),
            "contrib_state": list(cli.CONTRIB_STATES),
            "contrib_ci": list(cli.CONTRIB_CI),
            "contrib_review": list(cli.CONTRIB_REVIEW),
            "contrib_role": list(cli.CONTRIB_ROLES),
            "method": list(cli.CONTRIB_METHODS),
            "contrib_kind": list(cli.CONTRIB_KINDS),
            "project_status": list(PROJECT_STATUSES),
            "repo_kind": list(cli.REPO_KINDS),
            "repo_status": list(cli.REPO_STATUSES),
            "factory_trigger": ["on-demand", "watch"],
            "factory_reach": ["shadow", "draft-pr", "pr", "merge"],
            "factory_reach_install": ["shadow", "draft-pr", "pr"],
            "model_provider": _model_providers(),
        },
    }


def object_detail(root: Path, otype: str, ref: str) -> dict:
    if otype not in objects.TYPE_DIRS:
        raise UiError("unknown object type", 404)
    found = objects.find(root, otype, ref)
    if found is None:
        raise UiError(f"{otype} not found: {ref}", 404)
    path, meta, body = found
    return {
        "type": otype,
        "id": meta.get("id", path.stem),
        "title": meta.get("title", path.stem),
        "path": _rel(root, path),
        "meta": {k: v for k, v in meta.items() if k != "title"},
        "body": body,
    }


def read_inbox(root: Path, name: str) -> dict:
    if not name or name != Path(name).name or name.startswith(".") or name == "README.md":
        raise UiError("inbox file not found", 404)
    folder = (root / "inbox").resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.is_file():
        raise UiError("inbox file not found", 404)
    return {"name": path.name, "path": _rel(root, path),
            "body": path.read_text(encoding="utf-8")}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "item"


def _https_or_empty(value: str | None, label: str) -> str | None:
    value = (value or "").strip()
    if value and not (value.startswith("https://") or value.startswith("http://localhost")):
        raise UiError(f"{label} must be an https URL")
    return value or None


def _require_project(root: Path, project: str | None) -> str | None:
    project = (project or "").strip()
    if not project:
        return None
    found = objects.find(root, "project", project)
    if found is None:
        raise UiError(f"project not found: {project}")
    return found[1]["id"]


def _alloc(root: Path, otype: str, title: str) -> tuple[str, Path]:
    slug = _slugify(title)
    folder = root / "context" / objects.TYPE_DIRS[otype]
    folder.mkdir(parents=True, exist_ok=True)
    object_id, n = f"{otype}-{slug}", 2
    while (folder / f"{object_id.removeprefix(otype + '-')}.md").exists():
        object_id, n = f"{otype}-{slug}-{n}", n + 1
    return object_id, folder / f"{object_id.removeprefix(otype + '-')}.md"


def _note_body(title: str, body: str) -> str:
    text = body if body is not None else ""
    if len(text) > MAX_NOTE:
        raise UiError("note is too long")
    text = text.strip()
    if not text:
        text = f"# {title}"
    return text if text.endswith("\n") else text + "\n"


def create_object(root: Path, payload: dict) -> dict:
    """Write a new project, document, meeting, or repo. Never a contribution."""
    otype = payload.get("type") or ""
    title = (payload.get("title") or "").strip()
    if otype not in ("project", "document", "meeting", "repo"):
        raise UiError("can create a project, document, meeting, or repo")
    if not title or len(title) > 200:
        raise UiError("needs a title of at most 200 characters")
    if otype == "repo":
        _call(cli.cmd_repo_add, root, title,
              _https_or_empty(payload.get("url"), "url"),
              payload.get("kind") or "oss",
              payload.get("status") or "active",
              None, None,
              (payload.get("notes") or "").strip() or None)
        return {"ok": True, "type": "repo"}
    status = None
    project_id = None
    if otype == "project":
        status = payload.get("status") or "active"
        if status not in PROJECT_STATUSES:
            raise UiError(f"invalid status {status!r}")
    else:
        project_id = _require_project(root, payload.get("project"))
    object_id, path = _alloc(root, otype, title)
    today = date.today().isoformat()
    meta = {"id": object_id, "type": otype, "title": title,
            "created": today, "updated": today}
    if status:
        meta["status"] = status
    if project_id:
        meta["project"] = project_id
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, _note_body(title, payload.get("body") or "")),
                    encoding="utf-8")
    return {"ok": True, "id": object_id, "type": otype}


def save_body(root: Path, otype: str, ref: str, body: str) -> dict:
    """Replace the body of a private note. Contribution files stay read-only."""
    if otype not in EDITABLE:
        raise UiError("only projects, tasks, documents, and meetings can be edited here")
    if not ref:
        raise UiError("id is required")
    if body is None:
        raise UiError("body is required")
    if len(body) > MAX_NOTE:
        raise UiError("note is too long")
    found = objects.find(root, otype, ref)
    if found is None:
        raise UiError(f"{otype} not found: {ref}", 404)
    path, meta, _old = found
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    text = body if body.endswith("\n") or body == "" else body + "\n"
    path.write_text(frontmatter.dumps(meta, text), encoding="utf-8")
    if otype == "task" and db.db_path(root).exists():
        conn = db.connect(root)
        try:
            conn.execute("UPDATE tasks SET updated = ? WHERE id = ?",
                         (meta["updated"], meta["id"]))
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": meta.get("id"), "type": otype}


def set_title(root: Path, otype: str, ref: str, title: str) -> dict:
    """Rename a private object. The id stays put."""
    if otype not in EDITABLE:
        raise UiError("only projects, tasks, documents, and meetings can be renamed here")
    title = (title or "").strip()
    if not title or len(title) > 200:
        raise UiError("needs a title of at most 200 characters")
    found = objects.find(root, otype, ref or "")
    if found is None:
        raise UiError(f"{otype} not found: {ref}", 404)
    path, meta, body = found
    meta["title"] = title
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    if otype == "task" and db.db_path(root).exists():
        conn = db.connect(root)
        try:
            conn.execute("UPDATE tasks SET title = ?, updated = ? WHERE id = ?",
                         (title, meta["updated"], meta["id"]))
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": meta.get("id"), "title": title}


def _spec_body(title: str, description: str, criteria: str) -> str:
    parts = [f"# {title}", ""]
    if description.strip():
        parts += [description.strip(), ""]
    items = []
    for raw in criteria.splitlines():
        item = raw.strip().removeprefix("- ").strip()
        if not item:
            continue
        if item.startswith("[ ] ") or item.startswith("[x] ") or item.startswith("[X] "):
            items.append(f"- {item}")
        else:
            items.append(f"- [ ] {item}")
    if items:
        parts += ["## Acceptance criteria", "", *items]
    return "\n".join(parts).rstrip() + "\n"


def create_contribution(root: Path, payload: dict) -> dict:
    """Add a local public issue or PR. Does not post it to GitHub."""
    title = (payload.get("title") or "").strip()
    repo = (payload.get("repo") or "").strip()
    if not title or not repo:
        raise UiError("a contribution needs a title and a repo")
    try:
        number = int(payload.get("number"))
    except (TypeError, ValueError) as exc:
        raise UiError("number must be a positive integer") from exc
    if number < 1:
        raise UiError("number must be a positive integer")
    kind = payload.get("kind") or "issue"
    method = payload.get("method") or "spec-kit"
    role = payload.get("role") or "author"
    _call(cli.cmd_contribution_add, root, title, repo, kind, number, None,
          role, "open", "none", "none", method)
    found_repo = objects.find(root, "repo", repo)
    if found_repo is None:
        raise UiError(f"repo not found: {repo}")
    ref = f"contribution-{found_repo[1]['id'].removeprefix('repo-')}-{kind}-{number}"
    description = payload.get("description") or ""
    criteria = payload.get("criteria") or ""
    if description.strip() or criteria.strip():
        found = objects.find(root, "contribution", ref)
        if found is None:
            raise UiError("contribution was added but could not be found")
        path, meta, _body = found
        if criteria.strip():
            tags = meta.get("tags") if isinstance(meta.get("tags"), list) else []
            if "feature-spec" not in tags:
                tags.append("feature-spec")
            meta["tags"] = tags
        meta["updated"] = date.today().isoformat()
        from ctx.actors import stamp
        stamp(root, meta)
        path.write_text(frontmatter.dumps(meta, _spec_body(title, description, criteria)),
                        encoding="utf-8")
        if db.db_path(root).exists():
            conn = db.connect(root)
            try:
                db.index_contribution(conn, root, path, meta, meta["updated"])
                conn.commit()
            finally:
                conn.close()
    return {"ok": True, "id": ref, "type": "contribution"}


def save_public_body(root: Path, ref: str, body: str) -> dict:
    """Edit a contribution body. It is public GitHub-cache data, not a private note."""
    if not ref:
        raise UiError("id is required")
    if body is None:
        raise UiError("body is required")
    if len(body) > MAX_NOTE:
        raise UiError("note is too long")
    found = objects.find(root, "contribution", ref)
    if found is None:
        raise UiError(f"contribution not found: {ref}", 404)
    path, meta, _old = found
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    text = body if body.endswith("\n") or body == "" else body + "\n"
    path.write_text(frontmatter.dumps(meta, text), encoding="utf-8")
    if db.db_path(root).exists():
        conn = db.connect(root)
        try:
            db.index_contribution(conn, root, path, meta, meta["updated"])
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": meta.get("id")}


def set_repo(root: Path, repo_id: str, payload: dict) -> dict:
    found = objects.find(root, "repo", repo_id or "")
    if found is None:
        raise UiError(f"repo not found: {repo_id}", 404)
    path, meta, body = found
    changed = False
    if payload.get("status"):
        if payload["status"] not in cli.REPO_STATUSES:
            raise UiError(f"invalid status {payload['status']!r}")
        meta["status"] = payload["status"]
        changed = True
    if payload.get("kind"):
        if payload["kind"] not in cli.REPO_KINDS:
            raise UiError(f"invalid kind {payload['kind']!r}")
        meta["kind"] = payload["kind"]
        changed = True
    if payload.get("trigger"):
        from ctx.autonomy import TRIGGERS
        if payload["trigger"] not in TRIGGERS:
            raise UiError(f"invalid trigger {payload['trigger']!r}")
        meta["trigger"] = payload["trigger"]
        changed = True
    if payload.get("reach"):
        from ctx.autonomy import REACHES
        if payload["reach"] not in REACHES:
            raise UiError(f"invalid reach {payload['reach']!r}")
        meta["reach"] = payload["reach"]
        changed = True
    if "notes" in payload:
        notes = (payload.get("notes") or "").strip()
        if len(notes) > 400:
            raise UiError("notes are too long")
        if notes:
            meta["notes"] = notes
        else:
            meta.pop("notes", None)
        changed = True
    if "url" in payload:
        url = _https_or_empty(payload.get("url"), "url")
        if url:
            meta["url"] = url
        else:
            meta.pop("url", None)
        changed = True
    if not changed:
        raise UiError("nothing to set")
    today = date.today().isoformat()
    meta["updated"] = today
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    if db.db_path(root).exists():
        conn = db.connect(root)
        try:
            db.index_repo(conn, root, path, meta, today)
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": meta.get("id")}


def set_project_status(root: Path, project_id: str, status: str) -> dict:
    if status not in PROJECT_STATUSES:
        raise UiError(f"invalid status {status!r}")
    found = objects.find(root, "project", project_id or "")
    if found is None:
        raise UiError(f"project not found: {project_id}", 404)
    path, meta, body = found
    meta["status"] = status
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"ok": True, "id": meta["id"], "status": status}


def _inbox_file(root: Path, name: str) -> Path:
    if not name or name != Path(name).name or name.startswith(".") or name == "README.md":
        raise UiError("inbox file not found", 404)
    folder = (root / "inbox").resolve()
    path = (folder / name).resolve()
    if path.parent != folder or not path.is_file():
        raise UiError("inbox file not found", 404)
    return path


def delete_inbox(root: Path, name: str) -> dict:
    _inbox_file(root, name).unlink()
    return {"ok": True}


def _heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _strip_capture_footer(body: str) -> str:
    return re.sub(r"\n*Captured \d{4}-\d{2}-\d{2} from the local cockpit\..*\Z",
                  "", body, flags=re.S).strip()


def triage_inbox(root: Path, name: str, otype: str, project: str | None,
                 title: str | None) -> dict:
    """File an inbox note into context, then remove the inbox copy."""
    if otype not in ("document", "meeting", "task"):
        raise UiError("file an inbox note as a document, meeting, or task — never a contribution")
    item = read_inbox(root, name)
    filed_title = (title or "").strip() or _heading(item["body"]) or Path(name).stem
    body = _strip_capture_footer(item["body"])
    if otype == "task":
        if not (project or "").strip():
            raise UiError("a task needs a project")
        add_task(root, filed_title, project, "to-do")
        matches = [(path, meta) for path, meta, _body in objects.iter_objects(root, "task")
                   if meta.get("title") == filed_title]
        if not matches:
            raise UiError("task was added but could not be found to attach the note")
        path, meta = max(matches, key=lambda item: item[0].stat().st_mtime)
        meta["updated"] = date.today().isoformat()
        from ctx.actors import stamp
        stamp(root, meta)
        path.write_text(frontmatter.dumps(meta, _note_body(filed_title, body)), encoding="utf-8")
        result = {"ok": True, "id": meta["id"], "type": "task"}
    else:
        result = create_object(root, {"type": otype, "title": filed_title,
                                       "project": project, "body": body})
    _inbox_file(root, name).unlink()
    return result


def sync_github(root: Path, offline: bool = False) -> dict:
    """Read-only GitHub refresh, or an offline re-index. Never writes remotely."""
    _call(cli.cmd_sync_github, root, "@me", 30, bool(offline))
    return {"ok": True, "offline": bool(offline)}


def capture(root: Path, title: str, body: str) -> dict:
    title = (title or "").strip()
    body = (body or "").strip()
    if not title:
        raise UiError("capture needs a title")
    if len(title) > 200 or len(body) > 20_000:
        raise UiError("capture is too long")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "note"
    today = date.today().isoformat()
    folder = root / "inbox"
    folder.mkdir(exist_ok=True)
    path = folder / f"{today}-{slug}.md"
    n = 2
    while path.exists():
        path = folder / f"{today}-{slug}-{n}.md"
        n += 1
    text = (f"# {title}\n\n{body}\n\n"
            f"Captured {today} from the local cockpit. "
            "Triage into context/ — do not leave this here.\n")
    path.write_text(text, encoding="utf-8")
    return {"name": path.name, "path": _rel(root, path)}


def _call(fn, *args, **kwargs) -> None:
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn(*args, **kwargs)
    except SystemExit as exc:
        raise UiError(str(exc) or "request rejected") from exc


def add_task(root: Path, title: str, project: str, status: str = "to-do") -> dict:
    if not (title or "").strip() or not (project or "").strip():
        raise UiError("a task needs a title and a project")
    _call(cli.cmd_task_add, root, title.strip(), project.strip(), status or "to-do")
    return {"ok": True}


def set_task_status(root: Path, task_id: str, status: str) -> dict:
    if not task_id or not status:
        raise UiError("a status change needs an id and a status")
    _call(cli.cmd_task_set, root, task_id, status)
    return {"ok": True}


def set_contribution(root: Path, payload: dict) -> dict:
    ref = payload.get("id")
    if not ref:
        raise UiError("contribution id is required")
    fields = ("state", "ci", "review", "role", "method")
    updates = {key: payload[key] for key in fields if payload.get(key)}
    if not updates:
        raise UiError("nothing to set")
    _call(cli.cmd_contribution_set, root, ref,
          updates.get("state"), updates.get("ci"), updates.get("review"),
          updates.get("role"), updates.get("method"))
    return {"ok": True}


def _public_run(info: dict) -> dict:
    """Drop the assembled prompt — the page only needs where the draft landed."""
    return {
        "ok": True,
        "run_id": info.get("run_id"),
        "run_dir": info.get("run_dir"),
        "prompt_version": info.get("prompt_version"),
        "mode": "shadow",
        "flags": info.get("flags") or [],
        "generated": bool(info.get("generated")),
        "output_path": info.get("output_path") or "",
        "reach": info.get("reach") or "",
        "ceiling": info.get("ceiling") or "",
        "remote": info.get("remote") or "",
    }


_REVIEW_VERDICTS = ("approved", "rejected")


def set_run_verdict(root: Path, run_id: object, verdict: str,
                    output: str | None = None) -> dict:
    """Record a human review on an existing run. Does not create a new row."""
    if verdict not in _REVIEW_VERDICTS:
        raise UiError("verdict must be approved or rejected")
    try:
        rid = int(run_id)
    except (TypeError, ValueError) as exc:
        raise UiError("run id must be a number") from exc
    note = (output or "").strip()
    if len(note) > 4000:
        raise UiError("review note is too long")
    if not db.db_path(root).exists():
        raise UiError("state.db not found — run stead init first", 404)
    conn = db.connect(root)
    try:
        if note:
            cur = conn.execute("UPDATE runs SET verdict = ?, output = ? WHERE id = ?",
                               (verdict, note, rid))
        else:
            cur = conn.execute("UPDATE runs SET verdict = ? WHERE id = ?", (verdict, rid))
        conn.commit()
        if cur.rowcount != 1:
            raise UiError(f"run not found: {rid}", 404)
    finally:
        conn.close()
    return {"ok": True, "id": rid, "verdict": verdict}


def shadow_run(root: Path, payload: dict) -> dict:
    if payload.get("live") or payload.get("mode") == "live":
        raise UiError("the cockpit only assembles shadow runs — no remote writes")
    name = payload.get("factory") or ""
    try:
        if name == factory.FEATURE_BUILDER_FACTORY:
            if not payload.get("contribution"):
                raise UiError("feature-builder needs a contribution")
            info = factory.assemble_feature_build(
                root, payload["contribution"], mode="shadow", reach=payload.get("reach") or None)
        elif name == factory.DIGEST_FACTORY:
            info = factory.assemble_digest(root, mode="shadow")
        else:
            if not payload.get("project"):
                raise UiError(f"{name or 'this factory'} needs a project")
            info = factory.assemble(root, name, payload["project"], mode="shadow")
    except SystemExit as exc:
        raise UiError(str(exc) or "could not assemble a shadow run") from exc
    if payload.get("generate"):
        from ctx.models import ModelError, draft
        try:
            text = draft(root, info["assembled_prompt"])
            info = factory.write_output(root, info, text, source="model")
        except ModelError as exc:
            raise UiError(str(exc)) from exc
    return _public_run(info)


def ensure_index(root: Path) -> None:
    """Build state.db only when it is missing. Never rebuild an existing index."""
    if not db.db_path(root).exists():
        db.init_db(root)


def dispatch(root: Path, method: str, path: str, query: dict,
             payload: dict | None, *, token_ok: bool) -> tuple[int, bytes, str]:
    """Handle one cockpit request. Returns (status, body, content-type)."""
    try:
        if method == "GET" and path == "/":
            page = PAGE_PATH.read_text(encoding="utf-8")
            return 200, page.encode("utf-8"), "text/html; charset=utf-8"
        if method == "GET" and path == "/api/snapshot":
            return 200, _json(snapshot(root)), "application/json; charset=utf-8"
        if method == "GET" and path == "/api/object":
            detail = object_detail(root, query.get("type", ""), query.get("id", ""))
            return 200, _json(detail), "application/json; charset=utf-8"
        if method == "GET" and path == "/api/inbox":
            return 200, _json(read_inbox(root, query.get("name", ""))), "application/json; charset=utf-8"
        if method == "GET" and path == "/favicon.ico":
            return 204, b"", "image/x-icon"
        if method != "POST":
            raise UiError("not found", 404)
        if not token_ok:
            raise UiError("missing or invalid token", 403)
        payload = payload or {}
        if path == "/api/task":
            result = add_task(root, payload.get("title", ""), payload.get("project", ""),
                              payload.get("status") or "to-do")
        elif path == "/api/task/status":
            result = set_task_status(root, payload.get("id", ""), payload.get("status", ""))
        elif path == "/api/contribution":
            result = set_contribution(root, payload)
        elif path == "/api/contribution/add":
            result = create_contribution(root, payload)
        elif path == "/api/contribution/body":
            if "body" not in payload:
                raise UiError("body is required")
            result = save_public_body(root, payload.get("id") or "", payload.get("body"))
        elif path == "/api/repo":
            result = set_repo(root, payload.get("id") or "", payload)
        elif path == "/api/title":
            result = set_title(root, payload.get("type") or "", payload.get("id") or "",
                               payload.get("title") or "")
        elif path == "/api/capture":
            result = capture(root, payload.get("title", ""), payload.get("body", ""))
        elif path == "/api/factory/run":
            result = shadow_run(root, payload)
        elif path == "/api/run/verdict":
            result = set_run_verdict(root, payload.get("id"), payload.get("verdict") or "",
                                     payload.get("output"))
        elif path == "/api/welcome":
            from ctx.onboard import OnboardError, welcome
            try:
                result = welcome(root, payload.get("title") or "", payload.get("url"))
            except OnboardError as exc:
                raise UiError(str(exc)) from exc
            mode = payload.get("deployment") or "single"
            if mode not in ("single", "multi"):
                raise UiError("deployment must be single or multi")
            from ctx.config import ConfigError, choose
            try:
                chosen = choose(root, mode)
            except ConfigError as exc:
                raise UiError(str(exc)) from exc
            result["deployment"] = chosen["deployment"]
            if chosen.get("access_token"):
                result["access_token"] = chosen["access_token"]
                result["next"] = (
                    "Shared server chosen. Start it with Docker, not by opening "
                    "this computer to the network: set STEAD_ACCESS_TOKEN to the "
                    "token below, then docker compose up --build"
                )
        elif path == "/api/onboard":
            from ctx.onboard import OnboardError, onboard
            try:
                result = onboard(
                    root, payload.get("title") or "",
                    kind=payload.get("kind") or "own",
                    url=payload.get("url"),
                    code_path=payload.get("path"),
                    method=payload.get("method") or "spec-kit",
                    integration=payload.get("integration") or "claude",
                    run_specify_init=payload.get("run_specify", True) is not False,
                )
            except OnboardError as exc:
                raise UiError(str(exc)) from exc
        elif path == "/api/object":
            result = create_object(root, payload)
        elif path == "/api/object/body":
            if "body" not in payload:
                raise UiError("body is required")
            result = save_body(root, payload.get("type") or "", payload.get("id") or "",
                               payload.get("body"))
        elif path == "/api/project/status":
            result = set_project_status(root, payload.get("id") or "", payload.get("status") or "")
        elif path == "/api/inbox/triage":
            result = triage_inbox(root, payload.get("name") or "", payload.get("type") or "",
                                  payload.get("project"), payload.get("title"))
        elif path == "/api/inbox/delete":
            result = delete_inbox(root, payload.get("name") or "")
        elif path == "/api/sync":
            result = sync_github(root, bool(payload.get("offline")))
        elif path == "/api/factory/defaults":
            from ctx.autonomy import AutonomyError, set_defaults
            try:
                result = set_defaults(
                    root,
                    trigger=payload.get("trigger") or None,
                    reach=payload.get("reach") or None,
                )
                result["ok"] = True
            except AutonomyError as exc:
                raise UiError(str(exc)) from exc
        elif path == "/api/model":
            from ctx.models import ModelError, set_model
            try:
                result = set_model(
                    root,
                    provider=payload.get("provider") or "",
                    name=payload.get("name") or "",
                    base_url=payload.get("base_url") or "",
                    api_key=payload.get("api_key"),
                )
                result["ok"] = True
            except ModelError as exc:
                raise UiError(str(exc)) from exc
        elif path == "/api/settings":
            from ctx.config import ConfigError, choose, rotate_token
            try:
                if payload.get("rotate"):
                    token = rotate_token(root)
                    result = {"ok": True, "access_token": token}
                else:
                    result = choose(root, payload.get("deployment") or "single")
                    result["ok"] = True
            except ConfigError as exc:
                raise UiError(str(exc)) from exc
        elif path == "/api/actor/use":
            from ctx.actors import ActorError, use
            try:
                result = {"ok": True, "actor": use(root, payload.get("id") or "")}
            except ActorError as exc:
                raise UiError(str(exc)) from exc
        elif path == "/api/account":
            from ctx.accounts import AccountError, add
            try:
                shown = add(root, payload.get("name") or "", payload.get("actor") or "")
            except AccountError as exc:
                raise UiError(str(exc)) from exc
            result = {"ok": True, "name": (payload.get("name") or "").strip().lower(),
                      "password": shown}
        elif path == "/api/actor":
            result = add_actor(root, payload.get("title") or "", payload.get("kind") or "human")
        else:
            raise UiError("not found", 404)
        return 200, _json(result), "application/json; charset=utf-8"
    except UiError as exc:
        return exc.status, _json({"error": str(exc)}), "application/json; charset=utf-8"


def _json(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


class CockpitHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def _host_ok(self) -> bool:
        if getattr(self.server, "deployment", "single") == "multi":
            return True
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]")
        return host in LOOPBACK

    def _cookie(self, wanted: str) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == wanted:
                return value
        return ""

    def _people(self) -> int:
        from ctx.accounts import AccountError, count
        try:
            return count(self.server.root)
        except AccountError:
            return 0

    def _session_actor(self) -> str:
        token = self._cookie("stead_session")
        if not token:
            return ""
        with self.server.sessions_lock:
            return self.server.sessions.get(token, "")

    def _access_ok(self) -> bool:
        if getattr(self.server, "deployment", "single") != "multi":
            return True
        if self._session_actor():
            return True
        if self._people() > 0:
            return False
        expected = getattr(self.server, "access_token", "") or ""
        presented = self.headers.get("X-Stead-Access", "") or self._cookie("stead_access")
        if not expected or not presented:
            return False
        return secrets.compare_digest(presented, expected)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _reject(self, status: int, message: str) -> None:
        self._send(status, _json({"error": message}), "application/json; charset=utf-8")

    def _query(self) -> dict[str, str]:
        parsed = urlparse(self.path)
        raw = parse_qs(parsed.query)
        return {key: values[0] for key, values in raw.items() if values}

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length > MAX_BODY:
            raise UiError("request is too large")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UiError("expected a JSON object") from exc
        if not isinstance(payload, dict):
            raise UiError("expected a JSON object")
        return payload

    def _handle(self, method: str) -> None:
        if not self._host_ok():
            self._reject(403, "cockpit only answers on loopback")
            return
        parsed = urlparse(self.path)
        if not self._access_ok():
            if method == "GET" and parsed.path == "/":
                self._send(200, _gate_page(self._people() > 0), "text/html; charset=utf-8")
                return
            if method == "POST" and parsed.path == "/api/session":
                self._open_session()
                return
            self._reject(401, "sign in required")
            return
        from ctx.actors import bind, unbind
        bound = bind(self._session_actor())
        try:
            token_ok = secrets.compare_digest(
                self.headers.get("X-Ctx-Token", ""), self.server.token)
            try:
                payload = self._read_json() if method == "POST" else None
            except UiError as exc:
                self._reject(exc.status, str(exc))
                return
            status, body, content_type = dispatch(
                self.server.root, method, parsed.path, self._query(), payload, token_ok=token_ok)
            if parsed.path == "/" and status == 200:
                body = body.replace(b"__CTX_TOKEN__", self.server.token.encode("ascii"), 1)
            self._send(status, body, content_type)
        finally:
            unbind(bound)

    def _open_session(self) -> None:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        fields = self._session_fields(raw, ctype)
        if self._people() > 0:
            from ctx.accounts import verify
            person = verify(self.server.root, fields.get("name") or "", fields.get("password") or "")
            if not person or not person.get("actor"):
                self._reject(401, "name or password is wrong")
                return
            session = secrets.token_urlsafe(24)
            with self.server.sessions_lock:
                self.server.sessions[session] = person["actor"]
            cookie = "stead_session=%s; HttpOnly; SameSite=Lax; Path=/" % session
            self._send_session(cookie, ctype)
            return
        expected = getattr(self.server, "access_token", "") or ""
        token = fields.get("token") or ""
        if not expected or not token or not secrets.compare_digest(token, expected):
            self._reject(401, "access token required")
            return
        cookie = "stead_access=%s; HttpOnly; SameSite=Lax; Path=/" % token
        self._send_session(cookie, ctype)

    def _session_fields(self, raw: bytes, ctype: str) -> dict:
        if "application/json" in ctype:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                return {}
            return payload if isinstance(payload, dict) else {}
        from urllib.parse import parse_qs
        parsed = parse_qs(raw.decode("utf-8", errors="replace"))
        return {key: values[0] for key, values in parsed.items() if values}

    def _send_session(self, cookie: str, ctype: str) -> None:
        if "application/json" not in ctype:
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie", cookie)
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")


class CockpitServer(ThreadingHTTPServer):
    def __init__(self, root: Path, address: tuple[str, int], token: str):
        self.root = root
        self.token = token
        super().__init__(address, CockpitHandler)


def make_server(root: Path, host: str | None = None, port: int | None = None,
                deploy: bool = False) -> CockpitServer:
    from ctx.config import ConfigError, effective
    try:
        cfg = effective(root, deploy=deploy)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    bind = host or cfg["bind"]
    listen_port = port if port is not None else cfg["port"]
    if cfg["deployment"] == "single" and bind not in LOOPBACK:
        raise SystemExit(
            f"single-user mode only binds to loopback ({', '.join(LOOPBACK)}). "
            "Choose Shared server and run with --deploy, or use Docker.")
    from ctx.accounts import count
    if cfg["deployment"] == "multi" and not cfg["access_token"] and count(root) < 1:
        raise SystemExit(
            "multi-user mode needs a person account, or an access token until "
            "the first account exists")
    ensure_index(root)
    httpd = CockpitServer(root, (bind, listen_port), secrets.token_urlsafe(24))
    httpd.deployment = cfg["deployment"]
    httpd.access_token = cfg["access_token"]
    httpd.sessions = {}
    httpd.sessions_lock = threading.Lock()
    return httpd


def serve(root: Path, host: str | None = None, port: int | None = None,
          open_browser: bool = True, deploy: bool = False) -> int:
    httpd = make_server(root, host, port, deploy=deploy)
    bound_host, bound_port = httpd.server_address[:2]
    shown = "127.0.0.1" if bound_host in ("0.0.0.0", "::") else bound_host
    url = f"http://{shown}:{bound_port}/"
    print(f"Stead\n  {url}")
    if httpd.deployment == "multi":
        print("  shared server · sign in required · markdown is the source of truth · Ctrl+C to stop")
    else:
        print("  this computer · loopback only · markdown is the source of truth · Ctrl+C to stop")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0
