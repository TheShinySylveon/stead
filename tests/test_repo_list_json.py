"""Unit tests: `repo list --json` emits the field contract.

The `--json` flag emits one object per repo with exactly the fields
id, kind, status, title; the default table output is unchanged. All tests
run against a temporary root — never the real repo state.
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


class TestRepoListJson(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_root(Path(self._tmp.name))
        db.init_db(self.root)

    def _list(self, **kwargs) -> str:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.cmd_repo_list(self.root, **kwargs)
        return buf.getvalue()

    def test_json_empty_is_empty_array(self) -> None:
        text = self._list(json=True)
        data = json.loads(text)
        self.assertEqual(data, [])

    def test_json_emits_one_object_per_repo_with_exact_fields(self) -> None:
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app",
                         kind="oss")
        cli.cmd_repo_add(self.root, "Core Lib", url="https://github.com/testuser/core",
                         kind="own")
        text = self._list(json=True)
        data = json.loads(text)
        self.assertEqual(len(data), 2)
        for obj in data:
            self.assertEqual(set(obj), {"id", "kind", "status", "title"})
        titles = {obj["title"] for obj in data}
        self.assertEqual(titles, {"My App", "Core Lib"})

    def test_json_kind_filter_applies(self) -> None:
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app",
                         kind="oss")
        cli.cmd_repo_add(self.root, "Core Lib", url="https://github.com/testuser/core",
                         kind="own")
        text = self._list(json=True, kind="oss")
        data = json.loads(text)
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["kind"], "oss")
        self.assertEqual(data[0]["title"], "My App")

    def test_default_table_output_is_unchanged(self) -> None:
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app",
                         kind="oss")
        text = self._list()
        self.assertNotIn('"id"', text)  # not JSON
        self.assertIn("My App", text)
        self.assertIn("repo", text)  # the trailing count line

    def test_json_matches_the_same_rows_as_the_table(self) -> None:
        cli.cmd_repo_add(self.root, "My App", url="https://github.com/testuser/my-app",
                         kind="oss")
        table = self._list()
        data = json.loads(self._list(json=True))
        for obj in data:
            self.assertIn(obj["title"], table)
            self.assertIn(obj["id"], table)


if __name__ == "__main__":
    unittest.main()
