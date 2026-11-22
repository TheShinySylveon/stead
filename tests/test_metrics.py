"""`stead metrics` reports what the factory actually did, from build records."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import frontmatter, metrics, writeback


class MetricsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("repos", "contributions", "documents"):
            (self.root / "context" / folder).mkdir(parents=True)
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")

    def _contrib(self, number: int) -> str:
        cid = f"contribution-me-app-issue-{number}"
        meta = {"id": cid, "type": "contribution", "title": f"Feature {number}",
                "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-me-app", "kind": "issue", "number": number,
                "role": "author", "state": "open", "visibility": "public"}
        (self.root / "context/contributions" / f"issue-{number}.md").write_text(
            frontmatter.dumps(meta, f"# Feature {number}\n"), encoding="utf-8")
        return cid

    def _result(self, **over) -> dict:
        base = {"branch": "stead/x", "commit": "abc", "files": ["app.py", "util.py"],
                "deleted": [], "checks": "make test", "checks_mode": "docker",
                "tests_touched": ["tests/test_app.py"], "tests_deleted": [],
                "elapsed_seconds": 12.0, "repair_rounds": 1,
                "summary": "done", "published": True, "merged": False}
        base.update(over)
        return base

    def test_empty_store(self) -> None:
        report = metrics.collect(self.root)
        self.assertEqual(report["builds"], 0)
        self.assertIn("No build records", metrics.render(report))

    def test_aggregates_outcomes_time_and_tests(self) -> None:
        writeback.record_delivery(self.root, self._contrib(1), self._result())
        writeback.record_delivery(
            self.root, self._contrib(2),
            self._result(merged=True, checks_mode="host", elapsed_seconds=8.0,
                         repair_rounds=0, files=["app.py"],
                         tests_touched=[], tests_deleted=["tests/test_old.py"]))
        report = metrics.collect(self.root)
        self.assertEqual(report["builds"], 2)
        self.assertEqual(report["outcomes"]["merged"], 1)
        self.assertEqual(report["outcomes"]["published"], 1)
        self.assertEqual(report["merged_share"], 0.5)
        self.assertEqual(report["checks_modes"]["docker"], 1)
        self.assertEqual(report["checks_modes"]["host"], 1)
        self.assertEqual(report["avg_elapsed_seconds"], 10.0)
        self.assertEqual(report["repair_rounds"], 1)
        self.assertEqual(report["files_touched"], 3)
        self.assertEqual(report["tests_touched"], 1)
        self.assertEqual(report["tests_deleted"], 1)
        self.assertEqual(report["by_repo"]["repo-me-app"], 2)
        text = metrics.render(report)
        self.assertIn("merged share: 50%", text)
        self.assertIn("repo-me-app=2", text)

    def test_repo_filter(self) -> None:
        writeback.record_delivery(self.root, self._contrib(1), self._result())
        self.assertEqual(metrics.collect(self.root, repo="repo-me-app")["builds"], 1)
        self.assertEqual(metrics.collect(self.root, repo="repo-other")["builds"], 0)

    def test_failure_rate_and_reconciled_merge_with_human_edits(self) -> None:
        writeback.record_failure(self.root, self._contrib(1), ValueError("boom"),
                                 branch="stead/x")
        writeback.record_delivery(
            self.root, self._contrib(2),
            self._result(pr_url="https://github.com/me/app/pull/2"))

        def view_pr(_url):
            return {"state": "MERGED", "headRefOid": "def",
                    "mergedAt": "2026-11-21T00:00:00Z"}

        result = writeback.reconcile_records(self.root, view_pr)
        self.assertEqual(result["reconciled"], 1)
        report = metrics.collect(self.root)
        self.assertEqual(report["builds"], 2)
        self.assertEqual(report["outcomes"]["failed"], 1)
        self.assertEqual(report["outcomes"]["merged"], 1)
        self.assertEqual(report["failure_rate"], 0.5)
        self.assertEqual(report["merged_share"], 0.5)
        self.assertEqual(report["human_edits"], 1)
        text = metrics.render(report)
        self.assertIn("failure rate (build-class): 50%", text)
        self.assertIn("merged after a human edit: 1", text)

    def test_reconcile_closed_and_open_prs(self) -> None:
        writeback.record_delivery(
            self.root, self._contrib(1),
            self._result(pr_url="https://github.com/me/app/pull/1"))
        writeback.record_delivery(
            self.root, self._contrib(2),
            self._result(pr_url="https://github.com/me/app/pull/2"))
        states = {"https://github.com/me/app/pull/1": "CLOSED",
                  "https://github.com/me/app/pull/2": "OPEN"}
        result = writeback.reconcile_records(
            self.root, lambda url: {"state": states[url]})
        self.assertEqual(result["reconciled"], 1)  # only the closed one
        report = metrics.collect(self.root)
        self.assertEqual(report["outcomes"]["closed"], 1)
        self.assertEqual(report["outcomes"]["published"], 1)  # open stays published

    def test_mark_merged_updates_the_existing_record_without_a_duplicate(self) -> None:
        cid = self._contrib(1)
        writeback.record_delivery(
            self.root, cid, self._result(pr_url="https://github.com/me/app/pull/1"))
        writeback.mark_merged(self.root, cid,
                              url="https://github.com/me/app/pull/1", head_sha="abc")
        report = metrics.collect(self.root)
        self.assertEqual(report["builds"], 1)
        self.assertEqual(report["outcomes"]["merged"], 1)
        self.assertEqual(report["human_edits"], 0)  # head == recorded commit
        meta, _body = frontmatter.parse(
            (self.root / "context/contributions/issue-1.md").read_text(encoding="utf-8"))
        self.assertEqual(meta["state"], "merged")

    def test_reviews_and_token_cost_are_counted(self) -> None:
        cid = self._contrib(1)
        writeback.record_delivery(
            self.root, cid,
            self._result(tokens_in=100, tokens_out=50, cost_usd=0.25))
        writeback.record_review(self.root, cid,
                                {"verdict": "approve", "reason": "criteria met"})
        report = metrics.collect(self.root)
        self.assertEqual(report["reviews"]["approve"], 1)
        self.assertEqual(report["tokens_in"], 100)
        self.assertEqual(report["tokens_out"], 50)
        self.assertEqual(report["cost_usd"], 0.25)
        text = metrics.render(report)
        self.assertIn("independent reviews: approve 1", text)
        self.assertIn("cost: $0.25", text)

    def test_build_failure_attempts_counts_only_build_class(self) -> None:
        from ctx import spec as spec_approval
        cid = self._contrib(1)
        sha = spec_approval.body_hash("# Feature 1\n")
        writeback.record_failure(self.root, cid, ValueError("checks failed"),
                                 branch="stead/x", reason="checks")
        writeback.record_failure(self.root, cid, ValueError("model down"),
                                 branch="stead/x", reason="infrastructure")
        self.assertEqual(
            writeback.build_failure_attempts(self.root, "repo-me-app", sha), 1)

    def test_record_failure_carries_spec_sha(self) -> None:
        from ctx import spec as spec_approval
        cid = self._contrib(1)
        rec = writeback.record_failure(self.root, cid, ValueError("boom"),
                                       branch="stead/x", reason="gate")
        meta, _body = frontmatter.parse(
            (self.root / rec["path"]).read_text(encoding="utf-8"))
        self.assertEqual(meta["outcome"], "failed")
        self.assertEqual(meta["spec_sha"], spec_approval.body_hash("# Feature 1\n"))

    def test_infrastructure_failures_are_reported_separately(self) -> None:
        cid = self._contrib(1)
        writeback.record_failure(self.root, cid, ValueError("model down"),
                                 branch="stead/x", reason="infrastructure")
        writeback.record_delivery(self.root, self._contrib(2), self._result())
        report = metrics.collect(self.root)
        self.assertEqual(report["infra_failures"], 1)
        self.assertEqual(report["build_failures"], 0)
        self.assertEqual(report["failure_rate"], 0.0)  # infra does not count
        self.assertIn("infrastructure 1", metrics.render(report))

    def test_committed_is_separate_from_correct(self) -> None:
        # A delivered build is "committed" mechanically but unverified by hand.
        rec = writeback.record_delivery(self.root, self._contrib(1), self._result())
        report = metrics.collect(self.root)
        self.assertEqual(report["outcomes"]["published"], 1)
        self.assertEqual(report["correct"], 0)
        self.assertEqual(report["incorrect"], 0)
        self.assertEqual(report["unverified"], 1)
        self.assertIn("unverified: 1", metrics.render(report))

        # The bad-build case: it committed, but the rubric check failed.
        marked = writeback.mark_correct(self.root, rec["id"], False)
        self.assertEqual(marked["correct"], "false")
        report = metrics.collect(self.root)
        self.assertEqual(report["incorrect"], 1)
        self.assertEqual(report["unverified"], 0)
        self.assertIn("incorrect: 1", metrics.render(report))

        # Marking correct flips it, and "correct" is what counts as a success.
        writeback.mark_correct(self.root, rec["id"], True)
        report = metrics.collect(self.root)
        self.assertEqual(report["correct"], 1)
        self.assertEqual(report["incorrect"], 0)
        self.assertIn("correct: 1", metrics.render(report))

    def test_mark_correct_refuses_a_non_record(self) -> None:
        doc = {"id": "document-notes", "type": "document", "title": "Notes",
               "created": "2026-11-21", "updated": "2026-11-21",
               "status": "active", "tags": []}
        (self.root / "context/documents/notes.md").write_text(
            frontmatter.dumps(doc, "# Notes\n"), encoding="utf-8")
        with self.assertRaises(writeback.WritebackError):
            writeback.mark_correct(self.root, "document-notes", True)
