"""`stead metrics --json` exposes attempts, build_failures, and infra_failures."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ctx import frontmatter, metrics, writeback


class MetricsJsonFieldsTest(unittest.TestCase):
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
        base = {"branch": "stead/x", "commit": "abc", "files": ["app.py"],
                "deleted": [], "checks": "make test", "checks_mode": "docker",
                "tests_touched": [], "tests_deleted": [],
                "elapsed_seconds": 1.0, "repair_rounds": 0,
                "summary": "done", "published": True, "merged": False}
        base.update(over)
        return base

    def test_collect_returns_integer_attempt_and_failure_fields(self) -> None:
        cid_success = self._contrib(1)
        cid_build = self._contrib(2)
        cid_infra = self._contrib(3)
        writeback.record_delivery(self.root, cid_success, self._result())
        writeback.record_failure(self.root, cid_build, ValueError("checks failed"),
                                 branch="stead/x", reason="checks")
        writeback.record_failure(self.root, cid_infra, ValueError("model down"),
                                 branch="stead/x", reason="infrastructure")
        report = metrics.collect(self.root)
        for key in ("attempts", "build_failures", "infra_failures"):
            self.assertIn(key, report)
            self.assertIsInstance(report[key], int)
            self.assertNotIsInstance(report[key], bool)
        self.assertEqual(report["builds"], 3)
        self.assertEqual(report["infra_failures"], 1)
        self.assertEqual(report["build_failures"], 1)
        self.assertEqual(report["attempts"], 2)
        self.assertEqual(report["attempts"],
                         report["builds"] - report["infra_failures"])

    def test_json_payload_has_top_level_integer_fields(self) -> None:
        cid_success = self._contrib(1)
        cid_infra = self._contrib(2)
        writeback.record_delivery(self.root, cid_success, self._result())
        writeback.record_failure(self.root, cid_infra, ValueError("model down"),
                                 branch="stead/x", reason="infrastructure")
        report = metrics.collect(self.root)
        payload = json.loads(json.dumps(report, indent=2))
        for key in ("attempts", "build_failures", "infra_failures"):
            self.assertIn(key, payload)
            self.assertIsInstance(payload[key], int)
            self.assertNotIsInstance(payload[key], bool)
        self.assertEqual(payload["attempts"], 1)
        self.assertEqual(payload["build_failures"], 0)
        self.assertEqual(payload["infra_failures"], 1)

    def test_empty_store_reports_zero_integer_fields(self) -> None:
        report = metrics.collect(self.root)
        for key in ("attempts", "build_failures", "infra_failures"):
            self.assertIn(key, report)
            self.assertIsInstance(report[key], int)
            self.assertNotIsInstance(report[key], bool)
            self.assertEqual(report[key], 0)
