"""Unit tests: schema init, task add/list/set, status rollup, factory run, prompts.

All tests run against a temporary root — never the real repo state.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import cli, db, factory, frontmatter, objects


def make_root(base: Path) -> Path:
    """A minimal but valid repo skeleton for tests."""
    root = base / "repo"
    for sub in ("context/projects", "context/tasks", "context/documents",
                "context/meetings", "factories/weekly-project-status/prompts",
                "factories/weekly-project-status/evals"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    meta = {"id": "project-demo", "type": "project", "title": "Demo Project",
            "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}
    (root / "context/projects/demo.md").write_text(
        frontmatter.dumps(meta, "# Demo Project\n\nA test project.\n"), encoding="utf-8")
    (root / "factories/weekly-project-status/FACTORY.md").write_text(
        "# FACTORY: weekly-project-status\n", encoding="utf-8")
    (root / "factories/weekly-project-status/prompts/v1.md").write_text(
        "Draft a weekly status update from the bundle below.\n", encoding="utf-8")
    return root


class CtxTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_root(Path(self._tmp.name))


class TestFrontmatter(unittest.TestCase):
    def test_roundtrip(self) -> None:
        meta = {"id": "task-x", "type": "task", "title": "X: a title",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "to-do", "project": "project-demo",
                "related": ["document-a", "document-b"]}
        text = frontmatter.dumps(meta, "# X\n\nBody text.\n")
        parsed, body = frontmatter.parse(text)
        self.assertEqual(parsed, meta)
        self.assertIn("Body text.", body)

    def test_block_list_and_comments(self) -> None:
        text = "---\nid: task-y\ntype: task\nrelated:\n  - a\n  - b\n# comment\n---\nbody\n"
        meta, body = frontmatter.parse(text)
        self.assertEqual(meta["related"], ["a", "b"])
        self.assertEqual(body.strip(), "body")

    def test_no_frontmatter(self) -> None:
        meta, body = frontmatter.parse("just text\n")
        self.assertEqual(meta, {})
        self.assertEqual(body, "just text\n")


class TestInit(CtxTestCase):
    def test_init_creates_tables_and_seeds(self) -> None:
        counts = db.init_db(self.root)
        self.assertEqual(counts["prompt_versions"], 1)
        conn = db.connect(self.root)
        try:
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"tasks", "prompt_versions", "runs", "evals"} <= tables)
            row = conn.execute("SELECT status FROM prompt_versions "
                               "WHERE factory='weekly-project-status'").fetchone()
            self.assertEqual(row["status"], "production")
        finally:
            conn.close()

    def test_init_idempotent_and_reindexes_files(self) -> None:
        db.init_db(self.root)
        cli.cmd_task_add(self.root, "Hand-written later", "project-demo")
        db.init_db(self.root)  # rebuild must pick up the file, not duplicate rows
        conn = db.connect(self.root)
        try:
            n = conn.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
            self.assertEqual(n, 1)
        finally:
            conn.close()


class TestTasks(CtxTestCase):
    def setUp(self) -> None:
        super().setUp()
        db.init_db(self.root)

    def test_add_list_set(self) -> None:
        cli.cmd_task_add(self.root, "Write the docs", "project-demo")
        cli.cmd_task_add(self.root, "Ship it", "project-demo", status="doing")
        # markdown file created with correct frontmatter
        path = self.root / "context/tasks/write-the-docs.md"
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "task-write-the-docs")
        self.assertEqual(meta["project"], "project-demo")
        self.assertEqual(meta["status"], "to-do")
        # set updates file AND index
        cli.cmd_task_set(self.root, "task-write-the-docs", "done")
        meta, _ = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["status"], "done")
        conn = db.connect(self.root)
        try:
            rows = conn.execute("SELECT id, status FROM tasks ORDER BY id").fetchall()
            self.assertEqual([(r["id"], r["status"]) for r in rows],
                             [("task-ship-it", "doing"), ("task-write-the-docs", "done")])
        finally:
            conn.close()

    def test_add_rejects_unknown_project_and_bad_status(self) -> None:
        with self.assertRaises(SystemExit):
            cli.cmd_task_add(self.root, "Orphan", "project-nope")
        with self.assertRaises(SystemExit):
            cli.cmd_task_add(self.root, "Bad", "project-demo", status="wat")

    def test_duplicate_title_gets_unique_id(self) -> None:
        cli.cmd_task_add(self.root, "Same title", "project-demo")
        cli.cmd_task_add(self.root, "Same title", "project-demo")
        ids = {m["id"] for _p, m, _b in objects.iter_objects(self.root, "task")}
        self.assertEqual(ids, {"task-same-title", "task-same-title-2"})


class TestStatusRollup(CtxTestCase):
    def test_counts_and_runs(self) -> None:
        db.init_db(self.root)
        cli.cmd_task_add(self.root, "A", "project-demo", status="done")
        cli.cmd_task_add(self.root, "B", "project-demo", status="doing")
        cli.cmd_task_add(self.root, "C", "project-demo")
        cli.cmd_task_add(self.root, "D", "project-demo", status="blocked")
        tasks = objects.linked(self.root, "task", "project-demo")
        counts: dict[str, int] = {}
        for _p, m, _b in tasks:
            counts[m["status"]] = counts.get(m["status"], 0) + 1
        self.assertEqual(counts, {"done": 1, "doing": 1, "to-do": 1, "blocked": 1})
        # CLI status runs without error and a factory run shows up in the ledger
        self.assertEqual(cli.cmd_status(self.root, "project-demo"), 0)
        cli.cmd_factory_run(self.root, "weekly-project-status", "demo")
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT mode, verdict, project FROM runs").fetchone()
            self.assertEqual((row["mode"], row["verdict"], row["project"]),
                             ("shadow", "pending", "project-demo"))
        finally:
            conn.close()


class TestFactoryRun(CtxTestCase):
    def test_shadow_run_artifacts(self) -> None:
        db.init_db(self.root)
        cli.cmd_task_add(self.root, "Bundle me", "project-demo")
        info = factory.assemble(self.root, "weekly-project-status", "demo")
        self.assertEqual(cli.cmd_factory_run(self.root, "weekly-project-status", "demo"), 0)
        run_dir = self.root / info["run_dir"]
        for name in ("bundle.md", "prompt.md", "run.json"):
            self.assertTrue((run_dir / name).exists(), name)
        bundle = (run_dir / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("Demo Project", bundle)
        self.assertIn("Bundle me", bundle)
        prompt = (run_dir / "prompt.md").read_text(encoding="utf-8")
        self.assertTrue(prompt.startswith("Draft a weekly status update"))
        self.assertIn("Context bundle", prompt)
        self.assertEqual(info["mode"], "shadow")

    def test_unknown_project_and_factory_fail(self) -> None:
        db.init_db(self.root)
        with self.assertRaises(SystemExit):
            cli.cmd_factory_run(self.root, "weekly-project-status", "ghost")
        with self.assertRaises(SystemExit):
            cli.cmd_factory_run(self.root, "no-such-factory", "demo")


class TestRunLog(CtxTestCase):
    def test_run_log_records_output_and_verdict(self) -> None:
        db.init_db(self.root)
        cli.cmd_run_log(self.root, "weekly-project-status", "project-demo", "v1",
                        output="Drafted update text.", verdict="approved",
                        project="project-demo")
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT output, verdict, mode FROM runs").fetchone()
            self.assertEqual((row["output"], row["verdict"], row["mode"]),
                             ("Drafted update text.", "approved", "shadow"))
        finally:
            conn.close()


class TestPrompts(CtxTestCase):
    def test_promote_retires_old_production(self) -> None:
        db.init_db(self.root)
        v2 = self.root / "factories/weekly-project-status/prompts/v2.md"
        v2.write_text("Improved prompt.\n", encoding="utf-8")
        cli.cmd_prompt_promote(self.root, "weekly-project-status", "v2")
        conn = db.connect(self.root)
        try:
            rows = {r["version"]: r["status"] for r in conn.execute(
                "SELECT version, status FROM prompt_versions")}
            self.assertEqual(rows, {"v1": "retired", "v2": "production"})
        finally:
            conn.close()

    def test_promote_requires_prompt_file(self) -> None:
        db.init_db(self.root)
        with self.assertRaises(SystemExit):
            cli.cmd_prompt_promote(self.root, "weekly-project-status", "v9")


if __name__ == "__main__":
    unittest.main()
