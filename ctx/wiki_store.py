"""Small write layer for the wiki: curation order, pins, and change requests.

Source objects stay generated/read-only from the wiki. This module stores only
the arrangement (a JSON file per repo) and explicit change requests (documents
tagged `wiki-request`). Every write goes through frontmatter so humans can read
it and git can diff it.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path

from ctx import objects

CURATION_DIR = ("context", "wiki")
REQUEST_TAG = "wiki-request"


class WikiStoreError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _folder(root: Path) -> Path:
    return root.joinpath(*CURATION_DIR)


def _path(root: Path, repo_id: str) -> Path:
    safe = re.sub(r"[^a-z0-9-]+", "-", (repo_id or "repo").lower()).strip("-") or "repo"
    return _folder(root) / f"{safe}.json"


def load(root: Path, repo_id: str) -> dict:
    path = _path(root, repo_id)
    if not path.is_file():
        return {"order": [], "children": {}, "pinned": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"order": [], "children": {}, "pinned": []}
    if not isinstance(data, dict):
        return {"order": [], "children": {}, "pinned": []}
    return {
        "order": [str(item) for item in data.get("order") or [] if isinstance(item, str)],
        "children": {str(key): [str(v) for v in value if isinstance(v, str)]
                     for key, value in (data.get("children") or {}).items()
                     if isinstance(value, list)},
        "pinned": [str(item) for item in data.get("pinned") or [] if isinstance(item, str)],
    }


def save(root: Path, repo_id: str, data: dict) -> None:
    import tempfile
    folder = _folder(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = _path(root, repo_id)
    text = json.dumps(data, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=str(folder))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass  # best-effort cleanup of temp file before re-raising
        raise


def ordered(items: list[str], saved: list[str]) -> list[str]:
    """Apply a saved order, appending anything new in its natural order."""
    rank = {value: index for index, value in enumerate(saved)}
    return sorted(items, key=lambda value: (rank.get(value, len(saved)), items.index(value)))


def move(root: Path, repo_id: str, siblings: list[str], path: str,
         direction: str) -> dict:
    """Move one page within its sibling list. Returns the saved curation."""
    if path not in siblings:
        raise WikiStoreError(f"page not in this list: {path}")
    data = load(root, repo_id)
    group, _, child = path.partition("/")
    if child:
        current = ordered(siblings, data["children"].get(group, []))
        key = "children"
        target = group
    else:
        current = ordered(siblings, data["order"])
        key = "order"
        target = None
    index = current.index(path)
    swap = index - 1 if direction == "up" else index + 1
    if swap < 0 or swap >= len(current):
        return data
    current[index], current[swap] = current[swap], current[index]
    if key == "order":
        data["order"] = current
    else:
        data["children"][target] = current
    save(root, repo_id, data)
    return data


def set_pinned(root: Path, repo_id: str, path: str, pinned: bool) -> dict:
    data = load(root, repo_id)
    values = [item for item in data["pinned"] if item != path]
    if pinned:
        values.append(path)
    data["pinned"] = values
    save(root, repo_id, data)
    return data


def request_folder(root: Path) -> Path:
    return root / "context" / "documents"


def create_request(root: Path, repo_id: str, project_id: str, page: str,
                   text: str, title: str | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise WikiStoreError("a change request needs a description")
    if len(text) > 4000:
        raise WikiStoreError("a change request is too long")
    shown = (title or "").strip() or f"Wiki change: {page or 'home'}"
    slug = re.sub(r"[^a-z0-9]+", "-", shown.lower()).strip("-") or "wiki-change"
    folder = request_folder(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{slug}.md"
    n = 2
    while path.exists():
        path = folder / f"{slug}-{n}.md"
        n += 1
    today = date.today().isoformat()
    object_id = f"document-{path.stem}"
    from ctx import frontmatter
    meta = {
        "id": object_id, "type": "document", "title": shown,
        "created": today, "updated": today, "status": "open",
        "tags": [REQUEST_TAG, f"wiki:{repo_id}"],
    }
    if project_id:
        meta["project"] = project_id
    from ctx.actors import stamp
    stamp(root, meta)
    body = (f"# {shown}\n\n"
            f"Page: `{page or 'home'}`\n\n{text}\n\n"
            "Requested from the wiki. Source pages are generated; this request is the input.\n")
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"id": object_id, "title": shown, "path": path.relative_to(root).as_posix()}


def close_request(root: Path, request_id: str) -> dict:
    found = objects.find(root, "document", request_id)
    if found is None:
        raise WikiStoreError(f"request not found: {request_id}")
    path, meta, body = found
    if REQUEST_TAG not in [str(tag) for tag in (meta.get("tags") or [])]:
        raise WikiStoreError("that document is not a wiki request")
    from ctx import frontmatter
    meta["status"] = "done"
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"id": request_id, "status": "done"}
