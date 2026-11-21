"""Merge is explicit, green-only, and never bypasses branch protection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ctx import autonomy
from ctx.merge import MergeError, merge
from ctx.publish import publish
from tests.test_feature_builder import SPEC_ID, FeatureBuilderTestCase


def _view(**overrides) -> str:
    payload = {
        "number": 9,
        "url": "https://github.com/testuser/my-app/pull/9",
        "state": "OPEN",
        "isDraft": False,
        "baseRefName": "main",
        "headRefName": "feature/json",
        "statusCheckRollup": [
            {"name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
        ],
    }
    payload.update(overrides)
    return json.dumps(payload)


class MergeTest(FeatureBuilderTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.seed_spec()
        self.code = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.code, ignore_errors=True))

    def _allow(self) -> None:
        autonomy.set_repo(self.root, "repo-testuser-my-app", reach="merge",
                          code_path=str(self.code))

    def test_inherited_merge_never_calls_gh(self) -> None:
        autonomy.set_repo(self.root, "repo-testuser-my-app", code_path=str(self.code))

        def boom(*_args):
            raise AssertionError("gh was called")

        with self.assertRaises(MergeError) as caught:
            merge(self.root, SPEC_ID, runner=boom)
        self.assertIn("not inherited", str(caught.exception))

    def test_red_check_is_not_merged(self) -> None:
        self._allow()
        calls = []

        def runner(argv, _cwd):
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view(statusCheckRollup=[
                    {"name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"},
                ])
            raise AssertionError(argv)

        with self.assertRaises(MergeError) as caught:
            merge(self.root, SPEC_ID, runner=runner)
        self.assertIn("not green", str(caught.exception))
        self.assertFalse(any(argv[1:3] == ["pr", "merge"] for argv in calls if len(argv) > 2))

    def test_green_pr_merges_without_admin_or_a_default_push(self) -> None:
        self._allow()
        calls = []

        def runner(argv, _cwd):
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view()
            if argv[:4] == ["gh", "pr", "merge", "9"]:
                self.assertEqual(argv, ["gh", "pr", "merge", "9", "--merge"])
                self.assertNotIn("--admin", argv)
                return ""
            raise AssertionError(argv)

        opened = merge(self.root, SPEC_ID, runner=runner)
        self.assertTrue(opened["merged"])
        self.assertFalse(opened["bypassed"])
        self.assertFalse(any(argv[1] == "push" for argv in calls if len(argv) > 1))

    def test_publish_at_merge_ceiling_opens_a_pr_and_does_not_merge(self) -> None:
        self._allow()
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
                return "https://github.com/testuser/my-app/pull/9\n"
            raise AssertionError(argv)

        opened = publish(self.root, SPEC_ID, runner=runner)
        self.assertFalse(opened["merged"])
        self.assertFalse(any("merge" in argv for argv in calls))
