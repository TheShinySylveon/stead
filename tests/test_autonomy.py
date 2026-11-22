"""Factory trigger and reach. Ceiling is per repo. No remote writes."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ctx import autonomy, cli, config, factory, frontmatter
from tests.test_feature_builder import SPEC_BODY, SPEC_ID, FeatureBuilderTestCase


class AutonomyPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_merge_is_not_an_install_default_and_survives_deployment_save(self) -> None:
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.set_defaults(self.root, reach="merge")
        shown = autonomy.set_defaults(self.root, trigger="watch", reach="draft-pr")
        self.assertEqual(shown["reach"], "draft-pr")
        config.choose(self.root, "single")
        self.assertEqual(autonomy.factory_defaults(self.root)["reach"], "draft-pr")
        self.assertEqual(autonomy.factory_defaults(self.root)["trigger"], "watch")

    def test_budgets_are_saved_and_bounded(self) -> None:
        shown = autonomy.set_defaults(self.root, max_builds_per_day=4, build_minutes=20)
        self.assertEqual(shown["max_builds_per_day"], 4)
        self.assertEqual(shown["build_minutes"], 20)
        config.save_model(self.root, {"provider": "ollama", "name": "llama3.2"})
        kept = autonomy.factory_defaults(self.root)
        self.assertEqual(kept["max_builds_per_day"], 4)
        self.assertEqual(kept["build_minutes"], 20)
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.set_defaults(self.root, build_minutes=0)

    def test_merge_is_not_inherited(self) -> None:
        policy = autonomy.effective(self.root, {})
        self.assertEqual(policy["ceiling"], "shadow")
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.permit(policy, "merge")
        autonomy.set_defaults(self.root, reach="pr")
        inherited = autonomy.effective(self.root, {})
        self.assertEqual(inherited["ceiling"], "pr")
        self.assertEqual(autonomy.permit(inherited, None), "pr")
        with self.assertRaises(autonomy.AutonomyError):
            autonomy.permit(inherited, "merge")
        explicit = autonomy.effective(self.root, {"reach": "merge"})
        self.assertEqual(autonomy.permit(explicit, "merge"), "merge")
        self.assertEqual(autonomy.permit(explicit, "shadow"), "shadow")


class AutonomyRunTest(FeatureBuilderTestCase):
    def test_run_refuses_to_pass_the_ceiling_and_does_not_push(self) -> None:
        self.seed_spec()
        with self.assertRaises(SystemExit) as caught:
            factory.assemble_feature_build(self.root, SPEC_ID, reach="pr")
        self.assertIn("ceiling", str(caught.exception))
        self.assertFalse((self.root / "factories" / "feature-builder" / "runs").exists())

    def test_allowed_draft_pr_is_local_only(self) -> None:
        self.seed_spec()
        autonomy.set_repo(self.root, "repo-testuser-my-app", reach="draft-pr")
        boom = AssertionError("remote write during an allowed draft-pr run")
        with mock.patch("subprocess.run", side_effect=boom), \
             mock.patch("urllib.request.urlopen", side_effect=boom):
            info = factory.assemble_feature_build(self.root, SPEC_ID)
        self.assertEqual(info["reach"], "draft-pr")
        self.assertEqual(info["remote"], "not-implemented")
        self.assertIn("did not push", (self.root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8"))

    def test_watch_skips_on_demand_and_flagged_specs(self) -> None:
        self.seed_spec()
        vague = self.root / "context" / "contributions" / "testuser-my-app-issue-202.md"
        cli.cmd_contribution_add(self.root, "Make it better", "repo-testuser-my-app",
                                 "issue", 202, role="author")
        meta, _body = frontmatter.parse(vague.read_text(encoding="utf-8"))
        meta["tags"] = ["feature-spec"]
        vague.write_text(frontmatter.dumps(meta, "# Make it better\n\nMake it better somehow.\n"),
                         encoding="utf-8")
        report = factory.watch_specs(self.root)
        self.assertEqual(report["ran"], [])
        autonomy.set_repo(self.root, "repo-testuser-my-app", trigger="watch", reach="shadow")
        report = factory.watch_specs(self.root)
        self.assertEqual([item["id"] for item in report["ran"]], [SPEC_ID])
        self.assertEqual(report["ran"][0]["remote"], "none")
        self.assertTrue(any(item["id"].endswith("issue-202") for item in report["skipped"]))
        self.assertIn(SPEC_BODY.split("\n", 1)[0].lstrip("# "),
                      (self.root / report["ran"][0]["run_dir"] / "bundle.md").read_text(encoding="utf-8"))

    def test_watch_respects_the_stop_file(self) -> None:
        from ctx import safety
        self.seed_spec()
        autonomy.set_repo(self.root, "repo-testuser-my-app", trigger="watch")
        safety.set_stopped(self.root, True)
        try:
            report = factory.watch_specs(self.root)
        finally:
            safety.set_stopped(self.root, False)
        self.assertTrue(report.get("stopped"))
        self.assertEqual(report["ran"], [])

    def test_watch_stops_at_the_daily_build_budget(self) -> None:
        self.seed_spec()
        autonomy.set_repo(self.root, "repo-testuser-my-app", trigger="watch")
        autonomy.set_defaults(self.root, max_builds_per_day=2)
        with mock.patch.object(factory, "_builds_today", return_value=2):
            report = factory.watch_specs(self.root, build=True)
        self.assertEqual(report["ran"], [])
        self.assertTrue(any("budget" in item["reason"] for item in report["skipped"]))
