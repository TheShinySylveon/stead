"""Merge is explicit, green-only, and never bypasses branch protection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from ctx import autonomy
from ctx.merge import MergeError, merge
from ctx.publish import PublishError, publish
from tests import strip_git_hygiene
from tests.test_feature_builder import SPEC_ID, FeatureBuilderTestCase


def _view(**overrides) -> str:
    payload = {
        "number": 9,
        "url": "https://github.com/testuser/my-app/pull/9",
        "state": "OPEN",
        "isDraft": False,
        "baseRefName": "main",
        "headRefName": "feature/json",
        "headRefOid": "builtsha",
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

    def _allow(self, **extra) -> None:
        fields = {"trust_checks": "host", "merge_without_required_checks": True,
                  "merge_without_review": True}
        fields.update(extra)
        autonomy.set_repo(self.root, "repo-testuser-my-app", reach="merge",
                          code_path=str(self.code), extra=fields)

    def _review_runner(self, calls: list | None = None):
        """A runner that reaches the reviewer: branch, head, PR view, diff."""
        def runner(argv, _cwd):
            argv = strip_git_hygiene(argv)
            if calls is not None:
                calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return "builtsha\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view()
            if argv[:3] == ["git", "diff", "main...HEAD"]:
                return "diff --git a/app.py b/app.py\n+print('x')\n"
            if argv[:4] == ["gh", "pr", "merge", "9"]:
                return ""
            raise AssertionError(argv)
        return runner

    def test_the_independent_reviewer_must_approve_before_merge(self) -> None:
        from ctx import spec as spec_approval
        spec_approval.approve(self.root, SPEC_ID)
        self._allow(merge_without_review=False)
        prompts = []

        def reviewer(prompt):
            prompts.append(prompt)
            return json.dumps({"verdict": "approve", "reason": "criteria met"})

        opened = merge(self.root, SPEC_ID, runner=self._review_runner(),
                       reviewer=reviewer)
        self.assertTrue(opened["merged"])
        self.assertIn("Acceptance criteria", prompts[0])
        self.assertIn("diff --git", prompts[0])
        self.assertIn("untrusted", prompts[0])
        reviews = list((self.root / "context/documents").glob("review-*.md"))
        self.assertEqual(len(reviews), 1)

    def test_the_independent_reviewer_can_block_the_merge(self) -> None:
        from ctx import spec as spec_approval
        spec_approval.approve(self.root, SPEC_ID)
        self._allow(merge_without_review=False)
        calls: list = []

        def reviewer(_prompt):
            return json.dumps({"verdict": "reject", "reason": "no test for the flag"})

        with self.assertRaises(MergeError) as caught:
            merge(self.root, SPEC_ID, runner=self._review_runner(calls),
                  reviewer=reviewer)
        self.assertIn("rejected", str(caught.exception))
        self.assertFalse(any(argv[1:3] == ["pr", "merge"] for argv in calls
                             if len(argv) > 2))

    def test_a_merge_without_a_model_or_reviewer_is_refused(self) -> None:
        from ctx import spec as spec_approval
        spec_approval.approve(self.root, SPEC_ID)
        self._allow(merge_without_review=False)
        with self.assertRaises(MergeError) as caught:
            merge(self.root, SPEC_ID, runner=self._review_runner())
        self.assertIn("reviewer pass could not run", str(caught.exception))

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
            argv = strip_git_hygiene(argv)
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
            argv = strip_git_hygiene(argv)
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return "builtsha\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view()
            if argv[:4] == ["gh", "pr", "merge", "9"]:
                self.assertEqual(argv[:5], ["gh", "pr", "merge", "9", "--merge"])
                self.assertIn("--match-head-commit", argv)
                self.assertIn("builtsha", argv)
                self.assertNotIn("--admin", argv)
                return ""
            raise AssertionError(argv)

        opened = merge(self.root, SPEC_ID, runner=runner)
        self.assertTrue(opened["merged"])
        self.assertFalse(opened["bypassed"])
        self.assertFalse(any(argv[1] == "push" for argv in calls if len(argv) > 1))

    def test_merge_refuses_a_head_that_differs_from_the_built_commit(self) -> None:
        self._allow()
        calls = []

        def runner(argv, _cwd):
            argv = strip_git_hygiene(argv)
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return "builtsha\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view(headRefOid="human-edited-sha")
            raise AssertionError(argv)

        with self.assertRaises(MergeError) as caught:
            merge(self.root, SPEC_ID, runner=runner)
        self.assertIn("differs from the commit Stead built", str(caught.exception))
        self.assertFalse(any(argv[1:3] == ["pr", "merge"] for argv in calls if len(argv) > 2))

    def test_host_checks_are_not_merged_without_an_ack(self) -> None:
        autonomy.set_repo(self.root, "repo-testuser-my-app", reach="merge",
                          code_path=str(self.code))

        def boom(*_args):
            raise AssertionError("gh was called before the checks gate")

        with self.assertRaises(MergeError) as caught:
            merge(self.root, SPEC_ID, runner=boom)
        self.assertIn("checks run on the host", str(caught.exception))

    def test_default_branch_must_require_checks(self) -> None:
        self._allow(merge_without_required_checks=False)

        def runner(argv, _cwd):
            argv = strip_git_hygiene(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view()
            if argv[:4] == ["gh", "repo", "view", "--json"]:
                return "testuser/my-app\n"
            if argv[:3] == ["gh", "api", "repos/testuser/my-app/branches/main/protection"]:
                raise PublishError("HTTP 404: Branch not protected")
            if argv[:3] == ["gh", "api", "repos/testuser/my-app/rules/branches/main"]:
                return "[]"
            raise AssertionError(argv)

        with self.assertRaises(MergeError) as caught:
            merge(self.root, SPEC_ID, runner=runner)
        self.assertIn("required status checks", str(caught.exception))

    def test_rulesets_satisfy_the_required_checks_gate(self) -> None:
        self._allow(trust_checks=None, checks_isolation="docker",
                    merge_without_required_checks=False)

        def runner(argv, _cwd):
            argv = strip_git_hygiene(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return "builtsha\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view()
            if argv[:4] == ["gh", "repo", "view", "--json"]:
                return "testuser/my-app\n"
            if argv[:3] == ["gh", "api", "repos/testuser/my-app/branches/main/protection"]:
                raise PublishError("HTTP 404: Branch not protected")
            if argv[:3] == ["gh", "api", "repos/testuser/my-app/rules/branches/main"]:
                return json.dumps([{"type": "required_status_checks",
                                    "parameters": {"required_status_checks":
                                                   [{"context": "tests"}]}}])
            if argv[:4] == ["gh", "pr", "merge", "9"]:
                return ""
            raise AssertionError(argv)

        opened = merge(self.root, SPEC_ID, runner=runner)
        self.assertTrue(opened["merged"])

    def test_protected_default_and_docker_checks_merge(self) -> None:
        self._allow(trust_checks=None, checks_isolation="docker",
                    merge_without_required_checks=False)

        def runner(argv, _cwd):
            argv = strip_git_hygiene(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-parse", "HEAD"]:
                return "builtsha\n"
            if argv[:3] == ["gh", "pr", "view"]:
                return _view()
            if argv[:4] == ["gh", "repo", "view", "--json"]:
                return "testuser/my-app\n"
            if argv[:3] == ["gh", "api", "repos/testuser/my-app/branches/main/protection"]:
                return json.dumps({"required_status_checks": {"contexts": ["tests"]}})
            if argv[:4] == ["gh", "pr", "merge", "9"]:
                return ""
            raise AssertionError(argv)

        opened = merge(self.root, SPEC_ID, runner=runner)
        self.assertTrue(opened["merged"])

    def test_publish_at_merge_ceiling_opens_a_pr_and_does_not_merge(self) -> None:
        self._allow()
        calls = []

        def runner(argv, _cwd):
            argv = strip_git_hygiene(argv)
            calls.append(argv)
            if argv[:3] == ["git", "rev-parse", "--abbrev-ref"]:
                return "feature/json\n"
            if argv[:3] == ["git", "rev-list", "--count"]:
                return "1\n"
            if argv[:3] == ["git", "diff", "--name-status"]:
                return "M\tapp.py\n"
            if argv[:3] == ["git", "push", "-u"]:
                return ""
            if argv[:3] == ["gh", "pr", "create"]:
                self.assertNotIn("--draft", argv)
                return "https://github.com/testuser/my-app/pull/9\n"
            raise AssertionError(argv)

        opened = publish(self.root, SPEC_ID, runner=runner)
        self.assertFalse(opened["merged"])
        self.assertFalse(any("merge" in argv for argv in calls))
