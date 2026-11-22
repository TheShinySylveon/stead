"""Merge one open pull request. Explicit command. Never the default.

The repo file must say `reach: merge`. Checks must already be green. The
default branch must have required status checks, and the checks run must be
trusted (a container, or an explicit host acknowledgement). GitHub branch
protection is not bypassed: this never passes `--admin`, and it never pushes
the default branch. Factory assembly and publish do not call this.
"""

from __future__ import annotations

import json
from pathlib import Path

from ctx import objects, safety
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
    if not safety.checks_trusted(repo_meta):
        raise MergeError(
            "refusing to merge while checks run on the host. The model wrote the "
            "code those checks execute, so they can read your environment. Set "
            "`checks_isolation: docker` and `checks_image` on the repo, or set "
            "`trust_checks: host` to accept that risk explicitly.")
    code = Path(repo_meta.get("code_path") or "")
    if not repo_meta.get("code_path") or not code.is_dir():
        raise MergeError("set the repo code_path to a local checkout before merging")
    if code.resolve() == root.resolve():
        raise MergeError("code_path must be the project checkout, not this Stead repo")
    run = safety.safe_runner(runner or _run)
    default = (repo_meta.get("default_branch") or "main").strip()
    branch = _git(run, code, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if not branch or branch in {default, "HEAD"}:
        raise MergeError(
            f"refusing to merge from {branch or 'an unknown branch'}. Stay off {default}.")
    raw = run([
        "gh", "pr", "view", "--json",
        "number,url,state,isDraft,baseRefName,headRefName,headRefOid,statusCheckRollup",
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
    _require_protected_default(run, code, default, repo_meta)
    _require_green(view.get("statusCheckRollup"))
    number = view.get("number")
    if not isinstance(number, int):
        raise MergeError("the pull request has no number")
    # Pin the merge to the commit Stead built and recorded. If the PR head has
    # moved (a human pushed edits), refuse rather than merge unreviewed code;
    # --match-head-commit also guards the head moving between view and merge.
    expected = ""
    from ctx import writeback
    record = writeback.record_for_branch(root, str(repo_meta.get("id") or ""), branch)
    if record is not None:
        expected = str(record.get("commit") or "")
    if not expected:
        expected = _git(run, code, ["rev-parse", "HEAD"]).strip()
    head_sha = (view.get("headRefOid") or "").strip()
    if expected and head_sha and head_sha != expected:
        raise MergeError(
            "the pull request head differs from the commit Stead built "
            f"({head_sha[:12]} vs {expected[:12]}). A human may have edited it; "
            "review and merge it manually.")
    argv = ["gh", "pr", "merge", str(number), "--merge"]
    if expected:
        argv += ["--match-head-commit", expected]
    run(argv, code)
    try:
        writeback.mark_merged(root, contribution_ref,
                              url=(view.get("url") or "").strip(),
                              head_sha=head_sha or expected)
    except Exception:
        pass
    return {
        "merged": True,
        "number": number,
        "url": (view.get("url") or "").strip(),
        "branch": branch,
        "base": default,
        "bypassed": False,
    }


def _require_protected_default(run, code: Path, default: str, repo_meta: dict) -> None:
    """Refuse merge when the default branch does not require checks.

    Otherwise "branch protection is not bypassed" protects nothing: a repo with
    no required checks merges straight away. A repo can acknowledge that with
    `merge_without_required_checks: true`. Branch protection needs admin rights
    to read and does not see rulesets, so fall back to the branch rules API
    before refusing — otherwise valid repos drive people to the override.
    """
    if safety.truthy(repo_meta.get("merge_without_required_checks")):
        return
    try:
        name = run(["gh", "repo", "view", "--json", "nameWithOwner",
                    "--jq", ".nameWithOwner"], code).strip()
    except PublishError as exc:
        raise MergeError(
            "could not read the repository name, so required checks cannot be "
            "confirmed. Refusing to merge.") from exc
    if "/" not in name:
        raise MergeError("could not read the repository name. Refusing to merge.")
    if _protection_has_required_checks(run, code, name, default):
        return
    if _rulesets_have_required_checks(run, code, name, default):
        return
    raise MergeError(
        f"{default} has no required status checks (branch protection or rulesets). "
        "Enable required checks on the default branch, or set "
        "`merge_without_required_checks: true` on the repo to accept that.")


def _protection_has_required_checks(run, code: Path, name: str, default: str) -> bool:
    try:
        raw = run(["gh", "api", f"repos/{name}/branches/{default}/protection"], code)
        protection = json.loads(raw)
    except (PublishError, json.JSONDecodeError):
        return False
    required = protection.get("required_status_checks") if isinstance(protection, dict) else None
    if not isinstance(required, dict):
        return False
    contexts = required.get("contexts") or required.get("checks") or []
    return bool(contexts)


def _rulesets_have_required_checks(run, code: Path, name: str, default: str) -> bool:
    try:
        raw = run(["gh", "api", f"repos/{name}/rules/branches/{default}"], code)
        rules = json.loads(raw)
    except (PublishError, json.JSONDecodeError):
        return False
    if not isinstance(rules, list):
        return False
    for rule in rules:
        if not isinstance(rule, dict) or rule.get("type") != "required_status_checks":
            continue
        params = rule.get("parameters") or {}
        if params.get("required_status_checks"):
            return True
    return False


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
