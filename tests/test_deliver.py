"""An approved draft becomes a private document. Nothing is posted."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import db, deliver, frontmatter


class DeliveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "context/projects").mkdir(parents=True)
        project = {"id": "project-demo", "type": "project", "title": "Demo",
                   "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}
        (self.root / "context/projects/demo.md").write_text(
            frontmatter.dumps(project, "# Demo\n"), encoding="utf-8")
        db.init_db(self.root)
        conn = db.connect(self.root)
        try:
            conn.execute(
                "INSERT INTO prompt_versions (factory, version, status, path, created) "
                "VALUES ('weekly-project-status', 'v1', 'production', "
                "'factories/weekly-project-status/prompts/v1.md', '2026-11-21')")
            conn.commit()
        finally:
            conn.close()

    def _run(self, verdict: str = "approved", output: str = "Project is on track.") -> int:
        conn = db.connect(self.root)
        try:
            cur = conn.execute(
                "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, "
                "output, verdict, created) VALUES "
                "('weekly-project-status', 'project-demo', 'project-demo', 'v1', "
                "'shadow', ?, ?, '2026-11-21T00:00:00Z')", (output, verdict))
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def test_approved_run_becomes_a_private_document(self) -> None:
        run_id = self._run()
        filed = deliver.file_run(self.root, run_id)
        path = filed["path"]
        self.assertTrue(path.is_file())
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertEqual(meta["type"], "document")
        self.assertEqual(meta["source_run"], str(run_id))
        self.assertEqual(meta["project"], "project-demo")
        self.assertIn("Project is on track.", body)
        self.assertIn("Nothing was posted", body)
        self.assertFalse(list((self.root / "context/contributions").glob("*.md")))

    def test_pending_run_is_refused(self) -> None:
        run_id = self._run(verdict="pending")
        with self.assertRaises(deliver.DeliveryError):
            deliver.file_run(self.root, run_id)
        self.assertFalse(list((self.root / "context/documents").glob("*.md")))

    def test_second_filing_is_refused(self) -> None:
        run_id = self._run()
        deliver.file_run(self.root, run_id)
        with self.assertRaises(deliver.DeliveryError):
            deliver.file_run(self.root, run_id)

    def test_feature_builder_output_is_not_filed(self) -> None:
        conn = db.connect(self.root)
        try:
            cur = conn.execute(
                "INSERT INTO runs (factory, task_ref, project, prompt_version, mode, "
                "output, verdict, created) VALUES "
                "('feature-builder', 'issue-1', NULL, 'v1', 'shadow', 'diff', "
                "'approved', '2026-11-21T00:00:00Z')")
            conn.commit()
            run_id = cur.lastrowid
        finally:
            conn.close()
        with self.assertRaises(deliver.DeliveryError):
            deliver.file_run(self.root, run_id)

    def test_title_override_is_used(self) -> None:
        run_id = self._run()
        filed = deliver.file_run(self.root, run_id, "Week 47 review")
        self.assertEqual(filed["id"], "document-week-47-review")
