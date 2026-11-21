"""The remaining plan items that fit the locked decisions."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

from ctx import config, db, factory, frontmatter, ui
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
        self.assertEqual(info["counts"], {"inbox": 1, "broken": 1, "stale": 1})
        bundle = (root / info["run_dir"] / "bundle.md").read_text(encoding="utf-8")
        self.assertIn("project-missing", bundle)
        self.assertIn("waiting.md", bundle)
        self.assertEqual(path.read_text(encoding="utf-8"), before)
        self.assertTrue(note.is_file())
        self.assertIn("did not edit", bundle)


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
