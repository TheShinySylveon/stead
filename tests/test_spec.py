"""Spec approval is bound to the body hash, not to a tag."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import agent, db, frontmatter, spec


class SpecApprovalTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "context/contributions").mkdir(parents=True)
        self.body = ("The greeting script should accept a name option so callers can "
                     "address a person without editing the source. Keep the default "
                     "output stable and cover the new path with a small test.\n\n"
                     "## Acceptance criteria\n\n- [ ] flag works\n")
        self.meta = {"id": "contribution-me-app-issue-1", "type": "contribution",
                     "title": "Flag", "created": "2026-11-21", "updated": "2026-11-21",
                     "repo": "repo-me-app", "kind": "issue", "number": 1,
                     "role": "author", "state": "open", "visibility": "public",
                     "tags": ["feature-spec"]}
        self.path = self.root / "context/contributions/issue-1.md"
        self.path.write_text(frontmatter.dumps(self.meta, self.body), encoding="utf-8")
        db.init_db(self.root)

    def test_approve_stores_a_hash_and_build_accepts_it(self) -> None:
        result = spec.approve(self.root, "contribution-me-app-issue-1")
        self.assertEqual(result["sha"], spec.body_hash(self.body))
        meta, body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.assertTrue(spec.is_approved(meta, body))
        spec.require_approval(meta, body)

    def test_a_changed_body_needs_reapproval(self) -> None:
        spec.approve(self.root, "contribution-me-app-issue-1")
        meta, _body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.path.write_text(frontmatter.dumps(meta, self.body + "\nExtra text.\n"),
                             encoding="utf-8")
        meta, body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        self.assertFalse(spec.is_approved(meta, body))
        with self.assertRaises(spec.SpecError) as caught:
            spec.require_approval(meta, body)
        self.assertIn("changed", str(caught.exception))

    def test_an_unapproved_spec_cannot_build(self) -> None:
        code = self.root / "code"
        code.mkdir()
        (self.root / "context/repos").mkdir(parents=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "default_branch": "main",
                "code_path": str(code), "reach": "draft-pr"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        with self.assertRaises(agent.BuildError) as caught:
            agent.build(self.root, "contribution-me-app-issue-1",
                        responder=lambda _p: "{}")
        self.assertIn("not approved", str(caught.exception))

    def test_only_issues_can_be_approved(self) -> None:
        meta, body = frontmatter.parse(self.path.read_text(encoding="utf-8"))
        meta["kind"] = "pr"
        self.path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        with self.assertRaises(spec.SpecError):
            spec.approve(self.root, "contribution-me-app-issue-1")
