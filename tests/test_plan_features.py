"""The remaining plan items that fit the locked decisions."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from ctx import cli, config, db, factory, frontmatter, ui
from ctx.schedule import install, show
from ctx.inbox_import import import_file
from ctx.scaffold import ScaffoldError, scaffold


class MaintenanceTest(unittest.TestCase):
    def test_assembly_flags_problems_and_does_not_edit_them(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        prompt = root / "factories/context-maintenance/prompts"
        prompt.mkdir(parents=True)
        (root / "factories/context-maintenance/FACTORY.md").write_text("# F\n", encoding="utf-8")
        (prompt / "v1.md").write_text("Draft a triage note.\n", encoding="utf-8")
        (root / "inbox").mkdir()
        (root / "inbox/README.md").write_text("# Inbox\n", encoding="utf-8")
        note = root / "inbox/waiting.md"
        note.write_text("# Waiting\n", encoding="utf-8")
        old = (date.today() - timedelta(days=40)).isoformat()
        task = {"id": "task-old", "type": "task", "title": "Old",
                "created": old, "updated": old, "status": "to-do",
                "project": "project-missing"}
        folder = root / "context/tasks"
        folder.mkdir(parents=True)
        path = folder / "old.md"
        path.write_text(frontmatter.dumps(task, "# Old\n"), encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        db.init_db(root)
        info = factory.assemble_maintenance(root)
        self.assertEqual(info["counts"], {"inbox": 1, "broken": 1, "stale": 1, "duplicates": 0})
        bundle = (root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("project-missing", bundle)
        self.assertIn("waiting.md", bundle)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertTrue(note.is_file())
        self.assertIn("did not edit", bundle)
        self.assertIn("## Duplicates", bundle)


    def test_two_titles_are_flagged_as_duplicates(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        prompt = root / "factories/context-maintenance/prompts"
        prompt.mkdir(parents=True)
        (root / "factories/context-maintenance/FACTORY.md").write_text("# F\n", encoding="utf-8")
        (prompt / "v1.md").write_text("Draft.\n", encoding="utf-8")
        folder = root / "context/tasks"
        folder.mkdir(parents=True)
        for name, task_id in (("one", "task-dup"), ("two", "task-dup-2")):
            meta = {"id": task_id, "type": "task", "title": "Same title",
                    "created": "2026-11-21", "updated": "2026-11-21", "status": "to-do"}
            (folder / f"{name}.md").write_text(
                frontmatter.dumps(meta, "# Same title\n"), encoding="utf-8")
        db.init_db(root)
        info = factory.assemble_maintenance(root)
        self.assertEqual(info["counts"]["duplicates"], 1)
        bundle = (root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("task-dup", bundle)
        self.assertIn("task-dup-2", bundle)


class ScaffoldAndImportTest(unittest.TestCase):
    def test_scaffold_refuses_to_overwrite(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        folder = scaffold(root, "tidy-notes", "Tidy the notes")
        self.assertTrue((folder / "prompts/v1.md").is_file())
        with self.assertRaises(ScaffoldError):
            scaffold(root, "tidy-notes", "Again")

    def test_import_writes_inbox_and_not_a_contribution(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        eml = Path(tmp.name) / "note.eml"
        eml.write_text(
            "Subject: Ship notes\nFrom: Ada <ada@example.com>\n\nThe notes are ready.\n",
            encoding="utf-8",
        )
        written = import_file(root, str(eml))
        text = (root / "inbox" / written[0]["name"]).read_text(encoding="utf-8")
        self.assertIn("Ship notes", text)
        self.assertIn("The notes are ready.", text)
        self.assertFalse((root / "context/contributions").exists())


class ScheduleAndSyncTest(unittest.TestCase):
    def test_weekly_command_does_not_push_or_merge(self) -> None:
        text = show(Path("C:/notes"))
        self.assertIn("sync github --limit 30 --digest", text)
        self.assertIn("context-maintenance", text)
        self.assertNotIn("factory publish", text)
        self.assertNotIn("factory merge", text)
        calls = []
        install(Path("C:/notes"), runner=lambda argv: calls.append(argv) or "",
                platform="win32")
        self.assertEqual(calls[0][0], "schtasks")
        self.assertNotIn("push", calls[0])
        self.assertNotIn("merge", calls[0])

    def test_install_refuses_a_non_windows_host(self) -> None:
        from ctx.schedule import ScheduleError
        with self.assertRaises(ScheduleError):
            install(Path("C:/notes"), runner=lambda argv: "", platform="linux")

    def test_digest_flag_assembles_only_after_a_change(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        unchanged = {"offline": False, "fetched": 0, "new": 0, "updated": 0,
                     "repos": 0, "contributions": 0}
        with unittest.mock.patch("ctx.sync.sync_github", return_value=unchanged), \
             unittest.mock.patch("ctx.cli.cmd_digest") as digest:
            self.assertEqual(cli.cmd_sync_github(root, digest=True), 0)
            digest.assert_not_called()
        changed = dict(unchanged, new=1)
        with unittest.mock.patch("ctx.sync.sync_github", return_value=changed), \
             unittest.mock.patch("ctx.cli.cmd_digest", return_value=0) as digest:
            self.assertEqual(cli.cmd_sync_github(root, digest=True), 0)
            digest.assert_called_once()


class HookTest(unittest.TestCase):
    def test_webhook_only_captures_when_the_token_matches(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        httpd = ui.make_server(root, "127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(_stop, httpd, thread)
        port = httpd.server_address[1]
        status, _body = _post(port, {"title": "Ping", "body": "hello"})
        self.assertEqual(status, 404)
        token = config.set_hook_token(root)
        status, body = _post(port, {"title": "Ping", "body": "hello"}, token=token)
        self.assertEqual(status, 200, body)
        notes = list((root / "inbox").glob("*.md"))
        self.assertEqual(len(notes), 1)
        self.assertIn("hello", notes[0].read_text(encoding="utf-8"))
        self.assertFalse((root / "context").exists())
        self.assertFalse(db.db_path(root).exists() and _ran(root))


def _ran(root: Path) -> bool:
    if not db.db_path(root).exists():
        return False
    conn = db.connect(root)
    try:
        return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] > 0
    finally:
        conn.close()


def _stop(httpd, thread) -> None:
    httpd.shutdown()
    thread.join(timeout=2)
    httpd.server_close()


def _post(port: int, payload: dict, token: str = "") -> tuple[int, str]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/hook",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
    )
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-Stead-Hook", token)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.status, exc.read().decode("utf-8")
