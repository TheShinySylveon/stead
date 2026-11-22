"""Repo wiki: a home page and drill-down pages over existing objects."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import db, frontmatter, wiki


class WikiTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("context/projects", "context/repos", "context/documents",
                       "context/contributions", "context/tasks"):
            (self.root / folder).mkdir(parents=True)
        project = {"id": "project-app", "type": "project", "title": "App",
                   "created": "2026-11-21", "updated": "2026-11-21",
                   "status": "active"}
        (self.root / "context/projects/app.md").write_text(
            frontmatter.dumps(project, "# App\n\nA small service. It does one thing well.\n"),
            encoding="utf-8")
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "project": "project-app",
                "url": "https://github.com/me/app", "default_branch": "main",
                "trigger": "watch", "reach": "draft-pr"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        decision = {"id": "document-adr-one", "type": "document", "title": "ADR: one cache",
                    "created": "2026-11-21", "updated": "2026-11-21",
                    "status": "active", "project": "project-app", "tags": ["adr"]}
        (self.root / "context/documents/adr-one.md").write_text(
            frontmatter.dumps(decision, "# ADR: one cache\n\nWe keep one cache, not three.\n"),
            encoding="utf-8")
        glossary = {"id": "document-glossary", "type": "document", "title": "Glossary",
                    "created": "2026-11-21", "updated": "2026-11-21",
                    "status": "active", "project": "project-app", "tags": ["glossary"]}
        (self.root / "context/documents/glossary.md").write_text(
            frontmatter.dumps(glossary, "# Glossary\n\n- cache: the one cache.\n"),
            encoding="utf-8")
        issue = {"id": "contribution-me-app-issue-3", "type": "contribution",
                 "title": "Add a flag", "created": "2026-11-21",
                 "updated": "2026-11-21", "repo": "repo-me-app", "kind": "issue",
                 "number": 3, "role": "author", "state": "open", "ci": "none",
                 "review": "none", "method": "builtin", "visibility": "public",
                 "tags": ["feature-spec"]}
        (self.root / "context/contributions/issue-3.md").write_text(
            frontmatter.dumps(issue, "# Add a flag\n\nNeeds a flag.\n"), encoding="utf-8")
        merged = dict(issue, id="contribution-me-app-pr-9", kind="pr", number=9,
                      state="merged", title="Fix the parser",
                      tags=[])
        (self.root / "context/contributions/pr-9.md").write_text(
            frontmatter.dumps(merged, "# Fix the parser\n\nDone.\n"), encoding="utf-8")
        task = {"id": "task-write-it", "type": "task", "title": "Write it",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "doing", "project": "project-app"}
        (self.root / "context/tasks/write-it.md").write_text(
            frontmatter.dumps(task, "# Write it\n"), encoding="utf-8")
        db.init_db(self.root)

    def test_home_has_essentials_and_tree(self) -> None:
        home = wiki.index(self.root, "repo-me-app")
        self.assertEqual(home["repo"]["title"], "App")
        self.assertIn("small service", home["summary"])
        slugs = {node["slug"]: node for node in home["tree"]}
        for slug in ("overview", "specs", "decisions", "glossary", "tasks", "history"):
            self.assertIn(slug, slugs)
        spec_children = [child["slug"] for child in slugs["specs"]["children"]]
        self.assertIn("specs/contribution-me-app-issue-3", spec_children)
        decision_children = [child["slug"] for child in slugs["decisions"]["children"]]
        self.assertIn("decisions/document-adr-one", decision_children)
        self.assertEqual(home["counts"]["specs_open"], 1)
        self.assertEqual(home["counts"]["decisions"], 1)
        self.assertEqual(home["counts"]["tasks_open"], 1)
        self.assertEqual(home["counts"]["merged"], 1)
        self.assertTrue(any(item.get("slug") for item in home["start"]))

    def test_pages_drill_down_to_children(self) -> None:
        specs = wiki.page(self.root, "repo-me-app", "specs")
        self.assertEqual(specs["page"]["children"][0]["title"], "Add a flag")
        spec = wiki.page(self.root, "repo-me-app", "specs/contribution-me-app-issue-3")
        self.assertEqual(spec["page"]["title"], "Add a flag")
        self.assertIn("Needs a flag", spec["page"]["markdown"])
        decision = wiki.page(self.root, "repo-me-app", "decisions/document-adr-one")
        self.assertIn("one cache", decision["page"]["markdown"])
        self.assertIn("adr", decision["page"]["labels"])
        history = wiki.page(self.root, "repo-me-app", "history")
        self.assertIn("Fix the parser", history["page"]["markdown"])
        overview = wiki.page(self.root, "repo-me-app", "overview")
        self.assertIn("Autonomy ceiling", overview["page"]["markdown"])

    def test_unknown_page_and_repo(self) -> None:
        with self.assertRaises(wiki.WikiError):
            wiki.page(self.root, "repo-me-app", "nope")
        with self.assertRaises(wiki.WikiError):
            wiki.page(self.root, "repo-me-app", "specs/contribution-missing")
        with self.assertRaises(wiki.WikiError):
            wiki.index(self.root, "repo-missing")
