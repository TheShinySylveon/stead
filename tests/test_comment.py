"""The gated issue comment: kind own, allow_comment, idempotent marker,
and a clean skip when the spec has no real upstream issue."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import db, frontmatter
from ctx.comment import CommentError, COMMENT_MARKER, comment


class CommentTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("repos", "contributions"):
            (self.root / "context" / folder).mkdir(parents=True)
        (self.root / "code").mkdir()
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own",
                "url": "https://github.com/me/app",
                "code_path": str(self.root / "code"),
                "allow_comment": "true"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        spec = {"id": "contribution-me-app-issue-5", "type": "contribution",
                "title": "Add export", "created": "2026-11-21",
                "updated": "2026-11-21", "repo": "repo-me-app",
                "kind": "issue", "number": 5, "role": "author",
                "state": "open", "visibility": "public"}
        (self.root / "context/contributions/issue-5.md").write_text(
            frontmatter.dumps(spec, "# Add export\n"), encoding="utf-8")
        db.init_db(self.root)

    def test_comment_creates_when_there_is_no_marker(self) -> None:
        calls = []

        def runner(argv, _cwd):
            calls.append(argv)
            if argv[1] == "api" and argv[2] == "user":
                return "me\n"
            if argv[1] == "api" and argv[2] == "repos/me/app/issues/5":
                return '{"number": 5}'
            if argv[1] == "api" and "--paginate" in argv:
                return "[]"
            if argv[1] == "issue":
                self.assertIn("--repo", argv)
                self.assertIn("me/app", argv)
                self.assertIn(COMMENT_MARKER, argv[argv.index("--body") + 1])
                return "https://github.com/me/app/issues/5#issuecomment-1\n"
            raise AssertionError(argv)

        result = comment(self.root, "contribution-me-app-issue-5",
                         "https://github.com/me/app/pull/9", runner=runner)
        self.assertTrue(result["created"])
        self.assertTrue(any(a[1] == "issue" for a in calls))

    def test_comment_updates_the_marked_comment_in_place(self) -> None:
        def runner(argv, _cwd):
            if argv[1] == "api" and argv[2] == "user":
                return "me\n"
            if argv[1] == "api" and argv[2] == "repos/me/app/issues/5":
                return '{"number": 5}'
            if argv[1] == "api" and "--paginate" in argv:
                return ('[{"id": 42, "body": "' + COMMENT_MARKER + ' old\\n", '
                        '"user": {"login": "me"}}]')
            if argv[1] == "api" and "PATCH" in argv:
                return "{}"
            raise AssertionError(argv)

        result = comment(self.root, "contribution-me-app-issue-5",
                         "https://github.com/me/app/pull/9", runner=runner)
        self.assertTrue(result["updated"])
        self.assertEqual(result["url"],
                         "https://github.com/me/app/issues/5#issuecomment-42")

    def test_comment_ignores_a_strangers_marked_comment(self) -> None:
        def runner(argv, _cwd):
            if argv[1] == "api" and argv[2] == "user":
                return "me\n"
            if argv[1] == "api" and argv[2] == "repos/me/app/issues/5":
                return '{"number": 5}'
            if argv[1] == "api" and "--paginate" in argv:
                return ('[{"id": 9, "body": "' + COMMENT_MARKER + ' theirs\\n", '
                        '"user": {"login": "stranger"}}]')
            if argv[1] == "issue":
                self.assertIn("--repo", argv)
                return "https://github.com/me/app/issues/5#issuecomment-1\n"
            raise AssertionError(argv)

        result = comment(self.root, "contribution-me-app-issue-5",
                         "https://github.com/me/app/pull/9", runner=runner)
        self.assertTrue(result["created"])  # does not overwrite the stranger's

    def test_comment_skips_when_the_number_is_a_pr_upstream(self) -> None:
        # Issues and PRs share a number space: a local-only spec numbered 5
        # must not post onto pull/5 when no issue 5 exists upstream.
        calls = []

        def runner(argv, _cwd):
            calls.append(argv)
            if argv[1] == "api" and argv[2] == "repos/me/app/issues/5":
                return ('{"number": 5, "pull_request": '
                        '{"url": "https://api.github.com/repos/me/app/pulls/5"}}')
            raise AssertionError(argv)

        result = comment(self.root, "contribution-me-app-issue-5",
                         "https://github.com/me/app/pull/9", runner=runner)
        self.assertTrue(result["skipped"])
        self.assertIn("pull request", result["reason"])
        self.assertFalse(any(a[1] == "issue" for a in calls))

    def test_comment_skips_when_there_is_no_upstream_issue(self) -> None:
        calls = []

        def runner(argv, _cwd):
            calls.append(argv)
            if argv[1] == "api" and argv[2] == "repos/me/app/issues/5":
                raise CommentError("HTTP 404: Not Found")
            raise AssertionError(argv)

        result = comment(self.root, "contribution-me-app-issue-5",
                         "https://github.com/me/app/pull/9", runner=runner)
        self.assertTrue(result["skipped"])
        self.assertIn("no upstream issue", result["reason"])
        self.assertFalse(any(a[1] == "issue" for a in calls))

    def test_comment_rejects_a_pr_in_another_repo(self) -> None:
        with self.assertRaises(CommentError) as caught:
            comment(self.root, "contribution-me-app-issue-5",
                    "https://github.com/other/repo/pull/9", runner=lambda *a: "")
        self.assertIn("not in", str(caught.exception))

    def test_comment_requires_allow_comment(self) -> None:
        path = self.root / "context/repos/app.md"
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta["allow_comment"] = "false"
        path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        with self.assertRaises(CommentError) as caught:
            comment(self.root, "contribution-me-app-issue-5",
                    "https://github.com/me/app/pull/9", runner=lambda *a: "")
        self.assertIn("allow_comment", str(caught.exception))

    def test_comment_requires_kind_own(self) -> None:
        path = self.root / "context/repos/app.md"
        meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
        meta["kind"] = "oss"
        path.write_text(frontmatter.dumps(meta, body), encoding="utf-8")
        with self.assertRaises(CommentError) as caught:
            comment(self.root, "contribution-me-app-issue-5",
                    "https://github.com/me/app/pull/9", runner=lambda *a: "")
        self.assertIn("kind: own", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
