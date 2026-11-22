"""Tests for `stead inbox list` (read-only inbox listing)."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from ctx import cli


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


DECISION_NOTE = """# Decide on the cache layer

We should use SQLite for the local cache.
"""

GLOSSARY_NOTE = """# Glossary: Reach

Reach is the autonomy ceiling for a repo.
"""

NOTE_WITH_HEADING = """# Meeting capture

Notes from the standup.
"""

NOTE_NO_HEADING = """Just some raw text with no heading.
"""


class InboxListTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _populate(self):
        _write(self.root, "inbox/propose-decision-cache.md", DECISION_NOTE)
        _write(self.root, "inbox/propose-glossary-reach.md", GLOSSARY_NOTE)
        _write(self.root, "inbox/note-standup.md", NOTE_WITH_HEADING)
        _write(self.root, "inbox/raw-capture.md", NOTE_NO_HEADING)

    def test_populated_listing(self):
        self._populate()
        rc, out = _run(self.root, "inbox", "list")
        self.assertEqual(rc, 0)
        self.assertIn("propose-decision-cache.md  decision  Decide on the cache layer", out)
        self.assertIn("propose-glossary-reach.md  glossary  Glossary: Reach", out)
        self.assertIn("note-standup.md  note  Meeting capture", out)
        self.assertIn("raw-capture.md  note  raw-capture", out)

    def test_kind_filter_decision(self):
        self._populate()
        rc, out = _run(self.root, "inbox", "list", "--kind", "decision")
        self.assertEqual(rc, 0)
        self.assertIn("propose-decision-cache.md", out)
        self.assertNotIn("propose-glossary-reach.md", out)
        self.assertNotIn("note-standup.md", out)
        self.assertNotIn("raw-capture.md", out)

    def test_kind_filter_glossary(self):
        self._populate()
        rc, out = _run(self.root, "inbox", "list", "--kind", "glossary")
        self.assertEqual(rc, 0)
        self.assertIn("propose-glossary-reach.md", out)
        self.assertNotIn("propose-decision-cache.md", out)
        self.assertNotIn("note-standup.md", out)
        self.assertNotIn("raw-capture.md", out)

    def test_kind_filter_note(self):
        self._populate()
        rc, out = _run(self.root, "inbox", "list", "--kind", "note")
        self.assertEqual(rc, 0)
        self.assertIn("note-standup.md", out)
        self.assertIn("raw-capture.md", out)
        self.assertNotIn("propose-decision-cache.md", out)
        self.assertNotIn("propose-glossary-reach.md", out)

    def test_title_fallback_to_stem(self):
        self._populate()
        rc, out = _run(self.root, "inbox", "list", "--kind", "note")
        self.assertEqual(rc, 0)
        self.assertIn("raw-capture.md  note  raw-capture", out)

    def test_empty_inbox(self):
        (self.root / "inbox").mkdir()
        rc, out = _run(self.root, "inbox", "list")
        self.assertEqual(rc, 0)
        self.assertIn("inbox is empty", out)

    def test_missing_inbox(self):
        rc, out = _run(self.root, "inbox", "list")
        self.assertEqual(rc, 0)
        self.assertIn("inbox not found", out)

    def test_read_only(self):
        self._populate()
        before = _snapshot(self.root)
        rc, _out = _run(self.root, "inbox", "list", "--kind", "decision")
        self.assertEqual(rc, 0)
        after = _snapshot(self.root)
        self.assertEqual(before, after)
        self.assertFalse((self.root / "state.db").exists())

    def test_non_utf8_note_does_not_crash(self):
        (self.root / "inbox").mkdir()
        (self.root / "inbox" / "bad-note.md").write_bytes(b"# Bad note\n\xff\xfe\x00\n")
        rc, out = _run(self.root, "inbox", "list")
        self.assertEqual(rc, 0)
        self.assertIn("bad-note.md", out)


if __name__ == "__main__":
    unittest.main()
