"""Merge one open pull request. Explicit command. Never the default.

The repo file must say `reach: merge`. Checks must already be green. GitHub
branch protection is not bypassed: this never passes `--admin`, and it never
pushes the default branch. Factory assembly and publish do not call this.
"""

from __future__ import annotations

import json
from pathlib import Path

from ctx import objects
from ctx.autonomy import effective
from ctx.publish import PublishError, _git, _run

_GREEN = {"SUCCESS"}
_SKIP = {"NEUTRAL", "SKIPPED"}
_BAD = {
    "FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STALE",
    "STARTUP_FAILURE", "ERROR", "PENDING", "IN_PROGRESS", "QUEUED",
    "WAITING", "REQUESTED",
}


class MergeError(PublishError):
    pass


def merge(root: Path, contribution_ref: str, *, runner=None) -> dict:
    """Merge the checkout's open pull request. Raises MergeError."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise MergeError(f"contribution not found: {contribution_ref}")
    _path, spec, _body = found
    if spec.get("kind") != "issue" or spec.get("role") != "author":
        raise MergeError("merge runs from an issue you authored")
    repo = objects.find(root, "repo", spec.get("repo") or "")
    if repo is None:
        raise MergeError(f"repo not found: {spec.get('repo')!r}")
    _repo_path, repo_meta, _repo_body = repo
    policy = effective(root, repo_meta)
    if not policy.get("merge_explicit"):
        raise MergeError(
            "merge must be set on the repo. It is not inherited, and it is not "
            "run from publish.")
    code = Path(repo_meta.get("code_path") or "")
    if not repo_meta.get("code_path") or not code.is_dir():
        raise MergeError("set the repo code_path to a local checkout before merging")
    if code.resolve() == root.resolve():
        raise MergeError("code_path must be the project checkout, not this Stead repo")
    run = runner or _run
    default = (repo_meta.get("default_branch") or "main").strip()
    branch = _git(run, code, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch in {default, "HEAD"}:
        raise MergeError(
            f"refusing to merge from {branch or 'an unknown branch'}. Stay off {default}.")
    raw = run([
        "gh", "pr", "view", "--json",
        "number,url,state,isDraft,baseRefName,headRefName,statusCheckRollup",
    ], code)
    try:
        view = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise MergeError("could not read the pull request") from exc
    if not isinstance(view, dict):
        raise MergeError("could not read the pull request")
    head = (view.get("headRefName") or "").strip()
    base = (view.get("baseRefName") or "").strip()
    if head in {default, "main", "master"} or head != branch:
        raise MergeError(f"refusing to merge {head or 'an unknown head'} into {base or default}")
    if base != default:
        raise MergeError(f"refusing to merge into {base or 'an unknown base'}. Expected {default}.")
    if str(view.get("state") or "").upper() != "OPEN":
        raise MergeError("the pull request is not open")
    if view.get("isDraft"):
        raise MergeError("draft pull requests are not merged")
    _require_green(view.get("statusCheckRollup"))
    number = view.get("number")
    if not isinstance(number, int):
        raise MergeError("the pull request has no number")
    run(["gh", "pr", "merge", str(number), "--merge"], code)
    return {
        "merged": True,
        "number": number,
        "url": (view.get("url") or "").strip(),
        "branch": branch,
        "base": default,
        "bypassed": False,
    }


def _require_green(rollup) -> None:
    if not isinstance(rollup, list) or not rollup:
        raise MergeError("no checks reported. Refusing to merge.")
    green = 0
    for item in rollup:
        if not isinstance(item, dict):
            raise MergeError("a check could not be read. Refusing to merge.")
        conclusion = str(item.get("conclusion") or item.get("state") or "").upper()
        status = str(item.get("status") or "").upper()
        if conclusion in _SKIP:
            continue
        if conclusion in _GREEN and status in {"", "COMPLETED", "SUCCESS"}:
            green += 1
            continue
        if conclusion in _BAD or status in _BAD or not conclusion:
            name = item.get("name") or item.get("context") or "a check"
            raise MergeError(f"{name} is not green. Refusing to merge.")
        raise MergeError("a check is not green. Refusing to merge.")
    if green < 1:
        raise MergeError("no green checks. Refusing to merge.")
