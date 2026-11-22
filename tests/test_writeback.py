"""Write-back: factual records on delivery, interpretive notes to the inbox."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import frontmatter, objects, writeback


class WritebackTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("repos", "contributions", "tasks", "documents"):
            (self.root / "context" / folder).mkdir(parents=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "project": "project-app"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        self.contrib_id = "contribution-me-app-issue-9"
        contrib = {"id": self.contrib_id, "type": "contribution", "title": "Flag",
                   "created": "2026-11-21", "updated": "2026-11-21",
                   "repo": "repo-me-app", "kind": "issue", "number": 9,
                   "role": "author", "state": "open", "visibility": "public"}
        (self.root / "context/contributions/issue-9.md").write_text(
            frontmatter.dumps(contrib, "# Flag\n"), encoding="utf-8")
        task = {"id": "task-flag", "type": "task", "title": "Ship the flag",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "doing", "project": "project-app",
                "related": [self.contrib_id]}
        (self.root / "context/tasks/flag.md").write_text(
            frontmatter.dumps(task, "# Ship the flag\n"), encoding="utf-8")

    def _result(self, **over) -> dict:
        base = {"branch": "stead/9-flag", "commit": "abc123", "files": ["app.py"],
                "deleted": [], "checks": "make test", "checks_mode": "docker",
                "summary": "Added the flag.", "published": True, "merged": False,
                "pr_url": "https://example.test/pr/9"}
        base.update(over)
        return base

    def test_delivery_writes_a_versioned_record(self) -> None:
        out = writeback.record_delivery(self.root, self.contrib_id, self._result(), run_id=7)
        path = self.root / out["path"]
        self.assertTrue(path.is_file())
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        self.assertIn("build-record", meta["tags"])
        self.assertIn("repo:repo-me-app", meta["tags"])
        self.assertEqual(meta["source_run"], "7")
        self.assertEqual(meta["project"], "project-app")
        self.assertIn("abc123", body)
        self.assertIn("published", out["outcome"])

    def test_merge_closes_the_contribution_and_linked_task(self) -> None:
        out = writeback.record_delivery(
            self.root, self.contrib_id, self._result(merged=True, merged_url="https://x/9"))
        self.assertEqual(out["outcome"], "merged")
        contrib = objects.find(self.root, "contribution", self.contrib_id)[1]
        self.assertEqual(contrib["state"], "merged")
        task = objects.find(self.root, "task", "task-flag")[1]
        self.assertEqual(task["status"], "done")
        self.assertIn("task-flag", out["updated"])

    def test_prior_records_feed_the_next_bundle(self) -> None:
        writeback.record_delivery(self.root, self.contrib_id, self._result())
        records = writeback.prior_records(self.root, "repo-me-app")
        self.assertEqual(len(records), 1)
        self.assertIn("build-record", records[0][1]["tags"])

    def test_interpretive_notes_go_to_the_inbox(self) -> None:
        out = writeback.propose_note(self.root, "decision", "Use argparse",
                                     "We chose argparse over click.", source=self.contrib_id)
        path = self.root / out["path"]
        self.assertTrue(path.is_file())
        self.assertTrue(str(path).replace("\\", "/").endswith(".md"))
        self.assertIn("inbox", out["path"])
        self.assertIn("argparse", path.read_text(encoding="utf-8"))
        # nothing landed in context/documents
        self.assertEqual(list((self.root / "context/documents").glob("*.md")), [])

    def test_a_bad_proposal_is_refused(self) -> None:
        with self.assertRaises(writeback.WritebackError):
            writeback.propose_note(self.root, "decision", "", "text")
        with self.assertRaises(writeback.WritebackError):
            writeback.propose_note(self.root, "rant", "Title", "text")
