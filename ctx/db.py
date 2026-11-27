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
    conn = sqlite3.connect(db_path(root), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
    except sqlite3.OperationalError:
        pass  # read-only or unsupported filesystem: fall back to default journal mode
    return conn


def require_db(root: Path) -> None:
    if not db_path(root).exists():
        raise SystemExit("state.db not found — run `python -m stead init` first.")


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
        "(id, title, repo, kind, number, url, role, state, ci, review, method, visibility, path, created, updated) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (meta["id"], meta["title"], meta.get("repo", ""), meta.get("kind", "issue"),
         int(meta.get("number", 0)), meta.get("url"), meta.get("role", "author"),
         meta.get("state", "open"), meta.get("ci", "none"), meta.get("review", "none"),
         meta.get("method", "spec-kit"), meta.get("visibility", "public"),
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


def _prompt_paths(pdir: Path) -> list[Path]:
    return sorted(
        (p for p in pdir.glob("v*.md") if p.stem[1:].isdigit()),
        key=lambda p: int(p.stem[1:]),
    )


def _has_tables(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    names = {row["name"] for row in rows}
    return {"tasks", "repos", "contributions", "prompt_versions", "runs", "evals"} <= names


def init_db(root: Path, *, reset: bool = False) -> dict[str, int]:
    """Idempotent rebuild of the markdown index in state.db.

    When state.db already exists and ``reset`` is False, preserves the append-only
    ``runs`` ledger and existing ``prompt_versions`` promotions while rebuilding
    the index tables (`tasks`, `repos`, `contributions`, `evals`) and seeding any
    newly discovered prompt files. Pass ``reset=True`` to drop and recreate all
    tables from schema.sql."""
    existed = db_path(root).exists()
    conn = connect(root)
    try:
        preserve = existed and not reset and _has_tables(conn)
        if not preserve:
            conn.executescript((PKG_DIR / "schema.sql").read_text(encoding="utf-8"))
        else:
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM repos")
            conn.execute("DELETE FROM contributions")
            conn.execute("DELETE FROM evals")
        today = date.today().isoformat()

        # Seed prompt versions from factories/*/prompts/v*.md. For a fresh
        # factory (no rows yet), the HIGHEST version is production and lower
        # versions are retired. When preserving an existing DB, newly added
        # prompt files for an already-indexed factory are inserted as 'testing'
        # so an explicit promotion or rollback is never clobbered.
        n_prompts = 0
        fdirs = sorted((root / "factories").iterdir()) if (root / "factories").is_dir() else []
        for fdir in fdirs:
            pdir = fdir / "prompts"
            if not (fdir.is_dir() and pdir.is_dir()):
                continue
            paths = _prompt_paths(pdir)
            if not paths:
                continue
            existing_versions = {
                row["version"] for row in conn.execute(
                    "SELECT version FROM prompt_versions WHERE factory = ?",
                    (fdir.name,),
                ).fetchall()
            } if preserve else set()
            latest = paths[-1]
            for prompt_path in paths:
                version = prompt_path.stem
                if version in existing_versions:
                    n_prompts += 1
                    continue
                if existing_versions:
                    status = "testing"
                else:
                    status = "production" if prompt_path == latest else "retired"
                conn.execute(
                    "INSERT INTO prompt_versions (factory, version, status, path, created) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (fdir.name, version, status,
                     prompt_path.relative_to(root).as_posix(), today),
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


def index_new_factory(root: Path, name: str) -> None:
    """Index one newly scaffolded factory's prompts + evals without rebuilding the
    database. A full init_db drops the runs ledger and resets every factory's
    production prompt; this touches only the new factory's rows."""
    if not db_path(root).exists():
        init_db(root)
        return
    conn = connect(root)
    try:
        fdir = root / "factories" / name
        today = date.today().isoformat()
        pdir = fdir / "prompts"
        paths = _prompt_paths(pdir) if pdir.is_dir() else []
        if paths:
            latest = paths[-1]
            for prompt_path in paths:
                status = "production" if prompt_path == latest else "retired"
                conn.execute(
                    "INSERT OR REPLACE INTO prompt_versions (factory, version, status, path, created) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (name, prompt_path.stem, status,
                     prompt_path.relative_to(root).as_posix(), today))
        for eval_path in sorted((fdir / "evals").glob("*.json")):
            case = json.loads(eval_path.read_text(encoding="utf-8"))
            conn.execute(
                "INSERT OR REPLACE INTO evals (id, factory, title, input, pass_criteria, path) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (case["id"], name, case["title"], case["input"], case["pass_criteria"],
                 eval_path.relative_to(root).as_posix()))
        conn.commit()
    finally:
        conn.close()


def forget_factory(root: Path, name: str) -> None:
    """Remove one deleted factory's index rows (prompts, evals, runs). Leaves every
    other factory's rows and the rest of the runs ledger intact."""
    if not db_path(root).exists():
        return
    conn = connect(root)
    try:
        conn.execute("DELETE FROM prompt_versions WHERE factory = ?", (name,))
        conn.execute("DELETE FROM evals WHERE factory = ?", (name,))
        conn.execute("DELETE FROM runs WHERE factory = ?", (name,))
        conn.commit()
    finally:
        conn.close()
