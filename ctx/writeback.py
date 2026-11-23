"""Close the loop: a delivered build updates the context it came from.

Two kinds of write-back, deliberately separated:

- **Facts** (this module): on a successful build, record the outcome as a
  versioned ``build-record`` document, mark the contribution merged when it
  merged, and close tasks that point at it. These need no review.
- **Interpretation** (decisions, glossary): the build may only *propose* these
  as inbox notes. A person triages them into documents. An agent never quietly
  rewrites the context later builds depend on.

The record is a normal markdown object, so git versions it and the wiki and the
next bundle can read it. The SQLite ``runs`` table stays a rebuildable index.
"""

from __future__ import annotations

import re
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

from ctx import frontmatter, objects

RECORD_TAG = "build-record"
REVIEW_TAG = "review-record"


class WritebackError(Exception):
    def __init__(self, message: str):
        super().__init__(message)


def _repo_of(root: Path, contribution_ref: str):
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        raise WritebackError(f"contribution not found: {contribution_ref}")
    _path, meta, _body = found
    repo = objects.find(root, "repo", meta.get("repo") or "")
    return meta, (repo[1] if repo else {})


def spec_sha_of(root: Path, contribution_ref: str) -> str:
    """The approval hash of the contribution body, if the contribution exists.

    Build records carry this so attempt gating can key on *approved content*
    (re-approval changes the hash and grants a fresh attempt), not on the
    contribution id."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        return ""
    from ctx import spec as spec_approval
    return spec_approval.body_hash(found[2])


def _max_step(result: dict, key: str) -> int:
    """The largest per-step value (e.g. prompt_chars) in a build result, or 0.
    A spike in the prompt size is the early sign of context truncation."""
    logs = result.get("step_logs") or []
    return max((int(s.get(key) or 0) for s in logs if isinstance(s, dict)),
               default=0)


def record_delivery(root: Path, contribution_ref: str, result: dict,
                    run_id: object = None) -> dict:
    """Write the factual record and update linked statuses. Returns the doc id."""
    contrib, repo_meta = _repo_of(root, contribution_ref)
    repo_id = str(repo_meta.get("id") or contrib.get("repo") or "repo")
    merged = bool(result.get("merged"))
    today = date.today().isoformat()
    updated: list[str] = []
    if merged:
        updated = _apply_merged(root, contribution_ref)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-",
                  (contrib.get("title") or contribution_ref).lower()).strip("-") or "build"
    folder = root / "context" / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"build-{slug[:40]}-{stamp}"
    path = folder / f"{name}.md"
    n = 2
    while path.exists():
        path = folder / f"{name}-{n}.md"
        n += 1
    doc_id = f"document-{path.stem}"
    outcome = "merged" if merged else ("published" if result.get("published") else "committed")
    title = f"Build: {contrib.get('title') or contribution_ref} ({outcome})"
    meta = {
        "id": doc_id, "type": "document", "title": title[:200],
        "created": today, "updated": today, "status": "active",
        "tags": [RECORD_TAG, f"repo:{repo_id}"],
        "outcome": outcome,
        # "committed" is mechanical; "correct" is the hand-checked rubric verdict
        # (criteria actually satisfied). Unset until a person marks it, so a
        # build that merely committed reads as unverified, not a success.
        "correct": "unverified",
        "contribution": str(contrib.get("id") or contribution_ref),
        "spec_sha": spec_sha_of(root, contribution_ref),
        "checks_mode": str(result.get("checks_mode") or "none"),
        "elapsed_seconds": str(result.get("elapsed_seconds") or 0),
        "repair_rounds": str(result.get("repair_rounds") or 0),
        "chars_sent": str(result.get("chars_sent") or 0),
        "chars_received": str(result.get("chars_received") or 0),
        "latency_ms": str(result.get("latency_ms") or 0),
        "max_prompt_chars": str(_max_step(result, "prompt_chars")),
        "max_reply_chars": str(_max_step(result, "reply_chars")),
        "tokens_in": str(result.get("tokens_in") or 0),
        "tokens_out": str(result.get("tokens_out") or 0),
        "cost_usd": str(result.get("cost_usd") or 0),
        "files": list(result.get("files") or []),
        "leftovers": list(result.get("leftovers") or []),
        "tests_touched": list(result.get("tests_touched") or []),
        "tests_deleted": list(result.get("tests_deleted") or []),
    }
    if result.get("branch"):
        meta["branch"] = result["branch"]
    if result.get("commit"):
        meta["commit"] = result["commit"]
    if result.get("pr_url"):
        meta["pr_url"] = result["pr_url"]
    if result.get("comment") and isinstance(result["comment"], dict):
        meta["comment_url"] = result["comment"].get("url") or ""
    if result.get("comment_error"):
        meta["comment_error"] = str(result["comment_error"])[:500]
    if repo_meta.get("project"):
        meta["project"] = repo_meta["project"]
    if run_id is not None:
        meta["source_run"] = str(run_id)
    from ctx.actors import stamp as actor_stamp
    actor_stamp(root, meta)
    body = _record_body(contrib, result, outcome)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"id": doc_id, "path": path.relative_to(root).as_posix(),
            "outcome": outcome, "updated": updated}


def _record_body(contrib: dict, result: dict, outcome: str) -> str:
    lines = [f"# Build record: {contrib.get('title') or contrib.get('id')}", "",
             f"Outcome: **{outcome}**.", ""]
    if result.get("branch"):
        lines.append(f"- branch: `{result['branch']}`")
    if result.get("commit"):
        lines.append(f"- commit: `{result['commit']}`")
    if result.get("pr_url"):
        lines.append(f"- pull request: {result['pr_url']}")
    if result.get("merged_url"):
        lines.append(f"- merged: {result['merged_url']}")
    if result.get("checks"):
        lines.append(f"- checks: `{result['checks']}` ({result.get('checks_mode', 'host')})")
    if result.get("files"):
        lines.append("- files: " + ", ".join(f"`{p}`" for p in result["files"]))
    if result.get("deleted"):
        lines.append("- deleted: " + ", ".join(f"`{p}`" for p in result["deleted"]))
    if result.get("leftovers"):
        lines.append("- removed untracked leftovers: "
                     + ", ".join(f"`{p}`" for p in result["leftovers"]))
    if result.get("tests_touched"):
        lines.append("- tests touched: " + ", ".join(f"`{p}`" for p in result["tests_touched"]))
    if result.get("tests_deleted"):
        lines.append("- tests deleted: " + ", ".join(f"`{p}`" for p in result["tests_deleted"]))
    if result.get("summary"):
        lines += ["", "## Summary (model)", "", str(result["summary"]).strip()]
    lines += ["", "Factual record written by Stead on delivery. Interpretive notes "
              "(decisions, glossary) are proposed to the inbox for a person to triage.", ""]
    return "\n".join(lines)


def record_failure(root: Path, contribution_ref: str, error, *,
                   branch: str = "", elapsed: float = 0.0,
                   checks_mode: str = "none", reason: str = "build") -> dict:
    """A failed build writes a record too, so metrics has a failure rate and
    the watch loop can tell a delivered branch from a failed one."""
    contrib, repo_meta = _repo_of(root, contribution_ref)
    repo_id = str(repo_meta.get("id") or contrib.get("repo") or "repo")
    today = date.today().isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-",
                  (contrib.get("title") or contribution_ref).lower()).strip("-") or "build"
    folder = root / "context" / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"build-{slug[:40]}-{stamp}"
    path = folder / f"{name}.md"
    n = 2
    while path.exists():
        path = folder / f"{name}-{n}.md"
        n += 1
    doc_id = f"document-{path.stem}"
    title = f"Build: {contrib.get('title') or contribution_ref} (failed)"
    meta = {
        "id": doc_id, "type": "document", "title": title[:200],
        "created": today, "updated": today, "status": "active",
        "tags": [RECORD_TAG, f"repo:{repo_id}"],
        "outcome": "failed",
        "contribution": str(contrib.get("id") or contribution_ref),
        "spec_sha": spec_sha_of(root, contribution_ref),
        "error_class": type(error).__name__,
        "reason": reason,
        "checks_mode": str(checks_mode or "none"),
        "elapsed_seconds": str(elapsed or 0),
    }
    if branch:
        meta["branch"] = branch
    if repo_meta.get("project"):
        meta["project"] = repo_meta["project"]
    from ctx.actors import stamp as actor_stamp
    actor_stamp(root, meta)
    body = (f"# Build record: {contrib.get('title') or contrib.get('id')}\n\n"
            f"Outcome: **failed** ({reason}).\n\n"
            f"```\n{str(error)[:2000]}\n```\n\n"
            "The model's work in progress, if any, was committed to the build "
            "branch and the checkout returned to the default branch. The full "
            "transcript is in the run directory under factories/feature-builder/runs/.\n")
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"id": doc_id, "path": path.relative_to(root).as_posix(),
            "outcome": "failed"}


def record_review(root: Path, contribution_ref: str, result: dict) -> dict:
    """Write the independent reviewer's verdict as a versioned document."""
    contrib, repo_meta = _repo_of(root, contribution_ref)
    repo_id = str(repo_meta.get("id") or contrib.get("repo") or "repo")
    today = date.today().isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = re.sub(r"[^a-z0-9]+", "-",
                  (contrib.get("title") or contribution_ref).lower()).strip("-") or "review"
    folder = root / "context" / "documents"
    folder.mkdir(parents=True, exist_ok=True)
    name = f"review-{slug[:40]}-{stamp}"
    path = folder / f"{name}.md"
    n = 2
    while path.exists():
        path = folder / f"{name}-{n}.md"
        n += 1
    doc_id = f"document-{path.stem}"
    verdict = str(result.get("verdict") or "reject")
    title = f"Review: {contrib.get('title') or contribution_ref} ({verdict})"
    meta = {
        "id": doc_id, "type": "document", "title": title[:200],
        "created": today, "updated": today, "status": "active",
        "tags": [REVIEW_TAG, f"repo:{repo_id}"],
        "verdict": verdict,
        "contribution": str(contrib.get("id") or contribution_ref),
        "reason": str(result.get("reason") or "")[:500],
        "reviewer_model": str(result.get("model") or ""),
        "reviewer_independent": "true" if result.get("independent") else "false",
        "truncated": "true" if result.get("truncated") else "false",
    }
    if repo_meta.get("project"):
        meta["project"] = repo_meta["project"]
    from ctx.actors import stamp as actor_stamp
    actor_stamp(root, meta)
    note = ("A separate model invocation reviewed the approved spec against the\n"
            "branch diff. It is an independent pass, not a guarantee.\n")
    if not result.get("independent"):
        note = ("The review ran on the builder's model: no separate reviewer\n"
                "endpoint is configured (`stead model set --review`). It is a\n"
                "fresh context, not an independent model.\n")
    body = (f"# Independent review: {contrib.get('title') or contrib.get('id')}\n\n"
            f"Verdict: **{verdict}**.\n\n"
            f"{str(result.get('reason') or '').strip()}\n\n"
            + note)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return {"id": doc_id, "path": path.relative_to(root).as_posix(),
            "verdict": verdict}


_STAMP_RE = re.compile(r"(\d{8}T\d{6}Z)(?:-(\d+))?$")


def _record_order(path: Path) -> tuple[str, int]:
    """Sort key for build records: the UTC stamp in the file name, then the
    same-second collision counter (`-2`, `-3`). `created` is only a date, so
    two records from one day would tie on it."""
    match = _STAMP_RE.search(path.stem)
    if match is None:
        return ("", 0)
    return (match.group(1), int(match.group(2) or 1))


def _records_for_branch(root: Path, repo_id: str, branch: str) -> list[dict]:
    """Every build record for one branch, oldest first."""
    found = []
    for path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags or f"repo:{repo_id}".lower() not in tags:
            continue
        if meta.get("branch") != branch:
            continue
        found.append((_record_order(path), meta))
    found.sort(key=lambda item: item[0])
    return [meta for _order, meta in found]


def record_for_branch(root: Path, repo_id: str, branch: str) -> dict | None:
    """The newest build record for one branch, whatever its outcome.

    Branch names are deterministic per spec, so one name can carry several
    attempts: a delivered build, then a rebuild that failed or was killed. The
    branch holds the latest attempt, so the latest record is the one that
    describes it. The watch loop and the build use this to tell 'already
    built' from 'failed here'."""
    records = _records_for_branch(root, repo_id, branch)
    return records[-1] if records else None


def delivered_record_for_branch(root: Path, repo_id: str,
                                branch: str) -> dict | None:
    """The newest delivered (not failed) build record for one branch. Merge
    pins to its commit, so a later failed attempt never unpins a merge."""
    for meta in reversed(_records_for_branch(root, repo_id, branch)):
        if str(meta.get("outcome") or "") != "failed":
            return meta
    return None


def _apply_merged(root: Path, contribution_ref: str) -> list[str]:
    """Mark the contribution merged and close linked tasks. Returns what changed."""
    found = objects.find(root, "contribution", contribution_ref)
    if found is None:
        return []
    _path, contrib, _body = found
    updated: list[str] = []
    if contrib.get("state") != "merged":
        _patch(root, "contribution", contribution_ref, {"state": "merged"})
        updated.append(contribution_ref)
    # A drafted spec merges; the raw issue it came from closes. On an own repo
    # the PR said "Closes #N", so GitHub closed it too, and sync (which fetches
    # open issues only) would never see that. Elsewhere the PR only tracks the
    # issue, so it stays open.
    linked = {contribution_ref, str(contrib.get("id") or "")}
    source_ref = str(contrib.get("drafted_from") or "")
    if source_ref:
        linked.add(source_ref)
        source = objects.find(root, "contribution", source_ref)
        repo = objects.find(root, "repo", str(contrib.get("repo") or ""))
        own = repo is not None and repo[1].get("kind") == "own"
        if source is not None and own and source[1].get("state") == "open":
            _patch(root, "contribution", source_ref, {"state": "closed"})
            updated.append(source_ref)
    for path, meta, _body in objects.iter_objects(root, "task"):
        related = meta.get("related") or []
        if isinstance(related, str):
            related = [related]
        if linked & {str(r) for r in related}:
            if meta.get("status") != "done":
                _patch(root, "task", meta.get("id") or path.stem, {"status": "done"})
                updated.append(str(meta.get("id") or path.stem))
    return updated


def _latest_record(root: Path, contribution_ref: str):
    """The newest build record for one contribution (any outcome)."""
    found = []
    for path, meta, body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags:
            continue
        if str(meta.get("contribution") or "") != contribution_ref:
            continue
        found.append((path, meta, body))
    found.sort(key=lambda item: (str(item[1].get("created") or ""),
                                 _record_order(item[0])), reverse=True)
    return found[0] if found else None


def mark_merged(root: Path, contribution_ref: str, *, url: str = "",
                head_sha: str = "") -> dict:
    """`stead factory merge` updates the existing build record to merged (it
    does not write a second one) and applies the linked statuses. A human
    merge is reconciled later by sync, not here."""
    updated = _apply_merged(root, contribution_ref)
    latest = _latest_record(root, contribution_ref)
    if latest is not None:
        path, meta, _body = latest
        fields = {"outcome": "merged"}
        if url:
            fields["merged_url"] = url
        recorded = str(meta.get("commit") or "")
        if head_sha and recorded:
            fields["human_edits"] = human_edits(root, meta, head_sha)
        _patch(root, "document", meta.get("id") or path.stem, fields)
    return {"outcome": "merged", "updated": updated}


def mark_published(root: Path, repo_id: str, branch: str, url: str) -> dict | None:
    """`stead factory publish` (run on its own, after a build) points the
    branch's delivered record at the pull request, so `sync github` can
    reconcile the merge later. `build --publish` writes the url into the new
    record itself and does not come through here."""
    meta = delivered_record_for_branch(root, repo_id, branch)
    if meta is None or not url:
        return None
    fields = {"pr_url": url}
    if str(meta.get("outcome") or "") == "committed":
        fields["outcome"] = "published"
    _patch(root, "document", str(meta.get("id") or ""), fields)
    return {"id": meta.get("id"), **fields}


def mark_commented(root: Path, contribution_ref: str) -> None:
    """Mark the newest build record for a spec as commented, so the cockpit
    pipeline stops offering the (idempotent) comment action after it runs."""
    best = None
    for path, meta, _body in objects.iter_objects(root, "document"):
        if RECORD_TAG not in {str(t).lower() for t in (meta.get("tags") or [])}:
            continue
        if str(meta.get("contribution") or "") != contribution_ref:
            continue
        if best is None or str(meta.get("updated") or "") >= str(best[1].get("updated") or ""):
            best = (path, meta)
    if best is not None:
        _patch(root, "document", str(best[1].get("id") or ""), {"commented": "true"})


def _git_out(code: Path, args: list[str], stdin: str | None = None) -> str | None:
    """stdout of one local git command, or None when it fails."""
    try:
        done = subprocess.run(["git", *args], cwd=code, input=stdin,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _patch_id(code: Path, old: str, new: str) -> str | None:
    """A stable id for the change from ``old`` to ``new`` that ignores line
    numbers, so the same change on a newer base gets the same id."""
    diff = _git_out(code, ["diff", "--no-color", "--no-ext-diff", old, new])
    if diff is None:
        return None
    if not diff.strip():
        return ""
    out = _git_out(code, ["patch-id", "--stable"], stdin=diff)
    return out.split()[0] if out and out.split() else None


def only_base_merges(code: Path, recorded: str, head: str) -> bool | None:
    """Whether every commit between the build's commit and the PR head is a
    clean merge of the base branch (GitHub's "Update branch").

    True: the branch only took in the base, so its own change is still the
    build's. False: a commit on the branch line added or changed something, a
    merge resolved a conflict differently, or history was rewritten. None:
    it can't be told from the local checkout (missing objects, git error).

    The PR head may exist only on GitHub, so its objects are fetched first
    (best effort, objects only; nothing is pushed)."""
    _git_out(code, ["fetch", "-q", "origin", head])
    for sha in (recorded, head):
        if _git_out(code, ["cat-file", "-e", f"{sha}^{{commit}}"]) is None:
            return None
    if _git_out(code, ["merge-base", "--is-ancestor", recorded, head]) is None:
        return False
    rows = _git_out(code, ["rev-list", "--first-parent", "--parents", f"{recorded}..{head}"])
    if rows is None:
        return None
    for row in rows.splitlines():
        shas = row.split()
        if not shas:
            continue
        commit, parents = shas[0], shas[1:]
        if len(parents) != 2:
            return False  # a commit made on the branch itself
        branch_side, base_side = parents
        fork = _git_out(code, ["merge-base", branch_side, base_side])
        if fork is None:
            return None
        before = _patch_id(code, fork.strip(), branch_side)
        after = _patch_id(code, base_side, commit)
        if before is None or after is None:
            return None
        if before != after:
            return False
    return True


def _code_for(root: Path, meta: dict) -> Path | None:
    for tag in meta.get("tags") or []:
        text = str(tag)
        if not text.lower().startswith("repo:"):
            continue
        found = objects.find(root, "repo", text[len("repo:"):])
        if found is None:
            continue
        code_path = str(found[1].get("code_path") or "")
        if code_path and Path(code_path).is_dir():
            return Path(code_path)
    return None


def human_edits(root: Path, meta: dict, head: str) -> str:
    """Return "true" when the merged PR head carries changes the build did not make.

    A different head SHA alone is not enough: under a strict up-to-date rule
    nearly every PR is updated from the base before merge, and that merge is
    not an edit. When the local checkout can't tell, a different head counts
    as an edit, as before."""
    recorded = str(meta.get("commit") or "")
    if not head or not recorded or head == recorded:
        return "false"
    code = _code_for(root, meta)
    clean = only_base_merges(code, recorded, head) if code is not None else None
    return "false" if clean else "true"


def mark_correct(root: Path, record_ref: str, correct: bool) -> dict:
    """Record the hand-check verdict for one build record.

    ``committed`` is mechanical (a change was produced); ``correct`` is the
    correctness-rubric verdict — every acceptance criterion actually satisfied,
    fail-before/pass-after holds, CI green. It is set by a person, never by the
    build, so an unmarked build cannot masquerade as a success.
    """
    found = objects.find(root, "document", record_ref)
    if found is None:
        raise WritebackError(f"build record not found: {record_ref}")
    path, meta, _body = found
    tags = {str(t).lower() for t in (meta.get("tags") or [])}
    if RECORD_TAG not in tags:
        raise WritebackError(f"{record_ref} is not a build record")
    verdict = "true" if correct else "false"
    _patch(root, "document", meta.get("id") or path.stem, {"correct": verdict})
    return {"id": meta.get("id") or path.stem, "correct": verdict}


def reconcile_records(root: Path, view_pr) -> dict:
    """Reconcile build records against live PR state. READ-ONLY: view_pr(url)
    returns the gh pr view JSON ({state, headRefOid, ...}) or None. A merged PR
    updates the record's outcome and flags human edits (the head carries
    changes beyond the recorded commit; merges of the base branch don't
    count); a closed-unmerged PR becomes 'closed'. This is how a human merge
    under the pr ceiling reaches the ledger."""
    reconciled: list[str] = []
    for path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags:
            continue
        pr_url = meta.get("pr_url")
        if not pr_url:
            continue
        if str(meta.get("outcome") or "") in ("merged", "closed", "failed"):
            continue
        try:
            data = view_pr(pr_url)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        state = str(data.get("state") or "").upper()
        fields: dict = {}
        if state == "MERGED":
            fields["outcome"] = "merged"
            fields["human_edits"] = human_edits(root, meta, str(data.get("headRefOid") or ""))
            if data.get("mergedAt"):
                fields["merged_at"] = str(data.get("mergedAt"))
            contrib_ref = str(meta.get("contribution") or "")
            if contrib_ref:
                _apply_merged(root, contrib_ref)
        elif state == "CLOSED":
            fields["outcome"] = "closed"
        else:
            continue  # still open; nothing to reconcile yet
        _patch(root, "document", meta.get("id") or path.stem, fields)
        reconciled.append(str(meta.get("id") or path.stem))
    return {"reconciled": len(reconciled), "ids": reconciled}


def reconcile_pr_state(root: Path, view_pr, repos: list[str] | None = None) -> dict:
    """Reconcile cached open PR contributions against live PR state. READ-ONLY:
    view_pr(url) returns the gh pr view JSON ({state, ...}) or None. A merged or
    closed PR stops showing as open, so the contribution list stays honest.

    ``repos`` (OWNER/NAME, the resolved sync scope) limits which cached PRs are
    checked; an empty/None scope means every repo."""
    scope = {n.lower() for n in (repos or [])}
    reconciled: list[str] = []
    for path, meta, _body in objects.iter_objects(root, "contribution"):
        if str(meta.get("kind") or "") != "pr":
            continue
        if str(meta.get("state") or "") != "open":
            continue
        pr_url = str(meta.get("url") or "")
        if not pr_url:
            continue
        if scope and _pr_owner_name(pr_url).lower() not in scope:
            continue
        try:
            data = view_pr(pr_url)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        state = str(data.get("state") or "").upper()
        if state == "MERGED":
            new_state = "merged"
        elif state == "CLOSED":
            new_state = "closed"
        else:
            continue
        _patch(root, "contribution", meta.get("id") or path.stem, {"state": new_state})
        reconciled.append(str(meta.get("id") or path.stem))
    return {"reconciled": len(reconciled), "ids": reconciled}


def _pr_owner_name(url: str) -> str:
    """OWNER/NAME from a GitHub PR/issue url, or "" when it can't be read."""
    url = (url or "").rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/", "github.com/"):
        if url.startswith(prefix):
            parts = url[len(prefix):].split("/")
            if len(parts) >= 2:
                return f"{parts[0]}/{parts[1]}"
    return ""


def issue_started(root: Path, issue_id: str) -> bool:
    """Whether a cached issue has local work: a drafted spec, an approval, or a
    build record. A 'started' issue is kept (and flagged) when GitHub closes it;
    an unstarted one is safe to drop from the cache."""
    found = objects.find(root, "contribution", issue_id)
    if found is not None and found[1].get("spec_sha"):
        return True
    draft_ids: list[str] = []
    for _path, meta, _body in objects.iter_objects(root, "contribution"):
        if str(meta.get("drafted_from") or "") == issue_id:
            draft_ids.append(str(meta.get("id") or ""))
            if meta.get("spec_sha"):
                return True
    if draft_ids:
        return True
    linked = {issue_id, *draft_ids}
    for _path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG in tags and str(meta.get("contribution") or "") in linked:
            return True
    return False


def reconcile_issue_state(root: Path, view_issue, repos: list[str] | None = None) -> dict:
    """Reconcile cached open issues against live GitHub state. READ-ONLY:
    ``view_issue(url)`` returns ``gh issue view --json state`` or None.

    An issue GitHub closed is dropped from the cache when it was never started
    (no draft, approval, or build record). A started issue is marked closed so it
    stays visible and can be deleted deliberately. ``repos`` limits the scope
    exactly like reconcile_pr_state."""
    scope = {n.lower() for n in (repos or [])}
    removed: list[str] = []
    closed: list[str] = []
    for path, meta, _body in objects.iter_objects(root, "contribution"):
        if str(meta.get("kind") or "") != "issue":
            continue
        if meta.get("drafted_from"):
            continue  # a locally drafted spec, not a cached GitHub issue
        if str(meta.get("state") or "") != "open":
            continue
        url = str(meta.get("url") or "")
        if not url:
            continue
        if scope and _pr_owner_name(url).lower() not in scope:
            continue
        try:
            data = view_issue(url)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        if str(data.get("state") or "").upper() != "CLOSED":
            continue
        issue_id = str(meta.get("id") or path.stem)
        if issue_started(root, issue_id):
            _patch(root, "contribution", issue_id, {"state": "closed"})
            closed.append(issue_id)
        else:
            path.unlink(missing_ok=True)
            removed.append(issue_id)
    return {"removed": removed, "closed": closed}


def _patch(root: Path, otype: str, ref: str, fields: dict) -> None:
    found = objects.find(root, otype, ref)
    if found is None:
        return
    path, meta, body = found
    meta.update(fields)
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")


def prior_records(root: Path, repo_id: str, limit: int = 5) -> list[tuple[Path, dict, str]]:
    """Recent *delivered* build records for one repo, newest first. Failed
    records are excluded: their raw error and check output must not become
    trusted-looking context for the next build."""
    found = []
    for path, meta, body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags or f"repo:{repo_id}".lower() not in tags:
            continue
        if str(meta.get("outcome") or "") == "failed":
            continue
        found.append((path, meta, body))
    found.sort(key=lambda item: str(item[1].get("created") or ""), reverse=True)
    return found[:limit]


def build_failure_attempts(root: Path, repo_id: str, spec_sha: str) -> int:
    """How many build-class failures exist for one approved spec hash.

    A build-class failure (protocol, gate, checks, budget, tamper, build)
    consumes the spec's single automatic attempt; an infrastructure failure
    (the model was down or timed out) does not. Keyed on the approval hash, so
    re-approval grants a fresh attempt."""
    count = 0
    for _path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags or f"repo:{repo_id}".lower() not in tags:
            continue
        if str(meta.get("outcome") or "") != "failed":
            continue
        if str(meta.get("reason") or "build") == "infrastructure":
            continue
        if spec_sha and str(meta.get("spec_sha") or "") == spec_sha:
            count += 1
    return count


def propose_note(root: Path, kind: str, title: str, text: str,
                 source: str = "") -> dict:
    """An interpretive proposal goes to the inbox, not into context/."""
    kind = (kind or "decision").strip().lower()
    if kind not in {"decision", "glossary"}:
        raise WritebackError("propose kind must be decision or glossary")
    title = (title or "").strip()
    text = (text or "").strip()
    if not title or not text:
        raise WritebackError("a proposal needs a title and text")
    folder = root / "inbox"
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or kind
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = folder / f"propose-{kind}-{slug[:40]}-{stamp}.md"
    n = 2
    while path.exists():
        path = folder / f"propose-{kind}-{slug[:40]}-{stamp}-{n}.md"
        n += 1
    body = (f"# Proposed {kind}: {title}\n\n{text}\n\n"
            f"Proposed by a build{(' from ' + source) if source else ''}. "
            "Triage into context/documents/ if it is worth keeping.\n")
    path.write_text(body, encoding="utf-8")
    return {"path": path.relative_to(root).as_posix(), "kind": kind, "title": title}
