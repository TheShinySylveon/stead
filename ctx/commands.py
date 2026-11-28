"""Shared command handlers and validation choices for the CLI and cockpit."""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from ctx import db, factory, frontmatter, objects, sync

TASK_STATUSES = ("to-do", "doing", "done", "blocked")
REPO_KINDS = ("own", "oss")
REPO_STATUSES = ("active", "paused", "archived")
CONTRIB_KINDS = ("issue", "pr")
CONTRIB_ROLES = ("author", "assignee", "reviewer")
CONTRIB_STATES = ("open", "closed", "merged")
CONTRIB_CI = ("pending", "pass", "fail", "none")
CONTRIB_REVIEW = ("requested", "approved", "changes", "none")
CONTRIB_METHODS = factory.CONTRIB_METHODS  # builtin | spec-kit (single source of truth)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "task"


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _info(msg: str) -> None:
    """Status feedback to stderr, keeping stdout for the command's actual
    output (tables, JSON, report text)."""
    print(msg, file=sys.stderr)


def cmd_task_add(root: Path, title: str, project: str, status: str = "to-do") -> int:
    db.require_db(root)
    if status not in TASK_STATUSES:
        raise SystemExit(f"invalid status {status!r}; choose from {TASK_STATUSES}")
    proj = objects.find(root, "project", project)
    if proj is None:
        raise SystemExit(f"project not found: {project!r} — create it in context/projects/ first")
    project_id = proj[1]["id"]

    slug = _slugify(title)
    task_id, n = f"task-{slug}", 2
    while (root / "context" / "tasks" / f"{task_id.removeprefix('task-')}.md").exists():
        task_id, n = f"task-{slug}-{n}", n + 1
    stem = task_id.removeprefix("task-")

    today = date.today().isoformat()
    meta = {"id": task_id, "type": "task", "title": title,
            "created": today, "updated": today, "status": status, "project": project_id}
    from ctx.actors import stamp
    stamp(root, meta)
    path = root / "context" / "tasks" / f"{stem}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(meta, f"# {title}\n"), encoding="utf-8")

    conn = db.connect(root)
    try:
        conn.execute(
            "INSERT INTO tasks (id, title, project, status, path, created, updated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (task_id, title, project_id, status, _rel(root, path), today, today))
        conn.commit()
    finally:
        conn.close()
    _info(f"added {task_id} [{status}] -> {_rel(root, path)}")
    return 0


def cmd_task_set(root: Path, task_id: str, status: str) -> int:
    db.require_db(root)
    if status not in TASK_STATUSES:
        raise SystemExit(f"invalid status {status!r}; choose from {TASK_STATUSES}")
    found = objects.find(root, "task", task_id)
    if found is None:
        raise SystemExit(f"task not found: {task_id!r}")
    path, meta, body = found
    meta["status"] = status
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")

    conn = db.connect(root)
    try:
        conn.execute("UPDATE tasks SET status = ?, updated = ? WHERE id = ?",
                     (status, meta["updated"], meta["id"]))
        conn.commit()
    finally:
        conn.close()
    print(f"{meta['id']} -> {status} (file + index updated)")
    return 0


def _repo_slug(title: str, url: str | None) -> str:
    if not url:
        return _slugify(title)
    url = url.strip()
    if url.startswith(("git@github.com:", "github.com:")):
        path = url.partition(":")[2]
    else:
        try:
            remote = urlsplit("//" + url if url.startswith("github.com/") else url)
            path = remote.path.removeprefix("/") if remote.hostname == "github.com" else ""
        except ValueError:
            path = ""
    owner, _, repo = path.removesuffix("/").partition("/")
    repo = repo.removesuffix(".git")
    if re.fullmatch(r"[A-Za-z0-9_-]+", owner) and re.fullmatch(r"[A-Za-z0-9_.-]+", repo):
        return _slugify(f"{owner}-{repo}")
    return _slugify(title)


def cmd_repo_add(root: Path, title: str, url: str | None = None, kind: str = "oss",
                 status: str = "active", default_branch: str | None = None,
                 contributing: str | None = None, notes: str | None = None) -> int:
    db.require_db(root)
    if kind not in REPO_KINDS:
        raise SystemExit(f"invalid kind {kind!r}; choose from {REPO_KINDS}")
    if status not in REPO_STATUSES:
        raise SystemExit(f"invalid status {status!r}; choose from {REPO_STATUSES}")
    slug = _repo_slug(title, url)
    n = 2
    while (root / "context" / "repos" / f"{slug}.md").exists():
        slug, n = f"{_repo_slug(title, url)}-{n}", n + 1
    repo_id = f"repo-{slug}"
    today = date.today().isoformat()
    meta = {"id": repo_id, "type": "repo", "title": title,
            "created": today, "updated": today, "status": status, "kind": kind}
    for key, value in (("url", url), ("default_branch", default_branch),
                       ("contributing", contributing), ("notes", notes)):
        if value:
            meta[key] = value
    from ctx.actors import stamp
    stamp(root, meta)
    path = root / "context" / "repos" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(meta, f"# {title}\n"), encoding="utf-8")

    conn = db.connect(root)
    try:
        db.index_repo(conn, root, path, meta, today)
        conn.commit()
    finally:
        conn.close()
    _info(f"added {repo_id} [{kind}] -> {_rel(root, path)}")
    return 0


def cmd_contribution_add(root: Path, title: str, repo: str, kind: str, number: int,
                         url: str | None = None, role: str = "author",
                         state: str = "open", ci: str = "none",
                         review: str = "none", method: str = "spec-kit") -> int:
    db.require_db(root)
    for label, value, allowed in (("kind", kind, CONTRIB_KINDS),
                                  ("role", role, CONTRIB_ROLES),
                                  ("state", state, CONTRIB_STATES),
                                  ("ci", ci, CONTRIB_CI),
                                  ("review", review, CONTRIB_REVIEW),
                                  ("method", method, CONTRIB_METHODS)):
        if value not in allowed:
            raise SystemExit(f"invalid {label} {value!r}; choose from {allowed}")
    found = objects.find(root, "repo", repo)
    if found is None:
        raise SystemExit(f"repo not found: {repo!r} — add it with `stead repo add` first")
    _rpath, rmeta, _rbody = found
    repo_id = rmeta["id"]
    stem = f"{repo_id.removeprefix('repo-')}-{kind}-{number}"
    path = root / "context" / "contributions" / f"{stem}.md"
    if path.exists():
        raise SystemExit(f"contribution already exists: contribution-{stem} "
                         "— use `stead contribution set` to update it")
    if not url and rmeta.get("url"):
        url = f"{rmeta['url'].rstrip('/')}/{'pull' if kind == 'pr' else 'issues'}/{number}"
    today = date.today().isoformat()
    meta = {"id": f"contribution-{stem}", "type": "contribution", "title": title,
            "created": today, "updated": today, "repo": repo_id, "kind": kind,
            "number": number, "role": role, "state": state, "ci": ci,
            "review": review, "method": method, "visibility": "public"}
    if url:
        meta["url"] = url
    from ctx.actors import stamp
    stamp(root, meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(meta, f"# {title}\n"), encoding="utf-8")

    conn = db.connect(root)
    try:
        db.index_contribution(conn, root, path, meta, today)
        conn.commit()
    finally:
        conn.close()
    _info(f"added contribution-{stem} [{kind} #{number}, {role}] -> {_rel(root, path)}")
    return 0


def cmd_contribution_set(root: Path, contrib_id: str, state: str | None = None,
                         ci: str | None = None, review: str | None = None,
                         role: str | None = None, method: str | None = None) -> int:
    db.require_db(root)
    updates = {}
    for label, value, allowed in (("state", state, CONTRIB_STATES),
                                  ("ci", ci, CONTRIB_CI),
                                  ("review", review, CONTRIB_REVIEW),
                                  ("role", role, CONTRIB_ROLES),
                                  ("method", method, CONTRIB_METHODS)):
        if value is not None:
            if value not in allowed:
                raise SystemExit(f"invalid {label} {value!r}; choose from {allowed}")
            updates[label] = value
    if not updates:
        raise SystemExit("nothing to set — pass at least one of "
                         "--state/--ci/--review/--role/--method")
    found = objects.find(root, "contribution", contrib_id)
    if found is None:
        raise SystemExit(f"contribution not found: {contrib_id!r}")
    path, meta, body = found
    meta.update(updates)
    meta["updated"] = date.today().isoformat()
    from ctx.actors import stamp
    stamp(root, meta)
    path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")

    conn = db.connect(root)
    try:
        db.index_contribution(conn, root, path, meta, meta["updated"])
        conn.commit()
    finally:
        conn.close()
    changed = ", ".join(f"{k}={v}" for k, v in updates.items())
    print(f"{meta['id']} -> {changed} (file + index updated)")
    return 0


def cmd_sync_github(root: Path, author: str = "@me", limit: int = 30,
                    offline: bool = False, *, digest: bool = False,
                    repos: list[str] | None = None, all_repos: bool = False,
                    remember: bool = False) -> int:
    from ctx import config
    try:
        chosen = config.check_repos(repos or [])
        if remember:
            if not chosen and not all_repos:
                raise SystemExit("--remember needs --repo OWNER/NAME (to save a scope) "
                                 "or --all-repos (to clear it)")
            config.save_sync_repos(root, chosen)
            print("saved sync scope: " + (", ".join(chosen) if chosen else "every repo"))
    except config.ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    scope = chosen if chosen else ([] if all_repos else None)
    result = sync.sync_github(root, author=author, limit=limit, offline=offline,
                              repos=scope)
    if result.get("repos_scope"):
        print("scope: " + ", ".join(result["repos_scope"]))
    if result["offline"]:
        print(f"sync github --offline: no network used; re-indexed local cache "
              f"({result['repos']} repos, {result['contributions']} contributions)")
    else:
        print(f"sync github: fetched {result['fetched']} items via gh (read-only); "
              f"{result['new']} new, {result['updated']} updated contribution files")
        print(f"index now: {result['repos']} repos, {result['contributions']} contributions")
    changed = (int(result.get("new") or 0) + int(result.get("updated") or 0)
               + int(result.get("reconciled_prs") or 0))
    if digest and changed:
        print("cache changed. assembling the digest. nothing is posted.")
        return cmd_digest(root)
    if digest:
        print("cache unchanged. digest not assembled.")
        return 0
    print("next: python -m stead factory run --factory weekly-contribution-digest --shadow")
    return 0


def cmd_digest(root: Path, live: bool = False, *, generate: bool = False) -> int:
    mode = "live" if live else "shadow"
    info = _maybe_draft(root, factory.assemble_digest(root, mode=mode), generate)
    c = info["counts"]
    print(f"run {info['run_id']} recorded [{mode}] — {info['factory']} "
          f"prompt {info['prompt_version']}")
    print(f"bundle: {c['contributions']} contributions across {c['repos']} repos "
          f"(PRs in flight: {c['prs_in_flight']}, reviews awaiting: {c['reviews_awaiting']}, "
          f"claimed issues: {c['claimed_issues']}, CI flags: {c['ci_flags']})")
    print(f"run dir: {info['run_dir']}/ (bundle.md, prompt.md, run.json)")
    _print_draft(info, generate)
    return 0


def cmd_prompt_promote(root: Path, factory_name: str, version: str) -> int:
    db.require_db(root)
    if not version.startswith("v"):
        version = "v" + version
    prompt_path = root / "factories" / factory_name / "prompts" / f"{version}.md"
    if not prompt_path.exists():
        raise SystemExit(f"prompt file missing: {_rel(root, prompt_path)} — write it before promoting")
    from ctx.models import promotion_blockers
    blocked = promotion_blockers(root, factory_name, version)
    if blocked:
        raise SystemExit(
            "refusing to promote. These evals have no pass for "
            f"{version}: {', '.join(blocked)}")
    conn = db.connect(root)
    try:
        conn.execute(
            "UPDATE prompt_versions SET status = 'retired' "
            "WHERE factory = ? AND status = 'production'", (factory_name,))
        conn.execute(
            "INSERT INTO prompt_versions (factory, version, status, path, created) "
            "VALUES (?, ?, 'production', ?, ?) "
            "ON CONFLICT(factory, version) DO UPDATE SET status = 'production'",
            (factory_name, version, _rel(root, prompt_path), date.today().isoformat()))
        conn.commit()
    finally:
        conn.close()
    _info(f"{factory_name}: {version} is now production (previous production retired)")
    return 0


def _model_timeout(root: Path, what: str) -> SystemExit:
    """A clean exit for a model call that ran past its call_timeout."""
    from ctx import models
    seconds = models.public_model(root)["call_timeout"]
    return SystemExit(
        f"the model did not reply within {seconds}s, so {what} stopped. Raise the "
        "limit with `stead model set ... --call-timeout SECONDS` or use a faster "
        "model, then run it again.")


def _maybe_draft(root: Path, info: dict, generate: bool) -> dict:
    if not generate:
        return info
    from ctx import models
    try:
        text = models.draft(root, info["assembled_prompt"])
    except models.ModelError as exc:
        raise SystemExit(str(exc)) from exc
    except TimeoutError as exc:
        raise _model_timeout(root, "the draft") from exc
    return factory.write_output(root, info, text, source="model")


def _print_draft(info: dict, generate: bool, *, coding: bool = False) -> None:
    if generate and info.get("output_path"):
        print(f"draft: {info['output_path']}")
        print("draft only — nothing posted, pushed, or merged")
        if info.get("mode") == "live":
            print("recorded as live. That still does not open a pull request.")
        return
    if coding:
        print("no model call, no remote writes — hand prompt.md to a coding agent, "
              "or rerun with --generate")
    else:
        print("no model call — hand prompt.md to any agent, or rerun with --generate")
    print(f"  python -m stead run log --factory {info['factory']} --task "
          f"{info.get('contribution') or info.get('project') or info.get('task_ref') or 'contributions'} "
          f"--prompt-version {info['prompt_version']} --output TEXT --verdict approved|rejected")
    print("\n--- assembled prompt ---\n")
    print(info["assembled_prompt"])
