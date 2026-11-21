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
FIRST_FACTORY = "weekly-project-status"


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


def init_db(root: Path) -> dict[str, int]:
    """Idempotent rebuild of state.db from schema.sql + source files."""
    conn = connect(root)
    try:
        conn.executescript((PKG_DIR / "schema.sql").read_text(encoding="utf-8"))
        today = date.today().isoformat()

        # Seed the first factory's production prompt (v1).
        conn.execute(
            "INSERT INTO prompt_versions (factory, version, status, path, created) "
            "VALUES (?, 'v1', 'production', ?, ?)",
            (FIRST_FACTORY, f"factories/{FIRST_FACTORY}/prompts/v1.md", today),
        )

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
        return {"tasks": n_tasks, "evals": n_evals, "prompt_versions": 1}
    finally:
        conn.close()
