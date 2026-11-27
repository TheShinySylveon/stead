"""`stead doctor` checks contribution `repo:` relations: missing, valid, dangling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import doctor, frontmatter


class DoctorRepoRelationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("contributions", "repos"):
            (self.root / "context" / folder).mkdir(parents=True)

    def _write(self, folder: str, name: str, meta: dict, body: str = "# X\n") -> Path:
        path = self.root / "context" / folder / name
        path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        return path

    def _contribution(self, name: str, repo: str | None) -> dict:
        meta = {"id": f"contribution-{name}", "type": "contribution", "title": "X",
                "created": "2026-11-21", "updated": "2026-11-21"}
        if repo is not None:
            meta["repo"] = repo
        return meta

    def test_contribution_repo_relation_missing_valid_and_dangling(self) -> None:
        self._write("repos", "real.md", {
            "id": "repo-real", "type": "repo", "title": "Real",
            "created": "2026-11-21", "updated": "2026-11-21", "status": "active"})
        self._write("contributions", "missing.md", self._contribution("missing", None))
        self._write("contributions", "valid.md", self._contribution("valid", "repo-real"))
        self._write("contributions", "dangling.md",
                    self._contribution("dangling", "repo-missing"))
        errors = doctor.run(self.root)["errors"]
        messages = " ".join(item["message"] for item in errors)
        self.assertIn("missing repo relation", messages)
        self.assertTrue(any(
            item["path"] == "context/contributions/missing.md"
            and "missing repo relation" in item["message"]
            for item in errors))
        self.assertFalse(any(
            item["path"] == "context/contributions/valid.md"
            and "repo" in item["message"]
            for item in errors))
        self.assertTrue(any(
            item["path"] == "context/contributions/dangling.md"
            and "repo points at missing object" in item["message"]
            for item in errors))
