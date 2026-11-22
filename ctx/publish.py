"""Open a pull request from an isolated branch. Never merge. Never push default.

feature-builder assembly stays local. Publish is a separate, explicit step.
It pushes the spec's deterministic build branch (`stead/<number>-<slug>`, never
the checkout's current branch), only when that branch has commits ahead of the
default. A draft is the default. A normal pull request is allowed when the repo
ceiling is `pr` or `merge`. Merging is `stead factory merge`, and only when the
repo file says so.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ctx import factory, objects, safety
from ctx.autonomy import AutonomyError, effective, permit


class PublishError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def publish(root: Path, contribution_ref: str, *, runner=None,
            code: Path | None = None) -> dict:
    """Push an isolated branch and open a pull request. Raises PublishError.

    ``code`` names the checkout whose branch is published; a worktree build
    passes its worktree here."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise PublishError(f"contribution not found: {contribution_ref}")
    _path, spec, _body = found
    if spec.get("kind") != "issue" or not factory.enabled(spec):
        raise PublishError("publish runs from an enabled issue (stead-build "
                           "label or feature-spec tag)")
    repo = objects.find(root, "repo", spec.get("repo") or "")
    if repo is None:
        raise PublishError(f"repo not found: {spec.get('repo')!r}")
    _repo_path, repo_meta, _repo_body = repo
    policy = effective(root, repo_meta)
    try:
        reach = permit(policy, None)
    except AutonomyError as exc:
        raise PublishError(str(exc)) from exc
    if reach in ("ghost", "shadow"):
        raise PublishError(
            f"this repo's ceiling is {reach}. Raise it before opening a pull request.")
    if code is None:
        code = Path(repo_meta.get("code_path") or "")
        if not repo_meta.get("code_path") or not code.is_dir():
            raise PublishError(
                "set the repo code_path to a local checkout before publishing")
        code = code.resolve()
    if code.resolve() == root.resolve():
        raise PublishError("code_path must be the project checkout, not this Stead repo")
    run = safety.safe_runner(runner or _run)
    default = (repo_meta.get("default_branch") or "main").strip()
    # Always the spec's deterministic build branch, never the checkout's
    # current branch: worktree builds made "the checkout is on another branch"
    # a supported state, and publishing HEAD could push an unrelated branch.
    branch = factory.branch_for(spec)
    if not _git(run, code, ["branch", "--list", branch]).strip():
        raise PublishError(
            f"build branch {branch} does not exist. Run `stead build` first.")
    ahead = _git(run, code, ["rev-list", "--count", f"{default}..{branch}"]).strip()
    if not ahead.isdigit() or int(ahead) < 1:
        raise PublishError(
            f"{branch} has no commits ahead of {default}. Nothing to publish.")
    _git(run, code, ["push", "-u", "origin", f"{branch}:{branch}"])
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
    changed = []
    deleted = []
    for line in _git(run, code, ["diff", "--name-status", f"{default}..{branch}"]).splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        status, path = parts[0].strip(), parts[-1].strip()
        if not path:
            continue
        if status.startswith("D"):
            deleted.append(path)
        else:
            changed.append(path)
    tests = [path for path in changed if safety.is_test_path(path)]
    tests_deleted = [path for path in deleted if safety.is_test_path(path)]
    ci = [path for path in changed + deleted if safety.is_ci_path(path)]
    if tests:
        body += ("\n\nThis branch touches tests (the repo allows it):\n"
                 + "\n".join(f"- {path}" for path in tests[:20]))
    if tests_deleted:
        body += ("\n\nThis branch deletes tests (the repo allows it):\n"
                 + "\n".join(f"- {path}" for path in tests_deleted[:20]))
    if ci:
        body += ("\n\nThis branch touches CI config (the repo allows it):\n"
                 + "\n".join(f"- {path}" for path in ci[:20]))
    argv = ["gh", "pr", "create", "--base", default, "--head", branch,
            "--title", title, "--body", body]
    if reach == "draft-pr":
        argv.insert(3, "--draft")
    url = run(argv, code).strip()
    return {
        "reach": reach,
        "repo": str(repo_meta.get("id") or ""),
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
            argv, cwd=cwd, check=True, capture_output=True,
            text=True, encoding="utf-8", errors="replace",
        )
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise PublishError(detail or f"{argv[0]} failed") from exc
    except FileNotFoundError as exc:
        raise PublishError(f"{argv[0]} is not installed") from exc
    return done.stdout or ""
