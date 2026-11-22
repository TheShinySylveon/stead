"""`stead metrics --since` windows the dogfood numbers to records created
on or after a date. Invalid dates are a clear error, not a crash."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import frontmatter, metrics


class MetricsSinceTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("repos", "documents"):
            (self.root / "context" / folder).mkdir(parents=True)

    def _record(self, number: int, created: str, outcome: str = "committed") -> None:
        meta = {
            "id": f"document-build-{number}",
            "type": "document",
            "title": f"Build {number}",
            "created": created,
            "updated": created,
            "status": "active",
            "tags": ["build-record", "repo:repo-me-app"],
            "outcome": outcome,
        }
        (self.root / "context/documents" / f"build-{number}.md").write_text(
            frontmatter.dumps(meta, f"# Build {number}\n"), encoding="utf-8")

    def test_since_counts_only_records_on_or_after(self) -> None:
        self._record(1, "2026-11-01")
        self._record(2, "2026-11-15")
        self._record(3, "2026-11-20")
        # No window: all three records count.
        self.assertEqual(metrics.collect(self.root)["builds"], 3)
        # Window from 2026-11-15 keeps the 15th and 20th, drops the 1st.
        report = metrics.collect(self.root, since="2026-11-15")
        self.assertEqual(report["builds"], 2)
        # Window from 2026-11-20 keeps only the 20th.
        self.assertEqual(metrics.collect(self.root, since="2026-11-20")["builds"], 1)
        # The boundary is inclusive: a record created exactly on the date counts.
        self.assertEqual(metrics.collect(self.root, since="2026-11-01")["builds"], 3)

    def test_empty_window_reports_no_records(self) -> None:
        self._record(1, "2026-11-01")
        self._record(2, "2026-11-15")
        # A since date after every record yields an empty report.
        report = metrics.collect(self.root, since="2026-12-01")
        self.assertEqual(report["builds"], 0)
        self.assertIn("No build records", metrics.render(report))

    def test_invalid_date_is_a_clear_error_not_a_crash(self) -> None:
        self._record(1, "2026-11-01")
        with self.assertRaises(ValueError) as ctx:
            metrics.collect(self.root, since="not-a-date")
        self.assertIn("invalid date", str(ctx.exception))
        with self.assertRaises(ValueError):
            metrics.collect(self.root, since="2026-13-45")
