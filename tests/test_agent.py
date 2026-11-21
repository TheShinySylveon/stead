"""Model-driven build: planning first, repo-bounded edits, checks, commit."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from ctx import agent, db, frontmatter


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout


class BuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.code = self.root / "code"
        for folder in ("context/repos", "context/contributions"):
            (self.root / folder).mkdir(parents=True)
        self.code.mkdir()
        _git(self.code, "init", "-b", "main")
        _git(self.code, "config", "user.email", "test@example.com")
        _git(self.code, "config", "user.name", "Test")
        (self.code / "app.py").write_text("print('hi')\n", encoding="utf-8")
        _git(self.code, "add", "-A")
        _git(self.code, "commit", "-m", "start")
        repo = {"id": "repo-me-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "default_branch": "main",
                "code_path": str(self.code), "reach": "draft-pr",
                "trigger": "on-demand"}
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps(repo, "# App\n"), encoding="utf-8")
        body = ("The greeting script should accept a --name option so a caller can "
                "address a specific person without editing the source. The default "
                "output must stay the same when the flag is absent, and the new path "
                "should be covered by a small test.\n\n"
                "## Acceptance criteria\n\n"
                "- [ ] the greeting uses the flag\n")
        spec = {"id": "contribution-me-app-issue-42", "type": "contribution",
                "title": "Add a name flag", "created": "2026-11-21",
                "updated": "2026-11-21", "repo": "repo-me-app", "kind": "issue",
                "number": 42, "role": "author", "state": "open", "ci": "none",
                "review": "none", "method": "builtin", "visibility": "public",
                "tags": ["feature-spec"]}
        (self.root / "context/contributions/issue-42.md").write_text(
            frontmatter.dumps(spec, body), encoding="utf-8")
        db.init_db(self.root)

    def _responder(self, replies: list[dict]):
        queue = list(replies)

        def respond(_prompt: str) -> str:
            if not queue:
                raise AssertionError("model called more times than scripted")
            return json.dumps(queue.pop(0))

        return respond

    def test_plan_then_edit_then_commit(self) -> None:
        responder = self._responder([
            {"action": "plan", "summary": "Add an argparse flag."},
            {"action": "read", "path": "app.py"},
            {"action": "write", "path": "app.py",
             "content": "import argparse\nprint('hi')\n"},
            {"action": "finish", "summary": "Flag added."},
        ])
        result = agent.build(self.root, "contribution-me-app-issue-42",
                             responder=responder)
        self.assertEqual(result["files"], ["app.py"])
        self.assertEqual(result["branch"], "stead/42-add-a-name-flag")
        self.assertEqual(_git(self.code, "rev-parse", "--abbrev-ref", "HEAD").strip(),
                         "stead/42-add-a-name-flag")
        self.assertIn("argparse", (self.code / "app.py").read_text(encoding="utf-8"))
        self.assertEqual(result["commit"], _git(self.code, "rev-parse", "HEAD").strip())
        self.assertFalse(result["published"])

    def test_write_before_plan_is_refused(self) -> None:
        responder = self._responder([
            {"action": "write", "path": "app.py", "content": "x"},
        ])
        with self.assertRaises(agent.BuildError):
            agent.build(self.root, "contribution-me-app-issue-42", responder=responder)

    def test_path_outside_the_repo_is_refused(self) -> None:
        responder = self._responder([
            {"action": "plan", "summary": "Escape."},
            {"action": "write", "path": "../escape.txt", "content": "x"},
        ])
        with self.assertRaises(agent.BuildError):
            agent.build(self.root, "contribution-me-app-issue-42", responder=responder)

    def test_dirty_checkout_is_refused(self) -> None:
        (self.code / "scratch.txt").write_text("mine", encoding="utf-8")
        with self.assertRaises(agent.BuildError) as caught:
            agent.build(self.root, "contribution-me-app-issue-42",
                        responder=lambda _p: "{}")
        self.assertIn("uncommitted", str(caught.exception))

    def test_merge_needs_publish(self) -> None:
        responder = self._responder([
            {"action": "plan", "summary": "Change it."},
            {"action": "write", "path": "app.py", "content": "print('new')\n"},
            {"action": "finish", "summary": "Done."},
        ])
        with self.assertRaises(agent.BuildError) as caught:
            agent.build(self.root, "contribution-me-app-issue-42",
                        responder=responder, merge=True)
        self.assertIn("--merge needs --publish", str(caught.exception))

    def test_publish_then_merge_when_reach_allows(self) -> None:
        import unittest.mock as mock
        from ctx import merge as merge_mod, publish as publish_mod
        repo_path = self.root / "context/repos/app.md"
        meta, _body = frontmatter.parse(repo_path.read_text(encoding="utf-8"))
        meta["reach"] = "merge"
        repo_path.write_text(frontmatter.dumps(meta, "# App\n"), encoding="utf-8")
        responder = self._responder([
            {"action": "plan", "summary": "Change it."},
            {"action": "write", "path": "app.py", "content": "print('new')\n"},
            {"action": "finish", "summary": "Done."},
        ])
        with mock.patch.object(publish_mod, "publish",
                               lambda *a, **k: {"url": "https://example.test/pr/1"}), \
             mock.patch.object(merge_mod, "merge",
                               lambda *a, **k: {"merged": True, "url": "https://example.test/pr/1"}):
            result = agent.build(self.root, "contribution-me-app-issue-42",
                                 responder=responder, publish=True, merge=True)
        self.assertTrue(result["published"])
        self.assertTrue(result["merged"])

    def test_failed_checks_can_be_repaired(self) -> None:
        repo_path = self.root / "context/repos/app.md"
        meta, _body = frontmatter.parse(repo_path.read_text(encoding="utf-8"))
        meta["checks"] = ('python -c "import pathlib,sys; '
                          "sys.exit(0 if 'ok' in pathlib.Path('app.py').read_text() else 1)\"")
        repo_path.write_text(frontmatter.dumps(meta, "# App\n"), encoding="utf-8")
        responder = self._responder([
            {"action": "plan", "summary": "Write then fix."},
            {"action": "write", "path": "app.py", "content": "print('bad')\n"},
            {"action": "finish", "summary": "First try."},
            {"action": "write", "path": "app.py", "content": "print('ok')\n"},
            {"action": "finish", "summary": "Second try."},
        ])
        result = agent.build(self.root, "contribution-me-app-issue-42",
                             responder=responder, repair_rounds=1)
        self.assertIn("ok", (self.code / "app.py").read_text(encoding="utf-8"))
        self.assertEqual(result["files"], ["app.py"])

    def test_search_and_delete_actions(self) -> None:
        (self.code / "old.py").write_text("obsolete\n", encoding="utf-8")
        _git(self.code, "add", "-A")
        _git(self.code, "commit", "-m", "old file")
        responder = self._responder([
            {"action": "plan", "summary": "Find and remove."},
            {"action": "search", "query": "print"},
            {"action": "delete", "path": "old.py"},
            {"action": "write", "path": "app.py", "content": "print('new')\n"},
            {"action": "finish", "summary": "Removed."},
        ])
        result = agent.build(self.root, "contribution-me-app-issue-42", responder=responder)
        self.assertFalse((self.code / "old.py").exists())
        self.assertEqual(result["deleted"], ["old.py"])

    def test_lock_blocks_a_second_build(self) -> None:
        from ctx.agent import _lock, _unlock
        held = _lock(self.code)
        try:
            with self.assertRaises(agent.BuildError) as caught:
                agent.build(self.root, "contribution-me-app-issue-42",
                            responder=lambda _p: "{}")
            self.assertIn("another build", str(caught.exception))
        finally:
            _unlock(held)

    def test_resume_continues_the_branch(self) -> None:
        _git(self.code, "checkout", "-b", "stead/42-add-a-name-flag")
        (self.code / "app.py").write_text("print('partial')\n", encoding="utf-8")
        responder = self._responder([
            {"action": "plan", "summary": "Finish the work."},
            {"action": "write", "path": "app.py", "content": "print('done')\n"},
            {"action": "finish", "summary": "Done."},
        ])
        result = agent.build(self.root, "contribution-me-app-issue-42",
                             responder=responder, resume=True)
        self.assertEqual(result["branch"], "stead/42-add-a-name-flag")
        self.assertIn("done", (self.code / "app.py").read_text(encoding="utf-8"))

    def test_failing_checks_stop_the_commit(self) -> None:
        repo_path = self.root / "context/repos/app.md"
        meta, _body = frontmatter.parse(repo_path.read_text(encoding="utf-8"))
        meta["checks"] = 'python -c "import sys; sys.exit(1)"'
        repo_path.write_text(frontmatter.dumps(meta, "# App\n"), encoding="utf-8")
        head = _git(self.code, "rev-parse", "HEAD").strip()
        responder = self._responder([
            {"action": "plan", "summary": "Change it."},
            {"action": "write", "path": "app.py", "content": "print('changed')\n"},
            {"action": "finish", "summary": "Done."},
        ])
        with self.assertRaises(agent.BuildError) as caught:
            agent.build(self.root, "contribution-me-app-issue-42", responder=responder,
                        repair_rounds=0)
        self.assertIn("checks", str(caught.exception).lower())
        self.assertEqual(_git(self.code, "rev-parse", "HEAD").strip(), head)

    def test_spec_without_criteria_is_refused(self) -> None:
        path = self.root / "context/contributions/issue-42.md"
        meta, _body = frontmatter.parse(path.read_text(encoding="utf-8"))
        path.write_text(frontmatter.dumps(meta, "Make it better.\n"), encoding="utf-8")
        with self.assertRaises(agent.BuildError) as caught:
            agent.build(self.root, "contribution-me-app-issue-42",
                        responder=lambda _p: "{}")
        self.assertIn("not buildable", str(caught.exception))
