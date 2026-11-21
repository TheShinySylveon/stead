"""Read-only GitHub sync via the open-source `gh` CLI (stdlib subprocess).

Design rules (locked):
- READ-ONLY: only `gh search`, `gh pr view`, `gh api user` (GET). This module
  never creates/issues/comments/labels/pushes anything. No remote writes.
- Explicit/on-demand: sync runs only when the user invokes `ctx sync github`.
- Local-first + offline-capable: results are cached as markdown contribution
  files (flat frontmatter, visibility: public) under context/contributions/,
  mirrored into state.db. `--offline` skips the network and re-indexes files.
- Files are the source of truth: `ctx init` rebuilds the index without gh.
- `gh` is an external open-source tool (like git), NOT a pip dependency.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from ctx import db, frontmatter, objects

GH_TIMEOUT = 60  # seconds per gh call
SEARCH_FIELDS = "number,title,url,state,repository,createdAt,updatedAt"

# gh search state values map 1:1 onto our ontology (open|closed|merged).
_STATES = ("open", "closed", "merged")
_FAIL = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE", "ERROR"}
_PASS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_PENDING = {"QUEUED", "IN_PROGRESS", "PENDING", "WAITING", "REQUESTED", "EXPECTED"}


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "repo"


def _run_gh(args: list[str]) -> subprocess.CompletedProcess:
    """One read-only gh invocation. Raises SystemExit with guidance on failure."""
    try:
        proc = subprocess.run(["gh", *args], capture_output=True, text=True,
                              timeout=GH_TIMEOUT)
    except FileNotFoundError:
        raise SystemExit(
            "gh CLI not found on PATH. Install it (https://cli.github.com) and "
            "run `gh auth login`, or use `ctx sync github --offline` to re-index "
            "the local cache without network.") from None
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"gh timed out after {GH_TIMEOUT}s ({' '.join(args[:3])}...). "
            "Check your network, or use `ctx sync github --offline`.") from None
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if "auth login" in err or "not logged" in err or "authentication" in err.lower():
            raise SystemExit(
                "gh is not authenticated. Run `gh auth login` (read-only scopes "
                "are enough), or use `ctx sync github --offline`.")
        raise SystemExit(f"gh failed ({' '.join(args[:3])}...): {err[:400]}")
    return proc


def _gh_json(args: list[str]):
    return json.loads(_run_gh(args).stdout or "null")


def _ci_from_rollup(rollup: list) -> str:
    """Aggregate GitHub statusCheckRollup into pending|pass|fail|none."""
    if not rollup:
        return "none"
    verdicts = []
    for check in rollup:
        conclusion = (check.get("conclusion") or check.get("state") or "").upper()
        status = (check.get("status") or "").upper()
        if conclusion in _FAIL:
            verdicts.append("fail")
        elif conclusion in _PASS:
            verdicts.append("pass")
        elif status in _PENDING or conclusion in _PENDING or not conclusion:
            verdicts.append("pending")
        else:
            verdicts.append("pending")
    if "fail" in verdicts:
        return "fail"
    if "pending" in verdicts:
        return "pending"
    return "pass"


def _review_decision(value: str | None) -> str:
    return {"APPROVED": "approved", "CHANGES_REQUESTED": "changes",
            "REVIEW_REQUIRED": "requested"}.get((value or "").upper(), "none")


def _enrich_pr(url: str) -> tuple[str, str]:
    """Best-effort read-only CI + review decision for one PR (gh pr view)."""
    try:
        data = _gh_json(["pr", "view", url, "--json", "statusCheckRollup,reviewDecision"])
    except SystemExit:
        return "none", "none"  # enrichment is optional; search data still caches
    if not isinstance(data, dict):
        return "none", "none"
    return (_ci_from_rollup(data.get("statusCheckRollup") or []),
            _review_decision(data.get("reviewDecision")))


def fetch_contributions(author: str = "@me", limit: int = 30) -> list[dict]:
    """Fetch the user's open PRs (author), review-requested PRs, and assigned
    issues across repos. READ-ONLY. Returns normalized item dicts, deduped."""
    login = None
    try:
        login = (_run_gh(["api", "user", "--jq", ".login"]).stdout or "").strip() or None
    except SystemExit:
        pass  # kind falls back to 'oss' for newly seen repos

    queries = [
        (["search", "prs", "--author", author, "--state", "open"], "pr", "author"),
        (["search", "prs", "--review-requested", author, "--state", "open"], "pr", "reviewer"),
        (["search", "issues", "--assignee", author, "--state", "open"], "issue", "assignee"),
    ]
    items: dict[tuple, dict] = {}
    for base, kind, role in queries:
        results = _gh_json(base + ["--limit", str(limit), "--json", SEARCH_FIELDS]) or []
        for r in results:
            repo_full = (r.get("repository") or {}).get("nameWithOwner") or ""
            if not repo_full or "/" not in repo_full:
                continue
            number = int(r.get("number", 0))
            key = (repo_full.lower(), kind, number)
            if key in items:
                continue  # first role wins (author > reviewer > assignee)
            state = (r.get("state") or "open").lower()
            item = {
                "repo_full": repo_full, "kind": kind, "number": number,
                "title": r.get("title") or f"{kind} #{number}",
                "url": r.get("url") or f"https://github.com/{repo_full}/"
                                       f"{'pull' if kind == 'pr' else 'issues'}/{number}",
                "state": state if state in _STATES else "open",
                "role": role, "ci": "none",
                "review": "requested" if role == "reviewer" else "none",
            }
            if kind == "pr":
                ci, decision = _enrich_pr(item["url"])
                item["ci"] = ci
                if decision != "none":
                    item["review"] = decision
            items[key] = item
    return list(items.values())


def ensure_repo(root: Path, repo_full: str, login: str | None, today: str) -> str:
    """Create context/repos/<slug>.md if missing; return the repo id.
    Existing repo files are left untouched (user edits win)."""
    slug = _slugify(repo_full.replace("/", "-"))
    path = root / "context" / "repos" / f"{slug}.md"
    repo_id = f"repo-{slug}"
    if path.exists():
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        return meta.get("id", repo_id)
    owner = repo_full.split("/", 1)[0]
    kind = "own" if login and owner.lower() == login.lower() else "oss"
    meta = {"id": repo_id, "type": "repo", "title": repo_full,
            "created": today, "updated": today, "status": "active",
            "kind": kind, "url": f"https://github.com/{repo_full}"}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(
        meta, f"# {repo_full}\n\nAuto-created by `ctx sync github` (read-only).\n"),
        encoding="utf-8")
    return repo_id


def write_contribution(root: Path, item: dict, login: str | None, today: str) -> tuple[Path, bool]:
    """Upsert one contribution markdown file. Returns (path, is_new).
    Sync updates GitHub-derived fields; user edits (body, tags, role, created)
    are preserved."""
    repo_id = ensure_repo(root, item["repo_full"], login, today)
    slug = _slugify(item["repo_full"].replace("/", "-"))
    stem = f"{slug}-{item['kind']}-{item['number']}"
    path = root / "context" / "contributions" / f"{stem}.md"
    contrib_id = f"contribution-{stem}"
    is_new = not path.exists()
    if is_new:
        meta = {"id": contrib_id, "type": "contribution", "created": today}
        body = (f"# {item['title']}\n\n"
                f"{item['kind'].upper()} #{item['number']} in {item['repo_full']} — {item['url']}\n\n"
                f"Cached read-only from GitHub by `ctx sync github` on {today}.\n"
                f"GitHub is authoritative for live state; this file is the local,\n"
                f"offline-capable cache. Add private strategy notes in context/documents/,\n"
                f"not here (contribution files are public GitHub-derived data).\n")
    else:
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta.setdefault("id", contrib_id)
        meta.setdefault("type", "contribution")
        meta.setdefault("created", today)
    # GitHub-derived fields (sync-owned):
    meta.update({"title": item["title"], "updated": today, "repo": repo_id,
                 "kind": item["kind"], "number": item["number"], "url": item["url"],
                 "state": item["state"], "ci": item["ci"], "review": item["review"],
                 "visibility": "public"})
    meta.setdefault("role", item["role"])  # respect a manually set role
    meta.setdefault("method", "spec-kit")  # user-owned choice; sync never overrides it
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
    return path, is_new


def sync_github(root: Path, author: str = "@me", limit: int = 30,
                offline: bool = False) -> dict:
    """Explicit, read-only GitHub sync. With --offline, only re-index the
    local markdown cache (no gh, no network)."""
    db.require_db(root)
    today = date.today().isoformat()
    if not offline:
        if shutil.which("gh") is None:
            raise SystemExit(
                "gh CLI not found on PATH. Install it (https://cli.github.com) "
                "and run `gh auth login`, or use `ctx sync github --offline` to "
                "re-index the local cache without network.")
        items = fetch_contributions(author=author, limit=limit)
        login = None
        try:
            login = (_run_gh(["api", "user", "--jq", ".login"]).stdout or "").strip() or None
        except SystemExit:
            pass
        n_new = n_updated = 0
        for item in items:
            _path, is_new = write_contribution(root, item, login, today)
            n_new += is_new
            n_updated += not is_new
    else:
        items, n_new, n_updated = [], 0, 0

    conn = db.connect(root)
    try:
        counts = db.reindex_github(conn, root)
        conn.commit()
    finally:
        conn.close()
    return {"offline": offline, "fetched": len(items), "new": n_new,
            "updated": n_updated, **counts}
