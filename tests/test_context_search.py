"""Tests for `stead context search` (read-only markdown search)."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ctx import cli

REPO_ALPHA = """---
id: repo-alpha
type: repo
title: Alpha Repo
---
# Alpha Repo

Alpha needle body.
"""

REPO_BETA = """---
id: repo-beta
type: repo
title: Beta Repo
---
# Beta Repo

Beta quiet body.
"""

DOC_ALPHA = """---
id: document-alpha
type: document
title: Alpha Doc
repo: repo-alpha
---
Alpha needle doc.
"""

DOC_BETA = """---
id: document-beta
type: document
title: Beta Doc
repo: repo-beta
---
Beta needle doc.
"""

TASK_ALPHA = """---
id: task-alpha
type: task
title: Alpha Task
repo: repo-alpha
---
Alpha needle task.
"""

DOC_NONE = """---
id: document-none
type: document
title: None Doc
---
None needle doc.
"""


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_store(root: Path) -> None:
    _write(root, "context/repos/repo-alpha.md", REPO_ALPHA)
    _write(root, "context/repos/repo-beta.md", REPO_BETA)
    _write(root, "context/documents/doc-alpha.md", DOC_ALPHA)
    _write(root, "context/documents/doc-beta.md", DOC_BETA)
    _write(root, "context/tasks/task-alpha.md", TASK_ALPHA)
    _write(root, "context/documents/doc-none.md", DOC_NONE)


def _snapshot(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8")
        for p in root.rglob("*") if p.is_file()
    }


def _run(root: Path, *args: str) -> tuple[int, str]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = cli.main(["--root", str(root), *args])
    return rc, buf.getvalue()


class ContextSearchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        _make_store(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_matching_query_text(self):
        rc, out = _run(self.root, "context", "search", "needle")
        self.assertEqual(rc, 0)
        self.assertIn("context/repos/repo-alpha.md", out)
        self.assertIn("context/documents/doc-alpha.md", out)
        self.assertIn("context/documents/doc-beta.md", out)
        self.assertIn("context/tasks/task-alpha.md", out)
        self.assertIn("context/documents/doc-none.md", out)
        self.assertIn("Alpha needle body.", out)
        self.assertIn("(5 objects)", out)

    def test_case_insensitive(self):
        rc, out = _run(self.root, "context", "search", "NEEDLE")
        self.assertEqual(rc, 0)
        self.assertIn("context/documents/doc-alpha.md", out)
        self.assertIn("(5 objects)", out)

    def test_non_matching_query(self):
        rc, out = _run(self.root, "context", "search", "zzz-not-present")
        self.assertEqual(rc, 0)
        self.assertIn("no matches for zzz-not-present", out)

    def test_repo_filter(self):
        rc, out = _run(self.root, "context", "search", "needle", "--repo", "repo-alpha")
        self.assertEqual(rc, 0)
        self.assertIn("context/repos/repo-alpha.md", out)
        self.assertIn("context/documents/doc-alpha.md", out)
        self.assertIn("context/tasks/task-alpha.md", out)
        self.assertNotIn("context/documents/doc-beta.md", out)
        self.assertNotIn("context/documents/doc-none.md", out)
        self.assertIn("(3 objects)", out)

    def test_json_output(self):
        rc, out = _run(self.root, "context", "search", "needle", "--json")
        self.assertEqual(rc, 0)
        data = json.loads(out)
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 5)
        for item in data:
            self.assertEqual(set(item), {"id", "type", "path", "snippet"})
        by_path = {item["path"]: item for item in data}
        self.assertEqual(by_path["context/documents/doc-alpha.md"]["id"], "document-alpha")
        self.assertEqual(by_path["context/documents/doc-alpha.md"]["type"], "document")
        self.assertEqual(by_path["context/documents/doc-alpha.md"]["snippet"], "Alpha needle doc.")
        self.assertEqual(by_path["context/repos/repo-alpha.md"]["type"], "repo")

    def test_read_only(self):
        before = _snapshot(self.root)
        rc, _out = _run(self.root, "context", "search", "needle", "--repo", "repo-alpha", "--json")
        self.assertEqual(rc, 0)
        after = _snapshot(self.root)
        self.assertEqual(before, after)
        self.assertFalse((self.root / "state.db").exists())


if __name__ == "__main__":
    unittest.main()
