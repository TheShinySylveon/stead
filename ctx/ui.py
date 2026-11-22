"""Local cockpit: a loopback web UI over the context system.

Stdlib only. Binds to 127.0.0.1. Markdown stays the source of truth; writes
go through the same CLI handlers as the terminal. No LLM, no network beyond
the loopback socket, no remote writes. Factory runs from the UI are
shadow-only.
"""

from __future__ import annotations

import contextlib
import email
import io
import json
import os
import re
import secrets
import sys
import threading
import webbrowser
from email import policy
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
    factory.MAINTENANCE_FACTORY: "none",
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
                "ci", "review", "method", "number", "trigger", "reach",
                "code_path", "default_branch"):
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
    """One row per object. Several reasons become several labels."""
    rows: dict[tuple[str, str], dict] = {}
    order: list[tuple[str, str]] = []

    def add(otype: str, item: dict, tone: str, label: str) -> None:
        key = (otype, item.get("id") or item.get("name") or "")
        if key not in rows:
            rows[key] = {
                "tone": tone, "label": label,
                "title": item.get("title") or item.get("name") or "",
                "type": otype, "id": key[1], "labels": [(label, tone)],
            }
            order.append(key)
            return
        rows[key]["labels"].append((label, tone))
        if rows[key]["tone"] != "fail":
            rows[key]["tone"] = tone
            rows[key]["label"] = label

    for task in tasks:
        if task.get("status") == "doing":
            add("task", task, "doing", "In progress")
        elif task.get("status") == "blocked":
            add("task", task, "blocked", "Blocked")
    for contrib in contribs:
        if contrib.get("review") == "requested":
            add("contribution", contrib, "review", "Review requested")
        if contrib.get("ci") == "fail":
            add("contribution", contrib, "fail", "CI failing")
    for item in inbox:
        add("inbox", item, "inbox", "Needs triage")
    return [rows[key] for key in order]


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
        _ensure_note_column(conn)
        rows = conn.execute(
            "SELECT id, factory, task_ref, project, prompt_version, mode, verdict, "
            "created, bundle_path, note FROM runs ORDER BY id DESC LIMIT 200"
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
        "note": r["note"] or "",
    } for r in rows]


def _ensure_note_column(conn) -> None:
    """Older state.db files lack runs.note. Add it instead of demanding init."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(runs)")}
    if "note" not in columns:
        conn.execute("ALTER TABLE runs ADD COLUMN note TEXT")
        conn.commit()


def run_detail(root: Path, run_id: object) -> dict:
    """One run, with the draft and the local bundle text the page may show."""
    if not db.db_path(root).exists():
        raise UiError("state.db not found — run stead init first", 404)
    try:
        rid = int(run_id)
    except (TypeError, ValueError) as exc:
        raise UiError("run id must be a number") from exc
    conn = db.connect(root)
    try:
        _ensure_note_column(conn)
        row = conn.execute(
            "SELECT id, factory, task_ref, project, prompt_version, mode, verdict, "
            "created, bundle_path, output, note FROM runs WHERE id = ?", (rid,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise UiError(f"run not found: {rid}", 404)
    detail = {key: row[key] for key in row.keys()}
    folder = root / (row["bundle_path"] or "")
    for label, name in (("bundle", "bundle.md"), ("prompt", "prompt.md"),
                        ("draft", "output.md")):
        path = folder / name
        try:
            detail[label] = path.read_text(encoding="utf-8")[:MAX_NOTE] if path.is_file() else ""
        except OSError:
            detail[label] = ""
    if not detail.get("draft"):
        detail["draft"] = row["output"] or ""
    return detail


def _needs_welcome(root: Path) -> bool:
    from ctx.onboard import needs_welcome
    return needs_welcome(root)


def _model_providers() -> list[dict]:
    from ctx.models import PROVIDER_LABELS, PROVIDERS
    return [{"id": key, "label": PROVIDER_LABELS[key]} for key in PROVIDERS]


def _hook_set(root: Path) -> bool:
    from ctx.config import hook_token
    return bool(hook_token(root))


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


def _deployment_view(root: Path, port: int | None = None) -> dict:
    from ctx.config import ConfigError, public_view
    try:
        view = public_view(root)
    except ConfigError:
        view = {"deployment": "single", "bind": "127.0.0.1", "port": 8765, "token_set": False}
    if port:
        view["port"] = port
    return view


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


def snapshot(root: Path, port: int | None = None, session_actor: str = "") -> dict:
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
        "version": _version(),
        "first_run": _needs_welcome(root),
        "deployment": _deployment_view(root, port),
        "model": _model_view(root),
        "factory": _factory_defaults(root),
        "actor": _current_actor(root),
        "signed_in": session_actor,
        "actors": _list(root, "actor"),
        "accounts": _accounts(root),
        "hook": {"set": _hook_set(root)},
        "schedule": {"project": "", "platform": "windows" if sys.platform == "win32" else sys.platform},
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


def _version() -> str:
    from ctx import __version__
    return __version__


def object_detail(root: Path, otype: str, ref: str) -> dict:
    if otype not in objects.TYPE_DIRS:
        raise UiError("unknown object type", 404)
    found = objects.find(root, otype, ref)
    if found is None:
        raise UiError(f"{otype} not found: {ref}", 404)
    path, meta, body = found
    detail = {
        "type": otype,
        "id": meta.get("id", path.stem),
        "title": meta.get("title", path.stem),
        "path": _rel(root, path),
        "meta": {k: v for k, v in meta.items() if k != "title"},
        "body": body,
    }
    if otype == "project":
        detail["rollup"] = _project_rollup(root, meta.get("id", path.stem))
    return detail


def _project_rollup(root: Path, project_id: str) -> dict:
    counts = {status: 0 for status in cli.TASK_STATUSES}
    for _path, meta, _body in objects.iter_objects(root, "task"):
        if meta.get("project") == project_id:
            status = meta.get("status", "to-do")
            counts[status] = counts.get(status, 0) + 1
    docs = sum(1 for _p, m, _b in objects.iter_objects(root, "document")
               if m.get("project") == project_id)
    meetings = sum(1 for _p, m, _b in objects.iter_objects(root, "meeting")
                   if m.get("project") == project_id)
    runs = []
    if db.db_path(root).exists():
        conn = db.connect(root)
        try:
            runs = [dict(row) for row in conn.execute(
                "SELECT id, factory, prompt_version, mode, verdict, created FROM runs "
                "WHERE project = ? ORDER BY id DESC LIMIT 5", (project_id,)).fetchall()]
        finally:
            conn.close()
    return {"counts": counts, "documents": docs, "meetings": meetings, "runs": runs}


def delete_object(root: Path, otype: str, ref: str, force: bool = False) -> dict:
    """Remove one object file. Git history is the audit trail."""
    if otype not in objects.TYPE_DIRS:
        raise UiError("unknown object type", 404)
    if otype == "contribution":
        reason = "a cached contribution is GitHub-derived. Refresh the cache instead."
        raise UiError(reason)
    found = objects.find(root, otype, ref)
    if found is None:
        raise UiError(f"{otype} not found: {ref}", 404)
    path, meta, _body = found
    object_id = meta.get("id", path.stem)
    if not force and otype == "project":
        linked = [m.get("id") for t in ("task", "document", "meeting")
                  for _p, m, _b in objects.iter_objects(root, t)
                  if m.get("project") == object_id]
        if linked:
            raise UiError(
                f"{object_id} still has {len(linked)} linked object(s). "
                "Move or delete them first.")
    if not force and otype == "repo":
        linked = [m.get("id") for _p, m, _b in objects.iter_objects(root, "contribution")
                  if m.get("repo") == object_id]
        if linked:
            raise UiError(
                f"{object_id} still has {len(linked)} cached contribution(s). "
                "Delete those first, or use force.")
    path.unlink()
    if db.db_path(root).exists():
        table = {"task": "tasks", "repo": "repos"}.get(otype)
        if table:
            conn = db.connect(root)
            try:
                conn.execute(f"DELETE FROM {table} WHERE id = ?", (object_id,))
                conn.commit()
            finally:
                conn.close()
    return {"ok": True, "type": otype, "id": object_id}


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
    if shared_server(root) and (payload.get("criteria") or "").strip():
        raise UiError(
            "on a shared server, authoring a build spec is read-only. Write and "
            "approve specs on the machine that runs builds.")
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
    if shared_server(root):
        locked = {"trigger", "reach", "code_path", "default_branch", "checks",
                  "checks_isolation", "checks_image", "protected_paths",
                  "trust_checks", "allow_test_edits", "allow_ci_edits",
                  "allow_protected", "merge_without_required_checks"}
        touched = locked.intersection(payload)
        if touched:
            raise UiError(
                "on a shared server these repo fields are read-only: "
                + ", ".join(sorted(touched))
                + ". Edit them on the machine that runs builds.")
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
    if "code_path" in payload:
        code_path = (payload.get("code_path") or "").strip()
        if code_path:
            target = Path(code_path).expanduser()
            if not target.is_dir():
                raise UiError(f"code_path is not a directory: {code_path}")
            if target.resolve() == root.resolve():
                raise UiError("code_path must be the project checkout, not this Stead repo")
            meta["code_path"] = str(target)
        else:
            meta.pop("code_path", None)
        changed = True
    if "default_branch" in payload:
        branch = (payload.get("default_branch") or "").strip()
        if branch:
            if not re.match(r"^[A-Za-z0-9._/-]{1,120}$", branch):
                raise UiError("default branch must be a plain branch name")
            meta["default_branch"] = branch
        else:
            meta.pop("default_branch", None)
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


def file_run(root: Path, run_id: object, title: str | None = None) -> dict:
    from ctx.deliver import DeliveryError, file_run as deliver
    try:
        filed = deliver(root, run_id, title)
    except DeliveryError as exc:
        raise UiError(str(exc)) from exc
    return {"ok": True, "id": filed["id"], "path": _rel(root, filed["path"])}


def new_factory(root: Path, name: str, title: str) -> dict:
    from ctx.scaffold import ScaffoldError, scaffold
    try:
        folder = scaffold(root, name, title)
    except ScaffoldError as exc:
        raise UiError(str(exc)) from exc
    ensure_index(root)
    db.init_db(root)
    return {"ok": True, "name": folder.name, "path": _rel(root, folder)}


def watch_now(root: Path, build: bool = False) -> dict:
    """Watch from the cockpit. Local only: publish and merge stay CLI-only."""
    if build:
        require_local_execution(root)
    report = factory.watch_specs(root, build=build, publish=False, merge=False)
    return {"ok": True, **report}


def shared_server(root: Path) -> bool:
    """True when this process is the multi-user deployment."""
    from ctx import config
    if os.environ.get("STEAD_DEPLOYMENT", "").strip() == "multi":
        return True
    try:
        return config.load(root).get("deployment") == "multi"
    except config.ConfigError:
        return False


def require_local_execution(root: Path) -> None:
    """Refuse to run model-written code from a shared server.

    A build executes code on the host, and every account on a shared server is
    an admin. The cockpit is not the place for that.
    """
    if shared_server(root) and os.environ.get("STEAD_ALLOW_SERVER_BUILD", "").strip() != "1":
        raise UiError(
            "the cockpit does not run builds on a shared server: a build runs "
            "model-written code on the host, and every signed-in account is an "
            "admin. Run `python -m stead build` on the machine that owns the "
            "checkout.")


def wiki_view(root: Path, repo: str, page: str = "") -> dict:
    from ctx.wiki import WikiError, index, page as wiki_page
    try:
        return wiki_page(root, repo, page) if page else index(root, repo)
    except WikiError as exc:
        raise UiError(str(exc)) from exc


def wiki_action(root: Path, action: str, payload: dict) -> dict:
    from ctx import wiki, wiki_store
    try:
        if action == "move":
            repo = payload.get("repo") or ""
            path = payload.get("path") or ""
            siblings = wiki.siblings(root, repo, path)
            wiki_store.move(root, _repo_id(root, repo), siblings, path,
                            payload.get("direction") or "up")
            return {"ok": True}
        if action == "pin":
            repo = payload.get("repo") or ""
            wiki_store.set_pinned(root, _repo_id(root, repo), payload.get("path") or "",
                                  bool(payload.get("pinned")))
            return {"ok": True}
        if action == "request":
            repo = payload.get("repo") or ""
            found = objects.find(root, "repo", repo)
            if found is None:
                raise UiError(f"repo not found: {repo}")
            meta = found[1]
            created = wiki_store.create_request(
                root, meta.get("id"), meta.get("project") or "",
                payload.get("page") or "", payload.get("text") or "",
                payload.get("title"))
            return {"ok": True, **created}
        if action == "close_request":
            return {"ok": True, **wiki_store.close_request(root, payload.get("id") or "")}
    except (wiki.WikiError, wiki_store.WikiStoreError) as exc:
        raise UiError(str(exc)) from exc
    raise UiError("unknown wiki action", 404)


def _repo_id(root: Path, repo_ref: str) -> str:
    found = objects.find(root, "repo", repo_ref)
    if found is None:
        raise UiError(f"repo not found: {repo_ref}")
    return found[1].get("id", found[0].stem)


def approve_spec(root: Path, ref: str) -> dict:
    if shared_server(root):
        raise UiError(
            "on a shared server, approving a build spec is read-only. Approve it "
            "on the machine that runs builds.")
    from ctx.spec import SpecError, approve
    try:
        return {"ok": True, **approve(root, ref)}
    except SpecError as exc:
        raise UiError(str(exc)) from exc


def build_with_model(root: Path, contribution: str) -> dict:
    """Build locally from the cockpit. Publishing and merging stay CLI-only."""
    from ctx.agent import BuildError, build
    from ctx.models import ModelError
    require_local_execution(root)
    try:
        return build(root, contribution, publish=False, merge=False)
    except (BuildError, ModelError) as exc:
        raise UiError(str(exc)) from exc


def judge_eval(root: Path, factory_name: str, case_id: str, version: str = "") -> dict:
    """Judge the newest draft for one factory. Local result file only."""
    from ctx.models import ModelError, judge
    if not db.db_path(root).exists():
        raise UiError("state.db not found — run stead init first", 404)
    conn = db.connect(root)
    try:
        _ensure_note_column(conn)
        row = conn.execute(
            "SELECT id, output, prompt_version FROM runs "
            "WHERE factory = ? AND output IS NOT NULL AND TRIM(output) != '' "
            "ORDER BY id DESC LIMIT 1", (factory_name,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise UiError("no draft to judge. Run the factory with --generate, or record output.")
    try:
        return judge(root, factory_name, case_id, None,
                     prompt_version=version or row["prompt_version"],
                     output_text=row["output"])
    except ModelError as exc:
        raise UiError(str(exc)) from exc


def check_evals(root: Path, factory_name: str) -> dict:
    from ctx.models import check_eval_files
    return check_eval_files(root, factory_name)


def promote_prompt(root: Path, factory_name: str, version: str) -> dict:
    _call(cli.cmd_prompt_promote, root, factory_name, version)
    return {"ok": True, "factory": factory_name, "version": version}


def import_inbox_upload(root: Path, filename: str, data: bytes) -> dict:
    from ctx.inbox_import import InboxImportError, import_bytes
    try:
        written = import_bytes(root, filename, data)
    except InboxImportError as exc:
        raise UiError(str(exc)) from exc
    return {"ok": True, "imported": written}


def rebuild_index(root: Path) -> dict:
    counts = db.init_db(root)
    return {"ok": True, **counts}


def hook_view(root: Path) -> dict:
    from ctx.config import hook_token
    return {"ok": True, "set": bool(hook_token(root))}


def hook_new(root: Path) -> dict:
    from ctx.config import set_hook_token
    return {"ok": True, "token": set_hook_token(root)}


def schedule_view(root: Path, project: str | None = None) -> dict:
    from ctx.schedule import ScheduleError, show, weekly_command
    try:
        text = show(root, project)
        command = weekly_command(root, project)
    except ScheduleError as exc:
        raise UiError(str(exc)) from exc
    return {"ok": True, "text": text, "command": command,
            "platform": "windows" if sys.platform == "win32" else sys.platform}


def schedule_install(root: Path, project: str | None = None) -> dict:
    from ctx.schedule import ScheduleError, install
    try:
        name = install(root, project=project)
    except ScheduleError as exc:
        raise UiError(str(exc)) from exc
    return {"ok": True, "task": name}


def reset_account(root: Path, name: str) -> dict:
    from ctx.accounts import AccountError, reset
    try:
        shown = reset(root, name)
    except AccountError as exc:
        raise UiError(str(exc)) from exc
    return {"ok": True, "name": (name or "").strip().lower(), "password": shown}


def capture(root: Path, title: str, body: str, source: str = "the local cockpit") -> dict:
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
            f"Captured {today} from {source}. "
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
    if shared_server(root) and "role" in updates:
        raise UiError(
            "on a shared server the author role is read-only. Set it on the "
            "machine that runs builds.")
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
        _ensure_note_column(conn)
        if note:
            cur = conn.execute("UPDATE runs SET verdict = ?, note = ? WHERE id = ?",
                               (verdict, note, rid))
        else:
            cur = conn.execute("UPDATE runs SET verdict = ?, note = '' WHERE id = ?",
                               (verdict, rid))
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
        elif name == factory.MAINTENANCE_FACTORY:
            info = factory.assemble_maintenance(root, mode="shadow")
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
             payload: dict | None, *, token_ok: bool, port: int | None = None,
             session_actor: str = "") -> tuple[int, bytes, str]:
    """Handle one cockpit request. Returns (status, body, content-type)."""
    try:
        if method == "GET" and path == "/":
            page = PAGE_PATH.read_text(encoding="utf-8")
            return 200, page.encode("utf-8"), "text/html; charset=utf-8"
        if method == "GET" and path == "/api/snapshot":
            return 200, _json(snapshot(root, port=port, session_actor=session_actor)), \
                "application/json; charset=utf-8"
        if method == "GET" and path == "/api/wiki":
            return 200, _json(wiki_view(root, query.get("repo", ""), query.get("page", ""))), \
                "application/json; charset=utf-8"
        if method == "GET" and path == "/api/run":            return 200, _json(run_detail(root, query.get("id", ""))), \
                "application/json; charset=utf-8"
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
        elif path == "/api/run/file":
            result = file_run(root, payload.get("id"), payload.get("title"))
        elif path == "/api/factory/new":
            result = new_factory(root, payload.get("name") or "", payload.get("title") or "")
        elif path == "/api/factory/watch":
            result = watch_now(root, bool(payload.get("build")))
        elif path == "/api/eval/run":
            result = check_evals(root, payload.get("factory") or "")
        elif path == "/api/eval/status":
            from ctx.models import eval_status
            result = eval_status(root, payload.get("factory") or "",
                                 payload.get("version") or "")
        elif path == "/api/wiki/action":
            result = wiki_action(root, payload.get("action") or "", payload)
        elif path == "/api/spec/approve":
            result = approve_spec(root, payload.get("contribution") or "")
        elif path == "/api/build":
            result = build_with_model(root, payload.get("contribution") or "")
        elif path == "/api/eval/judge":
            result = judge_eval(root, payload.get("factory") or "",
                                payload.get("case") or "", payload.get("version") or "")
        elif path == "/api/object/delete":
            result = delete_object(root, payload.get("type") or "",
                                   payload.get("id") or "", bool(payload.get("force")))
        elif path == "/api/prompt/promote":
            result = promote_prompt(root, payload.get("factory") or "",
                                    payload.get("version") or "")
        elif path == "/api/init":
            result = rebuild_index(root)
        elif path == "/api/hook":
            result = hook_new(root) if payload.get("create") else hook_view(root)
        elif path == "/api/schedule":
            if payload.get("install"):
                result = schedule_install(root, payload.get("project") or None)
            else:
                result = schedule_view(root, payload.get("project") or None)
        elif path == "/api/account/reset":
            result = reset_account(root, payload.get("name") or "")
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
        if method == "POST" and parsed.path == "/hook":
            self._capture_hook()
            return
        if not self._access_ok():
            if method == "GET" and parsed.path == "/":
                self._send(200, _gate_page(self._people() > 0), "text/html; charset=utf-8")
                return
            if method == "POST" and parsed.path == "/api/session":
                self._open_session()
                return
            self._reject(401, "sign in required")
            return
        if method == "POST" and parsed.path == "/api/inbox/import":
            self._import_upload()
            return
        if method == "POST" and parsed.path == "/api/session/end":
            self._end_session()
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
                self.server.root, method, parsed.path, self._query(), payload,
                token_ok=token_ok,
                port=self.server.server_address[1],
                session_actor=self._session_actor())
            if parsed.path == "/" and status == 200:
                body = body.replace(b"__CTX_TOKEN__", self.server.token.encode("ascii"), 1)
            self._send(status, body, content_type)
        finally:
            unbind(bound)

    def _import_upload(self) -> None:
        """Accept one .eml/.ics/.md/.txt file and put it in the inbox."""
        if not secrets.compare_digest(
                self.headers.get("X-Ctx-Token", ""), self.server.token):
            self._reject(403, "missing or invalid token")
            return
        length = int(self.headers.get("Content-Length") or "0")
        if length > MAX_BODY:
            self._reject(413, "file is too large")
            return
        raw = self.rfile.read(length) if length else b""
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._reject(400, "expected a file upload")
            return
        message = email.message_from_bytes(
            f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode() + raw,
            policy=policy.default)
        part = next((item for item in message.iter_parts() if item.get_filename()), None)
        if part is None:
            self._reject(400, "no file in the upload")
            return
        try:
            result = import_inbox_upload(
                self.server.root, part.get_filename() or "",
                part.get_payload(decode=True) or b"")
        except UiError as exc:
            self._reject(exc.status, str(exc))
            return
        self._send(200, _json(result), "application/json; charset=utf-8")

    def _end_session(self) -> None:
        """Forget this browser's session. Does nothing on this computer."""
        token = self._cookie("stead_session")
        if token:
            with self.server.sessions_lock:
                self.server.sessions.pop(token, None)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Set-Cookie",
                         "stead_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _capture_hook(self) -> None:
        """Write one inbox note. Does not run a factory or edit context/."""
        from ctx.config import hook_token
        expected = hook_token(self.server.root)
        presented = self.headers.get("X-Stead-Hook", "")
        if not expected:
            self._reject(404, "webhook is off")
            return
        if not presented or not secrets.compare_digest(presented, expected):
            self._reject(401, "webhook token required")
            return
        try:
            payload = self._read_json()
            result = capture(self.server.root, payload.get("title") or "",
                             payload.get("body") or "", source="a webhook")
        except UiError as exc:
            self._reject(exc.status, str(exc))
            return
        self._send(200, _json({"ok": True, "name": result["name"]}),
                   "application/json; charset=utf-8")

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
