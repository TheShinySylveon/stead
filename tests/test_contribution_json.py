"""Unit tests: `contribution list --json` emits the field contract.

The `--json` flag emits one object per contribution with exactly the fields
id, repo, kind, number, role, state, ci, title; the default table output is
unchanged. All tests run against a temporary root — never the real repo state.
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


class TestContributionListJson(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_root(Path(self._tmp.name))
        db.init_db(self.root)
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app")
        cli.cmd_contribution_add(self.root, "Add feature", "repo-testuser-my-app",
                                 "pr", 7, ci="pass", review="requested")
        cli.cmd_contribution_add(self.root, "Fix bug", "repo-testuser-my-app",
                                 "issue", 9, ci="pending")

    def _list(self, **kwargs) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.cmd_contribution_list(self.root, **kwargs)
        return buf.getvalue()

    def test_json_emits_one_object_per_contribution_with_exact_fields(self) -> None:
        text = self._list(json=True)
        data = json.loads(text)
        self.assertEqual(len(data), 2)
        for obj in data:
            self.assertEqual(set(obj), {"id", "repo", "kind", "number",
                                        "role", "state", "ci", "title"})
        titles = {obj["title"] for obj in data}
        self.assertEqual(titles, {"Add feature", "Fix bug"})
        # A JSON object maps number/kind as integers from the row, not strings.
        self.assertIsInstance(data[0]["number"], int)

    def test_default_table_output_is_unchanged(self) -> None:
        text = self._list()
        self.assertNotIn('"id"', text)  # not JSON
        self.assertIn("Add feature", text)
        self.assertIn("Fix bug", text)
        self.assertIn("contribution", text)  # the trailing count line

    def test_json_matches_the_same_rows_as_the_table(self) -> None:
        table = self._list()
        data = json.loads(self._list(json=True))
        for obj in data:
            # The table prints id, kind#number, role, state, ci, and title.
            self.assertIn(obj["title"], table)
            self.assertIn(obj["id"], table)


if __name__ == "__main__":
    unittest.main()
