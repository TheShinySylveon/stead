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
        "contribution": str(contrib.get("id") or contribution_ref),
        "spec_sha": spec_sha_of(root, contribution_ref),
        "checks_mode": str(result.get("checks_mode") or "none"),
        "elapsed_seconds": str(result.get("elapsed_seconds") or 0),
        "repair_rounds": str(result.get("repair_rounds") or 0),
        "chars_sent": str(result.get("chars_sent") or 0),
        "chars_received": str(result.get("chars_received") or 0),
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


def record_for_branch(root: Path, repo_id: str, branch: str) -> dict | None:
    """The build record for one branch, preferring a delivered one over a
    failed one. Lets the watch loop tell 'already built' from 'failed here'."""
    fallback = None
    for _path, meta, _body in objects.iter_objects(root, "document"):
        tags = {str(t).lower() for t in (meta.get("tags") or [])}
        if RECORD_TAG not in tags or f"repo:{repo_id}".lower() not in tags:
            continue
        if meta.get("branch") != branch:
            continue
        if str(meta.get("outcome") or "") != "failed":
            return meta
        fallback = meta
    return fallback


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
    for path, meta, _body in objects.iter_objects(root, "task"):
        related = meta.get("related") or []
        if isinstance(related, str):
            related = [related]
        if contribution_ref in related or contrib.get("id") in related:
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
    found.sort(key=lambda item: str(item[1].get("created") or ""), reverse=True)
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
            fields["human_edits"] = "true" if head_sha != recorded else "false"
        _patch(root, "document", meta.get("id") or path.stem, fields)
    return {"outcome": "merged", "updated": updated}


def reconcile_records(root: Path, view_pr) -> dict:
    """Reconcile build records against live PR state. READ-ONLY: view_pr(url)
    returns the gh pr view JSON ({state, headRefOid, ...}) or None. A merged PR
    updates the record's outcome and flags human edits (head SHA differs from
    the recorded commit); a closed-unmerged PR becomes 'closed'. This is how a
    human merge under the pr ceiling reaches the ledger."""
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
            head = str(data.get("headRefOid") or "")
            recorded = str(meta.get("commit") or "")
            fields["human_edits"] = "true" if (head and recorded and head != recorded) else "false"
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
