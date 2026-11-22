"""Read-only GitHub sync via the open-source `gh` CLI (stdlib subprocess).

Design rules (locked):
- READ-ONLY: only `gh search`, `gh pr view`, `gh api user` (GET). This module
  never creates/issues/comments/labels/pushes anything. No remote writes.
- Explicit/on-demand: sync runs only when the user invokes `stead sync github`.
- Local-first + offline-capable: results are cached as markdown contribution
  files (flat frontmatter, visibility: public) under context/contributions/,
  mirrored into state.db. `--offline` skips the network and re-indexes files.
- Files are the source of truth: `stead init` rebuilds the index without gh.
- `gh` is an external open-source tool (like git), NOT a pip dependency.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import date
from pathlib import Path

from ctx import db, frontmatter, objects

GH_TIMEOUT = 60  # seconds per gh call
SEARCH_FIELDS = "number,title,url,state,repository,createdAt,updatedAt"
BUILD_LABEL = "stead-build"  # a GitHub label that opts an issue into a build
_CACHE_NOTE = "Cached read-only from GitHub by `stead sync github`"

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
            "run `gh auth login`, or use `stead sync github --offline` to re-index "
            "the local cache without network.") from None
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"gh timed out after {GH_TIMEOUT}s ({' '.join(args[:3])}...). "
            "Check your network, or use `stead sync github --offline`.") from None
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if "auth login" in err or "not logged" in err or "authentication" in err.lower():
            raise SystemExit(
                "gh is not authenticated. Run `gh auth login` (read-only scopes "
                "are enough), or use `stead sync github --offline`.")
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


def _owner_name(repo_meta: dict) -> str:
    url = (repo_meta.get("url") or "").rstrip("/")
    for prefix in ("https://github.com/", "http://github.com/",
                   "git@github.com:", "github.com/"):
        if url.startswith(prefix):
            rest = url[len(prefix):].rstrip("/")
            if rest.endswith(".git"):
                rest = rest[:-4]
            return rest
    return ""


def _fetch_issue_body(url: str) -> str:
    """Best-effort read-only fetch of an issue body, so a draft has real text."""
    try:
        raw = _run_gh(["issue", "view", url, "--json", "body",
                       "--jq", ".body"]).stdout or ""
    except SystemExit:
        return ""
    return raw.strip()


def fetch_labeled(root: Path, login: str | None, limit: int = 30) -> list[dict]:
    """Fetch `stead-build`-labelled issues, scoped to repos you own or watch.

    A label on a stranger's repo must not pull their issues into your store, so
    the query runs once per repo (kind: own or trigger: watch), with --repo.
    Each issue's body is fetched so a later draft has real text, and a hash of
    the fetched text lets a later sync flag "changed since the draft"."""
    items: dict[tuple, dict] = {}
    for _path, meta, _body in objects.iter_objects(root, "repo"):
        if meta.get("kind") != "own" and meta.get("trigger") != "watch":
            continue
        owner_name = _owner_name(meta)
        if not owner_name or "/" not in owner_name:
            continue
        results = _gh_json(
            ["search", "issues", "--label", BUILD_LABEL, "--state", "open",
             "--repo", owner_name, "--limit", str(limit), "--json", SEARCH_FIELDS]) or []
        for r in results:
            repo_full = (r.get("repository") or {}).get("nameWithOwner") or ""
            if not repo_full or "/" not in repo_full:
                continue
            number = int(r.get("number", 0))
            key = (repo_full.lower(), "issue", number)
            if key in items:
                continue
            url = r.get("url") or f"https://github.com/{repo_full}/issues/{number}"
            state = (r.get("state") or "open").lower()
            body = _fetch_issue_body(url)
            item = {
                "repo_full": repo_full, "kind": "issue", "number": number,
                "title": r.get("title") or f"issue #{number}",
                "url": url, "state": state if state in _STATES else "open",
                "role": "author", "ci": "none", "review": "none",
                "tags": [BUILD_LABEL], "body": body, "body_fetched": True,
            }
            if body:
                item["body_sha"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
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
        meta, f"# {repo_full}\n\nAuto-created by `stead sync github` (read-only).\n"),
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
        if item.get("body_fetched"):
            # The body was fetched (possibly empty); record it distinctly from
            # the "not fetched yet" stub so spec draft can tell them apart.
            body = item.get("body") or "(the issue body is empty)\n"
        else:
            body = item.get("body") or (
                f"# {item['title']}\n\n"
                f"{item['kind'].upper()} #{item['number']} in {item['repo_full']} — {item['url']}\n\n"
                f"Cached read-only from GitHub by `stead sync github` on {today}.\n"
                f"GitHub is authoritative for live state; this file is the local,\n"
                f"offline-capable cache. Add private strategy notes in context/documents/,\n"
                f"not here (contribution files are public GitHub-derived data).\n")
    else:
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta.setdefault("id", contrib_id)
        meta.setdefault("type", "contribution")
        meta.setdefault("created", today)
        # A labelled issue previously cached without a body still has the
        # boilerplate stub; replace it with the freshly fetched text (or the
        # empty-body marker).
        if item.get("body_fetched") and (_CACHE_NOTE in body or not body.strip()):
            body = item.get("body") or "(the issue body is empty)\n"
    # GitHub-derived fields (sync-owned):
    meta.update({"title": item["title"], "updated": today, "repo": repo_id,
                 "kind": item["kind"], "number": item["number"], "url": item["url"],
                 "state": item["state"], "ci": item["ci"], "review": item["review"],
                 "visibility": "public"})
    meta.setdefault("role", item["role"])  # respect a manually set role
    meta.setdefault("method", "spec-kit")  # user-owned choice; sync never overrides it
    if item.get("body_sha"):
        # body_sha is the hash of the stored text; upstream_body_sha is the hash
        # of the freshly fetched text. They differ when the issue changed after
        # we stored it (which doctor and spec approve surface).
        meta["upstream_body_sha"] = item["body_sha"]
        meta["body_sha"] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    for tag in (item.get("tags") or []):
        tags = meta.setdefault("tags", [])
        if isinstance(tags, str):
            tags = [tags]
        if tag not in tags:
            tags.append(tag)
        meta["tags"] = tags
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
                "and run `gh auth login`, or use `stead sync github --offline` to "
                "re-index the local cache without network.")
        items = fetch_contributions(author=author, limit=limit)
        login = None
        try:
            login = (_run_gh(["api", "user", "--jq", ".login"]).stdout or "").strip() or None
        except SystemExit:
            pass
        # Label intake, scoped to repos you own or watch.
        by_key = {(i["repo_full"].lower(), i["kind"], i["number"]): i for i in items}
        for item in fetch_labeled(root, login, limit):
            key = (item["repo_full"].lower(), item["kind"], item["number"])
            if key in by_key:
                existing = by_key[key]
                existing["tags"] = list(dict.fromkeys(
                    (existing.get("tags") or []) + [BUILD_LABEL]))
                if item.get("body"):
                    existing["body"] = item["body"]
                if item.get("body_sha"):
                    existing["body_sha"] = item["body_sha"]
            else:
                by_key[key] = item
        items = list(by_key.values())
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
    reconciled = 0
    if not offline:
        # Reconcile build records against live PR state (read-only gh pr view):
        # a human merge under the pr ceiling reaches the ledger here.
        from ctx import writeback

        def view_pr(url):
            try:
                return _gh_json(["pr", "view", url, "--json", "state,headRefOid,mergedAt"])
            except SystemExit:
                return None

        reconciled = writeback.reconcile_records(root, view_pr)["reconciled"]
    return {"offline": offline, "fetched": len(items), "new": n_new,
            "updated": n_updated, "reconciled": reconciled, **counts}
