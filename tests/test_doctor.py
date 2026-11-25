"""`stead doctor` makes a hand edit fail loudly, before a later command does."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import doctor, frontmatter


class DoctorTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("projects", "tasks", "documents"):
            (self.root / "context" / folder).mkdir(parents=True)

    def _write(self, folder: str, name: str, meta: dict, body: str = "# X\n") -> Path:
        path = self.root / "context" / folder / name
        path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        return path

    def _project(self) -> dict:
        return {"id": "project-demo", "type": "project", "title": "Demo",
                "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}

    def test_a_clean_store_has_no_problems(self) -> None:
        self._write("projects", "demo.md", self._project())
        self._write("tasks", "one.md", {
            "id": "task-one", "type": "task", "title": "One",
            "created": "2026-11-21", "updated": "2026-11-21",
            "status": "to-do", "project": "project-demo"})
        report = doctor.run(self.root)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["checked"], 2)
        self.assertIn("no problems", doctor.render(report))

    def test_a_malformed_block_is_an_error(self) -> None:
        path = self.root / "context/projects/broken.md"
        path.write_text("---\nid: project-broken\ntitle: Broken\n", encoding="utf-8")
        report = doctor.run(self.root)
        self.assertTrue(report["errors"])
        self.assertIn("never closed", report["errors"][0]["message"])

    def test_missing_fields_and_ids_are_errors(self) -> None:
        self._write("projects", "demo.md", self._project())
        self._write("tasks", "bad.md", {
            "id": "", "type": "task", "title": "",
            "created": "not-a-date", "updated": "2026-11-21"})
        messages = " ".join(item["message"] for item in doctor.run(self.root)["errors"])
        self.assertIn("missing id", messages)
        self.assertIn("missing title", messages)
        self.assertIn("created is not an ISO date", messages)

    def test_duplicate_ids_and_broken_relations_are_errors(self) -> None:
        self._write("projects", "demo.md", self._project())
        self._write("projects", "copy.md", self._project())
        self._write("tasks", "one.md", {
            "id": "task-one", "type": "task", "title": "One",
            "created": "2026-11-21", "updated": "2026-11-21",
            "status": "to-do", "project": "project-missing"})
        messages = " ".join(item["message"] for item in doctor.run(self.root)["errors"])
        self.assertIn("duplicate id", messages)
        self.assertIn("missing object", messages)

    def test_a_synced_issue_changed_upstream_is_a_warning(self) -> None:
        (self.root / "context/contributions").mkdir(parents=True, exist_ok=True)
        self._write("contributions", "issue-1.md", {
            "id": "contribution-x-issue-1", "type": "contribution",
            "title": "X", "created": "2026-11-21", "updated": "2026-11-21",
            "repo": "repo-x", "kind": "issue", "number": 1, "role": "author",
            "state": "open", "visibility": "public",
            "body_sha": "aaa", "upstream_body_sha": "bbb"})
        report = doctor.run(self.root)
        self.assertTrue(any("changed after" in w["message"]
                           for w in report["warnings"]))

    def _stead_build(self, name: str, spec_sha: str | None) -> Path:
        meta = {"id": f"contribution-x-issue-{name}", "type": "contribution",
                "title": "X", "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-x", "kind": "issue", "number": int(name),
                "role": "author", "state": "open", "visibility": "public",
                "tags": ["stead-build"]}
        if spec_sha is not None:
            meta["spec_sha"] = spec_sha
        return self._write("contributions", f"issue-{name}.md", meta, body="approved body\n")

    def test_stead_build_missing_spec_sha_warns(self) -> None:
        (self.root / "context/contributions").mkdir(parents=True, exist_ok=True)
        self._stead_build("1", None)
        report = doctor.run(self.root)
        self.assertTrue(any("no spec_sha" in w["message"] for w in report["warnings"]))

    def test_stead_build_changed_body_warns(self) -> None:
        (self.root / "context/contributions").mkdir(parents=True, exist_ok=True)
        from ctx import spec as spec_mod
        wrong = spec_mod.body_hash("different body\n")
        self._stead_build("2", wrong)
        report = doctor.run(self.root)
        self.assertTrue(any("spec_sha mismatch" in w["message"]
                           for w in report["warnings"]))

    def test_stead_build_approved_is_silent(self) -> None:
        (self.root / "context/contributions").mkdir(parents=True, exist_ok=True)
        from ctx import spec as spec_mod
        good = spec_mod.body_hash("approved body\n")
        self._stead_build("3", good)
        report = doctor.run(self.root)
        self.assertFalse(any("spec_sha" in w["message"] for w in report["warnings"]))
