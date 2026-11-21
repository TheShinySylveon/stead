"""SQLite operational state. state.db is rebuildable; markdown is truth.

Stdlib sqlite3 only. `init_db` drops/recreates tables from schema.sql, seeds
the production prompt version, re-indexes task files, and loads eval JSON.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from ctx import objects

PKG_DIR = Path(__file__).resolve().parent
FIRST_FACTORY = "weekly-contribution-digest"
LEGACY_FACTORY = "weekly-project-status"


def db_path(root: Path) -> Path:
    return root / "state.db"


def connect(root: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path(root))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def require_db(root: Path) -> None:
    if not db_path(root).exists():
        raise SystemExit("state.db not found — run `python3 -m ctx init` first.")


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def index_repo(conn: sqlite3.Connection, root: Path, path: Path, meta: dict,
               today: str) -> None:
    """Upsert one context/repos/ file into the repos index."""
    conn.execute(
        "INSERT OR REPLACE INTO repos "
        "(id, title, kind, url, default_branch, status, contributing, notes, path, created, updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (meta["id"], meta["title"], meta.get("kind", "oss"), meta.get("url"),
         meta.get("default_branch"), meta.get("status", "active"),
         meta.get("contributing"), meta.get("notes"),
         path.relative_to(root).as_posix(),
         meta.get("created", today), meta.get("updated", today)),
    )


def index_contribution(conn: sqlite3.Connection, root: Path, path: Path, meta: dict,
                       today: str) -> None:
    """Upsert one context/contributions/ file into the contributions index."""
    conn.execute(
        "INSERT OR REPLACE INTO contributions "
        "(id, title, repo, kind, number, url, role, state, ci, review, visibility, path, created, updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (meta["id"], meta["title"], meta.get("repo", ""), meta.get("kind", "issue"),
         int(meta.get("number", 0)), meta.get("url"), meta.get("role", "author"),
         meta.get("state", "open"), meta.get("ci", "none"), meta.get("review", "none"),
         meta.get("visibility", "public"),
         path.relative_to(root).as_posix(),
         meta.get("created", today), meta.get("updated", today)),
    )


def reindex_github(conn: sqlite3.Connection, root: Path) -> dict[str, int]:
    """Re-index repos + contributions from markdown (source of truth)."""
    today = date.today().isoformat()
    n_repos = n_contribs = 0
    for path, meta, _body in objects.iter_objects(root, "repo"):
        index_repo(conn, root, path, meta, today)
        n_repos += 1
    for path, meta, _body in objects.iter_objects(root, "contribution"):
        index_contribution(conn, root, path, meta, today)
        n_contribs += 1
    return {"repos": n_repos, "contributions": n_contribs}


def init_db(root: Path) -> dict[str, int]:
    """Idempotent rebuild of state.db from schema.sql + source files."""
    conn = connect(root)
    try:
        conn.executescript((PKG_DIR / "schema.sql").read_text(encoding="utf-8"))
        today = date.today().isoformat()

        # Seed v1 = production for every factory that ships prompts/v1.md
        # (weekly-contribution-digest is the first factory; weekly-project-status
        # remains valid for own projects).
        n_prompts = 0
        fdirs = sorted((root / "factories").iterdir()) if (root / "factories").is_dir() else []
        for fdir in fdirs:
            v1 = fdir / "prompts" / "v1.md"
            if fdir.is_dir() and v1.exists():
                conn.execute(
                    "INSERT INTO prompt_versions (factory, version, status, path, created) "
                    "VALUES (?, 'v1', 'production', ?, ?)",
                    (fdir.name, v1.relative_to(root).as_posix(), today),
                )
                n_prompts += 1

        # Re-index tasks from markdown (source of truth).
        n_tasks = 0
        for path, meta, _body in objects.iter_objects(root, "task"):
            conn.execute(
                "INSERT OR REPLACE INTO tasks (id, title, project, status, path, created, updated) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (meta["id"], meta["title"], meta.get("project"),
                 meta.get("status", "to-do"),
                 path.relative_to(root).as_posix(),
                 meta.get("created", today), meta.get("updated", today)),
            )
            n_tasks += 1

        # Re-index repos + contributions from markdown (GitHub cache layer).
        gh_counts = reindex_github(conn, root)

        # Load eval cases from factories/*/evals/*.json.
        n_evals = 0
        for eval_path in sorted((root / "factories").glob("*/evals/*.json")):
            case = json.loads(eval_path.read_text(encoding="utf-8"))
            factory = eval_path.parent.parent.name
            conn.execute(
                "INSERT OR REPLACE INTO evals (id, factory, title, input, pass_criteria, path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (case["id"], factory, case["title"], case["input"],
                 case["pass_criteria"], eval_path.relative_to(root).as_posix()),
            )
            n_evals += 1

        conn.commit()
        return {"tasks": n_tasks, "evals": n_evals, "prompt_versions": n_prompts,
                "repos": gh_counts["repos"], "contributions": gh_counts["contributions"]}
    finally:
        conn.close()
