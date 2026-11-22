"""Read-only search over markdown context objects.

`stead context search` scans the files under `context/` and reports matches in
titles or bodies. It never writes to the store, calls a model, or touches the
network.
"""

from __future__ import annotations

from pathlib import Path

from ctx import objects

SNIPPET_RADIUS = 40
SNIPPET_MAX = 100


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _snippet(text: str, query: str) -> str:
    """A one-line snippet centered on the first case-insensitive match."""
    q = query.lower()
    idx = text.lower().find(q)
    if idx < 0:
        return ""
    line_start = text.rfind("\n", 0, idx) + 1
    line_end = text.find("\n", idx)
    if line_end == -1:
        line_end = len(text)
    line = _one_line(text[line_start:line_end])
    if len(line) <= SNIPPET_MAX:
        return line
    cidx = line.lower().find(q)
    start = max(0, cidx - SNIPPET_RADIUS)
    end = min(len(line), cidx + len(query) + SNIPPET_RADIUS)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(line) else ""
    return prefix + line[start:end] + suffix


def _repo_refs(meta: dict, body: str) -> set[str]:
    """Repo references: the `repo` frontmatter field and `repo:` tags.

    Only those two. A body line or another field that merely mentions
    `repo:` is prose, not a relation, and does not put an object in a repo."""
    refs: set[str] = set()
    value = meta.get("repo")
    if isinstance(value, list):
        refs.update(str(v).strip() for v in value if v is not None)
    elif value is not None:
        refs.add(str(value).strip())
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    for tag in tags:
        text = str(tag).strip()
        if text.lower().startswith("repo:"):
            refs.add(text[len("repo:"):].strip())
    return {r for r in refs if r}


def search(root: Path, query: str, repo: str | None = None) -> list[dict]:
    """Case-insensitive search across all context objects.

    With `repo`, only the named repository object and objects that reference it
    via a `repo` field or `repo:` tag are considered.
    """
    if not query.strip():
        raise ValueError("query must not be empty")
    repo_id: str | None = None
    if repo:
        found = objects.find(root, "repo", repo)
        if found is None:
            raise ValueError(f"repo not found: {repo!r}")
        repo_id = found[1]["id"]

    results: list[dict] = []
    for otype in objects.TYPE_DIRS:
        for path, meta, body in objects.iter_objects(root, otype):
            if repo:
                if otype == "repo":
                    if meta.get("id") != repo_id:
                        continue
                else:
                    refs = _repo_refs(meta, body)
                    if repo_id not in refs and repo not in refs:
                        continue
            title = str(meta.get("title", ""))
            snippet = ""
            if query.lower() in title.lower():
                snippet = _snippet(title, query)
            elif query.lower() in body.lower():
                snippet = _snippet(body, query)
            if snippet:
                results.append({
                    "id": str(meta.get("id", path.stem)),
                    "type": otype,
                    "path": path.relative_to(root).as_posix(),
                    "snippet": snippet,
                })
    results.sort(key=lambda r: r["path"])
    return results


def render(results: list[dict], query: str) -> str:
    if not results:
        return f"no matches for {query}"
    lines = [f"matches for {query}:"]
    for r in results:
        lines.append(r["path"])
        lines.append(f"  {r['snippet']}")
    lines.append(f"({len(results)} object{'s' if len(results) != 1 else ''})")
    return "\n".join(lines)
