"""A gated remote write: comment on the issue linking the PR.

This is the only new remote write beyond publish/merge. It is opt-in per repo
(``allow_comment: true``), ``kind: own`` only at MVP, idempotent (one marked
comment, updated in place), and never runs from factory assembly. GitHub already
surfaces ``Closes #N`` on the issue timeline; this adds an explicit link and is
the place CI status could later be refreshed without going stale.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ctx import objects, safety

COMMENT_MARKER = "<!-- stead-pr -->"


class CommentError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _owner_name(repo_meta: dict) -> str:
    url = (repo_meta.get("url") or "").rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/",
                   "git@github.com:", "github.com/"):
        if url.startswith(prefix):
            rest = url[len(prefix):].rstrip("/")
            if rest.endswith(".git"):
                rest = rest[:-4]
            return rest
    raise CommentError(f"cannot read the owner/name from the repo url: {url!r}")


def _comment_body(pr_url: str) -> str:
    return f"{COMMENT_MARKER}\nStead opened a pull request for this issue: {pr_url}\n"


def comment(root: Path, contribution_ref: str, pr_url: str, *, runner=None) -> dict:
    """Post (or update) the Stead comment linking the PR on the source issue."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise CommentError(f"contribution not found: {contribution_ref}")
    _path, spec, _body = found
    if spec.get("kind") != "issue":
        raise CommentError("commenting runs from an issue")
    repo = objects.find(root, "repo", spec.get("repo") or "")
    if repo is None:
        raise CommentError(f"repo not found: {spec.get('repo')!r}")
    _repo_path, repo_meta, _repo_body = repo
    if repo_meta.get("kind") != "own":
        raise CommentError("issue commenting is `kind: own` only at MVP")
    if not safety.truthy(repo_meta.get("allow_comment")):
        raise CommentError("commenting is off for this repo; set allow_comment: true")
    number = spec.get("number")
    if not number:
        raise CommentError("the issue has no number to comment on")
    code = Path(repo_meta.get("code_path") or "")
    if not code.is_dir():
        raise CommentError("set the repo code_path before commenting")
    owner_name = _owner_name(repo_meta)
    run = runner or _run

    existing = _find_marked_comment(run, owner_name, number, code)
    text = _comment_body(pr_url)
    if existing is not None:
        run(["gh", "api", "-X", "PATCH",
             f"repos/{owner_name}/issues/comments/{existing}",
             "-f", f"body={text}"], code)
        return {"updated": True,
                "url": f"https://github.com/{owner_name}/issues/{number}"
                       f"#issuecomment-{existing}"}
    url = run(["gh", "issue", "comment", str(number), "--body", text],
              code).strip()
    return {"created": True, "url": url or ""}


def _find_marked_comment(run, owner_name: str, number, code: Path):
    """The id of the existing marked Stead comment, or None."""
    try:
        raw = run(["gh", "api",
                   f"repos/{owner_name}/issues/{number}/comments"], code)
    except CommentError:
        return None
    try:
        comments = json.loads(raw or "null")
    except json.JSONDecodeError:
        return None
    if not isinstance(comments, list):
        return None
    for item in comments:
        if isinstance(item, dict) and COMMENT_MARKER in (item.get("body") or ""):
            return item.get("id")
    return None


def _run(argv: list[str], cwd: Path) -> str:
    try:
        done = subprocess.run(argv, cwd=cwd, check=True, capture_output=True,
                              text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise CommentError(detail or f"{argv[0]} failed") from exc
    except FileNotFoundError as exc:
        raise CommentError(f"{argv[0]} is not installed") from exc
    return done.stdout or ""
