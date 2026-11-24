"""Command-line interface: `python -m stead <command>` (argparse, stdlib only).

Handlers are plain functions taking a repo root Path so they are unit-testable
and callable from any scheduler or agent without a shell.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

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


def _model_timeout(root: Path, what: str) -> SystemExit:
    """A clean exit for a model call that ran past its call_timeout."""
    from ctx import models
    seconds = models.public_model(root)["call_timeout"]
    return SystemExit(
        f"the model did not reply within {seconds}s, so {what} stopped. Raise the "
        "limit with `stead model set ... --call-timeout SECONDS` or use a faster "
        "model, then run it again.")


def _info(msg: str) -> None:
    """Status feedback to stderr, keeping stdout for the command's actual
    output (tables, JSON, report text)."""
    print(msg, file=sys.stderr)


# --- init -----------------------------------------------------------------

def cmd_init(root: Path) -> int:
    seeded = factory.seed_builtin_factories(root)
    counts = db.init_db(root)
    print(f"state.db rebuilt from ctx/schema.sql "
          f"(tasks indexed: {counts['tasks']}, repos: {counts['repos']}, "
          f"contributions: {counts['contributions']}, evals loaded: {counts['evals']}, "
          f"prompt versions seeded: {counts['prompt_versions']})")
    if seeded:
        _info(f"seeded {seeded} built-in factory definition(s) into factories/")
    from ctx.onboard import needs_welcome
    if needs_welcome(root):
        print("No projects yet. First run:")
        print("  python -m stead ui")
        print("  python -m stead welcome --title \"My Project\"")
    return 0


def cmd_metrics_mark(root: Path, record: str, correct: bool, rule: str = "") -> int:
    """`stead metrics mark`: record the hand-checked correctness verdict on one
    build record. 'Committed' is mechanical; 'correct' is the rubric check."""
    from ctx.writeback import WritebackError, mark_correct
    try:
        marked = mark_correct(root, record, correct, rule=rule)
    except WritebackError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"recorded {marked['id']}: correct={marked['correct']} "
          "(hand-checked rubric verdict; local only, nothing posted)")
    if marked.get("rule_note"):
        print(f"proposed an anti-slop rule to inbox: {marked['rule_note']}")
    return 0


# --- task -----------------------------------------------------------------

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


def cmd_task_list(root: Path, project: str | None = None, status: str | None = None) -> int:
    db.require_db(root)
    query = "SELECT id, status, project, title FROM tasks"
    clauses, params = [], []
    if project:
        proj = objects.find(root, "project", project)
        clauses.append("project = ?")
        params.append(proj[1]["id"] if proj else project)
    if status:
        clauses.append("status = ?")
        params.append(status)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id"

    conn = db.connect(root)
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    if not rows:
        print("no tasks match")
        return 0
    width = max(len(r["id"]) for r in rows)
    for r in rows:
        print(f"{r['id']:<{width}}  {r['status']:<8}  {r['title']}")
    print(f"({len(rows)} task{'s' if len(rows) != 1 else ''})")
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


# --- repo -------------------------------------------------------------------

def _repo_slug(title: str, url: str | None) -> str:
    if url:
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
        if m:
            return _slugify(m.group(1).replace("/", "-"))
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


def cmd_repo_list(root: Path, kind: str | None = None) -> int:
    db.require_db(root)
    query = "SELECT id, kind, status, title FROM repos"
    params: list = []
    if kind:
        query += " WHERE kind = ?"
        params.append(kind)
    query += " ORDER BY id"
    conn = db.connect(root)
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    if not rows:
        print("no repos match")
        return 0
    width = max(len(r["id"]) for r in rows)
    for r in rows:
        print(f"{r['id']:<{width}}  {r['kind']:<4}  {r['status']:<8}  {r['title']}")
    print(f"({len(rows)} repo{'s' if len(rows) != 1 else ''})")
    return 0


# --- contribution -------------------------------------------------------------

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


def cmd_contribution_list(root: Path, repo: str | None = None, kind: str | None = None,
                          role: str | None = None, state: str | None = None,
                          json: bool = False) -> int:
    db.require_db(root)
    query = "SELECT id, repo, kind, number, role, state, ci, title FROM contributions"
    clauses, params = [], []
    if repo:
        found = objects.find(root, "repo", repo)
        clauses.append("repo = ?")
        params.append(found[1]["id"] if found else repo)
    for column, value in (("kind", kind), ("role", role), ("state", state)):
        if value:
            clauses.append(f"{column} = ?")
            params.append(value)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY repo, kind, number"
    conn = db.connect(root)
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    if not rows:
        print("no contributions match")
        return 0
    if json:
        import json as _json
        print(_json.dumps([
            {"id": r["id"], "repo": r["repo"], "kind": r["kind"], "number": r["number"],
             "role": r["role"], "state": r["state"], "ci": r["ci"], "title": r["title"]}
            for r in rows], indent=2))
        return 0
    width = max(len(r["id"]) for r in rows)
    for r in rows:
        print(f"{r['id']:<{width}}  {r['kind']}#{r['number']:<5}  {r['role']:<9}  "
              f"{r['state']:<7}  ci:{r['ci']:<8}  {r['title']}")
    print(f"({len(rows)} contribution{'s' if len(rows) != 1 else ''})")
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


# --- sync github ----------------------------------------------------------------

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


# --- digest -----------------------------------------------------------------------

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


# --- status ---------------------------------------------------------------

def cmd_status(root: Path, project: str) -> int:
    found = objects.find(root, "project", project)
    if found is None:
        raise SystemExit(f"project not found: {project!r} (see context/projects/)")
    _path, meta, _body = found
    project_id = meta["id"]
    print(f"# {meta.get('title', project_id)}  [{meta.get('status', '?')}]")
    print(f"id: {project_id}  updated: {meta.get('updated', '?')}")

    # Counts come from the markdown source of truth, not the index.
    counts = {s: 0 for s in TASK_STATUSES}
    tasks = objects.linked(root, "task", project_id)
    for _p, tmeta, _b in tasks:
        counts[tmeta.get("status", "to-do")] = counts.get(tmeta.get("status", "to-do"), 0) + 1
    print("\nTasks: " + ", ".join(f"{s}={n}" for s, n in counts.items())
          + f"  (total {len(tasks)})")
    for _p, tmeta, _b in tasks:
        print(f"  - {tmeta['id']}  [{tmeta.get('status', '?')}]  {tmeta.get('title', '')}")

    print("\nRecent factory runs:")
    if db.db_path(root).exists():
        conn = db.connect(root)
        try:
            rows = conn.execute(
                "SELECT id, factory, prompt_version, mode, verdict, created, bundle_path "
                "FROM runs WHERE project = ? ORDER BY id DESC LIMIT 5", (project_id,)
            ).fetchall()
        finally:
            conn.close()
        for r in rows:
            print(f"  run {r['id']}: {r['factory']} {r['prompt_version']} "
                  f"[{r['mode']}] verdict={r['verdict']} at {r['created']}")
            if r["bundle_path"]:
                print(f"    bundle: {r['bundle_path']}")
        if not rows:
            print("  (none)")
    else:
        print("  (state.db missing — run `python -m stead init`)")
    return 0


# --- run log ----------------------------------------------------------------

def cmd_run_log(root: Path, factory_name: str, task_ref: str, prompt_version: str,
                output: str | None = None, verdict: str = "pending",
                project: str | None = None, mode: str = "shadow") -> int:
    db.require_db(root)
    conn = db.connect(root)
    try:
        cur = conn.execute(
            "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, output, verdict, created) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (factory_name, task_ref, project, prompt_version, mode, output, verdict, db.utcnow()))
        conn.commit()
        run_id = cur.lastrowid
    finally:
        conn.close()
    print(f"logged run {run_id}: {factory_name} task={task_ref} "
          f"prompt={prompt_version} verdict={verdict}")
    return 0


# --- prompt -----------------------------------------------------------------

def cmd_prompt_list(root: Path, factory_name: str) -> int:
    db.require_db(root)
    conn = db.connect(root)
    try:
        rows = conn.execute(
            "SELECT version, status, path, created FROM prompt_versions "
            "WHERE factory = ? ORDER BY version", (factory_name,)).fetchall()
    finally:
        conn.close()
    if not rows:
        print(f"no prompt versions for {factory_name}")
        return 0
    for r in rows:
        print(f"{r['version']:<6} {r['status']:<11} {r['path']}")
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


# --- factory run --------------------------------------------------------------

def cmd_feature_build(root: Path, contribution: str, live: bool = False,
                      *, generate: bool = False, reach: str | None = None) -> int:
    mode = "live" if live else "shadow"
    info = _maybe_draft(
        root, factory.assemble_feature_build(root, contribution, mode=mode, reach=reach),
        generate)
    c = info["counts"]
    print(f"run {info['run_id']} recorded [{mode}] — {info['factory']} "
          f"prompt {info['prompt_version']} for {info['contribution']}")
    print(f"method: {info['method']}"
          + (" (Spec-Driven Development via the external, optional specify-cli "
             "toolchain — planning-before-code is unconditional)"
             if info["method"] == "spec-kit" else " (same SDD phases, hand-rolled markdown — no specify CLI)"))
    print(f"bundle: {c['acceptance_criteria']} acceptance criteria, "
          f"{c['related_documents']} related documents, "
          f"{c['related_contributions']} related cached contributions (duplicate sweep)")
    if info["flags"]:
        print(f"spec flags: {', '.join(info['flags'])} — NEEDS DECOMPOSITION; "
              "resolve before any agent builds this spec")
    else:
        print("spec flags: none — spec looks buildable")
    print(f"run dir: {info['run_dir']}/ (bundle.md, prompt.md, run.json)")
    print(f"reach: {info.get('reach', 'shadow')} (ceiling {info.get('ceiling', 'shadow')})")
    if info.get("remote") == "not-implemented":
        print("nothing was pushed. To open a pull request from an isolated branch:")
        print(f"  python -m stead factory publish --contribution {info.get('contribution')}")
    _print_draft(info, generate, coding=True)
    return 0


def cmd_factory_run(root: Path, factory_name: str, project: str | None,
                    live: bool = False, contribution: str | None = None,
                    *, generate: bool = False, reach: str | None = None) -> int:
    mode = "live" if live else "shadow"
    if reach and factory_name != factory.FEATURE_BUILDER_FACTORY:
        raise SystemExit("--reach is only valid for --factory feature-builder")
    if contribution is not None and factory_name != factory.FEATURE_BUILDER_FACTORY:
        raise SystemExit("--contribution is only valid for --factory feature-builder")
    if factory_name == factory.MAINTENANCE_FACTORY:
        info = _maybe_draft(root, factory.assemble_maintenance(root, mode=mode), generate)
        print(f"run {info['run_id']} recorded [{mode}] — {info['factory']} "
              f"prompt {info['prompt_version']}")
        c = info["counts"]
        print(f"bundle: {c['inbox']} inbox, {c['broken']} broken relations, "
              f"{c['stale']} stale, {c['duplicates']} duplicate titles")
        print(f"run dir: {info['run_dir']}/ (bundle.md, prompt.md, run.json)")
        print("no files were edited. Nothing was posted, pushed, or merged.")
        _print_draft(info, generate)
        return 0
    if factory_name == factory.FEATURE_BUILDER_FACTORY:
        if contribution is None:
            raise SystemExit("--contribution is required for factory 'feature-builder' "
                             "(a spec contribution: kind issue, role author, "
                             "with a ## Acceptance criteria checklist)")
        return cmd_feature_build(root, contribution, live=live, generate=generate, reach=reach)
    if factory_name == factory.DIGEST_FACTORY or project is None:
        if factory_name != factory.DIGEST_FACTORY and project is None:
            raise SystemExit(f"--project is required for factory {factory_name!r}")
        return cmd_digest(root, live=live, generate=generate)
    info = _maybe_draft(root, factory.assemble(root, factory_name, project, mode=mode), generate)
    print(f"run {info['run_id']} recorded [{mode}] — {info['factory']} "
          f"prompt {info['prompt_version']} for {info['project']}")
    c = info["counts"]
    print(f"bundle: {c['tasks']} tasks, {c['documents']} documents, {c['meetings']} meetings")
    print(f"run dir: {info['run_dir']}/ (bundle.md, prompt.md, run.json)")
    _print_draft(info, generate)
    return 0


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


# --- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="stead", description="Stead — local context you own. Command: stead. Stdlib only.")
    p.add_argument("--root", default=".", help="repo root (default: current directory)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the Stead version")
    sub.add_parser("init", help="rebuild state.db from schema.sql + markdown (idempotent)")
    doc = sub.add_parser("doctor", help="lint frontmatter, ids, dates, and relations")
    doc.add_argument("--json", action="store_true", help="machine-readable report")
    met = sub.add_parser("metrics", help="dogfood numbers from the build records")
    met.add_argument("--repo", help="only this repo id")
    met.add_argument("--since", help="only records created on or after YYYY-MM-DD")
    met.add_argument("--json", action="store_true", help="machine-readable report")
    met_sub = met.add_subparsers(dest="metrics_sub")
    metmark = met_sub.add_parser("mark",
                                 help="hand-check a build record correct/incorrect")
    metmark.add_argument("record", help="build record id")
    metmark.add_argument("--correct", required=True, choices=("true", "false"),
                         help="the correctness-rubric verdict (criteria actually met)")
    metmark.add_argument("--rule", default="",
                         help="optional: the deterministic check that would have caught "
                              "the failure (proposed to inbox as an anti-slop rule)")

    task = sub.add_parser("task", help="manage the task queue").add_subparsers(dest="sub", required=True)
    ta = task.add_parser("add", help="add a task (writes markdown + index)")
    ta.add_argument("--title", required=True)
    ta.add_argument("--project", required=True)
    ta.add_argument("--status", default="to-do", choices=TASK_STATUSES)
    tl = task.add_parser("list", help="list tasks")
    tl.add_argument("--project")
    tl.add_argument("--status", choices=TASK_STATUSES)
    ts = task.add_parser("set", help="set a task's status (file + index)")
    ts.add_argument("id")
    ts.add_argument("--status", required=True, choices=TASK_STATUSES)

    repo = sub.add_parser("repo", help="manage repos (own projects + OSS)").add_subparsers(dest="sub", required=True)
    ra = repo.add_parser("add", help="add a repo (writes markdown + index)")
    ra.add_argument("--title", required=True)
    ra.add_argument("--url", help="https://github.com/<owner>/<name>")
    ra.add_argument("--kind", default="oss", choices=REPO_KINDS)
    ra.add_argument("--status", default="active", choices=REPO_STATUSES)
    ra.add_argument("--default-branch")
    ra.add_argument("--contributing", help="CONTRIBUTING url or path")
    ra.add_argument("--notes")
    rlist = repo.add_parser("list", help="list repos")
    rlist.add_argument("--kind", choices=REPO_KINDS)
    rs = repo.add_parser("set", help="set this repo's factory trigger and ceiling")
    rs.add_argument("id")
    rs.add_argument("--trigger", choices=("on-demand", "watch"))
    rs.add_argument("--reach", choices=("ghost", "shadow", "draft-pr", "pr", "merge"))
    rs.add_argument("--path", help="local checkout for this repo. Not this Stead directory.")
    rs.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="set any repo field, e.g. checks_isolation=docker. "
                         "true/false become booleans; commas become lists")

    contrib = sub.add_parser("contribution", help="manage issues/PRs you're involved with").add_subparsers(dest="sub", required=True)
    ca = contrib.add_parser("add", help="add a contribution (writes markdown + index)")
    ca.add_argument("--title", required=True)
    ca.add_argument("--repo", required=True, help="repo id or slug")
    ca.add_argument("--kind", required=True, choices=CONTRIB_KINDS)
    ca.add_argument("--number", required=True, type=int)
    ca.add_argument("--url")
    ca.add_argument("--role", default="author", choices=CONTRIB_ROLES)
    ca.add_argument("--state", default="open", choices=CONTRIB_STATES)
    ca.add_argument("--ci", default="none", choices=CONTRIB_CI)
    ca.add_argument("--review", default="none", choices=CONTRIB_REVIEW)
    ca.add_argument("--method", default="spec-kit", choices=CONTRIB_METHODS,
                    help="feature-builder tooling (default: spec-kit; planning "
                         "before code is unconditional in both)")
    cl = contrib.add_parser("list", help="list contributions")
    cl.add_argument("--repo")
    cl.add_argument("--kind", choices=CONTRIB_KINDS)
    cl.add_argument("--role", choices=CONTRIB_ROLES)
    cl.add_argument("--state", choices=CONTRIB_STATES)
    cl.add_argument("--json", action="store_true", help="machine-readable list")
    cs = contrib.add_parser("set", help="update contribution fields (file + index)")
    cs.add_argument("id")
    cs.add_argument("--state", choices=CONTRIB_STATES)
    cs.add_argument("--ci", choices=CONTRIB_CI)
    cs.add_argument("--review", choices=CONTRIB_REVIEW)
    cs.add_argument("--role", choices=CONTRIB_ROLES)
    cs.add_argument("--method", choices=CONTRIB_METHODS)

    actor = sub.add_parser("actor", help="humans and agents who write here").add_subparsers(dest="sub", required=True)
    aa = actor.add_parser("add", help="add an actor file")
    aa.add_argument("--title", required=True)
    aa.add_argument("--kind", default="human", choices=("human", "agent"))
    actor.add_parser("list", help="list actors")
    au = actor.add_parser("use", help="remember who is writing. Stamped on later writes.")
    au.add_argument("id")

    ctx = sub.add_parser("context", help="read-only context tools").add_subparsers(dest="sub", required=True)
    cs = ctx.add_parser("search", help="search markdown context objects (read-only)")
    cs.add_argument("query", help="text to find in titles or bodies")
    cs.add_argument("--repo", help="only this repo id and objects that reference it")
    cs.add_argument("--json", action="store_true", help="machine-readable list")

    account = sub.add_parser("account", help="shared-server sign-in. Not a login on this computer.").add_subparsers(dest="sub", required=True)
    ac = account.add_parser("add", help="add a person. Prints a password once.")
    ac.add_argument("--name", required=True)
    ac.add_argument("--actor", required=True)
    ac.add_argument("--password", help="optional. If omitted, one is generated and printed once.")
    account.add_parser("list", help="list names and actors. Never prints a password.")
    ar = account.add_parser("reset", help="replace a password. Prints the new one once.")
    ar.add_argument("--name", required=True)

    inbox = sub.add_parser("inbox", help="unsorted capture").add_subparsers(dest="sub", required=True)
    imported = inbox.add_parser("import", help="copy a local .eml, .ics, .md, or .txt file into inbox/")
    imported.add_argument("path")
    listed = inbox.add_parser("list", help="list inbox notes. Read-only.")
    listed.add_argument("--kind", choices=("decision", "glossary", "note"),
                        help="limit output to one kind")
    sched = sub.add_parser("schedule", help="the weekly local jobs").add_subparsers(dest="sub", required=True)
    sshow = sched.add_parser("show", help="print the Friday command. Does not install it.")
    sshow.add_argument("--project", help="also assemble this project's status")
    sshow.add_argument("--watch", action="store_true", help="also build and publish watched specs")
    sshow.add_argument("--merge", action="store_true", help="with --watch, merge when reach: merge")
    sshow.add_argument("--interval", choices=("hourly", "daily"),
                       help="print the shorter monitor cadence (sync + watch) "
                            "instead of the weekly digest job")
    sinst = sched.add_parser("install", help="Windows only. Current user, Friday 16:00. No remote writes.")
    sinst.add_argument("--project", help="also assemble this project's status")
    sinst.add_argument("--watch", action="store_true", help="also build and publish watched specs")
    sinst.add_argument("--merge", action="store_true", help="with --watch, merge when reach: merge")
    sinst.add_argument("--interval", choices=("hourly", "daily"),
                       help="install the shorter monitor cadence (sync + watch) "
                            "instead of the weekly digest job")
    hook = sub.add_parser("hook", help="loopback or shared-server capture webhook").add_subparsers(dest="sub", required=True)
    hook.add_parser("set", help="create a webhook token. Printed once. Stored in stead.json.")
    hook.add_parser("show", help="say whether a webhook token is set. Never prints it.")

    dele = sub.add_parser("delete", help="remove one object file. Git history is the audit trail.")
    dele.add_argument("type", choices=("project", "task", "document", "meeting", "repo", "actor", "contribution"))
    dele.add_argument("id")
    dele.add_argument("--force", action="store_true",
                      help="delete a project or repo that still has linked objects")

    bld = sub.add_parser("build", help="model-driven build: plan, edit, run checks, commit. Optional PR.")
    bld.add_argument("--contribution", required=True)
    bld.add_argument("--publish", action="store_true",
                     help="push the branch and open a pull request when the ceiling allows")
    bld.add_argument("--merge", action="store_true",
                     help="after opening, merge when the repo says reach: merge and checks are green")
    bld.add_argument("--steps", type=int, default=300,
                     help="max model steps for this build (default 300)")
    bld.add_argument("--resume", action="store_true",
                     help="continue a failed build on its branch, keeping its WIP commit")
    bld.add_argument("--retry", action="store_true",
                     help="re-run a spec that already had a failed build attempt, "
                          "without re-approving its body")
    bld.add_argument("--wait", action="store_true",
                     help="with --publish, wait for PR checks before merging")
    bld.add_argument("--wait-minutes", type=int, default=30)
    bld.add_argument("--repair-rounds", type=int, default=2,
                     help="how many failed check rounds the model may fix")
    bld.add_argument("--max-minutes", type=int, default=240,
                     help="wall-clock budget for this build (default 240 = 4 hours)")
    bld.add_argument("--max-tokens", type=int,
                     help="token budget for this build. Defaults to the install default.")
    bld.add_argument("--max-cost", type=float,
                     help="USD budget for this build (needs model prices). "
                          "Defaults to the install default.")
    rev = sub.add_parser("review", help="independent reviewer pass on a build branch. Approve or reject.")
    rev.add_argument("--contribution", required=True)
    adr = sub.add_parser("address", help="address the review comments on a published PR: fix, commit, push")
    adr.add_argument("--contribution", required=True)
    adr.add_argument("--no-push", action="store_true",
                     help="commit the fix locally; do not push to the PR")

    sp = sub.add_parser("spec", help="approve a feature spec by its body hash").add_subparsers(dest="sub", required=True)
    spa = sp.add_parser("approve", help="approve the current body of a contribution as a build spec")
    spa.add_argument("--contribution", required=True)
    spd = sp.add_parser("draft", help="draft a feature spec from a raw issue in one model call")
    spd.add_argument("--contribution",
                     help="the source issue id (mutually exclusive with --all)")
    spd.add_argument("--all", action="store_true",
                     help="draft every open stead-build issue with no draft yet. Never approves.")
    spd.add_argument("--redraft", action="store_true",
                     help="replace the body of the existing draft and clear its approval")

    sy = sub.add_parser("sync", help="sync external context (read-only)").add_subparsers(dest="sub", required=True)
    sg = sy.add_parser("github", help="cache your GitHub PRs/reviews/issues via gh (READ-ONLY)")
    sg.add_argument("--author", default="@me")
    sg.add_argument("--limit", type=int, default=30)
    sg.add_argument("--offline", action="store_true",
                    help="skip network; re-index existing contribution files")
    sg.add_argument("--digest", action="store_true",
                    help="if the cache changed, assemble the digest. Nothing is posted.")
    sg.add_argument("--repo", action="append", metavar="OWNER/NAME",
                    help="only this repo (repeatable). Overrides the saved scope for this run.")
    sg.add_argument("--all-repos", action="store_true",
                    help="ignore the saved scope for this run")
    sg.add_argument("--remember", action="store_true",
                    help="save --repo as this store's default scope (or clear it with --all-repos)")

    model = sub.add_parser("model", help="the rented model factories may draft with").add_subparsers(dest="sub", required=True)
    model.add_parser("show", help="show the configured model. Never prints the key.")
    ms = model.add_parser("set", help="choose an OpenAI-compatible endpoint")
    from ctx.models import PROVIDERS
    ms.add_argument("--provider", required=True, choices=tuple(PROVIDERS))
    ms.add_argument("--name", required=True, help="model name, such as gpt-4.1-mini or llama3.2")
    ms.add_argument("--base-url", help="defaults to the provider preset")
    ms.add_argument("--key", help="stored in gitignored stead.json. Prefer STEAD_MODEL_API_KEY.")
    ms.add_argument("--key-env", default="STEAD_MODEL_API_KEY")
    ms.add_argument("--review", action="store_true",
                    help="configure the optional independent reviewer model. "
                         "Falls back to the builder model when unset.")
    ms.add_argument("--input-price", type=float,
                    help="USD per 1M input tokens, for a cost budget")
    ms.add_argument("--output-price", type=float,
                    help="USD per 1M output tokens, for a cost budget")
    ms.add_argument("--call-timeout", type=int, metavar="SECONDS",
                    help="seconds one model call may take during a build or "
                         "review (default 300, 30 to 7200). Raise it for a large "
                         "local model.")
    mt = model.add_parser("test", help="one live call to prove the model works. Never prints the key.")
    mt.add_argument("--prompt", default="Reply with exactly one word: ok")
    mt.add_argument("--timeout", type=int, default=60)
    model.add_parser("list", help="list model ids the endpoint offers")
    model.add_parser("profiles", help="list saved model profiles and role bindings")
    ma = model.add_parser("add", help="save a named provider connection (a profile)")
    ma.add_argument("profile")
    ma.add_argument("--provider", required=True, choices=tuple(PROVIDERS))
    ma.add_argument("--name", required=True, help="model name, such as gpt-4.1-mini or llama3.2")
    ma.add_argument("--base-url", help="defaults to the provider preset")
    ma.add_argument("--key", help="stored in gitignored stead.json. Prefer an env var.")
    ma.add_argument("--key-env", default="STEAD_MODEL_API_KEY")
    ma.add_argument("--input-price", type=float, help="USD per 1M input tokens")
    ma.add_argument("--output-price", type=float, help="USD per 1M output tokens")
    ma.add_argument("--call-timeout", type=int, metavar="SECONDS")
    mr = model.add_parser("remove", help="remove a saved profile")
    mr.add_argument("profile")
    mrole = model.add_parser("role", help="bind a job to a profile (build/draft/review/address)")
    mrole.add_argument("role", choices=("build", "draft", "review", "address"))
    mrole.add_argument("profile", help="profile name, or '-' to unbind and fall back to the default")

    ev = sub.add_parser("eval", help="factory eval cases").add_subparsers(dest="sub", required=True)
    er = ev.add_parser("run", help="check eval files. No model, no network.")
    er.add_argument("--factory")
    ej = ev.add_parser("judge", help="ask the configured model to judge one draft")
    ej.add_argument("--factory", required=True)
    ej.add_argument("--case", required=True)
    ej.add_argument("--output", required=True, help="path to the draft markdown")
    ej.add_argument("--prompt-version", default="", help="version this pass is for. Defaults to production.")

    dg = sub.add_parser("digest", help="assemble the weekly contribution digest")
    dg.add_argument("--shadow", action="store_true", help="shadow mode (default)")
    dg.add_argument("--live", action="store_true", help="record as live. Still does not post.")
    dg.add_argument("--generate", action="store_true",
                    help="draft with the configured model. Nothing is posted.")

    st = sub.add_parser("status", help="project rollup: task counts + recent runs")
    st.add_argument("project")

    run = sub.add_parser("run", help="run ledger").add_subparsers(dest="sub", required=True)
    rl = run.add_parser("log", help="record a run / supply generated output + verdict")
    rl.add_argument("--factory", required=True)
    rl.add_argument("--task", required=True, help="task reference (project id for the status factory)")
    rl.add_argument("--prompt-version", required=True)
    rl.add_argument("--output")
    rl.add_argument("--verdict", default="pending")
    rl.add_argument("--project")
    rl.add_argument("--mode", default="shadow", choices=("shadow", "live"))
    rf = run.add_parser("file", help="file an approved digest or status as a private document. Never posts.")
    rf.add_argument("--run", required=True)
    rf.add_argument("--title")
    pr = sub.add_parser("prompt", help="versioned prompts").add_subparsers(dest="sub", required=True)
    pl = pr.add_parser("list", help="list prompt versions")
    pl.add_argument("--factory", required=True)
    pp = pr.add_parser("promote", help="promote a version to production (retire old)")
    pp.add_argument("--factory", required=True)
    pp.add_argument("--version", required=True)

    fr = sub.add_parser("factory", help="factory runner").add_subparsers(dest="sub", required=True)
    frun = fr.add_parser("run", help="assemble a bundle. --generate drafts with the configured model.")
    frun.add_argument("--factory", required=True)
    frun.add_argument("--project", help="project id. Not needed for weekly-contribution-digest or context-maintenance")
    frun.add_argument("--contribution", help="spec contribution id (required for feature-builder)")
    frun.add_argument("--shadow", action="store_true", help="shadow mode (default)")
    frun.add_argument("--live", action="store_true", help="record as live. Still does not push or open a PR.")
    frun.add_argument("--generate", action="store_true",
                      help="draft with the configured model. Nothing is posted or pushed.")
    frun.add_argument("--reach", choices=("ghost", "shadow", "draft-pr", "pr", "merge"),
                      help="feature-builder only. Cannot exceed the repo ceiling. "
                           "Does not push. Merge is never inherited.")
    fwatch = fr.add_parser("watch", help="assemble open feature specs on repos set to watch")
    fwatch.add_argument("--build", action="store_true",
                        help="run the model build after assembly. Needs a configured model.")
    fwatch.add_argument("--publish", action="store_true",
                        help="with --build, open a pull request when the ceiling allows")
    fwatch.add_argument("--merge", action="store_true",
                        help="with --publish, merge when the repo says reach: merge and checks are green")
    fnew = fr.add_parser("new", help="scaffold a factory folder. Does not call a model.")
    fnew.add_argument("--name", required=True)
    fnew.add_argument("--title", required=True)
    fdel = fr.add_parser("delete", help="remove a factory folder. Refuses shipped factories and run logs without --force.")
    fdel.add_argument("--name", required=True)
    fdel.add_argument("--force", action="store_true",
                      help="also delete a shipped factory or its run logs (audit trail)")
    fpub = fr.add_parser("publish", help="push an isolated branch and open a pull request. Never merges.")
    fpub.add_argument("--contribution", required=True)
    fmerge = fr.add_parser("merge", help="merge a green pull request. Repo must say reach: merge. Never bypasses protection.")
    fmerge.add_argument("--contribution", required=True)
    fcomment = fr.add_parser("comment", help="comment on the issue linking the PR. Gated: allow_comment + kind own.")
    fcomment.add_argument("--contribution", required=True)
    fcomment.add_argument("--pr-url", help="the pull request URL to link; defaults to the build record's")
    fdef = fr.add_parser("defaults", help="install factory preference. Cannot be merge.")
    fdef.add_argument("--trigger", choices=("on-demand", "watch"))
    fdef.add_argument("--reach", choices=("ghost", "shadow", "draft-pr", "pr"))
    fdef.add_argument("--max-builds-per-day", type=int,
                      help="watched builds after which the scheduler stops (0 = no cap)")
    fdef.add_argument("--build-minutes", type=int,
                      help="wall-clock budget for each watched build")
    fdef.add_argument("--max-tokens-per-build", type=int,
                      help="token budget for each build (0 = off)")
    fdef.add_argument("--max-cost-per-build", type=float,
                      help="USD budget for each build, needs model prices (0 = off)")
    fr.add_parser("stop", help="create .stead-stop: builds stop between steps")
    fr.add_parser("start", help="remove .stead-stop and allow builds again")

    welcome = sub.add_parser("welcome", help="first run: name a project and optional GitHub URL")
    welcome.add_argument("--title", required=True)
    welcome.add_argument("--url", help="https://github.com/owner/name")
    welcome.add_argument("--deployment", default="single", choices=("single", "multi"),
                         help="single: this computer. multi: shared server, needs Docker")

    ob = sub.add_parser("onboard", help="create a project, its repo record, and the initial constitution")
    ob.add_argument("--title", required=True)
    ob.add_argument("--kind", default="own", choices=REPO_KINDS)
    ob.add_argument("--url", help="https://github.com/owner/name")
    ob.add_argument("--path", help="existing code directory; not this context repo")
    ob.add_argument("--method", default="spec-kit", choices=CONTRIB_METHODS,
                    help="spec-kit runs specify init when it is on PATH; builtin writes markdown only")
    ob.add_argument("--integration", default="claude",
                    choices=("claude", "copilot", "gemini", "codex", "generic"))
    ob.add_argument("--no-specify", action="store_true",
                    help="do not run specify init, even if it is installed")

    cockpit = sub.add_parser("ui", help="open the local cockpit in a browser (loopback only)")
    cockpit.add_argument("--port", type=int, default=None,
                         help="listen port (default 8765; stead.json may also set port)")
    cockpit.add_argument("--host", default=None,
                         help="single-user: loopback only. multi-user --deploy: 0.0.0.0")
    cockpit.add_argument("--deploy", action="store_true",
                         help="shared server. Requires an access token. Prefer Docker.")
    cockpit.add_argument("--no-browser", action="store_true",
                         help="serve without opening a browser")

    return p


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print("Stead")
        print("  python -m stead ui")
        print("  python -m stead welcome --title \"My Project\"")
        print("  python -m stead --help")
        return 0
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "version":
        from ctx import __version__
        print(__version__)
        return 0
    if args.command == "init":
        return cmd_init(root)
    if args.command == "doctor":
        from ctx import doctor
        report = doctor.run(root)
        if args.json:
            import json as _json
            print(_json.dumps(report, indent=2))
        else:
            print(doctor.render(report))
        return 1 if report["errors"] else 0
    if args.command == "metrics":
        if getattr(args, "metrics_sub", None) == "mark":
            return cmd_metrics_mark(root, args.record, args.correct == "true",
                                    rule=getattr(args, "rule", ""))
        from ctx import metrics
        try:
            report = metrics.collect(root, repo=args.repo, since=args.since)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if args.json:
            import json as _json
            print(_json.dumps(report, indent=2))
        else:
            print(metrics.render(report))
        return 0
    if args.command == "task":
        if args.sub == "add":
            return cmd_task_add(root, args.title, args.project, args.status)
        if args.sub == "list":
            return cmd_task_list(root, args.project, args.status)
        if args.sub == "set":
            return cmd_task_set(root, args.id, args.status)
    if args.command == "repo":
        if args.sub == "add":
            return cmd_repo_add(root, args.title, args.url, args.kind, args.status,
                                args.default_branch, args.contributing, args.notes)
        if args.sub == "list":
            return cmd_repo_list(root, args.kind)
        if args.sub == "set":
            from ctx.autonomy import AutonomyError, set_repo
            try:
                extra = {}
                for item in args.set:
                    key, _sep, value = item.partition("=")
                    key = key.strip()
                    if not key or not _sep:
                        raise AutonomyError(f"--set needs KEY=VALUE, got {item!r}")
                    raw = value.strip()
                    if raw.lower() in {"true", "false"}:
                        extra[key] = raw.lower() == "true"
                    elif "," in raw:
                        extra[key] = [part.strip() for part in raw.split(",") if part.strip()]
                    else:
                        extra[key] = raw
                policy = set_repo(root, args.id, trigger=args.trigger, reach=args.reach,
                                  code_path=args.path, extra=extra)
            except AutonomyError as exc:
                raise SystemExit(str(exc)) from exc
            print(f"{args.id}: trigger {policy['trigger']}, ceiling {policy['ceiling']}")
            if policy["ceiling"] == "merge":
                print("merge is explicit on this repo. It is not the install default.")
            from ctx import objects, safety
            found = objects.find(root, "repo", args.id)
            if found is not None:
                meta = found[1]
                code = Path(meta.get("code_path") or "")
                if code.is_dir():
                    for warning in safety.runner_warnings(code, meta):
                        print(f"warning: {warning}")
            print("nothing was pushed, opened, or merged")
            return 0
    if args.command == "contribution":
        if args.sub == "add":
            return cmd_contribution_add(root, args.title, args.repo, args.kind,
                                        args.number, args.url, args.role,
                                        args.state, args.ci, args.review,
                                        args.method)
        if args.sub == "list":
            return cmd_contribution_list(root, args.repo, args.kind, args.role, args.state,
                                         json=bool(args.json))
        if args.sub == "set":
            return cmd_contribution_set(root, args.id, args.state, args.ci,
                                        args.review, args.role, args.method)
    if args.command == "actor":
        from ctx.ui import UiError, add_actor
        from ctx import objects
        if args.sub == "add":
            try:
                added = add_actor(root, args.title, args.kind)
            except UiError as exc:
                raise SystemExit(str(exc)) from exc
            _info(f"added {added['id']} [{added['kind']}]")
            return 0
        if args.sub == "use":
            from ctx.actors import ActorError, use
            try:
                chosen = use(root, args.id)
            except ActorError as exc:
                raise SystemExit(str(exc)) from exc
            print(f"writing as {chosen}")
            return 0
        for _path, meta, _body in objects.iter_objects(root, "actor"):
            print(f"{meta.get('id')}  {meta.get('kind', 'human')}  {meta.get('title')}")
        return 0
    if args.command == "sync" and args.sub == "github":
        return cmd_sync_github(root, args.author, args.limit, args.offline, digest=args.digest,
                               repos=args.repo, all_repos=args.all_repos,
                               remember=args.remember)
    if args.command == "model":
        from ctx import models
        try:
            if args.sub == "test":
                result = models.test_model(root, prompt=args.prompt,
                                           timeout=max(1, args.timeout))
                print(f"ok: {result['provider']} {result['name']} @ {result['base_url']}")
                print(f"latency: {result['ms']} ms")
                print(f"reply: {result['reply']}")
                return 0
            if args.sub == "list":
                result = models.list_models(root)
                print(f"{result['provider']} @ {result['base_url']}")
                for mid in result["models"]:
                    print(f"  {mid}")
                if not result["models"]:
                    print("  (none)")
                return 0
            if args.sub == "set":
                shown = models.set_model(
                    root, provider=args.provider, name=args.name,
                    base_url=args.base_url or "", api_key=args.key,
                    api_key_env=args.key_env,
                    block="reviewer" if args.review else "model",
                    input_price=args.input_price,
                    output_price=args.output_price,
                    call_timeout=args.call_timeout)
                if args.review:
                    print("reviewer model saved in stead.json (gitignored). "
                          "It falls back to the builder model when unset.")
                    return 0
                print("model saved in stead.json (gitignored). The key was not printed.")
            if args.sub == "profiles":
                view = models.profiles_view(root)
                for role in models.MODEL_ROLES:
                    print(f"{role}: {view['roles'][role] or '(default)'}")
                for name, p in view["profiles"].items():
                    key = "set" if p["key_set"] else "not set"
                    print(f"profile {name}: {p['provider']} {p['name']} "
                          f"@ {p['base_url'] or '(preset)'} (key {key})")
                if not view["profiles"]:
                    print("(no saved profiles)")
                return 0
            if args.sub == "add":
                models.add_model(root, args.profile, provider=args.provider,
                                 name=args.name, base_url=args.base_url or "",
                                 api_key=args.key, api_key_env=args.key_env,
                                 input_price=args.input_price,
                                 output_price=args.output_price,
                                 call_timeout=args.call_timeout)
                print(f"profile {args.profile} saved in stead.json (gitignored). "
                      "Bind it with `stead model role <job> <profile>`.")
                return 0
            if args.sub == "remove":
                models.remove_model(root, args.profile)
                print(f"profile {args.profile} removed")
                return 0
            if args.sub == "role":
                profile = "" if args.profile == "-" else args.profile
                models.set_role(root, args.role, profile)
                print(f"{args.role} -> {profile or '(default)'}")
                return 0
            else:
                shown = models.public_model(root)
        except models.ModelError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"provider: {shown['provider'] or '(none)'}")
        print(f"model: {shown['name'] or '(none)'}")
        print(f"base_url: {shown['base_url'] or '(none)'}")
        print(f"key: {'set (' + shown['key_from'] + ')' if shown['key_set'] else 'not set'} "
              f"via {shown['key_env']}")
        print(f"call timeout: {shown['call_timeout']}s")
        return 0
    if args.command == "eval":
        from ctx import models
        if args.sub == "run":
            checked = models.check_eval_files(root, args.factory)
            if not checked["ok"]:
                for problem in checked["problems"]:
                    print(problem)
                return 1
            print(f"eval files ok ({checked['cases']} cases)")
            return 0
        try:
            judged = models.judge(root, args.factory, args.case, args.output,
                                  prompt_version=args.prompt_version)
        except TimeoutError as exc:
            raise _model_timeout(root, "the judge") from exc
        except (models.ModelError, OSError) as exc:
            raise SystemExit(str(exc)) from exc
        print(f"{judged['verdict']}: {judged['reason']}")
        print(f"recorded: {judged['path']}")
        return 0 if judged["verdict"] == "pass" else 1
    if args.command == "digest":
        return cmd_digest(root, live=args.live, generate=args.generate)
    if args.command == "status":
        return cmd_status(root, args.project)
    if args.command == "context" and args.sub == "search":
        from ctx import search
        try:
            results = search.search(root, args.query, repo=args.repo)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        if args.json:
            import json as _json
            print(_json.dumps(results, indent=2))
        else:
            print(search.render(results, args.query))
        return 0
    if args.command == "run" and args.sub == "log":
        return cmd_run_log(root, args.factory, args.task, args.prompt_version,
                           args.output, args.verdict, args.project, args.mode)
    if args.command == "run" and args.sub == "file":
        from ctx.deliver import DeliveryError, file_run
        try:
            filed = file_run(root, args.run, args.title)
        except DeliveryError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"filed {filed['id']} -> {_rel(root, filed['path'])}")
        print("local document only. Nothing was posted, pushed, or merged.")
        return 0
    if args.command == "prompt":
        if args.sub == "list":
            return cmd_prompt_list(root, args.factory)
        if args.sub == "promote":
            return cmd_prompt_promote(root, args.factory, args.version)
    if args.command == "factory" and args.sub == "run":
        return cmd_factory_run(root, args.factory, args.project, live=args.live,
                               contribution=args.contribution, generate=args.generate,
                               reach=args.reach)
    if args.command == "inbox" and args.sub == "import":
        from ctx.inbox_import import InboxImportError, import_file
        try:
            written = import_file(root, args.path)
        except InboxImportError as exc:
            raise SystemExit(str(exc)) from exc
        for item in written:
            print(f"inbox {item['name']}")
        print("triage into context/. Nothing was posted.")
        return 0
    if args.command == "inbox" and args.sub == "list":
        from ctx.inbox_import import list_notes
        status, rows = list_notes(root)
        if status == "missing":
            print("inbox not found")
            return 0
        if status == "empty":
            print("inbox is empty")
            return 0
        if args.kind:
            rows = [r for r in rows if r["kind"] == args.kind]
        if not rows:
            print(f"no {args.kind} notes")
            return 0
        for row in rows:
            print(f"{row['name']}  {row['kind']}  {row['title']}")
        return 0
    if args.command == "spec" and args.sub == "approve":
        from ctx.spec import SpecError, approve, source_changed_note
        from ctx import objects
        found = objects.find(root, "contribution", args.contribution)
        if found is not None:
            print("--- approving this body ---")
            print(found[2].strip())
            print("----------------------------")
            note = source_changed_note(root, found[1])
            if note:
                print(note)
        try:
            approved = approve(root, args.contribution)
        except SpecError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"approved {approved['id']}")
        print(f"spec sha256: {approved['sha']}")
        print("any change to the body needs re-approval before a build")
        return 0
    if args.command == "spec" and args.sub == "draft":
        from ctx.models import ModelError
        from ctx.spec import SpecError, auto_draft, draft_spec
        if args.all:
            report = auto_draft(root)
            for id_ in report["drafted"]:
                print(f"drafted {id_}")
            for skip in report["skipped"]:
                print(f"skipped {skip['id']}: {skip['reason']}")
            print(f"{len(report['drafted'])} drafted, {len(report['skipped'])} skipped")
            print("never approves. Review and approve each with: "
                  "python -m stead spec approve --contribution ID")
            return 0
        if not args.contribution:
            raise SystemExit("spec draft needs --contribution ID or --all")
        try:
            drafted = draft_spec(root, args.contribution, redraft=args.redraft)
        except (SpecError, ModelError) as exc:
            raise SystemExit(str(exc)) from exc
        except TimeoutError as exc:
            raise _model_timeout(root, "spec draft") from exc
        print(f"drafted {drafted['id']} -> {drafted['path']}")
        print(f"from {drafted['drafted_from']} (the source issue body is untouched)")
        for warning in drafted.get("warnings") or []:
            print(f"warning: {warning}. Fix the plan before approving.")
        print(f"review and approve it with: python -m stead spec approve "
              f"--contribution {drafted['id']}")
        return 0
    if args.command == "review":
        from ctx.models import ModelError
        from ctx.review import ReviewError, review as run_review
        try:
            result = run_review(root, args.contribution)
        except (ReviewError, ModelError) as exc:
            raise SystemExit(str(exc)) from exc
        print(f"verdict: {result['verdict']}")
        print(f"reason: {result['reason'] or '(none given)'}")
        if result.get("record"):
            print(f"record: {result['record']['path']}")
        return 0 if result["verdict"] == "approve" else 1
    if args.command == "address":
        from ctx.agent import BuildError, address_review
        from ctx.models import ModelError
        try:
            result = address_review(root, args.contribution, push=not args.no_push,
                                    progress=lambda line: print(line, file=sys.stderr, flush=True))
        except (BuildError, ModelError) as exc:
            raise SystemExit(str(exc)) from exc
        print(f"committed {result['commit'][:12]} on {result['branch']}"
              + (" and pushed" if result["pushed"] else " (not pushed)"))
        print(f"files: {', '.join(result['files']) or '(none)'}")
        print(f"pr: {result['pr_url']}")
        return 0
    if args.command == "build":
        from ctx.agent import BuildError, build as run_build
        from ctx.models import ModelError
        try:
            result = run_build(root, args.contribution, publish=args.publish,
                               merge=args.merge, resume=args.resume, retry=args.retry,
                               wait=args.wait,
                               wait_minutes=max(1, args.wait_minutes),
                               repair_rounds=max(0, args.repair_rounds),
                               max_steps=max(1, args.steps),
                               max_minutes=max(1, args.max_minutes),
                               max_tokens=args.max_tokens, max_cost=args.max_cost,
                               progress=lambda line: print(line, file=sys.stderr, flush=True))
        except (BuildError, ModelError) as exc:
            raise SystemExit(str(exc)) from exc
        except TimeoutError as exc:
            from ctx import models as models_mod
            seconds = models_mod.public_model(root)["call_timeout"]
            raise SystemExit(
                f"the model did not reply within {seconds}s, so the build stopped. "
                "The failure is recorded. Raise the limit with "
                "`stead model set ... --call-timeout SECONDS` or use a faster model, "
                "then re-run with --retry (a timeout uses the spec's attempt).") from exc
        print(f"plan: {result['plan']}")
        print(f"files: {', '.join(result['files'])}")
        print(f"branch: {result['branch']}  commit: {result['commit'][:12]}")
        if result.get("reach") == "ghost":
            print("checks: not run (ghost is purely spec, docs, and a code plan)")
            print(f"plan and docs: {result.get('run_dir', '')} (for approval)")
        elif result["checks"]:
            print(f"checks: passed ({result['checks']})")
        else:
            print("checks: none configured on the repo")
        if result["published"]:
            print(f"opened {result['pr_url']}")
            if result.get("comment"):
                print(f"commented on the issue: {result['comment'].get('url')}")
            if result.get("comment_error"):
                print(f"warning: issue comment failed: {result['comment_error']}")
            if result.get("merged"):
                print(f"merged {result['merged_url']}")
            elif args.merge:
                print("merge did not run. The checks may be pending or the repo moved.")
        elif result.get("reach") == "ghost":
            print("ghost run: no code was applied and nothing was pushed. "
                  "Review the plan and docs, then raise the repo reach to build.")
        else:
            print("not pushed. Run with --publish, or:")
            print(f"  python -m stead factory publish --contribution {args.contribution}")
        if result.get("deleted"):
            print(f"deleted: {', '.join(result['deleted'])}")
        return 0
    if args.command == "delete":
        from ctx.ui import UiError, delete_object
        try:
            removed = delete_object(root, args.type, args.id, args.force)
        except UiError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"deleted {removed['type']} {removed['id']}")
        print("git history keeps the old text.")
        return 0
    if args.command == "schedule":
        from ctx.schedule import (ScheduleError, install, install_monitor,
                                  monitor_show, show)
        interval = getattr(args, "interval", None)
        # The monitor cadence is sync + watch by definition; --watch only adds
        # the build to the weekly job.
        watch = args.watch or bool(interval)
        if args.sub == "show":
            if interval:
                print(monitor_show(root, interval=interval,
                                   watch=watch, merge=args.merge))
            else:
                print(show(root, args.project, watch=watch, merge=args.merge))
            return 0
        try:
            if interval:
                name = install_monitor(root, interval=interval,
                                       watch=watch, merge=args.merge)
            else:
                name = install(root, project=args.project, watch=watch,
                               merge=args.merge)
        except ScheduleError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"installed {name}")
        if interval:
            print("Monitor cadence. Read-only sync + watched build. Nothing merges "
                  "unless the repo says reach: merge.")
        else:
            print("Friday 16:00. Read-only sync, local drafts. Nothing is posted.")
        return 0
    if args.command == "hook":
        from ctx.config import hook_token, set_hook_token
        if args.sub == "set":
            token = set_hook_token(root)
            print("webhook token, shown once:")
            print(token)
            print("stored in stead.json. POST /hook with header X-Stead-Hook.")
            print("It only writes inbox/. It does not run a factory.")
            return 0
        print("webhook token: set" if hook_token(root) else "webhook token: not set")
        return 0
    if args.command == "factory" and args.sub == "new":
        from ctx.scaffold import ScaffoldError, scaffold
        try:
            folder = scaffold(root, args.name, args.title)
        except ScaffoldError as exc:
            raise SystemExit(str(exc)) from exc
        db.index_new_factory(root, folder.name)
        print(f"scaffolded {folder.relative_to(root).as_posix()} (index updated)")
        return 0
    if args.command == "factory" and args.sub == "delete":
        from ctx.scaffold import ScaffoldError, delete_factory
        try:
            removed = delete_factory(root, args.name, force=args.force)
        except ScaffoldError as exc:
            raise SystemExit(str(exc)) from exc
        db.forget_factory(root, removed["name"])
        print(f"deleted factory {removed['name']} (index updated)")
        return 0
    if args.command == "factory" and args.sub == "publish":
        from ctx.publish import PublishError, publish
        try:
            opened = publish(root, args.contribution)
        except PublishError as exc:
            raise SystemExit(str(exc)) from exc
        from ctx import writeback
        writeback.mark_published(root, opened["repo"], opened["branch"], opened["url"])
        print(f"opened {opened['url']}")
        print(f"branch {opened['branch']} -> {opened['base']} [{opened['reach']}]")
        print("not merged. A person reviews.")
        return 0
    if args.command == "factory" and args.sub == "merge":
        from ctx.merge import MergeError, merge
        try:
            opened = merge(root, args.contribution)
        except MergeError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"merged {opened['url']}")
        print(f"branch {opened['branch']} -> {opened['base']}")
        print("branch protection was not bypassed.")
        return 0
    if args.command == "factory" and args.sub == "comment":
        from ctx.comment import CommentError, comment
        from ctx import writeback
        pr_url = args.pr_url or writeback.contribution_pr_url(root, args.contribution)
        if not pr_url:
            raise SystemExit("no pull request URL to link; publish first or pass --pr-url")
        try:
            result = comment(root, args.contribution, pr_url)
        except CommentError as exc:
            raise SystemExit(str(exc)) from exc
        verb = "updated" if result.get("updated") else "created"
        print(f"{verb} {result['url']}")
        return 0
    if args.command == "account":
        from ctx.accounts import AccountError, add, public_list, reset
        try:
            if args.sub == "add":
                shown = add(root, args.name, args.actor, args.password)
                print(f"account {args.name.strip().lower()} -> {args.actor}")
                if args.password:
                    print("password was not printed.")
                else:
                    print(f"password, shown once: {shown}")
                print("stored as a hash in private/accounts.json")
                return 0
            if args.sub == "reset":
                shown = reset(root, args.name)
                print(f"password for {args.name.strip().lower()}, shown once: {shown}")
                return 0
        except AccountError as exc:
            raise SystemExit(str(exc)) from exc
        for item in public_list(root):
            print(f"{item['name']}  {item['actor']}")
        return 0
    if args.command == "factory" and args.sub == "watch":
        report = factory.watch_specs(root, build=args.build,
                                     publish=args.publish, merge=args.merge)
        if report.get("stopped"):
            print(f"stopped: {report.get('reason')}")
            return 0
        if not report["ran"] and not report["skipped"]:
            print("no watched feature specs. Set a repo to --trigger watch,")
            print("and tag an open authored issue feature-spec.")
            return 0
        for item in report["ran"]:
            if item.get("remote") == "built":
                state = "merged" if item.get("merged") else ("published" if item.get("published") else "committed")
                print(f"built {item['id']} on {item.get('branch')} [{state}]")
                continue
            print(f"assembled {item['id']} reach {item['reach']} -> {item['run_dir']}")
            if item.get("remote") == "not-implemented":
                print("  assembled only. To open a pull request from an isolated branch:")
                print(f"  python -m stead factory publish --contribution {item['id']}")
        for item in report["skipped"]:
            print(f"skipped {item['id']}: {item['reason']}")
        return 0
    if args.command == "factory" and args.sub in ("stop", "start"):
        from ctx import safety
        state = safety.set_stopped(root, args.sub == "stop")
        if state["stopped"]:
            print("stopped. Builds and watched runs halt between steps.")
            print("existing processes finish their current step. Run "
                  "`python -m stead factory start` to resume.")
        else:
            print("started. Builds and watched runs may run again.")
        return 0
    if args.command == "factory" and args.sub == "defaults":
        from ctx.autonomy import AutonomyError, factory_defaults, set_defaults
        try:
            if (args.trigger or args.reach or args.max_builds_per_day is not None
                    or args.build_minutes is not None
                    or args.max_tokens_per_build is not None
                    or args.max_cost_per_build is not None):
                shown = set_defaults(
                    root, trigger=args.trigger, reach=args.reach,
                    max_builds_per_day=args.max_builds_per_day,
                    build_minutes=args.build_minutes,
                    max_tokens_per_build=args.max_tokens_per_build,
                    max_cost_per_build_usd=args.max_cost_per_build)
                print("install default saved in stead.json (gitignored)")
            else:
                shown = factory_defaults(root)
        except AutonomyError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"trigger: {shown['trigger']}")
        print(f"reach: {shown['reach']}")
        print(f"max builds per day: {shown['max_builds_per_day']}")
        print(f"minutes per build: {shown['build_minutes']}")
        print(f"tokens per build: {shown['max_tokens_per_build'] or 'off'}")
        print(f"cost per build (USD): {shown['max_cost_per_build_usd'] or 'off'}")
        print("merge is not an install default. Set it on the repo.")
        return 0
    if args.command == "welcome":
        from ctx.onboard import OnboardError, welcome as run_welcome
        try:
            result = run_welcome(root, args.title, url=args.url)
        except OnboardError as exc:
            raise SystemExit(str(exc)) from exc
        from ctx.config import ConfigError, choose
        try:
            chosen = choose(root, args.deployment)
        except ConfigError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"welcome {result['project']}")
        print(f"repo: {result['repo']}")
        print(f"deployment: {chosen['deployment']}")
        if chosen.get("access_token"):
            print("access token (shown once, not saved in git):")
            print(chosen["access_token"])
            print("Shared server: set STEAD_ACCESS_TOKEN to that value, then")
            print("  docker compose up --build")
            print("This computer stays loopback until you start that container.")
        else:
            print("context/ is yours now. Open the cockpit with: python -m stead ui")
        return 0
    if args.command == "onboard":
        from ctx.onboard import OnboardError, onboard
        try:
            result = onboard(root, args.title, kind=args.kind, url=args.url,
                             code_path=args.path, method=args.method,
                             integration=args.integration,
                             run_specify_init=not args.no_specify)
        except OnboardError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"onboarded {result['project']}")
        print(f"repo: {result['repo']} [{result['kind']}]")
        print(f"constitution: {result['constitution']}")
        print(f"method: {result['method']}")
        if result["code_path"]:
            print(f"code path: {result['code_path']}")
        print(f"specify: {result['specify']}")
        if result["specify_detail"]:
            print(result["specify_detail"])
        if result["specify_command"] and result["specify"] != "ran":
            print(f"command: {result['specify_command']}")
        print("no push, no pull request")
        return 0
    if args.command == "ui":
        from ctx import ui as cockpit
        return cockpit.serve(root, args.host, args.port,
                             open_browser=not args.no_browser, deploy=args.deploy)
    raise SystemExit(f"unhandled command: {args.command}")
