import tempfile
import unittest
from pathlib import Path

from ctx import spec


class DraftReadRangeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.code = self.root / "code"
        self.code.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _write_big(self, name="big.py", lines=300, width=100):
        text = "\n".join(f"line {i}: " + ("x" * width) for i in range(1, lines + 1))
        (self.code / name).write_text(text, encoding="utf-8")
        return text

    def test_in_cap_range_of_large_file_returns_range(self):
        text = self._write_big()
        self.assertGreater(len(text), spec._DRAFT_MAX_READ_CHARS)
        result = spec._draft_read(self.code, "big.py", start=1, end=5)
        self.assertIn("lines 1-5", result)
        self.assertIn("line 1:", result)
        self.assertIn("line 5:", result)
        self.assertNotIn("truncated", result)
        self.assertNotIn("refused", result)

    def test_oversized_range_returns_bounded_excerpt(self):
        text = self._write_big(lines=300, width=100)
        self.assertGreater(len(text), spec._DRAFT_MAX_READ_CHARS)
        result = spec._draft_read(self.code, "big.py", start=1, end=300)
        self.assertIn("truncated", result)
        self.assertIn("line 1:", result)
        self.assertNotIn("refused", result)
        # The excerpt is bounded by the cap, so it should stop well before
        # the end of the requested 300-line range.
        self.assertNotIn("line 250:", result)

    def test_no_range_large_file_returns_excerpt_and_outline(self):
        body = [
            "def alpha():",
            "    return 1",
            "",
            "class Beta:",
            "    pass",
        ]
        for i in range(1, 250):
            body.append(f"line {i}: " + ("x" * 100))
        text = "\n".join(body)
        (self.code / "outline.py").write_text(text, encoding="utf-8")
        self.assertGreater(len(text), spec._DRAFT_MAX_READ_CHARS)
        result = spec._draft_read(self.code, "outline.py")
        self.assertNotIn("refused", result)
        self.assertIn("Outline", result)
        self.assertIn("1: def alpha", result)
        self.assertIn("4: class Beta", result)
        self.assertIn("line 1:", result)

    def test_small_file_read_unchanged(self):
        (self.code / "small.py").write_text("def tiny():\n    return 0\n", encoding="utf-8")
        result = spec._draft_read(self.code, "small.py")
        self.assertTrue(result.startswith("read small.py:"))
        self.assertIn("def tiny():", result)

    def test_range_semantics_clamped_and_one_sided(self):
        (self.code / "mid.py").write_text(
            "\n".join(f"line {i}" for i in range(1, 11)), encoding="utf-8"
        )
        r = spec._draft_read(self.code, "mid.py", start=8)
        self.assertIn("lines 8-10", r)
        self.assertIn("line 10", r)
        r = spec._draft_read(self.code, "mid.py", end=3)
        self.assertIn("lines 1-3", r)
        r = spec._draft_read(self.code, "mid.py", start=50, end=60)
        self.assertIn("lines 50-10", r)


if __name__ == "__main__":
    unittest.main()
