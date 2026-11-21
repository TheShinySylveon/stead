"""Publish opens a pull request from an isolated branch. It never merges."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import autonomy
from ctx.publish import PublishError, publish
from tests.test_feature_builder import SPEC_ID, FeatureBuilderTestCase


class PublishTest(FeatureBuilderTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_spec()
        self.code = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.code, ignore_errors=True))

    def test_shadow_ceiling_never_calls_git(self) -> None:
        def boom(*_args):
            raise AssertionError("git was called")
        with self.assertRaises(PublishError):
            publish(self.root, SPEC_ID, runner=boom)

    def test_merge_ceiling_still_does_not_merge_from_publish(self) -> None:
        autonomy.set_repo(self.root, "repo-testuser-my-app", reach="merge",
                          code_path=str(self.code))
        calls = []

        def runner(argv, _cwd):
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-list", "--count"]:
                return "1\n"
            if argv[:3] == ["git", "push", "-u"]:
                return ""
            if argv[:3] == ["gh", "pr", "create"]:
                self.assertNotIn("--draft", argv)
                return "https://github.com/testuser/my-app/pull/4\n"
            raise AssertionError(argv)

        opened = publish(self.root, SPEC_ID, runner=runner)
        self.assertFalse(opened["merged"])
        self.assertFalse(any(len(argv) > 2 and argv[1:3] == ["pr", "merge"] for argv in calls))

    def test_refuses_the_default_branch(self) -> None:
        autonomy.set_repo(self.root, "repo-testuser-my-app", reach="draft-pr",
                          code_path=str(self.code))
        calls = []

        def runner(argv, _cwd):
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "main\n"
            raise AssertionError(argv)

        with self.assertRaises(PublishError) as caught:
            publish(self.root, SPEC_ID, runner=runner)
        self.assertIn("refusing", str(caught.exception))
        self.assertFalse(any(argv[1] == "push" for argv in calls if len(argv) > 1))

    def test_draft_pr_pushes_the_isolated_branch_and_does_not_merge(self) -> None:
        autonomy.set_repo(self.root, "repo-testuser-my-app", reach="draft-pr",
                          code_path=str(self.code))
        calls = []

        def runner(argv, cwd):
            calls.append((argv, Path(cwd)))
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-list", "--count"]:
                self.assertEqual(argv[3], "main..HEAD")
                return "2\n"
            if argv[:3] == ["git", "push", "-u"]:
                self.assertEqual(argv[4], "HEAD:feature/json")
                return ""
            if argv[:3] == ["gh", "pr", "create"]:
                self.assertIn("--draft", argv)
                self.assertNotIn("merge", argv)
                return "https://github.com/testuser/my-app/pull/9\n"
            raise AssertionError(argv)

        opened = publish(self.root, SPEC_ID, runner=runner)
        self.assertEqual(opened["url"], "https://github.com/testuser/my-app/pull/9")
        self.assertFalse(opened["merged"])
        self.assertEqual(opened["branch"], "feature/json")
        self.assertTrue(all(cwd == self.code for _argv, cwd in calls))
