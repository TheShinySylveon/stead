"""Lint the context store. Hand edits should fail loudly, not silently.

The frontmatter reader is a flat YAML subset with no schema. `stead doctor`
checks the parts a reader would otherwise discover at the worst moment: a
malformed block, a missing id, a relation that points at nothing, a duplicate
id, a date that is not a date.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from ctx import frontmatter
from ctx.objects import TYPE_DIRS

REQUIRED = ("id", "type", "title", "created", "updated")
STATUSES = {
    "task": {"to-do", "doing", "done", "blocked"},
    "project": {"active", "paused", "done"},
    "repo": {"active", "paused", "archived"},
    "contribution": {"open", "closed", "merged"},
}
REQUIRED_RELATIONS = {"task": ("project",), "contribution": ("repo",)}
OPTIONAL_RELATIONS = {"document": ("project",), "meeting": ("project",)}


def run(root: Path) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    ids: dict[str, Path] = {}
    known: dict[str, Path] = {}
    checked = 0
    for otype, folder_name in TYPE_DIRS.items():
        folder = root / "context" / folder_name
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.md")):
            checked += 1
            relative = path.relative_to(root).as_posix()
            try:
                text = path.read_text(encoding="utf-8")
                meta, body = frontmatter.parse(text)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                errors.append(_issue(relative, f"cannot read frontmatter: {exc}"))
                continue
            if not meta:
                errors.append(_issue(relative, "no frontmatter block"))
                continue
            for key in REQUIRED:
                if not str(meta.get(key) or "").strip():
                    errors.append(_issue(relative, f"missing {key}"))
            if meta.get("type") and meta.get("type") != otype:
                errors.append(_issue(
                    relative, f"type is {meta.get('type')!r}, folder is {otype!r}"))
            identifier = str(meta.get("id") or "")
            if identifier:
                if identifier in ids:
                    errors.append(_issue(
                        relative, f"duplicate id {identifier} (also {ids[identifier]})"))
                ids[identifier] = path
                known[identifier] = path
            for key in ("created", "updated"):
                value = str(meta.get(key) or "")
                if value and not _is_date(value):
                    errors.append(_issue(relative, f"{key} is not an ISO date: {value!r}"))
            status_key = "state" if otype == "contribution" else "status"
            status = meta.get(status_key)
            if status and otype in STATUSES and status not in STATUSES[otype]:
                warnings.append(_issue(relative, f"unusual {status_key} {status!r}"))
            for relation in REQUIRED_RELATIONS.get(otype, ()):
                target = str(meta.get(relation) or "")
                if not target:
                    errors.append(_issue(relative, f"missing {relation} relation"))
                elif target not in _all_ids(root, relation):
                    errors.append(_issue(
                        relative, f"{relation} points at missing object {target!r}"))
            for relation in OPTIONAL_RELATIONS.get(otype, ()):
                target = str(meta.get(relation) or "")
                if target and target not in _all_ids(root, relation):
                    errors.append(_issue(
                        relative, f"{relation} points at missing object {target!r}"))
            if not body.strip():
                warnings.append(_issue(relative, "empty body"))
            if otype == "contribution":
                body_sha = str(meta.get("body_sha") or "")
                upstream = str(meta.get("upstream_body_sha") or "")
                if body_sha and upstream and body_sha != upstream:
                    warnings.append(_issue(
                        relative, "the synced issue changed after it was stored "
                                  "(body_sha != upstream_body_sha)"))
                raw_tags = meta.get("tags") or []
                if isinstance(raw_tags, str):
                    raw_tags = [raw_tags]
                tag_set = {str(t).lower() for t in raw_tags}
                if tag_set & {"stead-build", "feature-spec"}:
                    spec_sha = str(meta.get("spec_sha") or "")
                    if not spec_sha:
                        warnings.append(_issue(relative, "no spec_sha (unapproved)"))
                    elif spec_sha != _body_hash(body):
                        warnings.append(_issue(
                            relative, "body changed (spec_sha mismatch)"))
    return {"checked": checked, "errors": errors, "warnings": warnings}


def _all_ids(root: Path, otype: str) -> set[str]:
    folder = root / "context" / TYPE_DIRS.get(otype, "")
    if not folder.is_dir():
        return set()
    found = set()
    for path in folder.glob("*.md"):
        try:
            meta, _body = frontmatter.parse(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if meta.get("id"):
            found.add(str(meta["id"]))
    return found


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value[:10])
    except ValueError:
        return False
    return len(value) == 10


def _issue(path: str, message: str) -> dict:
    return {"path": path, "message": message}


def _body_hash(body: str) -> str:
    """The approval hash `spec_sha` stores: SHA-256 of the stripped body. Reuses
    the same rule as `ctx.spec.body_hash` so doctor flags exactly what approval
    would flag."""
    import hashlib
    return hashlib.sha256(body.strip().encode("utf-8")).hexdigest()


def render(report: dict) -> str:
    lines = [f"checked {report['checked']} objects"]
    for issue in report["errors"]:
        lines.append(f"error   {issue['path']}: {issue['message']}")
    for issue in report["warnings"]:
        lines.append(f"warning {issue['path']}: {issue['message']}")
    if not report["errors"] and not report["warnings"]:
        lines.append("no problems found")
    else:
        lines.append(f"{len(report['errors'])} error(s), "
                     f"{len(report['warnings'])} warning(s)")
    return "\n".join(lines)
