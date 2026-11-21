"""Read-side navigation of context/ markdown objects (files = source of truth)."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

from ctx import frontmatter

TYPE_DIRS = {
    "project": "projects",
    "task": "tasks",
    "document": "documents",
    "meeting": "meetings",
}


def iter_objects(root: Path, otype: str) -> Iterator[tuple[Path, dict, str]]:
    """Yield (path, meta, body) for every object of a type, sorted by filename."""
    folder = root / "context" / TYPE_DIRS[otype]
    if not folder.is_dir():
        return
    for path in sorted(folder.glob("*.md")):
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        yield path, meta, body


def find(root: Path, otype: str, ref: str) -> tuple[Path, dict, str] | None:
    """Resolve an object by full id, filename stem, or slug (id minus type)."""
    candidates = {ref, f"{otype}-{ref}"}
    for path, meta, body in iter_objects(root, otype):
        if meta.get("id") in candidates or path.stem == ref:
            return path, meta, body
    return None


def linked(root: Path, otype: str, project_id: str) -> list[tuple[Path, dict, str]]:
    """All objects of a type whose frontmatter relates them to project_id."""
    out = []
    for path, meta, body in iter_objects(root, otype):
        proj = meta.get("project")
        projects = proj if isinstance(proj, list) else [proj]
        if project_id in projects:
            out.append((path, meta, body))
    return out
