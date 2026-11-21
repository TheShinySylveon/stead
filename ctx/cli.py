"""Command-line interface: `python3 -m ctx <command>` (argparse, stdlib only).

Handlers are plain functions taking a repo root Path so they are unit-testable
and callable from any scheduler or agent without a shell.
"""

from __future__ import annotations

import argparse
import re
from datetime import date
from pathlib import Path

from ctx import db, factory, frontmatter, objects

TASK_STATUSES = ("to-do", "doing", "done", "blocked")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "task"


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


# --- init -----------------------------------------------------------------

def cmd_init(root: Path) -> int:
    counts = db.init_db(root)
    print(f"state.db rebuilt from ctx/schema.sql "
          f"(tasks indexed: {counts['tasks']}, evals loaded: {counts['evals']}, "
          f"prompt versions seeded: {counts['prompt_versions']})")
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

def cmd_factory_run(root: Path, factory_name: str, project: str, live: bool = False) -> int:
    mode = "live" if live else "shadow"
    info = factory.assemble(root, factory_name, project, mode=mode)
    print(f"run {info['run_id']} recorded [{mode}] — {info['factory']} "
          f"prompt {info['prompt_version']} for {info['project']}")
    c = info["counts"]
    print(f"bundle: {c['tasks']} tasks, {c['documents']} documents, {c['meetings']} meetings")
    print(f"run dir: {info['run_dir']}/ (bundle.md, prompt.md, run.json)")
    print("no LLM call made — hand prompt.md to any agent/human, then record the result:")
    print(f"  python3 -m ctx run log --factory {info['factory']} --task {info['project']} "
          f"--prompt-version {info['prompt_version']} --output TEXT --verdict approved|rejected")
    print("\n--- assembled prompt ---\n")
    print(info["assembled_prompt"])
    return 0


# --- parser -------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctx", description="Shared Context CLI — stdlib only, local-first, tool-agnostic.")
    p.add_argument("--root", default=".", help="repo root (default: current directory)")
    sub = p.add_subparsers(dest="command", required=True)

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

    fr = sub.add_parser("factory", help="factory runner (deterministic, no LLM)").add_subparsers(dest="sub", required=True)
    frun = fr.add_parser("run", help="assemble context bundle + prompt, record a run")
    frun.add_argument("--factory", required=True)
    frun.add_argument("--project", required=True)
    frun.add_argument("--shadow", action="store_true", help="shadow mode (default)")
    frun.add_argument("--live", action="store_true", help="record as a live run (still no LLM call)")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "init":
        return cmd_init(root)
    if args.command == "task":
        if args.sub == "add":
            return cmd_task_add(root, args.title, args.project, args.status)
        if args.sub == "list":
            return cmd_task_list(root, args.project, args.status)
        if args.sub == "set":
            return cmd_task_set(root, args.id, args.status)
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
        return cmd_factory_run(root, args.factory, args.project, live=args.live)
    raise SystemExit(f"unhandled command: {args.command}")
