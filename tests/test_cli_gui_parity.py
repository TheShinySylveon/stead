"""Tests for CLI <-> GUI parity, shared handlers, and infra/doc consistency."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch
from pathlib import Path

from ctx import agent, autonomy, cli, commands, db, frontmatter, models, ui, writeback


class CliGuiParityTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        for folder in ("projects", "tasks", "documents", "meetings",
                       "repos", "contributions", "actors"):
            (self.root / "context" / folder).mkdir(parents=True)
        (self.root / "inbox").mkdir()
        db.init_db(self.root)

    def test_inbox_cli_and_ui_share_capture_list_triage_delete(self) -> None:
        self.assertEqual(
            cli.main(["--root", str(self.root), "inbox", "capture",
                      "--title", "Use WAL mode", "--body", "Keeps readers fast."]),
            0,
        )
        items = ui.list_inbox(self.root)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Use WAL mode")
        self.assertEqual(items[0]["kind"], "note")
        name = items[0]["name"]

        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            cli.build_parser().parse_args(["inbox", "triage", name, "--type", "project"])
        self.assertEqual(error.exception.code, 2)

        self.assertEqual(
            cli.main(["--root", str(self.root), "inbox", "triage", name,
                      "--type", "document"]),
            0,
        )
        self.assertEqual(ui.list_inbox(self.root), [])
        docs = list((self.root / "context/documents").glob("*.md"))
        self.assertEqual(len(docs), 1)

        # Capture another and delete via CLI
        self.assertEqual(
            cli.main(["--root", str(self.root), "inbox", "capture",
                      "--title", "Scratch", "--body", "Throwaway"]),
            0,
        )
        name2 = ui.list_inbox(self.root)[0]["name"]
        self.assertEqual(
            cli.main(["--root", str(self.root), "inbox", "delete", name2]),
            0,
        )
        self.assertEqual(ui.list_inbox(self.root), [])

    def test_repo_slug_accepts_github_remotes_and_ignores_other_hosts(self) -> None:
        for url in ("https://github.com/Owner/project-name.git/",
                    "git@github.com:Owner/project-name.git",
                    "ssh://git@github.com/Owner/project-name",
                    "github.com/Owner/project-name"):
            with self.subTest(url=url):
                self.assertEqual(commands._repo_slug("Local Title", url), "owner-project-name")
        for url in ("https://example.com/github.com/owner/repo",
                    "https://github.com.example.com/owner/repo",
                    "https://github.com@example.com/owner/repo",
                    "https://github.com/owner/repo/issues", "https://[invalid"):
            with self.subTest(url=url):
                self.assertEqual(commands._repo_slug("Local Title", url), "local-title")

    def test_improve_edit_cli_matches_ui(self) -> None:
        prop = writeback.propose_improvement(
            self.root, "prompt", "Tighten prompt", "Too verbose", "Old text")
        name = Path(prop["path"]).name
        self.assertEqual(
            cli.main(["--root", str(self.root), "improve", "edit", name,
                      "--change", "New concise text"]),
            0,
        )
        rows = writeback.list_improvements(self.root)
        self.assertEqual(rows[0]["change"], "New concise text")

    def test_run_verdict_cli_and_latest_draft_shared_helper(self) -> None:
        conn = db.connect(self.root)
        try:
            conn.execute(
                "INSERT INTO runs (factory, task_ref, prompt_version, mode, output, verdict, created) "
                "VALUES ('weekly-contribution-digest', 'digest', 'v1', 'shadow', 'Draft text', 'pending', '2026-11-27T00:00:00Z')"
            )
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(
            cli.main(["--root", str(self.root), "run", "verdict",
                      "--run", str(run_id), "--verdict", "approved",
                      "--note", "Looks good"]),
            0,
        )
        output, version = models.latest_draft(self.root, "weekly-contribution-digest")
        self.assertEqual(output, "Draft text")
        self.assertEqual(version, "v1")

    def test_settings_cli_switches_deployment_and_rotates_token(self) -> None:
        self.assertEqual(
            cli.main(["--root", str(self.root), "settings", "deployment", "--mode", "multi"]),
            0,
        )
        first = (self.root / "stead.json").read_text(encoding="utf-8")
        tok1 = json.loads(first)["access_token"]
        self.assertTrue(tok1)
        self.assertEqual(
            cli.main(["--root", str(self.root), "settings", "rotate"]),
            0,
        )
        tok2 = json.loads((self.root / "stead.json").read_text(encoding="utf-8"))["access_token"]
        self.assertNotEqual(tok1, tok2)

    def test_lock_cli_distinguishes_absent_and_live_lock(self) -> None:
        code_tmp = tempfile.TemporaryDirectory()
        self.addCleanup(code_tmp.cleanup)
        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps({
                "id": "repo-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own", "code_path": code_tmp.name,
            }, "# App\n"),
            encoding="utf-8",
        )
        (self.root / "context/contributions/app-issue-1.md").write_text(
            frontmatter.dumps({
                "id": "contribution-app-issue-1", "type": "contribution",
                "title": "Issue", "created": "2026-11-21", "updated": "2026-11-21",
                "repo": "repo-app", "kind": "issue", "number": 1, "state": "open",
            }, "# Issue\n"),
            encoding="utf-8",
        )
        argv = ["--root", str(self.root), "lock", "--contribution", "contribution-app-issue-1"]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(argv), 0)
        self.assertEqual(output.getvalue().strip(), "not locked")

        lock = agent._lock(Path(code_tmp.name))
        self.addCleanup(agent._unlock, lock)
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(argv), 0)
        self.assertIn(f"locked pid={os.getpid()}", output.getvalue())
        self.assertIn("stale=False", output.getvalue())

    def test_ui_model_pricing_and_repo_safety_fields_and_autonomy_index_sync(self) -> None:
        status, body, _ct = ui.dispatch(self.root, "POST", "/api/model", {}, {
            "provider": "openai", "name": "gpt-4.1-mini",
            "input_price": 0.4, "output_price": 1.6, "api_key_env": "CUSTOM_KEY",
        }, token_ok=True)
        self.assertEqual(status, 200, body)
        shown = models.public_model(self.root)
        self.assertEqual(shown["input_price_per_mtok"], 0.4)
        self.assertEqual(shown["output_price_per_mtok"], 1.6)
        self.assertEqual(shown["key_env"], "CUSTOM_KEY")

        (self.root / "context/repos/app.md").write_text(
            frontmatter.dumps({
                "id": "repo-app", "type": "repo", "title": "App",
                "created": "2026-11-21", "updated": "2026-11-21",
                "status": "active", "kind": "own",
            }, "# App\n"),
            encoding="utf-8",
        )
        # CLI autonomy.set_repo updates state.db index too
        autonomy.set_repo(self.root, "repo-app", reach="pr")
        conn = db.connect(self.root)
        try:
            row = conn.execute("SELECT id FROM repos WHERE id = 'repo-app'").fetchone()
            self.assertIsNotNone(row)
        finally:
            conn.close()

        # Cockpit /api/repo accepts safety/execution fields locally
        status, body, _ct = ui.dispatch(self.root, "POST", "/api/repo", {}, {
            "id": "repo-app", "checks": "pytest -q", "checks_isolation": "docker",
            "checks_image": "python:3.12-slim", "allow_comment": True,
            "protected_paths": "Makefile,pyproject.toml",
        }, token_ok=True)
        self.assertEqual(status, 200, body)
        _p, meta, _b = __import__("ctx").objects.find(self.root, "repo", "repo-app")
        self.assertEqual(meta["checks"], "pytest -q")
        self.assertEqual(meta["checks_isolation"], "docker")
        self.assertEqual(meta["allow_comment"], "true")
        self.assertEqual(meta["protected_paths"], ["Makefile", "pyproject.toml"])
        repo, = ui.snapshot(self.root)["repos"]
        self.assertEqual(repo["checks_isolation"], "docker")
        self.assertEqual(repo["protected_paths"], ["Makefile", "pyproject.toml"])
        self.assertIs(repo["allow_comment"], True)

        with patch("ctx.ui.shared_server", return_value=True):
            snapshot = ui.snapshot(self.root)
            self.assertTrue(snapshot["shared_server"])
            shared_repo, = snapshot["repos"]
            self.assertNotIn("checks", shared_repo)
            with self.assertRaisesRegex(ui.UiError, "read-only"):
                ui.set_repo(self.root, "repo-app", {"checks_isolation": "host"})

    def test_cockpit_html_exposes_parity_controls(self) -> None:
        html = ui.PAGE_PATH.read_text(encoding="utf-8")
        for needle in (
            "data-set-contrib",
            "data-init-reset",
            'name="input_price"',
            'name="output_price"',
            'name="max_builds_per_day"',
            'name="max_tokens_per_build"',
            'name="max_cost_per_build_usd"',
            'id="metrics-repo"',
            'id="metrics-since"',
            'data-action="redraft"',
            "data-draft-all",
            '"/api/spec/draft-all"',
            'select("checks_isolation",',
            'input("protected_paths",',
        ):
            self.assertIn(needle, html, needle)


if __name__ == "__main__":
    unittest.main()
