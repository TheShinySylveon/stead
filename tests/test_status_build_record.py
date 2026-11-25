"""Tests for the build-record summary line in `stead status --project P`."""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ctx import cli


class StatusBuildRecordTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, rel: str, content: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def _project(self, pid: str, title: str = "Test Project") -> None:
        self._write(
            f"context/projects/{pid}.md",
            f"---\nid: {pid}\ntype: project\ntitle: {title}\n"
            f"status: active\ncreated: 2025-01-01\nupdated: 2025-01-01\n---\n"
            f"# {title}\n",
        )

    def _repo(self, rid: str, pid: str, title: str = "Test Repo") -> None:
        self._write(
            f"context/repos/{rid}.md",
            f"---\nid: {rid}\ntype: repo\ntitle: {title}\n"
            f"project: {pid}\nstatus: active\ncreated: 2025-01-01\n"
            f"updated: 2025-01-01\n---\n# {title}\n",
        )

    def _record(self, rid: str, outcome: str, reason: str, created: str,
                stamp: str, slug: str = "test") -> None:
        doc_id = f"document-build-{slug}-{stamp}"
        fname = f"build-{slug}-{stamp}.md"
        self._write(
            f"context/documents/{fname}",
            f"---\nid: {doc_id}\ntype: document\ntitle: Build: Test\n"
            f"created: {created}\nupdated: {created}\nstatus: active\n"
            f"tags: [build-record, repo:{rid}]\noutcome: {outcome}\n"
            f"reason: {reason}\n---\n# Build record\n",
        )

    def _status_output(self, project: str) -> tuple[int, str]:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.cmd_status(self.root, project)
        return rc, buf.getvalue()

    def test_newest_record_wins(self):
        self._project("project-p")
        self._repo("repo-r", "project-p")
        self._record("repo-r", "failed", "old failure", "2025-01-01",
                     "20250101T000000Z", "old")
        self._record("repo-r", "succeeded", "all tests passed", "2025-01-02",
                     "20250102T000000Z", "new")

        rc, out = self._status_output("project-p")
        self.assertEqual(rc, 0)
        lines = [ln.strip() for ln in out.splitlines()]
        self.assertIn("build: succeeded (all tests passed) 2025-01-02", lines)
        self.assertNotIn("build: failed (old failure) 2025-01-01", lines)

    def test_no_records_prints_none(self):
        self._project("project-p")
        self._repo("repo-r", "project-p")

        rc, out = self._status_output("project-p")
        self.assertEqual(rc, 0)
        lines = [ln.strip() for ln in out.splitlines()]
        self.assertIn("build: none", lines)

    def test_no_cross_talk_between_projects(self):
        self._project("project-p1")
        self._project("project-p2")
        self._repo("repo-r1", "project-p1")
        self._repo("repo-r2", "project-p2")
        self._record("repo-r1", "succeeded", "repo one", "2025-01-01",
                     "20250101T000000Z", "one")
        self._record("repo-r2", "failed", "repo two", "2025-01-02",
                     "20250102T000000Z", "two")

        rc, out = self._status_output("project-p1")
        self.assertEqual(rc, 0)
        lines = [ln.strip() for ln in out.splitlines()]
        self.assertIn("build: succeeded (repo one) 2025-01-01", lines)
        self.assertNotIn("build: failed (repo two) 2025-01-02", lines)


if __name__ == "__main__":
    unittest.main()
