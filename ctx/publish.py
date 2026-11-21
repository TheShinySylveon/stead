"""Open a pull request from an isolated branch. Never merge. Never push default.

feature-builder assembly stays local. Publish is a separate, explicit step.
It pushes the checkout's current branch only when that branch is not the
default branch and already has commits ahead of it. A draft is the default.
A normal pull request is allowed when the repo ceiling is `pr` or `merge`.
Merging is `stead factory merge`, and only when the repo file says so.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ctx import objects
from ctx.autonomy import AutonomyError, effective, permit


class PublishError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def publish(root: Path, contribution_ref: str, *, runner=None) -> dict:
    """Push an isolated branch and open a pull request. Raises PublishError."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise PublishError(f"contribution not found: {contribution_ref}")
    _path, spec, _body = found
    if spec.get("kind") != "issue" or spec.get("role") != "author":
        raise PublishError("publish runs from an issue you authored")
    repo = objects.find(root, "repo", spec.get("repo") or "")
    if repo is None:
        raise PublishError(f"repo not found: {spec.get('repo')!r}")
    _repo_path, repo_meta, _repo_body = repo
    policy = effective(root, repo_meta)
    try:
        reach = permit(policy, None)
    except AutonomyError as exc:
        raise PublishError(str(exc)) from exc
    if reach == "shadow":
        raise PublishError(
            "this repo's ceiling is shadow. Raise it before opening a pull request.")
    code = Path(repo_meta.get("code_path") or "")
    if not repo_meta.get("code_path") or not code.is_dir():
        raise PublishError(
            "set the repo code_path to a local checkout before publishing")
    if code.resolve() == root.resolve():
        raise PublishError("code_path must be the project checkout, not this Stead repo")
    run = runner or _run
    default = (repo_meta.get("default_branch") or "main").strip()
    branch = _git(run, code, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch in {default, "HEAD"}:
        raise PublishError(
            f"refusing to publish from {branch or 'an unknown branch'}. "
            f"Stay off {default}.")
    ahead = _git(run, code, ["rev-list", "--count", f"{default}..HEAD"]).strip()
    if not ahead.isdigit() or int(ahead) < 1:
        raise PublishError(
            f"{branch} has no commits ahead of {default}. Nothing to publish.")
    _git(run, code, ["push", "-u", "origin", f"HEAD:{branch}"])
    number = spec.get("number")
    title = spec.get("title") or branch
    link = f"Tracks #{number}." if number else "No issue number on the spec."
    if repo_meta.get("kind") == "own" and number:
        link = f"Closes #{number}."
    body = (
        f"{link}\n\n"
        "Opened by Stead from an isolated branch. A person reviews.\n"
        "This command does not merge. `stead factory merge` is separate, and "
        "only when this repo says reach: merge."
    )
    argv = ["gh", "pr", "create", "--base", default, "--head", branch,
            "--title", title, "--body", body]
    if reach == "draft-pr":
        argv.insert(3, "--draft")
    url = run(argv, code).strip()
    return {
        "reach": reach,
        "branch": branch,
        "base": default,
        "url": url,
        "merged": False,
    }


def _git(run, code: Path, args: list[str]) -> str:
    if args and args[0] == "push":
        dest = args[-1].split(":")[-1]
        if dest in {"main", "master"}:
            raise PublishError("refusing a push whose destination is a default branch name")
    return run(["git", *args], code)


def _run(argv: list[str], cwd: Path) -> str:
    try:
        done = subprocess.run(
            argv, cwd=cwd, check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise PublishError(detail or f"{argv[0]} failed") from exc
    except FileNotFoundError as exc:
        raise PublishError(f"{argv[0]} is not installed") from exc
    return done.stdout or ""
