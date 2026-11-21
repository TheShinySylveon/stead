"""Writes stamp the current actor. Promote waits for recorded eval passes."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from ctx import actors, cli, db, frontmatter, models
from ctx.actors import ENV_ACTOR


class ActorStampTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.addCleanup(lambda: os.environ.pop(ENV_ACTOR, None))
        for folder in ("context/projects", "context/tasks", "context/actors"):
            (self.root / folder).mkdir(parents=True)
        db.init_db(self.root)
        cli.cmd_task_add  # keep the import used
        meta = {"id": "project-demo", "type": "project", "title": "Demo",
                "created": "2026-11-21", "updated": "2026-11-21", "status": "active"}
        (self.root / "context/projects/demo.md").write_text(
            frontmatter.dumps(meta, "# Demo\n"), encoding="utf-8")
        actor = {"id": "actor-ada", "type": "actor", "title": "Ada",
                 "created": "2026-11-21", "updated": "2026-11-21",
                 "status": "active", "kind": "human"}
        (self.root / "context/actors/ada.md").write_text(
            frontmatter.dumps(actor, "# Ada\n"), encoding="utf-8")

    def test_unstamped_when_nobody_is_selected(self) -> None:
        cli.cmd_task_add(self.root, "Write it", "demo")
        _path, meta, _body = __import__("ctx").objects.find(
            self.root, "task", "task-write-it")
        self.assertNotIn("actor", meta)

    def test_selected_actor_is_stamped(self) -> None:
        os.environ[ENV_ACTOR] = "actor-ada"
        cli.cmd_task_add(self.root, "Write it", "demo")
        _path, meta, _body = __import__("ctx").objects.find(
            self.root, "task", "task-write-it")
        self.assertEqual(meta["actor"], "actor-ada")
        self.assertEqual(actors.current(self.root), "actor-ada")


class PromoteGateTest(unittest.TestCase):
    def test_promote_refuses_until_each_case_passes_for_that_version(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        prompts = root / "factories/weekly-project-status/prompts"
        evals = root / "factories/weekly-project-status/evals"
        prompts.mkdir(parents=True)
        evals.mkdir()
        (prompts / "v2.md").write_text("Better.\n", encoding="utf-8")
        (evals / "eval-ok.json").write_text(json.dumps({
            "id": "eval-ok", "title": "Ok", "input": "x", "pass_criteria": "y",
        }), encoding="utf-8")
        db.init_db(root)
        with self.assertRaises(SystemExit) as caught:
            cli.cmd_prompt_promote(root, "weekly-project-status", "v2")
        self.assertIn("eval-ok", str(caught.exception))
        recorded = evals / "results/eval-ok.json"
        recorded.parent.mkdir()
        recorded.write_text(json.dumps({
            "verdict": "pass", "prompt_version": "v1",
        }), encoding="utf-8")
        with self.assertRaises(SystemExit):
            cli.cmd_prompt_promote(root, "weekly-project-status", "v2")
        recorded.write_text(json.dumps({
            "verdict": "pass", "prompt_version": "v2",
        }), encoding="utf-8")
        self.assertEqual(cli.cmd_prompt_promote(root, "weekly-project-status", "v2"), 0)
        self.assertEqual(models.promotion_blockers(root, "weekly-project-status", "v2"), [])
