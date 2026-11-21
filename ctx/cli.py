"""Command-line interface: `python3 -m ctx <command>` (argparse, stdlib only).

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


# --- init -----------------------------------------------------------------

def cmd_init(root: Path) -> int:
    counts = db.init_db(root)
    print(f"state.db rebuilt from ctx/schema.sql "
          f"(tasks indexed: {counts['tasks']}, repos: {counts['repos']}, "
          f"contributions: {counts['contributions']}, evals loaded: {counts['evals']}, "
          f"prompt versions seeded: {counts['prompt_versions']})")
    from ctx.onboard import needs_welcome
    if needs_welcome(root):
        print("No projects yet. First run:")
        print("  python3 -m ctx ui")
        print("  python3 -m ctx welcome --title \"My Project\"")
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
    print(f"added {task_id} [{status}] -> {_rel(root, path)}")
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
    path = root / "context" / "repos" / f"{slug}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(meta, f"# {title}\n"), encoding="utf-8")

    conn = db.connect(root)
    try:
        db.index_repo(conn, root, path, meta, today)
        conn.commit()
    finally:
        conn.close()
    print(f"added {repo_id} [{kind}] -> {_rel(root, path)}")
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
        raise SystemExit(f"repo not found: {repo!r} — add it with `ctx repo add` first")
    _rpath, rmeta, _rbody = found
    repo_id = rmeta["id"]
    stem = f"{repo_id.removeprefix('repo-')}-{kind}-{number}"
    path = root / "context" / "contributions" / f"{stem}.md"
    if path.exists():
        raise SystemExit(f"contribution already exists: contribution-{stem} "
                         "— use `ctx contribution set` to update it")
    if not url and rmeta.get("url"):
        url = f"{rmeta['url'].rstrip('/')}/{'pull' if kind == 'pr' else 'issues'}/{number}"
    today = date.today().isoformat()
    meta = {"id": f"contribution-{stem}", "type": "contribution", "title": title,
            "created": today, "updated": today, "repo": repo_id, "kind": kind,
            "number": number, "role": role, "state": state, "ci": ci,
            "review": review, "method": method, "visibility": "public"}
    if url:
        meta["url"] = url
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(frontmatter.dumps(meta, f"# {title}\n"), encoding="utf-8")

    conn = db.connect(root)
    try:
        db.index_contribution(conn, root, path, meta, today)
        conn.commit()
    finally:
        conn.close()
    print(f"added contribution-{stem} [{kind} #{number}, {role}] -> {_rel(root, path)}")
    return 0


def cmd_contribution_list(root: Path, repo: str | None = None, kind: str | None = None,
                          role: str | None = None, state: str | None = None) -> int:
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
                    offline: bool = False) -> int:
    result = sync.sync_github(root, author=author, limit=limit, offline=offline)
    if result["offline"]:
        print(f"sync github --offline: no network used; re-indexed local cache "
              f"({result['repos']} repos, {result['contributions']} contributions)")
    else:
        print(f"sync github: fetched {result['fetched']} items via gh (read-only); "
              f"{result['new']} new, {result['updated']} updated contribution files")
        print(f"index now: {result['repos']} repos, {result['contributions']} contributions")
    print("next: python3 -m ctx factory run --factory weekly-contribution-digest --shadow")
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
        print("  (state.db missing — run `python3 -m ctx init`)")
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
    print(f"{factory_name}: {version} is now production (previous production retired)")
    return 0


# --- factory run --------------------------------------------------------------

def cmd_feature_build(root: Path, contribution: str, live: bool = False,
                      *, generate: bool = False) -> int:
    mode = "live" if live else "shadow"
    info = _maybe_draft(root, factory.assemble_feature_build(root, contribution, mode=mode), generate)
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
    _print_draft(info, generate, coding=True)
    return 0


def cmd_factory_run(root: Path, factory_name: str, project: str | None,
                    live: bool = False, contribution: str | None = None,
                    *, generate: bool = False) -> int:
    mode = "live" if live else "shadow"
    if contribution is not None and factory_name != factory.FEATURE_BUILDER_FACTORY:
        raise SystemExit("--contribution is only valid for --factory feature-builder")
    if factory_name == factory.FEATURE_BUILDER_FACTORY:
        if contribution is None:
            raise SystemExit("--contribution is required for factory 'feature-builder' "
                             "(a spec contribution: kind issue, role author, "
                             "with a ## Acceptance criteria checklist)")
        return cmd_feature_build(root, contribution, live=live, generate=generate)
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
    print(f"  python3 -m ctx run log --factory {info['factory']} --task "
          f"{info.get('contribution') or info.get('project') or 'contributions'} "
          f"--prompt-version {info['prompt_version']} --output TEXT --verdict approved|rejected")
    print("\n--- assembled prompt ---\n")
    print(info["assembled_prompt"])


# --- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctx", description="Stead — local context you own. Command: ctx. Stdlib only.")
    p.add_argument("--root", default=".", help="repo root (default: current directory)")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="print the Stead version")
    sub.add_parser("init", help="rebuild state.db from schema.sql + markdown (idempotent)")

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

    sy = sub.add_parser("sync", help="sync external context (read-only)").add_subparsers(dest="sub", required=True)
    sg = sy.add_parser("github", help="cache your GitHub PRs/reviews/issues via gh (READ-ONLY)")
    sg.add_argument("--author", default="@me")
    sg.add_argument("--limit", type=int, default=30)
    sg.add_argument("--offline", action="store_true",
                    help="skip network; re-index existing contribution files")

    model = sub.add_parser("model", help="the rented model factories may draft with").add_subparsers(dest="sub", required=True)
    model.add_parser("show", help="show the configured model. Never prints the key.")
    ms = model.add_parser("set", help="choose an OpenAI-compatible endpoint")
    ms.add_argument("--provider", required=True, choices=("openai", "openrouter", "ollama", "custom"))
    ms.add_argument("--name", required=True, help="model name, such as gpt-4.1-mini or llama3.2")
    ms.add_argument("--base-url", help="defaults to the provider preset")
    ms.add_argument("--key", help="stored in gitignored stead.json. Prefer STEAD_MODEL_API_KEY.")
    ms.add_argument("--key-env", default="STEAD_MODEL_API_KEY")

    ev = sub.add_parser("eval", help="factory eval cases").add_subparsers(dest="sub", required=True)
    er = ev.add_parser("run", help="check eval files. No model, no network.")
    er.add_argument("--factory")
    ej = ev.add_parser("judge", help="ask the configured model to judge one draft")
    ej.add_argument("--factory", required=True)
    ej.add_argument("--case", required=True)
    ej.add_argument("--output", required=True, help="path to the draft markdown")

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

    pr = sub.add_parser("prompt", help="versioned prompts").add_subparsers(dest="sub", required=True)
    pl = pr.add_parser("list", help="list prompt versions")
    pl.add_argument("--factory", required=True)
    pp = pr.add_parser("promote", help="promote a version to production (retire old)")
    pp.add_argument("--factory", required=True)
    pp.add_argument("--version", required=True)

    fr = sub.add_parser("factory", help="factory runner").add_subparsers(dest="sub", required=True)
    frun = fr.add_parser("run", help="assemble a bundle. --generate drafts with the configured model.")
    frun.add_argument("--factory", required=True)
    frun.add_argument("--project", help="project id (not needed for weekly-contribution-digest)")
    frun.add_argument("--contribution", help="spec contribution id (required for feature-builder)")
    frun.add_argument("--shadow", action="store_true", help="shadow mode (default)")
    frun.add_argument("--live", action="store_true", help="record as live. Still does not push or open a PR.")
    frun.add_argument("--generate", action="store_true",
                      help="draft with the configured model. Nothing is posted or pushed.")

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
    cockpit.add_argument("--port", type=int, default=None)
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
        print("  python3 -m ctx ui")
        print("  python3 -m ctx welcome --title \"My Project\"")
        print("  python3 -m ctx --help")
        return 0
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "version":
        from ctx import __version__
        print(__version__)
        return 0
    if args.command == "init":
        return cmd_init(root)
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
    if args.command == "contribution":
        if args.sub == "add":
            return cmd_contribution_add(root, args.title, args.repo, args.kind,
                                        args.number, args.url, args.role,
                                        args.state, args.ci, args.review,
                                        args.method)
        if args.sub == "list":
            return cmd_contribution_list(root, args.repo, args.kind, args.role, args.state)
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
            print(f"added {added['id']} [{added['kind']}]")
            return 0
        for _path, meta, _body in objects.iter_objects(root, "actor"):
            print(f"{meta.get('id')}  {meta.get('kind', 'human')}  {meta.get('title')}")
        return 0
    if args.command == "sync" and args.sub == "github":
        return cmd_sync_github(root, args.author, args.limit, args.offline)
    if args.command == "model":
        from ctx import models
        try:
            if args.sub == "set":
                shown = models.set_model(
                    root, provider=args.provider, name=args.name,
                    base_url=args.base_url or "", api_key=args.key,
                    api_key_env=args.key_env)
                print("model saved in stead.json (gitignored). The key was not printed.")
            else:
                shown = models.public_model(root)
        except models.ModelError as exc:
            raise SystemExit(str(exc)) from exc
        print(f"provider: {shown['provider'] or '(none)'}")
        print(f"model: {shown['name'] or '(none)'}")
        print(f"base_url: {shown['base_url'] or '(none)'}")
        print(f"key: {'set (' + shown['key_from'] + ')' if shown['key_set'] else 'not set'} "
              f"via {shown['key_env']}")
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
            judged = models.judge(root, args.factory, args.case, args.output)
        except (models.ModelError, OSError) as exc:
            raise SystemExit(str(exc)) from exc
        print(f"{judged['verdict']}: {judged['reason']}")
        print(f"recorded: {judged['path']}")
        return 0 if judged["verdict"] == "pass" else 1
    if args.command == "digest":
        return cmd_digest(root, live=args.live, generate=args.generate)
    if args.command == "status":
        return cmd_status(root, args.project)
    if args.command == "run" and args.sub == "log":
        return cmd_run_log(root, args.factory, args.task, args.prompt_version,
                           args.output, args.verdict, args.project, args.mode)
    if args.command == "prompt":
        if args.sub == "list":
            return cmd_prompt_list(root, args.factory)
        if args.sub == "promote":
            return cmd_prompt_promote(root, args.factory, args.version)
    if args.command == "factory" and args.sub == "run":
        return cmd_factory_run(root, args.factory, args.project, live=args.live,
                               contribution=args.contribution, generate=args.generate)
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
            print("context/ is yours now. Open the cockpit with: python3 -m ctx ui")
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
