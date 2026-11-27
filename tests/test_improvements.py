"""Improvements: the model proposes a change; a person accepts, rejects, edits."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ctx import db, frontmatter, writeback


class ImprovementsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "context").mkdir(parents=True)
        db.init_db(self.root)

    def _propose(self, itype="eval-case", title="Add an eval", change="pass criteria",
                 rationale="why", source="", factory="feature-builder"):
        return writeback.propose_improvement(
            self.root, itype, title, rationale, change, source=source, factory=factory)

    def test_propose_and_list(self) -> None:
        self._propose(title="Flag fabricated tables", change="a plan naming a table not in schema must be flagged")
        rows = writeback.list_improvements(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["improvement_type"], "eval-case")
        self.assertEqual(rows[0]["title"], "Flag fabricated tables")
        self.assertIn("must be flagged", rows[0]["change"])

    def test_accept_eval_case_writes_json(self) -> None:
        self._propose(title="Flag fabricated tables", rationale="scenario", change="pass criteria")
        name = writeback.list_improvements(self.root)[0]["name"]
        result = writeback.accept_improvement(self.root, name)
        self.assertEqual(result["improvement_type"], "eval-case")
        path = self.root / result["path"]
        self.assertTrue(path.is_file())
        case = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(case["factory"], "feature-builder")
        self.assertEqual(case["pass_criteria"], "pass criteria")
        # the proposal note is removed
        self.assertEqual(writeback.list_improvements(self.root), [])

    def test_accept_prompt_writes_new_version(self) -> None:
        pdir = self.root / "factories" / "feature-builder" / "prompts"
        pdir.mkdir(parents=True)
        (pdir / "v1.md").write_text("old prompt", encoding="utf-8")
        self._propose(itype="prompt", title="Sharper prompt", change="the new prompt text")
        name = writeback.list_improvements(self.root)[0]["name"]
        result = writeback.accept_improvement(self.root, name)
        self.assertEqual((self.root / result["path"]).name, "v2.md")
        self.assertIn("the new prompt text",
                      (self.root / result["path"]).read_text(encoding="utf-8"))

    def test_accept_code_files_a_task(self) -> None:
        # project -> repo -> build-record (source) chain
        (self.root / "context/projects").mkdir(parents=True)
        (self.root / "context/repos").mkdir(parents=True)
        (self.root / "context/documents").mkdir(parents=True)
        project = {"id": "project-x", "type": "project", "title": "X",
                   "created": "2026-11-26", "updated": "2026-11-26"}
        (self.root / "context/projects/x.md").write_text(
            frontmatter.dumps(project, "# X\n"), encoding="utf-8")
        repo = {"id": "repo-x", "type": "repo", "title": "X", "project": "project-x",
                "created": "2026-11-26", "updated": "2026-11-26", "status": "active"}
        (self.root / "context/repos/x.md").write_text(
            frontmatter.dumps(repo, "# X\n"), encoding="utf-8")
        record = {"id": "document-build-x", "type": "document", "title": "build",
                  "created": "2026-11-26", "updated": "2026-11-26",
                  "tags": ["build-record", "repo:repo-x"]}
        (self.root / "context/documents/build-x.md").write_text(
            frontmatter.dumps(record, "# build\n"), encoding="utf-8")

        self._propose(itype="code", title="Fix the gate", rationale="why",
                      change="the code fix", source="document-build-x")
        name = writeback.list_improvements(self.root)[0]["name"]
        result = writeback.accept_improvement(self.root, name)
        self.assertTrue(result["path"].startswith("context/tasks/"))
        task_path = self.root / result["path"]
        meta, body = frontmatter.parse(task_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["project"], "project-x")
        self.assertIn("the code fix", body)

    def test_reject_and_edit(self) -> None:
        self._propose(title="Tweak", change="original change")
        name = writeback.list_improvements(self.root)[0]["name"]
        writeback.edit_improvement(self.root, name, "edited change")
        rows = writeback.list_improvements(self.root)
        self.assertIn("edited change", rows[0]["change"])
        writeback.reject_improvement(self.root, name, reason="not now")
        self.assertEqual(writeback.list_improvements(self.root), [])

    def test_bad_improvement_type_is_refused(self) -> None:
        with self.assertRaises(writeback.WritebackError):
            self._propose(itype="nonsense")

    def test_traversal_in_name_is_refused(self) -> None:
        self._propose(title="X", change="y")
        for bad in ("../context/projects/evil", "..\\evil", "sub/dir"):
            with self.assertRaises(writeback.WritebackError):
                writeback.accept_improvement(self.root, bad)

    def test_traversal_in_factory_is_refused(self) -> None:
        # A proposal whose factory tries to escape the store must be refused.
        (self.root / "inbox").mkdir(parents=True)
        note = (self.root / "inbox" / "propose-improvement-bad-1.md")
        note.write_text(
            "---\nkind: improvement\nimprovement_type: eval-case\n"
            "factory: ../../evil\ntitle: Bad\n---\n\n"
            "# Bad\n\n## Rationale\n\nwhy\n\n## Change\n\nwhat\n", encoding="utf-8")
        with self.assertRaises(writeback.WritebackError):
            writeback.accept_improvement(self.root, note.name)



if __name__ == "__main__":
    unittest.main()
