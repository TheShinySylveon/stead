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
import webbrowser
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ctx import cli, db, factory, objects

PKG_DIR = Path(__file__).resolve().parent
PAGE_PATH = PKG_DIR / "cockpit.html"
LOOPBACK = ("127.0.0.1", "localhost", "::1")
MAX_BODY = 64 * 1024

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
                "ci", "review", "method", "number"):
        if meta.get(key) not in (None, ""):
            item[key] = meta[key]
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
    }


def shadow_run(root: Path, payload: dict) -> dict:
    if payload.get("live") or payload.get("mode") == "live":
        raise UiError("the cockpit only assembles shadow runs — no remote writes")
    name = payload.get("factory") or ""
    try:
        if name == factory.FEATURE_BUILDER_FACTORY:
            if not payload.get("contribution"):
                raise UiError("feature-builder needs a contribution")
            info = factory.assemble_feature_build(root, payload["contribution"], mode="shadow")
        elif name == factory.DIGEST_FACTORY:
            info = factory.assemble_digest(root, mode="shadow")
        else:
            if not payload.get("project"):
                raise UiError(f"{name or 'this factory'} needs a project")
            info = factory.assemble(root, name, payload["project"], mode="shadow")
    except SystemExit as exc:
        raise UiError(str(exc) or "could not assemble a shadow run") from exc
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
        elif path == "/api/capture":
            result = capture(root, payload.get("title", ""), payload.get("body", ""))
        elif path == "/api/factory/run":
            result = shadow_run(root, payload)
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
        host = (self.headers.get("Host") or "").split(":")[0].strip("[]")
        return host in LOOPBACK

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

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")


class CockpitServer(ThreadingHTTPServer):
    def __init__(self, root: Path, address: tuple[str, int], token: str):
        self.root = root
        self.token = token
        super().__init__(address, CockpitHandler)


def make_server(root: Path, host: str = "127.0.0.1", port: int = 8765) -> CockpitServer:
    if host not in LOOPBACK:
        raise SystemExit(
            f"ctx ui only binds to loopback ({', '.join(LOOPBACK)}). "
            "It serves private notes and will not listen on a public interface.")
    ensure_index(root)
    return CockpitServer(root, (host, port), secrets.token_urlsafe(24))


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765,
          open_browser: bool = True) -> int:
    httpd = make_server(root, host, port)
    bound = httpd.server_address[1]
    url = f"http://127.0.0.1:{bound}/"
    print(f"Shared Context cockpit\n  {url}")
    print("  loopback only · markdown is the source of truth · Ctrl+C to stop")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()
    return 0
