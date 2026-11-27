"""Unit tests: `contribution list --count` prints only the matching row count.

The `--repo`, `--kind`, `--role`, and `--state` filters still apply to the count;
the default table and JSON array outputs remain unchanged. All tests run against
a temporary root — never the real repo state.
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ctx import cli, db
from tests.test_ctx import make_root


class TestContributionListCount(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_root(Path(self._tmp.name))
        db.init_db(self.root)
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app")
        cli.cmd_repo_add(self.root, "Cool Lib", url="https://github.com/oss-org/cool-lib")
        cli.cmd_contribution_add(self.root, "Add feature", "repo-testuser-my-app",
                                 "pr", 7, role="author", state="merged", ci="pass")
        cli.cmd_contribution_add(self.root, "Fix bug", "repo-testuser-my-app",
                                 "issue", 9, role="reviewer", state="open", ci="pending")
        cli.cmd_contribution_add(self.root, "Docs", "repo-oss-org-cool-lib",
                                 "issue", 10, role="assignee", state="merged", ci="none")

    def _list(self, **kwargs) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = cli.cmd_contribution_list(self.root, **kwargs)
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_count_prints_only_number(self) -> None:
        text = self._list(count=True)
        self.assertEqual(text.strip(), "3")
        self.assertNotIn("id", text)
        self.assertNotIn("Add feature", text)
        self.assertNotIn("Fix bug", text)
        self.assertNotIn("Docs", text)
        self.assertNotIn("contribution", text)  # no trailing table count line

    def test_count_applies_filters(self) -> None:
        # repo filter
        self.assertEqual(self._list(count=True, repo="repo-testuser-my-app").strip(), "2")
        self.assertEqual(self._list(count=True, repo="repo-oss-org-cool-lib").strip(), "1")
        # kind filter
        self.assertEqual(self._list(count=True, kind="pr").strip(), "1")
        self.assertEqual(self._list(count=True, kind="issue").strip(), "2")
        # role filter
        self.assertEqual(self._list(count=True, role="author").strip(), "1")
        self.assertEqual(self._list(count=True, role="reviewer").strip(), "1")
        self.assertEqual(self._list(count=True, role="assignee").strip(), "1")
        # state filter
        self.assertEqual(self._list(count=True, state="merged").strip(), "2")
        self.assertEqual(self._list(count=True, state="open").strip(), "1")
        # combined filters
        self.assertEqual(self._list(count=True, repo="repo-testuser-my-app", kind="pr",
                                    state="merged").strip(), "1")
        self.assertEqual(self._list(count=True, repo="repo-testuser-my-app", kind="pr",
                                    state="open").strip(), "0")

    def test_count_json_emits_bare_number(self) -> None:
        text = self._list(count=True, json=True)
        self.assertEqual(text.strip(), "3")
        self.assertEqual(json.loads(text), 3)
        # filtered JSON count remains a bare number, not an array
        text = self._list(count=True, json=True, kind="issue")
        self.assertEqual(json.loads(text), 2)

    def test_default_table_output_unchanged(self) -> None:
        text = self._list()
        self.assertNotIn('"id"', text)  # not JSON
        self.assertIn("Add feature", text)
        self.assertIn("Fix bug", text)
        self.assertIn("Docs", text)
        self.assertIn("(3 contributions)", text)

    def test_default_json_array_unchanged(self) -> None:
        data = json.loads(self._list(json=True))
        self.assertEqual(len(data), 3)
        for obj in data:
            self.assertEqual(set(obj), {"id", "repo", "kind", "number",
                                        "role", "state", "ci", "title"})


if __name__ == "__main__":
    unittest.main()
