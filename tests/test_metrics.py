"""`stead metrics` reports what the factory actually did, from build records."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import frontmatter, metrics, writeback


class MetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("repos", "contributions", "documents"):
            (self.root / "context" / folder).mkdir(parents=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")

    def _contrib(self, number: int) -> str:
        cid = f"contribution-me-app-issue-{number}"
        meta = {"id": cid, "type": "contribution", "title": f"Feature {number}",
                "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-me-app", "kind": "issue", "number": number,
                "role": "author", "state": "open", "visibility": "public"}
        (self.root / "context/contributions" / f"issue-{number}.md").write_text(
            frontmatter.dumps(meta, f"# Feature {number}\n"), encoding="utf-8")
        return cid

    def _result(self, **over) -> dict:
        base = {"branch": "stead/x", "commit": "abc", "files": ["app.py", "util.py"],
                "deleted": [], "checks": "make test", "checks_mode": "docker",
                "tests_touched": ["tests/test_app.py"], "tests_deleted": [],
                "elapsed_seconds": 12.0, "repair_rounds": 1,
                "summary": "done", "published": True, "merged": False}
        base.update(over)
        return base

    def test_empty_store(self) -> None:
        report = metrics.collect(self.root)
        self.assertEqual(report["builds"], 0)
        self.assertIn("No build records", metrics.render(report))

    def test_aggregates_outcomes_time_and_tests(self) -> None:
        writeback.record_delivery(self.root, self._contrib(1), self._result())
        writeback.record_delivery(
            self.root, self._contrib(2),
            self._result(merged=True, checks_mode="host", elapsed_seconds=8.0,
                         repair_rounds=0, files=["app.py"],
                         tests_touched=[], tests_deleted=["tests/test_old.py"]))
        report = metrics.collect(self.root)
        self.assertEqual(report["builds"], 2)
        self.assertEqual(report["outcomes"]["merged"], 1)
        self.assertEqual(report["outcomes"]["published"], 1)
        self.assertEqual(report["merged_share"], 0.5)
        self.assertEqual(report["checks_modes"]["docker"], 1)
        self.assertEqual(report["checks_modes"]["host"], 1)
        self.assertEqual(report["avg_elapsed_seconds"], 10.0)
        self.assertEqual(report["repair_rounds"], 1)
        self.assertEqual(report["files_touched"], 3)
        self.assertEqual(report["tests_touched"], 1)
        self.assertEqual(report["tests_deleted"], 1)
        self.assertEqual(report["by_repo"]["repo-me-app"], 2)
        text = metrics.render(report)
        self.assertIn("merged share: 50%", text)
        self.assertIn("repo-me-app=2", text)

    def test_repo_filter(self) -> None:
        writeback.record_delivery(self.root, self._contrib(1), self._result())
        self.assertEqual(metrics.collect(self.root, repo="repo-me-app")["builds"], 1)
        self.assertEqual(metrics.collect(self.root, repo="repo-other")["builds"], 0)
