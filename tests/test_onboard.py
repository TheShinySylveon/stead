"""Onboard: project + repo + constitution, with specify optional and never required."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ctx import cli, db, frontmatter, objects, onboard


def make_root(base: Path) -> Path:
    root = base / "repo"
    (root / "context").mkdir(parents=True)
    db.init_db(root)
    return root


class OnboardTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = make_root(Path(self._tmp.name))
        self.code = Path(self._tmp.name) / "app"
        self.code.mkdir()

    def test_builtin_writes_project_repo_and_constitution(self) -> None:
        result = onboard.onboard(self.root, "Side App", kind="own", method="builtin",
                                 code_path=str(self.code))
        self.assertEqual(result["specify"], "builtin")
        project = objects.find(self.root, "project", result["project"])
        repo = objects.find(self.root, "repo", result["repo"])
        doc = objects.find(self.root, "document", result["constitution"])
        self.assertEqual(repo[1]["project"], result["project"])
        self.assertEqual(doc[1]["project"], result["project"])
        self.assertIn("feature-builder", doc[2])
        self.assertIn("never push", doc[2].lower())
        self.assertTrue((self.code / "constitution.md").is_file())
        self.assertFalse((self.code / ".specify").exists())

    def test_oss_constitution_stays_local(self) -> None:
        result = onboard.onboard(self.root, "Upstream Lib", kind="oss", method="builtin")
        doc = objects.find(self.root, "document", result["constitution"])
        self.assertIn("Do not commit or push", doc[2])

    def test_spec_kit_uses_runner_and_does_not_require_specify(self) -> None:
        calls = []

        def runner(target, integration):
            calls.append((target, integration))
            return {"status": "skipped", "command": "specify init", "detail": "not installed"}

        result = onboard.onboard(self.root, "Kit App", method="spec-kit",
                                 code_path=str(self.code), integration="copilot",
                                 specify_runner=runner)
        self.assertEqual(calls, [(self.code.resolve(), "copilot")])
        self.assertEqual(result["specify"], "skipped")
        self.assertTrue(objects.find(self.root, "project", result["project"]))
        self.assertTrue((self.code / "constitution.md").is_file())

    def test_specify_argv_cannot_prompt(self) -> None:
        argv = onboard.specify_argv("claude", "ps")
        self.assertIn("--non-interactive", argv)
        self.assertIn("--ignore-agent-tools", argv)
        self.assertIn("--here", argv)
        self.assertNotIn("--trust-extension-urls", argv)

    def test_refuses_the_context_repo_and_a_missing_directory(self) -> None:
        with self.assertRaises(onboard.OnboardError):
            onboard.onboard(self.root, "Nope", code_path=str(self.root))
        with self.assertRaises(onboard.OnboardError):
            onboard.onboard(self.root, "Nope", code_path=str(self.code / "missing"))

    def test_welcome_is_the_empty_checkout_path(self) -> None:
        self.assertTrue(onboard.needs_welcome(self.root))
        result = onboard.welcome(self.root, "First Project")
        self.assertFalse(onboard.needs_welcome(self.root))
        self.assertEqual(result["method"], "builtin")
        self.assertEqual(result["specify"], "builtin")
        repo = objects.find(self.root, "repo", result["repo"])
        self.assertEqual(repo[1]["project"], result["project"])

    def test_cli_parser_accepts_onboard(self) -> None:
        args = cli.build_parser().parse_args(
            ["onboard", "--title", "Demo", "--kind", "own", "--method", "builtin", "--no-specify"])
        self.assertEqual(args.command, "onboard")
        self.assertTrue(args.no_specify)
