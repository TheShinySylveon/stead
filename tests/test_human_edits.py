"""A merged PR counts as human-edited only when its head carries changes the
build did not make. Updating the branch from the base (GitHub's "Update
branch", needed under a strict up-to-date rule) is not an edit."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ctx import frontmatter, metrics, objects, writeback

PR = "https://github.com/me/app/pull/7"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


class _Fixture(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "store"
        self.code = Path(self._tmp.name) / "code"
        for folder in ("repos", "contributions", "documents"):
            (self.root / "context" / folder).mkdir(parents=True)
        self.code.mkdir()
        _git(self.code, "init", "-b", "main")
        _git(self.code, "config", "user.email", "test@example.com")
        _git(self.code, "config", "user.name", "Test")
        (self.code / "app.py").write_text("print('hi')\n", encoding="utf-8")
        (self.code / "other.py").write_text("x = 1\n", encoding="utf-8")
        _git(self.code, "add", "-A")
        _git(self.code, "commit", "-m", "start")
        # The build's commit on its branch.
        _git(self.code, "switch", "-c", "stead/7-feature")
        (self.code / "app.py").write_text("print('hi')\nprint('flag')\n", encoding="utf-8")
        _git(self.code, "commit", "-am", "build")
        self.built = _git(self.code, "rev-parse", "HEAD")
        # Main moves on in another file.
        _git(self.code, "switch", "main")
        (self.code / "other.py").write_text("x = 2\n", encoding="utf-8")
        _git(self.code, "commit", "-am", "main moves on")
        _git(self.code, "switch", "stead/7-feature")

        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "default_branch": "main",
                "code_path": str(self.code)}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        self.cid = "contribution-me-app-issue-7"
        spec = {"id": self.cid, "type": "contribution", "title": "Feature",
                "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-me-app", "kind": "issue", "number": 7,
                "role": "author", "state": "open", "visibility": "public"}
        (self.root / "context/contributions/issue-7.md").write_text(
            frontmatter.dumps(spec, "# Feature\n"), encoding="utf-8")

    def _record(self, **over) -> None:
        result = {"branch": "stead/7-feature", "commit": self.built, "files": ["app.py"],
                  "deleted": [], "checks": "make test", "checks_mode": "host",
                  "tests_touched": [], "tests_deleted": [], "elapsed_seconds": 1.0,
                  "repair_rounds": 0, "summary": "done", "published": True,
                  "merged": False, "pr_url": PR}
        result.update(over)
        writeback.record_delivery(self.root, self.cid, result)

    def _merged_at(self, head: str) -> int:
        writeback.reconcile_records(
            self.root, lambda _url: {"state": "MERGED", "headRefOid": head})
        return metrics.collect(self.root)["human_edits"]


class HumanEditsTest(_Fixture):
    def test_an_update_from_main_is_not_a_human_edit(self) -> None:
        self._record()
        _git(self.code, "merge", "--no-ff", "-m", "Merge branch 'main' into stead/7-feature",
             "main")
        head = _git(self.code, "rev-parse", "HEAD")
        self.assertNotEqual(head, self.built)
        self.assertEqual(self._merged_at(head), 0)

    def test_a_commit_on_the_branch_is_a_human_edit(self) -> None:
        self._record()
        (self.code / "app.py").write_text("print('hi')\nprint('tweaked')\n", encoding="utf-8")
        _git(self.code, "commit", "-am", "human tweak")
        self.assertEqual(self._merged_at(_git(self.code, "rev-parse", "HEAD")), 1)

    def test_a_change_hidden_in_the_update_merge_is_a_human_edit(self) -> None:
        self._record()
        _git(self.code, "merge", "--no-ff", "--no-commit", "main")
        (self.code / "app.py").write_text("print('hi')\nprint('sneaky')\n", encoding="utf-8")
        _git(self.code, "add", "-A")
        _git(self.code, "commit", "-m", "Merge branch 'main' into stead/7-feature")
        self.assertEqual(self._merged_at(_git(self.code, "rev-parse", "HEAD")), 1)

    def test_a_head_the_checkout_cannot_see_counts_as_an_edit(self) -> None:
        self._record()
        self.assertEqual(self._merged_at("f" * 40), 1)

    def test_factory_merge_uses_the_same_rule(self) -> None:
        self._record()
        _git(self.code, "merge", "--no-ff", "-m", "update", "main")
        writeback.mark_merged(self.root, self.cid, url=PR,
                              head_sha=_git(self.code, "rev-parse", "HEAD"))
        self.assertEqual(metrics.collect(self.root)["human_edits"], 0)


class PublishRecordTest(_Fixture):
    def _records(self) -> list[dict]:
        return [meta for _path, meta, _body in objects.iter_objects(self.root, "document")]

    def test_factory_publish_points_the_record_at_the_pr(self) -> None:
        self._record(published=False, pr_url=None)
        self.assertNotIn("pr_url", self._records()[0])
        writeback.mark_published(self.root, "repo-me-app", "stead/7-feature", PR)
        meta = self._records()[0]
        self.assertEqual(meta["pr_url"], PR)
        self.assertEqual(meta["outcome"], "published")
        # And sync can now reconcile the merge.
        result = writeback.reconcile_records(
            self.root, lambda _url: {"state": "MERGED", "headRefOid": self.built})
        self.assertEqual(result["reconciled"], 1)

    def test_mark_merged_updates_the_newest_record_of_the_day(self) -> None:
        older = {"id": "document-build-feature-20261121T010000Z", "type": "document",
                 "title": "Build: Feature (committed)", "created": "2026-11-21",
                 "updated": "2026-11-21", "status": "active",
                 "tags": ["build-record", "repo:repo-me-app"], "outcome": "committed",
                 "contribution": self.cid, "commit": "old"}
        newer = dict(older, id="document-build-feature-20261121T020000Z", commit=self.built)
        for meta in (newer, older):  # write order must not matter
            (self.root / "context/documents" / f"{meta['id'][len('document-'):]}.md").write_text(
                frontmatter.dumps(meta, "# Build\n"), encoding="utf-8")
        writeback.mark_merged(self.root, self.cid, url=PR, head_sha=self.built)
        by_id = {meta["id"]: meta for meta in self._records()}
        self.assertEqual(by_id[newer["id"]]["outcome"], "merged")
        self.assertEqual(by_id[older["id"]]["outcome"], "committed")


if __name__ == "__main__":
    unittest.main()
